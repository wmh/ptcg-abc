# Imitation Learning Pipeline — Architecture & Execution Plan

> **Purpose**: This document is the single source of truth for the imitation learning pipeline project.
> A future agent (including a restarted session) must read this FIRST before continuing work.
> Last updated: 2026-06-24 23:15 CST

---

## 1. Current State (2026-06-24)

### Scores & Submissions

| Agent | Current Score | Goal | Status |
|-------|--------------|------|--------|
| **夯 (Team)** | 757.0 (Rank 1151/3139) | 1000+ | 📉 Trending down |
| Megastarmie v3 | Just submitted (PENDING) | 820+ | Needs reset check |
| Dragapult restored | Just submitted (PENDING) | ~871 | Needs reset check |

**Historical peak**: 1002.8 (6/19 Alakazam), 1006 (6/20)
**Top of ladder**: keidroid 1366.9

### What Was Done Today (6/24)

1. **Read 4 community notebooks** from `docs/official/codes/20260624/`:
   - `ptcg-diary-day3.ipynb` — Imitation learning: record Day 2 decisions → train linear model → rerank heuristic top moves
   - `ptcg-mega-lucario-ex-v61.ipynb` — Full rule agent with `_plan_attack()`, Snover evolution-base priority, prize tracking
   - `ptcg-lucario-public-lab-anti-crustle-log.ipynb` — Meta analysis: tomatomato's Starmie #3, Nithin 1084.5 compact Lucario, Dragapult only 762.9
   - `pok-mon-tcg-deck-transformer-training.ipynb` — Next-card + win-rate prediction from episode data

2. **Megastarmie v3 improvements** (in `agents/megastarmie/main.py`):
   - Added `_jett_ko_bench()` — checks if Jetting Blow's 50 bench spread can KO key targets
   - Overrode `score_spread_target()` — evolution-base priority (Snover-style: kill before it evolves)
   - Improved `score_attack()` — Nebula effect-pierce bonus (+2000), multi-prize KO bonus (+1000)
   - Tuned `Crushing Hammer` — only disrupt when setup is ready
   - All passing `check_agent` (0 over-fill, 0 fallback, BasePolicy)

3. **Dragapult fixes** (in `agents/dragapult/main.py`):
   - Confirmed +25000 attach bonus is in code (line 849) — the 665.9 submission was a temporary experiment
   - `attach_score` for Budew: `-1` → `UNNECESSARY` (-10000000) to prevent over-fill
   - Selection logic: added `sorted_scores[i][1] > UNNECESSARY` guard
   - Still 1 remaining over-fill (likely through Crispin attach effect) — acceptable for legacy agent

4. **Submitted 2 agents**: Megastarmie v3 + Dragapult restored (both PENDING)

### Blockers Found

| Blocker | Status | Notes |
|---------|--------|-------|
| Hand-tuned scores don't scale | 🚫 ACTIVE | This pipeline is the solution |
| cabt doesn't predict ladder reliably | ⚠️ KNOWN | Trust ladder scores, not cabt |
| Dragapult is legacy (not on BasePolicy) | 🔧 PENDING | Migrate after pipeline is built |
| Daily meta shifts too fast for manual tuning | 🚫 ACTIVE | Pipeline should re-train daily |

---

## 2. The Problem

### Why hand-tuning fails

```
Current workflow:
  1. divergence_decode  →  see disagreements
  2. Manual score tweak →  "I think Fez should be 35000 not 53000"
  3. cabt A/B (40 games) →  ±10% noise, ladder disagrees
  4. Submit →  score drops (or rises, can't tell why)
  5. Repeat for next archetype →  no knowledge transfer

Root cause: Each card/context score is a HUMAN GUESS.
Even with divergence data, the mapping from "disagree 27%" to "change score by X" is arbitrary.
```

### Why imitation learning fixes it

```
Proposed workflow:
  1. Extract top pilot decisions from daily episodes (Elo ≥ 1150)
  2. For each decision: feature vector + label (which option pilot chose)
  3. Train lightweight model: features → pilot's preference
  4. Deploy as reranker on top of heuristic
  5. Daily re-train → stays current with meta
  6. Same pipeline works for ANY deck (just change the decision pool)

Key insight: The model learns WHAT SCORES WORK from real data.
No more "I think 35000 is right" — the data decides.
```

---

