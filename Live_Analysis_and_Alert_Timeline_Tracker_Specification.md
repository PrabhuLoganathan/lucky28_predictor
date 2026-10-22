# Live Analysis & Alert Timeline Tracker

Requirements, Architecture, and Implementation Specification

## Number Game implementation in this repository

The implementation adapts the CAR Game reference below. The following choices
apply to Lucky28; the original 50-game examples are retained as reference only.

- **150 completed games**, newest first by numeric round sequence where available
  (otherwise completion time), across dates and
  isolated by game stream. Show 25 aligned game columns per page, with newer/older
  navigation through all 150 results.
- **Live number palette:** fixed 4 × 7 board (0–27), highlights and hit counts from
  the latest ten completed rounds, newest-result badge, and independent clicked
  selection. Its right-hand panel updates appearances and observed-game gap
  statistics from the same completed history used by the timeline and Live Gaps.
  Corrections rebuild the window; unavailable history never displays as zero hits.
- Locations: `/alerts/timeline/` and the live widget on `/analysis/`. Analysis date
  filters do not restrict the global live history.
- Tracks: winning number, Big/Small, Even/Odd, SE/BE/BO/SO, the existing **seven**
  color groups, four board rows, seven board columns, extremes (0–5 and 22–27),
  repeat of either previous two numbers, rolling 10-game repeat/drought, and saved
  alert events from the rule, group, category, window and legacy signal systems.
- CAR-specific Fresh Board and speed ranking do not apply to a fixed 0–27 board.
  AI fidelity is omitted until reliable pre-game predictions are persisted.
- One shared feed checks every five seconds while visible. It detects both newly
  completed games and corrections without reloading the page; errors retain the
  last successful view and show an explicit retry status.
- Track visibility/collapse persists in local storage. Disabled tracks are omitted
  from requests. A per-track reset stores a completion-time/ID watermark in the
  session, separately for each stream. Restore removes that watermark. Earlier
  slots stay aligned and display a dash; history and alert counters are untouched.
- Missing/invalid/pending rounds break continuity. Repeat windows need all their
  preceding results; `?` means insufficient continuous history. Fetch nine extra
  results so the oldest displayed 10-game window can still be classified.
- Observations: streak ≥4; absence ≥6 for two-state tracks or ≥12 otherwise;
  concentration ≥7 of the latest 10; alternating latest four. Computation stops
  at the first history gap, unknown state, or reset boundary. These are descriptive
  observations, separate from configured delivery rules and recorded alert events.
- Feed: `GET /api/trackers/live/?stream=lucky28&tracks=size,parity,...`.
  Reset: CSRF-protected `POST /api/trackers/<key>/reset/` with `action=reset` or
  `action=restore`. Polling is read-only and does not evaluate or send alerts.
- Source: `games/services/timeline.py`, `games/timeline_views.py`, the reusable
  `games/timeline_widget.html`, and `games/static/games/timeline.{js,css}`.
  Coverage: `games.tests.test_timeline` and `scripts/check_timeline_ui.py`.

---

## Original CAR Game reference (not the Number Game implementation contract)

# 1. System Overview & Core Concept

The **Timeline Tracker** provides an instant visual history (last 50 games, newest first) of categorical outcomes and prediction fidelity. Rather than looking only at static numbers, it allows operators and players to identify:
1. **Streaks & Dominance** (e.g., 4+ consecutive hits of a primary pattern).
2. **Absence & Droughts** (e.g., a high-tier outcome missing for 12+ games).
3. **Clustering & Chaos** (e.g., elevated density of upsets/uncommon outcomes).
4. **Oscillation / Traps** (e.g., alternating between two states).

---

# 2. Reference Predictor Specifications

## A. Repeat Predictor Global Timeline

### 1. Objective
Tracks entity/outcome turnover dynamics between games to identify whether recent winners are persisting or if the board is constantly rotating.

### 2. Classification Logic (Window: Game $K$ vs $K-1$ and $K-2$)
For each completed game $K$:
* Let $W_{K-1}$ and $W_{K-2}$ be the candidates/winner from the previous two completed games.
* Compare current game $K$ contenders and winner:

| Status Symbol | Name | Description | UI Style |
| :--- | :--- | :--- | :--- |
| **`R`** | **Repeat Winner** | The winner of game $K$ was present/won in $K-1$ or $K-2$. | Green pill (`#22c55e`), bg `rgba(34,197,94,0.2)` |
| **`N`** | **New Winner** | Returning candidates existed on the board, but a new entrant won. | Red pill (`#ef4444`), bg `rgba(239,68,68,0.2)` |
| **`F`** | **Fresh Game** | All contenders in game $K$ were completely new compared to $K-1$ and $K-2$. | Blue/Cyan pill (`#38bdf8`), bg `rgba(56,189,248,0.2)` |

### 3. Active Event Detection Rules (Computed over Timeline)
* **Repeat Dominance**: 4+ consecutive `R` outcomes $\rightarrow$ *"Repeat winners have won 4+ consecutive games. Strong momentum."*
* **Repeat Drought**: 6+ consecutive games without an `R` (`N` or `F`) $\rightarrow$ *"No repeat winner in 6+ games. Repeat win overdue."*
* **Fresh Streak**: 2+ consecutive `F` games $\rightarrow$ *"Multiple consecutive fresh boards. Highly unusual rotation."*
* **Immediate Repeat Overdrive**: The exact same entity won 3 consecutive games.

---

## B. Speed Advantage Predictor Global Timeline

### 1. Objective
Tracks whether intrinsic statistical advantage (Rank 1 / Hot vs Rank 2 / Mid vs Rank 3 / Upset) is holding up, or if the server is experiencing mean reversion and volatility.

### 2. Classification Logic
For each completed game, candidates are ranked based on their baseline win rate / speed rating for that context:
* **Rank 1**: Favorite / Hot candidate
* **Rank 2**: Middle candidate
* **Rank 3**: Underdog / Longshot

| Status Symbol | Name | Description | UI Style |
| :--- | :--- | :--- | :--- |
| **`H`** | **Concordant (Rank 1)** | The favorite / top-ranked candidate won. | Green dot (`#22c55e`), bg `rgba(34,197,94,0.2)` |
| **`G`** | **Partial (Rank 2)** | The mid-tier candidate won. | Gold/Yellow dot (`#eab308`), bg `rgba(234,179,8,0.2)` |
| **`B`** | **Discordant (Rank 3)** | The underdog/upset candidate won. | Red dot (`#ef4444`), bg `rgba(239,68,68,0.2)` |

### 3. Active Event Detection (4 Strategic Families)
1. **Mean Reversion / Droughts**:
   * *The 'H' Drought*: 'H' absent in the last 5+ games $\rightarrow$ Favor Rank 1 rebound.
   * *The 'B' Bomb Setup*: 'B' absent in the last 12+ games $\rightarrow$ Upset overdue.
   * *The 'G' Squeeze*: 'G' absent in the last 8+ games $\rightarrow$ Mid overdue.
2. **Momentum & Streaks**:
   * *The 'B' Train (Chaos Mode)*: Back-to-back Rank 3 hits (`['B', 'B']`) $\rightarrow$ Server heavily penalizing favorites.
   * *The 'H' Dominance*: 4+ consecutive Rank 1 hits $\rightarrow$ Safe trend riding.
3. **Density / Clusters**:
   * *High 'B' Density*: $\ge 3$ Rank 3 hits in the last 10 games $\rightarrow$ High volatility / jackpot conditions.
   * *Anti-G Cluster*: $\le 1$ 'G' in the last 10 games $\rightarrow$ Binary split between safest and riskiest.
4. **Pattern & Oscillations**:
   * *The Ping-Pong Trap*: Alternating sequence `[H, G, H, G]` or `[G, H, G, H]` (last 4 games).
   * *Double 'G' Warning*: `['G', 'G']` in the last 2 games $\rightarrow$ Signals transitional shift toward an upset (`B`).
   * *The 'B' Breaker*: A streak of 5+ `H` hits was immediately broken by a `B`.

