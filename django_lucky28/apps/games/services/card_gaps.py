"""Frozen gap evidence and pure selection of the groups relevant to a card."""
from games.group_config import GROUP_BY_NAME, GROUP_BY_NUMBER
from .group_history import definitions, group_statistics


def capture_gaps(games):
    groups = definitions() + [dict(key=f'N{n}', label=f'Number {n}', family='Numbers',
        numbers=[n], color=GROUP_BY_NUMBER[n].color) for n in range(28)]
    fields = ('key', 'label', 'family', 'numbers', 'color', 'current_gap',
              'gap_lower_bound', 'current_incomplete', 'average_gap', 'max_gap',
              'exact_gap_count', 'latest_appearance')
    return dict(version=1, history_count=len(games),
        as_of=games[0].game_no if games else None,
        groups=[{key: row[key] for key in fields}
                for row in group_statistics(games, groups=groups)])


def gap_sections(payload, kind, snapshot):
    """Select from saved evidence only, including every applicable match family."""
    if kind in ('health', 'test'):
        return []
    evidence = snapshot.get('gap_analytics')
    if not evidence:
        return []  # Legacy cards must not invent statistics or read live history.
    groups = evidence['groups']
    targets = set()
    if payload.get('group_id'):
        targets.add(payload['group_id'])
    aliases = dict(size='Size', parity='Parity', color='Colors', row='Rows',
                   column='Columns', combo='Combos', extreme='Range', range='Range')
    families = set()
    for match in payload.get('matches', []):
        series = match.get('group')
        values = {str(v) for v in match.get('values', [])}
        if series == 'number':
            targets.update(f'N{int(v)}' for v in values if v.isdigit() and 0 <= int(v) <= 27)
        elif series in aliases:
            family = aliases[series]
            families.add(family)
            if series == 'color':
                targets.update(GROUP_BY_NAME[v].id for v in values if v in GROUP_BY_NAME)
            targets.update(g['key'] for g in groups if g['family'] == family
                           and (g['key'] in values or g['label'] in values))
    if kind == 'window':
        targets.update(f'N{n}' for n in payload.get('numbers', []) if type(n) is int and 0 <= n <= 27)
    if kind == 'result':
        number = payload.get('result', {}).get('number')
        if type(number) is int and 0 <= number <= 27:
            targets.add(f'N{number}')
    families.update(g['family'] for g in groups if g['key'] in targets)
    output = []
    for family in dict.fromkeys(g['family'] for g in groups):
        if family not in families:
            continue
        rows = [dict(g, highlighted=g['key'] in targets) for g in groups
                if g['family'] == family and (family != 'Numbers' or g['key'] in targets)]
        output.append(dict(family=family, rows=rows,
            scale=max([g['current_gap'] or 0 for g in rows] + [1])))
    return output


def gap_label(row):
    if row['current_gap'] is None:
        return 'N/A'
    return (str(row['current_gap']) + ('+' if row['gap_lower_bound'] else '')
            + ('*' if row['current_incomplete'] else ''))
