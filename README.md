# Pokémon TCG AI Battle Challenge — Agents & Strategy

Rule-based agents and meta analysis for the **Pokémon TCG AI Battle Challenge**
(Kaggle × The Pokémon Company × Matsuo Lab (松尾研) × HEROZ).

The task: write `agent(obs_dict) -> list[int]` that plays the standard-format
Pokémon Trading Card Game and wins on an automated Elo ladder. This repo holds
three complete ladder agents (each its own deck + policy), the meta analysis that
drove the deck choices, and tooling to evaluate and play against them locally.

> Official competition materials (the engine, sample notebooks, card data, rules)
> are **not** included here — they are available on the Kaggle competition page.
> See [Setup](#setup).

---

## Competition at a glance

| | |
|---|---|
| **Simulation track** | `pokemon-tcg-ai-battle` — Elo ladder, auto-battles. Deadline **2026-08-16**. |
| **Strategy report track** | `…-strategy` ($240K prize pool). Deadline **2026-09-13**. |
| **Submission** | a `submission.tar.gz` of `main.py` + `deck.csv` + the engine `cg/`. 5/day; the latest 2 are scored. |
| **Agent contract** | `agent(obs_dict)` returns a list of option indices; on deck-selection it returns the 60 card IDs. Must never crash (always return a legal fallback) and must respect the per-move time limit. |

---

## Repository layout

```
agents/                 # three complete ladder agents (deck + policy)
  bellibolt/            #   Iono's Bellibolt ex — simple Lightning engine (our best ladder result)
  typhlosion/           #   Ethan's Typhlosion + Dudunsparce — Stage-2 combo
  alakazam/             #   胡地小人 / Alakazam + Dudunsparce — single-prize, current top meta
    main.py             #   the agent: AlakazamPolicy + robust scaffolding
    deck.csv            #   60 card IDs
    build_submission.sh #   packs main.py + deck.csv + cg/ into submission.tar.gz
docs/strategy/          # meta + deck strategy write-ups (Traditional Chinese)
tools/cabt_eval.py      # evaluate an agent vs meta decks in the official cabt environment
web/                    # browser sandbox: play a human vs the agent, see its scored options
research/               # early / superseded experiments (env wrapper, MCTS, RL & imitation trainers)
```

Each agent is self-contained: a single `main.py` with deck loading,
`normalize_selection`, per-`SelectContext` scoring, and a `_legal_fallback` that
guarantees it never crashes.

---

## The three agents

| Agent | Deck | Idea | Ladder Elo |
|---|---|---|---|
| **bellibolt** | Iono's Bellibolt ex | Stream Lightning with *Electric Streamer*, hit 230 with Thunderous Bolt; Kilowattrel (non-ex) answers Crustle's ex-immunity. **Simple, consistent.** | **836 (best)** |
| **typhlosion** | Ethan's Typhlosion + Dudunsparce | Buddy Blast scales with Ethan's Adventures in discard; Dudunsparce *Run Away Draw* engine; Boss's Orders gust. | 532 |
| **alakazam** | 胡地小人 (Alakazam + Dudunsparce) | All single-prize. *Powerful Hand* places **20 damage × cards in hand** — the Dudunsparce engine builds a 15–20 card hand for 300–400 damage. Current top meta. | A/B pending |

## What the meta analysis found

The deck choice was driven by replaying the daily ladder episode datasets (real
games, including top players) — see `docs/strategy/`. Headline lessons:

- **Meta shifts fast.** Crustle (immune to ex/megaEx attacks) ballooned to ~50% of
  the field, which is why non-ex attackers and counter-decks matter.
- **Deck choice dominates** agent quality on the ladder — but only up to a point…
- **…the *real ladder* is the only reliable judge.** Local simulators (both a
  ctypes harness and the official `cabt` environment) mispredicted ladder rank:
  the simple Bellibolt (Elo 836) beat the "stronger" combo decks in practice
  because a rule-based agent pilots a **simple** deck cleanly and a **complex**
  one clunkily. Optimize via real-ladder A/B testing, and keep decks simple.

---

## Setup

The official engine and assets are not redistributed here. From the Kaggle
competition page, download the starter materials and place the local engine at
`docs/official/models/cg-lib/`.

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/pip install kaggle-environments==1.30.1   # same version as the ladder
```

## Build, test, submit

```bash
# Build a submission (point CG_LIB_PATH at the engine's cg/ folder)
CG_LIB_PATH="$(pwd)/docs/official/models/cg-lib/cg" bash agents/alakazam/build_submission.sh

# Evaluate in the OFFICIAL cabt environment (more accurate than the ctypes harness)
venv/bin/python tools/cabt_eval.py agents/alakazam crustle 40

# Submit to the ladder
venv/bin/kaggle competitions submit pokemon-tcg-ai-battle \
  -f agents/alakazam/submission.tar.gz -m "message"
```

## Play against an agent (web sandbox)

```bash
venv/bin/python web/server.py     # open http://localhost:8000
```
You pilot a deck against the agent and, at every decision, see the agent's
suggested move and its score for each legal option — useful for finding where
the agent's judgement differs from a human's.

---

## Strategy write-ups

`docs/strategy/` (Traditional Chinese):
- `牌組策略.md` — every deck's strategy, meta distribution, the rock-paper-scissors
  map, expected-win-rate tables, and a deck-building checklist.
- `訓練家牌應用.md` — every Trainer card by category (draw/search, energy,
  disruption, heal, switch, tools, stadiums) with application notes and combos.

---

*Not affiliated with The Pokémon Company or Kaggle. Pokémon and card names are
trademarks of their respective owners; this is independent competition work.*