---

# 3. Adapting to the Number Game (Live Analysis Page)

In a Number Game (e.g., Lucky 28 with numbers $0 \dots 27$, sums, or lotto draws), you have diverse alert sectors. Here is how each alert category maps to a Timeline Tracker track:

| Number Game Category | Timeline Track Name | Possible States / Symbols | Colors |
| :--- | :--- | :--- | :--- |
| **Size** | Size Dominance & Reversion | **`B`** (Big: $14-27$), **`S`** (Small: $0-13$) | `B` = Green, `S` = Blue |
| **Parity** | Parity Alternation | **`E`** (Even), **`O`** (Odd) | `E` = Purple, `O` = Orange |
| **Combo** | 4-Quadrant Combo Track | **`SO`**, **`SE`**, **`BO`**, **`BE`** | SO=Blue, SE=Cyan, BO=Green, BE=Emerald |
| **Color Wave** | Color Wheel Track | **`R`** (Red), **`G`** (Green), **`B`** (Blue) | Red, Green, Blue |
| **AI Fidelity** | AI Model Accuracy | **`C`** (Correct), **`W`** (Wrong) | `C` = Green, `W` = Red |
| **Extreme Numbers** | Edge / Jackpot Alerts | **`J`** (Extremes $0-5, 22-27$), **`M`** (Middle $6-21$) | `J` = Gold, `M` = Slate |

---

# 4. Architecture & Technical Design

```
+-------------------------------------------------------------+
|                     Live Analysis Page                      |
|                                                             |
|  [ Enable / Disable Tracker Settings ]  [ Global Refresh ]  |
+-------------------------------------------------------------+
                              |
    +-------------------------+-------------------------+
    |                                                   |
+---v---------------------------+   +-------------------v-------------------+
|  Tracker Widget: Repeat       |   |  Tracker Widget: Speed / Number Alert |
|  - Active Event Banner        |   |  - Active Event Banner                |
|  - [Reset] [Collapse/Expand]  |   |  - [Reset] [Collapse/Expand]          |
|  - Horizontal 50-Dot Track    |   |  - Horizontal 50-Dot Track            |
|  - Legend (R / N / F)         |   |  - Legend (H / G / B or S / B)        |
+-------------------------------+   +---------------------------------------+
```

### 1. Data Schema (Standard Timeline Contract)
Every tracker returns a clean JSON response containing an array of up to 50 items (newest first):

```json
{
  "tracker_key": "speed_advantage",
  "display_name": "Speed Advantage Predictor",
  "latest_game_id": "202610211262",
  "active_events": [
    {
      "id": "h_drought",
      "title": "The 'H' Drought",
      "desc": "Rank 1 hasn't won in the last 5+ races. Expected to break soon.",
      "level": "warning",
      "color": "rgba(249, 115, 22, 0.2)",
      "border": "rgba(249, 115, 22, 0.4)",
      "text": "#fdba74"
    }
  ],
  "timeline": [
    {"status": "concordant", "letter": "H", "game_no": "202610211262", "meta": "Car 1"},
    {"status": "partial",    "letter": "G", "game_no": "202610211261", "meta": "Car 2"},
    {"status": "discordant", "letter": "B", "game_no": "202610211260", "meta": "Car 3"}
  ],
  "legend": [
    {"label": "Concordant (Rank 1 / H)", "color": "#22c55e"},
    {"label": "Partial (Rank 2 / G)",    "color": "#eab308"},
    {"label": "Discordant (Rank 3 / B)", "color": "#ef4444"}
  ]
}
```

### 2. Enable / Disable & Session Reset Mechanism
* **Enable / Disable per Alert**:
  * Store enabled tracks either in **User Session** (`request.session['enabled_trackers'] = ['speed', 'repeat', 'size']`) or **LocalStorage** in the browser.
  * Disabled tracks do not render in the DOM and are omitted from polling requests to minimize server compute.
