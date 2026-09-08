import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { LuckyEvent } from './packets';

interface Config { apiUrl: string; token: string; dataDir: string }

export class DjangoBridge {
    private busy = false;
    private pendingDir: string;
    private failedDir: string;
    private signalsDir: string;

    constructor(private config: Config, private send: typeof fetch = fetch) {
        this.pendingDir = path.join(config.dataDir, 'pending');
        this.failedDir = path.join(config.dataDir, 'failed');
        this.signalsDir = path.join(config.dataDir, 'received-signals');
        fs.mkdirSync(this.pendingDir, { recursive: true });
        fs.mkdirSync(this.failedDir, { recursive: true });
        fs.mkdirSync(this.signalsDir, { recursive: true });
    }

    async health(): Promise<void> {
        const response = await this.send(`${this.config.apiUrl}/health/`, {
            headers: { 'X-Lucky28-Token': this.config.token }, signal: AbortSignal.timeout(5000),
        });
        if (!response.ok) throw new Error(`Django health check returned HTTP ${response.status}. Check the shared URL and token.`);
        const body = await response.json() as any;
        if (body.service !== 'lucky28' || body.schema_version !== 1) throw new Error('The server does not provide the Lucky28 logger API v1.');
    }

    enqueue(event: LuckyEvent): void {
        const body = JSON.stringify(event);
        const digest = createHash('sha256').update(body).digest('hex');
        const name = `${event.observed_at.replace(/[^0-9TZ]/g, '')}-${digest}.json`;
        const target = path.join(this.pendingDir, name);
        if (fs.existsSync(target)) return;
        fs.writeFileSync(`${target}.tmp`, body, { mode: 0o600 });
        fs.renameSync(`${target}.tmp`, target);
    }

    pendingCount(): number { return fs.readdirSync(this.pendingDir).filter(name => name.endsWith('.json')).length; }
    failedCount(): number { return fs.readdirSync(this.failedDir).filter(name => name.endsWith('.json')).length; }

    async flush(): Promise<void> {
        if (this.busy) return;
        this.busy = true;
        try {
            for (const name of fs.readdirSync(this.pendingDir).filter(name => name.endsWith('.json')).sort()) {
                const file = path.join(this.pendingDir, name);
                const event = JSON.parse(fs.readFileSync(file, 'utf8')) as LuckyEvent;
                const response = await this.send(`${this.config.apiUrl}/events/`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lucky28-Token': this.config.token },
                    body: JSON.stringify(event), signal: AbortSignal.timeout(10000),
                });
                if (!response.ok) {
                    if (response.status >= 500 || [401, 403, 408, 429].includes(response.status)) {
                        throw new Error(`Django returned HTTP ${response.status}; queued events will retry.`);
                    }
                    // Preserve rejected events for inspection instead of blocking later games.
                    fs.writeFileSync(path.join(this.failedDir, `${name}.error.txt`), (await response.text()).slice(0, 4000));
                    fs.renameSync(file, path.join(this.failedDir, name));
                    console.warn(`[rejected] ${event.game_no}: HTTP ${response.status}; see ${this.failedDir}`);
                    continue;
                }
                const result = await response.json() as any;
                if (result.accepted !== true || result.game?.game_no !== event.game_no || !Array.isArray(result.signals)) {
                    throw new Error('Invalid Django acknowledgement; keeping the event queued.');
                }
                fs.appendFileSync(path.join(this.config.dataDir, 'delivered.jsonl'), JSON.stringify(event) + '\n');
                if (result.signals.length) {
                    for (const signal of result.signals) {
                        if (!Number.isSafeInteger(signal.id) || signal.id < 1) throw new Error('Invalid signal ID in Django feedback.');
                        const file = path.join(this.signalsDir, `${signal.id}.json`);
                        if (fs.existsSync(file)) continue;
                        const feedback = { received_at: new Date().toISOString(), game_no: event.game_no, observed_at: event.observed_at, signal };
                        fs.writeFileSync(file, JSON.stringify(feedback), { flag: 'wx', mode: 0o600 });
                        fs.appendFileSync(path.join(this.config.dataDir, 'signals.jsonl'), JSON.stringify(feedback) + '\n');
                        console.log(`[signal] ${event.game_no}: ${signal.rule__name} (${signal.value})`);
                    }
                }
                fs.unlinkSync(file);
                console.log(`[saved] ${event.phase} ${event.game_no}${result.duplicate ? ' (already saved)' : ''}`);
            }
        } finally { this.busy = false; }
    }
}
