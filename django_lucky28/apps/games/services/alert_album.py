"""Three square evidence pages, rendered only from one saved payload."""
from collections import Counter
from datetime import datetime
from html import escape
from io import BytesIO
import math
import time
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from games.group_config import GROUP_BY_NAME, GROUP_BY_NUMBER
from .alert_card import BG, PANEL, WHITE, MUTED, TIP_GOLD, card_model, load_font, sticker
from .alert_presentation import card_lines, match_labels
from .card_gaps import gap_label
from .timeline import TRACKS

ALBUM_KINDS = frozenset(('alert', 'group', 'group_end', 'category', 'category_end', 'window', 'result'))
PAGE_TITLES = ('Alert details', 'Analytics', 'Verification timeline')
SIZE = 1600


def round_id(payload):
    return str(payload.get('game_no') or payload.get('evaluated_round') or payload.get('end_round') or 'Not saved')


def capture_time(payload, short=False):
    value = str(payload.get('captured_at') or '')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            return value  # Never invent a timezone for legacy evidence.
        stamp = stamp.astimezone(ZoneInfo('Asia/Kolkata'))
        return stamp.strftime('%d %b · %I:%M %p IST' if short else '%d %b %Y · %I:%M:%S %p IST')
    except ValueError:
        return value or 'Capture time not saved'


def summary(payload, kind, model=None):
    model = model or card_model(payload, kind)
    primary = next(iter(payload.get('matches', [])), {})
    key = model['key']
    count = payload.get('count', payload.get('absence', primary.get('observed')))
    lower = payload.get('lower_bound', False)
    count_text = ('at least ' if lower else '') + str(count) if count is not None else ''
    rounds = 'round' if count == 1 else 'rounds'
    numbers = payload.get('numbers', []) if kind in ('group', 'group_end', 'category', 'category_end') else []
    heading = f'{model["title"]} — {model["label"]}'
    color_name = payload.get('color') if kind in ('group', 'group_end') else None
    if primary.get('group') == 'color' and len(primary.get('values', [])) == 1:
        color_name = primary['values'][0]
    if color_name and color_name in GROUP_BY_NAME:
        numbers = list(GROUP_BY_NAME[color_name].numbers)
        heading = f'{color_name.upper()} GROUP — {"ABSENCE ENDED" if key == "ended" else key.replace("_", " ").upper()}'
    if key == 'absence' and count is not None:
        detail = f'Absent for: {count_text} completed {rounds}'
    elif key == 'streak' and count is not None:
        detail = f'Consecutive appearances: {count_text} completed {rounds}'
    elif key == 'ended':
        detail = (f'Absence ended after {count_text} missed {rounds}; returned: {payload.get("ended_number", "not saved")}'
                  if payload.get('mode') == 'absence' else
                  f'Streak ended after {count_text} consecutive hits. Result {payload.get("ended_number", "not saved")} is outside this group.')
    elif kind == 'window':
        detail = ('All 10 completed results are different' if payload.get('kind') == 'drought' else
                  'Repeated numbers: ' + ', '.join(f'{n} × {c}' for n, c in Counter(payload.get('numbers', [])).items() if c > 1))
    elif kind == 'result':
        result = payload.get('result', {})
        detail = ' · '.join(str(result[k]) for k in ('number', 'size', 'parity', 'color') if result.get(k) is not None)
    else:
        detail = primary.get('detail') or payload.get('detail') or 'Observed game history'
    return dict(heading=heading, detail=detail, numbers=numbers)


def escaped_limit(value, budget):
    output, used = [], 0
    for char in str(value):
        encoded = escape(char)
        length = len(encoded.encode('utf-16-le')) // 2
        if used + length > budget:
            break
        output.append(encoded)
        used += length
    return ''.join(output)