* **Per-Tracker Reset**:
  * When the user clicks **Reset**, send a `POST` request to `/api/trackers/<tracker_key>/reset/`.
  * Store the current latest `game_id` as the cutoff in the session: `request.session[f'{tracker_key}_reset_game_id'] = latest_game_id`.
  * On subsequent queries, filter: `races.filter(game_id__gt=cutoff)`. The user sees a fresh blank slate from that moment onward without affecting other users or historical database records.

---

# 5. Ready-to-Copy Implementation Code

### A. Backend Python Engine (`timeline_service.py`)

```python
"""
Modular Timeline and Alert Evaluator for Live Analysis Page.
"""

def build_speed_advantage_timeline(recent_games, cutoff_game_id=None):
    """
    recent_games: list of games ordered by -game_id (newest first).
    cutoff_game_id: session reset point (only include games > cutoff).
    """
    if cutoff_game_id:
        recent_games = [g for g in recent_games if g.game_id > int(cutoff_game_id)]

    timeline = []
    for game in recent_games[:50]:
        # Evaluate winner against rank: 1 -> H, 2 -> G, 3 -> B
        win_rank = game.winner_rank  # Replace with your project's rank lookup
        if win_rank == 1:
            status, letter = "concordant", "H"
        elif win_rank == 2:
            status, letter = "partial", "G"
        else:
            status, letter = "discordant", "B"

        timeline.append({
            "game_id": str(game.game_id),
            "status": status,
            "letter": letter
        })

    # Pattern / Event Detection
    letters = [item["letter"] for item in timeline]
    events = []

    # 1. Droughts
    if len(letters) >= 5 and 'H' not in letters[:5]:
        events.append({
            "title": "The 'H' Drought",
            "desc": "Rank 1 (Hot) hasn't hit in 5+ games. Rebound expected.",
            "color": "rgba(249, 115, 22, 0.2)",
            "border": "rgba(249, 115, 22, 0.4)",
            "text": "#fdba74"
        })
    if len(letters) >= 12 and 'B' not in letters[:12]:
        events.append({
            "title": "The 'B' Bomb Setup",
            "desc": "Upset (Rank 3) absent for 12+ games. High alert for an upset.",
            "color": "rgba(239, 68, 68, 0.2)",
            "border": "rgba(239, 68, 68, 0.4)",
            "text": "#fca5a5"
        })

    # 2. Streaks
    if len(letters) >= 4 and letters[:4] == ['H', 'H', 'H', 'H']:
        events.append({
            "title": "The 'H' Dominance",
            "desc": "Favorites hit 4 times in a row. Ride the safe trend.",
            "color": "rgba(34, 197, 94, 0.2)",
            "border": "rgba(34, 197, 94, 0.4)",
            "text": "#86efac"
        })
    if len(letters) >= 2 and letters[:2] == ['B', 'B']:
        events.append({
            "title": "The 'B' Train (Chaos Mode)",
            "desc": "Back-to-back upsets. Server is in high volatility mode.",
            "color": "rgba(220, 38, 38, 0.3)",
            "border": "rgba(220, 38, 38, 0.6)",
            "text": "#fecaca"
        })

    return {"timeline": timeline, "events": events}


def build_repeat_timeline(recent_games, cutoff_game_id=None):
    """
    Repeat Winner vs New Winner vs Fresh Game Timeline.
    """
    if cutoff_game_id:
        recent_games = [g for g in recent_games if g.game_id > int(cutoff_game_id)]

    timeline = []
    # Needs at least 3 games to compare K against K-1 and K-2
    for i in range(min(50, max(0, len(recent_games) - 2))):
        game_k = recent_games[i]
        prev_1 = recent_games[i + 1]
        prev_2 = recent_games[i + 2]

        prev_candidates = set(prev_1.candidate_ids + prev_2.candidate_ids)
        current_candidates = set(game_k.candidate_ids)

        is_all_new = current_candidates.isdisjoint(prev_candidates)
        winner_was_repeat = game_k.winner_id in prev_candidates

        if is_all_new:
            status, letter = "fresh", "F"
        elif winner_was_repeat:
            status, letter = "green", "R"
        else:
            status, letter = "red", "N"

        timeline.append({
            "game_id": str(game_k.game_id),
            "status": status,
            "letter": letter
        })

    # Events
    statuses = [t["status"] for t in timeline]
    events = []
    if len(statuses) >= 4 and all(s == "green" for s in statuses[:4]):
        events.append({
            "title": "Repeat Dominance",
            "desc": "Repeat outcomes have won 4+ consecutive games.",
            "color": "rgba(34, 197, 94, 0.2)",
            "border": "rgba(34, 197, 94, 0.4)",
            "text": "#86efac"
        })
    if len(statuses) >= 6 and all(s != "green" for s in statuses[:6]):
        events.append({
            "title": "Repeat Drought",
            "desc": "No repeat winner in 6+ games. A repeat is overdue.",
            "color": "rgba(239, 68, 68, 0.2)",
            "border": "rgba(239, 68, 68, 0.4)",
            "text": "#fca5a5"
        })

    return {"timeline": timeline, "events": events}
```

