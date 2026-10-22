"""Read-only, shared 150-result timeline. No evaluation or delivery side effects."""
from collections import Counter, defaultdict
from itertools import takewhile

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from games.group_config import COLOR_GROUPS, GROUP_BY_NUMBER
from games.category_config import ROW_GROUPS, COLUMN_GROUPS, COMBO_GROUPS
from games.models import (AlertOccurrence, GroupAbsenceEvent, CategoryAlertEvent,
                          WindowAlertEvent, GroupAbsenceStream, GameRound, SignalLog)
from .group_absence import stream_games, sequence_id

LIMIT = 150
UNKNOWN = ('?', 'Insufficient continuous history', '#94a3b8')
PALETTE = ('#38bdf8', '#a78bfa', '#34d399', '#fbbf24', '#fb923c', '#f472b6', '#94a3b8')


def states(*items):
    return [dict(letter=letter, label=label, color=color) for letter, label, color in items]


TRACKS = {
    'number': ('Winning numbers', states(*[(str(n), str(n), GROUP_BY_NUMBER[n].color) for n in range(28)])),
    'size': ('Size', states(('B', 'Big · 14–27', '#34d399'), ('S', 'Small · 0–13', '#38bdf8'))),
    'parity': ('Parity', states(('E', 'Even', '#a78bfa'), ('O', 'Odd', '#fb923c'))),
    'combo': ('Size / parity', states(*[(g.id, g.name, PALETTE[i]) for i, g in enumerate(COMBO_GROUPS)])),
    'color': ('Color groups', states(*[(f'G{i+1}', f'{g.name} · {", ".join(map(str, g.numbers))}', g.color) for i, g in enumerate(COLOR_GROUPS)])),
    'row': ('Board rows', states(*[(f'R{i+1}', f'{g.name} · {", ".join(map(str, g.numbers))}', PALETTE[i]) for i, g in enumerate(ROW_GROUPS)])),
    'column': ('Board columns', states(*[(f'C{i+1}', f'{g.name} · {", ".join(map(str, g.numbers))}', PALETTE[i]) for i, g in enumerate(COLUMN_GROUPS)])),
    'extreme': ('Extreme numbers', states(('J', 'Edges · 0–5, 22–27', '#fbbf24'), ('M', 'Middle · 6–21', '#94a3b8'))),
    'repeat': ('Repeat in previous 2', states(('R', 'Same number as either previous 2 games', '#34d399'), ('N', 'Different from both previous games', '#38bdf8'), UNKNOWN)),
    'window': ('10-game repeat / drought', states(('R', 'A number repeats in this 10-game window', '#34d399'), ('D', 'All 10 numbers are different', '#fbbf24'), UNKNOWN)),
    'alerts': ('Recorded alerts', states(('A', 'Recorded alert or condition ended', '#f472b6'), ('·', 'No recorded alert', '#64748b'))),
}


def recent_games(key):
    # Match the analysis page's event-time ordering, not lexicographic round IDs.
    return list(stream_games(key).filter(has_winner=True, winning_number__range=(0, 27),
        winner_event_ts__isnull=False).filter(Q(status__isnull=True) | Q(status__in=(3, 4)))
        .only('game_no', 'winning_number', 'winner_event_ts').order_by('-winner_event_ts', '-pk')[:LIMIT + 9])


def watermark(game):
    return [game.winner_event_ts.isoformat(), game.pk]


def adjacent(newer, older):
    a, b = sequence_id(newer.game_no), sequence_id(older.game_no)
    return bool(a and b and a[0] == b[0] and a[1] == b[1] + 1)


def recorded_alerts(key, games):
    """Only saved evidence; absence of evidence is never interpreted as success."""
    ids = [g.game_no for g in games]
    output = defaultdict(list)

    def add(game_no, title, detail, url):
        output[game_no].append(dict(title=title, detail=detail, url=url))

    for event in AlertOccurrence.objects.filter(evaluation__game_no__in=ids).select_related('evaluation'):
        snapshot = event.snapshot
        add(event.evaluation.game_no, snapshot.get('title', event.rule_key), snapshot.get('detail', ''),
            reverse('alert_evidence_detail', args=[event.evaluation_id]))
    for event in GroupAbsenceEvent.objects.filter(stream_id=key, snapshot__evaluated_round__in=ids):
        snapshot = event.snapshot
        add(snapshot['evaluated_round'], f'{snapshot.get("color", event.group_id)} absence',
            f'Recorded count: {snapshot.get("count", snapshot.get("absence", "—"))}', reverse('group_absence_dashboard'))
    for event in CategoryAlertEvent.objects.filter(rule__settings_id=key).filter(
            Q(snapshot__evaluated_round__in=ids) | Q(resolution_snapshot__evaluated_round__in=ids)):
        for snapshot, ended in ((event.snapshot, False), (event.resolution_snapshot, True)):
            game_no = snapshot.get('evaluated_round')
            if game_no in ids:
                add(game_no, f'{snapshot.get("group_name", "Category")} {snapshot.get("mode", "")}'+(' ended' if ended else ''),
                    f'Recorded count: {snapshot.get("count", "—")}', reverse('category_alerts'))
    for event in WindowAlertEvent.objects.filter(stream_id=key, snapshot__end_round__in=ids, invalidated_at__isnull=True):
        add(event.snapshot['end_round'], f'10-game {event.kind}', event.snapshot.get('repeated_details', ''), reverse('window_alerts'))
    for event in SignalLog.objects.filter(game__game_no__in=ids).select_related('game', 'rule'):
        add(event.game.game_no, event.rule.name, f'Recorded signal count: {event.value}', reverse('signals_dashboard'))
    return output


