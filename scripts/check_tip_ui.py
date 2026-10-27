"""Browser-check the tip monitor against an isolated database; never send alerts."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
BROWSER = r'''
const {chromium, expect} = require('./chamet_logger_standalone/node_modules/@playwright/test');
(async () => {
  const browser = await chromium.launch({channel:'chrome', headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.TIP_URL + '/tips/');
    await expect(page.locator('#tip-status')).toContainText('Latest accepted round: game-8');
    await expect(page.locator('#tip-streak')).toHaveText('7');
    await expect(page.locator('#tip-rounds tr')).toHaveCount(8);
    await expect(page.locator('#tip-events article')).toHaveCount(2);
    await expect(page.locator('#tip-events')).toContainText('No tip for 7 consecutive completed games');
    await expect(page.locator('#tip-queued')).toHaveText('2');
    await expect(page.locator('#tip-rounds')).toContainText('CONFLICT');
    const data = await (await page.request.get(process.env.TIP_URL+'/api/tips/')).json();
    expect(data.state.noTipStreak).toBe(7);
    for (const width of [1440, 1000, 390]) {
      await page.setViewportSize({width, height:1000});
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({path:'.local/tip-monitor-'+width+'.png', fullPage:true});
    }
    await page.route('**/api/tips/', route => route.fulfill({status:503, body:'offline'}));
    await page.locator('#tip-refresh').click();
    await expect(page.locator('#tip-status')).toContainText('may be stale');
    await expect(page.locator('#tip-rounds tr')).toHaveCount(8);
    expect(errors).toEqual([]);
    await page.goto(process.env.TIP_URL + '/alerts/timeline/');
    await expect(page.locator('#tl-status')).toContainText('Live');
    await expect(page.locator('#tl-tip-summary')).toContainText('3 of the latest 10');
    await expect(page.locator('#tl-tip-summary')).toContainText('no-tip run: 3');
    await expect(page.locator('.tl-recent-chip.is-tip')).toHaveCount(3);
    await expect(page.locator('tr[data-track="number"] .tl-tip-game')).toHaveCount(3);
    await expect(page.locator('tr[data-track="row"] .tl-tip-game')).toHaveCount(3);
    const marked = page.locator('.tl-recent-chip.is-tip').first();
    await expect(marked).toHaveAttribute('aria-label', /TIP: 100 diamonds/);
    expect(await marked.locator('.tl-recent-circle').evaluate(n => getComputedStyle(n).borderTopColor)).toBe('rgb(245, 197, 66)');
    for (let mode = 0; mode < 9; mode++) {
      await page.selectOption('#tl-recent-select', String(mode));
      await expect(page.locator('.tl-recent-circle .tl-tip-star')).toHaveCount(3);
    }
    await page.selectOption('#tl-recent-select', '0');
    for (const width of [1440, 390]) {
      await page.setViewportSize({width, height:1000});
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.locator('#tl-recent-results').screenshot({path:'.local/tip-timeline-'+width+'.png'});
    }
    expect(errors).toEqual([]);
    console.log('Tip browser checks passed: settlements, queue, gold/star markers in all timeline modes, density, desktop/mobile, and offline state.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
'''


def main():
    with tempfile.TemporaryDirectory(prefix='lucky28-tip-ui-') as directory:
        env = {**os.environ, 'LUCKY28_DB_PATH': str(Path(directory) / 'source.sqlite3'),
               'ALERT_STATE_DIR': str(Path(directory) / 'alerts'), 'ALERT_TELEGRAM_ENABLED': 'false',
               'ALERT_TELEGRAM_BOT_TOKEN': '', 'TIP_MONITOR_ID': 'lucky28'}
        manage = [sys.executable, str(ROOT / 'django_lucky28/manage.py')]
        subprocess.run(manage + ['migrate', '--noinput'], cwd=ROOT, env=env, check=True, capture_output=True)
        seed = '''
from games.services.tips import TipMonitor
monitor = TipMonitor()
for i in range(1, 9):
    monitor.ingest(dict(gameId=f'game-{i}', sequence=i, winningNumber=4,
        totalBets=23977479, totalPrizes=23776191 if i == 1 else 23977479,
        settlementFinal=True, totalsComplete=True))
monitor.ingest(dict(gameId='game-8', sequence=8, winningNumber=4,
    totalBets=23977479, totalPrizes=1, settlementFinal=True, totalsComplete=True))
from games.models import GameRound, AlertRule
from games.services.alert_engine import tip_rules, evaluate_rules
from games.services.alerts import game_facts
from games.services.card_timeline import snapshot_from_games
from games.services.alert_presentation import render_card, format_message
from django.utils import timezone
from datetime import timedelta
from pathlib import Path
now = timezone.now()
games = [GameRound.objects.create(game_no=f'20261027{i:04}', game_type='lucky28', winning_number=i,
    has_winner=True, status=3, winner_event_ts=now-timedelta(seconds=20-i),
    winner_raw={'bet_total_energy':1000, 'win_total_energy':900 if i in (2,4,7) else 1000}) for i in range(1,11)]
games.reverse()
rules = [AlertRule.objects.create(**rule) for rule in tip_rules()]
matches = evaluate_rules(rules, game_facts(games))
payload = dict(game_no='202610270011', captured_at=now.isoformat(), matches=[matches[-1]], global_timeline=snapshot_from_games(games))
Path('.local').mkdir(exist_ok=True)
Path('.local/tip-density-alert.jpg').write_bytes(render_card(payload))
Path('.local/tip-density-alert.txt').write_text(format_message(payload, limit=1024))
'''
        subprocess.run(manage + ['shell', '-c', seed], cwd=ROOT, env=env, check=True, capture_output=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env['TIP_URL'] = f'http://127.0.0.1:{port}'
        with (Path(directory) / 'server.log').open('wb') as log:
            server = subprocess.Popen(manage + ['runserver', f'127.0.0.1:{port}', '--noreload'],
                                      cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                for _ in range(60):
                    try:
                        with urllib.request.urlopen(env['TIP_URL'] + '/api/tips/', timeout=1):
                            break
                    except OSError:
                        if server.poll() is not None:
                            raise RuntimeError((Path(directory) / 'server.log').read_text())
                        time.sleep(0.2)
                else:
                    raise RuntimeError('Test server did not start.')
                (ROOT / '.local').mkdir(exist_ok=True)
                subprocess.run(['node', '-e', BROWSER], cwd=ROOT, env=env, check=True)
            finally:
                server.terminate()
                server.wait(timeout=10)


if __name__ == '__main__':
    main()