---

### B. Django Views & Reset Endpoint (`views.py`)

```python
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET

@require_POST
def reset_tracker_stats(request, tracker_key):
    """
    Resets the timeline starting point for the current user session.
    """
    last_game = Game.objects.order_by('-game_id').first()
    request.session[f'{tracker_key}_reset_game_id'] = last_game.game_id if last_game else 0
    return JsonResponse({"success": True, "reset_at_game_id": request.session[f'{tracker_key}_reset_game_id']})

@require_GET
def live_tracker_feed(request, tracker_key):
    """
    Live API endpoint polled by the frontend.
    """
    cutoff = request.session.get(f'{tracker_key}_reset_game_id')
    recent_games = list(Game.objects.filter(winner__isnull=False).order_by('-game_id')[:60])

    if tracker_key == "speed_advantage":
        data = build_speed_advantage_timeline(recent_games, cutoff)
    elif tracker_key == "repeat_predictor":
        data = build_repeat_timeline(recent_games, cutoff)
    else:
        return JsonResponse({"error": "Unknown tracker"}, status=400)

    return JsonResponse(data)
```

---

### C. Reusable UI Template Component (`_timeline_card.html`)

```html
<!-- Reusable Timeline Component Card -->
<div class="timeline-tracker-card" id="tracker-{{ tracker.key }}" data-tracker-key="{{ tracker.key }}" style="margin-top: 16px; padding: 20px; background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; backdrop-filter: blur(10px);">
  
  <!-- Header -->
  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
    <div style="display: flex; align-items: center; gap: 10px;">
      <span style="font-size: 18px; font-weight: 700; color: #f8fafc;">{{ tracker.icon }} {{ tracker.title }}</span>
      <button onclick="resetTracker('{{ tracker.key }}')" style="background: rgba(239,68,68,0.15); color: #f87171; border: 1px solid rgba(239,68,68,0.3); padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; cursor: pointer;">
        🔄 Reset
      </button>
    </div>
    <span class="live-status-badge" style="font-size: 11px; color: #94a3b8;">Live Auto-Refresh</span>
  </div>

  <!-- Active Event Banners -->
  <div id="{{ tracker.key }}-events-container" style="display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px;"></div>

  <!-- Timeline Dots Box -->
  <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05); padding: 14px 16px; border-radius: 8px;">
    <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; margin-bottom: 8px; letter-spacing: 0.5px;">
      Global Timeline Tracker (Last 50 Games · Newest First)
    </div>

    <!-- Scrollable Dot Row -->
    <div id="{{ tracker.key }}-dots-track" style="display: flex; flex-wrap: nowrap; gap: 6px; overflow-x: auto; padding-bottom: 6px;"></div>

    <!-- Legend -->
    <div id="{{ tracker.key }}-legend" style="display: flex; gap: 16px; font-size: 11px; color: #94a3b8; margin-top: 10px; justify-content: flex-end;"></div>
  </div>
</div>
```

---

### D. Frontend Live Polling & Rendering Engine (`timeline_client.js`)

