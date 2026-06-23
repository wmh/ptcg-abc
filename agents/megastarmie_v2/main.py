"""Mega Starmie ex + Cinderace (clone of ladder #1 keidroid). Thin deck-specific subclass of the
shared BasePolicy — the generic energy discipline (no over-fill), dispatch, and robust agent
wrapper are INHERITED from policy_base; only this deck's scoring lives here."""
from __future__ import annotations

import os
import sys

# The Kaggle/cabt loader appends the agent dir to sys.path so sibling imports work; add it here
# too for direct/test imports. (__file__ is absent under the loader, so guard it.)
_HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from policy_base import (  # noqa: E402
    BasePolicy, make_agent, new_diag,
    card_table, attack_table, get_card, is_evolution, prize_count,
    ATTACK_COST, ATTACK_COST_ENERGIES,
    AreaType, CardType, EnergyType, OptionType, Pokemon, SelectContext,
)


# ── Card IDs (Mega Starmie ex + Cinderace toolbox) ───────────────────────────
class C:
    STARYU = 1030          # Basic {W} -> Mega Starmie ex
    MEGA_STARMIE = 1031    # Stage1 MegaEx {W}, 330HP, 3 prizes. Jetting Blow [W]=120+50 bench;
                           #   Nebula Beam [CCC]=210 ignoring weakness/resistance + opp effects.
    CINDERACE = 666        # Stage2 {Fire}. Explosiveness: open face-down active during setup.
                           #   Turbo Flare [C]=50 + search 3 Basic Energy to bench (accel).
    WATER_ENERGY = 3       # Basic {W} (x9) — permanent build-up
    IGNITION_ENERGY = 17   # Special: {C}, or {C}{C}{C} on an EVOLUTION; DISCARDED end of turn
    POKEGEAR = 1122
    MEGA_SIGNAL = 1145
    BUDDY_POFFIN = 1086
    CRUSHING_HAMMER = 1120
    SALVATORE = 1189
    BOSS_ORDERS = 1182
    WALLY = 1229
    HILDA = 1225
    LILLIE = 1227
    HARLEQUIN = 1223
    NIGHT_STRETCHER = 1097
    HEROS_CAPE = 1159
    ULTRA_BALL = 1121


# resolve our attack IDs by name (deck-local)
JETTING_BLOW = NEBULA_BEAM = WATER_GUN = TURBO_FLARE = None
for _c in (card_table.get(C.MEGA_STARMIE), card_table.get(C.STARYU), card_table.get(C.CINDERACE)):
    for _aid in (getattr(_c, 'attacks', None) or []):
        _a = attack_table.get(_aid)
        nm = (getattr(_a, 'name', '') or '').lower()
        if _c.cardId == C.MEGA_STARMIE and 'jetting' in nm:
            JETTING_BLOW = _aid
        elif _c.cardId == C.MEGA_STARMIE and 'nebula' in nm:
            NEBULA_BEAM = _aid
        elif _c.cardId == C.STARYU and 'water gun' in nm:
            WATER_GUN = _aid
        elif _c.cardId == C.CINDERACE and ('turbo' in nm or 'flare' in nm):
            TURBO_FLARE = _aid


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


