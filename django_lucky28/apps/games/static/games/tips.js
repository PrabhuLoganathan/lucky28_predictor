(() => {
    const root = document.getElementById('tip-monitor');
    if (!root) return;
    const element = id => document.getElementById(`tip-${id}`);
    const amount = value => typeof value === 'number' ? value.toLocaleString() : '—';
    const text = (tag, value, className = '') => {
        const node = document.createElement(tag);
        node.textContent = value;
        node.className = className;
        return node;
    };
    let busy = false;
    async function refresh() {
        if (busy) return;
        busy = true;
        element('refresh').disabled = true;
        try {
            const response = await fetch(root.dataset.api, {cache: 'no-store', signal: AbortSignal.timeout(15000)});
            if (!response.ok) throw new Error('Fetch failed');
            const data = await response.json();
            const state = data.state;
            element('streak').textContent = `${state.exactStreak ? '' : 'At least '}${state.noTipStreak}`;
            element('certainty').textContent = state.exactStreak ? 'Continuous since an observed tip.' : 'Observed lower bound.';
            element('last').textContent = state.lastTipGameId || 'No tip observed in this segment';
            element('thresholds').textContent = state.thresholds.join(' · ');
            element('queued').textContent = amount(data.queued);
            element('status').textContent = state.lastGameId
                ? `Latest accepted round: ${state.lastGameId}. Updated ${new Date().toLocaleTimeString()}.`
                : 'Waiting for a complete final settlement.';
            element('rounds').replaceChildren();
            for (const row of data.rounds) {
                const tr = document.createElement('tr');
                const result = row.result;
                const values = [row.game_id, row.source.winningNumber ?? '—', amount(row.source.totalBets),
                    amount(row.source.totalPrizes), amount(result.tipAmount),
                    typeof result.tipPercent === 'number' ? `${result.tipPercent.toFixed(4)}%` : '—', row.status];
                values.forEach(value => tr.append(text('td', value)));
                if (result.reason || result.gapDetected || row.status === 'CONFLICT') {
                    tr.lastChild.append(text('div', result.reason || (row.status === 'CONFLICT'
                        ? 'Changed settlement; accepted state was preserved. Replay corrected history into a new monitor.'
                        : 'Gap detected; a new observed segment starts here.'), 'tip-diagnostic small text-warning'));
                }
                element('rounds').append(tr);
            }
            if (!data.rounds.length) {
                const tr = document.createElement('tr');
                const td = text('td', 'No settlement evidence recorded yet.', 'text-secondary');
                td.colSpan = 7;
                tr.append(td);
                element('rounds').append(tr);
            }
            element('events').replaceChildren();
            for (const event of data.events) {
                const item = text('article', '', 'border-bottom pb-3 mb-3');
                item.append(text('p', event.payload.message, 'mb-1'));
                item.append(text('small', `${event.sent_at ? 'Sent' : 'Queued'} · ${new Date(event.created_at).toLocaleString()} · Attempts: ${event.attempts}`, 'text-secondary'));
                if (event.last_error) item.append(text('p', event.last_error, 'text-warning small mb-0'));
                element('events').append(item);
            }
            if (!data.events.length) element('events').append(text('p', 'No alerts recorded. Historical replay does not create alerts.', 'text-secondary mb-0'));
        } catch {
            element('status').textContent = 'Unable to refresh. Displayed data may be stale; retrying automatically.';
        } finally {
            busy = false;
            element('refresh').disabled = false;
        }
    }
    element('refresh').addEventListener('click', refresh);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
    setInterval(() => { if (!document.hidden) refresh(); }, 5000);
    refresh();
})();
