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
    const select=n=>tile(n).locator('.tl-tile-toggle').click();
    const inspect=n=>tile(n).locator('.tl-tile-details').click();
    const selectedNumbers=()=>page.locator('.tl-number-tile.number-selected').evaluateAll(nodes=>nodes.map(node=>Number(node.dataset.number)));
    const group=id=>page.locator(`[data-selection-group="${id}"]`);
    const clear=async()=>{for(const n of await selectedNumbers())await select(n);};
    const comparison=()=>page.locator('#tl-probability-status').textContent();
    expect(await selectedNumbers()).toEqual([4,9,13,14,15,16,18,19]);
    await expect(page.locator('#tl-probability-status')).toContainText('46.20% versus 53.80%');
    await expect(tile(14)).toContainText('2 hits');await expect(tile(19)).toContainText('2 hits');
    const recentChips=page.locator('.tl-recent-chip'),recentView=page.locator('#tl-recent-view');
    const recentLabels=()=>page.locator('.tl-recent-circle').allTextContents();
    const recentNumbers=[9,13,4,14,19,18,15,19,14,16];
    expect(await recentLabels()).toEqual(recentNumbers.map(String));
    await expect(recentChips).toHaveCount(10);await expect(recentChips.first()).toHaveClass(/is-latest/);
    const selectionBeforeView=await selectedNumbers(),probabilityBeforeView=await comparison();
    const dimensions=await recentChips.first().boundingBox();
    await expect(page.locator('.tl-recent-legend>span')).toHaveCount(7);
    expect(await recentChips.evaluateAll(nodes=>nodes.map(n=>n.dataset.colorGroup))).toEqual(['G05','G07','G03','G07','G05','G05','G07','G05','G07','G06']);
    const numberColors=await recentChips.evaluateAll(nodes=>nodes.map(n=>n.style.getPropertyValue('--recent-color')));
    expect(numberColors[0]).toBe('#31c8c4');expect(numberColors[1]).toBe('#aab0bb');expect(numberColors[2]).toBe('#e754cf');
    expect(dimensions.width).toBeGreaterThan(44);
    const circleBox=await recentChips.first().locator('span').boundingBox();expect(Math.abs(circleBox.width-circleBox.height)).toBeLessThan(1);
    await recentChips.first().click();expect(await recentLabels()).toEqual(recentNumbers.map(n=>n<14?'S':'B'));
    await expect(recentView).toHaveText('View: Size ↻');
    await expect(page.locator('.tl-recent-legend>span')).toHaveCount(2);
    expect(new Set(await recentChips.evaluateAll(nodes=>nodes.map(n=>n.style.getPropertyValue('--recent-color')))).size).toBe(2);
    await recentView.press('Space');expect(await recentLabels()).toEqual(recentNumbers.map(n=>n%2===0?'E':'O'));
    await recentChips.first().press('Enter');expect(await recentLabels()).toEqual(recentNumbers.map(n=>(n<14?'S':'B')+(n%2===0?'E':'O')));
    await expect(page.locator('.tl-recent-legend>span')).toHaveCount(4);
    expect(new Set(await recentChips.evaluateAll(nodes=>nodes.map(n=>n.style.getPropertyValue('--recent-color')))).size).toBe(4);
    const comboDimensions=await recentChips.first().boundingBox();expect(comboDimensions.width).toBe(dimensions.width);expect(comboDimensions.height).toBe(dimensions.height);
    await expect(recentChips.first()).toBeFocused();
    await recentView.click();expect(await recentLabels()).toEqual(recentNumbers.map(String));
    expect(await selectedNumbers()).toEqual(selectionBeforeView);expect(await comparison()).toBe(probabilityBeforeView);
    await expect(page.locator('#tl-selection-status')).toContainText('Mode: Auto last 10');
    await page.locator('[data-round="P7"]').focus();await page.locator('#tl-recent-details').click();
    await expect(page.locator('#tl-recent-info')).toContainText('Number 4 · Small (S) · Even (E) · SE · #P7');
    await expect(page.locator('.tl-recent-round-link')).toHaveAttribute('href',/P7/);
    await page.locator('#tl-recent-details').click();await expect(page.locator('#tl-recent-info')).toBeHidden();
    // No duplicate statistics or explanation sits between the board and Newest.
    expect(await page.locator('.tl-board-scroller').evaluate(n=>n.nextElementSibling.id)).toBe('tl-recent-results');
    await expect(page.locator('.tl-compact-metrics')).toBeHidden();
    expect(await page.locator('#tl-probability').evaluate(n=>n.nextElementSibling.id)).toBe('tl-row-column-summary');

    await expect(page.locator('#tl-palette input,.tl-overlap,.tl-match-strips,.tl-match-controls')).toHaveCount(0);
    await group('recent').click();expect(await selectedNumbers()).toEqual([]);
    await expect(page.locator('#tl-selection-status')).toContainText('Mode: Manual');
    await expect(page.locator('#tl-probability-status')).toContainText('0.00% versus 100.00%');
    await group('absent').click();expect((await selectedNumbers()).length).toBe(20);
    await group('recent').click();expect((await selectedNumbers()).length).toBe(28);
    await expect(group('recent')).toHaveAttribute('aria-pressed','true');await expect(group('absent')).toHaveAttribute('aria-pressed','true');
    await expect(page.locator('#tl-probability-status')).toContainText('100.00% versus 0.00%');
    await group('recent').click();expect((await selectedNumbers()).length).toBe(20);
    await group('absent').click();expect(await selectedNumbers()).toEqual([]);
    const all=Array.from({length:28},(_,n)=>n);
    const categoryMembers={S:all.slice(0,14),B:all.slice(14),E:all.filter(n=>n%2===0),O:all.filter(n=>n%2===1),SE:[0,2,4,6,8,10,12],SO:[1,3,5,7,9,11,13],BE:[14,16,18,20,22,24,26],BO:[15,17,19,21,23,25,27]};
    const metricsBefore=await page.locator('[data-gap] strong,[data-streak] strong').allTextContents();
    for(const [id,members] of Object.entries(categoryMembers)){
      await group(id).click();expect(await selectedNumbers()).toEqual(members);
      if(['S','B','E','O'].includes(id))await expect(page.locator('#tl-probability-status')).toContainText('equal: 50.00% versus 50.00%');
      await group(id).click();expect(await selectedNumbers()).toEqual([]);
    }
    for(const prefix of ['R','C'])for(let i=0;i<(prefix==='R'?4:7);i++){
      const id=`${prefix}0${i+1}`,members=all.filter(n=>prefix==='R'?Math.floor(n/7)===i:n%7===i);
      await group(id).click();expect(await selectedNumbers()).toEqual(members);await group(id).click();expect(await selectedNumbers()).toEqual([]);
    }
    const panelBefore=await page.locator('#tl-number-detail').textContent();
    await group('R01').click();await group('C01').click();await group('R01').click();
    expect(await selectedNumbers()).toEqual([7,14,21]);await expect(group('C01')).toContainText('3/4');await expect(group('C01')).toHaveAttribute('aria-pressed','false');
    expect(await page.locator('#tl-number-detail').textContent()).toBe(panelBefore);
    await group('C01').click();expect(await selectedNumbers()).toEqual([0,7,14,21]);await group('C01').click();expect(await selectedNumbers()).toEqual([]);
    await group('S').click();await group('E').click();expect((await selectedNumbers()).length).toBe(21);await group('S').click();expect(await selectedNumbers()).toEqual([14,16,18,20,22,24,26]);await clear();
    expect(await page.locator('[data-gap] strong,[data-streak] strong').allTextContents()).toEqual(metricsBefore);
    await select(0);await expect(tile(0)).toHaveClass(/number-selected/);await select(0);expect(await selectedNumbers()).toEqual([]);
    await tile(13).locator('.tl-tile-toggle').press('Enter');await tile(14).locator('.tl-tile-toggle').press('Space');expect(await selectedNumbers()).toEqual([13,14]);
    await inspect(27);expect(await selectedNumbers()).toEqual([13,14]);await expect(page.locator('#tl-number-detail')).toContainText('Standard odds reference: 1000.0');await expect(tile(27)).not.toHaveClass(/focused|number-selected/);
    for(const target of [1,3,5,10,14]){await page.selectOption('#tl-selection-target',String(target));await expect(page.locator('#tl-target-status')).toContainText(`Selected 2 / target ${target}`);expect(await selectedNumbers()).toEqual([13,14]);}
    await recentView.click();await page.locator('[data-round="P5"]').focus();
    const scrollBeforeUpdate=await page.evaluate(()=>window.scrollY);
    const manualComparison=await comparison();append('palette','P10',20);
    await expect(tile(20)).toContainText('1 hit',{timeout:12000});expect(await selectedNumbers()).toEqual([13,14]);expect(await comparison()).toEqual(manualComparison);
    await expect(recentView).toHaveText('View: Size ↻');await expect(page.locator('[data-round="P5"]')).toBeFocused();
    expect(Math.abs(await page.evaluate(()=>window.scrollY)-scrollBeforeUpdate)).toBeLessThan(3);
    await expect(recentChips.first()).toHaveAttribute('data-round','P10');await expect(recentChips).toHaveCount(10);
    expect((await recentLabels())[0]).toBe('B');
    await group('recent').click();await expect(page.locator('#tl-selection-status')).toContainText('Mode: Manual');
    expect(await selectedNumbers()).toEqual([4,9,13,14,15,18,19,20]);
    await refresh();expect(await selectedNumbers()).toEqual([4,9,13,14,15,18,19,20]);
    // Selection is per stream in this page; full reload deliberately starts Auto.
    await clear();await select(22);
    await page.selectOption('#tl-stream','streak');await expect(page.locator('#tl-status')).toContainText('#S3');
    await expect(page.locator('.tl-recent-caption')).toHaveText('Newest → · 4 results');await expect(recentChips).toHaveCount(4);
    await expect(recentView).toHaveText('View: Size ↻');
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
    await page.selectOption('#tl-stream','palette');await expect(page.locator('#tl-status')).toContainText('#P10');expect(await selectedNumbers()).toEqual([22]);
    await page.reload();await expect(page.locator('#tl-status')).toContainText('Live');await page.selectOption('#tl-stream','palette');await expect(page.locator('#tl-status')).toContainText('#P10');
    await expect(page.locator('#tl-selection-status')).toContainText('Mode: Auto last 10');
    append('palette','P11',0);await expect(tile(0)).toHaveClass(/number-selected/,{timeout:12000});
    await expect(page.locator('#tl-probability-status')).toContainText('43.00% versus 57.00%');
    // Corrections rebuild Auto selection and probability from the same snapshot.
    shell('from games.models import GameRound; GameRound.objects.filter(game_no="P11").update(winning_number=2)');
    await expect(tile(2)).toHaveClass(/number-selected/,{timeout:12000});await expect(tile(0)).not.toHaveClass(/number-selected/);
    await expect(recentChips.first().locator('.tl-recent-circle')).toHaveText('2');await expect(recentView).toHaveText('View: Number ↻');
    await expect(page.locator('#tl-probability-status')).toContainText('43.50% versus 56.50%');
    const corrected=await selectedNumbers();await refresh();expect(await selectedNumbers()).toEqual(corrected);
    // Late import changes recent window, with no duplicate-count side effects.
    shell('from games.models import GameRound; from django.utils import timezone; from datetime import timedelta; GameRound.objects.create(game_no="P00",game_type="palette",winning_number=27,has_winner=True,status=3,winner_event_ts=timezone.now()-timedelta(days=1))');
    await refresh();expect(await selectedNumbers()).toEqual(corrected);
    await inspect(2);await page.setViewportSize({width:1440,height:1100});await page.addStyleTag({content:'.navbar{visibility:hidden!important}'});
    await page.locator('.tl-palette-section').screenshot({path:'.local/palette-direct-desktop.png'});
    await page.locator('#tl-gap-analytics').screenshot({path:'.local/palette-direct-charts.png'});
    const tileHeight=(await tile(2).boundingBox()).height;expect(tileHeight).toBeLessThanOrEqual(110);
    for(const width of [768,390]){
      await page.setViewportSize({width,height:900});
      if(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth))throw Error('Page overflows narrow screen');
      await expect(page.locator('.tl-compact-metrics')).toBeHidden();
      const boardPosition=await page.locator('.tl-board-scroller').boundingBox(),recentPosition=await page.locator('#tl-recent-results').boundingBox();
      expect(recentPosition.y-boardPosition.y-boardPosition.height).toBeLessThan(12);
      await page.locator('#tl-row-column-summary>summary').click();await expect(page.locator('.tl-compact-metrics')).toBeVisible();
      await expect(page.locator('[data-summary-group]')).toHaveCount(11);await page.locator('#tl-row-column-summary>summary').click();
      await expect(recentView).toHaveText('View: Number ↻');
      const boardBox=await page.locator('.tl-board-scroller').evaluate(node=>({width:node.clientWidth,scroll:node.scrollWidth}));if(width===390)expect(boardBox.scroll).toBeGreaterThan(boardBox.width);
      if(boardBox.scroll>boardBox.width+1)await expect(page.locator('.tl-board-hint')).toBeVisible();else await expect(page.locator('.tl-board-hint')).toBeHidden();
      await page.locator('.tl-board-scroller').evaluate(node=>node.scrollLeft=node.scrollWidth);
      await expect(page.locator('.tl-row-streaks')).toBeVisible();
      const circleLayout=await recentChips.evaluateAll(nodes=>nodes.map(n=>{const r=n.getBoundingClientRect(),c=n.querySelector('.tl-recent-circle').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,circleWidth:c.width,circleHeight:c.height};}));
      circleLayout.forEach(r=>expect(Math.abs(r.circleWidth-r.circleHeight)).toBeLessThan(1));
      const stripBox=await page.locator('.tl-recent-chips').boundingBox();
      expect(Math.abs(circleLayout[0].x-stripBox.x)).toBeLessThan(1);
      const lastInRow=circleLayout[width===390?4:9];expect(Math.abs(lastInRow.x+lastInRow.width-stripBox.x-stripBox.width)).toBeLessThan(1);
      if(width===390){expect(circleLayout[5].y).toBeGreaterThan(circleLayout[0].y);expect(circleLayout[0].width).toBeGreaterThanOrEqual(44);}
      const cards=await page.locator('.tl-probability-card').evaluateAll(nodes=>nodes.map(n=>({width:n.clientWidth,scroll:n.scrollWidth})));cards.forEach(c=>expect(c.scroll).toBeLessThanOrEqual(c.width));
    }
    await page.locator('.tl-palette-section').screenshot({path:'.local/palette-direct-mobile.png'});
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
    await refresh();await page.selectOption('#tl-stream','empty');await expect(page.locator('#tl-palette-status')).toContainText('no completed results');
    await expect(page.locator('[data-gap="S"] strong')).toHaveText('N/A');await expect(page.locator('[data-streak="S"] strong')).toHaveText('N/A');
    await expect(page.locator('[data-gap].metric-max-gap')).toHaveCount(0);expect(await selectedNumbers()).toEqual([]);
    await expect(group('recent')).toBeDisabled();await expect(group('absent')).toBeDisabled();
    await expect(recentView).toBeDisabled();await expect(recentChips).toHaveCount(0);await expect(page.locator('#tl-recent-details')).toBeDisabled();
    await group('S').click();expect((await selectedNumbers()).length).toBe(14);await expect(page.locator('#tl-probability-status')).toContainText('50.00% versus 50.00%');
    await page.selectOption('#tl-stream','palette');await expect(page.locator('#tl-status')).toContainText('#P11');
    await clear();await select(0);
    await page.route('**/api/trackers/live/**',route=>route.fulfill({status:503,body:'offline'}));
    await page.getByRole('button',{name:'Refresh now',exact:true}).click();await expect(page.locator('#tl-palette-status')).toContainText('last loaded palette');
    expect(await selectedNumbers()).toEqual([0]);await expect(page.locator('#tl-gap-status')).toContainText('last loaded gap history');
    await expect(page.locator('#tl-recent-notice')).toContainText('Last loaded results');await expect(recentChips).toHaveCount(10);
    await page.unroute('**/api/trackers/live/**');await refresh();expect(await selectedNumbers()).toEqual([0]);
    await page.route('**/api/trackers/live/**',route=>route.fulfill({status:503,body:'offline'}));await page.reload();
    await expect(page.locator('#tl-palette-status')).toContainText('History unavailable');await expect(group('recent')).toBeDisabled();await expect(group('absent')).toBeDisabled();
    await select(0);await inspect(0);expect(await selectedNumbers()).toEqual([0]);await expect(page.locator('#tl-probability-status')).toContainText('0.10% versus 99.90%');
    await expect(page.locator('#tl-number-detail')).toContainText('Probability weight: 1 / 1,000');
    await expect(page.locator('[data-gap="SE"] strong')).toHaveText('N/A');
    await page.unroute('**/api/trackers/live/**');await refresh();
    // New/Repeated uses each round's prior ten, and only the latest carries a run.
    seed('badges','B',[0,1,2,3,4,5,6,7,8,9,10,11,10,11]);await refresh();
    await expect(page.locator('#tl-stream option[value="badges"]')).toHaveCount(1);await page.selectOption('#tl-stream','badges');
    const latestTag=page.locator('.tl-recent-chip').first().locator('.tl-new-repeat');
    await expect(latestTag).toHaveText('Repeated · R×2');
    await expect(tile(11).locator('.tl-palette-result-tag')).toHaveText('Repeated · R×2');
    await expect(tile(11).locator('.tl-latest-badge')).toBeVisible();
    await expect(tile(10).locator('.tl-palette-result-tag')).toHaveText('Repeated');
    await expect(tile(27).locator('.tl-palette-result-tag')).toBeHidden();
    await select(11);await expect(tile(11).locator('.tl-palette-result-tag')).toHaveText('Repeated · R×2');
    await page.locator('#tl-recent-view').click();await expect(tile(11).locator('.tl-palette-result-tag')).toHaveText('Repeated · R×2');
    await expect(page.locator('[data-round="B12"] .tl-new-repeat')).toHaveText('Repeated');
    await expect(page.locator('[data-round="B11"] .tl-new-repeat')).toHaveText('New');
    await expect(page.locator('[data-round="B9"] .tl-new-repeat')).toHaveText('Building history');
    for(const width of [1440,1000,390]){
      await page.setViewportSize({width,height:1000});
      expect(await page.locator('.tl-palette-result-tag:visible').evaluateAll(tags=>tags.every(tag=>{
        const tile=tag.closest('.tl-number-tile'),box=tile.getBoundingClientRect(),r=tag.getBoundingClientRect(),details=tile.querySelector('.tl-tile-details').getBoundingClientRect();
        return r.bottom<=details.top+1&&r.left>=box.left&&r.right<=box.right&&box.height<=110;
      }))).toBe(true);
    }
    // Conditional polls leave DOM nodes intact and avoid a full response body.
    const notModified=page.waitForResponse(r=>r.url().includes('/api/trackers/live/')&&r.status()===304);
    await notModified;
    await page.evaluate(()=>{window.latestCircle=document.querySelector('.tl-recent-chip');window.paletteMutations=0;window.paletteObserver=new MutationObserver(()=>window.paletteMutations++);window.paletteObserver.observe(document.querySelector('#tl-palette'),{childList:true,subtree:true});});
    await page.waitForResponse(r=>r.url().includes('/api/trackers/live/')&&r.status()===304);
    expect(await page.evaluate(()=>window.paletteMutations)).toBe(0);
    expect(await page.evaluate(()=>window.latestCircle===document.querySelector('.tl-recent-chip'))).toBe(true);
    const resultTime=Date.now();append('badges','B14',12);
    await expect(latestTag).toHaveText('New · N×1',{timeout:5000});
    await expect(tile(12).locator('.tl-palette-result-tag')).toHaveText('New · N×1');
    await expect(tile(11).locator('.tl-palette-result-tag')).toHaveText('Repeated');
    await expect(tile(11).locator('.tl-latest-badge')).toBeHidden();
    console.log('Saved result to visible badge, including test insertion: '+(Date.now()-resultTime)+'ms');
    await expect(page.locator('[data-round="B13"] .tl-new-repeat')).toHaveText('Repeated');
    append('badges','B15',13);await expect(latestTag).toHaveText('New · N×2',{timeout:5000});
    expect(await page.locator('.tl-new-repeat').allTextContents().then(tags=>tags.filter(t=>t.includes('×')).length)).toBe(1);
    await expect(tile(13).locator('.tl-palette-result-tag')).toHaveText('New · N×2');
    await expect(tile(12).locator('.tl-palette-result-tag')).toHaveText('New');
    expect(await page.locator('.tl-palette-result-tag').allTextContents().then(tags=>tags.filter(t=>t.includes('×')).length)).toBe(1);
    for(const width of [1440,1000,390]){
      await page.setViewportSize({width,height:1000});
      const fit=await tile(13).evaluate(tile=>{const tag=tile.querySelector('.tl-palette-result-tag').getBoundingClientRect(),action=tile.querySelector('.tl-tile-details').getBoundingClientRect(),box=tile.getBoundingClientRect();return tag.bottom<=action.top+1&&tag.left>=box.left&&tag.right<=box.right&&box.height<=110;});
      expect(fit).toBe(true);
    }
    if (errors.length) throw new Error(errors.join('\n'));
    console.log('Direct palette and probability checks passed: exact groups, overlaps, keyboard, Auto/Manual, targets, history corrections, offline use, compact desktop/mobile, existing analytics and timeline controls.');
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
