"""Run matchup battles between agents using the cg.game local simulator.

Usage:
    python3 tests/run_battles.py [--games N] [--vs v1|iono|random]

Results:
    Prints win/loss/draw counts and win rate.
"""
from __future__ import annotations

import sys
import os
import argparse
import ctypes
import types
from collections import defaultdict

# ── Path setup ────────────────────────────────────────────────────────────────

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CG_LIB = os.path.join(ROOT, "docs/official/models/cg-lib")
sys.path.insert(0, CG_LIB)
sys.path.insert(0, ROOT)

from cg.game import battle_start, battle_finish, _get_battle_data
from cg.api import all_card_data, to_observation_class
from cg.sim import lib, Battle

# ── Deck loading ───────────────────────────────────────────────────────────────

DECK_CSV = os.path.join(ROOT, "submit/deck.csv")
with open(DECK_CSV) as f:
    LUCARIO_DECK = [int(l) for l in f.read().splitlines() if l.strip()]
assert len(LUCARIO_DECK) == 60, f"Deck has {len(LUCARIO_DECK)} cards"

# ── Agent module loading ───────────────────────────────────────────────────────

def _load_module(name: str, path: str | None = None, src: str | None = None,
                 strip_first_line: bool = False) -> types.ModuleType:
    if src is None:
        src = open(path, encoding="utf-8").read()
    if strip_first_line:
        src = src.split("\n", 1)[1]
    mod = types.ModuleType(name)
    mod.__file__ = path or name
    os.chdir(ROOT + "/submit")
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    os.chdir(ROOT)
    return mod


def load_v2() -> types.ModuleType:
    return _load_module("v2_agent", path=os.path.join(ROOT, "submit/main.py"))


def _extract_notebook_agent(nb_path: str, cell_index: int = 2) -> str:
    """Extract agent source from a notebook cell (strips %%writefile magic)."""
    import json
    with open(nb_path, encoding="utf-8") as f:
        nb = json.load(f)
    src = "".join(nb["cells"][cell_index]["source"])
    if src.startswith("%%writefile"):
        src = src.split("\n", 1)[1]
    return src


def load_v1() -> types.ModuleType:
    nb_path = os.path.join(ROOT, "docs/official/models/a-sample-rule-based-agent-mega-lucario-ex-deck.ipynb")
    src = _extract_notebook_agent(nb_path)
    return _load_module("v1_agent", src=src)


def load_iono() -> types.ModuleType:
    nb_path = os.path.join(ROOT, "docs/official/models/a-sample-rule-based-agent-iono-s-deck.ipynb")
    src = _extract_notebook_agent(nb_path)
    return _load_module("iono_agent", src=src)


def random_agent_fn(obs_dict: dict) -> list[int]:
    import random
    from cg.api import to_observation_class
    obs = to_observation_class(obs_dict)
    if obs.select is None:
        return LUCARIO_DECK
    select = obs.select
    n = len(select.option)
    if n == 0:
        return []
    k = max(select.minCount, 1)
    k = min(k, n)
    return list(range(k))  # just take first k (deterministic "random")


# ── Deck for each opponent ─────────────────────────────────────────────────────

def get_iono_deck() -> list[int]:
    # Iono's deck from the sample agent
    Iono_Voltorb, Iono_Tadbulb, Iono_Bellibolt_ex = 265, 268, 269
    Iono_Wattrel, Iono_Kilowattrel = 270, 271
    Buddy_Buddy_Poffin, Night_Stretcher, Max_Rod = 1086, 1097, 1110
    Energy_Retrieval, Ultra_Ball, Poke_Pad = 1118, 1121, 1152
    Lillie_Determination, Canari, Levincia = 1227, 1233, 1254
    Basic_Lightning_Energy = 4
    deck = (
        [Iono_Voltorb] * 3 + [Iono_Tadbulb] * 3 + [Iono_Bellibolt_ex] * 3
        + [Iono_Wattrel] * 3 + [Iono_Kilowattrel] * 3
        + [Buddy_Buddy_Poffin] * 3 + [Night_Stretcher] * 2 + [Max_Rod] * 1
        + [Energy_Retrieval] * 1 + [Ultra_Ball] * 3 + [Poke_Pad] * 2
        + [Lillie_Determination] * 4 + [Canari] * 4 + [Levincia] * 3
        + [Basic_Lightning_Energy] * 22
    )
    return deck


# ── Game loop ─────────────────────────────────────────────────────────────────

def reset_module_state(mod: types.ModuleType) -> None:
    """Force turn-state reset so module globals refresh on turn 0."""
    for attr in ("pre_turn", "_pre_turn"):
        if hasattr(mod, attr):
            setattr(mod, attr, -1)