def format_album_caption(payload, kind):
    model = card_model(payload, kind)
    info = summary(payload, kind, model)
    primary = next(iter(payload.get('matches', [])), {})
    color = ''
    if kind in ('group', 'group_end'):
        color = payload.get('color', '')
    elif primary.get('group') == 'color':
        color = (primary.get('values') or [''])[0]
    symbol = {'Yellow': '🟡', 'Orange': '🟠', 'Red': '🔴', 'Blue': '🔵', 'Green': '🟢',
              'Pink': '🟣', 'Magenta': '🟣', 'Cyan': '🔵', 'Cyan / Teal': '🔵', 'Grey': '⚪'}.get(color, '')
    lines = [f'{symbol + " " if symbol else ""}<b>{escaped_limit(info["heading"], 200)}</b>', '', f'<b>{escaped_limit(info["detail"], 300)}</b>']
    if info['numbers']:
        lines.append('Numbers: ' + escaped_limit(', '.join(map(str, info['numbers'])), 140))
    lines += ['', 'Round: ' + escaped_limit(round_id(payload), 100),
              'Updated: ' + escaped_limit(capture_time(payload, short=True), 100), '', '<i>Observed history only.</i>']
    return '\n'.join(lines)


class Page:
    def __init__(self, payload, model, index):
        self.canvas = Image.new('RGB', (SIZE, SIZE), BG)
        self.draw = ImageDraw.Draw(self.canvas)
        self.accent = model['accent']
        self.fonts = {}
        self.draw.rounded_rectangle((56, 40, 1544, 47), radius=3, fill=self.accent)
        self.text(64, 72, 'LUCKY28  /  ' + PAGE_TITLES[index].upper(), 32, bold=True)
        self.text(1536, 72, f'{index+1} / 3', 28, color=self.accent, anchor='ra')
        self.fit('ROUND  #' + round_id(payload), (64, 127, 1536, 164), size=28, minimum=18, bold=True)
        self.text(64, 178, 'CAPTURED  ' + capture_time(payload), 24, color=MUTED)
        self.text(64, 1530, 'Same saved snapshot · Observed history only', 23, color=MUTED)
        self.text(1536, 1530, 'LUCKY28', 24, bold=True, color=self.accent, anchor='ra')

    def font(self, size, bold=False):
        key = (size, bold)
        if key not in self.fonts:
            self.fonts[key] = load_font(size, bold)
        return self.fonts[key]

    def text(self, x, y, value, size=28, bold=False, color=WHITE, anchor=None):
        self.draw.text((x, y), str(value), font=self.font(size, bold), fill=color, anchor=anchor)

    def panel(self, box):
        self.draw.rounded_rectangle(box, radius=24, fill=PANEL, outline='#2a3b55', width=2)

    def fit(self, value, box, size=32, minimum=18, bold=False, color=WHITE):
        left, top, right, bottom = box
        for chosen in range(size, minimum-1, -2):
            font = self.font(chosen, bold)
            lines = [line for paragraph in str(value).splitlines() for line in (card_lines(paragraph, font, right-left) or [''])]
            step = math.ceil(chosen * 1.35)
            if len(lines) * step <= bottom-top:
                for i, line in enumerate(lines):
                    self.text(left, top+i*step, line, chosen, bold, color)
                return
        raise ValueError('Evidence does not fit square page without truncation')

    def jpeg(self, check):
        for quality in (90, 82, 74):
            check()
            output = BytesIO()
            self.canvas.save(output, format='JPEG', quality=quality, optimize=True)
            check()
            if output.tell() < 1_500_000:
                return output.getvalue()
        raise ValueError('Album page exceeds image budget')


