import fs from 'node:fs';
import { chromium, devices, Page } from '@playwright/test';
import { loadConfig } from './config';
import { DjangoBridge } from './bridge';
import { LuckyEvent, PacketCollector, normalizePacket } from './packets';
import { NumberGameAutomation } from './navigation';

async function main() {
    const config = loadConfig();
    const bridge = new DjangoBridge(config);
    await bridge.health();
    const replayIndex = process.argv.indexOf('--replay');
    if (replayIndex !== -1) {
        const failuresBefore = bridge.failedCount();
        const file = process.argv[replayIndex + 1];
        if (!file) throw new Error('--replay requires a JSONL file.');
        const collector = new PacketCollector();
        for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/).filter(Boolean)) {
            const value = JSON.parse(line);
            const event: LuckyEvent | null = value.schema_version === 1 ? value : collector.collect(value);
            if (event) bridge.enqueue(event);
        }
        await bridge.flush();
        if (bridge.pendingCount()) throw new Error('Some events remain queued.');
        if (bridge.failedCount() > failuresBefore) throw new Error('Some events were rejected; inspect the failed directory.');
        return;
    }
    const context = await chromium.launchPersistentContext(config.profileDir, {
        channel: config.channel === 'chromium' ? undefined : config.channel,
        headless: config.headless, viewport: config.viewport, hasTouch: true,
        // Apply the DevTools device-toolbar behavior directly, without its UI.
        isMobile: config.mobileEmulation,
        userAgent: config.mobileEmulation ? devices['Pixel 7'].userAgent : undefined,
        args: config.devtools ? ['--auto-open-devtools-for-tabs'] : [],
    });
    const collector = new PacketCollector();
    let automation: NumberGameAutomation | undefined;
    const flush = () => bridge.flush().catch(error => console.warn(`[retry] ${error.message}`));
    const capture = (value: unknown, observedAt: string) => {
        const packet = normalizePacket(value, observedAt);
        if (packet) automation?.observe(packet);
        const event = collector.collect(value, observedAt);
        if (event) { bridge.enqueue(event); void flush(); }
    };
    const attach = (page: Page) => {
        // Serialize console extraction so slow argument decoding cannot reorder events.
        let consoleQueue = Promise.resolve();
        page.on('console', message => {
            const observedAt = new Date().toISOString();
            consoleQueue = consoleQueue.then(async () => {
                for (const argument of message.args()) {
                    try { capture(await argument.jsonValue(), observedAt); } catch { /* Non-serializable browser value. */ }
                }
            }).catch(error => console.warn(`[capture] ${error.message}`));
        });
        page.on('websocket', socket => socket.on('framereceived', frame => {
            if (typeof frame.payload === 'string') capture(frame.payload, new Date().toISOString());
        }));
    };
    context.pages().forEach(attach);
    context.on('page', attach);
    const page = context.pages()[0] || await context.newPage();
    if (config.autoOpen) automation = new NumberGameAutomation(page, config);
    let timer: NodeJS.Timeout | undefined;
    const closed = new Promise<void>(resolve => context.once('close', () => resolve()));
    const stop = () => { automation?.stop(); void context.close(); };
    process.once('SIGINT', stop);
    process.once('SIGTERM', stop);
    try {
        timer = setInterval(() => void flush(), 3000);
        await flush();
        await page.goto(config.gameUrl, { waitUntil: 'domcontentloaded' });
        console.log(config.autoOpen
            ? 'Logger connected. Opening a party and Lucky Number automatically; sign in if prompted.'
            : 'Logger connected. Sign in to Chamet and open Lucky Number in this browser.');
        automation?.start();
        console.log(`UTC event queue and signal feedback: ${config.dataDir}`);
        await closed;
    } finally {
        automation?.stop();
        if (timer) clearInterval(timer);
        await context.close();
        await flush();
        process.removeListener('SIGINT', stop);
        process.removeListener('SIGTERM', stop);
    }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
