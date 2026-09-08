export interface LuckyEvent {
    schema_version: 1;
    game_type: 'lucky28';
    game_no: string;
    phase: 'pre' | 'winner';
    observed_at: string;
    data: Record<string, unknown>;
}

type RecordValue = Record<string, any>;
const object = (value: unknown): value is RecordValue => Boolean(value && typeof value === 'object' && !Array.isArray(value));
const integer = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value);

function unwrap(value: unknown, depth = 0): RecordValue | null {
    if (depth > 4) return null;
    if (typeof value === 'string') {
        try { return unwrap(JSON.parse(value), depth + 1); } catch { return null; }
    }
    if (!object(value)) return null;
    if (value.page === 'IM') return unwrap(value.params, depth + 1);
    if ('code' in value && value.code !== 651) return null;
    if (object(value.info)) return unwrap(value.info, depth + 1);
    return value;
}

export function normalizePacket(value: unknown, observedAt = new Date().toISOString()): LuckyEvent | null {
    const info = unwrap(value);
    if (!info) return null;
    // A mixed Chamet stream can contain race packets; reject those before any write.
    if (['winCarId', 'carIds', 'trackIds', 'liveCarBetBeanList'].some(key => key in info)) return null;
    const rates = Array.isArray(info.numberTypeRates) ? info.numberTypeRates : [];
    if (typeof info.winResult !== 'number' && !rates.some(r => object(r) && ['B', 'S', 'E', 'O'].includes(r.numberType))) return null;
    if (!(typeof info.gameNo === 'string' || integer(info.gameNo))) return null;
    const gameNo = String(info.gameNo).trim();
    if (!gameNo || gameNo.length > 32) return null;
    const event: LuckyEvent = {
        schema_version: 1, game_type: 'lucky28', game_no: gameNo,
        phase: 'pre', observed_at: observedAt, data: {},
    };
    const copyCount = (source: string, target: string) => {
        if (integer(info[source]) && info[source] >= 0) event.data[target] = info[source];
    };
    copyCount('betUsers', 'bet_users');
    copyCount('betTotalEnergy', 'bet_total_energy');
    if (info.status === 3 || info.status === 4) {
        if (!integer(info.winResult) || info.winResult < 0 || info.winResult > 27) return null;
        event.phase = 'winner';
        event.data.winning_number = info.winResult;
        event.data.status = info.status;
        copyCount('winnerCount', 'winner_count');
        copyCount('winTotalEnergy', 'win_total_energy');
        if (typeof info.openCode === 'string') {
            const numbers = info.openCode.split(',').map((s: string) => Number(s.trim()));
            if (numbers.length === 3 && numbers.every((n: number) => integer(n) && n >= 0 && n <= 9)
                && numbers.reduce((a: number, b: number) => a + b, 0) === info.winResult) event.data.reward_numbers = numbers;
        }
    } else {
        if (!integer(info.surplusSeconds) || info.surplusSeconds < 0) return null;
        event.data.surplus_seconds = info.surplusSeconds;
        if (typeof info.latestStatistic === 'string') event.data.latest_statistic = info.latestStatistic.slice(0, 32);
        const names: Record<string, string> = { B: 'rate_big', S: 'rate_small', E: 'rate_even', O: 'rate_odd' };
        for (const rate of rates) {
            if (object(rate) && names[rate.numberType] && typeof rate.proportion === 'number'
                && Number.isFinite(rate.proportion) && rate.proportion >= 0 && rate.proportion <= 1) {
                event.data[names[rate.numberType]] = Math.round(rate.proportion * 10000) / 100;
            }
        }
    }
    return event;
}

export class PacketCollector {
    private milestones = new Map<string, Set<string>>();

    collect(value: unknown, observedAt?: string): LuckyEvent | null {
        const event = normalizePacket(value, observedAt);
        if (!event) return null;
        const seen = this.milestones.get(event.game_no) || new Set<string>();
        const seconds = Number(event.data.surplus_seconds);
        const stage = event.phase === 'winner' ? 'winner' : seconds === 0 ? 'zero' : seconds <= 5 ? 'five' : seconds <= 10 ? 'ten' : 'start';
        if (seen.has(stage) || (event.phase === 'pre' && seen.has('winner'))) return null;
        seen.add(stage);
        this.milestones.set(event.game_no, seen);
        if (this.milestones.size > 2000) this.milestones.delete(this.milestones.keys().next().value!);
        return event;
    }
}