```javascript
/**
 * Universal Frontend Engine for Live Analysis Timeline Trackers
 */
class TimelineTrackerManager {
  constructor(trackerKey, apiEndpoint, styleMap, legendItems) {
    this.key = trackerKey;
    this.apiEndpoint = apiEndpoint;
    this.styleMap = styleMap; // Mapping letter -> { bg, border, text }
    this.legendItems = legendItems;
    this.pollIntervalMs = 5000;
    this.timer = null;
  }

  init() {
    this.renderLegend();
    this.fetchData();
    this.timer = setInterval(() => this.fetchData(), this.pollIntervalMs);
  }

  renderLegend() {
    const legendEl = document.getElementById(`${this.key}-legend`);
    if (!legendEl) return;
    legendEl.innerHTML = this.legendItems.map(item => `
      <div style="display: flex; align-items: center; gap: 5px;">
        <div style="width: 8px; height: 8px; border-radius: 50%; background: ${item.color};"></div>
        <span>${item.label}</span>
      </div>
    `).join('');
  }

  async fetchData() {
    try {
      const response = await fetch(this.apiEndpoint);
      if (!response.ok) return;
      const data = await response.json();
      this.renderEvents(data.events || []);
      this.renderDots(data.timeline || []);
    } catch (err) {
      console.warn(`[Tracker: ${this.key}] Poll failed`, err);
    }
  }

  renderEvents(events) {
    const container = document.getElementById(`${this.key}-events-container`);
    if (!container) return;

    if (!events.length) {
      container.innerHTML = '';
      return;
    }

    container.innerHTML = events.map(e => `
      <div style="padding: 10px 14px; background: ${e.color}; border: 1px solid ${e.border}; border-radius: 8px; display: flex; align-items: center; gap: 10px;">
        <div style="font-size: 18px;">⚠️</div>
        <div>
          <div style="font-weight: 700; color: ${e.text}; font-size: 13px; text-transform: uppercase;">${e.title}</div>
          <div style="font-size: 12px; color: #cbd5e1; margin-top: 2px;">${e.desc}</div>
        </div>
      </div>
    `).join('');
  }

  renderDots(timeline) {
    const track = document.getElementById(`${this.key}-dots-track`);
    if (!track) return;

    if (!timeline.length) {
      track.innerHTML = '<span style="font-size: 12px; color: #64748b;">No games recorded in current session.</span>';
      return;
    }

    track.innerHTML = timeline.map(item => {
      const s = this.styleMap[item.letter] || { bg: 'rgba(255,255,255,0.1)', border: '#fff' };
      return `
        <div title="Game #${item.game_id}" style="width: 24px; height: 24px; border-radius: 50%; flex-shrink: 0; display: flex; align-items: center; justify-content: center; color: white; font-size: 11px; font-weight: 700; background: ${s.bg}; border: 2px solid ${s.border};">
          ${item.letter}
        </div>
      `;
    }).join('');
  }
}

// Global Reset Function
async function resetTracker(trackerKey) {
  if (!confirm(`Reset statistics for this tracker?`)) return;
  try {
    const res = await fetch(`/api/trackers/${trackerKey}/reset/`, {
      method: 'POST',
      headers: { 'X-CSRFToken': getCookie('csrftoken') }
    });
    if (res.ok) {
      window.location.reload();
    }
  } catch (err) {
    alert("Reset failed");
  }
}
```

---

# 6. Summary Checklist for Your Number Game Integration

1. **Database / Game Query**: Ensure your queries order by `game_id DESC` and support a session cutoff filter (`game_id > reset_id`).
2. **Category Evaluator**: Map each game outcome into 1 of 2 or 3 single-letter states (e.g. `H/G/B` or `R/N/F` or `B/S` or `E/O`).
3. **Pattern Engine**: Apply the 4 event rule types (**Streaks**, **Absences/Droughts**, **Density/Clusters**, and **Oscillations**).
4. **Live Polling**: Wire the client to fetch `/api/trackers/<tracker_key>/live/` every 5 seconds to update the dot array and alert banners without full page refresh.
5. **Session Isolation**: Using Django session variables (`request.session['..._reset_game_id']`) allows each operator to reset their view independently without altering DB records.
