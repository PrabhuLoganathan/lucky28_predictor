"""Latest-ten drought/repeat alerts, isolated from lifetime group absences.

Continuity is required only for the relevant window. Older gaps do not poison a
new complete ten-round window. Startup and corrections evaluate current evidence
once; events and their delivery keys survive repeats, refreshes and restarts.
"""
import hashlib
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from games.models import (GameRound, GroupAbsenceStream, GroupDataIssue, WindowAlertState,
                          WindowAlertEvent, AlertDelivery)
from .group_absence import locked_stream, stream_games, sequence_id, valid_result, display_time
from .repetition import WINDOW_SIZE, summarize_window
from .alerts import eligible_destinations, queue_delivery
from .alert_settings import get_config


def result_evidence(game):
    return dict(round_id=game.game_no, number=game.winning_number, timestamp=display_time(game.winner_event_ts))


def current_window(key):
    games = list(stream_games(key).only('game_no', 'has_winner', 'winning_number', 'status',
                                       'winner_event_ts', 'pre_event_ts', 'created_at'))
    # The current round is selected by event time, as on the analysis screen.
    completed = [game for game in games if game.has_winner and game.winner_event_ts]
    if not completed:
        return dict(status='Waiting for 10 results', reason='No completed results available.', results=[])
    latest = max(completed, key=lambda game: (game.winner_event_ts, game.pk))
    sequence = sequence_id(latest.game_no)
    if not sequence:
        return dict(status='Data incomplete', reason='The latest round ID has no numeric sequence.', results=[])
    prefix, end = sequence
    by_sequence = {}
    for game in games:
        item = sequence_id(game.game_no)
        if item and item[0] == prefix and item[1] > end and game.has_winner and not valid_result(game):
            return dict(status='Data incomplete', reason=f'Round {game.game_no} has an invalid or missing completed result.', results=[])
        if item and item[0] == prefix and item[1] <= end:
            if item[1] in by_sequence:
                return dict(status='Data incomplete', reason='Ambiguous round IDs share the same sequence number.', results=[])
            by_sequence[item[1]] = game
    # Walk the uninterrupted suffix to identify the current all-different period.
    suffix = []
    index = end
    while index in by_sequence and valid_result(by_sequence[index]):
        suffix.append(by_sequence[index])
        index -= 1
    suffix.reverse()
    results = [result_evidence(game) for game in suffix[-WINDOW_SIZE:]]
    if len(suffix) < WINDOW_SIZE:
        # Fewer than ten at the beginning of available history is a warm-up, not a gap.
        older = any(number <= index for number in by_sequence)
        return dict(status='Data incomplete' if older else 'Waiting for 10 results',
                    reason='Need 10 consecutive valid completed rounds; a missing or invalid round cannot be skipped.',
                    results=results)
    for issue in GroupDataIssue.objects.filter(stream_id=key):
        item = sequence_id(issue.round_id)
        if item and item[0] == prefix and item[1] >= end - WINDOW_SIZE + 1:
            saved = by_sequence.get(item[1])
            if not saved or not valid_result(saved):
                return dict(status='Data incomplete', reason=f'Round {issue.round_id}: {issue.reason}', results=results)
    summary = summarize_window([result['number'] for result in results])
    # One drought alert per uninterrupted run of all-different windows.
    drought_start = len(suffix) - WINDOW_SIZE
    if not summary['has_repetition']:
        while drought_start > 0:
            previous = suffix[drought_start - 1:drought_start - 1 + WINDOW_SIZE]
            if summarize_window([game.winning_number for game in previous])['has_repetition']:
                break
            drought_start -= 1
    return dict(summary, status='Repeat' if summary['has_repetition'] else 'Drought', reason='',
                results=results, start_round=results[0]['round_id'], end_round=results[-1]['round_id'],
                drought_start_round=suffix[drought_start + WINDOW_SIZE - 1].game_no,
                drought_period_rounds=[game.game_no for game in suffix[drought_start + WINDOW_SIZE - 1:]])


def event_snapshot(key, kind, window):
    from .card_timeline import snapshot_for_round
    path = reverse('game_detail', args=[window['end_round']])
    base = getattr(settings, 'ALERT_PUBLIC_BASE_URL', '').rstrip('/')
    url = urlsplit(base)
    # Period membership is internal reconciliation state, not notification content.
    snapshot = {name: value for name, value in window.items() if name != 'drought_period_rounds'}
    snapshot.update(stream=key, kind=kind, game_no=window['end_round'], captured_at=display_time(timezone.now()),
                    global_timeline=snapshot_for_round(key, window['end_round']),
                    matches=[], details_path=path,
                    details_url=base + path if url.scheme in ('http', 'https') and url.netloc else '')
    return snapshot


