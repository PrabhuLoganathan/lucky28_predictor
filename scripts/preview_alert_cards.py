"""Generate local card previews from fictional results; no Telegram requests."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'django_lucky28'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from games.services.card_timeline import snapshot_from_games
from games.services.alert_presentation import render_card


def snapshot(numbers):
    base = datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)
    games = [SimpleNamespace(game_no=f'20261021{1000+i}', winning_number=n, has_winner=True,
             status=3, winner_event_ts=base+timedelta(minutes=i)) for i,n in enumerate(numbers)]
    return snapshot_from_games(list(reversed(games)))


def examples():
    numbers = [(i*11+3)%28 for i in range(160)]
    common = dict(game_no='202610211159', captured_at='2026-10-21T15:39:00+00:00', stream='lucky28',
                  lower_bound=False, threshold=8, evaluated_round='202610211159',
                  details_path='/games/detail/202610211159/', matches=[])
    absent = numbers[:-18] + [8,12,6,2,4,10,14,16,9,3,5,11,13,17,15,19,21,23]
    absent[-19] = 26
    yield 'absence', 'group', dict(common, group_id='G01', color='Red', numbers=[0,1,26,27], absence=18,
        last_number=26, last_round='202610211141', last_timestamp='2026-10-21T15:21:00+00:00', global_timeline=snapshot(absent))
    streak = numbers[:-8]+[14,19,16,20,15,18,17,14]
    yield 'streak', 'category', dict(common, group_id='R03', group_name='Row 3', mode='streak', count=8,
        numbers=list(range(14,21)), last_number=14, last_round=common['game_no'], period_start='202610211152',
        global_timeline=snapshot(streak), matches=[dict(title='Row 3 · 8 consecutive appearances',
            detail='Every result in the latest 8 completed games belongs to Row 3.', group='category', mode='streak')])
    repeated = numbers[:-10]+[8,3,17,8,12,20,8,5,14,8]
    window_common = {key: value for key,value in common.items() if key != 'threshold'}
    yield 'repeat', 'window', dict(window_common, kind='repeat', numbers=repeated[-10:],
        start_round='202610211150', end_round=common['game_no'], repeated_details='8 × 4', global_timeline=snapshot(repeated))
    ended = streak[:-1]+[21]
    yield 'ended', 'category_end', dict(common, group_id='R03', group_name='Row 3', mode='streak', count=7,
        change_type='ended', threshold=4, ended_number=21, ended_at=common['captured_at'], numbers=list(range(14,21)),
        global_timeline=snapshot(ended), matches=[dict(title='Row 3 streak ended · Number 21',
            detail='Result 21 is outside Row 3. The run ended after 7 consecutive appearances.', group='category', mode='breaker')])

    from games.category_config import CATEGORY_BY_ID
    from games.group_config import GROUP_BY_ID
    for name, group_id in [('rows', 'R03'), ('columns', 'C01'), ('combinations', 'SE'),
                           ('colors', 'G04'), ('extremes', 'edges'), ('border', 'border')]:
        group = CATEGORY_BY_ID.get(group_id) or GROUP_BY_ID[group_id]
        yield name, 'group' if group_id.startswith('G') else 'category', dict(common,
            group_id=group_id, group_name=group.name, color=group.name, mode='absence', count=8,
            numbers=list(group.numbers), global_timeline=snapshot(repeated))
    for series in ('number', 'size', 'parity'):
        yield series, 'alert', dict(common, global_timeline=snapshot(repeated),
            matches=[dict(group=series, mode='absence', title=series.title()+' absence',
                          detail='Fictional preview of the category timeline.', observed=8,
                          values={'number':['0'], 'size':['Small'], 'parity':['Even']}[series])])


def main():
    directory = ROOT / '.local' / 'telegram-card-previews'
    directory.mkdir(parents=True, exist_ok=True)
    for name, kind, payload in examples():
        content = render_card(payload, kind)
        path = directory / f'{name}.jpg'
        path.write_bytes(content)
        print(f'{path} ({len(content):,} bytes)')


if __name__ == '__main__':
    main()
