# Pokémon TCG AI Battle Challenge — Project Guide

Competition: **Pokémon TCG AI Battle Challenge** (Kaggle × The Pokémon Company × 松尾研 × HEROZ).
Goal: build an `agent(obs_dict)` that wins the standard-format card battle. Two tracks:
- **Simulation**: `pokemon-tcg-ai-battle` (Elo ladder, auto-battles). Deadline **2026-08-16**.
- **Strategy report**: `pokemon-tcg-ai-battle-challenge-strategy` ($240K). Deadline **2026-09-13**.
- 5 submissions/day; latest 2 are scored.

## Current status (2026-06-18)
- **Three decks built; REAL LADDER is the only reliable judge** (local ctypes AND cabt both mispredicted ladder rank — see below).
  - `agents/bellibolt/` — **Iono's Bellibolt ex** (`BellipoltPolicy`). **Ladder 836 = our BEST** (the proven simple deck). Pure-v1 ready (anti-Fighting gated behind `USE_ANTI_FIGHTING=False`).
  - `agents/typhlosion/` — Ethan's Typhlosion + Dudunsparce (`QuilavaPolicy`) + Boss's Orders/tools. **Ladder 532 — WORSE than Bellibolt** (complex deck, our agent pilots it clunkily).
  - `agents/alakazam/` — **胡地小人 (Alakazam + Dudunsparce single-prize)** (`AlakazamPolicy`). Top-meta NOW. Powerful Hand = 20×hand-size; pilots well locally (15/15 setup, ~350 dmg). cabt-best of the three. **Ladder A/B pending.**
  - `agents/alakazam_mist/` — alakazam + 2 Mist Energy (−2 Poké Pad) + defensive-attach logic. **Mirror tech**: Mist Energy negates Powerful Hand (counter placement = an "effect"); agent overlays Mist on a fuelled attacker vs counter-decks when not ahead on prizes. cabt mirror **62-63% vs base** (control: Mist unpiloted = 50% → gain is all from piloting); Crustle 85%≈base 80%. **Submitted 2026-06-20 for ladder A/B vs base alakazam.**
