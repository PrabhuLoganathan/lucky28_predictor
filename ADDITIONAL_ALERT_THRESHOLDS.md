# Additional history-based alert proposals

These are **proposed observational alerts**, with configurable thresholds. They
have not been enabled in the application. They describe completed results; they
do not establish which number comes next or why the provider generated it.

## History used

The review uses 4,013 dated, completed Lucky28 rounds through **202610241199**
(24 October 2026, 13:18:26 UTC / 18:48:26 IST). The first 2,809 rounds calibrate
thresholds. The later 1,204 estimate notice frequency. This is the same historical
period used in [the previous review](ALERT_HISTORY_REVIEW.md), not a new independent
validation sample. Next-result prediction accuracy was **not** evaluated here.

Missing links and date boundaries split this data into 177 sequences. Ten-game
metrics have 1,720 eligible training windows and 988 later windows. Twenty-game
metrics have 1,020 eligible training windows and 823 later windows. Repeated
numbers remain separate results; records are unique by round ID.

For each metric, the default is the least restrictive observed integer threshold
that matches **at most 5% of eligible training windows**. This avoids integer
percentile ties: a nominal 95th-percentile threshold can match far more than 5%
when many observations equal it. Overlapping windows are not independent, and
this calibration does not guarantee future rarity or a predictive advantage.

## Recommended defaults

| Proposed alert | Trigger, including the just-completed round | Required consecutive results | Training windows matched | Later notices |
|---|---|---:|---:|---:|
| Number concentration | **5 or fewer distinct numbers in the last 10** | 10 | 28 / 1,720 (1.63%) | **4** |
| Complete number-set change | **Zero shared distinct numbers** between the previous 10 and latest 10 | 20 | 8 / 1,020 (0.78%) | **4** |
| Size balance shift | Small count changes by **at least 5** between those two windows | 20 | 34 / 1,020 (3.33%) | **19** |
| Parity balance shift | Even count changes by **at least 5** between those two windows | 20 | 49 / 1,020 (4.80%) | **9** |
| Narrow number range | **Maximum minus minimum ≤9** in the last 10 | 10 | 66 / 1,720 (3.84%) | **14** |
| Two-color concentration | The two most frequent color groups account for **9 or more of the last 10 results** | 10 | 84 / 1,720 (4.88%) | **19** |

Later notices use the reset/cooldown settings below. They are counts of notices
that would have been logged, **not wins, successful predictions, or daily rates**.
Different alerts can occur together; do not add their counts as independent
evidence. Counting broad coverage at ten distinct numbers was also examined, but
it duplicates the existing ten-game drought alert and is not proposed again.

Definitions and useful card content:

- **Number concentration:** show the distinct numbers and every hit count.
  Five distinct numbers in ten results means five duplicate appearances beyond
  each number's first appearance. It does not mean five consecutive repeats or
  five `Repeated` classifications against each round's preceding ten.
- **Complete number-set change:** compare disjoint windows `results[-20:-10]`
  and `results[-10:]`. Duplicates count once for the set intersection. Show the
  previous set, current set, and shared numbers. This describes a past change,
  not a prediction that the next number will be New.
- **Size balance shift:** `abs(S_now - S_previous) ≥5`. Example: Small goes from
  2/10 to 7/10. Big changes by the opposite amount, so send one size alert.
  Small 0–13, Big 14–27. A shift does not necessarily mean a reversal.
- **Parity balance shift:** `abs(E_now - E_previous) ≥5`. Example: Even goes from
  8/10 to 3/10. Odd is complementary; do not send a duplicate alert.
- **Narrow number range:** show the minimum, maximum, and span. Results from
  9 through 18 have span 9; not every integer between them must have appeared.
- **Two-color concentration:** show both color names, members, and individual
  counts, using existing game color mappings. Example: Grey 5 + Green 4 = 9/10.
  The condition includes all ten results belonging to just one color. Resolve
  equal-count color ties by stable group ID. A change in the leading pair alone
  does not start a new episode.

## Threshold options for configuration

The default column is the calibrated, quieter setting. Watch thresholds are
more sensitive training-quantile suggestions; their notice counts are not those
reported above. Keep watch status on the dashboard rather than notifying by
default. Labels indicate sensitivity, not prediction confidence.

