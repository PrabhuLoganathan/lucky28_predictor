"""Deterministic research baselines and descriptive result evidence, without I/O."""
from collections import Counter

from games.group_config import COLOR_GROUPS

VERSION = 'case-study-v1'
WEIGHTS = [1, 3, 6, 10, 15, 21, 28, 36, 45, 55, 63, 69, 73, 75,
           75, 73, 69, 63, 55, 45, 36, 28, 21, 15, 10, 6, 3, 1]
BASE = [w / 1000 for w in WEIGHTS]


def adjacency(older, newer):
    a, b = str(older.get('round_id', '')), str(newer.get('round_id', ''))
    if not (a.isdigit() and b.isdigit() and len(a) == len(b) and len(a) >= 12 and a[:8] == b[:8]):
        return 'unknown'
    difference = int(b[8:]) - int(a[8:])
    return 'continuous' if difference == 1 else 'missing' if difference > 1 else 'unknown'


def clean(history, target=None):
    rows, seen, invalid, duplicate = [], set(), 0, 0
    for row in history:
        number, identity = row.get('number'), row.get('round_id')
        if identity == target:
            continue
        if type(number) is not int or not 0 <= number <= 27 or not identity:
            invalid += 1
            continue
        if identity in seen:
            duplicate += 1
            continue
        seen.add(identity)
        rows.append(row)
    return rows, invalid, duplicate


def quality(history, invalid=0, duplicate=0, result=None):
    links = [adjacency(a, b) for a, b in zip(history, history[1:])]
    recent = history[-10:] + ([result] if result else [])
    continuous = len(history) >= 10 and all(adjacency(a, b) == 'continuous' for a, b in zip(recent, recent[1:]))
    if result:
        links += [adjacency(history[-1], result)] if history else []
    return dict(status='empty' if not history else 'partial' if invalid or duplicate or any(x != 'continuous' for x in links) else 'continuous',
                known_missing_links=links.count('missing'), unknown_links=links.count('unknown'),
                invalid_records=invalid, duplicate_records=duplicate, latest_ten_continuous=continuous)


def forecast(history):
    rows, invalid, duplicate = clean(history)
    rows = rows[-150:]
    specs = [('theoretical', 'Theoretical baseline', 0, 0),
             ('frequency150', 'Recent frequency · 150', 150, 100),
             ('recency10', 'Recent frequency · 10', 10, 20)]
    strategies = []
    for identity, name, window, prior in specs:
        sample = rows[-window:] if window else []
        counts = Counter(r['number'] for r in sample)
        probabilities = [(counts[n] + prior * BASE[n]) / (len(sample) + prior) for n in range(28)] if prior else BASE[:]
        ranked = sorted(range(28), key=lambda n: (-probabilities[n], n))
        reasons = [dict(number=n, probability=probabilities[n], baseline_probability=BASE[n], features=[
            f'Theoretical digit-sum weight: {WEIGHTS[n]} / 1,000 (independent uniform digits assumed).',
            f'{counts[n]} appearances among {len(sample)} earlier observed results.' if window else 'Fixed distribution; gaps and streaks do not alter this baseline.',
            f'Counts are smoothed with {prior} baseline-weighted observations.' if prior else 'Equal probabilities are ordered by smaller number; ties are not a preference supported by evidence.',
        ]) for n in ranked[:5]]
        strategies.append(dict(id=identity, name=name, experimental=bool(window), history_count=len(sample),
            description='Experimental frequency estimate; no validated predictive advantage.' if window else 'Assumed distribution of the sum of three independent uniform digits from 0–9.',
            probabilities=probabilities, ranked_numbers=ranked,
            top={str(k):dict(numbers=ranked[:k], coverage=sum(probabilities[n] for n in ranked[:k]),
                            baseline_coverage=sum(BASE[n] for n in ranked[:k])) for k in (1, 3, 5)}, reasons=reasons))
    return dict(version=VERSION, history_count=len(rows), history_quality=quality(rows, invalid, duplicate), strategies=strategies)


def groups():
    universe = set(range(28))
    output = [('size', 'S', 'Small', set(range(14))), ('size', 'B', 'Big', set(range(14, 28))),
              ('parity', 'E', 'Even', set(range(0, 28, 2))), ('parity', 'O', 'Odd', set(range(1, 28, 2)))]
    for size in 'SB':
        for parity in 'EO':
            output.append(('combination', size+parity, size+parity,
                           {n for n in universe if (n < 14) == (size == 'S') and (n % 2 == 0) == (parity == 'E')}))
    output += [('color', g.id, g.name, set(g.numbers)) for g in COLOR_GROUPS]
    output += [('row', f'R{i+1}', f'Row {i+1}', set(range(i*7, i*7+7))) for i in range(4)]
    output += [('column', f'C{i+1}', f'Column {i+1}', set(range(i, 28, 7))) for i in range(7)]
    return output