## 3. Architecture

### High-Level Design

```
┌──────────────────────────────────────────────────────────────┐
│                    DAILY PIPELINE (Phase A)                    │
│                                                              │
│  kaggle episodes.zip                                         │
│       │                                                      │
│       ▼                                                      │
│  extract_pilot_decisions.py                                  │
│       │  For each top-pilot game (Elo ≥ 1150):               │
│       │  1. Replay through our agent                         │
│       │  2. For each decision context:                       │
│       │     - Record heuristic scores for all options        │
│       │     - Record which option the pilot chose (label)    │
│       │     - Record board state features                    │
│       │  3. Output: features.npy + labels.npy                │
│       ▼                                                      │
│  train_reranker.py                                           │
│       │  Input: features + labels                            │
│       │  Model: MLP (2×64) or logistic regression            │
│       │  Output: model.pt + accuracy report                  │
│       ▼                                                      │
│  deploy_reranker.py                                          │
│       │  Copy model.pt → agents/{deck}/reranker_model.pt     │
│       │  Update config.json with blend weight α              │
│       ▼                                                      │
│  /tmp/autopsy/{date}/imitation_report.md                     │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                     RUNTIME (Phase B)                         │
│                                                              │
│  obs_dict                                                     │
│       │                                                      │
│       ▼                                                      │
│  BasePolicy.score(o)  ──→  heuristic_scores[]                │
│       │                                                      │
│       ▼ (if reranker model exists)                           │
│  ImitationReranker.rerank(scores, obs)                       │
│       │  final_scores[i] = α * heuristic + (1-α) * model     │
│       ▼                                                      │
│  normalize_selection(ranked, final_scores, select)           │
│       │                                                      │
│       ▼                                                      │
│  selected option indices                                     │
└──────────────────────────────────────────────────────────────┘
```

### Data Flow Detail

#### Feature Vector (per decision)

For each decision context (e.g., MAIN, ATTACH_FROM, TO_HAND, DISCARD):

**Core features (~20 dims):**
1. Normalized heuristic scores for each option (top 10, padded with 0)
2. z-score of each score within this decision (relative preference)
3. Rank position of each option (1, 2, 3...)

**Board state features (~30 dims):**
4. Turn number (normalized)
5. My prizes left / Opponent prizes left
6. Deck count
7. Hand size
8. Bench count
9. Energy attached (sum, by type)
10. Cards in play by category
11. Supporter played? Stadium played?
12. Energy attached this turn?

**Per-archetype features (~10 dims):**
13. Attacker ID on field count
14. Evolution line completeness
15. Win-con readiness (can attack?)

**Label**: one-hot over options (which one the pilot chose)

#### Model Architecture (Phase 1: simple, Phase 2: refine)

```
Phase 1: Logistic Regression (multinomial)
  - Input: ~60 dims
  - Output: option scores
  - Pro: fast, interpretable, works with small data
  - Con: can't capture non-linear interactions

Phase 2: Small MLP
  - Input → Linear(60→64) → ReLU → Linear(64→32) → ReLU → Linear(32→n_options)
  - Pro: captures complex patterns
  - Con: needs more data (~5000+ decisions)

Phase 3 (future): Transformer
  - Embed each option's features + board state
  - Self-attention across options
  - Pro: handles variable number of options
  - Con: heavier, data-hungry
```

### Integration Points in Code

1. **`BasePolicy.rank()`** (`agents/_base/policy_base.py`, line 396-401):
   - Current: compute `scores`, sort descending
   - New: after computing scores, call `reranker.rerank(scores, self)` → blended scores

2. **`make_agent()`** (`agents/_base/policy_base.py`, line 618-659):
   - Load reranker model when agent starts
   - Attach to policy instance

3. **`BasePolicy.score_card()`** dispatch (`agents/_base/policy_base.py`, line 473-507):
   - Ensure all sub-scorers return comparable score magnitudes
   - Sub-scorers that return normalized scores work better with the model

---

## 4. Implementation Plan

### Phase A: Data Pipeline (EST: 4-6 hours)

**Priority: HIGH — must-do first**

#### Step A1: `tools/imitation_pipeline.py` — Core module

