# Lucky28: commands and feature guide

Updated: 24 October 2026. This guide describes the current Number Game application.
For detailed alert behavior and implementation notes, see [README.md](README.md).
For the independent Number Game recorder, reasons log and prediction experiments,
see [Case study commands and evidence rules](CASE_STUDY.md). It starts with `run.py`;
use `--no-case-study` to omit the recorder.

## Contents

- [Start, stop and restart](#start-stop-and-restart)
- [Browser and logger configuration](#browser-and-logger-configuration)
- [Pages and features](#pages-and-features)
- [Number palette and Newest strip](#number-palette-and-newest-strip)
- [Gaps, streaks and graphs](#gaps-streaks-and-graphs)
- [Alert types and Telegram](#alert-types-and-telegram)
- [History, import and export](#history-import-and-export)
- [Maintenance commands](#maintenance-commands)
- [Tests and previews](#tests-and-previews)
- [Files, logs and backups](#files-logs-and-backups)
- [Troubleshooting](#troubleshooting)
- [API and source map](#api-and-source-map)

## Start, stop and restart

### Open the project

Run commands from the repository root unless a section says otherwise:

```bash
cd /Users/nilav/Documents/GitHub/lucky28_predictor
```

Requirements: Python 3.10+, Node.js 22+, npm, and Google Chrome. The launcher
creates/reuses `.venv` and installs missing project dependencies.

### First-time setup

```bash
python3 run.py --setup
```

This prepares dependencies, compiles the logger, applies database migrations,
synchronizes alert state, and adds missing default alert rules. It exits without
opening the game. Existing customized rules are preserved; deliberately deleted
default rules can be added again by this command.

Configuration is optional when defaults are suitable. To create `.env` only if
it does not already exist:

```bash
test -f .env || cp .env.example .env
```

### Normal daily start

```bash
python3 run.py
```

The launcher:

1. Checks dependencies, builds TypeScript, and applies migrations.
2. Restores color-group, 10-game and category alert state.
3. Starts Django, or reuses a compatible server already listening.
4. Opens Chrome using the saved project browser profile.
5. Loads `https://webapp.chametw.com/partyList` with mobile emulation enabled.
6. Joins the first available party, opens its game menu and selects Lucky Number.
7. Captures Number Game events and saves them to Django through a durable queue.

Open the dashboard at <http://127.0.0.1:8000/> and the Global Timeline at
<http://127.0.0.1:8000/alerts/timeline/>.

The game browser stays visible; the DevTools panel stays closed. Mobile user
agent, viewport and touch emulation are applied directly by the logger.
If Chamet requires login, sign in in that browser; navigation continues afterwards.
The logger does not click Play or place bets.

### Stop and restart

Press **Ctrl+C** in the launcher terminal. It closes the logger and the Django
server that this launcher started. It leaves an independently started/reused
Django server alone. Captured pending events remain on disk for the next start.

To restart after a code or `.env` change, stop the launcher, then run:

```bash
python3 run.py
```

The Telegram worker is a separate process. Stop it separately through
**Alerts → Telegram & worker → Stop worker** when you want all services stopped.

### Other startup commands

| Command | Purpose |
| --- | --- |
| `python3 run.py --check` | Check dependencies and connectivity to an already running authenticated logger API. |
| `python3 run.py --django-only` | Start the dashboard without opening Chrome or starting capture. |
| `python3 run.py --port 8001` | Use port 8001 for the dashboard and logger API. |
| `python3 run.py --host 127.0.0.1 --port 8001` | Set the local bind address and port explicitly. |
| `python3 run.py --replay /absolute/path/events.jsonl` | Submit captured events without opening Chrome; writes to the configured database and processes pending events. |
| `python3 run.py --help` | Show launcher options. |

An explicit `LUCKY28_API_URL` overrides the URL derived from host/port. Update or
remove that override when changing ports. Replaying a conflicting winner does
not overwrite the saved result: the logger API rejects it with HTTP 409.

### Run only the logger

First start Django in a separate terminal:

```bash
python3 run.py --django-only
```

Then, from the logger directory:

```bash
cd /Users/nilav/Documents/GitHub/lucky28_predictor/chamet_logger_standalone
npm run build
npm start
```

`npm start` reads the root `.env`. Do not run a second browser logger using the
same Chrome profile while the first is running. `npm test` runs tests; it does
not launch the live game.

### Keep the launcher running after closing Terminal

Use this instead of a foreground launcher, after checking that another instance
is not already running:

```bash
mkdir -p .local
nohup .venv/bin/python run.py > .local/app.log 2>&1 < /dev/null &
printf '%s\n' "$!" > .local/app.pid
```

This backgrounds the launcher process; Chrome remains visible. Inspect its log:

```bash
tail -f .local/app.log
```

Before stopping it, check that the saved PID still belongs to this project's
`run.py` (a PID file can become stale):

```bash
ps -p "$(cat .local/app.pid)" -o pid=,command=
```

After confirming the process identity, request a graceful stop:

```bash
kill -TERM "$(cat .local/app.pid)"
```

## Browser and logger configuration

Edit the root `.env`, then restart the launcher. Start with:

```dotenv
LUCKY28_HOST=127.0.0.1
LUCKY28_PORT=8000
CHAMET_GAME_URL=https://webapp.chametw.com/partyList
CHAMET_AUTO_OPEN=true
CHAMET_MOBILE=true
CHAMET_DEVTOOLS=false
CHAMET_HEADLESS=false
CHAMET_BROWSER_CHANNEL=chrome
CHAMET_VIEWPORT_WIDTH=375
CHAMET_VIEWPORT_HEIGHT=667
```

| Setting | Default | Function |
| --- | --- | --- |
| `CHAMET_GAME_URL` | Party-list URL above | Startup and recovery destination. A current room URL can also be supplied. |
| `CHAMET_AUTO_OPEN` | `true` | Automatically enter a party and select Number Game. `false` leaves navigation to you. |
| `CHAMET_MOBILE` | `true` | Apply mobile user agent and device emulation in the background. |
| `CHAMET_DEVTOOLS` | `false` | Set `true` to open the visible DevTools panel for troubleshooting. |
| `CHAMET_HEADLESS` | `false` | Set `true` to hide the entire browser; this also disables the visible DevTools panel. |
| `CHAMET_BROWSER_CHANNEL` | `chrome` | Browser channel. `chromium` requires an installed Playwright Chromium browser. |
| `CHAMET_VIEWPORT_WIDTH` / `CHAMET_VIEWPORT_HEIGHT` | `375` / `667` | Game viewport dimensions. |
| `CHAMET_PROFILE_DIR` | `.local/chamet-profile` | Saved browser login/profile. Relative paths resolve from the project root. |
| `CHAMET_DATA_DIR` | `.local/chamet` | Durable events, acknowledgements and signal feedback. |
| `CHAMET_PARTY_SELECTOR` | `.card` | Optional party selector override. Used on the party-list page. |
| `CHAMET_MENU_SELECTOR` | Game image selectors | Optional room game-menu selector override. |
| `CHAMET_NUMBER_SELECTOR` | Number Game images/labels | Optional Number Game option selector override. |
| `LUCKY28_API_URL` | Derived from host/port | Override the logger API base URL, ending in `/api/logger`. |
| `LUCKY28_LOGGER_TOKEN` | Generated local token file | Shared logger API credential; usually no manual setting is needed. |
| `LUCKY28_DB_PATH` | `lucky28.db` | Database path; relative paths resolve from the project root. |
| `ALERT_STATE_DIR` | `.local/alerts` | Worker lease, saved alert configuration, token and logs. |
| `ALERT_TELEGRAM_ENABLED` / `ALERT_TELEGRAM_BOT_TOKEN` | Disabled / empty | Initial Telegram defaults; saved UI configuration takes precedence. |
| `ALERT_PUBLIC_BASE_URL` | Empty | Externally reachable app origin for links in Telegram messages. |

Keep room URLs containing `&` in a quoted `.env` value. Room links may stop
working when the room/session changes; the party-list URL is the normal startup
destination. Headless mode needs an existing usable login because no interactive
browser is displayed.

After a game-opening attempt or valid Number Game activity, two minutes without
packet progress triggers reopening the configured URL. Unrelated console logs
and repeated copies of the same frozen winner do not count as progress.
The logger waits for initial login rather than repeatedly restarting Chrome.

## Pages and features

All paths below are relative to `http://127.0.0.1:8000` unless you changed the port.

| Page | Path | Available functions |
| --- | --- | --- |
| Dashboard | `/` or `/games/dashboard/` | View rounds, date selection and game details. |
| Round details | `/games/detail/<game_no>/` | Inspect a saved round and its pre-result/winner data. |
| Global Timeline | `/alerts/timeline/` | Shared 150-game tracks, palette, Newest strip, group metrics and gap graphs. |
| Alerts overview | `/alerts/` | Current patterns, saved evaluations, activations and worker status. |
| Color absence | `/alerts/groups/` | Seven color groups, absence counters and event history. |
| Color settings | `/alerts/groups/settings/` | Enable groups and configure thresholds. |
| Recent 10 games | `/alerts/windows/` | Enable rolling-window drought/repeat alerts and inspect their evidence. |
| Rows and categories | `/alerts/categories/` | Row, column and combination absence/streak states. |
| Category settings | `/alerts/categories/settings/` | Per-group absence/streak thresholds and follow-up settings. |
| Alert rules | `/alerts/rules/` | Add, edit, enable, disable, delete or restore missing default rules. |
| Telegram destinations | `/alerts/destinations/` | Chats/channels, plans, expiry, cards and result/health delivery options. |
| Telegram and worker | `/alerts/settings/` | Token, delivery settings, timing and worker start/stop. |
| Deliveries | `/alerts/deliveries/` | Pending/sent/failed history, card previews, cancellation and eligible retries. |
| Signals | `/signals/` | Saved signal triggers. |
| Signal configuration | `/signals/config/` | Streak/drought signal rules and thresholds. |
| Pro Analysis | `/analysis/` | Date/range analysis, frequency charts, hot/cold lists, streaks, empirical statistics and repetition analysis. |
| Live Gaps | `/gaps/` | Current and historical number gaps from saved results. |
| Daily archive | `/days/` | Daily summaries, CSV downloads and confirmed day deletion. |
| Import | `/games/import/` | Upload one or more dated CSV files. |

## Number palette and Newest strip

### Layout and selection

- Numbers **0–27** stay in a fixed **4 × 7** board.
- A fresh page starts in **Auto last 10**, selecting the unique numbers in the
  latest ten available completed results. Repeated appearances count separately
  in each tile's hit count.
- Clicking a number or selection group enters **Manual** mode. Purple indicates
  selection; hit counts, Latest and New/Repeated tags remain result information.
- **Details** opens a number's history without changing selection.
- Last 10, Absent in last 10, S/B/E/O/SE/SO/BE/BO, row and column controls share
  one selected set. If a whole group is selected, clicking removes its members;
  otherwise it adds missing members. Numbers outside that group are unchanged.
- S followed by E produces their **union**. Select SE when you want only small
  even numbers. Partial selection counts are shown on group controls.
- Manual selection survives polling, corrections and stream switches within the
  open page. A full page reload starts Auto again.

| Code | Meaning |
| --- | --- |
| S / B | Small 0–13 / Big 14–27 |
| E / O | Even / Odd; zero is even |
| SE / SO | Small Even / Small Odd |
| BE / BO | Big Even / Big Odd |
| R1 / R2 / R3 / R4 | 0–6 / 7–13 / 14–20 / 21–27 |
| C1–C7 | Fixed columns: C1 = 0,7,14,21; C2 = 1,8,15,22; and so on. |

### Color groups

| Group | Numbers | Other labels used in older views |
| --- | --- | --- |
| Red | 0, 1, 26, 27 | — |
| Orange | 2, 3, 24, 25 | Yellow |
| Magenta | 4, 5, 22, 23 | Pink |
| Blue | 6, 7, 20, 21 | — |
| Cyan / Teal | 8, 9, 18, 19 | Cyan |
| Green | 10, 11, 16, 17 | — |
| Grey | 12, 13, 14, 15 | Gray |

### New / Repeated tags

Each result is compared with its **own previous 10 completed rounds**, excluding
itself. A result is New if its number does not appear there; otherwise Repeated.

| Tag | Appearance and meaning |
| --- | --- |
| New | Teal badge. |
| Repeated | Amber badge. |
| N×2, N×3… | Consecutive New classifications. |
| R×2, R×3… | Consecutive Repeated classifications; the repeated numbers can differ. |
| Latest | Separate marker for the newest completed result. |
| Building history / History gap | Neutral gray; insufficient or discontinuous prior history. |

Only the latest result displays the run counter. When classification changes,
the new run starts at one; older results keep only New or Repeated. Unknown
classification breaks the run. A palette tile uses its most recent appearance
within the displayed ten; absent tiles have no New/Repeated badge.

### Newest display

Up to 150 result circles sit in a compact vertical scroll area directly below
the board, newest first. Scroll down for older results and up for newer results,
or use **Back to newest**. Live updates preserve your position when browsing
older rounds. Palette highlights and hit counts still use the latest ten.
Click a circle or the View button
to cycle the whole strip through:

**Number → Size → Parity → Combination → Number**.

Number mode uses color-group colors; the other modes use distinct category
colors. View changes do not alter selected numbers or probability totals.
Game details provides the focused round's ID, timestamp and detail link. Narrow
layouts use five circles per row instead of ten; the board can scroll horizontally.

### Selected-number probability comparison

The comparison appears at the top right beside the palette controls. On narrow
screens it sits below the controls and above the number board for easy access.

The panel compares the selected numbers with their complement using the stated
model of **three independent, uniformly distributed digits 0–9**. It sums integer
weights over 1,000 possible outcomes. The target sizes 1, 3, 5, 10 and 14 report
selection-count differences; they do not automatically choose numbers.

This is a theoretical coverage calculation, not a prediction of the next number
or a guarantee about the game's actual distribution or payout.

## Gaps, streaks and graphs

- **Gap:** observed completed rounds since any member of a number/group appeared.
  An appearance resets that group's gap to zero.
- **Streak:** consecutive matching results ending at the newest completed round.
- Column gaps appear above the board, row gaps on the left, row streaks on the
  right and column streaks below. Category buttons have Streak above and Gap below.
- Red highlights maximum positive gaps; green highlights maximum positive
  streaks. Tied maxima are included within the corresponding comparison family.
- Gap analytics has **Rows, Columns, Size, Parity, Combos, Colors and Range** tabs.
  Sort by largest gap, smallest gap or natural order.
- Gap history shows the current ongoing gap and up to 30 completed gaps.
- `+` means the available history limits the count; `*` marks missing/unverified
  boundaries. N/A means a reliable current value cannot be established.
- The palette, timeline and Live Gaps derive from the same saved completed rounds.
  Missing rounds are not invented or counted as observed results.

The timeline covers **150 completed games**, newest first, in pages of 25.
Tracks include number, size, parity, combination, color, row, column, extremes,
previous-two repeats, 10-game windows and recorded alerts. Click a timeline dot
for its round details and evidence.

Visible, unpaused timelines poll every second without overlapping requests.
Unchanged responses use HTTP 304. Failed requests retry after five seconds and
show stale status while retaining the last loaded view. Refresh now fetches data;
**Cmd+R** loads updated page code after a UI change.

A track's Reset hides earlier history for the current session/stream. Restore
history reverses it. These controls do not delete results or reset alert counters.

## Alert types and Telegram

### Different repeat definitions

| Feature | Comparison |
| --- | --- |
| Palette / Newest New–Repeated tag | Current result versus **10 prior rounds**; 11 rounds including the current result. |
| Recent 10-game repeat alert | Newest result versus the **previous 9** inside a total window of 10. |
| Recent 10-game drought alert | All 10 numbers in the current window are distinct. |
| Timeline Repeat track | Repeat against the previous two games. |

For 10-game alerts, an earlier duplicate still in the window does not trigger a
new repeat alert unless the newest result matches. A drought alert fires once
per continuing all-distinct period. Missing results pause unreliable evaluations.

### Other alert functions

| Alert family | Functions |
| --- | --- |
| Pre-round pattern rules | Streaks, droughts, density, alternation, streak breakers and individual-number droughts. Freeze evidence from results known before that round. |
| Color-group absence | Thresholds for all seven color groups, current counts and durable occurrence history. |
| Rows / columns / combinations | Absence and streak thresholds for 4 rows, 7 columns and SE/SO/BE/BO. |
| Category endings | Optional follow-ups when a previously delivered absence or streak ends. |
| Result follow-ups | Optional winner result for a previously delivered pre-round alert. |
| Collection health | Optional warning when fresh events stop for the configured interval. |

Alert records, thresholds and notification identities survive restarts. Repeated
ingestion does not create duplicate winners or re-send the same activation.
Cards include symbols, counts, member numbers and a frozen timeline snapshot;
text fallback remains available if image rendering fails.

### Enable Telegram delivery

1. Open **Alerts → Telegram & worker** and save the bot token and delivery settings.
2. Open **Destinations**, add the chat/channel and enable its desired options.
3. Configure the relevant rules or group thresholds and save them.
4. Start the worker through **Telegram & worker → Start worker**.
5. Inspect **Deliveries** for status and evidence. Send test message explicitly
   queues a real test to that destination.

Starting `run.py` does not start the Telegram worker. For a terminal-managed worker:

```bash
.venv/bin/python django_lucky28/manage.py run_alert_messaging
```

Process one worker cycle and exit:

```bash
.venv/bin/python django_lucky28/manage.py run_alert_messaging --once
```

These worker commands can send real queued notifications when delivery is enabled.
A lease prevents two workers sharing the same alert-state directory from running
simultaneously. Stop a foreground worker with Ctrl+C, or use the UI Stop worker.
The `--managed` flag is used internally by the UI launcher.

Uncertain Telegram outcomes are not automatically retried because Telegram sends
do not support the logger API's result deduplication. Definitively failed messages
can be reviewed and retried through Deliveries where allowed.

## History, import and export

- Saved history lives in `lucky28.db`; starting another day does not replace it.
- Daily archive dates use the configured Django timezone, currently **UTC**.
- Import one or more CSV files at `/games/import/`. Timestamps are required;
  invalid/conflicting rows cancel the upload rather than partially importing it.
- Re-importing the same records recognizes saved results. Historical imports do
  not send live alerts. Original round IDs help preserve continuity checks.
- Download a day's CSV before using the archive's confirmed Delete action.
  Deleting a day permanently removes its results and associated signal history.

Example supported CSV:

```csv
result,timestamp,winners_count,prize_amount
19,2026-10-23 01:03:00,467,37006000
17,2026-10-23 01:04:00,450,30000000
```

Use the application's exported CSV when you need game IDs retained for re-import.

## Maintenance commands

Run these from the project root. Commands that synchronize state can create
current alert events/outbox entries according to the saved settings; the worker
performs any actual delivery.

| Command | Purpose / effect |
| --- | --- |
| `.venv/bin/python django_lucky28/manage.py check` | Validate Django configuration. |
| `.venv/bin/python django_lucky28/manage.py migrate --noinput` | Apply schema migrations. Also runs during normal launcher startup. |
| `.venv/bin/python django_lucky28/manage.py showmigrations` | List migration status. |
| `.venv/bin/python django_lucky28/manage.py seed_alert_rules` | Add missing alert defaults without overwriting existing rule customization. |
| `.venv/bin/python django_lucky28/manage.py seed_signal_rules` | Add missing default signal rules. |
| `.venv/bin/python django_lucky28/manage.py sync_group_absence` | Reconcile color-group absence state. |
| `.venv/bin/python django_lucky28/manage.py sync_window_alerts` | Reconcile current 10-game alert state. |
| `.venv/bin/python django_lucky28/manage.py sync_category_alerts` | Reconcile row, column and combination alert state. |
| `.venv/bin/python django_lucky28/manage.py backfill_colors` | Update stored winner-color labels for existing results. |
| `.venv/bin/python django_lucky28/manage.py calculate_historical_gaps` | Rebuild legacy `NumberGapStat` counters. Current Live Gaps uses shared result history instead. |
| `.venv/bin/python django_lucky28/manage.py help` | List Django and project management commands. |
| `.venv/bin/python django_lucky28/manage.py help run_alert_messaging` | Show worker options. |

The legacy `simulate_even_streak` command writes six artificial results and can
invoke configured WhatsApp notifications. It is for an isolated disposable test
environment, not normal startup or live-data troubleshooting. Use the automated
tests below to verify production behavior without inserting synthetic live games.

Optional older Streamlit interface:

```bash
.venv/bin/streamlit run streamlit_lucky28/app.py
```

It uses the older workflow and is not started by `run.py`. Use the Django Import
page for the current dashboard, timeline and daily archive.

## Tests and previews

These commands are for verification; they do not start a live Chamet session.
Browser checks need Chrome and permission to bind local test ports.

| Command | Checks |
| --- | --- |
| `npm --prefix chamet_logger_standalone test` | Build TypeScript; validate Number Game mapping, navigation health, queue retries and deduplication. |
| `npm --prefix chamet_logger_standalone run build` | Compile TypeScript without running tests. |
| `.venv/bin/python django_lucky28/manage.py test games.tests --noinput` | Django ingestion, alerts, history, timeline and related tests. |
| `.venv/bin/python django_lucky28/manage.py test games.tests.test_logger_api --noinput` | Logger API validation, idempotency and database-busy handling. |
| `.venv/bin/python django_lucky28/manage.py test games.tests.test_category_alerts --noinput` | Category thresholds, corrections and ending follow-ups. |
| `.venv/bin/python django_lucky28/manage.py test games.tests.test_timeline --noinput` | Timeline/history behavior. |
| `node scripts/check_number_model.js` | Number-selection and theoretical probability calculations. |
| `.venv/bin/python scripts/check_logger_integration.py` | Local fixture: party → menu → Number Game iframe → Django → signal feedback. Uses a temporary database/profile. |
| `.venv/bin/python scripts/check_timeline_ui.py` | Palette, selections, tags, live updates and responsive timeline UI in an isolated database. |
| `.venv/bin/python scripts/check_alert_ui.py` | Alert management forms, validation and desktop/mobile layouts in an isolated database. |
| `.venv/bin/python scripts/preview_alert_cards.py` | Generate fictional local JPEG card previews; sends no Telegram messages. |
| `python3 -m unittest dataFeeds.test_extract_html_data` | Legacy HTML data-extraction tests. |

Card previews are written to `.local/telegram-card-previews/`.

`src/tests/logger.test.ts` contains tests; live startup is in `src/main.ts`.
The copied `src/tests/chamet_logger.spec.ts` Car Game reference is excluded from
the active TypeScript build and is not the Number Game startup command.

## Files, logs and backups

| Location | Contents |
| --- | --- |
| `.env` | Local configuration. |
| `lucky28.db` | Saved results, rules, alert evidence and delivery records. |
| `.local/logger-token` | Generated logger API credential. |
| `.local/chamet-profile/` | Chrome session/login data. |
| `.local/chamet/pending/` | Captured events awaiting acknowledgement. |
| `.local/chamet/failed/` | Rejected events and response details. |
| `.local/chamet/delivered.jsonl` | Successfully acknowledged normalized events. |
| `.local/chamet/received-signals/` | Deduplicated signal feedback files. |
| `.local/chamet/signals.jsonl` | Signal feedback journal. |
| `.local/alerts/worker.log` | UI-started Telegram worker log. |
| `.local/alerts/bot-token` | Saved Telegram token, when configured through the UI. |
| `.local/app.log` / `.local/app.pid` | Created by the optional background-launch command in this guide. |

A foreground launch writes logs to its terminal. A startup performed with another
log redirection uses that chosen filename, not automatically `.local/app.log`.

Useful log commands:

```bash
tail -f .local/alerts/worker.log
tail -n 20 .local/chamet/delivered.jsonl
```

### Database backup

Use SQLite's backup API instead of copying a database while it is being written.
This command reads the configured database and creates a timestamped backup:

```bash
.venv/bin/python - <<'PY'
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

root = Path.cwd()
load_dotenv(root / '.env')
source_path = root / os.environ.get('LUCKY28_DB_PATH', 'lucky28.db')
backup_dir = root / '.local/backups'
backup_dir.mkdir(parents=True, exist_ok=True)
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
target_path = backup_dir / f'lucky28-{stamp}.sqlite3'
source = sqlite3.connect(source_path.resolve().as_uri() + '?mode=ro', uri=True)
target = sqlite3.connect(target_path)
try:
    source.backup(target)
finally:
    target.close()
    source.close()
print(target_path)
PY
```

A database backup does not include the browser login, queued capture files or
Telegram token/settings files. Keep those separately if you need full recovery.
Stop the app and worker before manually restoring a database. Do not delete
SQLite journal files as a lock-error workaround.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Chamet redirects to its public homepage | Keep `CHAMET_MOBILE=true`, use the party-list URL, and restart. Mobile emulation is independent of the DevTools panel. |
| A login screen appears | Sign in once using the project Chrome window. Keep the same profile directory. |
| Party/menu/Number Game does not open | Watch `[navigation]` messages. Check current labels/selectors or use `CHAMET_AUTO_OPEN=false` to navigate manually. |
| Want DevTools visible temporarily | Set `CHAMET_DEVTOOLS=true` and restart. Set it back to `false` afterwards. |
| Chrome reports that its profile is in use | Stop the other logger using that profile before starting another. |
| API connection check fails | Start Django; verify host, port, API URL and shared token. `--check` does not start a stopped server. |
| Port is already occupied | Stop the conflicting instance or use another port. A compatible server is reused automatically. |
| New results seem delayed | Check the latest saved round, `[saved]` / `[retry]` logs and pending queue; verify the game is receiving packets. |
| `database is locked` / HTTP 503 | Ingestion rolls back and returns a retryable busy response; the captured event stays queued. Avoid duplicate writers, check worker health, and confirm the current code is running. |
| Broken pipe / timeout | The client may have disconnected before the response. Current logger timeout is 35s, exceeding the 20s SQLite lock wait; inspect queue acknowledgements rather than assuming loss. |
| No Telegram alerts | Check rule/group switches, thresholds, continuity, destination enablement/expiry, global delivery setting and worker status. Inspect Deliveries for the actual reason. |
| Question mark, Building history, History gap | There is insufficient verified history for that calculation. Import/reconcile genuine missing results; do not fabricate them. |
| UI looks unchanged after a code update | Reload with Cmd+R. Refresh now only refreshes data. Backend/logger changes require a process restart. |
| Wrong archive date | Archive/analysis dates currently use UTC, which can differ from the local date. |
| An event appears in `failed/` | Review its response file. Invalid or conflicting events are preserved rather than silently discarded or used to overwrite a winner. |

## API and source map

The active logger authenticates with `X-Lucky28-Token`. Its main endpoints are:

| Method and path | Function |
| --- | --- |
| `GET /api/logger/health/` | Authenticated service/schema check. |
| `POST /api/logger/events/` | Validate and save a pre-result/winner event; return acknowledgement, duplicate flag and signal feedback. |
| `GET /api/trackers/live/` | Shared live timeline/palette data; supports conditional responses. |
| `POST /api/trackers/<tracker_key>/reset/` | Session/stream timeline visibility controls. |
| `GET /api/gaps/` | Shared number-gap statistics. |
| `GET /api/alerts/latest/` | Latest frozen alert evaluation. |
| `GET /api/games/` | Saved game list. |
| `GET /api/games/<game_no>/` | Saved game record. |
| `POST /analysis/api/simulate/` | Streak simulation under supplied assumptions. |

Older `POST /api/games/pre/` and `POST /api/games/<game_no>/winner/` routes remain
for existing integrations; the active browser logger uses `/api/logger/events/`.
UI management mutations use their forms with POST/CSRF handling. See
[`urls.py`](django_lucky28/apps/games/urls.py) for the complete route list.

| File / module | Responsibility |
| --- | --- |
| [`run.py`](run.py) | Setup, build, database preparation and process lifecycle. |
| [`main.ts`](chamet_logger_standalone/src/main.ts) | Browser launch, console/WebSocket capture and shutdown. |
| [`navigation.ts`](chamet_logger_standalone/src/navigation.ts) | Party/menu/Number Game navigation and stalled-capture recovery. |
| [`config.ts`](chamet_logger_standalone/src/config.ts) | Browser, API, profile and queue settings. |
| [`packets.ts`](chamet_logger_standalone/src/packets.ts) | Number Game normalization, race-packet rejection and milestone deduplication. |
| [`bridge.ts`](chamet_logger_standalone/src/bridge.ts) | Durable queue, API delivery/retries and local signal feedback. |
| [`logger_api.py`](django_lucky28/apps/games/logger_api.py) | Authenticated ingestion, conflicts, transactions and busy responses. |
| [`timeline.py`](django_lucky28/apps/games/services/timeline.py) | Timeline classifications and recorded alert evidence. |
| [`timeline.js`](django_lucky28/apps/games/static/games/timeline.js) | Palette, Newest strip, graphs and live UI refresh. |
| [`number_model.js`](django_lucky28/apps/games/static/games/number_model.js) | Selection operations and theoretical probability weights. |
| [`alerts.py`](django_lucky28/apps/games/services/alerts.py) | Pre-round evidence, result follow-ups and collection health. |
| [`group_absence.py`](django_lucky28/apps/games/services/group_absence.py) | Color-group continuity and absence state. |
| [`window_alerts.py`](django_lucky28/apps/games/services/window_alerts.py) | Rolling 10-game alert evaluation. |
| [`category_alerts.py`](django_lucky28/apps/games/services/category_alerts.py) | Row/column/combination absence and streak reconciliation. |
| [`category_changes.py`](django_lucky28/apps/games/services/category_changes.py) | Ending evidence and follow-up delivery eligibility. |
| [`alert_delivery.py`](django_lucky28/apps/games/services/alert_delivery.py) | Telegram queue delivery and retry/uncertain outcome handling. |
| [`alert_worker.py`](django_lucky28/apps/games/services/alert_worker.py) | UI worker start/stop and lease handling. |

The application describes saved outcomes and configured models. It does not
guarantee the next winning number, and capture/analysis do not place bets.

## Color-group absence endings

Open `/alerts/groups/settings/` and adjust **Minimum missed rounds before return** for each
color. The **Notify when group returns** switch is independent of the existing
absence-in-progress switch. Both respect the stream's delivery switch and the
existing Telegram destination/worker settings. Values are whole rounds, 1–1,000,000;
separate bulk-fill controls populate absence and ending thresholds before Save.

Example: Red's ending threshold is 100. After 164 consecutive completed results
outside Red, number 26 arrives. One **Red absence ended — 164 missed rounds**
notification is recorded with the returning number, ending round, configured
threshold, and frozen global timeline. A prior absence notification is not
required. The returning round is not included in the 164 missed rounds.

Existing configured color groups initially use their saved absence thresholds
and enabled flags for endings. Later edits are independent and audited. Saving
settings, importing old history, or restarting does not replay old endings.
Endings need a verified prior appearance and every intervening round. Historical
gaps remain visible but do not block unrelated, fully verified recent periods.
Corrections preserve original ending evidence and cancel invalid unsent messages.

See **Absence ended history** on `/alerts/groups/` and **Deliveries** for status.
The existing maximum event age applies to ending delivery. Verification commands:

```sh
.venv/bin/python django_lucky28/manage.py test games.tests.test_group_endings games.tests.test_group_absence --noinput
.venv/bin/python scripts/check_group_endings_ui.py
```

The browser check uses a temporary database with Telegram disabled.

### Recognizing alert cards

Cards and Telegram captions identify the group family explicitly: **ROW ABSENCE
ENDED**, **COLUMN ABSENCE ENDED**, **COLOR ABSENCE ENDED**, or **COMBINATION
ABSENCE ENDED**. Rows use cyan horizontal bars and an R badge; columns use amber
vertical bars and a C badge. Combinations use a purple diamond and their SE/SO/
BE/BO code. Color groups use their configured color and G code. Every ending
shows the returning number and the number of missed rounds before it returned.
Active absence and streak notifications also carry their family name; streak
endings remain explicitly labeled STREAK ENDED. These visual identities do not
change trigger thresholds or result calculations.
