# Number Game case study

Open **Case study** in the navigation or `http://127.0.0.1:8000/case-study/`.
This separate research page reads saved games and writes its own evidence journal,
`.local/case-study.sqlite3`. It does not change the palette, alert rules, result
ingestion, or deliveries, and does not send Telegram messages.

## Commands

Normal startup automatically starts the separate recorder:

```sh
python3 run.py
```

The recorder stops with that launcher. An exclusive process lock prevents two
recorders from writing the same journal. Recorder failures do not stop the main
logger or dashboard. Output is in `.local/case-study-worker.log`; the page shows
the recorder heartbeat and any error.

Run separately when Django is already running, or reconcile once:

```sh
.venv/bin/python django_lucky28/manage.py case_study_worker
.venv/bin/python django_lucky28/manage.py case_study_worker --once
```

The default interval is one second; `--interval 2` changes it. Ctrl+C stops a
foreground worker. `python3 run.py --no-case-study` starts the main application
without starting this recorder. Set `CASE_STUDY_DB_PATH` to override the journal
path. Back up the journal with SQLite's backup API, or stop the worker before
copying the database and any WAL/SHM files. Keep the journal to retain the study.

## Evidence recorded

- A fresh pending round gets one immutable forecast: round ID, recording time,
  history cutoff, up to 150 earlier results, model version, all 28 estimated
  probabilities, top 1/3/5 candidates and the reasons behind their rankings.
- Three fixed methods are compared: the theoretical digit-sum distribution,
  frequency over 150 observed results (baseline prior strength 100), and frequency
  over ten observed results (baseline prior strength 20).
- Completed cases include digit calculation when available, New/Repeated status,
  observed number absence, size/parity/combination/color/row/column matches,
  ended gaps and streak changes, selection hits and misses, and saved earlier
  alert evidence where available.
- Corrections append revisions. Original forecasts and reviews stay in the log;
  aggregate scores use the latest case revision.

The initial historical review covers the latest 150 completed rounds per stream.
The recorder then follows source updates, including catch-up after downtime.
The page shows 150 recent cases; older cases remain in the journal. Only valid,
dated numeric production-style IDs are included. Synthetic `TEST_`/`GAME_` IDs,
invalid numbers, and undated or unfinished results are excluded.

## Timing and interpretation

**Before receipt** means a forecast was saved before the local browser observed
the result. This does not prove it preceded provider generation or the betting
deadline: those timestamps are unavailable.

**Historical review** replays fixed methods using earlier saved results. Current
history may contain later imports/corrections; these are not predictions recorded
at the time. **Late record** means a forecast was saved at or after result
observation and is excluded from aggregate prediction scores.

The manual dashboard selection is neither captured nor changed. Candidates in
this page come from the independent case-study methods. Missing digits remain
unavailable. `received_at` is the source row's last-update time, not verified first
receipt; `logged_at` is when the journal saved the review.

Adjacent numeric IDs within the same date establish continuity. Date boundaries
are unknown continuity, not exact missing-round counts. New/Repeated requires ten
continuous preceding rounds and a continuous link to the target. Absences count
only observed non-matching rounds and mark incomplete history. Group labels all
describe the same result; they are not independent confirming signals.

Theoretical probabilities assume three independent uniform digits from 0–9;
this assumption is unverified for the provider. Equal probabilities are ordered
by smaller number purely for determinism. Frequency estimates are experimental,
not calibrated confidence. Long gaps do not make a number due. Observed pattern
matches are distinguished from the unavailable generation cause.

## Evaluation and exports

Performance includes sample count, hits, misses and hit rate for top 1/3/5. Each
method is compared with the theoretical baseline's actual outcomes on the same
rounds and shortlist size. Historical and before-receipt samples stay separate.
The API also includes summed theoretical expected coverage of the chosen sets.
No statistical-significance or predictive-advantage claim is made; further live
samples and a predefined evaluation period are needed. No model is automatically
promoted as best.

**Download log** exports append-only JSONL events containing forecast inputs,
all reasons, results, and revisions. Event kinds are `forecast_locked`,
`result_review`, and `result_revision`.

Read-only endpoints:

- `GET /api/case-study/?stream=lucky28`: recorder, rankings, performance, cases.
- `GET /api/case-study/<case_id>/`: full saved evidence for a revision.
- `GET /case-study/export/?stream=lucky28`: complete event journal export.

## Verification

```sh
.venv/bin/python django_lucky28/manage.py test games.tests.test_case_study --noinput
.venv/bin/python scripts/check_case_study_ui.py
```

These use temporary databases and send no notifications. Browser verification
uses the existing logger's Playwright package and installed Chrome.
