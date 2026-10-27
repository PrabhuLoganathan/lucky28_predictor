import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DjangoBridge } from '../bridge';
import { loadConfig, projectRoot } from '../config';
import { normalizePacket, PacketCollector } from '../packets';
import { NumberGameHealth } from '../navigation';

const winner = { gameNo: 'game-1', winResult: 0, surplusSeconds: 0, status: 3, winnerCount: 0, winTotalEnergy: 0, openCode: '0,0,0' };
const observed = '2026-09-07T23:59:59.000Z';

function temporary(t: any) {
    const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'lucky28-test-'));
    t.after(() => fs.rmSync(dataDir, { recursive: true, force: true }));
    return { dataDir, apiUrl: 'http://local.invalid/api/logger', token: 'test-token' };
}

function accepted(event: any, signals: any[] = []) {
    return Response.json({ accepted: true, game: { game_no: event.game_no }, signals });
}

test('normalizes direct, nested and IM winner packets including zero and timestamp', () => {
    for (const input of [winner, { info: winner }, { page: 'IM', params: JSON.stringify({ code: 651, info: winner }) }]) {
        const result = normalizePacket(input, observed)!;
        assert.equal(result.phase, 'winner');
        assert.equal(result.observed_at, observed);
        assert.equal(result.data.winning_number, 0);
        assert.deepEqual(result.data.reward_numbers, [0, 0, 0]);
        assert.equal(result.data.winner_count, 0);
    }
});

test('rejects race, unrelated and incomplete winner packets', () => {
    for (const input of [null, 'not JSON', { gameNo: 'unknown', surplusSeconds: 3 },
        { ...winner, winCarId: 1 }, { ...winner, carIds: [1, 2, 3] },
        { ...winner, winResult: 28 },
        { code: 652, info: winner }]) assert.equal(normalizePacket(input), null);
});

test('extracts percentage rates and excludes unneeded source data', () => {
    const result = normalizePacket({ info: { gameNo: 123, surplusSeconds: 10, latestStatistic: '2B/1E',
        token: 'do-not-save', numberTypeRates: [{ numberType: 'B', proportion: 0.4325 }, { numberType: 'E', proportion: 0 }] } })!;
    assert.equal(result.game_no, '123');
    assert.equal(result.data.rate_big, 43.25);
    assert.equal(result.data.rate_even, 0);
    assert.equal('token' in result.data, false);
});

test('collector limits pre milestones and ignores repeated winners and late pre frames', () => {
    const collector = new PacketCollector();
    const pre = { gameNo: 'game-1', winResult: -1, status: 1, surplusSeconds: 30 };
    assert.ok(collector.collect(pre));
    assert.equal(collector.collect({ ...pre, surplusSeconds: 20 }), null);
    assert.ok(collector.collect({ ...pre, surplusSeconds: 10 }));
    assert.ok(collector.collect({ ...pre, surplusSeconds: 5 }));
    assert.ok(collector.collect(winner));
    assert.equal(collector.collect(winner), null);
    assert.equal(collector.collect({ ...pre, surplusSeconds: 0 }), null);
});

test('configuration resolves profile and data paths inside the shared project', () => {
    const config = loadConfig({ LUCKY28_LOGGER_TOKEN: 'test-token' });
    assert.equal(config.profileDir, path.join(projectRoot, '.local/chamet-profile'));
    assert.equal(config.dataDir, path.join(projectRoot, '.local/chamet'));
    assert.equal(config.apiUrl, 'http://127.0.0.1:8000/api/logger');
    assert.equal(config.autoOpen, true);
    assert.equal(config.gameUrl, 'https://webapp.chametw.com/partyList');
    assert.equal(config.devtools, false);
    assert.equal(config.mobileEmulation, true);
    assert.equal(loadConfig({ LUCKY28_LOGGER_TOKEN: 'test-token', CHAMET_DEVTOOLS: 'true' }).devtools, true);
    assert.equal(loadConfig({ LUCKY28_LOGGER_TOKEN: 'test-token', CHAMET_MOBILE: 'false' }).mobileEmulation, false);
    assert.equal(loadConfig({ LUCKY28_LOGGER_TOKEN: 'test-token', CHAMET_HEADLESS: 'true' }).devtools, false);
    assert.equal(loadConfig({ LUCKY28_LOGGER_TOKEN: 'test-token', CHAMET_DEVTOOLS: 'false' }).devtools, false);
    assert.match(config.selectors.number, /Lucky Number/);
    const manual = loadConfig({ LUCKY28_LOGGER_TOKEN: 'test-token', CHAMET_AUTO_OPEN: 'false', CHAMET_NUMBER_SELECTOR: '.number-option' });
    assert.equal(manual.autoOpen, false);
    assert.equal(manual.selectors.number, '.number-option');
});

test('collector forwards completed or changed settlements while deduplicating identical winners', () => {
    const collector = new PacketCollector();
    assert.ok(collector.collect(winner));
    const final = { ...winner, betTotalEnergy: 100, winTotalEnergy: 99,
        reportedTip: 1, totalsComplete: true, settlementFinal: true, settlementSequence: 897 };
    const event = collector.collect(final)!;
    assert.equal(event.data.bet_total_energy, 100);
    assert.equal(event.data.win_total_energy, 99);
    assert.equal(event.data.reported_tip, 1);
    assert.equal(event.data.settlement_sequence, 897);
    assert.equal(event.data.totals_complete, true);
    assert.equal(collector.collect(final), null);
    assert.ok(collector.collect({ ...final, winTotalEnergy: 98 }));
    assert.ok(collector.collect({ ...final, totalsComplete: false }));
    assert.equal(collector.collect({ gameNo: 'game-1', winResult: -1, status: 1, surplusSeconds: 0 }), null);
});

