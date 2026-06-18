"""CabtAgent: heuristic + MCTS agent using the cabt engine API.

Decision flow:
1. Parse obs_dict into a structured view of the board
2. For MAIN selections: score each option with heuristics,
   optionally run MCTS via cabt search_begin/search_step
3. For all other selections (discard, choose target, etc.):
   use targeted heuristics per SelectContext
4. Return chosen index list
"""
from __future__ import annotations
import math
import random
import time
from typing import Any, Optional

from deck.card_db import load_all_cards, Card

_ALL_CARDS: dict[int, Card] = {}  # loaded lazily


def _cards() -> dict[int, Card]:
    global _ALL_CARDS
    if not _ALL_CARDS:
        _ALL_CARDS = load_all_cards()
    return _ALL_CARDS


# ─── Observation helpers ──────────────────────────────────────────────────────

class BoardView:
    """Parsed snapshot of the current game state."""

    def __init__(self, obs: dict):
        self.obs = obs
        self.select = obs.get("select") or {}
        self.current = obs.get("current")  # may be None during deck selection

        if self.current:
            self.your_index: int = self.current.get("yourIndex", 0)
            self.turn: int = self.current.get("turn", 0)
            self.players: list[dict] = self.current.get("players", [{}, {}])
            self.me: dict = self.players[self.your_index] if len(self.players) > self.your_index else {}
            self.opp: dict = self.players[1 - self.your_index] if len(self.players) > 1 else {}
        else:
            self.your_index = 0
            self.turn = 0
            self.players = []
            self.me = {}
            self.opp = {}

    @property
    def options(self) -> list[dict]:
        return self.select.get("option", [])

    @property
    def max_count(self) -> int:
        return self.select.get("maxCount", 1)

    @property
    def select_type(self) -> str:
        return str(self.select.get("type", ""))

    @property
    def select_context(self) -> str:
        return str(self.select.get("context", ""))

    # ── Board accessors ──────────────────────────────────────────

    def my_active(self) -> Optional[dict]:
        active = self.me.get("active")
        if isinstance(active, list):
            return active[0] if active else None
        return active

    def opp_active(self) -> Optional[dict]:
        active = self.opp.get("active")
        if isinstance(active, list):
            return active[0] if active else None
        return active

    def my_bench(self) -> list[dict]:
        return self.me.get("bench", []) or []

    def opp_bench(self) -> list[dict]:
        return self.opp.get("bench", []) or []

    def my_prizes(self) -> int:
        prizes = self.me.get("prize", [])
        return len(prizes) if prizes else 0

    def opp_prizes(self) -> int:
        prizes = self.opp.get("prize", [])
        return len(prizes) if prizes else 0

    def my_hand(self) -> list[dict]:
        return self.me.get("hand", []) or []

    def opp_hand_count(self) -> int:
        return self.opp.get("handCount", 0)

    def pokemon_hp(self, poke: dict) -> int:
        return poke.get("hp", 0)

    def pokemon_max_hp(self, poke: dict) -> int:
        return poke.get("maxHp", 0)

    def pokemon_card_id(self, poke: dict) -> int:
        return poke.get("id", 0)

    def pokemon_energy_count(self, poke: dict) -> int:
        return len(poke.get("energies", []) or [])

    def option_type(self, opt: dict) -> str:
        return str(opt.get("type", ""))

    def option_card_id(self, opt: dict) -> Optional[int]:
        card = opt.get("card")
        if isinstance(card, dict):
            return card.get("id")
        return None

    def option_damage(self, opt: dict) -> int:
        """Estimated damage for an ATTACK option."""
        return opt.get("damage", 0) or 0

    def get_card(self, card_id: int) -> Optional[Card]:
        return _cards().get(card_id)


# ─── Main agent ──────────────────────────────────────────────────────────────