def _safe_select(select_list: list[int]) -> dict:
    """Like battle_select but tolerates err=4 (empty option list edge case)."""
    arg = (ctypes.c_int * len(select_list))(*select_list)
    err = lib.Select(Battle.battle_ptr, arg, len(select_list))
    if err == 30:
        raise ValueError("battle_ptr broken")
    # err=4 with n=0 is a game-finished edge case — state is valid, just fetch it
    return _get_battle_data()


def run_one_game(
    agent0_mod: types.ModuleType | None,
    deck0: list[int],
    agent1_mod: types.ModuleType | None,
    deck1: list[int],
) -> int:
    """Return: 0=agent0 wins, 1=agent1 wins, 2=draw, -1=error."""
    agent0 = agent0_mod.agent if agent0_mod else random_agent_fn
    agent1 = agent1_mod.agent if agent1_mod else random_agent_fn

    if agent0_mod:
        reset_module_state(agent0_mod)
    if agent1_mod:
        reset_module_state(agent1_mod)

    obs_dict, sd = battle_start(deck0, deck1)
    if obs_dict is None:
        return -1

    max_steps = 2000
    for _ in range(max_steps):
        try:
            obs = to_observation_class(obs_dict)
        except Exception:
            battle_finish()
            return -1

        # result != -1 means game over (even if select is still not None)
        if obs.current.result != -1:
            battle_finish()
            return obs.current.result
        if obs.select is None:
            battle_finish()
            return obs.current.result

        player = obs.current.yourIndex
        try:
            action = (agent0 if player == 0 else agent1)(obs_dict)
        except Exception:
            battle_finish()
            return 1 - player  # agent crashed → opponent wins

        try:
            obs_dict = _safe_select(action)
        except ValueError:
            battle_finish()
            return -1
        except Exception:
            # Invalid action index — try legal fallback
            select = obs.select
            n = len(select.option)
            k = min(max(select.minCount, 1), n) if n else 0
            try:
                obs_dict = _safe_select(list(range(k)))
            except Exception:
                battle_finish()
                return -1

    battle_finish()
    return 2  # draw on timeout


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--vs", choices=["v1", "iono", "random"], default="v1")
    args = parser.parse_args()

    print(f"Loading agents...")
    v2_mod = load_v2()
    print(f"  V2 (our agent) loaded")

    if args.vs == "v1":
        opp_mod = load_v1()
        opp_deck = LUCARIO_DECK
        opp_name = "V1 (official sample)"
        print(f"  V1 agent loaded")
    elif args.vs == "iono":
        opp_mod = load_iono()
        opp_deck = get_iono_deck()
        opp_name = "Iono's deck"
        print(f"  Iono agent loaded")
    else:
        opp_mod = None
        opp_deck = LUCARIO_DECK
        opp_name = "Random"

    print(f"\nRunning {args.games} games: V2 vs {opp_name}")
    print("-" * 50)

    wins   = [0, 0]  # wins[0]=V2 wins, wins[1]=opp wins
    draws  = 0
    errors = 0

    for game_num in range(args.games):
        # Alternate who goes first to balance first-player advantage
        if game_num % 2 == 0:
            result = run_one_game(v2_mod, LUCARIO_DECK, opp_mod, opp_deck)
            v2_is_player = 0
        else:
            result = run_one_game(opp_mod, opp_deck, v2_mod, LUCARIO_DECK)
            v2_is_player = 1

        if result == -1:
            errors += 1
        elif result == 2:
            draws += 1
        elif result == v2_is_player:
            wins[0] += 1
        else:
            wins[1] += 1

        # Progress bar
        done = game_num + 1
        if done % 10 == 0 or done == args.games:
            total_decided = wins[0] + wins[1]
            rate = wins[0] / total_decided * 100 if total_decided else 0
            print(f"  [{done:3d}/{args.games}] V2 {wins[0]:3d}W  Opp {wins[1]:3d}W  "
                  f"Draw {draws}  Err {errors}  WR={rate:.1f}%")

    total = args.games - errors
    total_decided = wins[0] + wins[1]
    wr = wins[0] / total_decided * 100 if total_decided else 0
    wr_adj = (wins[0] + 0.5 * draws) / total * 100 if total else 0
    print()
    print(f"{'='*50}")
    print(f"Final: V2 {wins[0]}W / Opp {wins[1]}W / {draws} Draw / {errors} Error")
    print(f"Win rate (excl draws): {wr:.1f}%")
    print(f"Win rate (incl draws as 0.5): {wr_adj:.1f}%")


if __name__ == "__main__":
    main()