def details_page(payload, kind, model):
    page = Page(payload, model, 0)
    info = summary(payload, kind, model)
    page.panel((56, 242, 1544, 738))
    identity = model['identity']
    sticker(page.draw, (154, 345), 62, identity['icon'] if identity else model['key'], model['accent'])
    page.fit(info['heading'], (260, 278, 1450, 420), 48, bold=True, color=model['accent'])
    page.fit(model['count'], (96, 445, 480, 640), 130, bold=True, color=model['accent'])
    page.fit(model['metric'], (96, 645, 500, 705), 25, color=MUTED)
    page.fit(info['detail'], (540, 448, 1460, 680), 40)
    page.panel((56, 770, 1544, 1468))
    lines = []
    if info['numbers']:
        lines.append('Numbers: ' + ', '.join(map(str, info['numbers'])))
    if payload.get('threshold') is not None:
        lines.append('Trigger threshold: ' + str(payload['threshold']))
    if payload.get('last_round'):
        lines.append(f'Last appearance: {payload.get("last_number", "—")} · round {payload["last_round"]}')
    if payload.get('last_timestamp'):
        lines.append('Last appearance time: ' + str(payload['last_timestamp']))
    if model.get('return_detail'):
        lines.append(model['return_detail'])
    if kind == 'window':
        lines.append('Results, oldest to newest: ' + ', '.join(map(str, payload.get('numbers', []))))
        lines.append(f'Window: {payload.get("start_round", "—")} to {payload.get("end_round", "—")}')
    for match in payload.get('matches', []):
        title, detail = match_labels(match)
        lines.extend([title, detail])
        if match.get('threshold') is not None:
            lines.append(f'Trigger: {match["threshold"]}' + (f' in {match["window"]} rounds' if match.get('window') else ''))
    if payload.get('stream'):
        lines.append('Stream: ' + str(payload['stream']))
    page.text(96, 810, 'TRIGGERED CONDITION & SUPPORTING DETAILS', 26, bold=True, color=model['accent'])
    page.fit('\n'.join(lines) if lines else 'All available condition details are shown above.',
             (96, 872, 1495, 1405), 32, minimum=18)
    return page


def analytics_page(payload, kind, model):
    page = Page(payload, model, 1)
    snapshot, sections = model['snapshot'], model['gap_sections']
    evidence = snapshot.get('gap_analytics', {})
    page.text(64, 245, 'GAP ANALYTICS', 38, bold=True)
    page.fit(f'{evidence.get("history_count", "No")} saved results · as of #{evidence.get("as_of") or "not saved"}',
             (64, 301, 1536, 350), 25, color=MUTED)
    entries = [(section, row) for section in sections for row in section['rows']]
    if not entries:
        page.panel((56, 380, 1544, 1150))
        page.fit('No gap analytics were saved with this alert. New statistics have not been substituted.',
                 (100, 500, 1480, 850), 38, color=MUTED)
    else:
        columns = math.ceil(len(entries)/16)
        if columns > 4:
            raise ValueError('Too many analytics rows for one readable square')
        width = 1488 / columns
        for column in range(columns):
            x = 56 + column*width
            page.panel((x, 380, x+width-12, 1256))
            page.text(x+24, 402, 'GROUP / CURRENT', 22 if columns < 3 else 18, bold=True)
            page.text(x+width-30, 438, 'AVG / LONGEST', 19, color=MUTED, anchor='ra')
            column_entries = entries[column*16:(column+1)*16]
            step = min(96, 740/max(1, len(column_entries)))
            if len(sections) == 1:
                page.text(x+24, 438, f'{sections[0]["family"]} · Linear scale 0–{sections[0]["scale"]}', 21, color=MUTED)
            for index, (section, row) in enumerate(column_entries):
                y = 487+index*step
                if row['highlighted']:
                    page.draw.rounded_rectangle((x+12,y-4,x+width-24,y+39), radius=7, fill='#24354e')
                label = ('> ' if row['highlighted'] else '')+(section['family']+' / ' if len(sections)>1 else '')+row['label']
                page.fit(label, (x+24,y,x+width*.43,y+34), 23, minimum=16)
                highest = max((r['current_gap'] or 0 for r in section['rows']), default=0)
                maximum = highest > 0 and row['current_gap'] == highest
                current = gap_label(row)+(' MAX' if maximum else '')
                page.fit(current,(x+width*.43,y,x+width*.55,y+34),23,minimum=15,
                         color='#ff879b' if maximum else WHITE)
                avg, longest = row['average_gap'], row['max_gap']
                page.fit(f'{avg if avg is not None else "N/A"} / {longest if longest is not None else "N/A"}',
                         (x+width*(.81 if columns == 1 else .60),y,x+width-30,y+34),22,minimum=14,color=MUTED)
                if columns == 1:
                    left, right = x+width*.56, x+width*.78
                    page.draw.rounded_rectangle((left,y+7,right,y+24),radius=5,fill=BG)
                    value = row['current_gap'] or 0
                    if value:
                        page.draw.rounded_rectangle((left,y+7,left+(right-left)*value/section['scale'],y+24),radius=5,fill=row['color'])
        page.text(64, 1280, '> Alert group · Red count = largest current gap · 0 = appeared in latest result', 22, color=MUTED)
        page.text(64, 1315, '+ Not seen in saved history · * Unverified rounds · N/A = insufficient history', 22, color=MUTED)
        page.text(64, 1350, 'Average / longest use verified completed gaps only.', 22, color=MUTED)
    tip = snapshot.get('tip_summary', {})
    if tip.get('window_available'):
        tip_line = f'TIP density: {tip["tip_count"]}/10 completed games · Observed no-tip run: {tip["no_tip_streak"]}'
    else:
        tip_line = 'TIP density: unavailable — 10 consecutive verified settlements required.'
    page.fit(tip_line, (64, 1408, 1536, 1488), 26, color=TIP_GOLD)
    return page


