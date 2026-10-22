"""Telegram cards drawn from frozen evidence, with portable vector stickers."""
from collections import Counter
from datetime import datetime
from io import BytesIO
import math
import time

from PIL import Image, ImageDraw, ImageFont

from games.category_config import CATEGORY_BY_ID
from games.group_config import GROUP_BY_NUMBER, GROUP_BY_ID, GROUP_BY_NAME

WHITE, MUTED, BG, PANEL = '#f1f5ff', '#9baec9', '#0b1120', '#152139'
STYLES = {
    'absence': ('ABSENCE', '#ffbd69', '⌛'),
    'streak': ('STREAK', '#b79aff', '🔥'),
    'repeat': ('REPEAT', '#54d9ed', '🔁'),
    'drought': ('ALL DIFFERENT', '#ffbd69', '🧩'),
    'ended': ('CONDITION ENDED', '#68e0b4', '✅'),
    'alternating': ('ALTERNATING', '#54d9ed', '🔀'),
    'density': ('CLUSTER', '#f58ac9', '🎯'),
    'density_low': ('LOW DENSITY', '#ffbd69', '🔎'),
    'breaker': ('STREAK BROKEN', '#ff879b', '⚡'),
    'result': ('RESULT', '#68e0b4', '🎲'),
    'health': ('FEED PAUSED', '#ff879b', '📡'),
    'alert': ('PATTERN ALERT', '#8faeff', '🔔'),
}


def style_key(payload, kind):
    if kind == 'category_end' or payload.get('change_type') == 'ended': return 'ended'
    if kind in ('result', 'health'): return kind
    if kind == 'window': return payload.get('kind', 'repeat')
    if kind == 'group': return 'absence'
    return payload.get('mode') or next(iter(payload.get('matches', [])), {}).get('mode', 'alert')


def symbol_for(payload, kind):
    return STYLES.get(style_key(payload, kind), STYLES['alert'])[2]


def load_font(size, bold=False):
    paths = (('DejaVuSans-Bold.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf') if bold else
             ('DejaVuSans.ttf', '/System/Library/Fonts/Supplemental/Arial.ttf'))
    for path in paths:
        try: return ImageFont.truetype(path, size)
        except OSError: pass
    return ImageFont.load_default(size=size)


def focus_track(payload, kind, snapshot):
    """Return the alert's visual vocabulary; H/M mean group membership only."""
    matches = payload.get('matches', [])
    primary = matches[0] if matches else {}
    group_id = payload.get('group_id')
    group = CATEGORY_BY_ID.get(group_id) or GROUP_BY_ID.get(group_id)
    numbers = set(group.numbers) if group else None
    title = group.name if group else ''
    if kind == 'alert' and primary.get('values'):
        values, series = primary['values'], primary.get('group')
        if series == 'number': numbers = {int(n) for n in values if str(n).isdigit()}
        elif series == 'size': numbers = {n for n in range(28) if ('Big' if n >= 14 else 'Small') in values}
        elif series == 'parity': numbers = {n for n in range(28) if ('Even' if n % 2 == 0 else 'Odd') in values}
        elif series == 'color': numbers = {n for v in values if v in GROUP_BY_NAME for n in GROUP_BY_NAME[v].numbers}
        title = ' / '.join(values)
    if numbers is not None:
        return dict(title=f'{title} appearances', letters=['H' if g['number'] in numbers else 'M' for g in snapshot['games']],
            legend=[dict(letter='H', label='In group', color='#68e0b4'), dict(letter='M', label='Outside group', color='#52647f')])
    key = 'window' if kind == 'window' else primary.get('group', 'size')
    track = snapshot.get('tracks', {}).get(key) or snapshot.get('tracks', {}).get('size')
    if track: return track
    return dict(title='Color groups', letters=[f'G{int(GROUP_BY_NUMBER[g["number"]].id[1:])}' for g in snapshot['games']],
                legend=[dict(letter=f'G{i}', label=g.name, color=g.color) for i, g in enumerate(GROUP_BY_ID.values(), 1)])