def gap(history, members, result):
    last = next((i for i in range(len(history)-1, -1, -1) if history[i]['number'] in members), None)
    start = last if last is not None else 0
    segment = history[start:] + [result]
    return dict(observed_games=len(history)-1-last if last is not None else len(history),
                lower_bound=last is None,
                interrupted=any(adjacency(a, b) != 'continuous' for a, b in zip(segment, segment[1:])),
                last_round_id=history[last]['round_id'] if last is not None else None)


def streak(history, members):
    count = 0
    for index in range(len(history)-1, -1, -1):
        if history[index]['number'] not in members:
            break
        if count and adjacency(history[index], history[index+1]) != 'continuous':
            break
        count += 1
    return count


def calculation(result):
    digits = result.get('digits')
    valid = isinstance(digits, list) and len(digits) == 3 and all(type(d) is int and 0 <= d <= 9 for d in digits)
    if digits is None or digits == []:
        return dict(status='unavailable', digits=None, sum=None, expression=None, detail='Component digits were not captured.')
    if not valid:
        return dict(status='invalid', digits=digits, sum=None, expression=None, detail='Captured digits are not three integers from 0–9.')
    total = sum(digits)
    return dict(status='verified' if total == result['number'] else 'mismatch', digits=digits, sum=total,
                expression=' + '.join(map(str, digits)) + f' = {total}',
                detail='Captured digits add up to the declared result.' if total == result['number'] else 'Captured digit sum does not match the declared result.')


def explain(result, history, frozen_forecast=None, *, evidence_mode=None):
    rows, invalid, duplicate = clean(history, result['round_id'])
    number = result['number']
    if type(number) is not int or not 0 <= number <= 27:
        raise ValueError('A result must be an integer from 0 through 27.')
    q = quality(rows, invalid, duplicate, result)
    kind = ('repeated' if any(r['number'] == number for r in rows[-10:]) else 'new') if q['latest_ten_continuous'] else 'unknown'
    size, parity = ('S' if number < 14 else 'B'), ('E' if number % 2 == 0 else 'O')
    color = next(g for g in COLOR_GROUPS if number in g.numbers)
    matches, broken = [], []
    connected = bool(rows and adjacency(rows[-1], result) == 'continuous')
    for family, key, label, members in groups():
        before = streak(rows, members)
        if number in members:
            missing = gap(rows, members, result)
            matches.append(dict(family=family, group=key, label=label, gap_before=missing,
                streak_before=before, streak_after=before+1 if connected else 1,
                detail=f'{label} appeared after {missing["observed_games"]} observed non-matching rounds'
                       + ('; earlier history is limited.' if missing['lower_bound'] else '.')
                       + (' Continuity is incomplete.' if missing['interrupted'] else '')))
        elif before and connected:
            broken.append(dict(family=family, group=key, label=label, count=before,
                               detail=f'The observed {label} streak of {before} ended.'))
    scores = []
    if frozen_forecast:
        for strategy in frozen_forecast['strategies']:
            scores.append(dict(id=strategy['id'], name=strategy['name'], actual_probability=strategy['probabilities'][number],
                top={str(k):dict(**strategy['top'][str(k)], hit=number in strategy['top'][str(k)]['numbers']) for k in (1, 3, 5)}))
    return dict(version=VERSION, round_id=result['round_id'], number=number,
        evidence_mode=evidence_mode or ('recorded_before_result' if frozen_forecast else 'retrospective'),
        history_quality=q, calculation=calculation(result),
        classification=dict(kind=kind, label=kind.title(), previous_ten=[r['number'] for r in rows[-10:]],
            detail='Compared against the ten immediately preceding completed rounds.' if kind != 'unknown' else 'Ten continuous preceding rounds are unavailable.'),
        number_gap=gap(rows, {number}, result),
        groups=dict(size=size, parity=parity, combination=size+parity, color=color.name,
                    color_hex=color.color, row=f'R{number//7+1}', column=f'C{number%7+1}'),
        observed_matches=matches, broken_streaks=broken, strategy_results=scores,
        generation_cause='Unavailable: the provider generation mechanism is not captured. Pattern matches are not causes.',
        limitations=['Theoretical probabilities assume three independent uniform digits; this is not verified for the provider.',
                     'Rows, columns, colors, size and parity describe the same outcome; they are not independent confirming signals.',
                     'Missing rounds are not counted as observed absence. Gaps do not make a number due.',
                     'These fixed experimental methods have not demonstrated a predictive advantage.'])
