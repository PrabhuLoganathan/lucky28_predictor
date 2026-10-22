"""Authoritative completed history shared by timeline, palette and Live Gaps."""
from django.db.models import Q
from django.urls import reverse

from games.group_config import GROUP_BY_NUMBER
from .group_absence import stream_games, sequence_id


def completed_history(key='lucky28'):
    games = list(stream_games(key).filter(has_winner=True, winning_number__range=(0, 27),
        winner_event_ts__isnull=False).filter(Q(status__isnull=True) | Q(status__in=(3, 4)))
        .only('game_no', 'winning_number', 'winner_event_ts').order_by('-winner_event_ts', '-pk'))
    # Numeric round order also handles late packets and daily numeric ID rollover.
    sequences = [sequence_id(game.game_no) for game in games]
    if sequences and all(sequences) and len({s[0] for s in sequences}) == 1:
        games.sort(key=lambda game: (sequence_id(game.game_no)[1], game.pk), reverse=True)
    return games


def number_statistics(games):
    positions = [[] for _ in range(28)]
    for index, game in enumerate(games):
        positions[game.winning_number].append(index)
    stats = []
    for number, indexes in enumerate(positions):
        gaps = [older-newer-1 for newer, older in zip(indexes, indexes[1:])]
        last = games[indexes[0]] if indexes else None
        group = GROUP_BY_NUMBER[number]
        stats.append(dict(number=number, hits=sum(i < 10 for i in indexes), total_hits=len(indexes),
            current_gap=indexes[0] if indexes else (len(games) if games else None),
            gap_lower_bound=not bool(indexes), max_gap=max(gaps) if gaps else None,
            average_gap=round(sum(gaps)/len(gaps), 1) if gaps else None,
            latest_appearance=dict(game_no=last.game_no, timestamp=last.winner_event_ts.isoformat(),
                                   url=reverse('game_detail', args=[last.game_no])) if last else None,
            color=group.name, display_color=group.color,
            size='Big' if number >= 14 else 'Small', parity='Even' if number % 2 == 0 else 'Odd'))
    return stats


def latest_completed_unavailable(games, key):
    """An active pending round is normal; a newer finished round without a result is not."""
    invalid = stream_games(key).filter(status__in=(3, 4)).exclude(
        has_winner=True, winning_number__range=(0, 27), winner_event_ts__isnull=False)
    if not games:
        return invalid.exists()
    latest = games[0]
    latest_sequence = sequence_id(latest.game_no)
    for game in invalid.only('game_no', 'winner_event_ts'):
        candidate = sequence_id(game.game_no)
        if candidate and latest_sequence and candidate[0] == latest_sequence[0]:
            if candidate[1] > latest_sequence[1]:
                return True
        elif game.winner_event_ts and game.winner_event_ts > latest.winner_event_ts:
            return True
    return False
