"""Capture global timeline evidence before rendering; never query from a card."""
from django.db.models import Q

from .group_absence import stream_games, valid_result
from .timeline import LIMIT, TRACKS, adjacent, classify, new_repeat_history


def snapshot_from_games(games):
    from .card_gaps import capture_gaps
    history = [game for game in games if valid_result(game)]
    games = history[:LIMIT + 9]
    visible = games[:LIMIT]
    tags = new_repeat_history(history)
    keys = ('number', 'size', 'parity', 'combo', 'color', 'row', 'column', 'extreme', 'border', 'repeat', 'window')
    return dict(version=3, limit=LIMIT, latest_game_id=visible[0].game_no if visible else None,
        gap_analytics=capture_gaps(history),
        games=[dict(game_no=g.game_no, number=g.winning_number, timestamp=g.winner_event_ts.isoformat(),
                    new_repeat=tags[i], gap_before=i + 1 < len(games) and not adjacent(g, games[i + 1])) for i, g in enumerate(visible)],
        tracks={key: dict(title=TRACKS[key][0], legend=TRACKS[key][1],
                         letters=[classify(key, games, i) for i in range(len(visible))]) for key in keys})


def snapshot_for_round(key, game_no):
    query = stream_games(key)
    anchor = query.filter(game_no=game_no).first()
    if not anchor or not anchor.winner_event_ts:
        return snapshot_from_games([])
    games = query.filter(Q(winner_event_ts__lt=anchor.winner_event_ts) |
                         Q(winner_event_ts=anchor.winner_event_ts, pk__lte=anchor.pk))
    games = games.filter(has_winner=True, winning_number__range=(0, 27)).filter(
        Q(status__isnull=True) | Q(status__in=(3, 4)))
    return snapshot_from_games(list(games.only('game_no', 'winning_number', 'winner_event_ts',
        'has_winner', 'status').order_by('-winner_event_ts', '-pk')))
