# Pokémon TCG AI Battle Challenge — Project Guide

Competition: **Pokémon TCG AI Battle Challenge** (Kaggle × The Pokémon Company × 松尾研 × HEROZ).
Goal: build an `agent(obs_dict)` that wins the standard-format card battle. Two tracks:
- **Simulation**: `pokemon-tcg-ai-battle` (Elo ladder, auto-battles). Deadline **2026-08-16**.
- **Strategy report**: `pokemon-tcg-ai-battle-challenge-strategy` ($240K). Deadline **2026-09-13**.
- 5 submissions/day; latest 2 are scored.

## Current status (2026-06-21)
- **REAL LADDER is the only reliable judge** + **the field is getting HARDER fast (Elo is relative)**: the SAME Alakazam build scored 1002.8 (6-19) → 734.2 (6-20), rank 151→985. Climbing needs GENUINE improvement; compare versions via SAME-DAY A/B (cross-day is confounded by field drift).
- 6-20 A/B: Trevenant **681**, Alakazam-resubmit **734** (both weak; Trevenant's cabt 72% vs Lucario did NOT carry to ladder — cabt misled again).
- **6-21 FIX shipped**: root-caused Alakazam `no_offense` losses (set up but never attack, 0 prizes) to a THIN energy base (5 usable {P} vs top pilots' 7). Adopted the **114-win consensus Alakazam deck** (7 energy, cut Enriching/Lucky Helmet/tech singles, max consistency; Dunsparce id 305→65, agent `C.DUNSPARCE` updated). battle_analyze: no_offense vs Lucario/Dragapult 4→1. Submitted same-field A/B {new vs old deck} — check next reset.
  - `agents/alakazam/` — **胡地小人 (Alakazam + Dudunsparce single-prize)** (`AlakazamPolicy`). **Ladder 1006.7 = our BEST** (type-aware energy build, 6-19). The real-meta #2 deck (see below); even vs Lucario.
  - `agents/trevenant/` — **Hop's Trevenant** (`TrevenantPolicy`), NEW 2026-06-20. Single-prize aggro: cheap revenge attackers trade 1-prize bodies UP into the 3-prize ex field; hard-counters Lucario. cabt vs Lucario **72%**, clean (0 fallback). **Submitted 2026-06-20 for ladder A/B vs base Alakazam** (scored pair = Trevenant + Alakazam 1006).
  - `agents/bellibolt/` — Iono's Bellibolt ex (`BellipoltPolicy`). Ladder 836 — but the deck CRASHED in the meta (now ~39% field WR, loses to Lucario). DEPRIORITIZED.
  - `agents/typhlosion/` — Ethan's Typhlosion (`QuilavaPolicy`). Ladder 532, 36.8% field WR — poorly positioned. DEPRIORITIZED.
  - `agents/alakazam_mist/` — Mist-overlay mirror tech. **REGRESSED on ladder (907.8 < base 1006.7)** — cabt 62-63% misled again. Do NOT use; displaced from the scored pair.
- **CRITICAL LESSON: local sims (ctypes + cabt) do NOT predict ladder rank.** cabt said Mist 62-63% > base; ladder said 907<1006. cabt said Quilava>>Bellibolt; ladder said opposite. Optimize via REAL-LADDER A/B (daily submissions), keep decks SIMPLE. Many local "optimizations" LOWERED the ladder score.
- Daily limit resets **UTC 00:00 = Taiwan 08:00**. 5 subs/day; latest 2 scored (displayed = best of the 2). Today (6-20) used 3/5.

## Meta — re-check EVERY day with `tools/meta_analyze.py` (the meta flips fast)
6-19 episodes (5411 games), archetype detection FIXED (excludes shared draw engines like Fezandipiti/Dudunsparce — they're tech, not deck identity). Field %/WR:
- **Mega Lucario ex 55.8% / 52.7%** — the field KING (megaEx = 3-prize liability).
- **Alakazam 16.5% / 50% (OUR deck) — the real #2; TOP players (Elo≥1150) run it 34.7%.** We picked well.
- **Crustle COLLAPSED 5.9% / 40%** (was ~50% on 6-17). The whole "beat Crustle" thesis is DEAD/obsolete.
- Iono's Bellibolt 7% / 39% (crashed from 72.8%), Ethan's Typhlosion 3.4% / 37%.
- **Hop's Trevenant 2.2% / 70.6% field, 10% / 72.7% top — the counter-meta sleeper. Beats Lucario 75%, our Alakazam 59%.**
- Matchups (6-19): Alakazam vs Lucario 52% (even), vs Crustle 71%; weak vs Trevenant 41%, Bellibolt 29%.
- Lesson: deck choice dominates ladder. The field king is Lucario; Trevenant is the deck that beats it. Trend 6-17→6-19: Crustle ~50%→5.9%, Lucario 47.5%→55.8%.

## Repo layout (reorganized 2026-06-18 — see README.md)
- `agents/<deck>/` — each ladder agent. Each: `main.py` (the agent: `agent(obs_dict) -> list[int]`, robust scaffolding — deck-load, `normalize_selection`, `get_card`, per-`SelectContext` scoring, `_legal_fallback` so it never crashes), `deck.csv` (60 IDs), `build_submission.sh` (location-independent; packs `main.py + deck.csv + cg/`). The scaffolding is shared across agents — copy `agents/alakazam/main.py` as the template for a new deck and rewrite the `*Policy`.
  - `agents/alakazam` = 胡地小人 (AlakazamPolicy, ladder 1006.7 BEST, real-meta #2). `agents/trevenant` = Hop's Trevenant (TrevenantPolicy, single-prize counter to Lucario, A/B in flight). `agents/bellibolt`/`agents/typhlosion` = deprioritized (meta moved past them).
- `docs/strategy/` — TC strategy write-ups. `web/` — human-vs-AI sandbox. `research/` — early/superseded experiments.
- `tools/`: `meta_analyze.py` (episode zip → archetype distribution + WR + top-tier slice + matchup matrix; **run daily**), `replay_divergence.py` (replay top-pilot games through our agent → SelectContext-bucketed decision divergences = piloting fixes), `cabt_eval.py` (official-env eval vs sample bots), `cabt_ab.py` (A/B two of our agents), `battle_analyze.py` (anomaly/loss-cause report).
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

### Hop's Trevenant (agents/trevenant — NEW counter-meta deck)
- Pokémon (all SINGLE-prize, no ex): Hop's Phantump(878, 70HP {P})→**Hop's Trevenant(879, 140HP)**, Hop's Cramorant(311, 110HP), Hop's Snorlax(304, 150HP). Energy: 4 Mist(11, {C}+prevent effects on holder), 4 Telepath Psychic(19, {P}+search 2 basic {P} on attach). Trainers: Hop's Bag(1115), Pokégear(1122), TR Transceiver(1134)→Petrel(1219, any Trainer), Poké Pad(1152), **Hop's Choice Band(1171, −{C} cost +30 dmg)**, Boss(1182), Hilda(1225), Lillie's Det(1227), **Postwick(1255 stadium, +30 Hop's dmg)**, Secret Box(1092), Night Stretcher(1097).
- **Engine**: Trevenant **Horrifying Revenge** [C]=30, +100 if a Hop's was KO'd last opp turn (=130); with Choice Band it costs 0. Stack +30s (Postwick + Choice Band + **Snorlax "Extra Helpings" ability**, no self-stack) → 130+90=220. Cramorant **Fickle Spitting** [C]=120 only when opp at 3-4 prizes. Plan: flood cheap 1-prize bodies, trade UP into the opp's 3-prize ex, win the prize race. Weakness: Trevenant=Dark, Snorlax=Fighting (=Lucario, keep it benched).

### Lucario / Crustle (reference)
- **Mega Lucario ex = the field king (56%)** — megaEx, 3 prizes. Beat it by trading single-prize attackers up (Trevenant) or out-tempo (Alakazam, even matchup).
- Crustle (now rare): Dwebble(344)→Crustle(345), ability blocks ALL damage from ex/megaEx attacks. Immune-to-ex IDs {158,207,330,345}. Beat with non-ex attackers.

## Next steps / ideas
1. **Watch the Trevenant ladder A/B** (submitted 6-20 vs base Alakazam 1006). If Trevenant scores ≥ Alakazam, lean into it.
2. **Apply Alakazam piloting fixes from `replay_divergence.py`** (A/B each on the ladder): biggest gap = **IS_FIRST — top pilots unanimously go FIRST; our agent hardcodes go-second** (flip & A/B). Then TO_HAND search-target selection (52% agree), MAIN ordering (40%).
3. Try the 94-count Trevenant variant (Trevenant+Dudunsparce engine, 77% wild WR vs the 68% Team-Rocket build we shipped).
4. Re-pull daily episode data; `tools/meta_analyze.py` every day — the meta flips fast (Crustle ~50%→dead in 2 days).