def card_model(payload, kind):
    snapshot = payload.get('global_timeline')
    if not snapshot:
        # Old queued cards keep their original evidence; never fetch newer history.
        history = payload.get('timeline', [])
        if kind == 'window' and not history:
            history = [dict(number=n) for n in reversed(payload.get('numbers', []))]
        snapshot = dict(games=[r for r in history[:150] if type(r.get('number')) is int and 0 <= r['number'] <= 27], tracks={})
    focus = focus_track(payload, kind, snapshot)
    key = style_key(payload, kind)
    label, accent, _ = STYLES.get(key, STYLES['alert'])
    matches = payload.get('matches', [])
    primary = matches[0] if matches else {}
    if kind in ('category', 'category_end', 'group'):
        title = payload.get('group_name') or f'{payload.get("color", "Color")} group'
        count = payload.get('count', payload.get('absence', 0))
        metric = 'rounds before ending' if key == 'ended' else ('rounds absent' if key == 'absence' else 'consecutive rounds')
        if payload.get('lower_bound'): count = f'{count}+'
    elif kind == 'window':
        title = '10-game number window'
        count = len(set(payload.get('numbers', []))) if key == 'drought' else max(Counter(payload.get('numbers', [])).values(), default=0)
        metric = 'different numbers' if key == 'drought' else 'highest repeat count'
    elif kind == 'result':
        title, count, metric = 'Confirmed number', payload.get('result', {}).get('number', '—'), 'completed result'
    elif kind == 'health':
        title, count, metric = 'Collection needs attention', '!', 'check the data feed'
    else:
        title = primary.get('title', 'Number Game patterns') if len(matches) <= 1 else f'{len(matches)} active conditions'
        count = primary.get('observed', '•') if len(matches) <= 1 else len(matches)
        metric = 'observed rounds' if len(matches) <= 1 else 'matched conditions'
    return dict(key=key, label=label, accent=accent, title=title, count=str(count), metric=metric,
                snapshot=snapshot, focus=focus)


def sticker(draw, center, radius, key, color):
    """Outlined stickers use shapes instead of platform-dependent emoji fonts."""
    x, y = center
    draw.ellipse((x-radius+3, y-radius+7, x+radius+3, y+radius+7), fill='#070c16')
    draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color, outline=WHITE, width=3)
    ink = '#111a2c'
    def points(coords): return [(x+a*radius, y+b*radius) for a, b in coords]
    def line(coords, width=6): draw.line(points(coords), fill=ink, width=max(2, int(width*radius/48)), joint='curve')
    if key in ('absence', 'density_low'):
        line([(-.4,-.55),(.4,-.55),(.3,-.2),(-.3,.2),(-.4,.55),(.4,.55),(.3,.2),(-.3,-.2),(-.4,-.55)])
        draw.polygon(points([(-.28,.43),(.28,.43),(0,.14)]), fill=ink)
    elif key == 'streak':
        draw.polygon(points([(0,-.7),(.22,-.26),(.38,-.4),(.55,.15),(.3,.57),(-.25,.57),(-.52,.19),(-.35,-.25),(-.17,-.03)]), fill=ink)
        draw.polygon(points([(0,-.02),(.2,.28),(0,.49),(-.17,.28)]), fill=color)
    elif key in ('ended', 'result'):
        line([(-.48,0),(-.12,.36),(.52,-.35)], 9)
    elif key in ('repeat', 'alternating'):
        draw.arc((x-radius*.55,y-radius*.55,x+radius*.55,y+radius*.55), 205, 350, fill=ink, width=max(3,int(radius*.12)))
        draw.arc((x-radius*.55,y-radius*.55,x+radius*.55,y+radius*.55), 25, 170, fill=ink, width=max(3,int(radius*.12)))
        draw.polygon(points([(.6,-.08),(.24,-.15),(.51,-.42)]), fill=ink)
        draw.polygon(points([(-.6,.08),(-.24,.15),(-.51,.42)]), fill=ink)
    elif key in ('drought', 'density'):
        for a,b in [(-.28,-.28),(.28,-.28),(-.28,.28),(.28,.28)]:
            r=radius*.16; draw.rounded_rectangle((x+a*radius-r,y+b*radius-r,x+a*radius+r,y+b*radius+r), radius=3, fill=ink)
    elif key == 'breaker':
        draw.polygon(points([(.12,-.7),(-.42,.12),(-.06,.12),(-.18,.7),(.45,-.2),(.1,-.2)]), fill=ink)
    else:
        line([(0,-.5),(0,.18)], 9)
        draw.ellipse((x-4,y+radius*.37,x+4,y+radius*.37+8), fill=ink)
    # A small glint makes the badge read as a sticker, not another data dot.
    sx, sy = x+radius*.82, y-radius*.72
    draw.line((sx-8,sy,sx+8,sy), fill=WHITE, width=3)
    draw.line((sx,sy-8,sx,sy+8), fill=WHITE, width=3)


