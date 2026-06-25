"""Team Rocket's Mewtwo ex — Tribal Disruption. Sample-Style 2.0 full policy.

Core mechanics:
  - Power Saver: Mewtwo can't attack unless 4+ Team Rocket's Pokémon in play.
  - Erasure Ball [P][P][C] = 160 + 60 per bench energy discarded (max 2, total 280).
  - Spidops Charging Up recycles Basic Energy from discard every turn.
  - Articuno Repelling Veil protects Basic Rocket Pokémon from attack effects.
  - Team Rocket's Energy provides {P}{D} (2 per card) — key for Mewtwo's Psychic cost.
  - Proton T1: search 3 Basic Rocket Pokémon for explosive setup.
  - Transceiver → Ariana/Archer/Proton: toolbox search chain.

Inherits from BasePolicy for infrastructure (energy tracking, PrizeTracker, fallback).
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
    # Pokémon
    TAROUNTULA = 400       # Basic {G} 50HP, Take Down [G]=30 self-dmg10
    SPIDOPS = 401          # Stage1 130HP, Charging Up (attach from discard), Rocket Rush [G,C]
    ARTICUNO = 414         # Basic {W} 120HP, Repelling Veil (protect basics), Dark Frost [W,C,C]
    MEWTWO_EX = 431        # Basic ex {P} 280HP, Power Saver (4 Rocket to attack), Erasure Ball [P,P,C]
    MIMIKYU = 434          # Basic {P} 60HP, Gemstone Mimicry [P,C] copy Tera attack
    # Item
    BUG_SET = 1094         # look top7, take up to 2 Grass Pokémon/Energy
    ULTRA_BALL = 1121      # discard2, search Pokémon
    POKEGEAR = 1122        # dig7 for Supporter
    TRANSCEIVER = 1134     # search a Team Rocket's Supporter
    POKE_PAD = 1152        # search non-Rule-Box Pokémon -> hand
    # Tool
    HEROS_CAPE = 1159      # +100HP
    # Supporter
    BOSS = 1182            # gust
    ARIANA = 1216          # draw to 5 (or to 8 if all Rocket in play)
    ARCHER = 1217          # KO-revenge: both shuffle, you draw5 opp draws3
    PROTON = 1220          # T1 (or later): search 3 Basic Rocket Pokémon
    LILLIE = 1227          # shuffle-draw 6(8)
    # Stadium
    FACTORY = 1257         # TR Factory: after playing TR Supporter, draw 2
    # Energy
    GRASS_ENERGY = 1       # Basic {G} x9
    ROCKET_ENERGY = 15     # Special: provides {P}{D} (2 energy per card)

# Roster of Team Rocket's Pokémon (for Power Saver count)
ROCKET_POKEMON = {C.TAROUNTULA, C.SPIDOPS, C.ARTICUNO, C.MEWTWO_EX}
ROCKET_BASICS = {C.TAROUNTULA, C.ARTICUNO, C.MEWTWO_EX}

# Attack IDs
ERASURE_BALL = 608
ROCKET_RUSH = 560
TAKE_DOWN = 559
GEMSTONE_MIMICRY = 612
DARK_FROST = 583

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
class MewtwoExPolicy(BasePolicy):
    ENERGY_TYPES = {C.GRASS_ENERGY, C.ROCKET_ENERGY}
    ATTACKER_IDS = {C.MEWTWO_EX}

    # GO SECOND: Mewtwo is a setup deck; going second gives an extra card and
    # lets Proton search on T1. (Rocket tribal wants bodies, not the attack.)
    def go_first(self):
        return False

    # ── state collection ──────────────────────────────────────────────────────
    def _collect(self):
        """Derived state flags."""
        # Rocket Pokémon in play (counted for Power Saver)
        self.rocket_in_play = sum(1 for p in self.my_board()
                                  if p is not None and p.id in ROCKET_POKEMON)
        self.mewtwo_on_board = any(p is not None and p.id == C.MEWTWO_EX for p in self.my_board())
        self.spidops_on_board = any(p is not None and p.id == C.SPIDOPS for p in self.my_board())
        self.spidops_on_bench = any(p is not None and p.id == C.SPIDOPS for p in self.me.bench)
        self.tarountula_on_board = any(p is not None and p.id == C.TAROUNTULA for p in self.my_board())
        self.articuno_on_board = any(p is not None and p.id == C.ARTICUNO for p in self.my_board())

        self.open_bench = sum(1 for p in self.me.bench if p is not None) < 5
        self.active = self.me.active[0] if self.me.active else None
        self.opp = self.opponent.active[0] if self.opponent.active else None

        # Mewtwo attack readiness
        self.mewtwo_active = self.active is not None and self.active.id == C.MEWTWO_EX
        self.can_attack_mewtwo = False
        if self.mewtwo_on_board and self.rocket_in_play >= 4:
            # Check if any Mewtwo can pay Erasure Ball
            for p in self.my_board():
                if p is not None and p.id == C.MEWTWO_EX and self.can_attack(p):
                    self.can_attack_mewtwo = True
                    break

        # Combat-ready mewtwo (on bench with energy)
        self.bench_mewtwo_ready = any(
            p is not None and p.id == C.MEWTWO_EX and self.can_attack(p)
            for p in self.me.bench)

        # Energy: how many Team Rocket's Energy on board
        self.rocket_energy_on_board = 0
        for p in self.my_board():
            if p is not None:
                for ec in (getattr(p, 'energyCards', None) or []):
                    if getattr(ec, 'id', None) == C.ROCKET_ENERGY:
                        self.rocket_energy_on_board += 1

        # Proton viability
        self.can_proton = (self.hand[C.PROTON] > 0
                           and not self.state.supporterPlayed)

        # Turn 1 special: if we go second, we can Proton on our first turn
        self.is_turn_1 = (self.state.turn <= 1)

    # ── provided_by: Team Rocket's Energy ─────────────────────────────────────
    def provided_by(self, src, target):
        if src is not None and src.id == C.ROCKET_ENERGY:
            # Engine says "2 in any combination of {P}{D}". The most useful split
            # for Mewtwo's [P,P,C] is [PSYCHIC, PSYCHIC]. Return 2 so can_pay
            # and should_fuel see it correctly.
            return [EnergyType.PSYCHIC, EnergyType.PSYCHIC]
        if src is not None and src.id == C.GRASS_ENERGY:
            return [EnergyType.GRASS]
        return super().provided_by(src, target)

    # ── hand_score — per-card explicit scores ─────────────────────────────────
    def hand_score(self, cid, ignore_count=False):
        """Per-card score for MAIN context PLAY decisions."""

        # ── Pokémon ──
        if cid == C.TAROUNTULA:
            if self.rocket_in_play >= 5 and not self.open_bench:
                return UNNECESSARY
            # If we have a Tarountula that can evolve but haven't evolved yet,
            # prefer evolving FIRST rather than playing more basics
            if self.tarountula_on_board and not self.spidops_on_board:
                if self.hand[C.SPIDOPS] > 0:
                    return 3000    # low priority — should evolve first
                return 12000       # no Spidops in hand, need another body
            if self.tarountula_on_board and self.spidops_on_board:
                return 15000      # 2nd Tarountula for a 2nd Spidops
            return 18000          # first body
        if cid == C.SPIDOPS:
            if self.tarountula_on_board and not self.spidops_on_board:
                return 22000      # CRITICAL — evolve to survive spread
            return 5000
        if cid == C.MEWTWO_EX:
            if self.rocket_in_play >= 3 and not self.mewtwo_on_board:
                return 35000    # almost ready — get the attacker online
            if self.mewtwo_on_board:
                return 2000     # extra copy
            return 20000        # early Mewtwo (build toward 4 Rocket)
        if cid == C.ARTICUNO:
            if not self.articuno_on_board:
                return 12000    # Repelling Veil protection
            return 2000
        if cid == C.MIMIKYU:
            return 3000          # situational tech

        # ── Search / Draw Items ──
        if cid == C.TRANSCEIVER:
            # Searches ANY Team Rocket supporter — the deck's primary search engine
            return 22000
        if cid == C.BUG_SET:
            # Early: find Tarountula or Grass Energy. Later: marginal.
            if self.rocket_in_play < 3:
                return 16000    # need bodies for setup
            if not self.mewtwo_on_board:
                return 10000
            return 4000
        if cid == C.POKE_PAD:
            # Search non-Rule-Box = Spidops / Tarountula / Articuno
            need_spidops = self.tarountula_on_board and not self.spidops_on_board
            need_tarountula = (self.rocket_in_play < 3 and not self.tarountula_on_board)
            if need_spidops:
                return 20000    # CRITICAL: find Spidops to evolve
            if need_tarountula:
                return 15000
            return 6000
        if cid == C.ULTRA_BALL:
            need = ((not self.mewtwo_on_board or self.rocket_in_play < 4)
                    and self.discard_count >= 2)
            return 14000 if need else 1000
        if cid == C.POKEGEAR:
            if self.state.supporterPlayed:
                return 500
            need = (self.hand[C.TRANSCEIVER] == 0 and self.hand[C.ARIANA] == 0
                    and self.hand[C.PROTON] == 0 and self.hand[C.LILLIE] == 0)
            return 9000 if need else 4000

        # ── Supporters ──
        if cid == C.PROTON:
            if self.state.supporterPlayed:
                return UNNECESSARY
            if self.is_turn_1:
                return 50000    # CRITICAL — absolute best T1 play: search 3 basics
            if self.rocket_in_play < 4:
                return 30000    # still need bodies for Power Saver
            return 8000
        if cid == C.ARIANA:
            if self.state.supporterPlayed:
                return UNNECESSARY
            if self.rocket_in_play == self.field_count_total():
                # All Pokémon on board are Rocket → draw to 8
                if self.me.handCount <= 4:
                    return 28000
                return 14000
            # draw to 5
            if self.me.handCount <= 3:
                return 20000
            return 6000
        if cid == C.ARCHER:
            if self.state.supporterPlayed:
                return UNNECESSARY
            # Archer is reactive: only valuable after a KO — and the reshuffle
            # disrupts the opponent. Be more willing to use it.
            if self.discard.get(C.MEWTWO_EX, 0) > 0 or self.discard.get(C.SPIDOPS, 0) > 0:
                return 18000   # post-KO: reshuffle + recover
            return 5000
        if cid == C.LILLIE:
            if self.state.supporterPlayed:
                return UNNECESSARY
            base = 15000
            if self.me.handCount >= 5:
                base -= 6000     # don't shuffle a good hand
            if self.me.deckCount <= 3:
                base -= 10000
            return base
        if cid == C.BOSS:
            if self.state.supporterPlayed:
                return UNNECESSARY
            if self.can_attack_mewtwo and self.opp is not None:
                # We can gust for a KO
                return 22000
            return 500

        # ── Stadium ──
        if cid == C.FACTORY:
            if self.stadium_id == C.FACTORY:
                return 200       # already ours
            if self.state.stadiumPlayed:
                return 200
            # Extra draw after Rocket supporter is strong
            if self.state.turn <= 3 or self.me.handCount <= 4:
                return 12000
            return 6000

        # ── Tool ──
        if cid == C.HEROS_CAPE:
            if self.mewtwo_active and not (self.active.tools or []):
                return 9000      # +100HP on the main attacker
            return 200

        # ── Energy ──
        if cid == C.GRASS_ENERGY:
            # Fuel Tarountula / Spidops, or provide Colorless for Mewtwo
            for p in self.my_board():
                if p is not None and self.should_fuel(p) and self.attach_helps(p, None):
                    return 10000
            return 1000
        if cid == C.ROCKET_ENERGY:
            # Critical for Mewtwo's Psychic cost. Prefer attaching to Mewtwo.
            need_psychic = self.mewtwo_on_board and not self.can_attack_mewtwo
            if need_psychic:
                return 25000
            return 8000

        return 1000

    # ── Override score() to collect state first ────────────────────────────────
    def score(self, o):
        self._collect()
        return super().score(o)

    # ── Override score_play to use hand_score ──────────────────────────────────
    def score_play(self, o):
        card = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        if card is None:
            return 0
        return self.hand_score(card.id, ignore_count=False)

    def score_play_poke(self, card):
        return self.hand_score(card.id)
    def score_play_trainer(self, card):
        return self.hand_score(card.id)

    # ── ATTACH ─────────────────────────────────────────────────────────────────
    def score_attach(self, o):
        p = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
        if not isinstance(p, Pokemon):
            return 0
        src = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        is_active = o.inPlayArea == AreaType.ACTIVE
        cid = src.id if src is not None else None

        # Team Rocket's Energy: priority to Mewtwo that needs Psychic
        if cid == C.ROCKET_ENERGY:
            if p.id == C.MEWTWO_EX and self.should_fuel(p):
                return 12000 + (500 if is_active else 0)
            if p.id == C.MEWTWO_EX and not self.should_fuel(p):
                return -1            # already fueled — don't over-fill
            # Spidops or others — still useful but lower priority
            if p.id in (C.SPIDOPS, C.TAROUNTULA) and self.should_fuel(p):
                return 5000
            if not self.should_fuel(p):
                return -1
            return 1000

        # Grass Energy: fuel attackers
        if not self.should_fuel(p):
            return -1
        return self.attach_priority(p, is_active)

    def attach_priority(self, p, is_active):
        concentrate = self.energy_count(p) * 500
        if p.id == C.MEWTWO_EX:
            return 9000 + concentrate + (400 if is_active else 0)
        if p.id == C.SPIDOPS:
            return 5000 + concentrate + (200 if is_active else 0)
        if p.id == C.TAROUNTULA:
            return 2000 + concentrate
        return -1

    # ── ABILITY: Spidops Charging Up ───────────────────────────────────────────
    def score_ability(self, o):
        card = get_card(self.obs, o.area, o.index, self.my_index)
        if card is not None and card.id == C.SPIDOPS:
            # Charging Up: attach Basic Energy from discard — USE IT every turn
            return 20000
        return 9000

    # ── EVOLVE ─────────────────────────────────────────────────────────────────
    def score_evolve(self, o):
        target = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
        if not isinstance(target, Pokemon):
            return 0
        card = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        cid = card.id if card is not None else None
        if cid == C.SPIDOPS:
            return 20000 + (300 if o.inPlayArea == AreaType.ACTIVE else 0)
        return 0

    def score_evolves_choice(self, card):
        if card is None:
            return 1000
        if card.id in (C.SPIDOPS, C.TAROUNTULA):
            return 3000
        return 1000

    # ── ATTACK ─────────────────────────────────────────────────────────────────
    def score_attack(self, o):
        active = self.active
        opp = self.opp
        if active is None or opp is None:
            return 800
        aid = o.attackId
        dmg = self._attack_damage(active, aid, opp)

        # Game-winning KO
        if dmg > 0 and opp.hp <= dmg and prize_count(opp) >= len(self.me.prize):
            return 95000

        if aid == ERASURE_BALL:
            if not self.can_attack_mewtwo:
                return 500       # Power Saver blocks this
            score = 3000 + min(dmg, 320)
            if opp.hp <= dmg:
                score += 3000 + prize_count(opp) * 300
                if prize_count(opp) >= 2:
                    score += 2000
            return score
        if aid == ROCKET_RUSH:
            if self.spidops_on_board and not self.can_attack_mewtwo:
                # Spidops is our only attacker while setting up Mewtwo
                score = 2000 + min(dmg, 200)
                if opp.hp <= dmg:
                    score += 1500 + prize_count(opp) * 200
                return score
            return 800            # marginal — prefer Mewtwo
        if aid == TAKE_DOWN:
            return 600            # last resort
        if dmg <= 0:
            return 400
        return 1000 + min(dmg, 320)

    def _attack_damage(self, attacker, aid, target):
        """Calculate damage accounting for Rocket synergy."""
        if target is None or attacker is None:
            return 0
        if aid == ERASURE_BALL:
            base = 160
            # Max bonus: 2 energy from bench = 120. We assume we can always discard
            # at least 1 energy (conservative).
            bench_energy = sum(
                len(p.energies or []) for p in self.me.bench
                if p is not None and p.id in ROCKET_POKEMON)
            bonus = min(bench_energy, 2) * 60
            return base + bonus
        if aid == ROCKET_RUSH:
            return self.rocket_in_play * 30
        if aid == TAKE_DOWN:
            return 30
        if aid == DARK_FROST:
            base = 60
            # +60 if this Pokémon has Team Rocket's Energy
            for ec in (getattr(attacker, 'energyCards', None) or []):
                if getattr(ec, 'id', None) == C.ROCKET_ENERGY:
                    base += 60
                    break
            # But Articuno needs [W] which we don't have — this won't be payable
            return base
        return 0

    # ── Sub-select scorers ─────────────────────────────────────────────────────
    def score_spread_target(self, card):
        """DAMAGE counter: Mewtwo/Boss target priority."""
        hp = getattr(card, 'hp', 0)
        d = card_table.get(card.id)
        can_evolve = d is not None and (d.stage1 or d.stage2 or d.evolvesFrom)
        sc = 5000 - hp * 12 + prize_count(card) * 250
        if can_evolve and hp <= 80:
            sc += 2000
        if hp <= 60:
            sc += 1500
        if hp <= 30:
            sc += 2000
        # ex/megaEx targets are highest priority (2-3 prizes)
        if prize_count(card) >= 2 and self.can_attack_mewtwo:
            sc += 3000 + prize_count(card) * 1000
        return sc

    def score_active_choice(self, o, card):
        if not isinstance(card, Pokemon):
            return 0
        if o.playerIndex == self.op_index:
            return self.gust_value(card)
        if o.playerIndex != self.my_index:
            return 0
        # Promote Mewtwo > Spidops > Articuno > Tarountula > Mimikyu
        score = len(card.energies) * 10
        if card.id == C.MEWTWO_EX:
            score += 300
            if self.can_attack_mewtwo:
                score += 500
        elif card.id == C.SPIDOPS:
            score += 150
        elif card.id == C.ARTICUNO:
            score += 80
        elif card.id == C.TAROUNTULA:
            score += 40
        score += getattr(card, 'hp', 0) // 30
        return score + 1

    def score_setup_active(self, card):
        if card is None:
            return 0
        if card.id == C.TAROUNTULA:
            return 50   # lead with the evolution line
        if card.id == C.MEWTWO_EX:
            return 30
        if card.id == C.ARTICUNO:
            return 20
        if card.id == C.MIMIKYU:
            return 5
        return 10

    def score_to_bench(self, card):
        if card is None:
            return 0
        d = card_table.get(card.id)
        if d is None or d.cardType != CardType.POKEMON:
            return 0
        cid = card.id; n = self.field[cid]
        if cid == C.TAROUNTULA:
            return 200 - 30 * n
        if cid == C.MEWTWO_EX:
            return 180 - 30 * n
        if cid == C.ARTICUNO:
            return 150 - 40 * n
        if cid == C.MIMIKYU:
            return 100 - 40 * n
        return 100 - 20 * n

    def score_to_hand(self, card):
        if card is None:
            return 0
        cid = card.id
        score = 200 - self.hand[cid] * 30
        # Priority: Transceiver (engine) > Rocket basics > Energy
        if cid == C.TRANSCEIVER:
            score += 120
        elif cid == C.PROTON:
            score += 100 if (self.rocket_in_play < 4 and not self.state.supporterPlayed) else 30
        elif cid in (C.TAROUNTULA, C.MEWTWO_EX):
            score += 80 if self.field[cid] == 0 else 20
        elif cid == C.ROCKET_ENERGY:
            score += 70 if self.mewtwo_on_board and not self.can_attack_mewtwo else 20
        elif self.is_energy(cid):
            score += 50
        return score

    def score_discard(self, card):
        if card is None:
            return 0
        cid = card.id
        if self.is_energy(cid):
            if cid == C.ROCKET_ENERGY:
                return -50 if self.hand[cid] <= 1 else 20   # keep Rocket Energy
            return 40 if self.hand[cid] >= 3 else -30
        if self.hand[cid] >= 2:
            return 60
        # Keep search/draw engines
        if cid in (C.TRANSCEIVER, C.PROTON, C.ARIANA, C.LILLIE, C.BUG_SET):
            return -40
        if cid in (C.TAROUNTULA, C.MEWTWO_EX, C.SPIDOPS):
            return -30 if self.field[cid] == 0 else 5
        return 0

    def score_putback(self, card):
        if card is None:
            return 0
        if self.hand[card.id] >= 2:
            return 60
        if card.id in (C.MEWTWO_EX, C.TAROUNTULA, C.TRANSCEIVER):
            return -40
        return 10

    # ── helpers ──
    def field_count_total(self):
        return sum(1 for p in self.my_board() if p is not None)

    @property
    def discard_count(self):
        return sum(1 for c in self.me.hand
                   if c.id not in (C.MEWTWO_EX, C.SPIDOPS) and not self.is_energy(c.id))


_impl = make_agent(MewtwoExPolicy, my_deck, DIAG)


def agent(obs_dict):
    return _impl(obs_dict)
