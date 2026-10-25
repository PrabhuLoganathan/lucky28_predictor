"""Read-only group absence statistics from the shared completed result history."""
from django.urls import reverse

from games.category_config import ROW_GROUPS, COLUMN_GROUPS, COMBO_GROUPS
from games.group_config import COLOR_GROUPS
from .group_absence import sequence_id


def definitions():
    groups = []

    def add(key, label, family, numbers, color='#b59cfa', filter_key=None, filter_value=None):
        groups.append(dict(key=key, label=label, family=family, numbers=list(numbers), color=color,
                           filter_key=filter_key, filter_value=filter_value))

    for family, items, field in [('Rows', ROW_GROUPS, 'row'), ('Columns', COLUMN_GROUPS, 'column')]:
        for group in items:
            add(group.id, group.name, family, group.numbers, filter_key=field, filter_value=group.name)
    for key, label, numbers in [('S', 'Small', range(14)), ('B', 'Big', range(14, 28)),
                                ('E', 'Even', range(0, 28, 2)), ('O', 'Odd', range(1, 28, 2))]:
        add(key, label, 'Size' if key in ('S', 'B') else 'Parity', numbers,
            filter_key='category', filter_value=key)
    for group in COMBO_GROUPS:
        add(group.id, group.name, 'Combos', group.numbers, filter_key='category', filter_value=group.id)
    for group in COLOR_GROUPS:
        add(group.id, group.name, 'Colors', group.numbers, group.color, 'color', group.name)
    add('edges', 'Edges', 'Range', (*range(6), *range(22, 28)), '#fbbf24', 'range', 'Edges · 0–5, 22–27')
    add('middle', 'Middle', 'Range', range(6, 22), '#94a3b8', 'range', 'Middle · 6–21')
    return groups


def group_statistics(games, latest_available=True, groups=None):
    """Newest first; zero means a hit now, consecutive hits produce a zero gap.

    Unverified boundaries do not become invented misses. Their observed counts
    remain inspectable, but are excluded from exact completed-gap averages/maxima.
    """
    boundaries = [0]
    for newer, older in zip(games, games[1:]):
        a, b = sequence_id(newer.game_no), sequence_id(older.game_no)
        verified = bool(a and b and a[0] == b[0] and a[1] == b[1] + 1)
        boundaries.append(boundaries[-1] + int(not verified))

    def appearance(index):
        game = games[index]
        return dict(game_no=game.game_no, timestamp=game.winner_event_ts.isoformat(),
                    url=reverse('game_detail', args=[game.game_no]))

    output = []
    for definition in definitions() if groups is None else groups:
        members = set(definition['numbers'])
        positions = [i for i, game in enumerate(games) if game.winning_number in members]
        intervals = [(newer, older, older-newer-1, boundaries[older] != boundaries[newer])
                     for newer, older in zip(positions, positions[1:])]
        exact = [gap for _, _, gap, interrupted in intervals if not interrupted]
        last_index = positions[0] if positions else len(games)-1
        streak, streak_incomplete, streak_lower_bound = 0, False, False
        for index, game in enumerate(games):
            if index and boundaries[index] != boundaries[index-1]:
                streak_incomplete = True
                break
            if game.winning_number not in members:
                break
            streak += 1
        else:
            streak_lower_bound = bool(games)
        output.append(dict(**definition,
            current_streak=streak if games and latest_available else None,
            streak_incomplete=streak_incomplete if latest_available else False,
            streak_lower_bound=streak_lower_bound if latest_available else False,
            current_gap=positions[0] if positions else (len(games) if games else None),
            gap_lower_bound=bool(games) and not positions,
            current_incomplete=bool(games) and boundaries[last_index] > 0,
            total_hits=len(positions), recent_hits=sum(i < 10 for i in positions),
            latest_appearance=appearance(positions[0]) if positions else None,
            average_gap=round(sum(exact)/len(exact), 1) if exact else None,
            max_gap=max(exact) if exact else None, completed_gap_count=len(intervals),
            exact_gap_count=len(exact),
            history=[dict(gap=gap, incomplete=interrupted, start=appearance(older), end=appearance(newer))
                     for newer, older, gap, interrupted in intervals[:30]]))
    return output