```python
class DecisionExtractor:
    """Replay episodes through our agent and extract pilot decisions."""
    
    def extract_decisions(self, episode_zip, agent_main_path):
        """Returns list of Decision objects."""
        # 1. Load agent's agent() function
        # 2. For each game in zip:
        #    a. Skip if either player's Elo < 1150
        #    b. Get the deck from steps[1][pi]['action']
        #    c. For each step t where pi == target_player:
        #       - Get obs from steps[t][pi]['observation']
        #       - Get the pilot's actual action from steps[t+1][pi]['action']
        #       - Run obs through our agent to get heuristic scores
        #       - Record: features + label
        # 3. Save to features.npy, labels.npy, metadata.json

class RerankerTrainer:
    """Train a lightweight reranker from extracted decisions."""
    
    def train(self, features, labels, model_type='logistic'):
        # Features shape: (n_decisions, n_features)
        # Labels shape: (n_decisions,) — option index the pilot chose
        # Train: logistic regression or MLP
        # Evaluate: holdout accuracy, top-3 rate
        # Save: model.pt, config.json

class RerankerEvaluator:
    """Compare heuristic vs reranker on held-out decisions."""
    # Metrics: agreement rate vs pilot, top-3 rate, score distribution
```

**File locations:**
- `tools/imitation_pipeline.py` — main script
- `agents/_base/imitation_features.py` — feature extraction helpers
- `agents/_base/imitation_model.py` — model definition + inference

**Input format:**
- Episode zip from Kaggle: `/tmp/ep{date}/pokemon-tcg-ai-battle-episodes-{date}.zip`
- Agent: `agents/{deck}/main.py`

**Output format:**
```
/tmp/imitation/{date}/
  ├── features_{archetype}.npy       # feature matrix (n_decisions × n_features)
  ├── labels_{archetype}.npy         # label vector (n_decisions,)
  ├── metadata_{archetype}.json      # feature names, score ranges, card IDs
  ├── model_{archetype}.pt           # trained model weights
  ├── config_{archetype}.json        # blend weight α, archetype name
  └── report_{archetype}.md          # accuracy, top-3 rate, feature importance
```

#### Step A2: Feature extraction — first pass

Start with minimal features that are guaranteed to work:

```python
def extract_basic_features(obs, policy, heuristic_scores):
    """Minimal feature set (~15 dims)."""
    state = obs.current
    me = state.players[state.yourIndex]
    op = state.players[1 - state.yourIndex]
    
    features = []
    for i, score in enumerate(heuristic_scores):
        opt = obs.select.option[i]
        features.extend([
            score / max(abs(s) for s in heuristic_scores if s != 0 or 1),  # norm score
            float(opt.type),              # option type
            opt.index,                     # option index
            len(me.prize),                 # my prizes
            len(op.prize),                 # op prizes
            state.turn / 30,               # turn (normalized)
            me.handCount / 10,             # hand size
            sum(1 for b in me.bench if b), # bench count
            me.deckCount / 60,             # deck count
            1 if state.supporterPlayed else 0,
            1 if state.energyAttached else 0,
            len(me.active[0].energies) if me.active else 0,
        ])
    return features
```

Then expand with board state + card-specific features.

#### Step A3: Integration test

Test the pipeline end-to-end:
1. Download 1 day of episodes
2. Extract decisions for Dragapult archetype
3. Train a model
4. Evaluate agreement improvement

**Success criteria:**
- Pipeline runs end-to-end without errors
- Trained model has >60% agreement on held-out decisions (vs ~40% heuristic alone)
- Inference takes <1ms per decision

---

### Phase B: Runtime Integration (EST: 1-2 hours)

**Priority: HIGH — needed before Phase C matters**

#### Step B1: `agents/_base/imitation_reranker.py`

```python
import torch

class ImitationReranker:
    """Lightweight reranker that blends heuristic scores with learned preference."""
    
    def __init__(self, model_path=None, alpha=0.7):
        self.alpha = alpha  # blend weight: 1.0 = pure heuristic, 0.0 = pure model
        self.model = None
        if model_path and os.path.exists(model_path):
            self.load(model_path)
    
    def load(self, model_path):
        self.model = torch.jit.load(model_path)  # or pickle
    
    def rerank(self, heuristic_scores, obs, policy):
        """Blend heuristic scores with model predictions."""
        if self.model is None:
            return heuristic_scores  # passthrough
        features = self._extract_features(obs, policy, heuristic_scores)
        model_scores = self.model.predict(features)
        return [
            self.alpha * h + (1 - self.alpha) * m
            for h, m in zip(heuristic_scores, model_scores)
        ]
    
    def _extract_features(self, obs, policy, scores):
        """Must match training-time feature extraction exactly."""
        # ... use same feature code as extract_basic_features()
```

