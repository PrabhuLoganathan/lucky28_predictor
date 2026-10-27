"""Telegram cards drawn from frozen evidence, with portable vector stickers."""
from collections import Counter
from datetime import datetime
from io import BytesIO
import math
import time

from PIL import Image, ImageDraw, ImageFont

from games.category_config import CATEGORY_BY_ID
from games.group_config import GROUP_BY_NUMBER, GROUP_BY_ID
from .alert_identity import group_identity, group_heading
from .card_gaps import gap_sections, gap_label
from types import SimpleNamespace
from .timeline import TRACKS, classify

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
    symbol = STYLES.get(style_key(payload, kind), STYLES['alert'])[2]
    identity = group_identity(payload) if kind in ('category', 'category_end', 'group', 'group_end') else None
    return f'{symbol} {identity["symbol"]}' if identity else symbol


def load_font(size, bold=False):
    paths = (('DejaVuSans-Bold.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf') if bold else
             ('DejaVuSans.ttf', '/System/Library/Fonts/Supplemental/Arial.ttf'))
    for path in paths:
        try: return ImageFont.truetype(path, size)
        except OSError: pass
    return ImageFont.load_default(size=size)


def focus_track(payload, kind, snapshot):
    """Use canonical category identity, never words in a display name."""
    primary = next(iter(payload.get('matches', [])), {})
    group_id = payload.get('group_id')
    category = CATEGORY_BY_ID.get(group_id)
    families = {'Rows': 'row', 'Columns': 'column', 'SE / BE / BO / SO': 'combo',
                'Extreme numbers': 'extreme', 'Board border': 'border'}
    key = families.get(category.family) if category else None
    if group_id in GROUP_BY_ID:
        key = 'color'
    if not key:
        key = {'S': 'size', 'B': 'size', 'E': 'parity', 'O': 'parity'}.get(group_id)
    key = key or primary.get('group', 'number')
    if kind in ('window', 'result', 'health', 'test') or primary.get('mode') == 'every_game' or key not in (
            'number', 'size', 'parity', 'combo', 'row', 'column', 'color', 'extreme', 'border'):
        key = 'number'
    # Derivation is safe for legacy snapshots too: only their frozen numbers are used.
    games = [SimpleNamespace(winning_number=g['number']) for g in snapshot.get('games', [])]
    title, legend = TRACKS[key]
    return dict(key=key, title=title, legend=legend,
                letters=[classify(key, games, i) for i in range(len(games))])


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
    absence_ended = key == 'ended' and payload.get('mode') == 'absence'
    if absence_ended:
        label = 'ABSENCE ENDED'
    elif key == 'ended' and payload.get('mode') == 'streak':
        label = 'STREAK ENDED'
    matches = payload.get('matches', [])
    primary = matches[0] if matches else {}
    identity = group_identity(payload) if kind in ('category', 'category_end', 'group', 'group_end') else None
    if identity:
        accent = identity['accent']
        label = group_heading(payload, payload.get('mode', 'absence'), key == 'ended')
    if kind in ('category', 'category_end', 'group', 'group_end'):
        title = identity['title'] if identity else payload.get('group_name') or f'{payload.get("color", "Color")} group'
        count = payload.get('count', payload.get('absence', 0))
        metric = ('missed rounds before return' if absence_ended else
                  'consecutive hits before break' if key == 'ended' else
                  'rounds absent' if key == 'absence' else 'consecutive rounds')
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
                identity=identity,
                return_detail=(f'Returned: {payload["ended_number"]} · absence reset to 0'
                               if absence_ended and 'ended_number' in payload else ''),
                snapshot=snapshot, focus=focus, gap_sections=gap_sections(payload, kind, snapshot))


