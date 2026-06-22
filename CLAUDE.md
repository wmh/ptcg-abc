# Pokémon TCG AI Battle Challenge — Project Guide

Competition: **Pokémon TCG AI Battle Challenge** (Kaggle × The Pokémon Company × 松尾研 × HEROZ).
Goal: build an `agent(obs_dict)` that wins the standard-format card battle. Two tracks:
- **Simulation**: `pokemon-tcg-ai-battle` (Elo ladder, auto-battles). Deadline **2026-08-16**.
- **Strategy report**: `pokemon-tcg-ai-battle-challenge-strategy` ($240K). Deadline **2026-09-13**.
- 5 submissions/day; latest 2 are scored.

## Current status (2026-06-22 PM)
- **6-22 SHIPPED (4/5 subs, 1 left): Dragapult ex (fix v1+v2) + Alakazam (hedge).** Latest 2: Dragapult fix v1 (Fez priority) and v2 (evolve revert+attach bonus). Scores accrue after next reset (UTC 00:00 / TW 08:00) — **CHECK THEM**.
- **`agents/dragapult/` — Dragapult ex (PRIMARY).** Consensus top-tier netdeck. Phantom Dive spread/control. **PILOT = the official sample agent** with our robust scaffolding.
  - **6-22 PILOT FIX (divergence-driven):** `divergence_decode --archetype "Dragapult ex"` against Elo≥1150 pool revealed **Fezandipiti ex OVER-prioritization** was the #1 piloting bug. Fix (4 changes):
    1. **Fezandipiti ex PLAY score**: 53000→**35000** (was outranking Dreepy/Budew/Latias/items)
    2. **Fezandipiti ex hand_score (pre_ko)**: 50000→**15000** (TO_HARD no longer grabs Fez over energy+board)
    3. **Dreepy PLAY score**: 51000→**54000** (prioritize board setup)
    4. **ATTACH bonus vs Dragapult ex**: **+25000** when <2 energy (fuel Phantom Dive faster)
    - ⚠ KEY LESSON: **don't blindly increase EVOLVE scores** — making Dreepy→Drakloak evolve too attractive (50000) made the ATTACH-vs-EVOLVE divergence WORSE. EVOLVE stays at 30000, below ATTACH (45150) and ABILITY (40000).
- `agents/alakazam/` — 胡地小人 (AlakazamPolicy, **2nd deck / hedge**). Even vs Dragapult in the real meta (49%), 55.1% top-tier WR. Hedge.
- `agents/trevenant/` — Hop's Trevenant (TrevenantPolicy). **DEMOTED 6-22.**
- `agents/bellibolt/` (836) + `agents/typhlosion/` (532) — DEPRIORITIZED.
- **CRITICAL LESSON: local sims (ctypes + cabt) do NOT reliably predict ladder rank.** Still: REAL-LADDER A/B is the only judge — confirm at reset.
- **Daily limit**: 5 subs/day; latest 2 scored (displayed = best of the 2). UTC 00:00 = Taiwan 08:00 reset.
- **NEW TOOL**: `tools/autopsy.py` — one-shot daily pipeline: download episodes + leaderboard → run meta_analyze + divergence_decode → save reports to `/tmp/autopsy/<date>/`.

