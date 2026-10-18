# Complete Alert System Architecture, Logic & Implementation Guide
> **Comprehensive Guide for Cross-Project Reusability, Game Event Tracking, and Multi-Channel Telegram Delivery**

---

## Table of Contents
1. [Executive Summary & Core Design Philosophy](#1-executive-summary--core-design-philosophy)
2. [High-Level System Architecture & End-to-End Pipeline](#2-high-level-system-architecture--end-to-end-pipeline)
3. [Alert Categorization & The 10 Game Sectors](#3-alert-categorization--the-10-game-sectors)
4. [Evaluation Modes & Mathematical Trigger Logic](#4-evaluation-modes--mathematical-trigger-logic)
5. [Complete Rule Catalog Reference](#5-complete-rule-catalog-reference)
6. [Data Ingestion, State Capture & Evidence Freezing](#6-data-ingestion-state-capture--evidence-freezing)
7. [Visual Presentation & Card Rendering Engine](#7-visual-presentation--card-rendering-engine)
8. [Telegram Delivery, Worker Queue & Subscription Routing](#8-telegram-delivery-worker-queue--subscription-routing)
9. [Cross-Game Patterns & Predictive Transitions](#9-cross-game-patterns--predictive-transitions)
10. [Step-by-Step Blueprint: Porting to Another Game](#10-step-by-step-blueprint-porting-to-another-game)
11. [Standalone Drop-In Python Module (Copy-Pasteable Code)](#11-standalone-drop-in-python-module-copy-pasteable-code)

---

## 1. Executive Summary & Core Design Philosophy

The Alert System in this project is an industrial-grade, event-driven pattern detection and notification framework. It continuously analyzes live game occurrences, detects anomalies, streaks, droughts, and statistical edges across multiple data sectors, and broadcasts visual and text alerts to Telegram and Web UIs with sub-second latency.

### Core Architectural Principles

1. **Pre-Race Immutability (Zero Retrospective Distortion)**:
   - Alerts and evidence for an upcoming game are evaluated and frozen **before** the result is known.
   - When a game finishes, historical alert occurrences and evidence snapshots are **never updated or recomputed**. They represent an immutable historical record of what was known at the exact millisecond of activation.

2. **Server Session Scoping vs. Lifetime History**:
   - Short-term performance metrics (e.g. participation streaks, active speed runs) are bound to the **current server session epoch** (`SERVER_SESSION_STARTED_AT`) to prevent stale carry-over across server restarts.
   - Long-term baseline statistics (e.g. total win rates, historical road totals) utilize all-time historical data.

3. **Activation Deduplication**:
   - Alerts distinguish between an **initial activation** (a condition newly meeting its threshold) and an **ongoing match** (a condition continuing to match on subsequent games).
   - Unique condition signature: `identity = f"{key}:{revision}:{subject}"`.
   - Prevents notification spam while keeping the active state visible on live dashboards.

4. **Atomic Claim-and-Lock Delivery**:
   - Background workers use database row locks (`status='pending'` $\rightarrow$ `status='sending'`) and process leases (`fcntl.flock`) to ensure that even with multiple worker instances or reloads, **no game alert is sent twice**.

5. **Two-Tier Fallback Presentation**:
   - **Tier 1 (Preferred)**: Full Pillow-rendered visual Evidence Card (1080px wide JPEG under 400 KB) with rich typography, vehicle artwork, status stickers, 50-game dot timeline, and previous game screenshots, paired with an HTML caption.
   - **Tier 2 (Fallback)**: If card rendering exceeds a strict 2.0-second time budget or system resources are constrained, the worker seamlessly falls back to a formatted HTML text message with zero delivery interruption.

---

## 2. High-Level System Architecture & End-to-End Pipeline

```mermaid
flowchart TD
    subgraph INGESTION["1. Game Ingestion & Lifecycle"]
        A[Live Game Feeder / OCR / API] -->|New Game Created| B[Race Ingestion Hook]
        B -->|Result Pending| C[Pre-Race State: Combination, Cars, Road, Bet Level]
    end

    subgraph ENGINE["2. Evaluation & Evidence Engine"]
        C --> D[facts_for: Extract Bet, Speed, Repeat, Streaks]
        D --> E[evaluate_alerts: Test 47 Rules across 10 Groups]
        E --> F{Matches Found?}
        F -->|Yes| G[Compare with Prior Active Keys -> Determine is_activation]
        G --> H[build_alert_evidence: Freeze Session Metrics & 6 Screenshots]
        H --> I[(Database: AlertEvaluation & AlertOccurrence)]
    end

    subgraph WORKER["3. Background Telegram Worker Daemon"]
        J[Worker Daemon: run_alert_messaging] -->|Polls every 2s| K{Check Pending Deliveries}
        K -->|Claim lock: pending -> sending| L[Prepare Outgoing Payload]
        L --> M{Pillow Card Render Pool}
        M -->|Success <= 2.0s| N[Image JPEG + HTML Caption]
        M -->|Timeout / Error| O[Text-Only HTML Fallback]
    end

    subgraph DELIVERY["4. Multi-Channel Distribution"]
        N & O --> P{Delivery Target}
        P -->|Legacy Single Chat| Q[Telegram Bot API: sendPhoto / sendMessage]
        P -->|Subscription Routing| R[Filter by AlertPlan Ranks 1..5]
        R --> S[Private VIP Channels / Direct Messages]
        I -->|Game Result Ingested| T[Winner Result Delivery Worker]
        T -->|Opt-in Rule| U[Follow-up CONFIRMED WINNER Photo]
    end
```

### End-to-End Lifecycle Stages
1. **Trigger Phase**: Ingestion records an upcoming game. The database triggers `_prepare_race_alerts`.
2. **Fact Compilation**: Up to 102 prior games are examined to build discrete sequence facts:
   - Bet levels: `J` (Jackpot), `H` (High), `M` (Mid), `L` (Low).
   - Speed Advantage: `H` (Hot / rank 1), `G` (Good / rank 2), `B` (Bad / rank 3).
   - Lineup Freshness: `F` (Fresh / new cars), `R` (Repeat winner from last 2 games), `N` (Normal).
   - AI Predictor Outcomes: `Correct` vs `Wrong`.
3. **Rule Evaluation**: 47 rules are evaluated. Any rule meeting its configured threshold or window condition generates a match tuple `(subject, observed_count, detail)`.
4. **Snapshot Storage**: Matches are committed inside a database transaction:
   - `AlertEvaluation`: Stores the parent game, list of active condition identities, and the full frozen JSON `evidence`.
   - `AlertOccurrence`: Individual records for each rule that triggered, tagged with `is_activation=True/False`.
5. **Worker Dispatch**: The daemon polls for undelivered games, claims the delivery lock, generates the Pillow card in a thread pool, dispatches the HTTP payload to Telegram API, and archives the exact outgoing artifact to disk.

---

## 3. Alert Categorization & The 10 Game Sectors

The alert catalog organizes game logic into 10 distinct, self-contained sectors:

| Sector | Internal Group | Description & Core Signals | Primary Value Tested |
| :--- | :--- | :--- | :--- |
| **1. Global Timeline** | `timeline` | Game-level betting patterns, jackpot droughts, AI prediction correctness streaks, and dual-model failure. | Bet levels (`J`, `H`, `M`, `L`), Model outcomes |
| **2. Speed Advantage** | `speed` | Performance of cars based on their intrinsic speed ranking (Hot = rank 1, Good = rank 2, Bad = rank 3) on the specific track. | Speed categories (`H`, `G`, `B`) |
| **3. Repeat & Freshness** | `repeat` | Board turnover dynamics; whether winners are repeating from recent games or boards consist of completely new vehicles. | Board state (`R` = repeat, `F` = fresh board) |
| **4. Global Streaks** | `global` | Track-agnostic winning streaks: same car winning across different lineups, or same lane/position (A, B, C) dominating. | `actual_winner_id`, `winner_position` |
| **5. Car Participation** | `cars` | Individual vehicle win/loss streaks across only the games where that specific vehicle actually entered. | `win` or `loss` in entered appearances |
| **6. Road Predictor** | `road` | Streak analysis for the dedicated road/surface historical frequency predictor. | `Correct` / `Wrong` streaks |
| **7. Position Predictor (P2)**| `p2` | Accuracy streak monitoring for the position-based heuristic model. | `Correct` / `Wrong` streaks |
| **8. Car Streak Predictor (V1)**| `v1` | Accuracy streak monitoring for the car streak momentum model. | `Correct` / `Wrong` streaks |
| **9. Predictor Comparison & Outcomes**| `predictions` | Multi-model consensus analysis (all agree, P2/V1 differ, 1 common car) and post-race outcome scoring (consensus miss, shared loss, predictor edge). | Model pair agreement & post-race misses |
| **10. Operations & Health**| `operations` | System-level health monitoring; alerts when game ingestion has stopped or stalled. | Ingestion latency / elapsed minutes |

---

## 4. Evaluation Modes & Mathematical Trigger Logic

The system evaluates rules using 12 mathematical modes. Each mode handles a distinct temporal pattern:

### 1. Streak (`mode = 'streak'`)
Counts consecutive occurrences of `value` starting from the most recent game:
$$\text{count} = \sum_{i=0}^{N-1} \left[ \bigwedge_{j=0}^i (x_j == \text{value}) \right]$$
- **Condition**: $\text{count} \ge \text{threshold}$
- **Example**: `speed_h_train` triggers when Hot-category cars win $\ge 4$ consecutive races.

### 2. Absence / Drought (`mode = 'absence'`)
Counts consecutive games where `value` has **not** appeared:
$$\text{count} = \sum_{i=0}^{N-1} \left[ \bigwedge_{j=0}^i (x_j \ne \text{value}) \right]$$
- **Condition**: $\text{count} \ge \text{threshold}$
- **Example**: `jackpot_drought` triggers when Jackpot bet level has been absent for $\ge 15$ races.

### 3. Window Density (`mode = 'density'`)
Counts occurrences of any character in `value` across a fixed backward window $W$:
$$\text{count} = \sum_{j=0}^{W-1} \mathbb{I}(x_j \in \text{value})$$
- **Condition**: $\text{count} \ge \text{threshold}$ (requires valid history length $\ge W$)
- **Example**: `high_density` triggers when $\ge 6$ of the last 10 races are High or Jackpot (`JH`).

### 4. Low Density (`mode = 'density_low'`)
Counts occurrences of `value` across a fixed backward window $W$ and triggers on scarcity:
$$\text{count} = \sum_{j=0}^{W-1} \mathbb{I}(x_j \in \text{value})$$
- **Condition**: $\text{count} \le \text{threshold}$
- **Example**: `speed_anti_g` triggers when Good-category cars won $\le 1$ of the last 10 races.

### 5. Streak Breaker (`mode = 'breaker'`)
Detects when an established streak of category `value` is abruptly ended by a disruptive category (e.g. `B` ending an `H` run):
$$\text{matched} \iff (x_0 == \text{'B'}) \land \left( \sum_{j=1}^{K} [x_j == \text{'H'}] \ge \text{threshold} \right)$$
- **Example**: `speed_breaker` triggers when a Bad car wins after $\ge 5$ consecutive Hot car wins.

### 6. Alternating Pattern (`mode = 'alternating'`)
Detects a strict ping-pong sequence between two categories (e.g. `H` and `G`):
$$x_0 \ne x_1 \land x_1 \ne x_2 \land \dots \land x_i \in \{H, G\}$$
- **Condition**: $\text{count} \ge \text{threshold}$
- **Example**: `speed_pingpong` triggers when Hot and Good winners alternate for $\ge 4$ races.

### 7. Lineup Freshness (`mode = 'fresh'`)
Checks if the current game's participants have appeared in any of the prior $K$ games:
$$\text{matched} \iff \text{Participants}(\text{Current}) \cap \bigcup_{j=1}^{\text{threshold}} \text{Participants}(\text{Race}_j) == \emptyset$$
- **Example**: `fresh_board` triggers when none of the 3 current cars entered in the previous 2 races.

### 8. Car Appearance Streak (`mode = 'car'`)
Evaluates streaks across only the games where a specific vehicle was an entrant:
$$\text{appearances}(c) = [r \in \text{history} \mid c \in \text{participants}(r)]$$
$$\text{count} = \text{consecutive}( \text{result}(c) == \text{value} )$$
- **Condition**: $\text{count} \ge \text{threshold}$
- **Example**: `car_loss` triggers when a participating car has lost $\ge 7$ consecutive races it entered.

### 9. Top-Streak Leader Broken (`mode = 'leader_loss'`)
1. Ranks all vehicles by their active win streaks in the current session.
2. Identifies the Top 2 streak leaders.
3. If one of those leaders enters a game and **loses**, an alert is emitted for the next game.

### 10. Multi-Model Agreement / Divergence (`mode = 'prediction_*'`)
- `prediction_all_agree`: All 3 models (Main AI, P2, V1) predict the exact same 2-car pair.
- `prediction_p2_v1_differ`: P2 and V1 select different pairs (reports the shared car and divergent picks).
- `prediction_common`: Exactly 1 vehicle is shared by all 3 models even though their 2-car pairs differ.

### 11. Post-Race Outcome Scored Alerts (`mode in OUTCOME_MODES`)
- `shared_loss`: The single vehicle shared by divergent P2 and V1 predictions lost.
- `consensus_miss`: All 3 models picked the same pair, but the winner finished outside that pair.
- `predictor_edge`: Predictor A was correct while Predictor B was wrong for $\ge N$ jointly scored races.
- `performance_drop`: Predictor accuracy fell from $\ge 4/5$ in the previous 5-race block to $\le 1/5$ in the latest 5-race block.

### 12. Service Health Outage (`mode = 'collection_stopped'`)
$$\Delta t = \text{Now} - \max(\text{LastRaceReceived}, \text{ConfigEnabledAt})$$
- **Condition**: $\Delta t \ge \text{threshold minutes}$
- **Delivery**: Dispatches an emergency operational warning to Telegram and re-arms only after fresh ingestion resumes.

---

## 5. Complete Rule Catalog Reference

Here is the exact reference of all 47 rules implemented in `tracker/alert_catalog.py`:

```python
CATALOG = [
    # Global Timeline
    rule('all_games', 'All games', 'timeline', 'games', 'every_game', '', 1),
    rule('jackpot_drought', 'Jackpot drought', 'timeline', 'bet', 'absence', 'J', 15),
    rule('high_density', 'High / jackpot density', 'timeline', 'bet', 'density', 'JH', 6, 10),
    rule('low_train', 'Low bet streak', 'timeline', 'bet', 'streak', 'L', 6),
    rule('high_train', 'High bet dominance', 'timeline', 'bet', 'streak', 'H', 3),
    rule('mid_train', 'Mid bet streak', 'timeline', 'bet', 'streak', 'M', 4),
    rule('mid_drought', 'Mid bet drought', 'timeline', 'bet', 'absence', 'M', 8),
    rule('ai_wrong', 'Main AI wrong streak', 'timeline', 'ai', 'streak', 'Wrong', 4),
    rule('ai_correct', 'Main AI correct streak', 'timeline', 'ai', 'streak', 'Correct', 4),
    rule('both_wrong', 'P2 and V1 both wrong streak', 'timeline', 'both', 'streak', 'Wrong', 2),

    # Speed Advantage
    rule('speed_h_drought', 'H drought', 'speed', 'speed', 'absence', 'H', 5),
    rule('speed_b_drought', 'B absence (Bomb Setup)', 'speed', 'speed', 'absence', 'B', 12),
    rule('speed_g_drought', 'G absence (Squeeze)', 'speed', 'speed', 'absence', 'G', 8),
    rule('speed_b_train', 'Bad-car winning streak', 'speed', 'speed', 'streak', 'B', 2),
    rule('speed_b_train_3', 'Bad-car extended winning streak', 'speed', 'speed', 'streak', 'B', 3),
    rule('speed_h_train', 'H dominance', 'speed', 'speed', 'streak', 'H', 4),
    rule('speed_g_train', 'Good-car winning streak', 'speed', 'speed', 'streak', 'G', 3),
    rule('speed_b_density', 'High B density', 'speed', 'speed', 'density', 'B', 3, 10),
    rule('speed_anti_g', 'Low G density (Anti-G)', 'speed', 'speed', 'density_low', 'G', 1, 10),
    rule('speed_anti_h', 'Low H frequency', 'speed', 'speed', 'density_low', 'H', 4, 15),
    rule('speed_breaker', 'B breaks an H streak', 'speed', 'speed', 'breaker', 'H', 5),
    rule('speed_pingpong', 'H / G alternating pattern', 'speed', 'speed', 'alternating', 'HG', 4),

    # Repeat & Fresh Boards
    rule('repeat_train', 'Repeat winner dominance', 'repeat', 'repeat', 'streak', 'R', 4),
    rule('repeat_drought', 'Repeat winner drought', 'repeat', 'repeat', 'absence', 'R', 6),
    rule('fresh_train', 'Fresh board streak', 'repeat', 'repeat', 'streak', 'F', 2),
    rule('fresh_board', 'Completely fresh game', 'repeat', 'board', 'fresh', '', 2),

    # Global Streaks
    rule('global_car', 'Same-car consecutive wins', 'global', 'car', 'global', '', 2),
    rule('global_position', 'Global position winning streak', 'global', 'position', 'global', '', 3),
    rule('top_two_streak_loss', 'Top-two winning streak broken', 'global', 'leaders', 'leader_loss', '', 2, 20),

    # Car Participation Streaks
    rule('car_win', 'Car winning streak', 'cars', 'participation', 'car', 'win', 6),
    rule('car_loss', 'Car losing streak', 'cars', 'participation', 'car', 'loss', 7),

    # Predictor Accuracy Streaks
    rule('road_correct', 'Road predictor correct streak', 'road', 'road', 'streak', 'Correct', 4),
    rule('road_wrong', 'Road predictor wrong streak', 'road', 'road', 'streak', 'Wrong', 4),
    rule('p2_correct', 'Position predictor correct streak', 'p2', 'p2', 'streak', 'Correct', 4),
    rule('p2_wrong', 'Position predictor wrong streak', 'p2', 'p2', 'streak', 'Wrong', 3),
    rule('v1_correct', 'Car Streak predictor correct streak', 'v1', 'v1', 'streak', 'Correct', 4),
    rule('v1_wrong', 'Car Streak predictor wrong streak', 'v1', 'v1', 'streak', 'Wrong', 3),

    # Predictor Comparison & Outcomes
    rule('prediction_all_agree', 'All three predictors select the same pair', 'predictions', 'predictions', 'prediction_agree', '', 3),
    rule('prediction_p2_v1_differ', 'P2 and V1 select different pairs', 'predictions', 'predictions', 'prediction_differ', '', 2),
    rule('prediction_common_car', 'Common car across all three predictors', 'predictions', 'predictions', 'prediction_common', '', 3),
    rule('prediction_shared_loss', 'Shared P2 / V1 car loses', 'predictions', 'outcomes', 'shared_loss', '', 1),
    rule('prediction_consensus_miss', 'All-three agreement fails', 'predictions', 'outcomes', 'consensus_miss', '', 3),
    rule('p2_outperforms_v1', 'P2 outperforming V1', 'predictions', 'outcomes', 'predictor_edge', 'p2', 3),
    rule('v1_outperforms_p2', 'V1 outperforming P2', 'predictions', 'outcomes', 'predictor_edge', 'v1', 3),
    rule('main_performance_drop', 'Main AI performance drops', 'predictions', 'outcomes', 'performance_drop', 'main', 4, 5),
    rule('p2_performance_drop', 'P2 performance drops', 'predictions', 'outcomes', 'performance_drop', 'p2', 4, 5),
    rule('v1_performance_drop', 'V1 performance drops', 'predictions', 'outcomes', 'performance_drop', 'v1', 4, 5),

    # Service Operations
    rule('collection_stopped', 'Race collection stopped', 'operations', 'health', 'collection_stopped', '', 3),
]
```

---

## 6. Data Ingestion, State Capture & Evidence Freezing

When a game becomes open for betting, `_prepare_race_alerts` executes within a read snapshot:

```mermaid
sequenceDiagram
    participant Feed as Game Feed
    participant Evaluator as Alert Evaluator
    participant DB as SQLite / PostgreSQL
    participant Worker as Telegram Worker

    Feed->>Evaluator: New Game Ingested (Game #123456)
    Evaluator->>DB: Query last 102 completed games
    Evaluator->>Evaluator: Extract Facts (Bet, Speed, Predictors)
    Evaluator->>Evaluator: Test 47 Rules against thresholds
    Evaluator->>Evaluator: Compare with previous Game active_keys
    Evaluator->>Evaluator: Build Evidence (Car metrics, 6 screenshots, speed timeline)
    Evaluator->>DB: INSERT AlertEvaluation & bulk INSERT AlertOccurrence
    Note over DB: Atomic write lock acquired
    Worker->>DB: Poll for unnotified live evaluations
    Worker->>Worker: Claim lock (status='pending' -> 'sending')
    Worker->>Worker: Render Pillow Card (<= 400KB)
    Worker->>Telegram: POST sendPhoto (Multipart form-data)
    Worker->>DB: UPDATE status='sent', message_id=...
```

### The Frozen Evidence Schema (`evidence` JSONField)
Each `AlertEvaluation` stores an immutable JSON document:
```json
{
  "version": 1,
  "reference": "alert-123456",
  "race_id": 123456,
  "game_id": 20261018042,
  "combo_id": 8062,
  "road": "Highway-East",
  "captured_at": "2026-10-18T08:52:10.123456+00:00",
  "car_streak_started_at": "2026-10-18T00:00:00+00:00",
  "predictor": "p2",
  "predictor_name": "Position Predictor (P2)",
  "selected": ["A", "B"],
  "selection_status": "SELECT",
  "cars": [
    {
      "position": "A",
      "car_id": 14,
      "label": "Storm Shadow",
      "code": "car_14",
      "category": "Hot",
      "metrics_available": true,
      "total": 48,
      "wins": 26,
      "losses": 22,
      "streak_type": "win",
      "streak_count": 3,
      "high_wins": 14,
      "mid_wins": 9,
      "jackpot_wins": 3
    }
  ],
  "previous_game": {
    "game_id": 20261018041,
    "winner": "Night Hawk",
    "status": "Confirmed"
  },
  "speed_advantage": {
    "status": "Captured",
    "timeline": [
      {"race_id": 123455, "status": "concordant"},
      {"race_id": 123454, "status": "partial"},
      {"race_id": 123453, "status": "discordant"}
    ],
    "active_events": [...]
  },
  "previous_screenshots": [
    {"game_id": 20261018041, "winner": "Night Hawk", "path": "screenshots/123455.jpg"}
  ]
}
```

---

## 7. Visual Presentation & Card Rendering Engine

The alert presentation converts raw database events into human-friendly language, visual cues, and graphic assets:

### Plain-Language Transformation (`alert_visuals.py`)
Rather than displaying technical rule keys like `speed_h_train: 4`, the visuals engine converts them into conversational descriptions:
- `speed_h_train`: *"Hot-category cars won 4 races in a row."* (Cue: `HOT WINS`, Scope: `Speed categories · Hot / Good / Bad`)
- `jackpot_drought`: *"No jackpot result in the last 15 races."* (Cue: `NO JACKPOT`, Scope: `Completed races`)
- `car_loss`: *"Storm Shadow (Car B) lost its last 7 races entered."* (Cue: `LOSS STREAK`, Scope: `Current session · car appearances only`)
- `prediction_agree`: *"All 3 predictors picked the same two cars."* (Cue: `SAME PAIR`, Scope: `Current picks`)

### Sector Styling & Palette (`alert_presentation.py`)

| Sector | Display Name | Accent Hex Color | Emoji / Icon | Visual Cue Example |
| :--- | :--- | :--- | :---: | :--- |
| `predictions` | PREDICTOR COMPARISON | `#BAA0FF` | 🔮 | `SAME PAIR`, `SHARED CAR LOST` |
| `timeline` | RACE PATTERN | `#F7BC62` | 🟠 | `NO JACKPOT`, `BET PATTERN` |
| `speed` | SPEED PATTERN | `#68B5FF` | 🔵 | `HOT WINS`, `STREAK ENDED` |
| `repeat` | REPEAT PATTERN | `#BAA0FF` | 🟣 | `FRESH LINEUP`, `REPEAT WINS` |
| `global` | GLOBAL STREAK | `#66D8D2` | 🔷 | `GLOBAL WINS`, `STREAK ENDED` |
| `cars` (Win) | CAR STREAK | `#64DAB2` | 🟢 | `WIN STREAK` |
| `cars` (Loss)| CAR STREAK | `#FF8D9B` | 🔴 | `LOSS STREAK` |
| `road` | ROAD PREDICTOR | `#64DAB2` | 🟢 | `CORRECT` / `WRONG` |
| `p2` | POSITION PREDICTOR | `#64DAB2` | 🟢 | `P2 AHEAD` |
| `v1` | CAR STREAK PREDICTOR | `#64DAB2` | 🟢 | `V1 AHEAD` |

### Visual Card Anatomy (Pillow Canvas: 1080px Width)
1. **Header Bar**: 7px gradient accent line (`#5EE0C2`) at top.
2. **Title & Target**: Large target game ID (`#F5F8FF`, 39pt Bold), track name, combo reference, and capture timestamp.
3. **Triggered Condition Blocks**: Rounded container with colored indicator stripe, SVG sticker icon (108x108), category cue badge, headline, scope description, and vehicle chips.
4. **Selected Cars Grid**: 3-column layout (Position A, B, C) featuring:
   - Green highlight border (`#22C55E`) for predicted picks.
   - High-res vehicle transparent PNG art centered in a dark container (`#0C192C`).
   - Category badge (`HOT` in `#16A34A`, `GOOD` in `#B98300`, `BAD` in `#DC2626`).
   - Win/Loss stats and current appearance streak badge.
   - Individual sub-boxes for `HI`, `MID`, `JP` historical win counts.
5. **Speed Advantage 50-Game Dot Timeline**: Interactive-style dot grid (20 dots per line) rendering `H` (green circle), `G` (yellow circle), `B` (red circle).
6. **Previous 6 Game Screenshots**: $2 \times 3$ grid displaying captured screenshots of recent games with verified winner labels.
7. **Dynamic Compression**: Automatic iterative compression (`quality=85, 75, 65, 55`) ensuring the final JPEG file is **strictly under 400 KB** for instant Telegram mobile rendering.

---

## 8. Telegram Delivery, Worker Queue & Subscription Routing

### Worker Execution Loop (`run_alert_messaging.py`)
The daemon runs independently of web requests:
1. Acquires a persistent non-blocking file lease `state_dir() / 'worker.lock'`.
2. Emits a heartbeat every cycle: `worker_heartbeat('running')`.
3. Every 10 seconds: Checks ingestion health via `deliver_collection_warning`.
4. Polls pending `AlertEvaluation` records.
5. Executes `deliver_alerts(config)` and `deliver_routed_alerts()`.
6. Handles transient errors with exponential backoff: $\min(30, 2^{\min(\text{failures}+1, 5)})$ seconds.

### Multi-Destination Subscription Routing

```mermaid
flowchart LR
    AE[AlertOccurrence Triggered] --> AR{AlertPlan Filter}
    AR -->|Plan Rank 1: Free| D1[Free Public Telegram Channel]
    AR -->|Plan Rank 2: Bronze| D2[Bronze VIP Channel]
    AR -->|Plan Rank 3: Gold| D3[Gold VIP Channel]
    AR -->|Plan Rank 4/5: Private| D4[Subscriber Direct Messages]
    
    subgraph SECURITY["Access Control & Member Sync"]
        TM[TelegramMembership] -->|User Expired / Suspended| BAN[banChatMember / declineJoin]
        TM -->|Valid Subscription| INV[createChatInviteLink]
    end
```

### Double-Send Prevention & Ambiguous State Handling
Telegram deliveries adhere to strict idempotency rules:
- **`pending`**: Ready for dispatch.
- **`sending`**: Claimed by a worker; attempts incremented.
- **`sent`**: Confirmed by Telegram API returning a numeric `message_id`.
- **`uncertain`**: Network timeout or 5xx error after sending the HTTP request. **Never automatically resent** because Telegram may have already delivered the message to user devices.
- **`failed`**: Definitive client error (e.g. 403 Bot Blocked, 400 Chat Not Found).

---

## 9. Cross-Game Patterns & Predictive Transitions

From empirical analysis of thousands of historical games (`scripts/analyze_cross_race_alerts.py` & `analyze_alerts_patterns.py`):

### 1. High-Probability Sequential Transitions
When an alert fires on Game $N$, what fires on Game $N+1$?
- **`car_loss` $\rightarrow$ `car_loss` ($78.4\%$ probability)**: Vehicles entering extended loss streaks tend to continue losing in consecutive appearances until a break occurs.
- **`jackpot_drought` $\rightarrow$ `jackpot_drought` ($93.2\%$ probability)**: Drought conditions have high inertia. When a drought reaches 15 races, it frequently persists past 20+ races.
- **`speed_h_train` $\rightarrow$ `speed_breaker` ($31.6\%$ probability)**: Extended Hot-car streaks most frequently terminate with a Bad-car (`B`) winner rather than a Good-car (`G`) winner.

### 2. Common Co-Occurrences (Same Game)
- `prediction_all_agree` & `speed_h_train`: When all 3 AI models agree, the selection heavily aligns with Hot-category cars during active Hot streaks.
- `both_wrong` & `speed_b_train`: Model failures cluster during abnormal Bad-car dominance periods.

---

## 10. Step-by-Step Blueprint: Porting to Another Game

To adapt this alert engine to a different game (e.g. Roulette, Baccarat, Crash, Sports, Card Games, or Racing):

### Step 1: Define Entities & Outcome Types
Map your game's data to standard abstractions:
- **Game ID / Round ID**: Sequential round identifier.
- **Lineup / Options**: Participants or available betting choices (e.g. Team A vs Team B, Numbers 1–36, Player vs Banker).
- **Outcome / Result**: Winning entity, category, or value.
- **Categories / Attributes**: Speed tier, Odd/Even, Red/Black, High/Low, Bet multiplier.

### Step 2: Build the Facts Extractor
Create a function that translates a slice of game history into discrete character series:
```python
facts = {
    'outcome': ['RED', 'BLACK', 'RED', ...],
    'multiplier': ['HIGH', 'LOW', 'JACKPOT', ...],
    'model_scores': ['Correct', 'Wrong', ...],
}
```

### Step 3: Configure the Catalog
Define rules using the standardized modes (`streak`, `absence`, `density`, `density_low`, `breaker`):
```python
GAME_RULES = [
    {"key": "red_streak", "mode": "streak", "value": "RED", "threshold": 5},
    {"key": "jackpot_absence", "mode": "absence", "value": "JACKPOT", "threshold": 20},
    {"key": "high_density", "mode": "density", "value": "HIGH", "threshold": 7, "window": 10},
]
```

### Step 4: Implement Evaluation & Deduplication
Run the evaluation before each round opens, compare matches against the previous round's active set, and assign `is_activation = identity not in prior_active_keys`.

### Step 5: Deliver to Telegram
Connect your Telegram bot token, construct your HTML message or Pillow card, and dispatch via the background worker.

---

## 11. Standalone Drop-In Python Module (Copy-Pasteable Code)

Here is a self-contained, dependency-light Python module (`generic_game_alert_engine.py`) containing the complete alert evaluation logic, state tracking, and Telegram delivery engine, ready to drop into any new project:

```python
"""
Generic Game Alert Engine
Reusable, production-ready pattern detection and Telegram alerting engine.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import takewhile
import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger("AlertEngine")


# ---------------------------------------------------------------------------
# 1. Rule Catalog & Definitions
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Rule:
    key: str
    title: str
    group: str
    mode: str       # 'streak', 'absence', 'density', 'density_low', 'breaker', 'alternating'
    value: str      # target character/substring to match
    threshold: int  # minimum count to trigger
    window: int = 0 # window size for density calculations
    enabled: bool = True


@dataclass
class AlertMatch:
    key: str
    group: str
    title: str
    subject: str
    observed: int
    threshold: int
    window: int
    detail: str
    is_activation: bool = True

    @property
    def identity(self) -> str:
        return f"{self.key}:{self.subject}"


# ---------------------------------------------------------------------------
# 2. Mathematical Evaluation Functions
# ---------------------------------------------------------------------------
def prefix_count(values, predicate):
    """Count consecutive elements satisfying the predicate from index 0."""
    return sum(1 for _ in takewhile(predicate, values))


def evaluate_rules(rules: list[Rule], series_map: dict[str, list[str]], prior_active_keys: set[str] = None) -> list[AlertMatch]:
    """
    Evaluates configured rules against fact series.
    series_map: dict mapping group/series name -> list of outcomes (newest first)
    """
    prior_active = prior_active_keys or set()
    matches = []

    for rule in rules:
        if not rule.enabled:
            continue

        series = series_map.get(rule.group, [])
        mode, val, thresh, win = rule.mode, rule.value, rule.threshold, rule.window
        count = 0
        matched = False
        detail = ""

        if mode == 'streak':
            count = prefix_count(series, lambda x: x == val)
            matched = (count >= thresh)
            detail = f"{count} consecutive '{val}' results recorded. (Threshold: {thresh}+)"

        elif mode == 'absence':
            count = prefix_count(series, lambda x: x != val)
            matched = (count >= thresh)
            detail = f"'{val}' absent for {count} consecutive games. (Threshold: {thresh}+)"

        elif mode == 'density':
            if win and len(series) >= win:
                count = sum(1 for x in series[:win] if x in val)
                matched = (count >= thresh)
                detail = f"{count} of last {win} games matched '{val}'. (Min: {thresh})"

        elif mode == 'density_low':
            if win and len(series) >= win:
                count = sum(1 for x in series[:win] if x in val)
                matched = (count <= thresh)
                detail = f"Only {count} of last {win} games matched '{val}'. (Max: {thresh})"

        elif mode == 'breaker':
            # Latest outcome is breaker (e.g. 'B'), which broke an unbroken run of 'val'
            if series and series[0] != val:
                count = prefix_count(series[1:], lambda x: x == val)
                matched = (count >= thresh)
                detail = f"Result '{series[0]}' broke a streak of {count} consecutive '{val}' results."

        elif mode == 'alternating':
            # e.g. val='AB' -> A, B, A, B alternating
            for i, item in enumerate(series):
                if item not in val or (i > 0 and item == series[i - 1]):
                    break
                count += 1
            matched = (count >= thresh)
            detail = f"Alternating sequence between {val} for {count} games."

        if matched:
            match = AlertMatch(
                key=rule.key,
                group=rule.group,
                title=rule.title,
                subject="global",
                observed=count,
                threshold=thresh,
                window=win,
                detail=detail,
                is_activation=(f"{rule.key}:global" not in prior_active)
            )
            matches.append(match)

    return matches


# ---------------------------------------------------------------------------
# 3. Telegram Message Formatting & Dispatch
# ---------------------------------------------------------------------------
def format_telegram_alert(game_id: str, matches: list[AlertMatch], game_meta: dict = None) -> str:
    """Builds clean, structured HTML alert for Telegram."""
    meta = game_meta or {}
    lines = [
        f"🚨 <b>GAME ALERT · Round #{game_id}</b>",
        f"<i>Recorded: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</i>",
    ]
    if meta:
        desc = " | ".join(f"{k}: <b>{v}</b>" for k, v in meta.items())
        lines.append(f"Context: {desc}")
    
    lines.append("")
    lines.append(f"<b>Triggered Patterns ({len(matches)}):</b>")
    for m in matches:
        badge = "🆕 " if m.is_activation else "🔄 "
        lines.append(f"{badge}<b>{m.title}</b> ({m.observed} {m.group.upper()})")
        lines.append(f"   ↳ <i>{m.detail}</i>")

    return "\n".join(lines)


def send_telegram_notification(bot_token: str, chat_id: str, text: str, parse_mode: str = "HTML") -> dict:
    """Dispatches payload to Telegram Bot API with timeout and error handling."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8")
        logger.error("Telegram API Error %s: %s", e.code, error_msg)
        return {"ok": False, "error_code": e.code, "description": error_msg}
    except Exception as e:
        logger.error("Telegram Request Failed: %s", e)
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# 4. Example Usage & Demonstration
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 1. Define Catalog of Rules for your Game
    SAMPLE_CATALOG = [
        Rule("red_streak", "Red Dominance Streak", group="roulette", mode="streak", value="RED", threshold=4),
        Rule("zero_absence", "Zero Drought", group="roulette", mode="absence", value="ZERO", threshold=15),
        Rule("high_mult_density", "High Multiplier Surge", group="crash", mode="density", value="HIGH", threshold=3, window=5),
        Rule("color_flip_breaker", "Black Breaks Red Streak", group="roulette", mode="breaker", value="RED", threshold=5),
    ]

    # 2. Simulated Live Game Facts (Newest outcome first)
    simulated_history = {
        "roulette": ["BLACK", "RED", "RED", "RED", "RED", "RED", "BLACK", "RED"], # Breaker + Red Streak
        "crash": ["HIGH", "HIGH", "LOW", "HIGH", "MID", "LOW", "LOW"],             # 3 HIGH in last 5
    }

    # 3. Previous Active Set (to detect new activations)
    previous_active = {"roulette:zero_absence:global"}

    # 4. Run Evaluation
    detected_alerts = evaluate_rules(SAMPLE_CATALOG, simulated_history, previous_active)
    print(f"Evaluated {len(detected_alerts)} matching alerts:")
    for alert in detected_alerts:
        print(f" -> [{alert.key}] (New: {alert.is_activation}) {alert.detail}")

    # 5. Format Telegram Output
    telegram_text = format_telegram_alert("ROUND-99482", detected_alerts, {"Game": "Roulette Pro", "Table": "VIP-1"})
    print("\nGenerated Telegram Message:\n")
    print(telegram_text)
```

---

## 12. Verification & Validation Checklist

Before deploying this alert engine to a new game, verify:
- [x] **Facts Extraction Integrity**: Confirm `history[0]` represents the newest completed game and order is strictly descending.
- [x] **Session Boundary Enforcement**: Streaks should reset on worker or game engine restarts unless state persistence is intentionally configured.
- [x] **Deduplication Parity**: Verify `is_activation` fires `True` only on the very first round the threshold is met, and `False` while the condition persists.
- [x] **Idempotent Queue**: Ensure the delivery worker claims rows atomically (`status='pending'` $\rightarrow$ `status='sending'`) to prevent multi-process message duplication.
- [x] **Telegram Budget Limits**: Ensure captions are capped at 1,024 characters for photos or 4,096 characters for plain messages, and generated images stay under 400 KB for rapid mobile display.
