"""Browser verification against an isolated database; never touches live results."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
BROWSER_CHECK = r'''
const { chromium, expect } = require('./chamet_logger_standalone/node_modules/@playwright/test');
const { execFileSync } = require('child_process');
(async () => {
  const browser = await chromium.launch({channel: 'chrome', headless: true});
  try {
    const context = await browser.newContext();
    const page = await context.newPage({viewport: {width: 1440, height: 1050}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const base = process.env.TIMELINE_TEST_URL;
    await page.goto(base + '/alerts/timeline/');
    await expect(page.locator('#tl-status')).toContainText('Live');
    await expect(page.locator('#tl-range')).toHaveText('Games 1–25 of 150 / 150 · newest first');
    await expect(page.locator('tr[data-track]')).toHaveCount(11);
    await expect(page.locator('tr[data-track="size"] .tl-dot')).toHaveCount(25);
    await page.locator('tr[data-track="size"] .tl-dot').first().click();
    await expect(page.locator('#tl-detail')).toContainText('Game #R159');
    await expect(page.locator('#tl-detail')).toContainText('Number 19');
    await expect(page.locator('#tl-detail')).toContainText('Size: Big');
    for (let i = 0; i < 5; i++) await page.getByRole('button', {name:'Show older games'}).click();
    await expect(page.locator('#tl-range')).toHaveText('Games 126–150 of 150 / 150 · newest first');
    await expect(page.getByRole('button', {name:'Show older games'})).toBeDisabled();
    await page.locator('tr[data-track="size"]').getByRole('button', {name:'Collapse'}).click();
    await expect(page.locator('tr[data-track="size"] .tl-dot')).toHaveCount(0);
    await page.locator('tr[data-track="size"]').getByRole('button', {name:'Expand'}).click();
    await expect(page.locator('tr[data-track="size"] .tl-dot')).toHaveCount(25);
    await page.locator('tr[data-track="size"]').getByRole('button', {name:'Reset', exact:true}).click();
    await expect(page.locator('tr[data-track="size"] .tl-dot')).toHaveCount(0);
    await expect(page.locator('tr[data-track="parity"] .tl-dot')).toHaveCount(25);
    const other = await browser.newContext();
    const independent = await other.request.get(base + '/api/trackers/live/?tracks=size');
    if ((await independent.json()).tracks[0].timeline.length !== 150) throw new Error('Reset leaked to another session');
    await other.close();
    await page.locator('tr[data-track="size"]').getByRole('button', {name:'Restore history'}).click();
    await expect(page.locator('tr[data-track="size"] .tl-dot')).toHaveCount(25);
    await page.getByText('Choose tracks', {exact:true}).click();
    await page.getByLabel('Board columns', {exact:true}).uncheck();
    await expect(page.locator('tr[data-track="column"]')).toHaveCount(0);
    await page.reload();
    await expect(page.locator('#tl-status')).toContainText('Live');
    await expect(page.locator('tr[data-track="column"]')).toHaveCount(0);
    await page.evaluate(() => window.timelinePageMarker = 'same document');
    execFileSync(process.env.TIMELINE_TEST_PYTHON, ['django_lucky28/manage.py', 'shell', '-c',
      'from games.models import GameRound; from django.utils import timezone; GameRound.objects.create(game_no="R160", game_type="lucky28", winning_number=27, has_winner=True, status=3, winner_event_ts=timezone.now())'], {stdio:'pipe'});
    await expect(page.locator('#tl-status')).toContainText('#R160', {timeout:12000});
    await expect(page.locator('#tl-range')).toContainText('of 150 / 150');
    if (await page.evaluate(() => window.timelinePageMarker) !== 'same document') throw new Error('Polling reloaded the page');
    await page.getByRole('button', {name:'Pause', exact:true}).click();
    await expect(page.locator('#tl-status')).toContainText('Paused');
    await page.getByRole('button', {name:'Resume', exact:true}).click();
    await expect(page.locator('#tl-status')).toContainText('Live');
    await page.screenshot({path:'.local/timeline-desktop.png', fullPage:true});
    await page.route('**/api/trackers/live/**', route => route.fulfill({status:503, body:'unavailable'}));
    await page.getByRole('button', {name:'Refresh now'}).click();
    await expect(page.locator('#tl-status')).toContainText('Refresh failed');
    await expect(page.locator('tr[data-track="size"] .tl-dot')).toHaveCount(25);
    await page.unroute('**/api/trackers/live/**');
    await page.getByRole('button', {name:'Refresh now'}).click();
    await expect(page.locator('#tl-status')).toContainText('Live');
    await page.setViewportSize({width:390, height:844});
    await page.locator('#global-timeline').scrollIntoViewIfNeeded();
    if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) throw new Error('Timeline overflows mobile viewport');
    await page.screenshot({path:'.local/timeline-mobile.png', fullPage:true});
    await page.goto(base + '/analysis/');
    await expect(page.locator('#tl-status')).toContainText('Live');
    await page.locator('tr[data-track="parity"]').getByRole('button', {name:'Reset', exact:true}).click();
    await expect(page.locator('tr[data-track="parity"] .tl-dot')).toHaveCount(0);
    // Exact specification examples, isolated from real results and Telegram.
    const shell = code => execFileSync(process.env.TIMELINE_TEST_PYTHON, ['django_lucky28/manage.py','shell','-c',code],{stdio:'pipe'});
    const seed=(stream,prefix,numbers)=>shell(`from games.models import GameRound; from django.utils import timezone; from datetime import timedelta; base=timezone.now()-timedelta(minutes=30); [GameRound.objects.create(game_no=f"${prefix}{i}",game_type="${stream}",winning_number=n,has_winner=True,status=3,winner_event_ts=base+timedelta(seconds=i)) for i,n in enumerate(${JSON.stringify(numbers)})]`);
    const append=(stream,id,n)=>shell(`from games.models import GameRound; from django.utils import timezone; GameRound.objects.create(game_no="${id}",game_type="${stream}",winning_number=${n},has_winner=True,status=3,winner_event_ts=timezone.now())`);
    const refresh=async()=>{await page.getByRole('button',{name:'Refresh now',exact:true}).click();await expect(page.locator('#tl-status')).toContainText('Live');};
    seed('palette','P',[16,14,19,15,18,19,14,4,13,9]);
    seed('streak','S',[14,5,7,9]);
    await page.goto(base+'/alerts/timeline/');await expect(page.locator('#tl-status')).toContainText('Live');
    await page.selectOption('#tl-stream','palette');
    await expect(page.locator('#tl-selection-status')).toContainText('8 selected · 8 recent distinct');
    const tile=n=>page.locator(`#tl-palette [data-number="${n}"]`);
    const checkbox=n=>tile(n).locator('input');
    const inspect=n=>tile(n).locator('.tl-tile-inspect').click();
    const selectedNumbers=()=>page.locator('.tl-number-tile input:checked').evaluateAll(nodes=>nodes.map(node=>Number(node.closest('[data-number]').dataset.number)));
    const qualified=()=>page.locator('.tl-number-tile.filter-match').evaluateAll(nodes=>nodes.map(node=>Number(node.dataset.number)));
    const filter=id=>page.locator(`[data-filter="${id}"]`).click();
    const clearFilters=()=>filter('all');
    expect(await selectedNumbers()).toEqual([4,9,13,14,15,16,18,19]);
    await expect(tile(14)).toContainText('2 hits');await expect(tile(19)).toContainText('2 hits');
    await page.getByRole('button',{name:'Unselect last 10',exact:true}).click();expect(await selectedNumbers()).toEqual([]);
    await expect(page.locator('#tl-selection-status')).toContainText('Mode: Manual');
    await checkbox(20).check();await checkbox(0).check();await inspect(27);
    await expect(tile(27)).toHaveClass(/focused/);expect(await selectedNumbers()).toEqual([0,20]);
    append('palette','P10',20);await expect(tile(20)).toHaveClass(/present/,{timeout:12000});
    expect(await selectedNumbers()).toEqual([0,20]);await expect(tile(27)).toHaveClass(/focused/);
    await page.getByRole('button',{name:'Unselect last 10',exact:true}).click();expect(await selectedNumbers()).toEqual([0]);
    await page.getByRole('button',{name:'Clear selection',exact:true}).click();expect(await selectedNumbers()).toEqual([]);
    await page.getByRole('button',{name:'Select absent numbers',exact:true}).click();
    expect(await selectedNumbers()).toEqual([0,1,2,3,5,6,7,8,10,11,12,16,17,21,22,23,24,25,26,27]);
    await page.getByRole('button',{name:'Restore last 10',exact:true}).click();await expect(page.locator('#tl-selection-status')).toContainText('Mode: Auto last 10');
    append('palette','P11',0);await expect(tile(0)).toHaveClass(/present/,{timeout:12000});await expect(checkbox(0)).toBeChecked();
    const selectionBefore=await selectedNumbers();await refresh();expect(await selectedNumbers()).toEqual(selectionBefore);
    await clearFilters();await filter('S');expect(await qualified()).toEqual(Array.from({length:14},(_,i)=>i));
    await expect(tile(2)).not.toHaveClass(/present/);await expect(tile(2)).toHaveClass(/filter-match/);
    const singleColor=await tile(0).evaluate(node=>node.style.getPropertyValue('--tile-fill'));
    await filter('E');expect((await qualified()).length).toBe(21);
    for(const n of [0,2,4,6,8,10,12])await expect(tile(n).locator('.tl-overlap')).toHaveText('×2 matches');
    await expect(tile(1).locator('.tl-overlap')).toHaveText('1 match');
    const overlapColor=await tile(0).evaluate(node=>node.style.getPropertyValue('--tile-fill'));
    expect(overlapColor).not.toBe(singleColor);expect(overlapColor).toContain('linear-gradient');
    await page.getByRole('button',{name:'All active filters',exact:true}).click();expect(await qualified()).toEqual([0,2,4,6,8,10,12]);
    await expect(tile(1).locator('.tl-match-strips')).toContainText('S');expect(await selectedNumbers()).toEqual(selectionBefore);
    await filter('E');expect((await qualified()).length).toBe(14);
    await filter('B');expect(await qualified()).toEqual([]);await expect(page.locator('#tl-filter-summary')).toContainText('No numbers match all active filters');
    await clearFilters();expect((await qualified()).length).toBe(28);expect(await selectedNumbers()).toEqual(selectionBefore);await expect(tile(27)).toHaveClass(/focused/);
    await page.getByRole('button',{name:'Any match',exact:true}).click();await filter('S');await filter('E');await filter('SE');
    await page.locator('.tl-more-filters summary').click();
    for(const id of ['G01','R01','C01','edges'])await page.locator(`[data-filter-id="${id}"]`).check();
    await expect(tile(0).locator('.tl-overlap')).toHaveText('×7 matches');await expect(tile(0).locator('.tl-match-strips span')).toHaveCount(3);
    await expect(tile(0).locator('.tl-match-strips')).toContainText('+4 more');
    await tile(0).locator('.tl-overlap').click();await expect(page.locator('#tl-match-details')).toBeVisible();
    await expect(page.locator('#tl-match-details')).toContainText('Red');await expect(page.locator('#tl-match-details')).toContainText('Column 1');
    const popupBox=await page.locator('#tl-match-details').boundingBox();
    expect(popupBox.y).toBeGreaterThanOrEqual(0);expect(popupBox.y+popupBox.height).toBeLessThanOrEqual(900);
    await page.getByRole('button',{name:'Close matches',exact:true}).click();await expect(page.locator('#tl-match-details')).toBeHidden();
    await tile(0).locator('.tl-overlap').focus();await expect(page.locator('#tl-match-details')).toBeVisible();
    await tile(0).locator('.tl-overlap').press('Escape');await expect(page.locator('#tl-match-details')).toBeHidden();
    await page.getByRole('button',{name:'Remove Even filter',exact:true}).click();await expect(tile(0).locator('.tl-overlap')).toHaveText('×6 matches');
    const beforeMetrics=await page.locator('[data-gap] strong').allTextContents();await clearFilters();
    expect(await page.locator('[data-gap] strong').allTextContents()).toEqual(beforeMetrics);
    await expect(tile(0).locator('.tl-overlap')).toBeHidden();
    // Selection is per stream in this page; full reload deliberately starts Auto.
    await page.getByRole('button',{name:'Clear selection',exact:true}).click();await checkbox(22).check();
    await page.selectOption('#tl-stream','streak');await expect(page.locator('#tl-status')).toContainText('#S3');
    await expect(page.locator('.tl-board-gap')).toHaveCount(11);await expect(page.locator('.tl-board-streak')).toHaveCount(11);
    await expect(page.locator('[data-streak]')).toHaveCount(8);await expect(page.locator('[data-gap]')).toHaveCount(8);
    for(const key of ['S','O','SO']){
      await expect(page.locator(`[data-streak="${key}"] strong`)).toHaveText('3');
      await expect(page.locator(`[data-streak="${key}"]`)).toHaveClass(/metric-max-streak/);
    }
    const feed=await(await page.request.get(base+'/api/trackers/live/?stream=streak&tracks=')).json();
    const top=feed.group_stats.filter(group=>['S','B','E','O','SE','SO','BE','BO'].includes(group.key));
    const maxGap=Math.max(...top.map(group=>group.current_gap));
    for(const group of top){
      if(group.current_gap===maxGap)await expect(page.locator(`[data-gap="${group.key}"]`)).toHaveClass(/metric-max-gap/);
      else await expect(page.locator(`[data-gap="${group.key}"]`)).not.toHaveClass(/metric-max-gap/);
    }
    append('streak','S4',16);await expect(page.locator('#tl-status')).toContainText('#S4',{timeout:12000});
    for(const key of ['S','O','SO'])await expect(page.locator(`[data-streak="${key}"] strong`)).toHaveText('0');
    await page.locator('.tl-board-gap[data-group="R01"]').click();await expect(page.locator('#tl-number-detail')).toContainText('Current consecutive streak');
    await page.setViewportSize({width:1440,height:1100});
    await page.getByRole('tab',{name:'Colors',exact:true}).click();await page.getByRole('button',{name:'Current gaps',exact:true}).click();
    const chartValues=()=>page.locator('#tl-gap-chart .tl-chart-count strong').allTextContents().then(values=>values.map(parseFloat));
    let values=await chartValues();expect(values).toEqual([...values].sort((a,b)=>b-a));
    await page.selectOption('#tl-gap-sort','asc');values=await chartValues();expect(values).toEqual([...values].sort((a,b)=>a-b));
    const focusedBar=page.locator('#tl-gap-chart [data-chart-id="G02"]');await focusedBar.focus();
    await page.evaluate(()=>document.querySelector('#tl-refresh').click());await expect(focusedBar).toBeFocused();
    await page.selectOption('#tl-gap-sort','natural');expect(await page.locator('#tl-gap-chart [data-chart-id]').evaluateAll(nodes=>nodes.map(node=>node.dataset.chartId))).toEqual(['G01','G02','G03','G04','G05','G06','G07']);
    const measurements=await page.locator('#tl-gap-chart .tl-gap-bar').evaluateAll(nodes=>nodes.map(node=>({value:parseFloat(node.querySelector('strong').textContent),width:parseFloat(node.querySelector('i').style.width),label:node.querySelector('.tl-gap-bar-label').getBoundingClientRect().x,count:node.querySelector('.tl-chart-count').getBoundingClientRect().x,bar:node.querySelector('.tl-gap-bar-track').getBoundingClientRect().x})));
    const maximum=Math.max(1,...measurements.map(row=>row.value));
    for(const row of measurements){expect(Math.abs(row.width-row.value/maximum*100)).toBeLessThan(.01);expect(row.count).toBeGreaterThan(row.label);expect(row.bar).toBeGreaterThan(row.count);}
    await page.selectOption('#tl-stream','palette');await expect(page.locator('#tl-status')).toContainText('#P11');expect(await selectedNumbers()).toEqual([22]);
    await page.reload();await expect(page.locator('#tl-status')).toContainText('Live');await page.selectOption('#tl-stream','palette');await expect(page.locator('#tl-status')).toContainText('#P11');
    await expect(page.locator('#tl-selection-status')).toContainText('Mode: Auto last 10');expect(await selectedNumbers()).toEqual(selectionBefore);
    // Corrections rebuild selection and metrics from the same ordered snapshot.
    shell('from games.models import GameRound; GameRound.objects.filter(game_no="P11").update(winning_number=2)');
    await expect(tile(2)).toHaveClass(/present/,{timeout:12000});await expect(tile(0)).not.toHaveClass(/present/);
    await expect(checkbox(2)).toBeChecked();await expect(checkbox(0)).not.toBeChecked();
    await filter('S');await filter('E');await inspect(2);
    await page.setViewportSize({width:1440,height:1100});await page.addStyleTag({content:'.navbar{visibility:hidden!important}'});
    await page.locator('.tl-palette-section').screenshot({path:'.local/palette-v2-desktop.png'});
    await page.locator('#tl-gap-analytics').screenshot({path:'.local/palette-v2-charts.png'});
    for(const width of [768,390]){
      await page.setViewportSize({width,height:900});
      if(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth))throw Error('Page overflows narrow screen');
      await expect(page.locator('.tl-compact-metrics')).toBeVisible();await expect(page.locator('[data-summary-group]')).toHaveCount(11);
      const boardBox=await page.locator('.tl-board-scroller').evaluate(node=>({width:node.clientWidth,scroll:node.scrollWidth}));expect(boardBox.scroll).toBeGreaterThan(boardBox.width);
      await page.locator('.tl-board-scroller').evaluate(node=>node.scrollLeft=node.scrollWidth);
      await expect(page.locator('.tl-row-streaks')).toBeVisible();
    }
    await page.locator('.tl-palette-section').screenshot({path:'.local/palette-v2-mobile.png'});
    await page.locator('.tl-board-scroller').evaluate(node=>node.scrollLeft=0);
    // Long, history-limited and interrupted runs must fit the mobile metric rails.
    seed('wide','W',Array(999).fill(0));await refresh();await page.selectOption('#tl-stream','wide');
    await expect(page.locator('[data-gap="B"] strong')).toHaveText('999+');
    await expect(page.locator('[data-streak="SE"] strong')).toHaveText('999+');
    const metricFits=await page.locator('[data-gap="B"] strong').evaluate(node=>node.scrollWidth<=node.clientWidth);
    expect(metricFits).toBe(true);
    shell('from games.models import GameRound; GameRound.objects.filter(game_no="W990").delete()');
    await expect(page.locator('[data-streak="SE"] strong')).toHaveText('8*',{timeout:12000});
    await expect(page.locator('[data-streak="SE"]')).toContainText('MAX observed');
    if(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth))throw Error('Long metrics overflow phone');
    shell('from games.models import GameRound; GameRound.objects.create(game_no="EMPTY1",game_type="empty",status=2)');
    await refresh();await page.selectOption('#tl-stream','empty');await expect(page.locator('#tl-palette-status')).toContainText('No completed results');
    await expect(page.locator('[data-gap="S"] strong')).toHaveText('N/A');await expect(page.locator('[data-streak="S"] strong')).toHaveText('N/A');
    await expect(page.locator('[data-gap].metric-max-gap')).toHaveCount(0);expect(await selectedNumbers()).toEqual([]);
    await page.selectOption('#tl-stream','palette');await expect(page.locator('#tl-status')).toContainText('#P11');
    await page.getByRole('button',{name:'Clear selection',exact:true}).click();await checkbox(0).check();
    await page.route('**/api/trackers/live/**',route=>route.fulfill({status:503,body:'offline'}));
    await page.getByRole('button',{name:'Refresh now',exact:true}).click();await expect(page.locator('#tl-palette-status')).toContainText('last loaded palette');
    expect(await selectedNumbers()).toEqual([0]);await expect(page.locator('#tl-gap-status')).toContainText('last loaded gap history');
    await page.unroute('**/api/trackers/live/**');await refresh();expect(await selectedNumbers()).toEqual([0]);
    await page.route('**/api/trackers/live/**',route=>route.fulfill({status:503,body:'offline'}));await page.reload();
    await expect(page.locator('#tl-palette-status')).toContainText('History unavailable');await expect(page.locator('.tl-number-tile input:disabled')).toHaveCount(28);
    await expect(page.locator('[data-gap="SE"] strong')).toHaveText('N/A');
    await page.unroute('**/api/trackers/live/**');await refresh();
    if (errors.length) throw new Error(errors.join('\n'));
    console.log('Palette v2 specification checks passed: selection modes, all-number filters and overlaps, streak rails, maxima, sorting, corrections, keyboard/touch and stale recovery. Prior timeline checks: row/column/filter gaps, group inspection, tab keyboard controls, proportional bars, live group corrections, palette filters and persistence, zero, desktop/mobile layout, timeline paging, reset/restore and connection recovery.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode=1;});
'''


def main():
    with tempfile.TemporaryDirectory(prefix='lucky28-timeline-ui-') as directory:
        environment = os.environ.copy()
        environment.update(LUCKY28_DB_PATH=str(Path(directory) / 'test.sqlite3'),
                           ALERT_STATE_DIR=str(Path(directory) / 'alerts'),
                           ALERT_TELEGRAM_ENABLED='false', ALERT_TELEGRAM_BOT_TOKEN='',
                           TIMELINE_TEST_PYTHON=sys.executable)
        manage = [sys.executable, str(ROOT / 'django_lucky28/manage.py')]
        subprocess.run(manage + ['migrate', '--noinput'], cwd=ROOT, env=environment, check=True, capture_output=True)
        subprocess.run(manage + ['shell', '-c',
            'from games.models import GameRound; from django.utils import timezone; from datetime import timedelta; '
            'base=timezone.now()-timedelta(minutes=200); '
            '[GameRound.objects.create(game_no=f"R{i}", game_type="lucky28", has_winner=True, '
            'winning_number=i%28, status=3, winner_event_ts=base+timedelta(minutes=i)) for i in range(160)]'],
            cwd=ROOT, env=environment, check=True, capture_output=True)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        environment['TIMELINE_TEST_URL'] = f'http://127.0.0.1:{port}'
        with (Path(directory) / 'server.log').open('wb') as log:
            server = subprocess.Popen(manage + ['runserver', f'127.0.0.1:{port}', '--noreload'], cwd=ROOT,
                                      env=environment, stdout=log, stderr=log)
            try:
                for _ in range(50):
                    try:
                        with urllib.request.urlopen(environment['TIMELINE_TEST_URL'] + '/alerts/timeline/', timeout=1):
                            break
                    except OSError:
                        time.sleep(.2)
                (ROOT / '.local').mkdir(exist_ok=True)
                subprocess.run(['node', '-e', BROWSER_CHECK], cwd=ROOT, env=environment, check=True)
            finally:
                server.terminate()
                server.wait(timeout=10)


if __name__ == '__main__':
    main()