- **CRITICAL LESSON: local sims (ctypes + cabt) do NOT predict ladder rank.** Bellibolt 836 > Quilava 532 on the ladder, yet cabt said Quilava>>Bellibolt. 20-game ctypes varies wildly (same code: 16W↔6W) — too noisy to tune small changes. Optimize via REAL-LADDER A/B (daily submissions), keep decks SIMPLE (our agent's strength). Every "optimization" I made (draw-fix, Quilava switch) LOWERED the ladder score.
- Daily limit resets **UTC 00:00 = Taiwan 08:00**. Our team: `superwmh`.

## Why we switched decks (CRITICAL meta lesson)
The meta shifts FAST. Re-check it every day from the episode datasets.
- 6-16 data: Mega Lucario ex was 61.6% (best volume deck).
- 6-17 data (7819 games): **Crustle exploded to ~50% of the field**; Mega Lucario ex dropped to **47.5%** (Crustle is immune to ex attacks → Lucario loses 23% vs Crustle). **Iono's Bellibolt ex = 72.8%**, used by #1 (onechan1, Elo 1298) and #2.
- Matchup vs Crustle: **Bellibolt 91%**, Fezandipiti 70%, Crustle-mirror 50%, **Lucario 23%**, Dragapult 11%, Abomasnow 12%.
- Lesson: deck choice dominates agent quality on the ladder. Pick a deck that beats the field's dominant deck (currently Crustle).

## Repo layout (reorganized 2026-06-18 — see README.md)
- `agents/bellibolt/`, `agents/typhlosion/`, `agents/alakazam/` — the three ladder agents. Each: `main.py` (the agent: `agent(obs_dict) -> list[int]`, robust scaffolding — deck-load, `normalize_selection`, `get_card`, per-`SelectContext` scoring, `_legal_fallback` so it never crashes), `deck.csv` (60 IDs), `build_submission.sh` (location-independent; packs `main.py + deck.csv + cg/`).
  - `agents/bellibolt` = Iono's Bellibolt ex (BellipoltPolicy, ladder 836 BEST). `agents/typhlosion` = Ethan's Typhlosion+Dudunsparce (QuilavaPolicy, 532). `agents/alakazam` = 胡地小人 (AlakazamPolicy, top-meta candidate).
- `docs/strategy/` — TC strategy write-ups. `tools/cabt_eval.py` — official-env eval. `web/` — human-vs-AI sandbox. `research/` — early/superseded experiments (env, MCTS, BC/value trainers, tests).
- `docs/official/models/` — official notebooks + `cg-lib/` (local engine). **GITIGNORED** (on the Kaggle site); kept locally for testing. `.kaggle*/`, `private/`, `venv/`, `**/cg/`, `*.tar.gz` also gitignored.

## Build & submit (per agent)
```bash
CG_LIB_PATH="$(pwd)/docs/official/models/cg-lib/cg" bash agents/<agent>/build_submission.sh
venv/bin/kaggle competitions submit pokemon-tcg-ai-battle -f agents/<agent>/submission.tar.gz -m "message"
venv/bin/kaggle competitions submissions pokemon-tcg-ai-battle    # check score
```

## Analyzing the meta (episode replays)
Episodes (real ladder games incl. top players) are Kaggle datasets, one per day:
```bash
venv/bin/kaggle datasets download kaggle/pokemon-tcg-ai-battle-episodes-index -p /tmp/idx --unzip   # lists dates
venv/bin/kaggle datasets download kaggle/pokemon-tcg-ai-battle-episodes-2026-06-17 -p /tmp/ep17     # ~760MB
```
Disk is tight (~99% full): process the .zip directly with Python `zipfile` (do NOT extract 21GB).
Each episode JSON: `steps[1][playerIdx]['action']` = the 60-card deck; `rewards` = [p0,p1] (winner = higher); `info.Agents[i].Name` = player. Replay states are `steps[*][pi]['observation']` (feed to our `agent` to compare decisions).
Leaderboard: `venv/bin/kaggle competitions leaderboard pokemon-tcg-ai-battle --download`.

## Engine API essentials (cg-lib)
- Game-over: `obs.current.result != -1` (winner index). `obs.select is None` during deck-selection (return the 60 IDs).
- `SelectContext`: MAIN=0, SETUP_ACTIVE=1, SETUP_BENCH=2, SWITCH=3, TO_ACTIVE=4, TO_BENCH=5, TO_HAND=7, DISCARD=8, ATTACH_FROM=21, ATTACH_TO=22, DAMAGE_COUNTER=13/14, IS_FIRST=41, MULLIGAN=42.
- `OptionType`: NUMBER=0, YES=1, NO=2, CARD=3, ENERGY=6, PLAY=7, ATTACH=8, EVOLVE=9, ABILITY=10, RETREAT=12, ATTACK=13, END=14.
- `Pokemon`: `.hp` (current), `.maxHp`, `.energies` (list of EnergyType), `.energyCards`, `.tools`, `.id`.
- `EnergyType`: COLORLESS=0, GRASS=1, FIRE=2, WATER=3, LIGHTNING=4, PSYCHIC=5, FIGHTING=6 ...
- `State`: `.turn`, `.yourIndex`, `.firstPlayer`, `.supporterPlayed`, `.stadiumPlayed`, `.energyAttached`, `.stadium`, `.players[2]`.
- Card data: `all_card_data()` → `card.cardId/hp/weakness/resistance/ex/megaEx/stage1/stage2/attacks/skills/evolvesFrom/retreatCost`. `all_attack()` → `attack.attackId/name/damage/energies/text`.

## Testing: use the OFFICIAL cabt env (accurate), not the ctypes harness
`venv/bin/pip install kaggle-environments` (1.30.1 = ladder version), then:
```bash
venv/bin/python tools/cabt_eval.py agents/alakazam crustle 20   # <our_dir> <crustle|lucario|abomasnow|dragapult|mirror> [games]
```
`tools/cabt_eval.py` builds opponents from the sample notebooks + consensus decks and runs `make('cabt')` matches (~1s/game). The old ctypes loop (battle_start/battle_select) gives UNRELIABLE numbers for some matchups (it crippled the strong day-1 Crustle bot: ctypes 98% vs cabt 20% for the same matchup; mirror & Lucario agree). Trust cabt + the real ladder. Agents need `cg/` copied into their dir for cabt.

## Human-vs-AI web sandbox (`web/`)
Play against the agent in a browser and see the strategy's suggested move + per-option scores at every decision (for finding optimization points by comparing human intuition vs the agent).
```bash
venv/bin/python web/server.py        # then open http://localhost:8000
```
- You pilot the Typhlosion deck (`agents/typhlosion`); pick opponent (Crustle/Lucario) in the header.
- `web/server.py`: stdlib HTTP server wrapping the cg engine; runs the opponent agent automatically; exposes `/new?opp=`, `/state`, `/select`. The human's legal options are labelled and each shows `QuilavaPolicy.rank()` score; the AI's `normalize_selection` pick is flagged `recommended`/★.
- `web/index.html`: single-page board UI. Single global game, single-threaded (one user at a time — the cg engine has global state).

## Strategy reference docs (Traditional Chinese — for the user to review)
- `docs/strategy/牌組策略.md` — all deck strategies, meta distribution, rock-paper-scissors map, expected-WR table, deck-building checklist.
- `docs/strategy/訓練家牌應用.md` — every trainer card by category (draw/search, energy, disruption, heal/recover, switch, tools, stadiums) + application notes & combos.
Keep both updated whenever the meta shifts or we switch decks.

## Card mechanics reference
Full per-deck card/attack/ability details live in the agent memory file `card_mechanics_reference.md`
(`/home/wmh/.claude/projects/-home-wmh-workspaces-ai-projects-ptcg-abc/memory/`). **Update it on every deck change** — the user wants every deck's mechanics kept permanently.

### Iono's Bellibolt ex (current deck)
- Pokémon: Voltorb(265), Tadbulb(268)→**Bellibolt ex(269, HP280, Thunderous Bolt 230, ability Electric Streamer = attach {L} from hand unlimited/turn)**, Wattrel(270)→Kilowattrel(271, HP120 non-ex, Mach Bolt 70, ability Flashing Draw). Trainers: Lillie's Det(1227), Canari(1233), Buddy Poffin(1086), Ultra Ball(1121), Levincia(1254 stadium), Night Stretcher(1097), Poké Pad(1152), Max Rod(1110), Energy Retrieval(1118). 22× Basic {L}(4).
- Plan: stream {L} onto an attacker, KO; rotate attackers because Thunderous Bolt locks; Kilowattrel/Voltaic Chain (non-ex) handle Crustle's ex-immunity.
- Known weakness of our agent: slow setup vs aggro (Bellibolt is Stage1 + 4 energy + lock). Improve early tempo / Voltaic Chain pressure.

### Crustle (the deck to beat — ~50% of field)
- Dwebble(344, 70HP, 1 prize) → Crustle(345, 150HP, Superb Scissors {G}{C}{C}→120; ability **Mysterious Rock Inn blocks ALL damage from opponent ex/megaEx attacks**). Weakness FIRE. Slow (1 prize/turn). Heals via Cook(1212)/Jumbo Ice Cream(1147). Battle Cage(1264) blocks bench damage.
- Beat it with **non-ex attackers** + fast aggression. Immune-to-ex IDs: {158, 207, 330, 345}.

## Next steps / ideas
1. Improve Bellibolt piloting vs aggro: faster energy concentration on one attacker, use Voltaic Chain (scales, no lock) for early pressure, manage Thunderous Bolt lock with a backup attacker.
2. Test vs more field decks (Abomasnow, Dragapult, Fezandipiti).
3. RL: official `reinforcement-learning-and-mcts-sample-code.ipynb` (MCTS + Transformer, self-play). Use prize-race tempo as reward signal.
4. Re-pull daily episode data; re-evaluate deck choice if the meta shifts again.
