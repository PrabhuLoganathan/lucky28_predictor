"""Render only frozen payloads; no live database reads during delivery."""
from html import escape
from games.group_config import label_color_groups
from .alert_identity import group_heading


def match_labels(match):
    """Also label previously queued evidence without changing the saved payload."""
    title, detail = match['title'], match['detail']
    if match.get('group') == 'color':
        return label_color_groups(title), label_color_groups(detail)
    return title, detail


def card_lines(text, font, width):
    """Wrap measured words; split long tokens with bounded binary searches."""
    lines, line = [], ''
    for word in text.split():
        candidate = f'{line} {word}' if line else word
        if font.getlength(candidate) <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
            line = ''
        while word and font.getlength(word) > width:
            low, high = 1, len(word)
            while low < high:
                middle = (low + high + 1) // 2
                if font.getlength(word[:middle]) <= width:
                    low = middle
                else:
                    high = middle - 1
            lines.append(word[:low])
            word = word[low:]
        line = word
    if line:
        lines.append(line)
    return lines


def format_message(payload, kind='alert', limit=4096):
    """Symbol-first text, with whole HTML lines within Telegram's UTF-16 budget."""
    from .alert_card import symbol_for
    message = symbol_for(payload, kind) + ' ' + _format_message(payload, kind, limit)
    games = payload.get('global_timeline', {}).get('games', [])
    if games:
        lines = message.split('\n')
        lines.insert(2, f'🧭 Timeline snapshot: {len(games)} / 150 games · newest first')
        message = '\n'.join(lines)
    length = lambda value: len(value.encode('utf-16-le')) // 2
    if length(message) <= limit:
        return message
    result = []
    footer = '… Full details in saved evidence.'
    for line in message.split('\n'):
        if length('\n'.join(result + [line, footer])) > limit:
            break
        result.append(line)
    return '\n'.join(result + [footer])


def _format_message(payload, kind='alert', limit=4096):
    if kind in ('category', 'category_end', 'group_end'):
        return format_category_message(payload)
    if kind == 'window':
        return format_window_message(payload)
    if kind == 'group':
        return format_group_message(payload)
    heading = {'alert': 'LUCKY28 ALERT', 'result': 'CONFIRMED RESULT', 'health': 'COLLECTION WARNING', 'test': 'LUCKY28 TEST MESSAGE'}[kind]
    lines = [f'<b>{heading}</b>', f'Round: {escape(str(payload["game_no"])[:100])}',
             escape(str(payload.get('captured_at', ''))[:100])]
    if kind == 'result':
        result = payload['result']
        lines.append(escape(f'{result["number"]} · {result["size"]} · {result["parity"]} · {result["color"]}'))
    if kind in ('health', 'test'):
        lines.append(escape(payload.get('detail', '')[:400]))
    matches = payload.get('matches', [])
    # Keep complete HTML blocks and reserve space for the omitted count/footer.
    for index, match in enumerate(matches):
        title, detail = match_labels(match)
        block = f'<b>{escape(title)}</b>\n{escape(detail)}'
        if len(('\n'.join(lines + [block])).encode('utf-16-le')) // 2 > limit - 150:
            lines.append(f'… {len(matches) - index} more conditions in the saved evidence.')
            break
        lines.append(block)
    if kind == 'alert':
        lines.append('<i>Observed history; not a prediction of the next result.</i>')
    return '\n'.join(lines)


def render_card(payload, kind='alert', budget=2.0):
    from .alert_card import render_card as create_card
    return create_card(payload, kind, budget)


def format_category_message(payload):
    if payload.get('change_type') == 'ended':
        return format_category_ending(payload)
    count = f'{"at least " if payload["lower_bound"] else ""}{payload["count"]}'
    detail = (f'Absent for {count} completed rounds.' if payload['mode'] == 'absence'
              else f'Appeared in {count} consecutive completed rounds.')
    lines = [f'<b>{group_heading(payload, payload["mode"])}</b>',
             escape(f'{payload["group_name"]} {payload["numbers"]}'),
             escape(f'{detail} Threshold: {payload["threshold"]}.'),
             escape(f'Stream: {payload["stream"]}')]
    if payload.get('last_round'):
        lines.append(escape(f'Last appearance: {payload["last_number"]} in round {payload["last_round"]}.'))
    else:
        lines.append('Last appearance: Not seen in available history.')
    if payload['mode'] == 'streak':
        lines.append(escape(f'Streak starts at round {payload["period_start"]}.'))
    lines.extend([escape(f'Evaluated through round {payload["evaluated_round"]}.'),
                  escape(f'Alert time: {payload["captured_at"]}')])
    if payload.get('details_url'):
        lines.append(f'<a href="{escape(payload["details_url"], quote=True)}">Round details</a>')
    else:
        lines.append(escape(f'Details in app: {payload["details_path"]}'))
    lines.append('<i>Observed results; not a prediction of the next result.</i>')
    return '\n'.join(lines)