def classify(key, games, index):
    n = games[index].winning_number
    if key == 'number': return str(n)
    if key == 'size': return 'B' if n >= 14 else 'S'
    if key == 'parity': return 'E' if n % 2 == 0 else 'O'
    if key == 'combo': return ('B' if n >= 14 else 'S') + ('E' if n % 2 == 0 else 'O')
    if key == 'color': return f'G{int(GROUP_BY_NUMBER[n].id[1:])}'
    if key == 'row': return f'R{n // 7 + 1}'
    if key == 'column': return f'C{n % 7 + 1}'
    if key == 'extreme': return 'J' if n <= 5 or n >= 22 else 'M'
    needed = 3 if key == 'repeat' else 10
    window = games[index:index + needed]
    if len(window) < needed or not all(adjacent(a, b) for a, b in zip(window, window[1:])):
        return '?'
    if key == 'repeat': return 'R' if n in [g.winning_number for g in window[1:]] else 'N'
    return 'R' if len({g.winning_number for g in window}) < 10 else 'D'


def patterns(items, legend):
    # Stop at gaps and unknown states; do not infer streaks across missing rounds.
    letters = []
    for item in items:
        if item['letter'] == '?': break
        letters.append(item['letter'])
        if item['gap_before']: break
    if not letters: return []
    labels = {s['letter']: s['label'].split(' · ')[0] for s in legend}
    events = []
    def add(kind, title, detail):
        events.append(dict(id=f'{kind}-{len(events)}', title=title, desc=detail, level='info'))
    run = len(list(takewhile(lambda x: x == letters[0], letters)))
    if run >= 4:
        add('streak', f'{labels[letters[0]]}: {run} in a row', 'Consecutive observed results in this timeline.')
    threshold = 6 if len(labels.keys() - {'?'}) == 2 else 12
    for letter, label in labels.items():
        if letter == '?': continue
        absence = next((i for i, value in enumerate(letters) if value == letter), len(letters))
        if absence >= threshold:
            add('absence', f'{label}: absent for {absence}{"+" if absence == len(letters) else ""}', 'Completed games since the last observed appearance.')
    if len(letters) >= 10:
        for letter, count in Counter(letters[:10]).items():
            if count >= 7:
                add('density', f'{labels[letter]}: {count} of last 10', 'High concentration in the latest 10 observed results.')
    if len(letters) >= 4 and letters[0] != letters[1] and letters[0] == letters[2] and letters[1] == letters[3]:
        add('alternating', 'Alternating last 4 games', 'Two outcomes alternate in the latest four results.')
    return events


def build_timeline(key, enabled=None, cutoffs=None):
    from .number_history import completed_history, number_statistics, latest_completed_unavailable
    from .group_history import group_statistics
    enabled = list(TRACKS) if enabled is None else enabled
    cutoffs = cutoffs or {}
    games = completed_history(key)
    latest_unavailable = latest_completed_unavailable(games, key)
    visible = games[:LIMIT]
    evidence = recorded_alerts(key, visible) if 'alerts' in enabled else {}
    rows = []
    for index, game in enumerate(visible):
        rows.append(dict(game_no=game.game_no, number=game.winning_number,
            timestamp=game.winner_event_ts.isoformat(), url=reverse('game_detail', args=[game.game_no]),
            gap_before=index + 1 < len(games) and not adjacent(game, games[index + 1]),
            alerts=evidence.get(game.game_no, [])))
    tracks = []
    for track_key in enabled:
        title, legend = TRACKS[track_key]
        cutoff = cutoffs.get(track_key)
        items = []
        for index, game in enumerate(visible):
            if cutoff and watermark(game) <= cutoff: continue
            letter = ('A' if evidence.get(game.game_no) else '·') if track_key == 'alerts' else classify(track_key, games, index)
            items.append(dict(game_no=game.game_no, letter=letter, gap_before=rows[index]['gap_before']))
        tracks.append(dict(tracker_key=track_key, display_name=title, timeline=items, legend=legend,
            reset=bool(cutoff), active_events=patterns(items, legend) if track_key not in ('number', 'alerts') else []))
    return dict(limit=LIMIT, stream=key, latest_game_id=visible[0].game_no if visible else None,
        checked_at=timezone.now().isoformat(), games=rows, tracks=tracks,
        has_gaps=any(row['gap_before'] for row in rows),
        number_stats=number_statistics(games), group_stats=group_statistics(games, not latest_unavailable),
        latest_completed_unavailable=latest_unavailable, observed_games=len(games))


def available_streams():
    return sorted({'lucky28'} | set(GroupAbsenceStream.objects.values_list('key', flat=True)) |
                  {key or 'lucky28' for key in GameRound.objects.values_list('game_type', flat=True).distinct()})