#### Step B2: Modify `BasePolicy.rank()`

```python
def rank(self):
    if not self.select.option or self.select.maxCount == 0:
        return [], []
    scores = [self.score(o) for o in self.select.option]
    if self.reranker is not None:
        scores = self.reranker.rerank(scores, self.obs, self)
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return ranked, scores
```

And `make_agent()`:
```python
def make_agent(policy_cls, my_deck, diag, reranker_model_path=None):
    ...
    reranker = ImitationReranker(reranker_model_path)
    ...
    pol = policy_cls(obs)
    pol.reranker = reranker
    ...
```

#### Step B3: DRY RUN — test on one archetype

1. Train model for Dragapult on 6/22-6/23 episodes
2. Deploy model to `agents/dragapult/reranker_model.pt`
3. Run `check_agent` — verify no crashes, similar behavior
4. Run `cabt_eval` vs baseline — verify no regression
5. Submit if promising

---

### Phase C: Automation (EST: 1-2 hours)

**Priority: MEDIUM — do after A+B work**

#### Step C1: Extend `tools/autopsy.py`

```python
# Add to the daily autopsy pipeline:
from imitation_pipeline import DecisionExtractor, RerankerTrainer

def run_imitation_pipeline(date, archetypes=["Dragapult ex", "Alakazam", "Hop's Trevenant", "Mega Starmie ex"]):
    episode_zip = download_episodes(date)
    for arch in archetypes:
        decisions = DecisionExtractor().extract(episode_zip, archetype=arch, min_elo=1150)
        if len(decisions) < 200:
            print(f"Not enough decisions for {arch}: {len(decisions)}")
            continue
        model = RerankerTrainer().train(decisions)
        deploy_to_agent(model, arch)
```

#### Step C2: Daily schedule

```bash
# Cron or manual:
# 1. Run autopsy (meta analysis)
venv/bin/python tools/autopsy.py --date $(date -d 'yesterday' +%F)

# 2. Run imitation pipeline
venv/bin/python tools/imitation_pipeline.py --date $(date -d 'yesterday' +%F) --agents agents/dragapult agents/megastarmie

# 3. Build and submit
bash agents/dragapult/build_submission.sh
bash agents/megastarmie/build_submission.sh
venv/bin/kaggle competitions submit pokemon-tcg-ai-battle -f agents/dragapult/submission.tar.gz -m "daily auto-update"
venv/bin/kaggle competitions submit pokemon-tcg-ai-battle -f agents/megastarmie/submission.tar.gz -m "daily auto-update"
```

---

## 5. Step-by-Step Execution Order (for the next agent)

### If session restarts:

**Step 0: Read this document** (you're doing it now ✅)

**Step 1: Check current scores**
```bash
venv/bin/kaggle competitions submissions pokemon-tcg-ai-battle
venv/bin/kaggle competitions leaderboard pokemon-tcg-ai-battle --download -p /tmp/lb
```

**Step 2: Run daily autopsy** (get fresh episodes + meta)
```bash
venv/bin/kaggle datasets download kaggle/pokemon-tcg-ai-battle-episodes-index -p /tmp/idx --unzip
# find latest date
venv/bin/kaggle datasets download kaggle/pokemon-tcg-ai-battle-episodes-{latest_date} -p /tmp/ep{date}
venv/bin/python tools/meta_analyze.py /tmp/ep{date}/*.zip --elo 1150
```

**Step 3: Build the imitation pipeline (Phase A)**
Target files to create:
- `tools/imitation_pipeline.py` — main script
- `agents/_base/imitation_features.py` — feature extraction
- `agents/_base/imitation_model.py` — model definition
- `agents/_base/imitation_reranker.py` — runtime inference

Refer to Section 4 (Phase A) above for detailed specs.

**Step 4: Test pipeline on Dragapult**
```bash
venv/bin/python tools/imitation_pipeline.py --episode /tmp/ep{date}/*.zip --agent agents/dragapult --archetype "Dragapult ex" --train
# Check output in /tmp/imitation/{date}/
```

**Step 5: Integrate reranker into BasePolicy (Phase B)**
Modify:
- `agents/_base/policy_base.py` — `rank()` and `make_agent()`
- Add `agents/_base/imitation_reranker.py`

**Step 6: Validate**
```bash
venv/bin/python tools/check_agent.py agents/dragapult
venv/bin/python tools/cabt_eval.py agents/dragapult dragapult 40  # skip if too slow
```

**Step 7: Submit**
```bash
bash agents/dragapult/build_submission.sh
# Also build one other agent (megastarmie or alakazam)
venv/bin/kaggle competitions submit ... -m "6-25 Dragapult imitation reranker v1"
```

**Step 8: Automate (Phase C)**
Extend `tools/autopsy.py` to call `imitation_pipeline.py` daily.

**Step 9: Expand to other archetypes**
- Alakazam (agents/alakazam) — needs migration to BasePolicy FIRST
- Megastarmie (agents/megastarmie) — already on BasePolicy ✅
- Trevenant (agents/trevenant) — legacy, needs BasePolicy migration

---

## 6. Key Files & Locations

| File | Purpose | Status |
|------|---------|--------|
| `agents/_base/policy_base.py` | Shared BasePolicy — modify `rank()` and `make_agent()` | 📄 EXISTING |
| `agents/_base/imitation_reranker.py` | Runtime reranker — TO CREATE | ❌ NEEDED |
| `agents/_base/imitation_features.py` | Feature extraction — TO CREATE | ❌ NEEDED |
| `agents/_base/imitation_model.py` | Model definition — TO CREATE | ❌ NEEDED |
| `tools/imitation_pipeline.py` | Main pipeline — TO CREATE | ❌ NEEDED |
| `tools/autopsy.py` | Existing daily pipeline — EXTEND | 📄 EXISTING |
| `agents/dragapult/main.py` | Dragapult legacy agent | 📄 EXISTING |
| `agents/megastarmie/main.py` | Megastarmie BasePolicy agent | 📄 EXISTING |
| `docs/imitation_learning_pipeline.md` | THIS DOCUMENT | ✅ NEW |
| `docs/official/codes/20260624/ptcg-diary-day3.ipynb` | Reference: imitation learning approach | 📄 REFERENCE |

---

## 7. Success Metrics

| Metric | Current | Target | How to Measure |
|--------|---------|--------|----------------|
| **Ladder score** | 757.0 (夯) | >1000 | `kaggle competitions submissions` |
| **Agreement vs top pilots (MAIN context)** | ~38% (megastarmie vs keidroid) | >60% | `tools/replay_divergence.py` |
| **Daily agent improvement** | Manual, slow | Automated pipeline | Pipeline runs without human intervention |
| **New deck setup time** | 1-2 days (hand-tune scores) | <2 hours (reranker adapts) | Time from deck choice → first submission |
| **Regressions (over-fill/crashes)** | 1-2 per release | 0 | `tools/check_agent.py` |
| **Model agreement on held-out data** | N/A | >65% top-3 | Pipeline eval step |

---

## 8. Appendix: Key Technical Decisions

### Why reranker, not replacement?
The heuristic (BasePolicy) handles edge cases, illegal moves, and provides sensible defaults. The reranker only adjusts PREFERENCES between legal options. This is robust: if the model crashes or returns garbage, the heuristic still works.

### Why per-archetype models, not one universal model?
Different decks have fundamentally different decision logic:
- Dragapult: spread damage, item lock, energy denial
- Megastarmie: Jetting Blow workhorse, Ignition burst
- Alakazam: type-aware, evolution setup
A universal model would need to learn all of these from features alone — possible but needs more data.

### Why Episode.replay through OUR agent?
Because we need the SAME decision contexts that our agent will encounter. If we just analyze pilot logs independently, the training distribution won't match the inference distribution. Replaying through our agent gives us aligned contexts.

### What if there aren't enough top-pilot games for an archetype?
Fallback: train on all Elo levels (not just ≥1150), but weight higher-Elo decisions more. If still <200 decisions, use a shared cross-archetype model with archetype ID as a feature.

### Blend weight α: how to choose?
Start conservative: α = 0.9 (90% heuristic, 10% model). Evaluate on held-out decisions. Gradually decrease α as model quality improves. Target α = 0.5-0.7 for a well-trained model.