def format_category_ending(payload):
    count = f'{"at least " if payload["lower_bound"] else ""}{payload["count"]}'
    detail = (f'Absence ended after {count} missed rounds. Result {payload["ended_number"]} returned to this group. Absence reset to 0 on this round.'
              if payload['mode'] == 'absence' else
              f'Streak ended after {count} consecutive hits. Result {payload["ended_number"]} is outside this group.')
    lines = [f'<b>{group_heading(payload, payload["mode"], ended=True)}</b>',
             escape(f'{payload["group_name"]} {payload["numbers"]}'), escape(detail),
             escape(f'Ending round: {payload["evaluated_round"]}.'),
             escape(f'Minimum missed rounds before return: {payload["threshold"]}.') if payload['mode'] == 'absence' else '',
             escape(f'Result time: {payload["ended_at"]}'), escape(f'Stream: {payload["stream"]}')]
    if payload.get('details_url'):
        lines.append(f'<a href="{escape(payload["details_url"], quote=True)}">Round details</a>')
    else:
        lines.append(escape(f'Details in app: {payload["details_path"]}'))
    lines.append('<i>Observed results; not a prediction of the next result.</i>')
    return '\n'.join(lines)


def format_group_message(payload):
    group = f'{payload["group_id"]} · {payload["color"]} group {payload["numbers"]}'
    count = f'{"at least " if payload["lower_bound"] else ""}{payload["absence"]}'
    lines = [f'<b>{group_heading(payload)}</b>', escape(group),
             escape(f'Absent for {count} observed completed rounds. Threshold: {payload["threshold"]}.'),
             escape(f'Stream: {payload["stream"]}')]
    if payload['lower_bound']:
        lines.append('Last appearance: Not seen in available history.')
    else:
        lines.append(escape(f'Last appearance: {payload["last_number"]} in round {payload["last_round"]} at {payload["last_timestamp"]}.'))
    lines.extend([escape(f'Evaluated through round {payload["evaluated_round"]}.'),
                  escape(f'Alert time: {payload["captured_at"]}')])
    if payload.get('details_url'):
        lines.append(f'<a href="{escape(payload["details_url"], quote=True)}">Round details</a>')
    else:
        lines.append(escape(f'Details in app: {payload["details_path"]}'))
    lines.append('<i>Observed absence; not a prediction of the next result.</i>')
    return '\n'.join(lines)


def format_window_message(payload):
    title = '10-GAME DROUGHT — ALL DIFFERENT' if payload['kind'] == 'drought' else '10-GAME REPEAT'
    lines = [f'<b>{title}</b>', escape(f'Stream: {payload["stream"]}'),
             escape(f'Rounds: {payload["start_round"]} – {payload["end_round"]}'),
             escape('Results (oldest → newest): ' + ', '.join(map(str, payload['numbers'])))]
    if payload['kind'] == 'drought':
        lines.append('All 10 completed results are different. No number repeats.')
    else:
        newest = payload['numbers'][-1]
        count = payload['numbers'].count(newest)
        lines.append(escape(f'Newest result {newest} appears {count} times within the latest 10 games.'))
        lines.append(escape(f'Repeated numbers: {payload["repeated_details"]}'))
    lines.append(escape(f'Alert time: {payload["captured_at"]}'))
    if payload.get('details_url'):
        lines.append(f'<a href="{escape(payload["details_url"], quote=True)}">Round details</a>')
    else:
        lines.append(escape(f'Details in app: {payload["details_path"]}'))
    lines.append('<i>Observed results; not a prediction of the next result.</i>')
    return '\n'.join(lines)
