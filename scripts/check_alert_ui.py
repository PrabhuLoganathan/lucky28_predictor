"""Exercise alert management in Chrome against an isolated temporary database."""
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
(async () => {
  const browser = await chromium.launch({channel: 'chrome', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1050}});
    page.setDefaultTimeout(15000);
    page.setDefaultNavigationTimeout(15000);
    const base = process.env.ALERT_TEST_URL;
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + '/alerts/groups/settings/');
    await expect(page.getByLabel('Red threshold', {exact:true})).toHaveValue('');
    await page.getByLabel('Apply to all absence thresholds', {exact:true}).fill('3');
    await page.getByRole('button', {name:'Populate fields', exact:true}).click();
    await expect(page.getByLabel('Grey threshold', {exact:true})).toHaveValue('3');
    await page.getByLabel('Enable group absence delivery', {exact:true}).check();
    await page.getByLabel('Enable Red', {exact:true}).check();
    await page.getByLabel('Red threshold', {exact:true}).fill('1.5');
    await page.getByRole('button', {name:'Save settings', exact:true}).click();
    if (await page.getByLabel('Red threshold', {exact:true}).evaluate(el => el.validity.valid)) throw new Error('Decimal threshold accepted');
    await page.getByLabel('Red threshold', {exact:true}).fill(' 3 ');
    await page.getByRole('button', {name:'Save settings', exact:true}).click();
    await expect(page.getByText('Group absence settings saved and applied immediately.')).toBeVisible();
    await page.reload();
    await expect(page.getByLabel('Red threshold', {exact:true})).toHaveValue('3');
    await page.getByLabel('Red threshold', {exact:true}).fill('99');
    await page.getByRole('link', {name:'Cancel', exact:true}).click();
    await expect(page.getByText('Threshold reached', {exact:true})).toBeVisible();
    await expect(page.getByText('Alert already recorded this absence')).toBeVisible();
    await page.screenshot({path:'.local/group-absence-desktop.png', fullPage:true});
    await page.getByRole('link', {name:'Edit absence & ending thresholds', exact:true}).click();
    await expect(page.getByLabel('Red threshold', {exact:true})).toHaveValue('3');
    await page.setViewportSize({width:390, height:844});
    await page.getByLabel('Red threshold', {exact:true}).scrollIntoViewIfNeeded();
    await page.screenshot({path:'.local/group-absence-settings-mobile.png'});
    await expect(page.getByRole('heading', {name:'Group Absence Alerts — settings', exact:true})).toHaveCount(1);
    await page.setViewportSize({width:1440, height:1050});
    await page.goto(base + '/alerts/windows/');
    await expect(page.getByText('All 10 results are different — no number repeats.', {exact:true})).toBeVisible();
    await expect(page.getByLabel('Enable drought alerts', {exact:true})).not.toBeChecked();
    await page.getByLabel('Enable drought alerts', {exact:true}).check();
    await page.getByLabel('Enable repeat alerts', {exact:true}).check();
    await page.getByRole('button', {name:'Save settings', exact:true}).click();
    await expect(page.getByText('10-game alert settings saved and applied immediately.')).toBeVisible();
    await expect(page.getByText('None — all different', {exact:true})).toBeVisible();
    await page.reload();
    await expect(page.getByLabel('Enable repeat alerts', {exact:true})).toBeChecked();
    await page.getByLabel('Enable repeat alerts', {exact:true}).uncheck();
    await page.getByRole('link', {name:'Cancel', exact:true}).click();
    await expect(page.getByLabel('Enable repeat alerts', {exact:true})).toBeChecked();
    await page.screenshot({path:'.local/window-alerts-desktop.png', fullPage:true});
    await page.setViewportSize({width:390, height:844});
    await page.getByLabel('Enable drought alerts', {exact:true}).scrollIntoViewIfNeeded();
    await page.screenshot({path:'.local/window-alerts-mobile.png'});
    await page.setViewportSize({width:1440, height:1050});
    await page.goto(base + '/alerts/categories/settings/');
    await expect(page.getByLabel('Send a follow-up when an alerted absence or streak ends', {exact:true})).toBeChecked();
    await page.getByLabel('Absence threshold for all groups', {exact:true}).fill('3');
    await page.getByRole('button', {name:'Populate absence thresholds', exact:true}).click();
    await page.getByLabel('Streak threshold for all groups', {exact:true}).fill('3');
    await page.getByRole('button', {name:'Populate streak thresholds', exact:true}).click();
    await page.getByRole('button', {name:'Enable all absence', exact:true}).click();
    await page.getByRole('button', {name:'Enable all streaks', exact:true}).click();
    await page.getByLabel('Enable row, column and category delivery', {exact:true}).check();
    await page.getByLabel('Row 1 absence threshold', {exact:true}).fill('1.5');
    await page.getByRole('button', {name:'Save settings', exact:true}).click();
    if (await page.getByLabel('Row 1 absence threshold', {exact:true}).evaluate(el => el.validity.valid)) throw new Error('Category decimal threshold accepted');
    await page.getByLabel('Row 1 absence threshold', {exact:true}).fill(' 3 ');
    await page.getByRole('button', {name:'Save settings', exact:true}).click();
    await expect(page.getByText('Row, column and category settings saved and applied immediately.')).toBeVisible();
    await page.reload();
    await expect(page.locator('.absence-enabled:checked')).toHaveCount(19);
    await page.getByLabel('Send a follow-up when an alerted absence or streak ends', {exact:true}).uncheck();
    await page.getByRole('button', {name:'Save settings', exact:true}).click();
    await page.reload();
    await expect(page.getByLabel('Send a follow-up when an alerted absence or streak ends', {exact:true})).not.toBeChecked();
    await page.getByLabel('Send a follow-up when an alerted absence or streak ends', {exact:true}).check();
    await page.getByRole('button', {name:'Save settings', exact:true}).click();
    await page.reload();
    await expect(page.getByLabel('Send a follow-up when an alerted absence or streak ends', {exact:true})).toBeChecked();
    await expect(page.locator('.streak-enabled:checked')).toHaveCount(19);
    await expect(page.getByLabel('Column 7 streak threshold', {exact:true})).toHaveValue('3');
    await expect(page.getByLabel('Extreme edges · 0–5, 22–27 absence threshold', {exact:true})).toHaveValue('3');
    await expect(page.getByLabel('Inner board center streak threshold', {exact:true})).toHaveValue('3');
    await page.getByLabel('Column 7 streak threshold', {exact:true}).fill('99');
    await page.getByRole('link', {name:'Cancel', exact:true}).click();
    await expect(page.locator('table tbody tr')).toHaveCount(19);
    await expect(page.getByText('SE — Small Even', {exact:true})).toBeVisible();
    await page.screenshot({path:'.local/category-alerts-desktop.png', fullPage:true});
    await page.getByRole('link', {name:'Edit category thresholds', exact:true}).click();
    await expect(page.getByLabel('Column 7 streak threshold', {exact:true})).toHaveValue('3');
    await page.setViewportSize({width:390, height:844});
    await page.getByLabel('Row 1 absence threshold', {exact:true}).scrollIntoViewIfNeeded();
    await page.screenshot({path:'.local/category-settings-mobile.png'});
    if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) throw new Error('Category settings overflow viewport');
    await page.setViewportSize({width:1440, height:1050});
    await page.goto(base + '/alerts/rules/new/');
    await page.getByLabel('Rule name', {exact:true}).fill('Browser smoke rule');
    await page.getByLabel('Matching values', {exact:true}).selectOption('Big');
    await page.getByLabel('Trigger count', {exact:true}).fill('3');
    await page.getByRole('button', {name:'Save', exact:true}).click();
    await expect(page).toHaveURL(base + '/alerts/rules/');
    await page.getByLabel('Search rules', {exact:true}).fill('Browser smoke');
    await page.getByRole('button', {name:'Filter', exact:true}).click();
    await page.getByRole('link', {name:'Edit', exact:true}).click();
    await page.getByLabel('Watch', {exact:true}).selectOption('parity');
    await page.getByLabel('Pattern', {exact:true}).selectOption('alternating');
    await page.getByLabel('Matching values', {exact:true}).selectOption(['Odd','Even']);
    await page.getByRole('button', {name:'Save', exact:true}).click();
    await expect(page).toHaveURL(base + '/alerts/rules/');
    await page.getByLabel('Search rules', {exact:true}).fill('Browser smoke');
    await page.getByRole('button', {name:'Filter', exact:true}).click();
    await page.getByRole('button', {name:'Disable Browser smoke rule', exact:true}).click();
    await page.goto(base + '/alerts/destinations/new/');
    await page.getByLabel('Destination name', {exact:true}).fill('Browser test channel');
    await page.getByLabel('Telegram chat ID or channel username', {exact:true}).fill('@test_channel');
    await page.getByRole('button', {name:'Save', exact:true}).click();
    await expect(page).toHaveURL(base + '/alerts/destinations/');
    await expect(page.getByRole('heading', {name:'Browser test channel'})).toBeVisible();
    await page.goto(base + '/alerts/destinations/new/');
    await page.getByLabel('Destination name', {exact:true}).fill('Lucky28(Wheel) - Group Absence Alerts');
    await page.getByLabel('Telegram chat ID or channel username', {exact:true}).fill('@direct_test_channel');
    await page.getByLabel('Destination type', {exact:true}).selectOption('direct');
    await expect(page.getByLabel('Destination level', {exact:true})).toBeHidden();
    await expect(page.getByLabel('Send collection outage warnings', {exact:true})).toBeHidden();
    await page.getByRole('button', {name:'Save', exact:true}).click();
    await expect(page.getByText('Direct only', {exact:true})).toBeVisible();
    await page.goto(base + '/alerts/rules/new/');
    await page.getByLabel('Rule name', {exact:true}).fill('Direct browser rule');
    await page.getByLabel('Pattern', {exact:true}).selectOption('every_game');
    await page.getByRole('group', {name:'Send to', exact:true}).getByLabel('Level hierarchy', {exact:true}).uncheck();
    await page.getByRole('group', {name:'Send to', exact:true}).getByLabel('Lucky28(Wheel) - Group Absence Alerts', {exact:true}).check();
    await expect(page.getByLabel('Minimum destination level', {exact:true})).toBeHidden();
    await page.getByRole('button', {name:'Save', exact:true}).click();
    await page.getByLabel('Search rules', {exact:true}).fill('Direct browser rule');
    await page.getByRole('button', {name:'Filter', exact:true}).click();
    await expect(page.getByText('Only: Lucky28(Wheel) - Group Absence Alerts', {exact:true})).toBeVisible();
    await page.getByRole('link', {name:'Edit', exact:true}).click();
    await expect(page.getByLabel('Minimum destination level', {exact:true})).toBeHidden();
    await page.getByRole('group', {name:'Send to', exact:true}).getByLabel('Level hierarchy', {exact:true}).check();
    await page.getByRole('group', {name:'Send to', exact:true}).getByLabel('Browser test channel', {exact:true}).check();
    await expect(page.getByLabel('Minimum destination level', {exact:true})).toBeVisible();
    await page.getByRole('button', {name:'Save', exact:true}).click();
    await page.getByLabel('Search rules', {exact:true}).fill('Direct browser rule');
    await page.getByRole('button', {name:'Filter', exact:true}).click();
    await expect(page.getByText('+ Lucky28(Wheel) - Group Absence Alerts', {exact:true})).toBeVisible();
    await expect(page.getByText('Level 1 and above', {exact:true})).toBeVisible();
    await page.getByRole('link', {name:'Edit', exact:true}).click();
    for (const name of ['Level hierarchy', 'Browser test channel', 'Lucky28(Wheel) - Group Absence Alerts']) {
      await expect(page.getByRole('group', {name:'Send to', exact:true}).getByLabel(name, {exact:true})).toBeChecked();
    }
    await page.screenshot({path:'.local/checkbox-routing-rule-desktop.png', fullPage:true});
    await page.setViewportSize({width:390, height:844});
    await page.getByRole('group', {name:'Send to', exact:true}).scrollIntoViewIfNeeded();
    await page.screenshot({path:'.local/checkbox-routing-rule-mobile.png'});
    await page.setViewportSize({width:1440, height:1050});
    await page.goto(base + '/alerts/groups/settings/');
    const bulk = page.getByRole('group', {name:'Send all groups to', exact:true});
    await bulk.getByLabel('Lucky28(Wheel) - Group Absence Alerts', {exact:true}).check();
    await bulk.getByLabel('Level hierarchy', {exact:true}).check();
    await page.getByRole('button', {name:'Populate destinations', exact:true}).click();
    await page.getByRole('button', {name:'Save settings', exact:true}).click();
    await page.reload();
    for (const group of ['Red', 'Grey']) {
      const recipients = page.getByRole('group', {name:group + ': send to', exact:true});
      await expect(recipients.getByLabel('Lucky28(Wheel) - Group Absence Alerts', {exact:true})).toBeChecked();
      await expect(recipients.getByLabel('Level hierarchy', {exact:true})).toBeChecked();
    }
    await page.screenshot({path:'.local/direct-routing-groups-desktop.png', fullPage:true});
    await page.setViewportSize({width:390, height:844});
    await page.getByRole('group', {name:'Red: send to', exact:true}).scrollIntoViewIfNeeded();
    await page.screenshot({path:'.local/direct-routing-groups-mobile.png'});
    await page.setViewportSize({width:1440, height:1050});
    await page.goto(base + '/alerts/settings/');
    await page.getByLabel('Telegram bot token', {exact:true}).fill('invalid-secret');
    await page.getByRole('button', {name:'Save settings', exact:true}).click();
    await expect(page.getByText('Enter a valid token supplied by BotFather.')).toBeVisible();
    await expect(page.getByLabel('Telegram bot token', {exact:true})).toHaveValue('');
    await page.getByRole('button', {name:'Save settings', exact:true}).click();
    await page.getByRole('button', {name:'Start worker', exact:true}).click();
    await expect.poll(async () => {
      await page.goto(base + '/alerts/settings/');
      return await page.getByRole('heading', {name:'Running', exact:true}).count();
    }, {timeout:15000}).toBe(1);
    await page.screenshot({path:'.local/alert-settings-desktop.png', fullPage:true});
    // The worker and multiple dashboard tabs must safely share SQLite writes.
    const concurrentResponses = await Promise.all(Array.from({length:12}, (_, i) =>
      page.request.get(base + (i % 2 ? '/alerts/categories/settings/' : '/alerts/categories/'))));
    if (concurrentResponses.some(response => response.status() !== 200)) throw new Error('Concurrent category requests failed');
    await page.getByRole('button', {name:'Stop worker', exact:true}).click();
    await expect.poll(async () => {
      await page.goto(base + '/alerts/settings/');
      return await page.getByRole('heading', {name:'Stopped', exact:true}).count();
    }, {timeout:15000}).toBe(1);
    await page.goto(base + '/alerts/rules/');
    await page.setViewportSize({width:390, height:844});
    await page.screenshot({path:'.local/alert-rules-mobile.png', fullPage:true});
    for (const path of ['/alerts/', '/alerts/deliveries/', '/alerts/destinations/']) {
      const response = await page.goto(base + path);
      if(response.status() !== 200) throw new Error(path + ' failed');
    }
    if(errors.length) throw new Error(errors.join('\n'));
    console.log('Browser checks passed: category settings enable/validate/save/cancel, 10-game alerts save/cancel, group thresholds, validation, save/cancel, alert dashboard, rule create/edit/toggle, destination form, token validation, worker start/stop, desktop/mobile pages.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode=1;});
'''


def main():
    with tempfile.TemporaryDirectory(prefix='lucky28-alert-ui-') as directory:
        environment = os.environ.copy()
        environment.update(LUCKY28_DB_PATH=str(Path(directory) / 'test.sqlite3'),
                           ALERT_STATE_DIR=str(Path(directory) / 'alerts'),
                           ALERT_TELEGRAM_ENABLED='false', ALERT_TELEGRAM_BOT_TOKEN='')
        manage = [sys.executable, str(ROOT / 'django_lucky28/manage.py')]
        for command in [('migrate', '--noinput'), ('seed_alert_rules',)]:
            subprocess.run(manage + list(command), cwd=ROOT, env=environment, check=True, capture_output=True)
        subprocess.run(manage + ['shell', '-c',
            'from games.models import GameRound; from django.utils import timezone; '
            '[GameRound.objects.create(game_no=f"R{100+i}", game_type="lucky28", has_winner=True, '
            'winning_number=n, status=3, winner_event_ts=timezone.now()) for i,n in enumerate([26,8,12,6,0,2,4,10,14,16])]'],
            cwd=ROOT, env=environment, check=True, capture_output=True)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        environment['ALERT_TEST_URL'] = f'http://127.0.0.1:{port}'
        with (Path(directory) / 'server.log').open('wb') as log:
            server = subprocess.Popen(manage + ['runserver', f'127.0.0.1:{port}', '--noreload'], cwd=ROOT,
                                      env=environment, stdout=log, stderr=log)
            try:
                for _ in range(50):
                    try:
                        with urllib.request.urlopen(environment['ALERT_TEST_URL'] + '/alerts/', timeout=1):
                            break
                    except OSError:
                        time.sleep(.2)
                (ROOT / '.local').mkdir(exist_ok=True)
                subprocess.run(['node', '-e', BROWSER_CHECK], cwd=ROOT, env=environment, check=True)
            finally:
                # Stop a test worker even if a browser assertion failed mid-flow.
                subprocess.run(manage + ['shell', '-c', 'from games.services.alert_worker import stop_worker; stop_worker()'],
                               cwd=ROOT, env=environment, capture_output=True)
                time.sleep(2.5)
                server.terminate()
                server.wait(timeout=10)


if __name__ == '__main__':
    main()
