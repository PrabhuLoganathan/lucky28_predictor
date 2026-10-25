# History-based alert review

Snapshot: **24 October 2026, 13:18 UTC**. Last inspected round:
**202610241199**, number **18**. The live feed continues after this snapshot.

Reviewed 4,013 dated, completed Lucky28 results. The first 2,809 records supplied
baseline frequencies and absence thresholds; the later 1,204 records were held
out for evaluation. There were 177 separate sequences, including date boundaries
and missing/unverified links. An alert and its next result were scored only when
the needed history and successor were consecutive within the same date.

**Conclusion:** the data supports factual pattern alerts. No next-number rule
has demonstrated a predictive advantage. Two families merit a prospective
case-study trial: three consecutive New classifications and per-combination
absence thresholds. They should be labeled experimental, not reliable picks.

## Candidate definitions

| Alert | Exact condition | Meaning and proposed use |
|---|---|---|
| New ×3 | Three consecutive results were each absent from their own preceding ten completed rounds | Research whether the next result is outside the current last-ten number set. Requires 13 continuous results to establish the signal. |
| Combination absence | No SE for 8 rounds, BE for 7, BO for 9, or SO for 7 | Factual group absence plus an experimental next-round match test. Thresholds were derived from earlier history. |
| Number concentration | A number reaches three appearances within ten completed rounds | Informational repeat alert. This test does not support predicting that number again. |
| Size/parity streak | Small/Big or Even/Odd reaches six consecutive results | Informational run alert. Neither continuation nor reversal is established as a useful prediction. |
| Color, row or column absence | The group's own training threshold is reached | Factual monitoring; unequal group frequencies require separate thresholds. No next-round advantage established. |

Send/log the initial threshold crossing once. Keep the condition visible while
active, then log when it ends. A threshold change or rule edit is not a new
independent event. Merge duplicate descriptions such as Big streak and Small
absence. Alerts sharing a round are correlated observations, not extra evidence.

## Held-out next-round outcomes

An absence hit means the absent group appeared on the **immediately following
round**. A streak hit means continuation. A New/Repeated hit means the next result
had the same classification against the updated preceding-ten set. A concentration
hit means the same concentrated number appeared next. No multi-round recovery
window or later hit is substituted for a next-round miss.

| Alert family | Episodes scored | Hits / misses | Next-round match | Training-frequency baseline |
|---|---:|---:|---:|---:|
| New ×3 | 80 | 52 / 28 | 65.00% | 56.11% |
| Combination absence | 118 | 38 / 80 | 32.20% | 25.02% |
| Repeated ×3 | 30 | 13 / 17 | 43.33% | 37.15% |
| Number absence | 103 | 6 / 97 | 5.83% | 5.69% |
| Parity streak ≥6 | 11 | 5 / 6 | 45.45% | 50.30% |
| Size streak ≥6 | 21 | 8 / 13 | 38.10% | 49.97% |
| Color absence | 110 | 18 / 92 | 16.36% | 23.07% |
| Row absence | 112 | 33 / 79 | 29.46% | 34.58% |
| Column absence | 110 | 13 / 97 | 11.82% | 14.40% |
| Number concentration ≥3/10 | 69 | 2 / 67 | 2.90% | 6.57% |

The baseline is the training frequency of the exact target number set, averaged
across alerts. For New, that set often contains many numbers: **65% is not an
exact-number prediction accuracy**. This is a frequency comparison, not a
randomized comparison or causal test.

Ten families and many group thresholds were examined. Episodes can overlap and
results can be dependent; selecting the largest observed difference would create
selection bias. No multiple-testing-adjusted significance, stable advantage, or
calibrated next-result confidence has been established. Follow-up live forecasts
must be recorded before results, under fixed definitions and a predefined
evaluation period. Historical replay may also reflect later source corrections.

## Candidate absence thresholds

These are the observed 95th-percentile **completed gaps** in the training segment,
with a minimum threshold of three rounds and at least 30 completed gaps per group.
Missing history truncates some gaps, so these are exploratory calibration values,
not verified population percentiles or guarantees of rarity.

| Family | Thresholds in observed rounds |
|---|---|
| Combinations | SE 8; BE 7; BO 9; SO 7 |
| Colors | Magenta 30; Blue 17; Cyan/Teal 10; Green 7; Grey 7 |
| Rows | R1 23; R2 4; R3 5; R4 21 |
| Columns | C1 16; C2 17; C3 16; C4 14; C5 12; C6 13; C7 13 |
| Numbers | 6:38; 7:50; 8:39; 9:45; 10:34; 11:36; 12:26; 13:25; 14:24; 15:37; 16:30; 17:31; 18:29; 19:30; 20:33 |

Red had only seven completed training gaps and Orange had 28. Numbers 0–5 and
21–27 also failed the 30-gap calibration minimum. Do not label their thresholds
history-validated yet. Their factual absence counts may still be displayed.

## Snapshot observations

At round 202610241199, the current uninterrupted sequence contained 104 results:

- New classification was on a run of at least three.
- Green had been absent for eight observed rounds (candidate threshold seven).
- Number 6 had been absent for 70 observed rounds (candidate threshold 38).
- Number 11 had been absent for 40 observed rounds (candidate threshold 36).

These are timestamped observations, not current instructions or next-result picks.

## Reliability changes needed before calling alerts valid

1. **Continuity gate:** generic alerts currently filter incomplete rounds out
   before building facts. This can make a streak/window span missing IDs. New
   research alerts must require the relevant consecutive history and report
   `Insufficient history` when it cannot be established.
2. **Per-group calibration:** current generic defaults use absence 15 for every
   color and 50 for every number. Those are not equally unusual. Under the
   repository's explicitly assumed uniform-digit model, absence of 0 for 50
   rounds has probability about 95.1%, versus 2.0% for absence of 13. These model
   values are illustrations, not verified provider probabilities.
3. **Episode counting:** count only first activation, distinguish endings, and
   combine redundant descriptions. Do not count repeated notifications as new
   independent evidence.
4. **Local completeness:** a historical outage should not permanently suppress a
   group whose last verified appearance and subsequent gap are fully known.
5. **Honest labels:** `Observed pattern`, `Experimental next-round test`, and
   `Insufficient evidence` are separate states. A long gap does not imply a number
   is due, and a matched pattern does not explain the provider's generation cause.

No existing alert configuration or delivery was changed or triggered by this
review. The read-only analysis and full episode ledger are in
`.local/review_history_alerts.py` and `.local/alert-history-review.json`.