def render_card(payload, kind='alert', budget=2.0):
    from .alert_presentation import card_lines, match_labels
    deadline = time.monotonic() + budget
    def check():
        if time.monotonic() >= deadline: raise TimeoutError('Card render deadline exceeded')
    fonts = {size: load_font(size) for size in (16, 18, 20, 22, 24, 28)}
    bold = {size: load_font(size, True) for size in (20, 24, 28, 34, 76)}
    model = card_model(payload, kind)
    accent, snapshot, focus = model['accent'], model['snapshot'], model['focus']
    games = snapshot['games'][:150]
    matches = payload.get('matches', [])
    # Keep the card scannable; remaining conditions stay in the archived payload.
    blocks = []
    for match in matches[:3]:
        title, detail = match_labels(match)
        blocks.append((match, card_lines(title[:500], bold[24], 830)[:2], card_lines(detail[:1000], fonts[22], 830)[:2]))
    block_height = sum(28 + len(t)*30 + len(d)*28 for _,t,d in blocks)
    rows = math.ceil(len(games)/30)
    timeline_height = 370 + rows*32 if games else 150
    height = 440 + block_height + timeline_height + 90
    canvas = Image.new('RGB', (1080, height), BG)
    draw = ImageDraw.Draw(canvas)
    def text(x,y,value,font=None,color=WHITE,anchor=None):
        draw.text((x,y), str(value), font=font or fonts[22], fill=color, anchor=anchor)
    def clipped(value, font, width):
        value = str(value)
        while font.getlength(value) > width and len(value)>1: value=value[:-2]+'…'
        return value
    draw.rounded_rectangle((32,30,1048,34),radius=2,fill=accent)
    text(40,51,'LUCKY28  /  NUMBER GAME',bold[20])
    stamp = str(payload.get('captured_at',''))
    try: stamp = datetime.fromisoformat(stamp).strftime('%d %b · %H:%M UTC') if stamp.endswith(('+00:00','Z')) else stamp
    except ValueError: pass
    text(1040,51,clipped(stamp,fonts[18],440),fonts[18],MUTED,'ra')

    draw.rounded_rectangle((32,100,1048,333),radius=24,fill=PANEL,outline='#293750',width=2)
    sticker(draw,(111,180),53,model['key'],accent)
    text(194,124,model['label'],bold[20],accent)
    title_lines = card_lines(model['title'][:500],bold[34],570)
    for i,line in enumerate(title_lines[:2]): text(194,160+i*40,clipped(line,bold[34],570),bold[34])
    count_font = bold[76] if len(model['count']) < 7 else bold[34]
    text(936,151,model['count'],count_font,accent,'ma')
    text(1030,243,clipped(model['metric'],fonts[18],270),fonts[18],MUTED,'ra')
    # Board membership chips use the exact same seven colors as the web timeline.
    members = payload.get('numbers', []) if kind in ('category','category_end','group') else []
    if members:
        text(54,285,'WATCH',bold[20],MUTED)
        for i,n in enumerate(members[:20]):
            x=161+i*41
            color=GROUP_BY_NUMBER[n].color
            draw.rounded_rectangle((x,278,x+34,313),radius=9,fill=color)
            text(x+17,295,n,bold[20],BG,'mm')
    elif kind == 'window':
        repeated = [(n,c) for n,c in Counter(payload.get('numbers', [])).items() if c>1]
        text(54,285,'REPEATS' if repeated else '10 UNIQUE NUMBERS',bold[20],MUTED)
        for i,(n,c) in enumerate(repeated[:5]):
            x=180+i*124
            draw.rounded_rectangle((x,278,x+110,313),radius=9,fill=GROUP_BY_NUMBER[n].color)
            text(x+55,295,f'{n} × {c}',bold[20],BG,'mm')
    else:
        detail = payload.get('detail','') if kind=='health' else ('Threshold '+str(payload['threshold']) if 'threshold' in payload else 'Observed game history')
        text(54,282,clipped(detail,fonts[22],960),fonts[22],MUTED)

    round_id = str(payload.get('game_no','—'))
    text(40,355,clipped(f'ROUND  #{round_id}',bold[20],690),bold[20])
    if 'threshold' in payload: text(1040,355,f'TRIGGER  ≥ {payload["threshold"]}',bold[20],accent,'ra')
    y=398
    for match,titles,details in blocks:
        check()
        h=28+len(titles)*30+len(details)*28
        draw.rounded_rectangle((32,y,1048,y+h-10),radius=16,fill='#101c30')
        key=match.get('mode',model['key']); color=STYLES.get(key,STYLES['alert'])[1]
        sticker(draw,(77,y+42),24,key,color)
        for i,line in enumerate(titles): text(120,y+12+i*30,line,bold[24])
        for i,line in enumerate(details): text(120,y+14+len(titles)*30+i*28,line,fonts[22],MUTED)
        y+=h
    if len(matches)>3:
        text(40,y+2,f'+ {len(matches)-3} more conditions in saved evidence',fonts[18],MUTED)
    y+=40

    draw.rounded_rectangle((32,y,1048,y+timeline_height),radius=20,fill='#121e32',outline='#2a3b55',width=2)
    text(54,y+22,'GLOBAL TIMELINE',bold[24])
    text(1025,y+25,f'{len(games)} / 150 GAMES  ·  NEWEST FIRST',fonts[18],MUTED,'ra')
    if not games:
        text(54,y+75,'No completed timeline saved with this alert.',fonts[24],MUTED)
    else:
        text(54,y+66,clipped(focus['title'],bold[20],700),bold[20],accent)
        text(1025,y+67,'LATEST 15 ENLARGED',fonts[16],MUTED,'ra')
        legend={s['letter']:s for s in focus['legend']}
        letters=focus['letters']
        for i,g in enumerate(games[:15]):
            x=84+i*65
            draw.ellipse((x-24,y+104,x+24,y+152),fill=GROUP_BY_NUMBER[g['number']].color)
            text(x,y+128,g['number'],bold[24],BG,'mm')
            letter=letters[i] if i<len(letters) else '?'
            color=legend.get(letter,{}).get('color',MUTED)
            draw.rounded_rectangle((x-23,y+164,x+23,y+200),radius=9,fill='#0b1323',outline=color,width=2)
            text(x,y+182,letter,bold[20],color,'mm')
        text(54,y+218,'FULL SNAPSHOT  ·  read left → right, then down',fonts[18],MUTED)
        for i,g in enumerate(games):
            if i%30==0: check()
            x=70+(i%30)*32.4; cy=y+264+(i//30)*32
            letter=letters[i] if i<len(letters) else '?'
            color=legend.get(letter,{}).get('color',MUTED)
            if letter=='H':
                draw.ellipse((x-12,cy-12,x+12,cy+12),fill=color)
                draw.line([(x-6,cy),(x-1,cy+5),(x+7,cy-5)],fill=BG,width=2)
            elif letter=='M':
                draw.ellipse((x-12,cy-12,x+12,cy+12),outline=color,width=2)
                draw.line((x-5,cy,x+5,cy),fill=MUTED,width=2)
            else:
                draw.rounded_rectangle((x-13,cy-12,x+13,cy+12),radius=6,fill='#0b1323',outline=color)
                text(x,cy,letter,fonts[16],color,'mm')
            if g.get('gap_before'): draw.line((x+14,cy-11,x+14,cy+11),fill='#ffbd69',width=2)
        ly=y+264+rows*32
        x=54
        for state in focus['legend']:
            label=f'{state["letter"]} {state["label"].split(" · ")[0]}'
            width=fonts[18].getlength(label)+30
            if x+width>1020: x=54; ly+=27
            draw.ellipse((x,ly+4,x+9,ly+13),fill=state['color'])
            text(x+16,ly,label,fonts[18],MUTED); x+=width
        latest=games[0].get('game_no','—')
        text(54,y+timeline_height-34,clipped(f'AS OF #{latest}   ·   Amber divider = history gap',fonts[18],960),fonts[18],MUTED)
    text(40,height-43,'Frozen evidence  ·  Observed results, not a prediction',fonts[18],MUTED)
    text(1040,height-43,'LUCKY28',bold[20],accent,'ra')
    for quality in (85,75,65,55):
        check(); output=BytesIO(); canvas.save(output,format='JPEG',quality=quality,optimize=True); check()
        if output.tell()<400_000: return output.getvalue()
    raise ValueError('Card exceeded 400KB')
