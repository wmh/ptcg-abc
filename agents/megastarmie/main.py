"""Mega Starmie ex + Cinderace — Sample-Style 2.0 full policy.
Clone of ladder #1 keidroid (Elo 1341). Every card has an explicit score in
hand_score(), attack planning, and HP-zone based DAMAGE_COUNTER targeting.

Inherits from BasePolicy for infrastructure (energy discipline, PrizeTracker,
normalize_selection, fallback), but overrides the dispatch to use sample-style
per-card scoring instead of generic abstract-method hooks.
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
    STARYU = 1030          # Basic {W} 70HP -> Mega Starmie ex
    MEGA_STARMIE = 1031    # Stage1 MegaEx {W} 330HP, 3 prizes
    CINDERACE = 666        # Stage2 {Fire} 160HP, Explosiveness opener, Turbo Flare accel
    MEOWTH_EX = 1071       # Basic {C} 170HP ex, Last-Ditch Catch (search Supporter on play)
    # Item
    POKEGEAR = 1122        # dig 7 for Supporter
    MEGA_SIGNAL = 1145     # search a Mega ex -> hand
    BUDDY_POFFIN = 1086    # 2 basics <=70HP -> bench
    CRUSHING_HAMMER = 1120 # coin-flip discard opp energy
    NIGHT_STRETCHER = 1097 # recover mon/energy from discard
    SALVATORE = 1189       # evolve a no-ability mon this turn
    ULTRA_BALL = 1121      # discard 2, search a Pokémon
    # Supporter
    WALLY = 1229           # heal ALL dmg on a Mega ex + recycle its energy
    HILDA = 1225           # search Evolution + Energy
    LILLIE = 1227          # shuffle-draw 6(8)
    HARLEQUIN = 1223       # draw until 5 in hand
    BOSS = 1182            # gust
    # Tool
    HEROS_CAPE = 1159      # +100HP
    # Energy
    WATER_ENERGY = 3       # Basic {W} x8
    IGNITION_ENERGY = 17   # Special: {C} base, {C}{C}{C} on evolution; DISCARDED end-of-turn

# Attack IDs
JETTING_BLOW = NEBULA_BEAM = TURBO_FLARE = WATER_GUN = None
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

UNNECESSARY = -10000000
IGNITION_ATTACK = NEBULA_BEAM  # Ignition enables this one-shot

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

# ── Attack plan structure (like Dragapult sample's plan_a/plan_b) ────────────
class AttackPlan:
    attack: int = 0            # attack ID to use
    target_idx: int = 0        # target index in opp bench (+1, 0 = Active)
    boss: bool = False         # need Boss to gust this target
    ko: bool = False           # this attack KOs the target


# ── Policy ───────────────────────────────────────────────────────────────────
class MegaStarmiePolicy(BasePolicy):
    ENERGY_TYPES = {C.WATER_ENERGY, C.IGNITION_ENERGY}
    ATTACKER_IDS = {C.MEGA_STARMIE, C.CINDERACE}

    def go_first(self):
        return True   # keidroid 27/27

    # ── state collected at the start of each decision ──────────────────────────
    def _detect_archetype(self):
        opp_ids = set()
        for p in self.opponent.active:
            if p: opp_ids.add(p.id)
        for p in self.opponent.bench:
            if p: opp_ids.add(p.id)
        if 119 in opp_ids or 235 in opp_ids:
            return 'dragapult'
        if 878 in opp_ids:
            return 'trevenant'
        if 673 in opp_ids:
            return 'lucario'
        if 400 in opp_ids or 431 in opp_ids:
            return 'mewtwo'
        if 97 in opp_ids:  # Snorunt
            return 'froslass'
        return 'unknown'

    def _collect(self):
        """Derived state flags, like Dragapult's main_pokemon_count / can_evolve / pre_ko."""
        self.staryu_on_board = self.field[C.STARYU] > 0
        self.mega_on_board = any(p is not None and p.id == C.MEGA_STARMIE for p in self.my_board())
        self.mega_in_hand = self.hand[C.MEGA_STARMIE] > 0
        self.cinderace_on_board = any(p is not None and p.id == C.CINDERACE for p in self.my_board())
        self.meowth_on_board = any(p is not None and p.id == C.MEOWTH_EX for p in self.my_board())
        self.open_bench = sum(1 for p in self.me.bench if p is not None) < 5
        self.mega_line_count = self.field[C.STARYU] + self.field[C.MEGA_STARMIE]
        self.cinderace_count = self.field[C.CINDERACE]
        # Basic-availability emergency: no benched body to promote AND no Basic in hand to play
        # — our Active being KO'd would lose the game (Staryu is our ONLY Basic line).
        self.bench_body_count = sum(1 for p in self.me.bench if p is not None)
        self.basic_emergency = self.bench_body_count == 0 and self.hand[C.STARYU] == 0

        # Active / opp state
        self.opp = self.opponent.active[0] if self.opponent.active else None
        self.active = self.me.active[0] if self.me.active else None
        self.active_is_mega = self.active is not None and self.active.id == C.MEGA_STARMIE
        self.active_is_cinderace = self.active is not None and self.active.id == C.CINDERACE

        # Ready attacker state
        self.ready_mega_on_bench = any(
            p is not None and p.id == C.MEGA_STARMIE and self.can_attack(p)
            for p in self.me.bench)

        # Build attack plan
        self.plan_a = AttackPlan()
        self.plan_b = []
        self._build_attack_plan()

        # ── matchup awareness ──
        if not hasattr(self, '_archetype'):
            self._archetype = self._detect_archetype()
            self._vs_spread = self._archetype in ('dragapult', 'froslass')
            self._vs_aggro = self._archetype in ('lucario',)
            self._vs_setup = self._archetype in ('mewtwo', 'trevenant')

    def _build_attack_plan(self):
        """plan_a = best attack + target for KO, matchup-aware.
        vs_spread → Jetting Blow's 50 spread gets KO bonus.
        vs_aggro → prioritize Nebula Beam's higher damage.
        """
        act = self.active
        if act is None or self.opp is None:
            return

        vs_spread = getattr(self, '_vs_spread', False)
        payable = self.payable_attacks(act)
        if not payable:
            return

        opp_bench = [p for p in self.opponent.bench if p is not None]

        # —— plan_a: best KO (Active or bench via Boss) ——
        best_score = -1
        best_target = None
        best_aid = None
        need_boss = False

        for aid in payable:
            # Score against Active
            d = self._raw_dmg(aid, self.opp)
            sc = d + (5000 if d >= self.opp.hp else 0) + prize_count(self.opp) * 250

            # Jetting Blow bonus: bench spread value
            if aid == JETTING_BLOW:
                spread_val = self._jett_spread_score()
                if vs_spread:
                    spread_val = int(spread_val * 1.5)  # more valuable vs spread
                sc += spread_val

            if sc > best_score:
                best_score = sc
                best_target = self.opp
                best_aid = aid
                need_boss = False

            # Check bench targets with Boss
            for p in opp_bench:
                d = self._raw_dmg(aid, p)
                if d >= p.hp:
                    sc = d + 5000 + prize_count(p) * 250 - 2000
                    if sc > best_score:
                        best_score = sc
                        best_target = p
                        best_aid = aid
                        need_boss = True

        if best_aid is not None:
            self.plan_a.attack = best_aid
            self.plan_a.target_idx = 1 + opp_bench.index(best_target) if best_target in opp_bench else 0
            self.plan_a.ko = self._raw_dmg(best_aid, best_target) >= best_target.hp
            self.plan_a.boss = need_boss

        # —— plan_b: Jetting Blow 50-spread KOs (no Boss needed) ——
        if JETTING_BLOW in payable:
            for p in opp_bench:
                if p is not None and p.hp <= 50:
                    self.plan_b.append(p)

    def _raw_dmg(self, aid, target):
        """Raw damage of attack `aid` against `target` (includes weakness for Jetting Blow)."""
        if target is None or aid is None:
            return 0
        if aid == NEBULA_BEAM:
            return 210      # ignores weakness/resistance
        if aid == JETTING_BLOW:
            dmg = 120
            d = card_table.get(target.id)
            if d and d.weakness == EnergyType.WATER:
                dmg *= 2
            return dmg
        a = attack_table.get(aid)
        base = getattr(a, 'damage', 0) or 0
        if aid == WATER_GUN:
            d = card_table.get(target.id)
            if d and d.weakness == EnergyType.WATER and base:
                base *= 2
        return base

    def _jett_spread_score(self):
        """Score for Jetting Blow's 50 bench spread — how much value in KOing a bench target."""
        if not self.plan_b:
            return 0
        best = 0
        for p in self.plan_b:
            d = card_table.get(p.id)
            can_evolve = d is not None and (d.stage1 or d.stage2 or d.evolvesFrom)
            bonus = 3000 if can_evolve else 1500
            best = max(best, bonus + prize_count(p) * 250)
        return best

    # ── provided_by (Ignition Energy provision) ───────────────────────────────
    def provided_by(self, src, target):
        if src is not None and src.id == C.IGNITION_ENERGY:
            return [EnergyType.COLORLESS] * (3 if is_evolution(target.id) else 1)
        return super().provided_by(src, target)

    # ── hand_score — per-card explicit scores (SAMPLE-STYLE) ───────────────────
    UNNECESSARY = UNNECESSARY

    def hand_score(self, cid, ignore_count=False):
        """Per-card score used in MAIN context PLAY decisions.
        Returns score in 0-55000 range; UNNECESSARY means never pick this option."""
        vs_spread = getattr(self, '_vs_spread', False)
        vs_aggro = getattr(self, '_vs_aggro', False)
        vs_setup = getattr(self, '_vs_setup', False)

        # ── Pokémon ──
        if cid == C.STARYU:
            if self.mega_line_count + self.hand[C.STARYU] >= 4:
                return 1000    # enough
            if self.mega_line_count == 0:
                return 20000   # need first body
            if self.mega_line_count == 1:
                return 15000   # want 2nd
            return 5000         # 3rd is ok
        if cid == C.MEGA_STARMIE:
            if self.staryu_on_board and self.mega_in_hand == 0:
                return 38000   # ready to evolve
            if self.mega_on_board and self.mega_in_hand >= 1:
                return 2000    # have one, extra copy
            if self.staryu_on_board:
                return 28000   # evolution piece available
            return 8000         # no staryu yet
        if cid == C.CINDERACE:
            if self.cinderace_count == 0:
                return 18000   # need Explosiveness opener
            if self.cinderace_count >= 1 and self.open_bench:
                return 12000   # 2nd body is nice
            return 2000
        if cid == C.MEOWTH_EX:
            # Meowth ex searches a Supporter on play to bench.
            # Higher priority when we need a specific supporter.
            need_supporter_search = not self.state.supporterPlayed and (
                self.hand[C.SALVATORE] == 0 and self.hand[C.HILDA] == 0
                and self.hand[C.LILLIE] == 0)
            if not self.meowth_on_board and need_supporter_search:
                return 14000 if vs_spread else 18000  # careful vs spread (gives 2 prizes)
            if not self.meowth_on_board:
                return 10000
            return 500

        # ── Search / Draw items ──
        if cid == C.BUDDY_POFFIN:
            if not self.open_bench:
                return UNNECESSARY
            if self.basic_emergency and self.copies_in_deck(C.STARYU) != 0:
                return 20000   # EMERGENCY: secure a Basic on the bench NOW (free, puts 1-2 Staryu)
            if self.mega_line_count == 0 and self.hand[C.STARYU] == 0:
                return 16000
            if self.mega_line_count <= 1:
                return 5000
            return UNNECESSARY
        if cid == C.MEGA_SIGNAL:
            if self.copies_in_deck(C.MEGA_STARMIE) == 0:
                return 150     # all prized/used -> whiff
            if self.staryu_on_board and not self.mega_in_hand and not self.mega_on_board:
                return 14000   # ready to evolve, need the Mega
            if self.mega_in_hand or self.mega_on_board:
                return 200
            return 6000         # search when we eventually need it
        if cid == C.SALVATORE:
            if self.staryu_on_board and self.mega_in_hand and not self.mega_on_board:
                return 15000   # instant evolve THIS turn
            return 200
        if cid == C.NIGHT_STRETCHER:
            need = self.discard.get(C.MEGA_STARMIE, 0) > 0 or self.discard.get(C.STARYU, 0) > 0
            return 6000 if need else 1500
        if cid == C.ULTRA_BALL:
            # EMERGENCY: fetch a Basic — but only if we can pay the 2-discard WITHOUT pitching a key
            # resource (draw supporter / win-con). Otherwise let Lillie dig instead.
            if (self.basic_emergency and self.copies_in_deck(C.STARYU) != 0
                    and self.safe_pitch_count() >= 2):
                return 18000
            need = (not self.mega_on_board and self.discard_count >= 2)
            return 8000 if need else 1000
        if cid == C.POKEGEAR:
            if self.state.supporterPlayed:
                return 500
            return 7000

        # ── Draw / refill supporters ──
        if cid in (C.LILLIE, C.HARLEQUIN):
            if self.state.supporterPlayed:
                return UNNECESSARY
            base = 9000 if cid == C.LILLIE else 6000
            if self.basic_emergency:
                base = max(base, 12000)   # fallback dig for a Basic when nothing else fetches one
            if self.me.handCount <= 3:
                base += 2000
            if self.me.handCount >= 7:
                base -= 4000
            if not self.mega_on_board and not self.mega_in_hand:
                base += 1000   # dig for pieces early
            return base
        if cid == C.HILDA:
            if self.state.supporterPlayed:
                return UNNECESSARY
            if self.field[C.STARYU] == 0 and self.hand[C.STARYU] == 0:
                return 1500    # Hilda fetches ONLY an Evolution — a dead card with no Staryu line;
                               # must never outrank a Basic-fetcher (Buddy/Ultra/Lillie)
            if not self.mega_on_board and (self.mega_in_hand or self.hand[C.STARYU]):
                return 11000   # search evolution + energy
            return 6000         # still decent draw

        # ── Disruption / recovery ──
        if cid == C.CRUSHING_HAMMER:
            if self.opp is None or len(self.opp.energies) == 0:
                return 100
            # vs_setup: deny energy is critical (Mewtwo/Trevenant need specific energy)
            if vs_setup and len(self.opp.energies) >= 1:
                return 6000
            if vs_spread:
                return 2000     # spread decks use cheap attacks, less impactful
            if self.have_ready_attacker():
                return 4500
            if len(self.opp.energies) >= 2:
                return 3500
            return 200
        if cid == C.BOSS:
            if self.state.supporterPlayed:
                return UNNECESSARY
            ko_bonus = 2000 if vs_setup else 0
            if self.active is not None and self.plan_a.ko and self.plan_a.boss:
                return 14000 + ko_bonus
            return 500

        # ── Healing / defense ──
        if cid == C.WALLY:
            if self.mega_on_board:
                bonus = 3000 if vs_aggro else 0  # more urgent vs Lucario
                for p in self.my_board():
                    if p is not None and p.id == C.MEGA_STARMIE and (p.maxHp - p.hp) >= 120:
                        return 16000 + bonus
            return 200
        if cid == C.HEROS_CAPE:
            bonus = 2000 if vs_aggro else 0  # +100HP critical vs Lucario
            if self.active is not None and self.active.id == C.MEGA_STARMIE and not (self.active.tools or []):
                return 8000 + bonus
            return 200

        # ── Energy ──
        if cid == C.WATER_ENERGY:
            rush_bonus = 2000 if vs_spread else 0  # need Mega faster vs spread
            for p in self.my_board():
                if p is not None and self.should_fuel(p) and self.attach_helps(p, None):
                    return 8000 + rush_bonus
            return 1000
        if cid == C.IGNITION_ENERGY:
            bonus = 2000 if vs_aggro else 0  # Nebula finisher vs heavy hitters
            if self.active_is_mega and not self.can_attack(self.active):
                return 10000 + bonus
            if self.active_is_mega and self.opp is not None:
                d = self._raw_dmg(NEBULA_BEAM, self.opp)
                if d > 0 and d >= (self.opp.hp or 9999):
                    return 9500 + bonus
            return 500

        return 1000

    # ── Override score() to refresh derived state before every option evaluation ──
    def score(self, o):
        self._collect()   # refresh state (opp, active, plan_a, plan_b, etc.)
        return super().score(o)

    # ── Override score_play to use hand_score in MAIN context ────────────────
    def score_play(self, o):
        card = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        if card is None:
            return 0
        return self.hand_score(card.id, ignore_count=False)

    # Stub implementations of the abstract methods (not used in MAIN PLAY dispatch
    # because we override score_play, but required by Python's ABC).
    def score_play_poke(self, card):
        return self.hand_score(card.id)
    def score_play_trainer(self, card):
        return self.hand_score(card.id)

    # ── Enhanced ATTACH scoring with per-card precision ──────────────────────
    def score_attach(self, o):
        p = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
        if not isinstance(p, Pokemon):
            return 0
        src = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        is_active = o.inPlayArea == AreaType.ACTIVE

        if src is not None and src.id == C.IGNITION_ENERGY:
            # Ignition: one-shot Nebula ENABLER, never build-up
            if not (is_active and p.id == C.MEGA_STARMIE):
                return -1
            if NEBULA_BEAM in ATTACK_COST_ENERGIES and self.can_pay(
                    list(p.energies or []), ATTACK_COST_ENERGIES[NEBULA_BEAM]):
                return -1   # already Nebula-ready
            if not self.can_attack(p):
                return 9500  # gets active attacking this turn
            if self.opp is not None and (self.effect_prevented(self.opp) or (120 < self.opp.hp <= 210)):
                return 9300  # Nebula KO/pierce
            return -1         # Jetting Blow is enough -> save Ignition

        # Water energy: generic should_fuel gated
        return super().score_attach(o)

    def attach_priority(self, p, is_active):
        concentrate = self.energy_count(p) * 600
        if p.id == C.MEGA_STARMIE:
            return 9000 + concentrate + (300 if is_active else 0)
        if p.id == C.CINDERACE:
            return 6000 + concentrate + (200 if is_active else 0)
        if p.id == C.STARYU:
            return 1500 + concentrate
        return -1

    # ── ABILITY ───────────────────────────────────────────────────────────────
    def score_ability(self, o):
        card = get_card(self.obs, o.area, o.index, self.my_index)
        if card is not None and card.id == C.CINDERACE:
            return 12000   # Explosiveness: open face-down
        return 9000

    # ── RETREAT ────────────────────────────────────────────────────────────────
    def score_retreat(self):
        active = self.me.active[0] if self.me.active else None
        if active is None:
            return -1
        # Retreat Cinderace if Mega on bench can attack (even if Cinderace can attack)
        if active.id == C.CINDERACE:
            ready_mega_on_bench = any(
                p is not None and p.id == C.MEGA_STARMIE and self.can_attack(p)
                for p in self.me.bench)
            if ready_mega_on_bench:
                return 7000
        # Generic retreat: can't attack and bench has a ready attacker
        if not self.can_attack(active) and self.bench_attacker_ready():
            return 6000
        return -1

    # ── EVOLVE ─────────────────────────────────────────────────────────────────
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
        return 0

    def score_evolves_choice(self, card):
        if card is None:
            return 1000
        if card.id in (C.MEGA_STARMIE, C.STARYU):
            return 3000
        if card.id == C.CINDERACE:
            return 2000
        return 1000

    # ── ATTACK ─────────────────────────────────────────────────────────────────
    def score_attack(self, o):
        active = self.active
        opp = self.opp
        if active is None or opp is None:
            return 800
        aid = o.attackId
        dmg = self._raw_dmg(aid, opp)

        # Game-winning KO
        if dmg > 0 and opp.hp <= dmg and prize_count(opp) >= len(self.me.prize):
            return 95000

        if aid == TURBO_FLARE:
            # Turbo Flare: search 3 Basic Energy to bench. Only do this once —
            # after we've accelerated enough energy, switch to Mega for real attacks.
            # Check if we still need energy acceleration.
            if not (self.mega_on_board and not self.have_ready_attacker()):
                return 800   # don't waste turns on Turbo Flare
            # Check how much energy is already on our board (expanded count)
            board_energy = sum(len(p.energies or []) for p in self.my_board() if p is not None)
            if board_energy >= 6:   # already have enough for multiple attacks
                return 800
            # Also check: if Mega is already on bench with at least 1 energy, we can
            # switch and attack — no need for more Turbo Flare
            for p in self.me.bench:
                if p is not None and p.id == C.MEGA_STARMIE and len(p.energies or []) >= 1:
                    return 800   # promote Mega instead
            return 4000          # first Turbo Flare for acceleration
        if dmg <= 0:
            return 500

        score = 1000 + min(dmg, 320)
        if aid == NEBULA_BEAM:
            score += 1500
            if self.effect_prevented(opp):
                score += 2000   # pierce
        if aid == JETTING_BLOW:
            score += 400
            bench_ko = self._jett_spread_score()
            if bench_ko:
                score += bench_ko
        if opp.hp <= dmg:
            score += 2500 + prize_count(opp) * 250
            if prize_count(opp) >= 2:
                score += 1000   # multi-prize KO bonus
        return score

    # ── Sub-select scorers (enhanced) ──────────────────────────────────────────
    def score_spread_target(self, card):
        """DAMAGE_COUNTER targeting: prioritize low-HP evolution bases and
        Jetting-Blow-finishable targets — like Dragapult's HP-zone system.
        Handles BOTH bench targets (spread) and active targets (Phantom Dive-style)."""
        hp = getattr(card, 'hp', 0)
        d = card_table.get(card.id)
        can_evolve = d is not None and (d.stage1 or d.stage2 or d.evolvesFrom)
        is_active = hasattr(card, 'is_active') or False   # approximated below

        sc = 5000 - hp * 14 + prize_count(card) * 250

        # Deny evolution: kill the basic before it becomes a threat
        if can_evolve and hp <= 80:
            sc += 2500           # e.g. Froslass basic / Riolu / Dreepy
        elif can_evolve and hp <= 110:
            sc += 1200           # bulkier basics

        # Jetting Blow 50-spread KO zone (bench targets only)
        if 0 < hp <= 50:
            sc += 2000

        # Near-death finish
        if hp <= 30:
            sc += 1500

        # High-value multi-prize targets get extra weight if they're weak
        if hp <= 60 and prize_count(card) >= 2:
            sc += 1000

        # Active target bonus: we can reach it without switching
        # (We don't know which are active here, so guess by high HP + tool presence)
        hp_from_attr = getattr(card, 'hp', 0)
        tools = getattr(card, 'tools', None)
        if tools is not None and len(tools) > 0:
            sc -= 2000           # active with a tool = harder to KO, waste spread

        return sc

    def score_active_choice(self, o, card):
        if not isinstance(card, Pokemon):
            return 0
        if o.playerIndex == self.op_index:
            return self.gust_value(card)
        if o.playerIndex != self.my_index:
            return 0
        # Promote priority: Mega Starmie (attacker) > Cinderace > Meowth ex > Staryu
        score = len(card.energies) * 10
        if card.id == C.MEGA_STARMIE:
            score += 300
            # If we can attack for lethal right now, it's urgent
            if self.opp is not None:
                for aid in self.payable_attacks(card):
                    if self._raw_dmg(aid, self.opp) >= self.opp.hp:
                        score += 500
        elif card.id == C.CINDERACE:
            score += 180
        elif card.id == C.MEOWTH_EX:
            score += 60
        elif card.id == C.STARYU:
            score += 50
        score += getattr(card, 'hp', 0) // 30
        return score + 1

    def score_setup_active(self, card):
        if card is None:
            return 0
        if card.id == C.CINDERACE:
            return 50   # Explosiveness -> can Turbo Flare T1
        if card.id == C.STARYU:
            return 30
        if card.id == C.MEOWTH_EX:
            return 20
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
        if cid == C.MEOWTH_EX:
            return 120 - 30 * n
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
        elif cid == C.MEOWTH_EX:
            score += 60 if self.field[C.MEOWTH_EX] == 0 else 10
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
            return 80   # plentiful (9) -> preferred pitch
        if cid == C.IGNITION_ENERGY:
            return 30 if self.hand[cid] >= 2 else -30
        if self.is_energy(cid):
            return 40
        if cid == C.MEGA_STARMIE:
            return -200   # never pitch the win-con
        if cid == C.MEOWTH_EX:
            return -80 if self.field[C.MEOWTH_EX] == 0 else 20  # keep basic body
        if cid in (C.STARYU, C.SALVATORE, C.MEGA_SIGNAL):
            return -100 if self.hand[cid] <= 1 else 0
        if cid in (C.LILLIE, C.HARLEQUIN):
            return -60 if self.hand[cid] <= 1 else 20   # don't pitch our draw engine (e.g. to Ultra Ball)
        if cid == C.CINDERACE:
            return -40 if self.field[cid] == 0 else 10
        if self.hand[cid] >= 2:
            return 60
        return 0

    def safe_pitch_count(self):
        """How many hand cards can be discarded for Ultra Ball WITHOUT losing a key resource
        (draw supporter / win-con piece). Uses score_discard(c) >= 0 as 'safe to pitch'."""
        n = 0
        for c in self.me.hand:
            if c.id == C.ULTRA_BALL:
                continue
            if self.score_discard(c) >= 0:
                n += 1
        return n

    def score_putback(self, card):
        if card is None:
            return 0
        if self.hand[card.id] >= 2:
            return 60
        if card.id in (C.STARYU, C.MEGA_STARMIE, C.CINDERACE, C.MEOWTH_EX):
            return -40
        return 10

    @property
    def discard_count(self):
        return sum(1 for c in self.me.hand if c.id not in (C.MEGA_STARMIE, C.CINDERACE, C.MEOWTH_EX)
                   and not self.is_energy(c.id))


_impl = make_agent(MegaStarmiePolicy, my_deck, DIAG)


def agent(obs_dict):
    return _impl(obs_dict)
