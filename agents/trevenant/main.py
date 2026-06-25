"""Hop's Trevenant — single-prize aggro that trades up vs ex decks.
Sample-Style 2.0 policy on shared BasePolicy.

Gameplan:
  - Flood cheap 1-prize bodies, let them KO one, then Revenge for +100.
  - Choice Band (-1{C} cost +30 dmg) + Postwick (+30) + Snorlax Extra Helpings (+30)
    = up to +90 damage. Horrifying Revenge 30 + 100 revenge + 90 boost = 220 total.
  - Mist Energy prevents attack effects (but NOT damage).
  - Telepath Energy provides {P} AND searches 2 Basic {P} on attach.
  - Cramorant Fickle Spitting: 120 [C] when opp at 3-4 prizes.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from policy_base import (
    BasePolicy, make_agent, new_diag,
    card_table, attack_table, get_card, is_evolution, prize_count,
    ATTACK_COST_ENERGIES,
    AreaType, CardType, EnergyType, OptionType, Pokemon, SelectContext,
)

# ── Card IDs ────────────────────────────────────────────────────────────────
class C:
    PHANTUMP = 878        # Basic {P} 70HP -> Trevenant
    TREVENANT = 879       # Stage1 140HP
    SNORLAX = 304         # Basic 150HP, Extra Helpings (+30 Hop's dmg)
    CRAMORANT = 311       # Basic 110HP, Fickle Spitting 120 [C]
    MIST_ENERGY = 11      # {C} + prevents effects
    TELEPATH = 19         # {P} + on attach search 2 Basic {P} to bench
    SECRET_BOX = 1092     # discard 3, grab Item+Tool+Supporter+Stadium
    NIGHT_STRETCHER = 1097
    HOPS_BAG = 1115       # search 2 Basic Hop's -> bench
    POKEGEAR = 1122       # dig 7 for Supporter
    TRANSCEIVER = 1134    # search "Team Rocket" Supporter (-> Petrel)
    POKE_PAD = 1152       # search non-Rule-Box Pokémon -> hand
    CHOICE_BAND = 1171    # TOOL: -1{C} cost, +30 to Active
    BOSS = 1182
    PETREL = 1219         # search ANY Trainer -> hand
    HILDA = 1225          # search Evolution + Energy
    LILLIE_DET = 1227     # shuffle-draw 6(8)
    POSTWICK = 1255       # STADIUM: Hop's +30 to opp Active

HOPS_POKEMON = {C.PHANTUMP, C.TREVENANT, C.SNORLAX, C.CRAMORANT}

# Attack IDs
HORRIFYING_REVENGE = 1267  # 30 + 100 if revenge
CORNER = 1268              # 90 [P,C,C], no retreat
FICKLE_SPITTING = 433      # 120 [C], only at 3-4 opp prizes
DYNAMIC_PRESS = 422        # 140 [C,C,C], 80 self-dmg
SPLASHING_DODGE = 1266     # 10 [C], coin-flip

UNNECESSARY = -10000000

# ── revenge tracker (global across decisions, resets each game) ─────────────
_GAME = {"turn": -10, "mycount": None, "revenge": False}

# ── deck load ────────────────────────────────────────────────────────────────
def _resolve_deck_path():
    cands = [os.path.join(_HERE, "deck.csv"), "deck.csv", "/kaggle_simulations/agent/deck.csv"]
    cands += [os.path.join(p, "deck.csv") for p in sys.path if p]
    for p in cands:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("deck.csv not found")

with open(_resolve_deck_path()) as f:
    my_deck = [int(x) for x in f.read().splitlines() if x.strip()]
if len(my_deck) != 60:
    raise ValueError(f"deck.csv must have 60 ids, got {len(my_deck)}")

DIAG = new_diag()


# ── Policy ───────────────────────────────────────────────────────────────────
class TrevenantPolicy(BasePolicy):
    ENERGY_TYPES = {C.MIST_ENERGY, C.TELEPATH}
    ATTACKER_IDS = {C.TREVENANT, C.CRAMORANT}

    # GO SECOND: revenge deck wants the opponent to attack first (KO a Hop's),
    # then revenge on our first turn for +100. Measured against rank-1 Debauchery.
    def go_first(self):
        return False

    def _detect_archetype(self):
        """Detect opponent archetype from their visible board."""
        opp_ids = set()
        for p in self.opponent.active:
            if p: opp_ids.add(p.id)
        for p in self.opponent.bench:
            if p: opp_ids.add(p.id)
        if 119 in opp_ids or 235 in opp_ids:
            return 'dragapult'
        if 1030 in opp_ids:
            return 'megastarmie'
        if 673 in opp_ids:
            return 'lucario'
        if 400 in opp_ids or 431 in opp_ids:
            return 'mewtwo'
        if 878 in opp_ids:
            return 'trevenant_mirror'
        return 'unknown'

    # ── state collection ──────────────────────────────────────────────────────
    def _collect(self):
        self.stadium_id = self.state.stadium[0].id if self.state.stadium else 0
        self.active = self.me.active[0] if self.me.active else None
        self.opp = self.opponent.active[0] if self.opponent.active else None
        self.opp_prizes = len(self.opponent.prize)
        self.my_prizes = len(self.me.prize)

        # Board state
        self.has_snorlax = any(p is not None and p.id == C.SNORLAX for p in self.my_board())
        self.has_trevenant = any(p is not None and p.id == C.TREVENANT for p in self.my_board())
        self.trevenant_count = self.field[C.TREVENANT] + self.field[C.PHANTUMP]
        self.open_bench = sum(1 for p in self.me.bench if p is not None) < 5

        # Choice Band on our active?
        self.active_has_band = False
        if self.active is not None:
            tools = [getattr(t, 'id', t) for t in (getattr(self.active, 'tools', None) or [])]
            self.active_has_band = C.CHOICE_BAND in tools
        self.bench_attacker_ready = any(
            p is not None and p.id in self.ATTACKER_IDS and self.can_attack(p)
            for p in self.me.bench)

        # Postwick active?
        self.postwick_active = (self.stadium_id == C.POSTWICK)

        # Flat boost calculation (stacked +30s)
        self.flat_boost = 0
        if self.postwick_active:
            self.flat_boost += 30
        if self.active_has_band:
            self.flat_boost += 30
        if self.has_snorlax:
            self.flat_boost += 30

        # Revenge tracking
        self._update_revenge()

        # Need attacker pieces?
        self.need_attacker_pieces = self.trevenant_count < 2

        # ── matchup-aware strategy ─────────────────────────────────────────────
        if not hasattr(self, '_archetype'):
            self._archetype = self._detect_archetype()
            self._vs_spread = self._archetype in ('dragapult', 'megastarmie')
            self._vs_setup = self._archetype in ('mewtwo',)
        # Detect if spread is hitting our bench (dynamic)
        self._under_spread = False
        if self._vs_spread:
            for p in self.me.bench:
                if p is not None and p.hp < p.maxHp:
                    self._under_spread = True
                    break

    def _update_revenge(self):
        """Detect a Hop's KO during opponent's last turn = a drop in board count."""
        try:
            cur = sum(1 for p in self.my_board() if p is not None)
            t = self.state.turn
            if t < _GAME["turn"]:  # new game
                _GAME.update({"turn": -10, "mycount": None, "revenge": False})
            if t > _GAME["turn"]:
                prev = _GAME["mycount"]
                _GAME["revenge"] = (prev is not None and cur < prev)
                _GAME["mycount"] = cur
                _GAME["turn"] = t
        except Exception:
            pass
        self.revenge = _GAME.get("revenge", False)

    # ── provided_by: Telepath provides {P} ─────────────────────────────────────
    def provided_by(self, src, target):
        if src is not None and src.id == C.TELEPATH:
            return [EnergyType.PSYCHIC]
        if src is not None and src.id == C.MIST_ENERGY:
            return [EnergyType.COLORLESS]
        return super().provided_by(src, target)

    # ── damage helpers ─────────────────────────────────────────────────────────
    def _dmg_raw(self, aid, target):
        if target is None:
            return 0
        if aid == HORRIFYING_REVENGE:
            return 30 + (100 if self.revenge else 0) + self.flat_boost
        if aid == CORNER:
            return 90 + self.flat_boost
        if aid == FICKLE_SPITTING:
            return 120 if self.opp_prizes in (3, 4) else 0
        if aid == DYNAMIC_PRESS:
            return 140 + self.flat_boost
        if aid == SPLASHING_DODGE:
            return 10
        return 0

    def _best_attacks(self, p, target):
        """(aid, dmg) for each payable attack against target."""
        results = []
        for aid in self.payable_attacks(p):
            d = self._dmg_raw(aid, target)
            results.append((aid, d))
        return results

    # ── hand_score — per-card explicit scores ─────────────────────────────────
    def hand_score(self, cid, ignore_count=False):
        # Archetype-based adjustments
        vs_spread = getattr(self, '_vs_spread', False)
        vs_setup = getattr(self, '_vs_setup', False)

        # ── Pokémon ──
        if cid == C.PHANTUMP:
            if self.trevenant_count + self.hand[C.PHANTUMP] >= 4:
                return UNNECESSARY
            if self.trevenant_count == 0:
                return 20000   # must have first body
            if self.trevenant_count == 1:
                if vs_spread:
                    return 8000    # vs spread: don't flood bench with 70HP bodies
                return 15000
            return 5000 if not vs_spread else 2000
        if cid == C.TREVENANT:
            if self.has_trevenant:
                return 3000
            if self.field[C.PHANTUMP] > 0:
                return 27000 if vs_spread else 25000
            return 8000
        if cid == C.SNORLAX:
            if not self.has_snorlax:
                return 19000 if vs_spread else 16000
            return 500
        if cid == C.CRAMORANT:
            if vs_spread:
                return 5000 if vs_spread else 10000
            if self.field[C.CRAMORANT] == 0:
                return 10000
            return 1000

        # ── Setup / Search Items ──
        if cid == C.HOPS_BAG:
            if vs_spread and self.trevenant_count >= 1:
                return 3000
            if self.open_bench and self.need_attacker_pieces:
                return 18000
            if self.open_bench:
                return 6000
            return 500
        if cid == C.POKE_PAD:
            need = self.field[C.PHANTUMP] > 0 and not self.has_trevenant and self.hand[C.TREVENANT] == 0
            return 15000 if need else 6000
        if cid == C.POKEGEAR:
            if self.state.supporterPlayed:
                return 500
            return 8000
        if cid == C.TRANSCEIVER:
            if not self.state.supporterPlayed:
                return 14000
            return 4000
        if cid == C.PETREL:
            if self.state.supporterPlayed:
                return 500
            return 12000
        if cid == C.NIGHT_STRETCHER:
            need = (self.discard.get(C.TREVENANT, 0) > 0 or self.discard.get(C.PHANTUMP, 0) > 0
                    or self.discard.get(C.SNORLAX, 0) > 0)
            return 8000 if need else 1500
        if cid == C.SECRET_BOX:
            if self.me.handCount >= 5:
                return 12000 if vs_setup else 10000  # faster toolbox vs setup decks
            return -1

        # ── Supporters ──
        if cid == C.LILLIE_DET:
            if self.state.supporterPlayed:
                return UNNECESSARY
            if self.me.deckCount <= 2:
                return UNNECESSARY
            return 14000 if self.me.handCount <= 4 else 4000
        if cid == C.HILDA:
            if self.state.supporterPlayed:
                return UNNECESSARY
            if self.need_attacker_pieces or not self.has_trevenant:
                return 15000
            return 4000
        if cid == C.BOSS:
            if self.state.supporterPlayed:
                return UNNECESSARY
            # Check if our active can KO a benched target after gust
            if self.active is not None:
                for p in self.opponent.bench:
                    if p is None:
                        continue
                    best = max((d for _, d in self._best_attacks(self.active, p)), default=0)
                    if best >= p.hp:
                        bonus = prize_count(p) * 300
                        if vs_setup: bonus += 2000  # rush: gust for KO ASAP
                        return 18000 + bonus
            return 500

        # ── Tool / Stadium ──
        if cid == C.CHOICE_BAND:
            priority = 22000 if vs_setup else 20000  # even more urgent vs setup
            if self.active is not None and not self.active_has_band:
                return priority
            for p in self.me.bench:
                if p is not None and p.id in self.ATTACKER_IDS:
                    tools = [getattr(t, 'id', t) for t in (getattr(p, 'tools', None) or [])]
                    if C.CHOICE_BAND not in tools:
                        return 15000
            return 5000
        if cid == C.POSTWICK:
            if self.stadium_id == C.POSTWICK:
                return 200
            if self.state.stadiumPlayed:
                return 200
            return 13000       # +30 to ALL our attacks

        # ── Energy ──
        if self.is_energy(cid):
            # Check if any attacker needs fuel
            for p in self.my_board():
                if p is not None and p.id in self.ATTACKER_IDS and self.should_fuel(p):
                    return 12000
            # Pre-load a Phantump for evolution
            for p in self.my_board():
                if p is not None and p.id == C.PHANTUMP and self.should_fuel(p):
                    return 8000
            return 1000

        return 500

    # ── Override score() to collect state first ────────────────────────────────
    def score(self, o):
        self._collect()
        return super().score(o)

    # ── score_play → hand_score ────────────────────────────────────────────────
    def score_play(self, o):
        card = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        if card is None:
            return 0
        return self.hand_score(card.id)

    def score_play_poke(self, card):
        return self.hand_score(card.id)
    def score_play_trainer(self, card):
        return self.hand_score(card.id)

    # ── ATTACH (Choice Band as tool, energy gated by should_fuel) ──────────────
    def score_attach(self, o):
        p = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
        if not isinstance(p, Pokemon):
            return 0
        src = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        is_active = o.inPlayArea == AreaType.ACTIVE

        # Choice Band (TOOL)
        if src is not None and src.id == C.CHOICE_BAND:
            if p.id in self.ATTACKER_IDS and not self.active_has_band:
                return 18000 + (500 if is_active else 0)
            return -1

        # Energy
        if not self.should_fuel(p):
            return -1
        base = 7000 if p.id == C.TREVENANT else 5000 if p.id == C.PHANTUMP else 2000
        if is_active:
            base += 300
        return base

    # ── ABILITY (Snorlax Extra Helpings is passive) ────────────────────────────
    def score_ability(self, o):
        return 5000

    # ── EVOLVE ─────────────────────────────────────────────────────────────────
    def score_evolve(self, o):
        target = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
        if not isinstance(target, Pokemon):
            return 0
        card = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        cid = card.id if card is not None else None
        if cid == C.TREVENANT:
            return 22000 + (400 if o.inPlayArea == AreaType.ACTIVE else 0)
        return 0

    def score_evolves_choice(self, card):
        if card is None:
            return 1000
        if card.id in (C.TREVENANT, C.PHANTUMP):
            return 3000
        return 1000

    # ── ATTACK ─────────────────────────────────────────────────────────────────
    def score_attack(self, o):
        active = self.active
        opp = self.opp
        if active is None or opp is None:
            return 800
        aid = o.attackId
        dmg = self._dmg_raw(aid, opp)

        # If we need Cramorant's prize condition
        if aid == FICKLE_SPITTING and self.opp_prizes not in (3, 4):
            return 200  # does nothing right now

        # Self-damage check for Dynamic Press
        if aid == DYNAMIC_PRESS:
            if dmg >= opp.hp:
                if prize_count(opp) >= self.my_prizes:
                    return 95000
                return 3000 + min(dmg, 320)
            return 500

        if dmg <= 0:
            return 400
        # Game-winning KO
        if opp.hp <= dmg and prize_count(opp) >= self.my_prizes:
            return 95000

        score = 1000 + min(dmg, 320)
        if opp.hp <= dmg:
            score += 3000 + prize_count(opp) * 300
            if prize_count(opp) >= 2:
                score += 2000    # trading 1-prize for 2-prize is the whole point
        if aid == CORNER:
            score += 200         # no-retreat lock is nice
        if aid == HORRIFYING_REVENGE and self.revenge:
            score += 500         # revenge is active
        return score

    # ── Sub-select scorers ─────────────────────────────────────────────────────
    def score_spread_target(self, card):
        """Trevenant doesn't spread — return 0 (no-op)."""
        return 0

    def score_active_choice(self, o, card):
        if not isinstance(card, Pokemon):
            return 0
        if o.playerIndex == self.op_index:
            return self.gust_value(card)
        if o.playerIndex != self.my_index:
            return 0
        # Promote: Trevenant (attacker) > Snorlax (wall) > Cramorant (pivot) > Phantump
        opp = self.opp
        score = len(card.energies) * 8
        if card.id == C.TREVENANT:
            score += 300
            if opp is not None:
                d = max((self._dmg_raw(aid, opp) for aid in self.payable_attacks(card)), default=0)
                if d >= opp.hp:
                    score += 500
        elif card.id == C.SNORLAX:
            score += 200 if getattr(self, '_vs_spread', False) else 30
        elif card.id == C.CRAMORANT:
            score += 150 + (120 if self.opp_prizes in (3, 4) else 0)
        elif card.id == C.PHANTUMP:
            score += 110
        score += getattr(card, 'hp', 0) // 30
        return score + 1

    def score_setup_active(self, card):
        if card is None:
            return 0
        if card.id == C.SNORLAX:
            return 55 if getattr(self, '_vs_spread', False) else 15  # vs spread: wall first
        if card.id == C.PHANTUMP:
            return 50 if not getattr(self, '_vs_spread', False) else 20
        if card.id == C.CRAMORANT:
            return 20
        return 5

    def score_to_bench(self, card):
        if card is None:
            return 0
        d = card_table.get(card.id)
        if d is None or d.cardType != CardType.POKEMON:
            return 0
        cid = card.id; n = self.field[cid]
        if cid == C.PHANTUMP:
            return 200 - 25 * n
        if cid == C.SNORLAX:
            return 180 if n == 0 else 20
        if cid == C.CRAMORANT:
            return 150 - 25 * n
        if cid == C.TREVENANT:
            return 160 - 30 * n
        return 100 - 20 * n

    def score_to_hand(self, card):
        if card is None:
            return 0
        cid = card.id
        score = 200 - self.hand[cid] * 30
        if cid == C.CHOICE_BAND:
            score += 120 if self.hand.get(C.CHOICE_BAND, 0) == 0 else 25
        elif cid == C.SECRET_BOX:
            score += 130 if self.me.handCount >= 5 else 70
        elif cid == C.HILDA:
            score += 100 if self.need_attacker_pieces else 78
        elif cid == C.HOPS_BAG:
            score += 95 if (self.need_attacker_pieces or self.open_bench) else 40
        elif cid == C.LILLIE_DET:
            score += 80
        elif cid == C.TREVENANT:
            score += 82 if self.field[C.PHANTUMP] else 20
        elif cid == C.PHANTUMP:
            score += 60 if self.trevenant_count < 2 else 15
        elif cid == C.SNORLAX:
            score += 35 if not self.has_snorlax else -20
        elif self.is_energy(cid):
            score += 45
        return score

    def score_discard(self, card):
        if card is None:
            return 0
        cid = card.id
        if self.is_energy(cid):
            return 25 if self.hand[cid] >= 3 else -40
        if self.hand[cid] >= 3:
            return 60
        if cid == C.HOPS_BAG:
            return -30 if (self.need_attacker_pieces and self.open_bench) else 50
        if cid in (C.LILLIE_DET, C.HILDA, C.SECRET_BOX):
            return -45   # keep the draw/search engines
        if cid in (C.TREVENANT, C.PHANTUMP, C.SNORLAX):
            return -50 if self.field[cid] == 0 else 5
        if cid == C.CHOICE_BAND:
            return 22 if self.hand[cid] >= 2 else 8
        if cid == C.POSTWICK:
            return 45 if self.stadium_id == C.POSTWICK else 14
        if cid == C.CRAMORANT and self.opp_prizes not in (3, 4):
            return 40
        return 12

    def score_putback(self, card):
        if card is None:
            return 0
        if self.hand[card.id] >= 2:
            return 60
        if card.id in (C.TREVENANT, C.PHANTUMP, C.CHOICE_BAND):
            return -40
        return 10


# ── agent entry point ──────────────────────────────────────────────────────
_impl = make_agent(TrevenantPolicy, my_deck, DIAG)


def agent(obs_dict):
    return _impl(obs_dict)