| Setting | Watch threshold | Default notice threshold | Valid threshold range |
|---|---:|---:|---:|
| Distinct numbers in last 10 | ≤6 | **≤5** | 1–10 |
| Shared distinct numbers across adjacent 10s | ≤1 | **0** | 0–10 |
| Absolute Small-count change | ≥4 | **≥5** | 1–10 |
| Absolute Even-count change | ≥4 | **≥5** | 1–10 |
| Last-10 numeric span | ≤10 | **≤9** | 0–27 |
| Top-two-color total hits | ≥8 | **≥9** | 1–10 |

Changing the window size requires fresh calibration; do not carry these
thresholds unchanged to windows of 20, 50, or 150 results. In particular, a zero
threshold is valid for shared-set size and numeric span, even though the current
generic threshold validator accepts only positive values.

## Shared behavior

1. **Start in case-study log-only mode**, separately from existing alert engines.
   No Telegram delivery by default. Give each rule a stable key and version.
2. **Evaluate once per completed round** after its authoritative result is saved.
   Capture the round ID, time received, input round IDs and numbers, before/after
   counts, threshold, and exact matched condition. Later corrections append a
   revised observation; they do not silently overwrite original evidence.
3. **Require consecutive history.** Deduplicate by round ID and require the full
   10 or 20 consecutive results. An unverified link produces `Insufficient
   history`, not zero absence, a reset notification, or a fabricated transition.
4. **Establish a baseline after warmup.** The first full window after startup or
   a history gap sets the observed state without sending a catch-up notice.
5. **Notify/log once on activation.** Rearm only after **two consecutive completed
   results** for which the condition is false. After the first normal result the
   UI can say `Recovering`; it must not claim the condition still holds.
6. **Use a ten-round cooldown per rule and stream**, measured from its last
   emitted activation. A crossing inside cooldown is logged as suppressed and
   consumed, not queued for a stale notification later. Rearming remains required.
7. **Persist state across refresh/restart.** A rule edit establishes a new
   baseline; it must not manufacture a fresh result event. Duplicate API updates
   do not advance warmup, reset counters, or cooldown.
8. **Keep overlapping alerts understandable.** Group observations from the same
   round into a card. A cluster plus narrow range plus color concentration is not
   three independent confirmations of the next result.

## Proposed settings shape

This YAML is a design/configuration reference, **not an existing import format**.
These dynamic metrics need a separate evaluator and settings UI; adding these
keys to the current application will not activate them.

```yaml
status: proposal_only
scope: additional_history_alerts
stream: lucky28
delivery: case_study_log_only
telegram_enabled: false

defaults:
  window_results: 10
  comparison_windows: adjacent_non_overlapping
  require_consecutive_rounds: true
  initial_window: baseline_only
  reset_after_normal_rounds: 2
  cooldown_rounds: 10
  minimum_training_windows: 500
  maximum_training_match_fraction: 0.05

rules:
  low_distinct_10:
    operator: lte
    threshold: 5
    required_results: 10
  low_overlap_20:
    operator: lte
    threshold: 0
    required_results: 20
  size_shift_20:
    operator: gte
    threshold: 5
    required_results: 20
  parity_shift_20:
    operator: gte
    threshold: 5
    required_results: 20
  narrow_span_10:
    operator: lte
    threshold: 9
    required_results: 10
  two_color_10:
    operator: gte
    threshold: 9
    required_results: 10
```

The strongest starting priorities are **number concentration, size/parity
balance shifts, and two-color concentration**: their cards explain the observed
change directly. Set turnover and numeric range can remain optional research
rules. Priority is based on interpretability, not a demonstrated betting edge.

Before testing a predictive use, freeze the exact candidate number set and
evaluation horizon before the next result. Record hits and misses, compare with
coverage-adjusted baselines, and use later unseen data. A factual alert can be
correct even when it has no next-number predictive value.

## Reproduction

Local read-only analysis: `.local/analyze_additional_alerts.py`.
Results and full activation ledger: `.local/additional-alert-analysis.json`.
The script reuses the prior review's cutoff/split, reads SQLite with `mode=ro`,
checks snapshot counts and unique IDs, and writes only its analysis JSON. Source
corrections can change a later re-extraction; this is not a frozen source export.

```sh
.venv/bin/python .local/analyze_additional_alerts.py
```

No application settings, existing alert logic, or Telegram delivery were changed
by this analysis.
