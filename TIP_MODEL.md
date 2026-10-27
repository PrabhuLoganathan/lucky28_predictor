# Tip game model

Implementation of **Lucky28 Tip Game Model Documentation v1.0 (27 October 2026)**
in the existing Django application. Open **`/tips/`** for the live settlement
table, no-tip counter, gap/conflict diagnostics, and persisted alert queue.
`GET /api/tips/` exposes the same data. Both routes are read-only.

## TIP conditions in the regular Telegram alerts

Two rules are installed in **Alerts → Rules**, using the same enabled destinations,
subscription levels, Telegram settings, and delivery worker as existing alerts:

| Rule | Condition |
| --- | --- |
| TIP absent for 3 consecutive games | At least 3 consecutive completed settlements have no tip. |
| TIP low density — at most 3 in 10 | The latest 10 consecutive verified settlements contain 0, 1, 2, or 3 TIP games. |

These rules are evaluated when the next round opens, using only preceding completed
results. Each sends on activation, stays silent while the condition remains active,
and rearms after it clears. Unknown totals, missing rounds, and date boundaries
cannot be counted as no-tip games or skipped to build a ten-game window. Both rules
can activate together. Thresholds and enable/disable controls are editable in the
existing rule form under **Tip settlement**.

`run.py` installs these two rules idempotently through `sync_tip_alerts`, preserving
customized saved rules. For an existing running installation:

```sh
.venv/bin/python django_lucky28/manage.py migrate
.venv/bin/python django_lucky28/manage.py sync_tip_alerts
```

Restart the application and its alert worker after updating the code. No separate
tip worker is needed for these two regular alerts. The older standalone monitor
still keeps its independent 7/10/15 milestone event queue; its optional worker is a
separate delivery path.

Confirmed TIP results have a **gold border and superscript star (★)** in every
browser timeline view and in newly captured Telegram timeline images. The fill
still identifies the number/category, and the newest-result ring stays visible.
Captions also mark TIP results with ★ and show verified ten-game density when
available. Unmarked circles may be NO_TIP or unknown; their accessible labels and
details distinguish the two. Old frozen alerts without settlement evidence stay
unchanged rather than guessing historical tip status.

## Rules

- `tipAmount = totalBets - totalPrizes`, using exact integers.
- Positive residual: **TIP**; zero: **NO_TIP**, including zero/zero totals.
- Negative residual, inconsistent reported tip, incomplete totals, invalid amount,
  or winner count greater than participant count: **INVALID**.
- A settlement not confirmed final is **PENDING**. Neither invalid nor pending
  input advances the monitor.
- Every accepted live tip produces **TIP_GAME** and resets the streak.
- **NO_TIP_STREAK** fires once at **7, 10, and 15** consecutive no-tip rounds.
  A tip rearms all milestones. Custom thresholds are sorted and deduplicated.
- Duplicate latest rounds and older rounds return **DUPLICATE** / **STALE**.
  Changed latest settlements return **CONFLICT** and preserve accepted state.
  Participant counts do not change settlement identity.
- Gaps clear the streak. Before an observed tip, or after a gap, counts are
  lower bounds (“at least”). These counts do not predict the next outcome.

## Source adapter

The authenticated logger already records `betTotalEnergy` and `winTotalEnergy`
as `bet_total_energy` and `win_total_energy`. The adapter reads **both from the
same saved winner packet**, never from an earlier pre-round betting total.
Completed source status 3/4 plus both totals is treated as final and complete,
unless explicit flags say otherwise. This mapping agrees with the supplied
screenshot settlements; whole-pool coverage remains an assumption of the source
contract, not something the classifier can prove. HTML imports lacking final
bets are invalid for tip classification.

Optional normalized logger fields are `reported_tip`, `settlement_sequence`,
`settlement_final`, and `totals_complete`. The packet normalizer recognizes
explicit upstream `reportedTip`, `settlementSequence`, `settlementFinal`, and
`totalsComplete` fields if present; it does not infer a tip from undocumented
purple values or net-profit fields. An absent reported tip is allowed.

Date-prefixed round IDs are mapped to `date.toordinal() * 1000000 + dailyNumber`.
Daily gaps and different zero padding remain visible. **Date rollover deliberately
breaks continuity**, because a verified number of actual rounds per day is not
available. A supplied `settlement_sequence` must instead be a globally continuous
source sequence. Do not switch sequence schemes within an existing monitor.
Unknown ID formats need an explicit sequence and otherwise remain invalid.

