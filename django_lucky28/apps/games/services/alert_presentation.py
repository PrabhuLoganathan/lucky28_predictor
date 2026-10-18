"""Render only frozen payloads; no live database reads during delivery."""
from html import escape
from io import BytesIO
from textwrap import wrap
import time


def format_message(payload, kind='alert', limit=4096):
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
        block = f'<b>{escape(match["title"][:120])}</b>\n{escape(match["detail"][:300])}'
        if len(('\n'.join(lines + [block])).encode('utf-16-le')) // 2 > limit - 150:
            lines.append(f'… {len(matches) - index} more conditions in the saved evidence.')
            break
        lines.append(block)
    if kind == 'alert':
        lines.append('<i>Observed history; not a prediction of the next result.</i>')
    return '\n'.join(lines)


def render_card(payload, kind='alert', budget=2.0):
    """1080px JPEG under 400KB, with a cooperative rendering deadline."""
    from PIL import Image, ImageDraw, ImageFont
    deadline = time.monotonic() + budget

    def check():
        if time.monotonic() >= deadline:
            raise TimeoutError('Card render deadline exceeded')

    def font(size):
        for path in ('DejaVuSans.ttf', '/System/Library/Fonts/Supplemental/Arial.ttf'):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
        return ImageFont.load_default(size=size)

    matches = payload.get('matches', [])[:8]
    height = 510 + len(matches) * 118
    canvas = Image.new('RGB', (1080, height), '#0C192C')
    draw = ImageDraw.Draw(canvas)
    title_font, body_font, small_font = font(38), font(25), font(20)
    draw.rectangle((0, 0, 1080, 7), fill='#5EE0C2')
    draw.text((40, 32), {'alert': 'LUCKY28 · ROUND ALERT', 'result': 'CONFIRMED RESULT',
                         'health': 'COLLECTION WARNING'}[kind], font=title_font, fill='#F5F8FF')
    draw.text((40, 88), str(payload['game_no'])[:40], font=body_font, fill='#68B5FF')
    draw.text((40, 128), str(payload.get('captured_at', ''))[:45], font=small_font, fill='#AAB8CC')
    y = 180
    colors = {'size': '#F7BC62', 'parity': '#68B5FF', 'color': '#BAA0FF', 'number': '#66D8D2'}
    for match in matches:
        check()
        draw.rounded_rectangle((30, y, 1050, y + 105), radius=12, fill='#16273D')
        draw.rectangle((30, y + 12, 36, y + 93), fill=colors.get(match['group'], '#5EE0C2'))
        draw.text((52, y + 10), match['title'][:60], font=body_font, fill='#F5F8FF')
        for line, text in enumerate(wrap(match['detail'], width=82)[:2]):
            draw.text((52, y + 48 + line * 24), text, font=small_font, fill='#C4CFDF')
        y += 118
    if kind == 'result':
        result = payload['result']
        draw.text((40, y), f'{result["number"]} · {result["size"]} · {result["parity"]} · {result["color"]}', font=title_font, fill='#5EE0C2')
    elif kind == 'health':
        draw.text((40, y), payload.get('detail', '')[:70], font=body_font, fill='#FF8D9B')
    else:
        draw.text((40, y), 'Recent results · newest first', font=small_font, fill='#AAB8CC')
        for index, result in enumerate(payload.get('timeline', [])[:50]):
            x, row_y = 55 + (index % 20) * 50, y + 60 + (index // 20) * 50
            draw.ellipse((x - 20, row_y - 20, x + 20, row_y + 20), fill='#245849' if result['size'] == 'Big' else '#3C3B68')
            draw.text((x, row_y), str(result['number']), font=small_font, anchor='mm', fill='white')
    if len(payload.get('matches', [])) > len(matches):
        draw.text((40, height - 100), f'{len(matches)} of {len(payload["matches"])} conditions shown · full evidence in dashboard', font=small_font, fill='#AAB8CC')
    draw.text((40, height - 70), 'Frozen evidence · Observed history, not a prediction', font=small_font, fill='#AAB8CC')
    for quality in (85, 75, 65, 55):
        check()
        output = BytesIO()
        canvas.save(output, format='JPEG', quality=quality, optimize=True)
        check()
        if output.tell() < 400_000:
            return output.getvalue()
    raise ValueError('Card exceeded 400KB')