def timeline_page(payload, kind, model, check):
    page = Page(payload, model, 2)
    snapshot, focus = model['snapshot'], model['focus']
    games = snapshot.get('games', [])
    if len(games) > 150:
        raise ValueError('Timeline exceeds the supported snapshot size')
    page.text(64, 245, focus['title'].upper(), 36, bold=True, color=model['accent'])
    page.text(1536, 298, f'{len(games)} / 150 SAVED GAMES · NEWEST FIRST', 24, color=MUTED, anchor='ra')
    page.text(64, 298, 'Read left to right, then down', 24, color=MUTED)
    legend = {s['letter']: s for s in focus['legend']}
    for i, game in enumerate(games):
        if i % 15 == 0:
            check()
        x, y = 62+(i%15)*99, 365+(i//15)*95
        letter = focus['letters'][i]
        color = legend.get(letter, {}).get('color', GROUP_BY_NUMBER[game['number']].color)
        is_tip = game.get('tip', {}).get('status') == 'TIP'
        page.draw.rounded_rectangle((x,y,x+89,y+84),radius=12,fill=PANEL,
            outline=TIP_GOLD if is_tip else color,width=3 if is_tip else 1)
        if i == 0:
            page.draw.rounded_rectangle((x-4,y-4,x+93,y+88),radius=14,outline=WHITE,width=2)
        page.text(x+44,y+9,letter,26,bold=True,anchor='ma')
        if is_tip:
            page.text(x+77,y+1,'*',19,bold=True,color=TIP_GOLD,anchor='ma')
        label = f'#{game["number"]}' if focus['key'] != 'number' else f'{i+1:03d}'
        page.text(x+44,y+42,label,17,color=MUTED,anchor='ma')
        tag = game.get('new_repeat') or {}
        tag_kind = tag.get('kind')
        value = 'N' if tag_kind == 'new' else 'R' if tag_kind == 'repeated' else '?'
        if i == 0 and tag_kind and tag.get('run'):
            value += '×'+str(tag['run'])
        if game.get('gap_before'):
            value += ' / gap'
        page.fit(value,(x+4,y+62,x+85,y+84),16,minimum=12,
                 color='#99f6e4' if tag_kind == 'new' else '#fde68a' if tag_kind == 'repeated' else MUTED)
    if not games:
        page.fit('No completed timeline was saved with this alert.',(64,450,1536,900),42,color=MUTED)
    shown = TRACKS['color'][1] if focus['key'] == 'number' else focus['legend']
    legend_text = ' · '.join(f'{s["letter"]} {s["label"].split(" · ")[0]}' for s in shown)
    page.fit(legend_text,(64,1338,1536,1408),22,minimum=18,color=MUTED)
    page.text(64, 1420, 'N = New · R = Repeated vs previous 10 rounds · ? = insufficient or unsaved evidence',21,color=MUTED)
    page.text(64, 1452, 'White outline = newest · gap = history gap · Gold outline + * = TIP game',21,color=MUTED)
    return page


def render_album(payload, kind='alert', budget=2.0):
    deadline = time.monotonic()+budget
    def check():
        if time.monotonic() >= deadline:
            raise TimeoutError('Album render deadline exceeded')
    check()
    model = card_model(payload, kind)
    pages = []
    for render in (details_page, analytics_page):
        check()
        pages.append(render(payload, kind, model).jpeg(check))
    pages.append(timeline_page(payload, kind, model, check).jpeg(check))
    return pages