test('malformed optional settlement assertions are rejected instead of silently omitted', () => {
    for (const changes of [{reportedTip: -1}, {reportedTip: '1'}, {reportedTip: Number.MAX_SAFE_INTEGER+1},
        {settlementSequence: false}, {totalsComplete: 'false'}, {settlementFinal: 1}, {winnerCount: -1}]) {
        assert.equal(normalizePacket({...winner, betTotalEnergy: 100, ...changes}), null);
    }
});

test('automatic navigation waits for login and recovers only after Number Game progress stops', () => {
    const health = new NumberGameHealth();
    assert.equal(health.needsRecovery(1000000, 120000), false); // Login has no deadline.
    health.awaiting(1000);
    assert.equal(health.needsRecovery(120999, 120000), false);
    assert.equal(health.needsRecovery(121000, 120000), true);
    const event = normalizePacket(winner, observed)!;
    assert.equal(health.observe(event, 122000), true);
    assert.equal(health.isLive(123000, 120000), true);
    // Repeated delivery of a frozen winner cannot hide a stalled game.
    assert.equal(health.observe(event, 240000), false);
    assert.equal(health.needsRecovery(242000, 120000), true);
    health.awaiting(243000);
    assert.equal(health.needsRecovery(244000, 120000), false);
    assert.equal(health.observe({ ...event, game_no: 'game-2' }, 245000), true);
    assert.equal(health.isLive(245000, 120000), true);
});

test('durable queue survives network failure and replays original UTC timestamps', async t => {
    const config = temporary(t);
    const offline = new DjangoBridge(config, (async () => { throw new Error('offline'); }) as typeof fetch);
    const event = normalizePacket(winner, observed)!;
    offline.enqueue(event);
    await assert.rejects(offline.flush(), /offline/);
    assert.equal(offline.pendingCount(), 1);
    const online = new DjangoBridge(config, (async (_url: any, options: any) => {
        const body = JSON.parse(options.body);
        assert.equal(body.observed_at, observed);
        assert.equal(options.headers['X-Lucky28-Token'], 'test-token');
        return accepted(body);
    }) as typeof fetch);
    await online.flush();
    assert.equal(online.pendingCount(), 0);
    assert.equal(fs.readFileSync(path.join(config.dataDir, 'delivered.jsonl'), 'utf8').trim().split('\n').length, 1);
});

test('authentication errors retain pending events; invalid events are preserved separately', async t => {
    const config = temporary(t);
    let status = 403;
    const bridge = new DjangoBridge(config, (async () => new Response('rejected', { status })) as typeof fetch);
    bridge.enqueue(normalizePacket(winner, observed)!);
    await assert.rejects(bridge.flush(), /403/);
    assert.equal(bridge.pendingCount(), 1);
    status = 400;
    await bridge.flush();
    assert.equal(bridge.pendingCount(), 0);
    assert.equal(bridge.failedCount(), 1);
});

test('bad acknowledgement keeps data pending', async t => {
    const bridge = new DjangoBridge(temporary(t), (async () => Response.json({ accepted: true, game: { game_no: 'different' }, signals: [] })) as typeof fetch);
    bridge.enqueue(normalizePacket(winner, observed)!);
    await assert.rejects(bridge.flush(), /acknowledgement/);
    assert.equal(bridge.pendingCount(), 1);
});

test('database busy keeps the durable event until a successful retry', async t => {
    const config = temporary(t);
    let busy = true;
    const event = normalizePacket(winner, observed)!;
    const bridge = new DjangoBridge(config, (async (_url: any, options: any) => busy
        ? Response.json({ accepted: false }, { status: 503, headers: { 'Retry-After': '1' } })
        : accepted(JSON.parse(options.body))) as typeof fetch);
    bridge.enqueue(event);
    await assert.rejects(bridge.flush(), /503/);
    assert.equal(bridge.pendingCount(), 1);
    assert.equal(bridge.failedCount(), 0);
    busy = false;
    await bridge.flush();
    assert.equal(bridge.pendingCount(), 0);
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(config.dataDir, 'delivered.jsonl'), 'utf8').trim()), event);
});

test('signal feedback is recorded once across delivery retries and restarts', async t => {
    const config = temporary(t);
    const send = (async (_url: any, options: any) => accepted(JSON.parse(options.body), [{ id: 7, rule__name: 'Two Big', value: 2 }])) as typeof fetch;
    for (let i = 0; i < 2; i++) {
        const bridge = new DjangoBridge(config, send);
        bridge.enqueue(normalizePacket(winner, observed)!);
        await bridge.flush();
    }
    const signals = fs.readFileSync(path.join(config.dataDir, 'signals.jsonl'), 'utf8').trim().split('\n');
    assert.equal(signals.length, 1);
    assert.equal(JSON.parse(signals[0]).signal.id, 7);
});

test('events queued during an in-flight send are delivered without waiting for the retry timer', async t => {
    const config = temporary(t);
    const delivered: string[] = [];
    let bridge: DjangoBridge;
    const next = { ...normalizePacket(winner, observed)!, game_no: 'next-round' };
    bridge = new DjangoBridge(config, (async (_url: any, options: any) => {
        const body = JSON.parse(options.body);
        delivered.push(body.game_no);
        if (delivered.length === 1) {
            bridge.enqueue(next);
            await bridge.flush(); // Busy call must not lose this new work.
        }
        return accepted(body);
    }) as typeof fetch);
    bridge.enqueue(normalizePacket(winner, observed)!);
    await bridge.flush();
    assert.equal(delivered.length, 2);
    assert.equal(delivered[1], 'next-round');
    assert.equal(bridge.pendingCount(), 0);
});
