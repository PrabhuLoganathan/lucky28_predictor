"""Exercise color ending settings against a temporary DB; no Telegram sends."""
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
const {chromium,expect}=require('./chamet_logger_standalone/node_modules/@playwright/test');
const {execFileSync}=require('child_process');
(async()=>{const browser=await chromium.launch({channel:'chrome',headless:true});try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.env.ENDING_URL+'/alerts/groups/settings/');
  await expect(page.locator('.ending-threshold')).toHaveCount(7);
  await page.locator('#apply-ending-value').fill('3');
  await page.locator('#apply-all-endings').click();
  for(const value of await page.locator('.ending-threshold').evaluateAll(es=>es.map(e=>e.value))) expect(value).toBe('3');
  await expect(page.locator('#id_G01_threshold')).toHaveValue('');
  await page.locator('#id_enabled').check();
  await page.locator('#id_G01_ending_enabled').check();
  await page.locator('#id_G01_ending_threshold').fill('0');
  expect(await page.locator('#id_G01_ending_threshold').evaluate(e=>e.checkValidity())).toBe(false);
  await page.locator('#id_G01_ending_threshold').fill('3');
  await page.getByRole('button',{name:'Save settings',exact:true}).click();
  await expect(page.getByText('Group absence settings saved and applied immediately.')).toBeVisible();
  await expect(page.locator('#id_G01_ending_threshold')).toHaveValue('3');
  const shell=code=>execFileSync(process.env.ENDING_PYTHON,['django_lucky28/manage.py','shell','-c',code],{stdio:'pipe'});
  shell('from games.models import GameRound; from django.utils import timezone; GameRound.objects.create(game_no="202610250004",game_type="lucky28",has_winner=True,winning_number=0,status=3,winner_event_ts=timezone.now())');
  await page.goto(process.env.ENDING_URL+'/alerts/groups/');
  await expect(page.getByText('Absence ended history',{exact:true})).toBeVisible();
  await expect(page.locator('summary').filter({hasText:'Returned as 0'})).toContainText('3 missed rounds');
  await page.locator('summary').filter({hasText:'Returned as 0'}).click();
  await expect(page.getByText('COLOR ABSENCE ENDED',{exact:true})).toBeVisible();
  for(const width of [1440,1000,390]){
    await page.setViewportSize({width,height:1000});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:'.local/group-endings-'+width+'.png',fullPage:true});
  }
  await page.goto(process.env.ENDING_URL+'/alerts/groups/settings/');
  await page.screenshot({path:'.local/group-ending-settings-mobile.png',fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  console.log('Passed: independent thresholds, bulk fill, invalid input, save/reload, ending evidence and responsive layout; no live database or Telegram used.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
'''


def main():
    with tempfile.TemporaryDirectory(prefix='number-group-ending-') as directory:
        env = {**os.environ, 'LUCKY28_DB_PATH': str(Path(directory)/'source.sqlite3'),
               'ALERT_STATE_DIR': str(Path(directory)/'alerts'), 'ALERT_TELEGRAM_ENABLED': 'false',
               'ALERT_TELEGRAM_BOT_TOKEN': '', 'ENDING_PYTHON': sys.executable}
        manage = [sys.executable, str(ROOT/'django_lucky28/manage.py')]
        subprocess.run(manage+['migrate', '--noinput'], cwd=ROOT, env=env, check=True, capture_output=True)
        seed = ('from games.models import GameRound; from django.utils import timezone; from datetime import timedelta; '
                'now=timezone.now(); '
                '[GameRound.objects.create(game_no=f"20261025{i:04}",game_type="lucky28",has_winner=True,'
                'winning_number=n,status=3,winner_event_ts=now-timedelta(seconds=10-i)) for i,n in enumerate([0,8,8,8])]')
        subprocess.run(manage+['shell', '-c', seed], cwd=ROOT, env=env, check=True, capture_output=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env['ENDING_URL'] = f'http://127.0.0.1:{port}'
        with (Path(directory)/'server.log').open('wb') as log:
            server = subprocess.Popen(manage+['runserver', f'127.0.0.1:{port}', '--noreload'],
                                      cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                for _ in range(50):
                    try:
                        urllib.request.urlopen(env['ENDING_URL']+'/alerts/groups/settings/', timeout=1).close()
                        break
                    except OSError:
                        time.sleep(.2)
                subprocess.run(['node', '-e', BROWSER], cwd=ROOT, env=env, check=True)
            finally:
                server.terminate()
                server.wait(timeout=10)


if __name__ == '__main__':
    main()