Changed winner packets now reach Django. A later complete settlement can resolve
the latest incomplete round. Once a later sequence is accepted, older corrections
are stale and require deliberate replay. Source winning numbers are never changed
by this model. The legacy winner route participates when its `winner_raw` contains
the same normalized final totals.

## Install and initialize

From the repository root:

```sh
.venv/bin/python django_lucky28/manage.py migrate
# Optional: run before accepting new tip observations into this monitor.
.venv/bin/python django_lucky28/manage.py initialize_tip_model
```

The initialization command reads saved Lucky28 rounds in sequence order, updates
tip state, and **creates no historical alert events**. It refuses to overwrite an
existing monitor. Normal ingestion starts an empty monitor automatically if none
exists. Historical/replayed packets older than 120 seconds update evidence and
state without generating alert events.

For changed thresholds or corrected history, replay into a new monitor:

```sh
.venv/bin/python django_lucky28/manage.py initialize_tip_model --monitor tips-v2 --thresholds 8 11 16
```

Then set `TIP_MONITOR_ID=tips-v2` in the application's environment and restart the
web process. This switches live ingestion and the dashboard together. Old monitor
evidence and outgoing events remain intact; stop its delivery worker before
switching. `GET /api/tips/?monitor=lucky28` can inspect the old monitor.

## Delivery

Ingestion creates local event records and never performs network delivery.
This change does not automatically start a sender. To send the queue, explicitly
run the worker with an existing enabled alert destination ID, with Telegram
enabled and its token configured through the existing alert settings:

```sh
.venv/bin/python django_lucky28/manage.py tip_alert_worker --destination 1
# One pass, also useful for a scheduler:
.venv/bin/python django_lucky28/manage.py tip_alert_worker --destination 1 --once
```

The worker checks the queue on startup and every 30 seconds even when no games
arrive. `--interval` changes the retry period. It binds a monitor to one destination
and chat ID, checks enabled/expiry settings on each delivery, and will not silently
redirect queued alerts when the recipient changes. Only a successful HTTP response
with Telegram's `ok: true` and integer message ID acknowledges an event. Failures
remain queued and stop the current pass. Starting this worker sends any existing
unsent live events, so review the queue first.

Delivery is **at least once**. A crash after sending but before committing the
acknowledgment may repeat a message; Telegram does not provide event-ID deduplication.
Database locking serializes dispatch and ingestion per monitor (SQLite serializes
all writers), including the bounded network request. External integrations can
use the stable event ID with a deduplicating destination instead.

## Interfaces and persistence

This is a Python port rather than a second Node service:

```python
from games.services.tip_model import classify_round, create_state, advance
from games.services.tips import TipMonitor

monitor = TipMonitor(stream_id='example', thresholds=[7, 10, 15])
result = monitor.ingest({
    'gameId': '20261027897', 'sequence': 897, 'winningNumber': 4,
    'totalBets': 23977479, 'totalPrizes': 23776191,
    'reportedTip': 201288, 'totalUsers': 407, 'winnerCount': 184,
    'settlementFinal': True, 'totalsComplete': True,
})
# Explicit host integration; callback must raise or return False on failure.
# monitor.dispatch(lambda event: existing_sender(event['message'], event_id=event['id']))
```

`advance` returns `(new_state, result, events)` without mutating its arguments.
`TipMonitor.ingest(..., emit_alerts=False)` supports historical initialization.
Constructor configuration mismatches fail before ingestion. The document's state
file/outbox is replaced by `TipStream`, `TipRound`, and `TipEvent` tables so source
ingestion, state, and outgoing events commit atomically and survive concurrent
web workers. A failed event write rolls back the result ingestion transaction.
`TipRound` shows the latest diagnostic for a round; accepted event evidence is
immutable. Existing source history is retained for correction/replay.

## Verification

```sh
.venv/bin/python django_lucky28/manage.py test games.tests.test_tip_model games.tests.test_logger_api
npm --prefix chamet_logger_standalone test
.venv/bin/python scripts/check_tip_ui.py
```

Tests cover all eight screenshot amounts, exact residuals and safe-integer limits,
milestones/reset, pending/invalid inputs, duplicates/conflicts, missing rounds,
rollover, replay, atomic rollback, restart/retry, source enrichment, destination
gates, and API reads. No live messages are needed for verification.