## Meta — re-check EVERY day with `tools/autopsy.py` (the meta flips fast)
**6-21 episodes (5046 decisive games) — META FLIPPED AGAIN: Dragapult ex surged, Trevenant's WR cratered, Lucario extinct.**
TOP TIER (Elo≥1150, 1524 games):
- **Hop's Trevenant 42.2% / 52.3% WR** — still most-played at the top but WR collapsed from 64.6% (6-20). The field adapted.
- **Alakazam 18.9% / 55.1%** (our #2 — now a higher WR than Trevenant).
- **Dragapult ex 16.5% / 63.1% 🚀 (OUR NEW PRIMARY)** — the rapid riser; one consensus netdeck, 63% WR.
- Chandelure 6.0% / 66.7% 🚀, Cinderace 3.8% / 67.2% 🚀, **Mega Froslass ex 3.6% / 70.0% 🚀** (all Trevenant counters), Team Rocket's Mewtwo ex 1.9% / 75.4%, **Mega Lucario ex 0.4% / 46% (EXTINCT — was the 56% king).**
FIELD (all, 5046): Hop's Trevenant 37.6% / 51.9%, Alakazam 27.6% / 50.8%, Mega Lucario 16.6% / 35.8% (collapsing), Dragapult ex 6.4% / 61.5%.
**Dragapult matchups (row, top tier): vs Trevenant 79% ✓, vs Chandelure 81% ✓, vs Iono 80% ✓, vs Alakazam ~49-51% (even), vs Mega Lucario 46%, ONLY clear loss vs Cinderace 36%.** Best-positioned deck in the format — beats the two biggest field decks.
- Lesson: deck choice dominates; the wave moved from Trevenant→Dragapult in ONE day. **Next threats to watch: Cinderace (Dragapult's counter, 67% WR rising) + Chandelure + Mega Froslass.** Trend: Trevenant top-tier WR 64.6%(6-20)→52.3%(6-21); Dragapult tiny→16.5%/63% top tier.

## Repo layout (reorganized 2026-06-18 — see README.md)
- `agents/<deck>/` — each ladder agent. Each: `main.py` (the agent: `agent(obs_dict) -> list[int]`, robust scaffolding — deck-load, `normalize_selection`, `get_card`, per-`SelectContext` scoring, `_legal_fallback` so it never crashes), `deck.csv` (60 IDs), `build_submission.sh` (location-independent; packs `main.py + deck.csv + cg/`). The scaffolding is shared across agents — copy `agents/alakazam/main.py` as the template for a new deck and rewrite the `*Policy`.
  - `agents/dragapult` = **Dragapult ex (PRIMARY, 6-22)** — adopts the official sample pilot (NOT a `*Policy` class; it's the sample's `_policy()` + a robust `agent()` wrapper). `agents/alakazam` = 胡地小人 (AlakazamPolicy, 2nd/hedge). `agents/trevenant` = Hop's Trevenant (demoted, field turned hostile). `agents/bellibolt`/`agents/typhlosion` = deprioritized.
- `docs/strategy/` — TC strategy write-ups. `web/` — human-vs-AI sandbox. `research/` — early/superseded experiments.
- `tools/`: `autopsy.py` (daily pipeline: download eps+LB → meta + divergence → `/tmp/autopsy/`), `meta_analyze.py` (episode zip → archetype distribution + WR + top-tier slice + matchup matrix; **run daily**), `replay_divergence.py` (replay top-pilot games through our agent → SelectContext-bucketed agree% = where we pilot differently), `divergence_decode.py` (same, but DECODES each disagreement into card/attack/option NAMES + aggregates human-vs-ours picks, and `--player "TeamName"` isolates ONE pilot — this is how you derive concrete piloting RULES, not just bare indices), `cabt_eval.py` (official-env eval vs sample bots), `cabt_ab.py` (A/B two of our agents), `battle_analyze.py` (anomaly/loss-cause report).
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
venv/bin/kaggle datasets download kaggle/pokemon-tcg-ai-battle-episodes-index -p /tmp/idx --unzip   # /tmp/idx/manifest.csv lists dates + top/median scores
venv/bin/kaggle datasets download kaggle/pokemon-tcg-ai-battle-episodes-2026-06-19 -p /tmp/ep19      # zip ~720MB (manifest's 21GB is the UNCOMPRESSED size)
venv/bin/kaggle competitions leaderboard pokemon-tcg-ai-battle --download -p /tmp/lb                # name→Elo for the top-tier slice
venv/bin/python tools/meta_analyze.py /tmp/ep19/<zip> --elo 1150                                     # archetype distribution + matchups
venv/bin/python tools/replay_divergence.py /tmp/ep19/<zip> agents/alakazam --archetype Alakazam      # piloting divergences
```
Process the .zip directly with Python `zipfile` (do NOT extract — 21GB unpacked). Each episode JSON: `steps[1][pi]['action']` = the 60-card deck; `rewards` = [p0,p1] (winner = higher); `info.Agents[i].Name` = player (map to Elo via the leaderboard CSV's `TeamName`). Replay: `steps[t][pi]['observation']` feeds our `agent`; the ANSWER to obs[t] is `steps[t+1][pi]['action']` (off-by-one — sub-decisions are consecutive same-pi steps; step-1 action is the deck).
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

### Dragapult ex (agents/dragapult — PRIMARY, 6-22) — consensus top-tier netdeck
- Pokémon: Dreepy(119, 70HP {N})→Drakloak(120, 90HP, *Recon Directive*: look top2, take 1)→**Dragapult ex(121, 320HP, stage2, 2 prizes)**. Support: Budew(235, 30HP {G}, *Itchy Pollen*[]=10 → opp can't play Items next turn), Fezandipiti ex(140, 210HP {D}, *Flip the Script*: if a mon was KO'd last turn, draw 3; Cruel Arrow[CCC]=100 to any), Latias ex(184, 210HP {P}, *Skyliner*: your Basics have no retreat cost; Eon Blade[PPC]=200), Meowth ex(1071, 170HP {C}, *Last-Ditch Catch*: on play from hand→search a Supporter). Energy: 4 Basic {R}/Fire(id 2) + 4 Basic {P}/Psychic(id 5).
- **Engine**: **Phantom Dive [R][P] = 200 to Active + put 6 damage counters (=60) on opp's BENCH however you like** — the win condition: set up multi-prize turns by pre-loading counters then KO-ing. Jet Headbutt[C]=70 is the cheap fallback. Disruption: **4× Crushing Hammer**(1120, coin-flip discard an opp Energy), Budew item-lock. Accel: **Crispin**(1198, search 2 diff-type basic energy: attach 1 + 1 to hand), **Rare Candy**(1079, Dreepy→Dragapult skip). Search/draw: Buddy-Buddy Poffin(1086, 2 basics ≤70HP→bench), Ultra Ball, Brock's Scouting, Poké Pad, Lillie's Det, Boss(1182), Night Stretcher, Unfair Stamp(1080, comeback draw after a KO), Lucky Helmet(1156 tool), Team Rocket's Watchtower(1256 stadium, {C} mons have no Abilities). **Plays GO SECOND.** Phantom Dive immune-active IDs {158,207,330,345}; no-counter IDs {28,199,203,207,362,1136} + holders of Mist(11)/Rock-Fighting(20) energy. Weakness: none on the line (Budew=Fire-weak).
- **Agent**: NOT a `*Policy` — it's the official sample's `_policy()` + a robust `agent()` wrapper. See the status section for why (sample beat a from-scratch policy 13-1).
- **6-22 PILOT FIX (divergence-driven)**: `divergence_decode` vs Elo≥1150 pool showed **Fezandipiti ex over-prioritization** was the #1 bug. Top players attach energy to Dragapult ex & play Dreepy/Budew/Latias/items over Fezandipiti ex. Fix: Fez PLAY 53000→35000, Fez hand_score(pre_ko) 50000→15000, Dreepy PLAY 51000→54000, ATTACH bonus +25000 when Dragapult ex <2 energy. ⚠ CRITICAL: EVOLVE score MUST stay at 30000 (raising it to 50000 made the ATTACH-vs-EVOLVE divergence WORSE). This is the lesson: every score change must be verified against the divergence data, not made intuitively. See divergence_data in `/tmp/autopsy/`.

### Hop's Trevenant (agents/trevenant — counter-meta deck, DEMOTED 6-22)
- Pokémon (all SINGLE-prize, no ex): Hop's Phantump(878, 70HP {P})→**Hop's Trevenant(879, 140HP)**, Hop's Cramorant(311, 110HP), Hop's Snorlax(304, 150HP). Energy: 4 Mist(11, {C}+prevent effects on holder), 4 Telepath Psychic(19, {P}+search 2 basic {P} on attach). Trainers: Hop's Bag(1115), Pokégear(1122), TR Transceiver(1134)→Petrel(1219, any Trainer), Poké Pad(1152), **Hop's Choice Band(1171, −{C} cost +30 dmg)**, Boss(1182), Hilda(1225), Lillie's Det(1227), **Postwick(1255 stadium, +30 Hop's dmg)**, Secret Box(1092), Night Stretcher(1097).
- **Engine**: Trevenant **Horrifying Revenge** [C]=30, +100 if a Hop's was KO'd last opp turn (=130); with Choice Band it costs 0. Stack +30s (Postwick + Choice Band + **Snorlax "Extra Helpings" ability**, no self-stack) → 130+90=220. Cramorant **Fickle Spitting** [C]=120 only when opp at 3-4 prizes. Plan: flood cheap 1-prize bodies, trade UP into the opp's 3-prize ex, win the prize race. Weakness: Trevenant=Dark, Snorlax=Fighting (=Lucario, keep it benched).

### Lucario / Crustle (reference)
- **Mega Lucario ex = the field king (56%)** — megaEx, 3 prizes. Beat it by trading single-prize attackers up (Trevenant) or out-tempo (Alakazam, even matchup).
- Crustle (now rare): Dwebble(344)→Crustle(345), ability blocks ALL damage from ex/megaEx attacks. Immune-to-ex IDs {158,207,330,345}. Beat with non-ex attackers.

## Next steps / ideas
1. **Check the 6-22 scores next reset (THE key read)**: did the **Fez priority fix** improve Dragapult ex? If ≥950, the fix worked — keep divergence-mining. If still <900, re-evaluate Dragapult vs Trevenant.
2. **Run `tools/autopsy.py` daily** — one command gives you fresh meta + divergence data. The meta flips fast (Lucario 56%→extinct in 3 days).
3. **Mine more Dragapult divergences**: current fix addresses 10/11 divergences. Remaining gaps to watch: Phantom-Dive spread placement (`DAMAGE_COUNTER` context), Crushing-Hammer targeting, Boss timing, when to go for the multi-KO turn. Run `divergence_decode.py --context DAMAGE_COUNTER` for spread-specific gaps.
4. **Watch CINDERACE (Dragapult's only clear loss, 36%) + Chandelure + Mega Froslass ex** — as Dragapult/Trevenant define the field, their counters rise next. Pull Cinderace's decklist/mechanics from episodes; find a tech or sideboard answer if it climbs.
5. **Alakazam piloting headroom**: archetype is 55% top-tier WR but our pilot scored only 674. No official Alakazam sample exists, so improve via divergence mining vs top Alakazam pilots (Elo≥1150). It's our hedge if the field turns anti-Dragapult.
6. **When score-fixing any agent, NEVER blindly increase scores** — verify EVERY change against the divergence data. The EVOLVE 50000 mistake cost us 2 submissions to correct. Instead of raising competing scores, lower the over-prioritized card's score (e.g., Fezandipiti ex 53000→35000).