class CabtAgent:
    def __init__(self, time_budget_s: float = 2.0):
        self.time_budget = time_budget_s
        self._game_step = 0

    def reset(self) -> None:
        self._game_step = 0

    def act(self, obs_dict: dict) -> list[int]:
        self._game_step += 1
        board = BoardView(obs_dict)
        n_options = len(board.options)

        if n_options == 0:
            return []
        if n_options == 1:
            return [0]

        ctx = board.select_context
        stype = board.select_type

        # Route to context-specific handler
        handler = self._route(ctx, stype)
        chosen = handler(board)

        # Clamp to valid range and correct count
        k = board.max_count
        chosen = [i for i in chosen if 0 <= i < n_options]
        if len(chosen) < k:
            remaining = [i for i in range(n_options) if i not in chosen]
            chosen += random.sample(remaining, min(k - len(chosen), len(remaining)))
        return chosen[:k]

    # ─── Context routing ─────────────────────────────────────────

    def _route(self, ctx: str, stype: str):
        routes = {
            "SETUP_ACTIVE_POKEMON":    self._choose_setup_active,
            "SETUP_BENCH_POKEMON":     self._choose_setup_bench,
            "ATTACK":                  self._choose_main_action,
            "MAIN":                    self._choose_main_action,
            "DISCARD_ENERGY_CARD":     self._choose_discard_energy,
            "DISCARD_CARD":            self._choose_discard_generic,
            "CHOOSE_POKEMON":          self._choose_pokemon_target,
            "BOSS_ORDERS":             self._choose_boss_target,
            "RETREAT_DESTINATION":     self._choose_retreat_destination,
            "PRIZE":                   self._choose_prize,
            "YES_NO":                  self._choose_yes_no,
            "DECK_SEARCH":             self._choose_deck_search,
        }
        return routes.get(ctx, self._choose_main_action)

    # ─── Setup phase ─────────────────────────────────────────────

    def _choose_setup_active(self, board: BoardView) -> list[int]:
        """Choose starting active Pokémon — pick highest HP Basic."""
        best_idx, best_hp = 0, -1
        for i, opt in enumerate(board.options):
            cid = board.option_card_id(opt)
            card = board.get_card(cid) if cid else None
            hp = card.hp if card else 0
            if hp > best_hp:
                best_hp, best_idx = hp, i
        return [best_idx]

    def _choose_setup_bench(self, board: BoardView) -> list[int]:
        """Fill bench with all available Basics."""
        k = board.max_count
        return list(range(min(k, len(board.options))))

    # ─── Main action ─────────────────────────────────────────────

    def _choose_main_action(self, board: BoardView) -> list[int]:
        """Score each option and pick the best."""
        scores = [self._score_option(board, i, opt)
                  for i, opt in enumerate(board.options)]
        best = max(range(len(scores)), key=lambda i: scores[i])
        return [best]

    def _score_option(self, board: BoardView, idx: int, opt: dict) -> float:
        otype = board.option_type(opt)

        if otype == "END":
            return -10.0

        if otype == "ATTACK":
            return self._score_attack(board, opt)

        if otype in ("PLAY", "SUPPORTER", "ITEM", "STADIUM"):
            return self._score_play(board, opt)

        if otype == "EVOLVE":
            return 60.0  # Always evolve when possible

        if otype == "ATTACH":
            return 50.0  # Attach energy — high priority

        if otype == "RETREAT":
            return self._score_retreat(board, opt)

        if otype == "ABILITY":
            return self._score_ability(board, opt)

        return 0.0

    def _score_attack(self, board: BoardView, opt: dict) -> float:
        opp = board.opp_active()
        if opp is None:
            return 10.0
        dmg = board.option_damage(opt)
        opp_hp = board.pokemon_hp(opp)

        # KO bonus
        if dmg >= opp_hp:
            prize_value = max(1, board.opp_prizes())
            return 500.0 + 100.0 / prize_value

        # Damage efficiency
        score = float(dmg)

        # Bench spread bonus (Phantom Dive style): check effect text
        attack_name = opt.get("attackName", "") or ""
        if "Benched" in opt.get("effect", ""):
            score += 30.0

        # Prefer high damage when ahead on prizes
        if board.my_prizes() < board.opp_prizes():
            score *= 1.2

        return score

    def _score_play(self, board: BoardView, opt: dict) -> float:
        cid = board.option_card_id(opt)
        card = board.get_card(cid) if cid else None
        if card is None:
            return 5.0

        # Supporter priority
        if card.stage == "Supporter":
            name = card.name
            if name == "Boss's Orders" and board.opp_bench():
                return 80.0
            if name in ("Iris's Fighting Spirit", "Lillie's Determination"):
                return 70.0
            if name == "Judge":
                return 55.0
            return 50.0

        # Item priority
        if card.stage == "Item":
            name = card.name
            if name == "Buddy-Buddy Poffin":
                return 75.0
            if name in ("Ultra Ball", "Master Ball"):
                return 65.0
            if name == "Rare Candy":
                return 72.0
            if name == "Night Stretcher":
                return 40.0
            if name == "Switch":
                active = board.my_active()
                if active and board.pokemon_hp(active) < board.pokemon_max_hp(active) * 0.3:
                    return 60.0  # flee when badly hurt
                return 15.0
            return 10.0

        return 5.0

    def _score_retreat(self, board: BoardView, opt: dict) -> float:
        active = board.my_active()
        if active is None:
            return 0.0
        hp_ratio = board.pokemon_hp(active) / max(board.pokemon_max_hp(active), 1)
        # Retreat if active is badly hurt
        if hp_ratio < 0.25:
            return 45.0
        return -5.0

    def _score_ability(self, board: BoardView, opt: dict) -> float:
        cid = board.option_card_id(opt)
        card = board.get_card(cid) if cid else None
        if card is None:
            return 5.0
        # Dusknoir Cursed Blast: 13 damage counters — very strong when needed
        if card.name == "Dusknoir":
            opp = board.opp_active()
            if opp and board.pokemon_hp(opp) <= 130:
                return 490.0  # KO assist
            return 100.0  # Still valuable for spreading
        # Lunatone draw: always good
        if card.name == "Lunatone":
            return 65.0
        return 20.0

    # ─── Non-main selections ─────────────────────────────────────

    def _choose_discard_energy(self, board: BoardView) -> list[int]:
        """When forced to discard energy, keep non-basic (special) ones."""
        k = board.max_count
        # Sort: discard basic energy first (index 0..n-1)
        return list(range(min(k, len(board.options))))

    def _choose_discard_generic(self, board: BoardView) -> list[int]:
        """Generic discard — choose lowest-value cards."""
        k = board.max_count
        return list(range(min(k, len(board.options))))

    def _choose_pokemon_target(self, board: BoardView) -> list[int]:
        """Choose Pokémon target — pick opponent's lowest HP non-active."""
        k = board.max_count
        opp_bench = board.opp_bench()
        if not opp_bench:
            return [0]
        # Pick weakest target
        scores = []
        for i, opt in enumerate(board.options):
            poke_data = opt.get("pokemon") or opt.get("card")
            if isinstance(poke_data, dict):
                hp = poke_data.get("hp", 999)
            else:
                hp = 999
            scores.append((hp, i))
        scores.sort()
        return [scores[j][1] for j in range(min(k, len(scores)))]

    def _choose_boss_target(self, board: BoardView) -> list[int]:
        """Boss's Orders — pull up opponent's most dangerous benched Pokémon."""
        best_idx, best_score = 0, -1
        for i, opt in enumerate(board.options):
            cid = board.option_card_id(opt)
            card = board.get_card(cid) if cid else None
            score = card.hp if card else 0
            if card and card.is_ex:
                score += 50  # prioritise pulling up ex with damage
            if score > best_score:
                best_score, best_idx = score, i
        return [best_idx]

    def _choose_retreat_destination(self, board: BoardView) -> list[int]:
        """Choose which bench Pokémon to bring up after retreating."""
        best_idx, best_score = 0, -1
        for i, opt in enumerate(board.options):
            cid = board.option_card_id(opt)
            card = board.get_card(cid) if cid else None
            if card is None:
                continue
            # Prefer Mega Lucario ex with most energy
            score = card.hp
            if card.name == "Mega Lucario ex":
                score += 200
            if best_score < score:
                best_score, best_idx = score, i
        return [best_idx]

    def _choose_prize(self, board: BoardView) -> list[int]:
        """Choose prize cards — always just pick first (face-down, no info)."""
        return [0]

    def _choose_yes_no(self, board: BoardView) -> list[int]:
        """YES/NO prompt — default YES for most beneficial effects."""
        ctx = board.select_context
        # Say NO to self-damaging or risky effects when not needed
        no_contexts = {"COIN_DISCARD", "SELF_DAMAGE"}
        if any(nc in ctx for nc in no_contexts):
            # Find NO option
            for i, opt in enumerate(board.options):
                if board.option_type(opt) == "NO":
                    return [i]
        # Default: YES
        for i, opt in enumerate(board.options):
            if board.option_type(opt) == "YES":
                return [i]
        return [0]

    def _choose_deck_search(self, board: BoardView) -> list[int]:
        """Deck search — pick the best card(s) for current situation."""
        k = board.max_count
        # Priority: Mega Lucario ex > Dusknoir > Riolu > Duskull > energy
        priority_names = [
            "Mega Lucario ex", "Dusknoir", "Riolu", "Duskull",
            "Lunatone", "Basic {F} Energy",
        ]
        chosen = []
        for target in priority_names:
            if len(chosen) >= k:
                break
            for i, opt in enumerate(board.options):
                if i in chosen:
                    continue
                cid = board.option_card_id(opt)
                card = board.get_card(cid) if cid else None
                if card and card.name == target:
                    chosen.append(i)
                    break
        # Fill remaining slots
        remaining = [i for i in range(len(board.options)) if i not in chosen]
        chosen += remaining[:k - len(chosen)]
        return chosen[:k]

    def opp_bench(self) -> list:
        return []
