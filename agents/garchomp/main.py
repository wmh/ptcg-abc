"""Cynthia's Garchomp ex — full policy (Phase 3, 2026-07-06).
Deck = ladder #7 nasuo445's exact 60 (the best-positioned deck of the 7-05 meta:
60.1% top-tier WR, beats Grimmsnarl 68% / Kangaskhan 60%).

Engine: Gabite *Champion's Call* (free Cynthia's search every turn) feeds
Garchomp ex — Corkscrew Dive [F]=100 + refill hand to 6 is the 1-energy
workhorse; Draconic Buster [FF]=260 (discard all energy) is the on-demand
finisher; Roserade's *Cheer On to Glory* adds +30 to both. Garchomp retreats
free. Rock Fighting Energy blocks attack effects on the holder.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from policy_base import (
    BasePolicy, make_agent, new_diag,
    card_table, attack_table, get_card, prize_count,
    ATTACK_COST_ENERGIES,
    AreaType, CardType, EnergyType, OptionType, Pokemon, SelectContext,
)

# ── Card IDs ────────────────────────────────────────────────────────────────
class C:
    GIBLE = 379            # Basic {F} 70HP -> Gabite
    GABITE = 380           # Stage1 {F} 100HP, Champion's Call: search a Cynthia's mon -> hand
    GARCHOMP = 381         # Stage2 ex {F} 330HP, 2 prizes, RETREAT 0, weak {G}
    ROSELIA = 341          # Basic {G} 70HP -> Roserade
    ROSERADE = 342         # Stage1 {G} 130HP, Cheer On to Glory: our attacks +30
    SPIRITOMB = 387        # Basic 70HP, Raging Curse: 10 x counters on OUR benched Cynthia's
    # Items
    BUDDY_POFFIN = 1086    # 2 basics <=70HP -> bench (Gible/Roselia/Spiritomb)
    FIGHTING_GONG = 1142   # search a Basic {F} Energy OR Basic {F} mon (Gible) -> hand
    POKE_PAD = 1152        # search a non-Rule-Box mon (NOT Garchomp ex)
    NIGHT_STRETCHER = 1097 # recover mon/basic energy from discard
    UNFAIR_STAMP = 1080    # after our mon was KO'd: both shuffle hands, we draw 5 / opp 2
    # Supporters
    HILDA = 1225           # search Evolution + Energy (Garchomp + F!)
    LILLIE = 1227          # shuffle-draw 6 (8 at exactly 6 prizes)
    BOSS = 1182            # gust
    SURFER = 1203          # switch active->bench, then draw to 5
    XEROSIC = 1197         # opp discards down to 3 cards
    # Tool / Stadium
    POWER_WEIGHT = 1173    # Cynthia's mon +70HP (Garchomp -> 400)
    FOREST = 1261          # Stadium: {G} mons may evolve the turn they're played
    # Energy
    F_ENERGY = 6           # Basic {F} x5
    ROCK_FIGHTING = 20     # {F} + prevents effects of opp attacks on the holder, x4

# Attack IDs (resolved from card data, never hardcoded)
CORKSCREW_DIVE = DRACONIC_BUSTER = RAGING_CURSE = None
for _aid in (card_table[C.GARCHOMP].attacks or []):
    _nm = (getattr(attack_table.get(_aid), 'name', '') or '').lower()
    if 'corkscrew' in _nm:
        CORKSCREW_DIVE = _aid
    elif 'buster' in _nm:
        DRACONIC_BUSTER = _aid
for _aid in (card_table[C.SPIRITOMB].attacks or []):
    if 'curse' in (getattr(attack_table.get(_aid), 'name', '') or '').lower():
        RAGING_CURSE = _aid

UNNECESSARY = -10000000

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
class GarchompPolicy(BasePolicy):
    ENERGY_TYPES = {C.F_ENERGY, C.ROCK_FIGHTING}
    ATTACKER_IDS = {C.GARCHOMP}

    def go_first(self):
        return True   # verify vs nasuo445's IS_FIRST once mined

    # ── derived state ──────────────────────────────────────────────────────
    def _collect(self):
        self.chomp_line = self.field[C.GIBLE] + self.field[C.GABITE] + self.field[C.GARCHOMP]
        self.chomp_on_board = self.field[C.GARCHOMP] > 0
        self.gabite_on_board = self.field[C.GABITE] > 0
        self.roserade_on_board = self.field[C.ROSERADE] > 0
        self.rose_line = self.field[C.ROSELIA] + self.field[C.ROSERADE]
        self.bench_body_count = sum(1 for p in self.me.bench if p is not None)
        self.open_bench = self.bench_body_count < 5
        self.basic_emergency = (self.bench_body_count == 0
                                and self.hand[C.GIBLE] == 0 and self.hand[C.ROSELIA] == 0
                                and self.hand[C.SPIRITOMB] == 0)
        self.opp = self.opponent.active[0] if self.opponent.active else None
        self.active = self.me.active[0] if self.me.active else None
        self.dmg_bonus = 30 if self.roserade_on_board else 0

    def score(self, o):
        self._collect()
        return super().score(o)

    # ── damage model ────────────────────────────────────────────────────────
    def _atk_dmg(self, aid, target):
        """Damage vs the ACTIVE target incl. Roserade's +30 and weakness."""
        if target is None or aid is None:
            return 0
        a = attack_table.get(aid)
        base = (getattr(a, 'damage', 0) or 0)
        if base <= 0 and aid != RAGING_CURSE:
            return 0
        d = card_table.get(target.id)
        dmg = base + self.dmg_bonus
        if d is not None and d.weakness == EnergyType.FIGHTING:
            dmg *= 2
        return dmg

    def _buster_worth_it(self):
        """A 2nd energy on the active Garchomp is only for Draconic Buster: pay the
        discard-all cost when Buster KOs something Corkscrew (100+30) cannot."""
        if self.opp is None:
            return False
        cork = self._atk_dmg(CORKSCREW_DIVE, self.opp)
        bust = self._atk_dmg(DRACONIC_BUSTER, self.opp)
        return cork < self.opp.hp <= bust

    # ── hand_score (MAIN PLAY) ───────────────────────────────────────────────
    def hand_score(self, cid):
        # nasuo445 (12693 MAIN decisions): this deck WANTS a big bench — damaged benched
        # Cynthia's feed Spiritomb's Raging Curse, and bodies are all 1-prize.
        if cid == C.GIBLE:
            if self.chomp_line == 0:
                return 20000
            if self.chomp_line == 1:
                return 12000
            return 6000 if self.open_bench else 400
        if cid == C.ROSELIA:
            if self.rose_line == 0:
                return 11000   # one Roserade enables the permanent +30
            return 5500 if self.open_bench else 400
        if cid == C.SPIRITOMB:
            if self.field[C.SPIRITOMB] == 0 and self.chomp_line >= 1:
                return 8000    # the 2nd attacker (Raging Curse)
            return 4000 if (self.field[C.SPIRITOMB] <= 1 and self.open_bench) else 400

        if cid == C.BUDDY_POFFIN:
            if not self.open_bench:
                return UNNECESSARY
            if self.basic_emergency:
                return 20000
            if self.chomp_line == 0 or (self.chomp_line <= 1 and self.rose_line == 0):
                return 16000
            return 12000 if self.bench_body_count <= 3 else UNNECESSARY  # nasuo keeps benching
        if cid == C.FIGHTING_GONG:
            starved = (not any(self.energy_count(p) > 0 for p in self.my_board() if p is not None)
                       and self.hand[C.F_ENERGY] == 0 and self.hand[C.ROCK_FIGHTING] == 0)
            if starved:
                return 12000
            if self.chomp_line == 0 and self.hand[C.GIBLE] == 0:
                return 11000   # fetch Gible
            return 8500
        if cid == C.POKE_PAD:
            # non-Rule-Box only: Gabite/Roserade/Roselia/Gible — NOT Garchomp ex
            if not self.gabite_on_board and self.hand[C.GABITE] == 0 and self.chomp_line >= 1:
                return 9000
            if self.rose_line == 0 and self.hand[C.ROSELIA] == 0:
                return 8000
            return 7500   # keep digging bodies (nasuo 419x)
        if cid == C.NIGHT_STRETCHER:
            need = (self.discard.get(C.GARCHOMP, 0) or self.discard.get(C.GABITE, 0)
                    or self.discard.get(C.GIBLE, 0) or self.discard.get(C.F_ENERGY, 0))
            return 3500 if need else 300
        if cid == C.UNFAIR_STAMP:
            # comeback shuffle: best when OUR hand is small
            return 10000 if self.me.handCount <= 4 else 1500

        if cid == C.HILDA:
            if self.state.supporterPlayed:
                return UNNECESSARY
            if self.chomp_line == 0 and self.hand[C.GIBLE] == 0:
                return 1500    # Evolution-searcher is dead without a base (6-25 lesson)
            if not self.chomp_on_board and not self.gabite_on_board:
                return 9000    # early only — once Champion's Call runs, Hilda is redundant
            return 4000
        if cid == C.LILLIE:
            if self.state.supporterPlayed:
                return UNNECESSARY
            base = 8000        # nasuo leans on Lillie (Champion's Call covers search)
            if self.basic_emergency:
                base = max(base, 12000)
            if self.me.handCount <= 3:
                base += 2000
            if self.me.handCount >= 7:
                base -= 4000
            return base
        if cid == C.SURFER:
            if self.state.supporterPlayed:
                return UNNECESSARY
            # switch + draw-to-5: rescue a stuck non-attacker AND refill
            if (self.active is not None and self.active.id != C.GARCHOMP
                    and self.bench_attacker_ready() and self.me.handCount <= 4):
                return 9000
            return 1200
        if cid == C.BOSS:
            if self.state.supporterPlayed:
                return UNNECESSARY
            if self.opp is not None and self.have_ready_attacker():
                for p in self.opponent.bench:
                    if p is None:
                        continue
                    for aid in (CORKSCREW_DIVE, DRACONIC_BUSTER):
                        if self._atk_dmg(aid, p) >= p.hp:
                            if prize_count(p) >= 2:
                                return 12000   # multi-prize gust-KO
                            return 4500        # 1-prize gust rarely worth the supporter
            return 500
        if cid == C.XEROSIC:
            if self.state.supporterPlayed:
                return UNNECESSARY
            opp_hand = getattr(self.opponent, 'handCount', 0) or 0
            return 8000 if opp_hand >= 6 else 800

        if cid == C.POWER_WEIGHT:
            for p in self.my_board():
                if p is not None and p.id == C.GARCHOMP and not (p.tools or []):
                    return 8000   # 330 -> 400HP
            for p in self.my_board():
                if p is not None and p.id == C.GABITE and not (p.tools or []):
                    return 3000   # persists through evolution
            return 300
        if cid == C.FOREST:
            if self.state.stadiumPlayed:
                return UNNECESSARY
            cur = None
            try:
                st = getattr(self.obs.current, 'stadium', None)
                cur = st[0].id if st else None
            except Exception:
                pass
            if cur == C.FOREST:
                return UNNECESSARY
            # {G} same-turn evolve: lets a fresh Roselia become Roserade immediately
            if self.hand[C.ROSELIA] and self.hand[C.ROSERADE]:
                return 7000
            return 2500 if cur is not None else 1800   # replacing opp's stadium is a bonus

        if cid in (C.F_ENERGY, C.ROCK_FIGHTING):
            for p in self.my_board():
                if p is not None and self.should_fuel(p) and self.attach_helps(p, None):
                    return 8000
            if (self.active is not None and self.active.id == C.GARCHOMP
                    and self.energy_count(self.active) == 1 and self._buster_worth_it()):
                return 7800   # 2nd energy for a Buster KO
            return 1000
        return 1000

    # ── dispatch overrides ───────────────────────────────────────────────────
    def score_play(self, o):
        card = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        return 0 if card is None else self.hand_score(card.id)

    def score_play_poke(self, card):
        return self.hand_score(card.id)

    def score_play_trainer(self, card):
        return self.hand_score(card.id)

    # ── ATTACH ───────────────────────────────────────────────────────────────
    def score_attach(self, o):
        p = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
        if not isinstance(p, Pokemon):
            return 0
        src = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        is_active = o.inPlayArea == AreaType.ACTIVE

        if src is not None and src.id == C.POWER_WEIGHT:
            # tool — must NOT be gated by energy should_fuel (7-06 Cape-bug lesson)
            if p.tools:
                return -1
            if p.id == C.GARCHOMP:
                return 8000 + (300 if is_active else 0)
            if p.id == C.GABITE:
                return 3000
            return -1

        # 2nd energy on the ACTIVE Garchomp only for a Buster KO (should_fuel stops at 1)
        if (p.id == C.GARCHOMP and is_active and self.energy_count(p) == 1
                and src is not None and self.is_energy(src.id) and self._buster_worth_it()):
            return 8500
        # Rock Fighting preferentially on the ACTIVE (its effect-shield matters there)
        base = super().score_attach(o)
        if base > 0 and src is not None and src.id == C.ROCK_FIGHTING and is_active:
            base += 400
        return base

    def score_card(self, o):
        # ATTACH_TO target choice must mirror the Buster bypass, or the base should_fuel
        # gate rejects the 1-energy active Garchomp and the fallback picks a bad target.
        if self.context == SelectContext.ATTACH_TO:
            card = get_card(self.obs, o.area, o.index, o.playerIndex)
            if (isinstance(card, Pokemon) and o.playerIndex == self.my_index
                    and card.id == C.GARCHOMP and o.inPlayArea == AreaType.ACTIVE
                    and self.energy_count(card) == 1 and self._buster_worth_it()):
                return 8500
        return super().score_card(o)

    def attach_priority(self, p, is_active):
        concentrate = self.energy_count(p) * 600
        if p.id == C.GARCHOMP:
            return 9000 + concentrate + (300 if is_active else 0)
        if p.id in (C.GABITE, C.GIBLE):
            return 5500 + concentrate   # carries through evolution
        if p.id == C.SPIRITOMB:
            # nasuo fuels Spiritomb (236x): 1 {F} arms Raging Curse (10 x bench counters)
            counters = sum((p2.maxHp - p2.hp) // 10 for p2 in self.me.bench if p2 is not None)
            return 4500 + concentrate if counters >= 6 else 2500
        return -1   # Roserade's attack needs {G} we don't run — support only

    # ── ABILITY (Champion's Call) ────────────────────────────────────────────
    def score_ability(self, o):
        card = get_card(self.obs, o.area, o.index, self.my_index)
        if card is not None and card.id == C.GABITE:
            return 19000   # free search — fire it FIRST every turn (nasuo 1025x)
        return 4000

    # ── EVOLVE ───────────────────────────────────────────────────────────────
    def score_evolve(self, o):
        card = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        cid = card.id if card is not None else None
        if cid == C.GARCHOMP:
            # nasuo's #1 lesson (our 2466x over-pick): evolving KILLS Champion's Call and
            # exposes a 2-prize body — only evolve a FUELED Gabite that will attack.
            target = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
            fueled = isinstance(target, Pokemon) and self.energy_count(target) >= 1
            is_active = o.inPlayArea == AreaType.ACTIVE
            if fueled and (is_active or not self.have_ready_attacker()):
                return 24000
            return 2000
        if cid == C.GABITE:
            return 22000   # turns on Champion's Call
        if cid == C.ROSERADE:
            return 18000   # permanent +30
        return 8000

    def score_evolves_choice(self, card):
        if card is None:
            return 1000
        if card.id in (C.GARCHOMP, C.GABITE, C.GIBLE):
            return 3000
        if card.id in (C.ROSERADE, C.ROSELIA):
            return 2000
        return 1000

    # ── RETREAT ──────────────────────────────────────────────────────────────
    def score_retreat(self):
        active = self.me.active[0] if self.me.active else None
        if active is None:
            return -1
        if active.id != C.GARCHOMP:
            for p in self.me.bench:
                if p is not None and p.id == C.GARCHOMP and self.can_attack(p):
                    return 6500
        if not self.can_attack(active) and self.bench_attacker_ready():
            return 6000
        # nasuo rotates constantly (533 divergent RETREATs): pull a damaged active out
        # while another attacker is ready — benched damage feeds Raging Curse.
        if (active.maxHp and (active.maxHp - active.hp) * 3 >= active.maxHp
                and self.bench_attacker_ready()):
            return 5800
        return -1

    # ── ATTACK ───────────────────────────────────────────────────────────────
    def score_attack(self, o):
        active = self.active
        opp = self.opp
        if active is None or opp is None:
            return 800
        aid = o.attackId
        dmg = self._atk_dmg(aid, opp)
        if dmg <= 0 and aid != RAGING_CURSE:
            return 500

        # Game-winning KO
        if dmg > 0 and opp.hp <= dmg and prize_count(opp) >= len(self.me.prize):
            return 95000

        score = 1000 + min(dmg, 400)
        if aid == CORKSCREW_DIVE:
            score += 1200   # the workhorse: damage + refill hand to 6
        if aid == DRACONIC_BUSTER:
            # discards ALL energy — only over Corkscrew when the extra damage matters
            if opp.hp <= dmg and opp.hp > self._atk_dmg(CORKSCREW_DIVE, opp):
                score += 3000
            else:
                score -= 1500
        if aid == RAGING_CURSE:
            counters = sum((p.maxHp - p.hp) // 10 for p in self.me.bench if p is not None)
            score = 800 + counters * 10
        if opp.hp <= dmg:
            score += 2500 + prize_count(opp) * 250
            if prize_count(opp) >= 2:
                score += 1000
        return score

    # ── sub-select scorers ───────────────────────────────────────────────────
    def score_active_choice(self, o, card):
        if not isinstance(card, Pokemon):
            return 0
        if o.playerIndex == self.op_index:
            return self.gust_value(card)
        if o.playerIndex != self.my_index:
            return 0
        score = len(card.energies or []) * 10
        if card.id == C.GARCHOMP:
            score += 300
        elif card.id == C.GABITE:
            score += 120
        elif card.id == C.GIBLE:
            score += 100
        elif card.id == C.SPIRITOMB:
            counters = sum((p.maxHp - p.hp) // 10 for p in self.me.bench if p is not None)
            score += 250 if (self.energy_count(card) >= 1 and counters >= 8) else 60
        else:
            score += 40   # Roselia/Roserade stay benched (support)
        return score + 1

    def score_setup_active(self, card):
        if card is None:
            return 0
        if card.id == C.GIBLE:
            return 50    # becomes the retreat-0 attacker
        if card.id == C.SPIRITOMB:
            return 30
        if card.id == C.ROSELIA:
            return 20
        return 5

    def score_to_bench(self, card):
        # nasuo benches NOTHING at setup (0/11 — hide information; Poffin fills later)
        if self.context == SelectContext.SETUP_BENCH_POKEMON:
            return -1
        if card is None:
            return 0
        d = card_table.get(card.id)
        if d is None or d.cardType != CardType.POKEMON:
            return 0
        cid = card.id; n = self.field[cid]
        if cid == C.GIBLE:
            return 220 - 30 * n   # his Poffin priority: Gible >> Roselia > Spiritomb
        if cid == C.ROSELIA:
            return 140 - 60 * n
        if cid == C.SPIRITOMB:
            return 60 - 40 * n
        return 50 - 20 * n

    def score_to_hand(self, card):
        if card is None:
            return 0
        cid = card.id
        score = 200 - self.hand[cid] * 40
        # nasuo's Champion's Call priorities: SUPPORT bodies first (Roselia 413 > Gabite 305
        # > Gible 282 > Roserade 259 > Garchomp 244 > Spiritomb 193); we hoarded Garchomp/Gabite.
        if cid == C.GARCHOMP:
            score += 70 if (self.hand[C.GARCHOMP] == 0
                            and (self.gabite_on_board or self.hand[C.GABITE])) else 20
        elif cid == C.GABITE:
            # a Gible waiting for its Gabite — and EXTRA Gabites = extra Champion's Calls
            score += 72 if self.field[C.GIBLE] >= self.field[C.GABITE] else 25
        elif cid == C.GIBLE:
            score += 50 if self.chomp_line + self.hand[C.GIBLE] < 2 else 15
        elif cid == C.ROSERADE:
            score += 65 if (self.rose_line >= 1 and not self.roserade_on_board) else 10
        elif cid == C.ROSELIA:
            score += 45 if self.rose_line == 0 else 10
        elif cid == C.SPIRITOMB:
            score += 35 if self.field[C.SPIRITOMB] == 0 else 10
        elif self.is_energy(cid):
            need = any(p is not None and p.id == C.GARCHOMP and self.should_fuel(p)
                       for p in self.my_board())
            score += 120 if need else 40
        return score

    def score_discard(self, card):
        if card is None:
            return 0
        cid = card.id
        if cid == C.GARCHOMP:
            return -200
        if cid in (C.GIBLE, C.GABITE):
            return -100 if (self.hand[cid] <= 1 and self.chomp_line < 2) else 10
        if cid in (C.F_ENERGY, C.ROCK_FIGHTING):
            return 40 if self.hand[C.F_ENERGY] + self.hand[C.ROCK_FIGHTING] >= 3 else -20
        if cid == C.LILLIE:
            return -60 if self.hand[cid] <= 1 else 25
        if cid == C.FOREST:
            return 45
        if cid == C.XEROSIC:
            return 35
        if cid == C.SPIRITOMB:
            return 20
        if cid in (C.ROSELIA, C.ROSERADE):
            return -40 if self.rose_line == 0 else 30
        if self.hand[cid] >= 2:
            return 60
        return 0

    def score_putback(self, card):
        if card is None:
            return 0
        cid = card.id
        if self.hand[cid] >= 2:
            return 70
        if cid in (C.GIBLE, C.GABITE, C.GARCHOMP):
            return -40 if self.field[cid] == 0 else 60   # spares are Champion's-Call-searchable
        return 10

    def score_spread_target(self, card):
        # no spread attack of our own; used only for rare placed-damage effects
        hp = getattr(card, 'hp', 0)
        return 5000 - hp * 14 + prize_count(card) * 250


_impl = make_agent(GarchompPolicy, my_deck, DIAG)


def agent(obs_dict):
    return _impl(obs_dict)
