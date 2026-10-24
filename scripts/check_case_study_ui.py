"""Verify the separate case study with temporary source and journal databases."""
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
  await page.goto(process.env.STUDY_URL+'/case-study/');
  await expect(page.locator('#cs-status')).toContainText('Recorder active');
  await expect(page.locator('.cs-strategy')).toHaveCount(3);
  await expect(page.locator('.cs-case')).toHaveCount(150);
  await expect(page.locator('#cs-detail')).toContainText('Generation mechanism',{ignoreCase:true}).catch(async()=>{
    await expect(page.locator('#cs-detail')).toContainText('generation mechanism');
  });
  await expect(page.locator('#cs-detail')).toContainText('No forecast recorded before this result');
  await page.locator('#cs-mode-retrospective').click();
  await expect(page.locator('#cs-performance tr')).toHaveCount(9);
  await page.locator('#cs-case-search').fill('202610240010');await expect(page.locator('.cs-case')).toHaveCount(1);
  await page.locator('.cs-case').click();await expect(page.locator('#cs-detail')).toContainText('#202610240010');
  await page.locator('#cs-case-search').fill('');
  const shell=code=>execFileSync(process.env.STUDY_PYTHON,['django_lucky28/manage.py','shell','-c',code],{stdio:'pipe'});
  shell('from games.models import GameRound; from django.utils import timezone; g=GameRound.objects.get(game_no="202610240151"); g.has_winner=True; g.winning_number=0; g.reward_numbers=[0,0,0]; g.status=3; g.winner_event_ts=timezone.now(); g.save()');
  await expect(page.locator('.cs-case').first()).toContainText('#202610240151',{timeout:15000});
  await page.locator('.cs-case').first().click();
  await expect(page.locator('#cs-detail')).toContainText('Forecast saved before the local observer');
  await expect(page.locator('#cs-detail')).toContainText('0 + 0 + 0 = 0');
  await expect(page.locator('#cs-detail')).toContainText('Missed');
  await page.locator('#cs-mode-prospective').click();await expect(page.locator('#cs-performance tr')).toHaveCount(9);
  const exportResponse=await page.request.get(process.env.STUDY_URL+'/case-study/export/');
  const records=(await exportResponse.text()).trim().split('\n').map(JSON.parse);
  expect(records.some(r=>r.kind==='forecast_locked')).toBe(true);
  expect(records.some(r=>r.kind==='result_review'&&r.round_id==='202610240151')).toBe(true);
  for(const width of [1440,1000,390]){
    await page.setViewportSize({width,height:1000});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:'.local/case-study-'+width+'.png',fullPage:true});
  }
  await page.route('**/api/case-study/?**',route=>route.fulfill({status:503,body:'offline'}));
  await page.locator('#cs-refresh').click();await expect(page.locator('#cs-status')).toContainText('Last loaded evidence remains visible');
  await expect(page.locator('#cs-detail')).toContainText('0 + 0 + 0 = 0');
  expect(errors).toEqual([]);
  console.log('Case study browser checks passed: separate page, 150 cases, live frozen forecast, verified digits, misses, log export, desktop/mobile and offline state.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
'''


def main():
    with tempfile.TemporaryDirectory(prefix='number-case-study-') as directory:
        env={**os.environ, 'LUCKY28_DB_PATH':str(Path(directory)/'source.sqlite3'),
             'CASE_STUDY_DB_PATH':str(Path(directory)/'journal.sqlite3'),
             'ALERT_STATE_DIR':str(Path(directory)/'alerts'), 'ALERT_TELEGRAM_ENABLED':'false',
             'ALERT_TELEGRAM_BOT_TOKEN':'', 'STUDY_PYTHON':sys.executable, 'PYTHONUNBUFFERED':'1'}
        manage=[sys.executable, str(ROOT/'django_lucky28/manage.py')]
        subprocess.run(manage+['migrate','--noinput'],cwd=ROOT,env=env,check=True,capture_output=True)
        seed=('from games.models import GameRound; from django.utils import timezone; from datetime import timedelta; '
              'now=timezone.now(); '
              '[GameRound.objects.create(game_no=f"20261024{i:04}",game_type="lucky28",has_winner=True,winning_number=i%28,status=3,winner_event_ts=now-timedelta(minutes=151-i)) for i in range(1,151)]; '
              'GameRound.objects.create(game_no="202610240151",game_type="lucky28",has_pre=True,pre_event_ts=now,status=2)')
        subprocess.run(manage+['shell','-c',seed],cwd=ROOT,env=env,check=True,capture_output=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env['STUDY_URL']=f'http://127.0.0.1:{port}'
        with (Path(directory)/'processes.log').open('wb') as log:
            worker=subprocess.Popen(manage+['case_study_worker'],cwd=ROOT,env=env,stdout=log,stderr=log)
            server=subprocess.Popen(manage+['runserver',f'127.0.0.1:{port}','--noreload'],cwd=ROOT,env=env,stdout=log,stderr=log)
            try:
                for _ in range(60):
                    try:
                        with urllib.request.urlopen(env['STUDY_URL']+'/api/case-study/',timeout=1) as response:
                            import json
                            if json.load(response)['cases']:
                                break
                    except OSError:
                        pass
                    time.sleep(.2)
                subprocess.run(['node','-e',BROWSER],cwd=ROOT,env=env,check=True)
            finally:
                server.terminate();worker.terminate()
                server.wait(timeout=10);worker.wait(timeout=10)


if __name__=='__main__':
    main()