# ── policy ───────────────────────────────────────────────────────────────────
class MegaStarmiePolicy(BasePolicy):
    ENERGY_TYPES = {C.WATER_ENERGY, C.IGNITION_ENERGY}
    ATTACKER_IDS = {C.MEGA_STARMIE, C.CINDERACE}

    # GO FIRST — measured: keidroid 27/27 (deck-specific; setup deck wants the extra turn).
    def go_first(self):
        return True

    # Ignition Energy provides {C}{C}{C} on an EVOLUTION mon (so should_fuel/attach_helps account
    # for it correctly); base provision otherwise.
    def provided_by(self, src, target):
        if src is not None and src.id == C.IGNITION_ENERGY:
            return [EnergyType.COLORLESS] * (3 if is_evolution(target.id) else 1)
        return super().provided_by(src, target)

    # —— attach: special-case the EOT-discard Ignition (Nebula finisher), else inherit the generic
    #    should_fuel-gated build-up (over-fill-proof). ——
    def score_attach(self, o):
        p = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
        if not isinstance(p, Pokemon):
            return 0
        src = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        is_active = o.inPlayArea == AreaType.ACTIVE
        if src is not None and src.id == C.IGNITION_ENERGY:
            # Ignition is discarded end-of-turn -> a one-shot Nebula Beam ENABLER, never build-up.
            if not (is_active and p.id == C.MEGA_STARMIE):
                return -1
            if NEBULA_BEAM in ATTACK_COST_ENERGIES and self.can_pay(
                    list(p.energies or []), ATTACK_COST_ENERGIES[NEBULA_BEAM]):
                return -1                      # already Nebula-ready -> don't burn a 2nd Ignition
            opp = self.opponent.active[0] if self.opponent.active else None
            if not self.can_attack(p):
                return 9500                    # gets the active attacking this turn at all
            # v2: TIGHTER — keidroid keeps Ignition for the cases Jetting Blow's spread can't solve,
            # not every 121-210 HP target. Use it only to pierce an effect-protected active, or to
            # KO a MULTI-PRIZE ex that Jetting Blow's 120 can't (210 does). Single-prize targets ->
            # just Jetting Blow (the +50 bench spread advances the multi-prize plan).
            if opp is not None and self.effect_prevented(opp):
                return 9300
            if opp is not None and prize_count(opp) >= 2 and 120 < opp.hp <= 210:
                return 9200
            return -1                          # Jetting Blow is enough -> save the Ignition
        return super().score_attach(o)         # Water build-up: generic, gated by should_fuel

    def attach_priority(self, p, is_active):
        concentrate = self.energy_count(p) * 600
        if p.id == C.MEGA_STARMIE:
            return 9000 + concentrate + (300 if is_active else 0)
        if p.id == C.CINDERACE:
            return 6000 + concentrate + (200 if is_active else 0)
        if p.id == C.STARYU:
            return 1500 + concentrate          # pre-fuel; carries through the evolution
        return -1

    # —— abilities ——
    def score_ability(self, o):
        card = get_card(self.obs, o.area, o.index, self.my_index)
        if card is not None and card.id == C.CINDERACE:
            return 12000                       # Explosiveness: open this Stage-2 in the Active Spot
        return 9000

    # —— play ——
    def score_play_poke(self, card):
        cid = card.id; n = self.field[cid]
        if cid == C.STARYU:
            return 20000 - 400 * n
        if cid == C.CINDERACE:
            return 18000 - 400 * n
        return 12000 - 300 * n

    def _open_bench(self):
        return sum(1 for p in self.me.bench if p is not None) < 5

    def _have_mega(self):
        return any(p is not None and p.id == C.MEGA_STARMIE for p in self.my_board())

    def _gust_ko_available(self):
        active = self.me.active[0] if self.me.active else None
        if active is None or active.id not in self.ATTACKER_IDS:
            return False
        atks = self.payable_attacks(active)
        for p in self.opponent.bench:
            if p is None:
                continue
            dmg = max((self._dmg(aid, p) for aid in atks), default=0)
            if dmg >= p.hp and prize_count(p) >= 2:
                return True
        return False

    def score_play_trainer(self, card):
        cid = card.id
        opp = self.opponent.active[0] if self.opponent.active else None
        active = self.me.active[0] if self.me.active else None
        have_mega_in_hand = self.hand[C.MEGA_STARMIE] > 0
        staryu_on_board = self.field[C.STARYU] > 0
        if cid == C.MEGA_SIGNAL:
            return 16000 if (staryu_on_board and not have_mega_in_hand) else 200
        if cid == C.SALVATORE:
            return 15500 if (staryu_on_board and have_mega_in_hand) else 150
        if cid == C.BUDDY_POFFIN:
            line = self.field[C.STARYU] + self.field[C.MEGA_STARMIE]
            if self._open_bench() and line == 0:
                return 15000
            if self._open_bench() and line == 1:
                return 6000
            return 300
        if cid == C.HILDA:
            return 14000 if (not self._have_mega() or not self.have_ready_attacker()) else 2000
        if cid == C.ULTRA_BALL:
            return 13000 if ((staryu_on_board and not have_mega_in_hand) or not self.my_board()) else 1000
        if cid == C.WALLY:
            for p in self.my_board():
                if p is not None and p.id == C.MEGA_STARMIE and (p.maxHp - p.hp) >= 120:
                    return 17000
            return 100
        if cid == C.CRUSHING_HAMMER:
            # v2: disrupt MORE proactively — keidroid plays Crushing Hammer far more than we do
            # (a core part of his tempo: strip the opponent's energy while we build/attack).
            return 8000 if (opp is not None and len(opp.energies) >= 1) else 200
        if cid == C.BOSS_ORDERS:
            return 14500 if self._gust_ko_available() else 300
        if cid == C.NIGHT_STRETCHER:
            return 6000 if (self.discard.get(C.MEGA_STARMIE, 0) or self.discard.get(C.STARYU, 0)) else 800
        if cid == C.POKEGEAR:
            return 7000 if not self.state.supporterPlayed else 500
        if cid in (C.LILLIE, C.HARLEQUIN):
            if self.state.supporterPlayed:
                return 100
            base = 8000 if cid == C.LILLIE else 5000
            if self.me.handCount <= 3:
                base += 2000
            elif self.me.handCount >= 7:
                base -= 4000
            return base
        if cid == C.HEROS_CAPE:
            if active is not None and active.id == C.MEGA_STARMIE and not (active.tools or []):
                return 9000
            return 200
        return 1000

    # —— evolve ——
    def score_evolve(self, o):
        target = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
        if not isinstance(target, Pokemon):
            return 0
        card = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        cid = card.id if card is not None else None
        if cid == C.MEGA_STARMIE:
            return 22000
        if cid == C.CINDERACE:
            return 18000
        return 16000

    def score_evolves_choice(self, card):
        if card is None:
            return 1000
        if card.id in (C.MEGA_STARMIE, C.STARYU):
            return 3000
        if card.id == C.CINDERACE:
            return 2000
        return 1000

    # —— attack ——
    def _dmg(self, attack_id, target):
        if target is None or attack_id is None:
            return 0
        if attack_id == NEBULA_BEAM:
            return 210                         # ignores weakness/resistance + opp effects
        if attack_id == JETTING_BLOW:
            dmg = 120
            d = card_table.get(target.id)
            if d and d.weakness == EnergyType.WATER:
                dmg *= 2
            return dmg
        a = attack_table.get(attack_id)
        base = getattr(a, 'damage', 0) or 0
        d = card_table.get(target.id)
        if d and base and d.weakness == EnergyType.WATER and attack_id == WATER_GUN:
            base *= 2
        return base

    def score_attack(self, o):
        active = self.me.active[0] if self.me.active else None
        opp = self.opponent.active[0] if self.opponent.active else None
        if active is None or opp is None:
            return 800
        aid = o.attackId
        dmg = self._dmg(aid, opp)
        if dmg > 0 and opp.hp <= dmg and prize_count(opp) >= len(self.me.prize):
            return 95000                       # lethal that wins the game now
        if aid == TURBO_FLARE:
            accel = 3000 if not self.have_ready_attacker() else 0
            return 1200 + accel + min(dmg, 50)
        if dmg <= 0:
            return 500
        score = 1000 + min(dmg, 320)
        # v2: Jetting Blow is the WORKHORSE — its +50 bench spread pre-loads multi-prize turns
        # (keidroid's main attack). Favor it over Nebula for non-KO hits; Nebula still wins when it
        # uniquely KOs (the KO bonus below). Was: Nebula +1500 auto-preferred.
        if aid == NEBULA_BEAM:
            score += 300
        if aid == JETTING_BLOW:
            score += 600
            if sum(1 for p in self.opponent.bench if p is not None) >= 2:
                score += 400               # spread is worth more vs a developed bench
        if opp.hp <= dmg:
            score += 2500 + prize_count(opp) * 250
        return score

    # —— sub-selects (deck-specific overrides; spread targeting uses the base default) ——
    def score_active_choice(self, o, card):
        if not isinstance(card, Pokemon):
            return 0
        if o.playerIndex == self.op_index:
            return self.gust_value(card)
        if o.playerIndex != self.my_index:
            return 0
        score = len(card.energies) * 10
        if card.id == C.MEGA_STARMIE:
            score += 300
        elif card.id == C.CINDERACE:
            score += 120
        elif card.id == C.STARYU:
            score += 40
        score += getattr(card, 'hp', 0) // 30
        return score + 1

    def score_setup_active(self, card):
        if card is None:
            return 0
        if card.id == C.CINDERACE:
            return 50                          # Explosiveness: can open AND attack/accelerate T1
        if card.id == C.STARYU:
            return 30
        return 5

    def score_to_bench(self, card):
        if card is None:
            return 0
        d = card_table.get(card.id)
        if d is None or d.cardType != CardType.POKEMON:
            return 0
        cid = card.id; n = self.field[cid]
        if cid == C.STARYU:
            return 200 - 40 * n
        if cid == C.CINDERACE:
            return 150 - 40 * n
        return 100 - 20 * n

    def score_to_hand(self, card):
        if card is None:
            return 0
        cid = card.id
        score = 200 - self.hand[cid] * 40
        if cid == C.MEGA_STARMIE:
            score += 90 if (self.field[C.STARYU] >= 1 and self.hand[C.MEGA_STARMIE] == 0) else 20
        elif cid == C.STARYU:
            score += 70 if self.field[C.STARYU] + self.hand[C.STARYU] < 2 else -10
        elif cid == C.CINDERACE:
            score += 50
        elif self.is_energy(cid):
            need_fuel = any(p is not None and p.id == C.MEGA_STARMIE and self.should_fuel(p)
                            for p in self.my_board())
            score += 250 if (need_fuel and cid == C.IGNITION_ENERGY) else 40
        return score

    def score_discard(self, card):
        if card is None:
            return 0
        cid = card.id
        if cid == C.WATER_ENERGY:
            return 80                          # plentiful (9 in deck) -> the preferred pitch
        if cid == C.IGNITION_ENERGY:
            return 30 if self.hand[cid] >= 2 else -30
        if self.is_energy(cid):
            return 40
        if cid == C.MEGA_STARMIE:
            return -200                        # never pitch the win-con
        if cid in (C.STARYU, C.SALVATORE, C.MEGA_SIGNAL):
            return -100 if self.hand[cid] <= 1 else 0
        if cid == C.CINDERACE:
            return -40 if self.field[cid] == 0 else 10
        if self.hand[cid] >= 2:
            return 60
        return 0

    def score_putback(self, card):
        if card is None:
            return 0
        if self.hand[card.id] >= 2:
            return 60
        if card.id in (C.STARYU, C.MEGA_STARMIE, C.CINDERACE):
            return -40
        return 10


_impl = make_agent(MegaStarmiePolicy, my_deck, DIAG)


def agent(obs_dict):
    # Thin wrapper defined in main.py so my_deck lives in this module's globals (deck-load
    # sanity checks read agent.__globals__['my_deck']); delegates to the shared wrapper.
    return _impl(obs_dict)
