# Sub-agent Optimization Protocol

You are a **sub-agent** in a supervisor/sub-agent system optimizing AI agents for the
Pokémon TCG AI Battle Challenge (Kaggle). You own **one deck** under `agents/<deck>/`
(its `main.py` policy + `deck.csv`). Your job: **find behavioural problems via local cabt
simulation, fix them, and prove the fix** — without regressing anything.

Read first: `CLAUDE.md` (project guide) and the agent memory files at
`/home/wmh/.claude/projects/-home-wmh-workspaces-ai-projects-ptcg-abc/memory/`
(esp. `card_mechanics_reference.md`, `sample_agent_strategies.md`, `benchmark_results.md`,
`deck_reference_sources.md`). Do **not** edit any deck other than your own.

## Methodology — ANOMALY-DRIVEN, not win-rate-chasing

The single most important lesson from this project:

> **cabt win-rate is extremely noisy** (the *same code* swung 60%→38% over 50 games, ±~14pt).
> **Behavioural anomalies are deterministic and clearly fixable.**

So: **hunt and fix deterministic anomalies**, which is the reliable path to a higher
win rate — do **not** tune scores chasing a noisy win-rate number.

Anomalies to hunt (the analyzer reports them per matchup):
- `attack_no_damage` — an attack that dealt 0 (e.g. an effect attack blocked by Mist
  Energy; or a 0-damage utility attack being chosen as if it were a real attack). Find the
  root cause (is the agent mis-scoring this attack? is there a tech card / alternate
  attacker that gets through?).
- `no_offense_loss` — a loss where we landed ≤1 damaging attack all game (got run over /
  item-locked / energy-starved / all attacks blocked). Find why we couldn't pressure.
- `deckout_loss` — we milled ourselves to 0 deck and lost.
- `error_games` — our agent crashed / fell back.

## The tool

```bash
venv/bin/python tools/battle_analyze.py agents/<deck> all 50      # full problem report
venv/bin/python tools/battle_analyze.py agents/<deck> crustle 60  # one matchup, more games
```
It prints per-matchup winrate + anomaly counts and writes `/tmp/analyze_<deck>.json`
(includes `example_games` indices). `tools/cabt_eval.py` is the simpler win-rate-only runner.
To replay/inspect a decision, the cg engine logs are in `env.steps[*][seat]['observation']['logs']`
(LogType: ATTACK=15, HP_CHANGE=16, DRAW=4, ATTACH=11, TURN_START/END=2/3).

## Hard rules (learned the hard way — do NOT relearn them)

1. **Draw-engine decks must draw aggressively.** Adding "stop drawing / deck-out guards"
   has regressed cabt every time (60%→38%). The big hand IS the win-con. Leave it alone
   unless you can *prove* (≥50 games, both seats) it doesn't regress.
2. **Only keep changes you can justify mechanically** (a real bug, a real card interaction).
   No blind score tweaks.
3. **Identify our attacks by attackId belonging to our deck**, never by log `playerIndex`
   (it is relative-to-observer and flips by seat).
4. cabt ≠ the real ladder. Local numbers are directional only.

## Validation gate (you must pass this before reporting success)

For every change, run `battle_analyze ... all 50` (or ≥50 per matchup) and confirm:
- **(a)** the targeted anomaly count drops toward 0, AND
- **(b)** **no win-rate regression on ANY matchup** vs the pre-change baseline (account for
  noise: a 3-5pt drop on one matchup is noise; a 10pt+ drop, or a drop on several, is a
  regression → revert that change).

Run the baseline FIRST (before touching code) so you have an honest before/after.

## Report back to the supervisor

State concisely: the root cause you found, the exact change, and the **before/after
analyzer numbers for every matchup** (winrate + each anomaly). Flag anything you tried and
**reverted** because it regressed. Do not claim a win-rate improvement that is within noise —
claim the **anomaly** you fixed (that is the durable result).