def sticker(draw, center, radius, key, color):
    """Outlined stickers use shapes instead of platform-dependent emoji fonts."""
    x, y = center
    draw.ellipse((x-radius+3, y-radius+7, x+radius+3, y+radius+7), fill='#070c16')
    draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color, outline=WHITE, width=3)
    ink = '#111a2c'
    def points(coords): return [(x+a*radius, y+b*radius) for a, b in coords]
    def line(coords, width=6): draw.line(points(coords), fill=ink, width=max(2, int(width*radius/48)), joint='curve')
    if key in ('row', 'column'):
        # Horizontal versus vertical stripes remain distinguishable without color.
        for offset in (-.38, 0, .38):
            if key == 'row':
                bounds = (x-radius*.6, y+radius*(offset-.10), x+radius*.6, y+radius*(offset+.10))
            else:
                bounds = (x+radius*(offset-.10), y-radius*.6, x+radius*(offset+.10), y+radius*.6)
            draw.rounded_rectangle(bounds, radius=3, fill=ink)
    elif key == 'combination':
        draw.polygon(points([(0,-.65),(.65,0),(0,.65),(-.65,0)]), fill=ink)
        line([(0,-.42),(0,.42)], 4)
        draw.line(points([(-.4,0),(.4,0)]), fill=color, width=4)
        draw.line(points([(0,-.4),(0,.4)]), fill=color, width=4)
    elif key == 'color_group':
        for a,b in [(-.28,-.28),(.28,-.28),(-.28,.28),(.28,.28)]:
            r=radius*.20
            draw.ellipse((x+a*radius-r,y+b*radius-r,x+a*radius+r,y+b*radius+r), fill=ink)
    elif key in ('absence', 'density_low'):
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
    fonts = {size: load_font(size) for size in (10, 11, 13, 16, 18, 20, 22, 24, 28)}
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
    rows = math.ceil(len(games)/10)
    timeline_height = 260 + rows*96 if games else 150
    sections = model['gap_sections']
    gap_height = 160 + sum(76 + len(section['rows'])*38 for section in sections) if sections else 0
    height = 440 + block_height + timeline_height + 90 + gap_height
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
    identity = model['identity']
    sticker(draw,(111,180),53,identity['icon'] if identity else model['key'],accent)
    if identity:
        text(111,241,identity['badge'],bold[20],accent,'ma')
    text(194,124,model['label'],bold[20],accent)
    title_lines = card_lines(model['title'][:500],bold[34],570)
    for i,line in enumerate(title_lines[:2]): text(194,160+i*40,clipped(line,bold[34],570),bold[34])
    count_font = bold[76] if len(model['count']) < 7 else bold[34]
    text(936,151,model['count'],count_font,accent,'ma')
    text(1030,243,clipped(model['metric'],fonts[18],270),fonts[18],MUTED,'ra')
    if model['return_detail']:
        text(194,243,clipped(model['return_detail'],bold[20],540),bold[20],accent)
    # Board membership chips use the exact same seven colors as the web timeline.
    members = payload.get('numbers', []) if kind in ('category','category_end','group','group_end') else []
    if members:
        text(54,285,'MEMBERS',bold[20],MUTED)
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
    if 'threshold' in payload:
        threshold_label = 'MIN ABSENCE' if model['return_detail'] else 'TRIGGER'
        text(1040,355,f'{threshold_label}  ≥ {payload["threshold"]}',bold[20],accent,'ra')
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

    if sections:
        evidence = snapshot['gap_analytics']
        draw.rounded_rectangle((32,y,1048,y+gap_height-20),radius=20,fill=PANEL,outline='#2a3b55',width=2)
        text(54,y+18,'GAP ANALYTICS',bold[24])
        text(54,y+53,clipped(f'{evidence["history_count"]} saved results · as of #{evidence["as_of"]}',fonts[18],960),fonts[18],MUTED)
        gy=y+88
        for section in sections:
            check()
            text(54,gy,section['family']+' · current absence',bold[20],accent)
            text(690,gy,f'Linear scale 0–{section["scale"]}',fonts[16],MUTED,'ra')
            text(825,gy,'AVG GAP',fonts[16],MUTED,'ra')
            text(1018,gy,'LONGEST GAP',fonts[16],MUTED,'ra')
            gy+=36
            highest=max((row['current_gap'] or 0 for row in section['rows']),default=0)
            for row in section['rows']:
                marked=row['highlighted']
                if marked:
                    draw.rounded_rectangle((45,gy-3,1034,gy+31),radius=7,fill='#24354e')
                    draw.rectangle((45,gy-3,49,gy+31),fill=accent)
                text(60,gy,clipped(('> ' if marked else '')+row['label'],fonts[18],190),fonts[18],WHITE if marked else MUTED)
                maximum=highest>0 and row['current_gap']==highest
                text(350,gy,gap_label(row)+(' MAX' if maximum else ''),fonts[18],'#ff879b' if maximum else WHITE,'ra')
                draw.rounded_rectangle((370,gy+5,690,gy+22),radius=5,fill=BG)
                value=row['current_gap'] or 0
                if value:
                    width=max(3,320*value/section['scale'])
                    color=row['color'] if section['family']=='Colors' else '#ff879b' if maximum else accent if marked else '#8899b5'
                    draw.rounded_rectangle((370,gy+5,370+width,gy+22),radius=3,fill=color)
                for x,field in ((825,'average_gap'),(1018,'max_gap')):
                    text(x,gy,row[field] if row[field] is not None else 'N/A',fonts[18],MUTED,'ra')
                gy+=38
            gy+=40
        text(54,gy-24,'> Alert group · MAX = largest current gap · 0 = appeared in latest result',fonts[16],MUTED)
        text(54,gy,'+ Not seen in saved history · * Unverified rounds; observed count only',fonts[16],MUTED)
        text(54,gy+24,'Average / longest use verified completed gaps only. N/A = insufficient history.',fonts[16],MUTED)
        y+=gap_height

    draw.rounded_rectangle((32,y,1048,y+timeline_height),radius=20,fill='#121e32',outline='#2a3b55',width=2)
    text(54,y+22,'GLOBAL TIMELINE',bold[24])
    text(1025,y+25,f'{len(games)} / 150 GAMES  ·  NEWEST FIRST',fonts[18],MUTED,'ra')
    if not games:
        text(54,y+75,'No completed timeline saved with this alert.',fonts[24],MUTED)
    else:
        text(54,y+66,clipped(focus['title'],bold[20],960),bold[20],accent)
        legend={s['letter']:s for s in focus['legend']}
        letters=focus['letters']
        for i,g in enumerate(games):
            if i%10==0: check()
            x=98+(i%10)*98; cy=y+132+(i//10)*96
            letter=letters[i] if i<len(letters) else '?'
            color=legend.get(letter,{}).get('color',MUTED)
            rgb=tuple(int(color[j:j+2],16) for j in (1,3,5))
            fill=tuple(int(c*.28+20) for c in rgb)
            bounds=(x-30,cy-30,x+30,cy+30)
            draw.ellipse(bounds,fill=fill)
            if g.get('gap_before'):
                for angle in range(0,360,30):
                    draw.arc(bounds,angle,angle+17,fill=color,width=2)
            else:
                draw.ellipse(bounds,outline=color,width=2)
            if i==0:
                draw.ellipse((x-34,cy-34,x+34,cy+34),outline=WHITE,width=2)
            text(x,cy,letter,bold[24],WHITE,'mm')
            state=g.get('new_repeat') or {}
            tag_kind=state.get('kind')
            tag='New' if tag_kind=='new' else 'Repeated' if tag_kind=='repeated' else state.get('reason','Not saved')
            if i==0 and tag_kind and state.get('run'):
                tag += ' · '+('N' if tag_kind=='new' else 'R')+'×'+str(state['run'])
            tag_color='#99f6e4' if tag_kind=='new' else '#fde68a' if tag_kind=='repeated' else '#354159'
            draw.rounded_rectangle((x-45,cy+37,x+45,cy+54),radius=4,fill=tag_color)
            tag_font=next((fonts[size] for size in (13,11,10) if fonts[size].getlength(tag)<=86),fonts[10])
            text(x,cy+45,clipped(tag,tag_font,86),tag_font,BG if tag_kind else WHITE,'mm')
        ly=y+104+rows*96
        x=54
        shown_legend=TRACKS['color'][1] if focus['key']=='number' else focus['legend']
        for state in shown_legend:
            label=f'{state["letter"]} {state["label"].split(" · ")[0]}'
            width=fonts[18].getlength(label)+30
            if x+width>1020: x=54; ly+=27
            draw.ellipse((x,ly+4,x+9,ly+13),fill=state['color'])
            text(x+16,ly,label,fonts[18],MUTED); x+=width
        text(54,y+timeline_height-87,'New / Repeated compares the number with its previous 10 rounds.',fonts[16],MUTED)
        text(54,y+timeline_height-61,'White ring = newest · Dashed circle = history gap · Not saved = legacy evidence',fonts[16],MUTED)
        latest=games[0].get('game_no','—')
        text(54,y+timeline_height-34,clipped(f'AS OF #{latest}   ·   Read left to right, then down',fonts[18],960),fonts[18],MUTED)
    text(40,height-43,'Frozen evidence  ·  Observed results, not a prediction',fonts[18],MUTED)
    text(1040,height-43,'LUCKY28',bold[20],accent,'ra')
    for quality in (85,75,65,55):
        check(); output=BytesIO(); canvas.save(output,format='JPEG',quality=quality,optimize=True); check()
        if output.tell()<400_000: return output.getvalue()
    raise ValueError('Card exceeded 400KB')
