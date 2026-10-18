"""Pure, newest-first rule evaluation. Missing facts break streaks and windows."""
from itertools import takewhile


def evaluate_rules(rules, facts, prior_active=()):
    matches = []
    for rule in rules:
        if not rule.enabled:
            continue
        series = facts.get(rule.series, [])
        values = set(rule.values)
        count, matched = 0, False
        prefix = lambda items, predicate: sum(1 for _ in takewhile(predicate, items))
        mode = rule.mode
        if mode == 'every_game':
            count, matched = 1, True
            detail = 'A new round is open.'
        elif mode in ('streak', 'absence'):
            count = prefix(series, lambda x: x is not None and ((x in values) if mode == 'streak' else (x not in values)))
            matched = count >= rule.threshold
            detail = (f'{", ".join(rule.values)} occurred in {count} consecutive completed rounds.' if mode == 'streak'
                      else f'No {", ".join(rule.values)} in the last {count} completed rounds.')
        elif mode in ('density', 'density_low'):
            sample = series[:rule.window]
            if rule.window and len(sample) == rule.window and None not in sample:
                count = sum(x in values for x in sample)
                matched = count >= rule.threshold if mode == 'density' else count <= rule.threshold
            detail = f'{", ".join(rule.values)} occurred {count} times in the last {rule.window} completed rounds.'
        elif mode == 'breaker':
            if series and series[0] == rule.breaker_value:
                count = prefix(series[1:], lambda x: x in values)
                matched = count >= rule.threshold
            detail = f'{rule.breaker_value} ended a run of {count} {", ".join(rule.values)} results.'
        elif mode == 'alternating':
            for index, value in enumerate(series):
                if value not in values or (index and value == series[index - 1]):
                    break
                count += 1
            matched = count >= rule.threshold
            detail = f'{" / ".join(rule.values)} alternated for {count} completed rounds.'
        else:
            continue
        if matched:
            identity = f'{rule.key}:{rule.revision}:global'
            matches.append(dict(identity=identity, rule_key=rule.key, revision=rule.revision,
                                title=rule.title, group=rule.series, mode=mode, observed=count,
                                threshold=rule.threshold, window=rule.window, detail=detail,
                                min_plan_rank=rule.min_plan_rank,
                                scope='Current server session' if rule.session_only else 'Completed history',
                                is_activation=mode == 'every_game' or identity not in prior_active))
    return matches


def default_rules():
    yield dict(key='all_games', title='Every new round', series='number', mode='every_game', enabled=False)
    for series, values in [('size', ['Big', 'Small']), ('parity', ['Odd', 'Even']),
                           ('color', ['Red', 'Yellow', 'Pink', 'Blue', 'Cyan', 'Green', 'Grey'])]:
        for value in values:
            base = dict(series=series, values=[value])
            for mode, threshold, window, label in [('streak', 6 if series != 'color' else 3, 0, 'streak'),
                                                  ('absence', 8 if series != 'color' else 15, 0, 'drought'),
                                                  ('density', 8 if series != 'color' else 5, 10, 'high density'),
                                                  ('density_low', 1, 10, 'low density')]:
                yield dict(base, key=f'{series}_{value.lower()}_{mode}', title=f'{value} {label}',
                           mode=mode, threshold=threshold, window=window)
        if len(values) == 2:
            yield dict(key=f'{series}_alternating', title=f'{" / ".join(values)} alternating', series=series,
                       mode='alternating', values=values, threshold=6)
            for value, other in [values, values[::-1]]:
                yield dict(key=f'{series}_{value.lower()}_breaker', title=f'{other} breaks {value} streak',
                           series=series, mode='breaker', values=[value], breaker_value=other, threshold=5)
    for number in range(28):
        yield dict(key=f'number_{number}_drought', title=f'Number {number} drought', series='number',
                   mode='absence', values=[str(number)], threshold=50, min_plan_rank=2)
