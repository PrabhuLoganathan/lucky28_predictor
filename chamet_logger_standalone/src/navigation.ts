import { Locator, Page } from '@playwright/test';
import { LuckyEvent } from './packets';

export const navigationSelectors = {
    party: '.card',
    menu: 'img[alt="game"], img[src*="game_btn"]',
    number: 'img.number_game, img[alt="number_game"], img.lucky28_game, img[alt="lucky28_game"], '
        + 'img.lucky_number, img[alt="lucky_number"], :text-matches("^(Lucky Number|Lucky 28|Lucky28|Number Game)$", "i")',
};

export interface NavigationConfig {
    gameUrl: string;
    selectors: typeof navigationSelectors;
    staleMs: number;
}

// Only progress in valid Number Game packets counts as a healthy capture.
export class NumberGameHealth {
    private lastProgress = 0;
    private lastPacket = '';
    private awaitingSince: number | null = null;

    awaiting(now: number): void { this.awaitingSince = now; }
    observe(event: LuckyEvent, now: number): boolean {
        const identity = `${event.game_no}:${event.phase}:${event.data.surplus_seconds ?? ''}`;
        if (identity === this.lastPacket) return false;
        this.lastPacket = identity;
        this.lastProgress = now;
        this.awaitingSince = null;
        return true;
    }
    isLive(now: number, staleMs: number): boolean {
        return Boolean(this.lastPacket) && now - this.lastProgress < staleMs;
    }
    needsRecovery(now: number, staleMs: number): boolean {
        const anchor = this.awaitingSince ?? (this.lastPacket ? this.lastProgress : null);
        return anchor !== null && now - anchor >= staleMs;
    }
}

export class NumberGameAutomation {
    readonly health = new NumberGameHealth();
    private stopped = false;
    private timer?: NodeJS.Timeout;
    private nextActionAt = 0;
    private selected = false;
    private openedMenu = false;
    private lastStatus = '';

    constructor(private page: Page, private config: NavigationConfig,
        private report: (message: string) => void = console.log) {}

    private status(message: string): void {
        if (message !== this.lastStatus) this.report(`[navigation] ${message}`);
        this.lastStatus = message;
    }

    observe(event: LuckyEvent): void {
        if (this.health.observe(event, Date.now())) this.status('Lucky Number capture is live.');
    }

    start(): void {
        const run = async () => {
            if (this.stopped || this.page.isClosed()) return;
            try { await this.step(); }
            catch {
                if (!this.stopped && !this.page.isClosed()) {
                    this.status('Waiting for the page to finish loading; navigation will retry.');
                    this.nextActionAt = Date.now() + 3000;
                }
            }
            if (!this.stopped && !this.page.isClosed()) this.timer = setTimeout(() => void run(), 1000);
        };
        void run();
    }

    stop(): void { this.stopped = true; if (this.timer) clearTimeout(this.timer); }

    private async visible(selector: string): Promise<Locator | null> {
        for (const frame of this.page.frames()) {
            const candidates = frame.locator(selector);
            const count = await candidates.count();
            for (let index = 0; index < count; index++) {
                const item = candidates.nth(index);
                if (await item.isVisible()) return item;
            }
        }
        return null;
    }

    private async activate(item: Locator): Promise<void> {
        // One native gesture avoids the old tap + click + synthetic-event triple toggle.
        await item.tap({ timeout: 3000 });
        this.nextActionAt = Date.now() + 2000;
    }

    async step(): Promise<void> {
        const now = Date.now();
        if (this.stopped || this.page.isClosed() || now < this.nextActionAt) return;
        if (this.health.isLive(now, this.config.staleMs)) return;
        if (this.health.needsRecovery(now, this.config.staleMs)) {
            this.status('Number Game packets stopped; reopening the room and Lucky Number.');
            this.selected = false;
            this.openedMenu = false;
            this.health.awaiting(now);
            this.nextActionAt = now + 5000;
            await this.page.goto(this.config.gameUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
            return;
        }
        if (this.selected) return;
        const number = await this.visible(this.config.selectors.number);
        if (number) {
            await this.activate(number);
            this.selected = true;
            this.health.awaiting(Date.now());
            this.status('Opened Lucky Number; waiting for Number Game packets.');
            return;
        }
        if (this.openedMenu) {
            this.status('Game menu opened; waiting for the Lucky Number option.');
            return;
        }
        const menu = await this.visible(this.config.selectors.menu);
        if (menu) {
            await this.activate(menu);
            this.openedMenu = true;
            this.health.awaiting(Date.now());
            this.status('Opened the game menu; looking for Lucky Number.');
            return;
        }
        // Never treat generic cards inside a room or a game as party entries.
        if (/\/partyList\/?$/i.test(new URL(this.page.url()).pathname)) {
            const party = await this.visible(this.config.selectors.party);
            if (party) {
                await this.activate(party);
                this.health.awaiting(Date.now());
                this.status('Joined the first available party; looking for its game menu.');
                return;
            }
        }
        this.status('Waiting for a party or game menu. Sign in if Chamet asks; automation resumes afterwards.');
    }
}
