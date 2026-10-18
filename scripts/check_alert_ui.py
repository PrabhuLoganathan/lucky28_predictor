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
    const base = process.env.ALERT_TEST_URL;
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
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
    console.log('Browser checks passed: rule create/edit/toggle, destination form, token validation, worker start/stop, desktop/mobile pages.');
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