def snapshot_valid(event):
    expected = event.snapshot['results']
    games = {game.game_no: game for game in stream_games(event.stream_id).filter(game_no__in=[r['round_id'] for r in expected])}
    return all(row['round_id'] in games and valid_result(games[row['round_id']])
               and games[row['round_id']].winning_number == row['number'] for row in expected)


def cancel_event(event, reason):
    if not event.invalidated_at:
        event.invalidated_at = timezone.now()
        event.save(update_fields=['invalidated_at'])
    AlertDelivery.objects.filter(kind='window', payload__event_id=event.pk,
                                 status__in=['pending', 'failed']).update(status='cancelled', error=reason)


@transaction.atomic
def synchronize(key='lucky28', evaluate_current=True):
    stream = locked_stream(key)
    state, _ = WindowAlertState.objects.get_or_create(stream=stream)
    window = current_window(key)
    state.snapshot, state.updated_at = window, timezone.now()
    state.save(update_fields=['snapshot', 'updated_at'])
    # Only queued events need revalidation on every read. Sent evidence is retained.
    pending_ids = AlertDelivery.objects.filter(kind='window', status__in=['pending', 'failed'],
        payload__stream=key).values_list('payload__event_id', flat=True)
    for event in WindowAlertEvent.objects.filter(pk__in=pending_ids, invalidated_at__isnull=True):
        if not snapshot_valid(event):
            cancel_event(event, 'Window evidence changed after a corrected or deleted result.')
        elif event.kind == 'drought' and window['status'] == 'Repeat':
            cancel_event(event, 'A repeat ended this drought before delivery.')
    if not evaluate_current or window['status'] not in ('Drought', 'Repeat'):
        return state
    kind = ('drought' if window['status'] == 'Drought' and state.drought_enabled else
            'repeat' if window['newest_repeats'] and state.repeat_enabled else None)
    if not kind:
        return state
    anchor = window['drought_start_round'] if kind == 'drought' else window['end_round']
    occurrence = hashlib.sha256(f'{key}:{kind}:{anchor}'.encode()).hexdigest()
    event = None
    if kind == 'drought':
        # A late correction can change the start of a period without making a
        # previously notified current period new. Keep that notification marker.
        period_rounds = set(window['drought_period_rounds'])
        event = next((item for item in WindowAlertEvent.objects.filter(stream=stream, kind=kind).order_by('pk')
                      if item.snapshot['end_round'] in period_rounds), None)
    if event is None:
        event, _ = WindowAlertEvent.objects.get_or_create(stream=stream, kind=kind, occurrence_key=occurrence,
            defaults={'snapshot': event_snapshot(key, kind, window)})
    if not event.invalidated_at:
        for destination in eligible_destinations(timezone.now()):
            queue_delivery(f'window:{event.pk}:{destination.pk}', destination, 'window', dict(event.snapshot, event_id=event.pk))
    return state


@transaction.atomic
def save_settings(key, drought_enabled, repeat_enabled):
    stream = locked_stream(key)
    state, _ = WindowAlertState.objects.get_or_create(stream=stream)
    state.drought_enabled, state.repeat_enabled = drought_enabled, repeat_enabled
    state.save(update_fields=['drought_enabled', 'repeat_enabled'])
    return synchronize(key)


def synchronize_all():
    keys = set(GroupAbsenceStream.objects.values_list('key', flat=True))
    keys.update(key or 'lucky28' for key in GameRound.objects.values_list('game_type', flat=True).distinct())
    for key in sorted(keys):
        synchronize(key)


def delivery_gate(payload):
    event = WindowAlertEvent.objects.filter(pk=payload.get('event_id')).first()
    if not event or event.invalidated_at:
        return 'cancelled'
    if (timezone.now() - event.created_at).total_seconds() > get_config().max_event_age_seconds:
        return 'cancelled'
    if not snapshot_valid(event):
        cancel_event(event, 'Window evidence changed after a corrected or deleted result.')
        return 'cancelled'
    state = WindowAlertState.objects.get(stream_id=event.stream_id)
    if not getattr(state, f'{event.kind}_enabled'):
        return 'pending'
    current = current_window(event.stream_id)
    if current['status'] not in ('Drought', 'Repeat'):
        return 'pending'
    if event.kind == 'drought' and (current['status'] != 'Drought' or event.snapshot['end_round'] not in current['drought_period_rounds']):
        return 'cancelled'
    return 'ready'
