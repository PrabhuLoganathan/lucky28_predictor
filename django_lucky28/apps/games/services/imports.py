"""Append dated CSV history without replacing other days or sending live alerts."""

import csv
from datetime import timezone as datetime_timezone
from io import StringIO

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from games.models import GameRound
from games.services.analysis import AnalysisService


def _integer(value, label, maximum=None):
    try:
        number = int(value.replace(',', ''))
    except ValueError as error:
        raise ValueError(f'{label} must be a whole number.') from error
    if number < 0 or (maximum is not None and number > maximum):
        raise ValueError(f'{label} is outside the allowed range.')
    return number


@transaction.atomic
def import_history(files):
    summary = {'created': 0, 'updated': 0, 'unchanged': 0, 'dates': set()}
    total_rows = 0
    for upload in files:
        if not upload.name.lower().endswith('.csv'):
            raise ValueError('Please upload CSV files only.')
        reader = csv.DictReader(StringIO(upload.read().decode('utf-8-sig')))
        headers = {name.strip().lower() for name in (reader.fieldnames or [])}
        if not headers.intersection({'result', 'winning_number', 'number'}):
            raise ValueError(f'{upload.name}: a result column is required.')
        if not headers.intersection({'timestamp', 'time'}):
            raise ValueError(f'{upload.name}: a timestamp column is required to store results by day.')

        for raw_row in reader:
            try:
                if None in raw_row:
                    raise ValueError('Too many columns; quote values that contain commas.')
                row = {key.strip().lower(): (value or '').strip() for key, value in raw_row.items()}
                if not any(row.values()):
                    continue
                number = _integer(row.get('result') or row.get('winning_number') or row.get('number', ''), 'Result', 27)
                timestamp = parse_datetime(row.get('timestamp') or row.get('time', ''))
                if timestamp is None:
                    raise ValueError('A valid timestamp with its date is required for every result.')
                if timezone.is_naive(timestamp):
                    timestamp = timezone.make_aware(timestamp)
                game_no = row.get('issue') or row.get('game_no') or row.get('game no')
                if game_no and len(game_no) > 32:
                    raise ValueError('Game No cannot exceed 32 characters.')

                defaults = {
                    'winning_number': number,
                    'has_winner': True,
                    'winner_event_ts': timestamp,
                    'winner_color': AnalysisService.get_color(number),
                }
                for column, field, label in (
                    ('winners_count', 'winner_count', 'Winners'),
                    ('prize_amount', 'win_total_energy', 'Prizes'),
                ):
                    if row.get(column):
                        defaults[field] = _integer(row[column], label, 9223372036854775807)

                if game_no:
                    game = GameRound.objects.filter(game_no=game_no).first()
                else:
                    # Recognize previous exports, including the old minute-based IDs.
                    game = GameRound.objects.filter(
                        winner_event_ts=timestamp, winning_number=number,
                    ).order_by('id').first()
                    if game is None and GameRound.objects.filter(winner_event_ts=timestamp).exists():
                        raise ValueError(
                            'A different result is already saved at this timestamp. '
                            'Check the result, or supply a unique game_no if these are separate games.'
                        )
                    utc_timestamp = timestamp.astimezone(datetime_timezone.utc)
                    game_no = f'{utc_timestamp:%Y%m%d%H%M%S%f}-{number}'

                if game is None:
                    GameRound.objects.create(game_no=game_no, **defaults)
                    summary['created'] += 1
                else:
                    changed = []
                    for field, value in defaults.items():
                        existing = getattr(game, field)
                        if field == 'has_winner':
                            if not existing:
                                game.has_winner = True
                                changed.append(field)
                        elif existing is None or existing == '':
                            setattr(game, field, value)
                            changed.append(field)
                        elif field != 'winner_color' and existing != value:
                            raise ValueError(f'Game {game.game_no} conflicts with a saved result; check its timestamp and details.')
                    if changed:
                        game.save(update_fields=changed + ['updated_at'])
                        summary['updated'] += 1
                    else:
                        summary['unchanged'] += 1
                summary['dates'].add(timezone.localtime(timestamp).date())
                total_rows += 1
            except (ValueError, TypeError) as error:
                raise ValueError(f'{upload.name}, row {reader.line_num}: {error}') from error
    if total_rows == 0:
        raise ValueError('The uploaded files contain no results.')
    return summary
