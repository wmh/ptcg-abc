from __future__ import annotations

import os
from collections import defaultdict

from cg.api import (
    AreaType, Card, CardType, EnergyType, Observation, OptionType, Pokemon,
    SelectContext, all_card_data, all_attack, to_observation_class,
)


# ── Card IDs (胡地小人 / Alakazam + Dudunsparce single-prize) ─────────────────
class C:
    ABRA = 741            # Basic -> Kadabra
    KADABRA = 742         # Stage1 (Psychic Draw on evolve) -> Alakazam
    ALAKAZAM = 743        # Stage2 attacker: Powerful Hand = 20 dmg x cards in hand
    ALAKAZAM_PSY = 245    # Stage2 TECH (1x): Psychic = 10 + 50/energy on opp Active.
                          # It does DAMAGE (not counters) -> bypasses Mist Energy; punishes
                          # energy-loaded ex. Our answer to Mist decks (Dragapult/Crustle).
    DUNSPARCE = 305       # Basic -> Dudunsparce (7-06: switched to id305 per ladder-#1 Majkel1337's
                          # list — 70HP + Trading Places free switch; the attack-id constants
                          # 423/424 below always belonged to THIS printing, not id65)
    DUDUNSPARCE = 66      # Stage1 draw engine (Run Away Draw)
    PSYDUCK = 858         # Damp (ability lock tech)
    SHAYMIN = 343         # Flower Curtain (protect non-Rule-Box bench)
    GENESECT = 142        # ACE Nullifier (with tool)
    FEZANDIPITI = 140     # ex (2 prizes): Flip the Script (+3 draw if we were KO'd last
                          # turn) + Cruel Arrow (100 snipe). Majkel 7-12 mirror tech.

    PSYCHIC_ENERGY = 5
    TELEPATH_ENERGY = 19  # special, provides {P}
    ENRICHING_ENERGY = 13 # ACE SPEC energy

    BUDDY_POFFIN = 1086
    POKE_PAD = 1152
    HILDA = 1225          # Supporter: search Evolution + Energy
    DAWN = 1231           # Supporter: search Basic+Stage1+Stage2
    RARE_CANDY = 1079
    BOSS_ORDERS = 1182
    BATTLE_CAGE = 1264    # Stadium: block bench damage counters (cut from the 7-12 list)
    XEROSIC = 1197        # Supporter: opp discards down to 3 cards — in the mirror this
                          # caps their Powerful Hand at 60 AND strips resources (7-12 Majkel
                          # runs 3; mirror opponents who beat us played it 0.56x/game)
    NIGHTTIME_MINE = 1266 # Stadium: each TERA Pokémon's attacks cost +{C} (both sides —
                          # we run zero Tera, so it's a pure tax on Dragapult ex etc.)
    ENHANCED_HAMMER = 1081  # Item: discard a Special Energy from opp (e.g. Mist Energy)
    LUCKY_HELMET = 1156   # Tool: draw 2 when damaged
    WONDROUS_PATCH = 1146
    NIGHT_STRETCHER = 1097
    SACRED_ASH = 1129
    LANA_AID = 1184


POWERFUL_HAND = 1072   # Alakazam 743: place 2 counters (20 dmg) per card in hand, on opp Active
PSYCHIC_ATK = 339      # Alakazam 245: 10 + 50 per energy on opp Active (DAMAGE; bypasses Mist)
STRANGE_HACKING = 338  # Alakazam 245: confuse + move opp's damage counters around
SUPER_PSY_BOLT = 1071  # Kadabra: 30
ALAKAZAM_IDS = {743, 245}   # both Stage-2 Alakazam attackers (Powerful Hand / Psychic)
ABRA_TELEPORT = 1070   # Abra: 10 + switch
DUDUN_LAND_CRUSH = 76  # Dudunsparce: 90 (rarely; engine instead)
DUNSPARCE_TRADE = 423  # Dunsparce: switch
DUNSPARCE_RAM = 424

ENERGY_TYPES = {C.PSYCHIC_ENERGY, C.TELEPATH_ENERGY, C.ENRICHING_ENERGY}
ATTACKER_IDS = {C.ALAKAZAM, C.KADABRA}
# Mega Lucario aggro package (Riolu/Mega Lucario + Solrock/Lunatone/Hariyama flank).
# These decks don't care about their own hand size, so Xerosic's discard-to-3 is a
# wasted supporter slot against them (7-14 ladder autopsy: we burned Xerosic 2-5x per
# game vs Lucario while losing the prize race 0-2 to 5-6).
RUSH_LINE_IDS = {673, 674, 675, 676, 677, 678}
LOW_DECK_COUNT = 6
pre_turn = -1

_DIAG = {"decisions": 0, "policy_ok": 0, "policy_fallback": 0,
         "obs_fallback": 0, "deck_returns": 0, "errors": {}}


def _diag_record_error(exc):
    k = type(exc).__name__ + ": " + str(exc)[:160]
    _DIAG["errors"][k] = _DIAG["errors"].get(k, 0) + 1


def diag_reset():
    _DIAG.update({"decisions": 0, "policy_ok": 0, "policy_fallback": 0,
                  "obs_fallback": 0, "deck_returns": 0, "errors": {}})


def diag_snapshot():
    s = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _DIAG.items()}
    s["fallback_rate"] = (s.get("policy_fallback", 0) + s.get("obs_fallback", 0)) / max(1, s["decisions"])
    return s


def _resolve_deck_path():
    import sys
    cands = []
    if "__file__" in globals():
        cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "deck.csv"))
    cands += ["deck.csv", "/kaggle_simulations/agent/deck.csv"]
    cands += [os.path.join(p, "deck.csv") for p in sys.path if p]
    for p in cands:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("deck.csv not found")


DECK_PATH = _resolve_deck_path()
with open(DECK_PATH) as f:
    my_deck = [int(x) for x in f.read().splitlines() if x.strip()]
if len(my_deck) != 60:
    raise ValueError(f"deck.csv must have 60 ids, got {len(my_deck)}")

all_card = all_card_data()
card_table = {c.cardId: c for c in all_card}

# Active-ability Item-lock cards (Tyranitar / Jellicent ex …). Some lock cards
# (e.g. Budew) carry the effect without an exposed skill, so we ALSO detect lock
# from game state (hold Items but none playable) — see AlakazamPolicy._item_locked.
ITEM_LOCK_IDS = set()
for _c in all_card:
    for _s in (_c.skills or []):
        _t = (_s.text or '')
        if 'Item' in _t and 'Active Spot' in _t and 'play' in _t and ('opponent' in _t or 'neither' in _t):
            ITEM_LOCK_IDS.add(_c.cardId)

# CRITICAL for Alakazam: Powerful Hand "places damage counters" = an EFFECT, so a
# target that "prevents all effects of attacks done to it" takes 0 from it.
#   - special energies that grant this (Mist Energy 11, Rock Fighting Energy 20)
#   - Pokémon/Tools whose own ability prevents effects of attacks done to itself
EFFECT_PREVENT_ENERGY = set()
EFFECT_PREVENT_SELF = set()
for _c in all_card:
    _ct = _c.cardType
    for _s in (_c.skills or []):
        _t = (_s.text or '')
        if 'effects of attacks' in _t and 'prevent' in _t.lower():
            if _ct in (CardType.SPECIAL_ENERGY, CardType.BASIC_ENERGY):
                EFFECT_PREVENT_ENERGY.add(_c.cardId)
            elif 'to this Pokémon' in _t or 'to this Pok' in _t:
                EFFECT_PREVENT_SELF.add(_c.cardId)

# GENERAL energy rule: attach only what an attack costs — never over-fill — UNLESS the attack
# scales with energy attached to ITSELF (then more = more damage). Disruption (energy removal)
# is handled automatically: it drops the count back below the need, so we just refill.
ATTACK_COST = {}                 # attackId -> number of energies in its cost
ATTACK_COST_ENERGIES = {}        # attackId -> list of required EnergyType (0=Colorless, 5=Psychic…)
SELF_SCALING_ATTACKS = set()     # attacks whose damage grows with energy on the attacker
for _a in all_attack():
    ATTACK_COST[_a.attackId] = len(_a.energies or [])
    ATTACK_COST_ENERGIES[_a.attackId] = list(_a.energies or [])
    _t = (_a.text or '').lower()
    if 'for each' in _t and 'energy attached to this' in _t:
        SELF_SCALING_ATTACKS.add(_a.attackId)

# What TYPE each energy card provides (Enriching -> Colorless 0; Telepath/Basic {P} -> Psychic 5).
# Critical: attaching energy must satisfy the attack's TYPE requirement, not just its count.
ENERGY_PROVIDES = {}
for _c in all_card:
    if _c.cardType in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY):
        ENERGY_PROVIDES[_c.cardId] = getattr(_c, 'energyType', 0)

# Situational-tech triggers (only bench the tech when the opponent's board warrants it):
#   Shaymin (Flower Curtain) matters ONLY vs bench-damage (spread/snipe) attacks;
#   Psyduck (Damp) matters ONLY vs abilities that require KO-ing the user itself.
BENCH_DAMAGE_ATTACKS = set()
for _a in all_attack():
    _t = (_a.text or '').lower()
    if ('benched' in _t and 'damage' in _t) or ('to each of your opponent' in _t and 'damage' in _t):
        BENCH_DAMAGE_ATTACKS.add(_a.attackId)
SELF_KO_ABILITY_IDS = set()
for _c in all_card:
    for _s in (_c.skills or []):
        _t = (_s.text or '').lower()
        if 'knock out' in _t and ('this pokémon' in _t or 'this pokemon' in _t or 'itself' in _t):
            SELF_KO_ABILITY_IDS.add(_c.cardId)


# ── generic helpers (proven scaffolding) ─────────────────────────────────────
def normalize_selection(ranked, scores, select):
    n = len(select.option)
    minc = max(0, min(select.minCount, n)); maxc = max(minc, min(select.maxCount, n))
    out, seen = [], set()
    for i in ranked:
        if not (0 <= i < n) or i in seen:
            continue
        s = scores[i] if i < len(scores) else 0
        if s > 0 or len(out) < minc:
            out.append(i); seen.add(i)
        if len(out) >= maxc:
            break
    for i in range(n):
        if len(out) >= minc:
            break
        if i not in seen:
            out.append(i); seen.add(i)
    return out


def _legal_fallback(select):
    try:
        n = len(select.option); return list(range(min(max(0, select.minCount), n)))
    except Exception:
        return []


def _legal_fallback_from_dict(obs_dict):
    try:
        sel = obs_dict.get("select") or {}
        return list(range(min(max(0, sel.get("minCount", 0)), len(sel.get("option") or []))))
    except Exception:
        return []


def _safe_get(seq, i):
    try:
        if seq is None or i is None or i < 0 or i >= len(seq):
            return None
        return seq[i]
    except Exception:
        return None


def get_card(obs, area, index, pi):
    try:
        player = obs.current.players[pi]
        match area:
            case AreaType.DECK: return _safe_get(getattr(obs.select, "deck", None), index)
            case AreaType.HAND: return _safe_get(getattr(player, "hand", None), index)
            case AreaType.DISCARD: return _safe_get(getattr(player, "discard", None), index)
            case AreaType.ACTIVE: return _safe_get(getattr(player, "active", None), index)
            case AreaType.BENCH: return _safe_get(getattr(player, "bench", None), index)
            case AreaType.PRIZE: return _safe_get(getattr(player, "prize", None), index)
            case AreaType.STADIUM: return _safe_get(getattr(obs.current, "stadium", None), index)
            case AreaType.LOOKING: return _safe_get(getattr(obs.current, "looking", None), index)
            case _: return None
    except Exception:
        return None


def prize_count(p):
    d = card_table.get(p.id)
    return (3 if d.megaEx else 2 if d.ex else 1) if d else 1


def is_energy(cid):
    d = card_table.get(cid)
    return cid in ENERGY_TYPES or (d is not None and d.cardType in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY))


# ── Alakazam policy ──────────────────────────────────────────────────────────
class AlakazamPolicy:
    def __init__(self, obs: Observation):
        self.obs = obs
        self.state = obs.current
        self.select = obs.select
        self.context = self.select.context
        self.my_index = self.state.yourIndex
        self.op_index = 1 - self.my_index
        self.me = self.state.players[self.my_index]
        self.opponent = self.state.players[self.op_index]
        self.stadium_id = self.state.stadium[0].id if self.state.stadium else 0
        self.field = defaultdict(int)
        self.hand = defaultdict(int)
        self.discard = defaultdict(int)
        for p in self._my_board():
            if p is not None:
                self.field[p.id] += 1
        for c in self.me.hand:
            self.hand[c.id] += 1
        for c in self.me.discard:
            self.discard[c.id] += 1

    def _my_board(self):
        return self.me.active + self.me.bench

    def _low_deck(self):
        return self.me.deckCount <= LOW_DECK_COUNT

    def _deck_preserve(self):
        """Don't mill ourselves out of a WINNING game (real-ladder bug: we filtered our
        deck to 0 while ahead enough to close). If we already have a powered attacker and a
        hand big enough to keep KO-ing (Powerful Hand = 20×hand), we don't NEED more cards —
        and once the deck is down to about the number of prizes we still have to take, every
        extra optional draw/filter risks decking out before the last prize. So: stop optional
        drawing and just attack ~1 KO per turn, keeping enough deck to draw 1/turn to the end."""
        if not self._have_attacker():
            return False
        opp = self.opponent.active[0] if self.opponent.active else None
        if opp is None:
            return False
        remaining_prizes = len(self.me.prize)                 # ≈ turns we still need
        big_hand = 20 * self.me.handCount >= max(opp.hp, 130)  # can essentially KO a body now
        deck_low = self.me.deckCount <= remaining_prizes + 4   # keep a draw-1/turn buffer
        return big_hand and deck_low

    def _hand_size(self):
        return self.me.handCount

    def _energy_count(self, p):
        return len(p.energies) if p is not None else 0

    @staticmethod
    def _can_pay(attached, cost):
        """Can `attached` (list of EnergyType) pay `cost` (list of EnergyType, 0=Colorless)?
        Specific-type requirements must be met by that exact type; Colorless by anything left."""
        from collections import Counter
        have = Counter(attached)
        colorless = 0
        for req in cost:
            if req == EnergyType.COLORLESS:
                colorless += 1
            elif have.get(req, 0) > 0:
                have[req] -= 1
            else:
                return False            # e.g. a Psychic requirement with only Colorless attached
        return sum(have.values()) >= colorless

    def _can_attack(self, p):
        """TYPE-AWARE: can p actually pay one of its attacks with its currently attached
        energy? (1 Enriching = Colorless does NOT pay Powerful Hand's Psychic cost.)"""
        c = card_table.get(p.id)
        if c is None:
            return False
        attached = list(p.energies or [])
        return any(aid in ATTACK_COST_ENERGIES and self._can_pay(attached, ATTACK_COST_ENERGIES[aid])
                   for aid in (c.attacks or []))

    def _should_fuel(self, p):
        """Attach more energy ONLY while p still can't pay an attack (type-aware), so we never
        over-fill — UNLESS an attack scales with its own energy (then keep attaching)."""
        c = card_table.get(p.id)
        if c is None or not (c.attacks or []):
            return False
        if any(aid in SELF_SCALING_ATTACKS for aid in c.attacks):
            return True
        return not self._can_attack(p)

    def _attach_helps(self, p, src):
        """Would attaching energy `src` actually let p pay an attack it currently can't?
        (A Colorless Enriching onto a Psychic-needing Alakazam does NOT help -> don't waste it.)"""
        if src is None:
            return True
        prov = ENERGY_PROVIDES.get(src.id)
        if prov is None:
            return True
        new = list(p.energies or []) + [prov]
        c = card_table.get(p.id)
        return any(aid in ATTACK_COST_ENERGIES and self._can_pay(new, ATTACK_COST_ENERGIES[aid])
                   for aid in (c.attacks or []))

    def _opp_threatens_bench(self):
        """Opponent has a bench-damaging (spread/snipe) attacker in play -> Shaymin matters."""
        for p in (self.opponent.active + self.opponent.bench):
            c = card_table.get(p.id) if p is not None else None
            if c and any(aid in BENCH_DAMAGE_ATTACKS for aid in (c.attacks or [])):
                return True
        return False

    def _opp_is_rush(self):
        """Opponent is the Mega Lucario aggro package -> their hand size is irrelevant,
        so the supporter slot must go to draw (Powerful Hand fuel), not Xerosic."""
        return any(p is not None and p.id in RUSH_LINE_IDS
                   for p in (self.opponent.active + self.opponent.bench))

    def _opp_has_tera(self):
        """Opponent has a Tera Pokémon in play -> Nighttime Mine taxes their attacks."""
        for p in (self.opponent.active + self.opponent.bench):
            c = card_table.get(p.id) if p is not None else None
            if c is not None and getattr(c, 'tera', False):
                return True
        return False

    def _opp_has_self_ko_ability(self):
        """Opponent has an ability that KOs the user itself -> Psyduck (Damp) matters."""
        return any(p is not None and p.id in SELF_KO_ABILITY_IDS
                   for p in (self.opponent.active + self.opponent.bench))

    def _energy_in_hand(self):
        return any(is_energy(c.id) for c in self.me.hand)

    def _psychic_in_hand(self):
        """A {P}-providing energy in hand (the ONLY kind that fuels our attacks — Enriching's
        Colorless does not). 'Energy in hand' that is just Enriching still leaves us starved."""
        return any(ENERGY_PROVIDES.get(c.id) == EnergyType.PSYCHIC for c in self.me.hand)

    def _energy_starved(self):
        """We have an Alakazam-line attacker in play (or a Kadabra + Alakazam in hand to
        evolve) that CAN'T attack, and no usable {P} energy in hand to fix it. With only 6
        energy in 60 cards, energy is the bottleneck — searches should grab a {P} energy."""
        bodies = [p for p in (self.me.active + self.me.bench) if p is not None]
        has_alakazam = any(p.id in ALAKAZAM_IDS for p in bodies)
        coming = any(p.id == C.KADABRA for p in bodies) and self.hand[C.ALAKAZAM] > 0
        if not (has_alakazam or coming):
            return False
        if any(p.id in ALAKAZAM_IDS and self._can_attack(p) for p in bodies):
            return False                       # already have an attacker that can actually attack
        return not self._psychic_in_hand()

    def _effect_prevented(self, target):
        """True if attack EFFECTS done to `target` are prevented (Mist Energy / Rock
        Fighting Energy attached, or a self-prevention ability). Powerful Hand places
        damage counters = an effect, so it does 0 to such a target."""
        if target is None:
            return False
        if target.id in EFFECT_PREVENT_SELF:
            return True
        for e in (getattr(target, 'energyCards', None) or []):
            if getattr(e, 'id', None) in EFFECT_PREVENT_ENERGY:
                return True
        return False

    def _opp_active_has_prevent_energy(self):
        """Opponent's Active has Mist/Rock-Fighting special energy blocking Powerful
        Hand — Enhanced Hammer should strip it before we attack."""
        opp = self.opponent.active[0] if self.opponent.active else None
        if opp is None:
            return False
        return any(getattr(e, 'id', None) in EFFECT_PREVENT_ENERGY
                   for e in (getattr(opp, 'energyCards', None) or []))

    # — damage —
    def _alakazam_damage(self, attack_id, target):
        if target is None:
            return 0
        if attack_id == POWERFUL_HAND:
            if self._effect_prevented(target):
                return 0                     # Mist Energy etc. negates "place counters"
            return 20 * self._hand_size()    # counter placement -> no weakness
        if attack_id == PSYCHIC_ATK:
            # 245 Alakazam: 10 + 50 per energy on opp Active. This is DAMAGE, so it goes
            # THROUGH Mist Energy and applies Weakness — our answer to Mist/energy decks.
            dmg = 10 + 50 * len(target.energies)
        elif attack_id == SUPER_PSY_BOLT:
            dmg = 30
        elif attack_id == ABRA_TELEPORT:
            dmg = 10
        elif attack_id == DUNSPARCE_RAM:
            dmg = 20
        elif attack_id == DUDUN_LAND_CRUSH:
            dmg = 90
        else:
            dmg = 0
        od = card_table.get(target.id)
        if od is not None:
            if od.weakness == EnergyType.PSYCHIC:
                dmg *= 2
            elif od.resistance == EnergyType.PSYCHIC:
                dmg = max(0, dmg - 30)
        return dmg

    def _active_best_dmg(self, target):
        a = self.me.active[0] if self.me.active else None
        if a is None or target is None:
            return 0
        if self._energy_count(a) >= 1:
            if a.id == C.ALAKAZAM:
                return self._alakazam_damage(POWERFUL_HAND, target)
            if a.id == C.ALAKAZAM_PSY:
                return self._alakazam_damage(PSYCHIC_ATK, target)
            if a.id == C.KADABRA:
                return self._alakazam_damage(SUPER_PSY_BOLT, target)
        return 0

    def _gust_ko_targets(self):
        return [p for p in self.opponent.bench if p is not None and self._active_best_dmg(p) >= p.hp]

    def _target_value(self, p):
        """Tactical worth of removing opponent Pokémon p (ported from the official
        sample agents): prizes + invested energy/tools + evolution stage; avoid
        wasting a KO on a disposable draw-support basic."""
        d = card_table.get(p.id)
        s = prize_count(p) * 1000
        s += len(p.energies) * 150
        s += len(getattr(p, 'tools', []) or []) * 100
        if d is not None:
            if getattr(d, 'stage2', 0):
                s += 250
            elif getattr(d, 'stage1', 0):
                s += 350   # Morgrem/Gabite: deny the stage-2 boss it becomes (Majkel's picks)
        if p.id in (144, 322, 323, 337):     # Squawkabilly ex / Noctowl / Fan Rotom / Archaludon ex
            s -= 200
        if p.id == 112 and len(p.energies) >= 1:   # Munkidori — Majkel rarely gusts it
            s += 100
        s += getattr(p, 'hp', 0)
        return s

    def _gust_value(self, p):
        d = self._active_best_dmg(p)
        # Majkel gusts what the ACHIEVABLE Powerful Hand can KO (he pulls 210HP Ogerpon/Fez
        # ex up and draws to 11+), not just what the current hand kills.
        if self._have_attacker() and not self._effect_prevented(p):
            d = max(d, 20 * self._achievable_hand())
        if d >= p.hp:
            if prize_count(p) >= len(self.me.prize):
                return 90000        # KO-ing this wins the game — gust it
            return 8000 + self._target_value(p)
        return max(1, d)

    # — entry —
    def rank(self):
        if not self.select.option or self.select.maxCount == 0:
            return [], []
        scores = [self._score(o) for o in self.select.option]
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return ranked, scores

    def choose(self):
        ranked, scores = self.rank()
        return normalize_selection(ranked, scores, self.select)

    def _score(self, o):
        t = o.type
        # First-or-second: GO FIRST. The Elo≥1150 Alakazam pool goes first 35/35 (unanimous) —
        # a setup/evolution deck wants the extra turn to build the Abra→Kadabra→Alakazam line and
        # get the Dudunsparce draw engine online before it has to attack. (Was hardcoded second.)
        if self.context == SelectContext.IS_FIRST:
            return 100 if t == OptionType.YES else 0
        if t == OptionType.NUMBER:
            return o.number if o.number is not None else 0
        if t == OptionType.YES:
            return 1
        if t == OptionType.NO:
            return 0
        if t == OptionType.CARD:
            return self._score_card(o)
        if t == OptionType.PLAY:
            return self._score_play(o)
        if t in (OptionType.ENERGY, OptionType.ATTACH):
            return self._score_attach(o)
        if t == OptionType.EVOLVE:
            return self._score_evolve(o)
        if t == OptionType.ABILITY:
            return self._score_ability(o)
        if t == OptionType.RETREAT:
            return self._score_retreat()
        if t == OptionType.ATTACK:
            return self._score_attack(o)
        if t == OptionType.END:
            return 0
        return 0

    def _item_locked(self):
        """Are we Item-locked (can't play Item cards)? Detect from a known lock
        ability on the opponent's Active, OR from game state: we hold Item card(s)
        but the engine offers no way to play any of them."""
        opp = self.opponent.active[0] if self.opponent.active else None
        if opp is not None and opp.id in ITEM_LOCK_IDS:
            return True
        items = [c for c in self.me.hand
                 if card_table.get(c.id) is not None and card_table[c.id].cardType == CardType.ITEM]
        if not items:
            return False
        for o in self.select.option:
            if o.type == OptionType.PLAY:
                c = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
                if c is not None and card_table.get(c.id) is not None and card_table[c.id].cardType == CardType.ITEM:
                    return False   # an Item is playable → not locked
        return True

    def _bench_attacker_ready(self):
        """A benched Alakazam that already has the energy to attack (Powerful Hand
        needs 1 {P}). If one exists, we want IT active, not a Dunsparce/Dudunsparce."""
        return any(p is not None and p.id in ALAKAZAM_IDS and self._energy_count(p) >= 1
                   for p in self.me.bench)

    # — abilities —
    def _score_ability(self, o):
        card = get_card(self.obs, o.area, o.index, self.my_index)
        if card is None:
            return 0
        if card.id == C.DUDUNSPARCE:
            # Run Away Draw: draw 3 + shuffle this Pokémon back into the deck.
            if self.me.deckCount <= 7:        # hard deck-out floor
                return -1
            if o.area != AreaType.BENCH:
                # ACTIVE copy: CYCLE this weak active out and promote a ready benched
                # attacker (or escape Item-lock), then attack the same turn. This is
                # REPOSITIONING TO ATTACK, not filtering — so it is ALWAYS allowed, even in
                # deck-preserve mode (getting the powered Alakazam active to swing is the
                # whole point). Bug fixed: gating this on _deck_preserve stranded a powered
                # Alakazam on the bench (Dudunsparce active, 0 energy, can't retreat) -> no
                # attacks -> no_offense loss.
                if self._item_locked() or self._bench_attacker_ready():
                    return 14000
                # (7-08: liberal active-copy cycling (Majkel 318x) was tried at 12800 and
                # the mirror A/B REGRESSED — reverted; see the bench-copy sequencing note.)
                return -1
            # BENCHED copy = the draw engine (pure filtering). Draw-engine decks WIN by
            # drawing aggressively (big hand = big Powerful Hand) — blanket deck-out guards
            # regressed cabt — so we draw, EXCEPT: when we already have a winning hand and the
            # deck is low, stop filtering ourselves out of a won game (real-ladder bug).
            if self._deck_preserve():
                return -1
            # NB: top pilots activate Run Away Draw ~1/4 as often as we did (MAIN ABILITY 163 vs
            # our 622) — but a blunt hand-cap gave ~0 divergence gain here and risks the documented
            # cabt regression (deck-out guards hurt cabt), so we keep the aggressive-draw identity
            # and leave "draw less" as a separate real-ladder A/B. Only the high-hand floor stays.
            if self.me.handCount >= 14 and self.me.deckCount <= 12:
                return -1
            # SEQUENCING (Majkel matchup mining 7-08, vs Grimmsnarl 1449 + Lucario 324 MAIN):
            # he fires Run Away Draw BEFORE the evolve/bench block (ABILITY his 157 vs our 43;
            # our EVOLVE:Dudunsparce 151 / EVOLVE:Kadabra 144 over-picks are the cascade of
            # drawing late). Draw first = decide the rest of the turn with 3 more cards, and
            # the engine body shuffles itself away freeing the bench slot before we re-bench.
            return 22000
        if card.id == C.FEZANDIPITI:
            # Flip the Script: free +3 cards (= +60 Powerful Hand), no shuffle-back cost.
            # Fire it FIRST like Run Away Draw — decide the rest of the turn with the
            # bigger hand (engine only offers it when legal).
            return 21500
        return 9000

    # — play —
    def _score_play(self, o):
        card = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        if card is None:
            return 0
        d = card_table.get(card.id)
        if d is None:
            return 0
        if d.cardType == CardType.POKEMON:
            return self._score_play_poke(card)
        return self._score_play_trainer(card)

    def _score_play_poke(self, card):
        cid = card.id; n = self.field[cid]
        if cid == C.ABRA:
            # Majkel (7-05, 7275 MAIN decisions): moderate bench — our #1 over-pick was
            # flooding bodies (PLAY:Dunsparce 548x / Abra 152x). 3 line bodies is plenty.
            line = (self.field[C.ABRA] + self.field[C.KADABRA]
                    + self.field[C.ALAKAZAM] + self.field[C.ALAKAZAM_PSY])
            if line >= 3:
                return 1500
            return 20000 - 250 * n
        if cid == C.DUNSPARCE:
            if self.field[C.DUNSPARCE] + self.field[C.DUDUNSPARCE] >= 2:
                return 1200   # cap at 2 engine bodies
            return 18500 - 250 * n
        if cid == C.SHAYMIN:
            # Flower Curtain protects the bench from attack damage -> bench it ONLY vs a
            # bench-damage (spread/snipe) opponent; otherwise it just clogs a bench slot.
            # (Covers the mirror too: opp Fezandipiti ex's Cruel Arrow is a bench snipe.)
            return 17000 if (n == 0 and self._opp_threatens_bench()) else -1
        if cid == C.FEZANDIPITI:
            # 1x tech: bench for Flip the Script (+3 cards = +60 Powerful Hand on our
            # comeback turns). It's a 2-prize gust target, so it needs a spare slot —
            # below every line piece, above nothing-better.
            return 10000 if n == 0 else -1
        if cid == C.PSYDUCK:
            # Damp only locks self-KO abilities (almost nothing in this meta) -> bench it
            # ONLY when the opponent actually has such an ability in play.
            return 9000 if (n == 0 and self._opp_has_self_ko_ability()) else -1
        if cid == C.GENESECT:
            return 9000 if n == 0 else -1
        return 14000 - 200 * n

    def _alakazam_ready(self):
        a = self.me.active[0] if self.me.active else None
        return a is not None and a.id in ALAKAZAM_IDS and self._energy_count(a) >= 1

    def _need_pieces(self):
        return self.field[C.ALAKAZAM] < 1

    def _open_bench(self):
        return sum(1 for p in self.me.bench if p is not None) < getattr(self.me, "benchMax", 5)

    def _achievable_hand(self):
        """Biggest hand we can realistically reach THIS turn (Powerful Hand = 20×hand):
        current hand + Run Away Draw (+3) + one draw/search Supporter (~+1 net)."""
        extra = 0
        if self.me.deckCount > 7 and any(p is not None and p.id == C.DUDUNSPARCE for p in self.me.bench):
            extra += 3
        if not self.state.supporterPlayed and (self.hand[C.HILDA] or self.hand[C.DAWN]):
            extra += 1
        return self.me.handCount + extra

    def _have_attacker(self):
        a = self.me.active[0] if self.me.active else None
        return (a is not None and a.id in ALAKAZAM_IDS and self._energy_count(a) >= 1) or self._bench_attacker_ready()

    def _lethal_now(self):
        """Powerful Hand KOs the opp Active with the CURRENT hand and a ready active attacker.
        Majkel's line: once lethal, STOP developing (every card played from hand = -20 damage)
        and attack — we over-sequenced plays before attacking (EVOLVE:Kadabra 874x over-pick)."""
        opp = self.opponent.active[0] if self.opponent.active else None
        a = self.me.active[0] if self.me.active else None
        return (opp is not None and a is not None and a.id in ALAKAZAM_IDS
                and self._energy_count(a) >= 1 and not self._effect_prevented(opp)
                and 20 * self.me.handCount >= opp.hp)

    def _ko_active_reachable(self):
        """Can Powerful Hand KO the opponent's ACTIVE this turn — now, or after the
        drawing still available to us? (Each turn, aim to KO the best target: usually
        the dangerous active attacker, by pumping the hand to lethal.)"""
        opp = self.opponent.active[0] if self.opponent.active else None
        return (opp is not None and self._have_attacker()
                and not self._effect_prevented(opp)        # Mist Energy etc. → 0, don't chase it
                and 20 * self._achievable_hand() >= opp.hp)

    def _score_play_trainer(self, card):
        cid = card.id
        ready = self._alakazam_ready()
        if cid == C.RARE_CANDY:
            if self.field[C.ABRA] >= 1 and self.hand[C.ALAKAZAM] >= 1:
                # Majkel: step-evolve through Kadabra when possible — its Psychic Draw (+3
                # cards) beats the Candy skip (we over-played Candy 341x). Candy is for
                # when the Kadabra bridge is missing.
                if self.hand[C.KADABRA] >= 1:
                    return 8000   # prefer the Kadabra bridge, but Candy is still fine tempo
                return 20500
            return -1
        opp_active = self.opponent.active[0] if self.opponent.active else None
        # Each turn, if we can KO the dangerous Active this turn by drawing up to a lethal
        # Powerful Hand, DRAW toward it (a draw Supporter beats gusting a weaker target).
        draw_for_ko = (opp_active is not None and self._ko_active_reachable()
                       and 20 * self.me.handCount < opp_active.hp)
        # Winning + deck low: stop spending the deck on draw/search supporters — preserve it
        # so we can draw 1/turn to the finish (Boss's Orders gust is still allowed below).
        if cid in (C.HILDA, C.DAWN, C.POKE_PAD) and self._deck_preserve():
            return -1
        if cid == C.HILDA:
            if self.state.supporterPlayed:
                return -1
            if draw_for_ko:
                return 14000
            return 12500 if self._need_pieces() else 5000
        if cid == C.DAWN:
            if self.state.supporterPlayed:
                return -1
            if draw_for_ko:
                return 13800
            # Majkel plays Dawn broadly (214x divergent) — +3 hand = +60 Powerful Hand
            return 12000 if self._need_pieces() else 7500
        if cid == C.BUDDY_POFFIN:
            bodies = (self.field[C.ABRA] + self.field[C.KADABRA] + self.field[C.ALAKAZAM]
                      + self.field[C.ALAKAZAM_PSY] + self.field[C.DUNSPARCE]
                      + self.field[C.DUDUNSPARCE])
            if bodies >= 4 or not self._open_bench():
                return 600   # board is set — a Poffin now is -20 Powerful Hand for nothing
            return 13000
        if cid == C.POKE_PAD:
            # Majkel keeps digging with it after setup too — every deck→hand card
            # is +20 Powerful Hand (but below Poffin/supporters)
            return 8500 if self._need_pieces() else 3500
        if cid == C.BOSS_ORDERS:
            if self.state.supporterPlayed:
                return -1
            ko = self._gust_ko_targets()
            # If we can KO the Active threat this turn and it's worth at least as much as
            # any benched target, KO IT — don't gust a weaker Pokémon and leave the threat.
            if opp_active is not None and self._ko_active_reachable():
                best_gust = max((self._target_value(p) for p in ko), default=-1)
                if self._target_value(opp_active) >= best_gust:
                    return -1
            if not ko:
                return -1
            best = max(ko, key=self._gust_value)
            if opp_active is not None and self._active_best_dmg(opp_active) >= opp_active.hp \
                    and prize_count(opp_active) >= prize_count(best):
                return -1
            return 13500
        if cid == C.ENHANCED_HAMMER:
            # Strip Mist/effect-prevention Special Energy off the opponent's Active so
            # Powerful Hand stops doing 0. Do it BEFORE drawing/attacking.
            if self._opp_active_has_prevent_energy():
                return 16000
            # otherwise only worth it if the opponent has any Special Energy to remove
            if any(card_table.get(getattr(e, 'id', None)) is not None
                   and card_table[e.id].cardType == CardType.SPECIAL_ENERGY
                   for p in (self.opponent.active + self.opponent.bench) if p is not None
                   for e in (getattr(p, 'energyCards', None) or [])):
                return 9500   # Majkel hammers special energy on sight (248x on 7-06).
                              # (7-13: raising Pad→14000/9200 + Hammer→11000 per the mirror
                              # mining measured ~10pts WORSE in the mirror A/B (83%→73-74%)
                              # — those divergence signals failed the poison test; keep.)
            return -1
        if cid == C.BATTLE_CAGE:
            if self.state.stadiumPlayed or self.stadium_id == C.BATTLE_CAGE:
                return -1
            # 1 copy in the Majkel list — hold it for bench-damage matchups (Grimmsnarl's
            # Shadow Bullet / Munkidori), don't burn it on sight (225x over-pick)
            return 6500 if self._opp_threatens_bench() else 1500
        if cid == C.XEROSIC:
            # Opp discards down to 3 — every stripped card is -20 off THEIR Powerful Hand
            # (mirror) and a lost resource otherwise. 7-13 mining: our #3 over-pick (228x)
            # at 12800 — Majkel holds it and fires selectively on a BIG hand; it also costs
            # the supporter slot AND -20 our own Powerful Hand.
            if self.state.supporterPlayed:
                return -1
            opp_hand = getattr(self.opponent, 'handCount', 0) or 0
            if self._opp_is_rush():
                # vs the Lucario aggro package the discard does nothing (they play off
                # the board, not the hand) — never outrank Hilda/Dawn/Boss here.
                return 2500 if opp_hand >= 8 else 800
            # (7-13 A/B: demoting this to 6500 [below ATTACK] crashed the mirror A/B
            # 83%→28% — Xerosic aggression IS the mirror win condition vs builders even
            # though pointwise mining says Majkel holds it. Ladder A/B > pointwise agree.)
            if opp_hand >= 7:
                return 12800
            if opp_hand >= 5:
                return 8800
            return 1000
        if cid == C.NIGHTTIME_MINE:
            if self.state.stadiumPlayed or self.stadium_id == C.NIGHTTIME_MINE:
                return -1
            # We run zero Tera: vs a Tera board (Dragapult ex etc.) it's a pure attack tax;
            # otherwise still fine to bump/deny the opponent's own stadium.
            if self._opp_has_tera():
                return 9000
            return 4000 if self.stadium_id else 1200
        if cid == C.LUCKY_HELMET:
            return 7000 if not ready else 1000
        if cid == C.NIGHT_STRETCHER:
            recoverable = (self.discard.get(C.ALAKAZAM, 0) or self.discard.get(C.ABRA, 0)
                           or self.discard.get(C.KADABRA, 0) or self.discard.get(C.DUNSPARCE, 0)
                           or self.discard.get(C.PSYCHIC_ENERGY, 0))
            return 7500 if recoverable else 300
        if cid == C.LANA_AID:
            if self.state.supporterPlayed:
                return -1
            return 6000 if self._low_deck() else 1500
        if cid == C.SACRED_ASH:
            return 6000 if self._low_deck() and self.me.discard else 200
        if cid == C.WONDROUS_PATCH:
            return 7000 if self.discard.get(C.PSYCHIC_ENERGY, 0) and self._open_bench() else 300
        return 9000

    # — evolve —
    def _score_evolve(self, o):
        target = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
        if not isinstance(target, Pokemon):
            return 0
        card = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        cid = card.id if card is not None else None
        if cid == C.ALAKAZAM_PSY:
            # The Psychic tech (bypasses Mist, punishes energy). Make THIS Alakazam only
            # when (a) the opp Active is Mist-protected AND we can't strip it (no Enhanced
            # Hammer in hand), or (b) it's heavily energy-loaded. Otherwise the 743 Powerful
            # Hand (after Enhanced Hammer if needed) is our higher-ceiling main attacker.
            opp = self.opponent.active[0] if self.opponent.active else None
            if opp is not None and ((self._effect_prevented(opp) and self.hand[C.ENHANCED_HAMMER] == 0)
                                    or len(opp.energies) >= 4):
                return 21500
            return 20400
        if cid == C.ALAKAZAM:
            # One attacking Alakazam at a time — each extra evolve burns a hand card
            # (-20 Powerful Hand). Majkel does evolve the ACTIVE Kadabra (fresh attacker)
            # even with one Alakazam up, but doesn't stack bench Alakazams.
            have = self.field[C.ALAKAZAM] + self.field[C.ALAKAZAM_PSY]
            if have == 0 or o.inPlayArea == AreaType.ACTIVE:
                return 21000
            return 4000
        if cid == C.KADABRA:
            # JIT (Majkel 7-06: his 237 vs our 1120): evolve when BRIDGING to Alakazam or
            # when the hand needs the +3 draw — otherwise the piece is safer in hand
            # (on board it's Grimmsnarl-snipe/Froslass-chip bait, in hand it's +20 dmg).
            if self.hand[C.ALAKAZAM] >= 1 or self.me.handCount <= 4                     or self.field[C.ALAKAZAM] + self.field[C.ALAKAZAM_PSY] == 0:
                return 20000
            return 6000
        if cid == C.DUDUNSPARCE:
            # (7-08: gating this on the Run-Away-Draw conditions REGRESSED pointwise agree
            # 49→46/45→43 — same lesson as the lethal/JIT gates: no behavior gates.)
            return 19000
        return 18000

    # — attach energy —
    def _score_attach(self, o):
        p = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
        if not isinstance(p, Pokemon):
            return 0
        # GENERAL RULE (type-aware): attach only while the body still can't pay an attack;
        # once it CAN attack, hold the rest (fuels a backup AND +20 Powerful Hand per card).
        if not self._should_fuel(p):
            return -1
        # The source energy must actually enable an attack — a Colorless Enriching onto a
        # Psychic-needing Alakazam does NOT (the bug); hold it / pick a {P} source instead.
        src = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        if not self._attach_helps(p, src):
            return -1
        if p.id in ALAKAZAM_IDS:
            return 8000 + (200 if o.inPlayArea == AreaType.ACTIVE else 0)
        if p.id in (C.ABRA, C.KADABRA):
            return 1500           # pre-fuel the line (energy carries through evolution)
        return -1                 # non-attacker -> don't waste energy, hold it

    # — retreat —
    def _score_retreat(self):
        active = self.me.active[0] if self.me.active else None
        opp = self.opponent.active[0] if self.opponent.active else None
        if active is None or opp is None:
            return -1
        if active.id not in ALAKAZAM_IDS:
            for p in self.me.bench:
                if p is not None and p.id in ALAKAZAM_IDS and self._energy_count(p) >= 1:
                    return 6000
        return -1

    # — attack —
    def _score_attack(self, o):
        active = self.me.active[0] if self.me.active else None
        opp = self.opponent.active[0] if self.opponent.active else None
        if active is None or opp is None:
            return 800
        aid = o.attackId
        if aid in (ABRA_TELEPORT, DUNSPARCE_TRADE):
            # These switch the Active with a benched Pokémon (ends the turn). Only worth
            # it to bring up a ready attacker when the current Active isn't one and we
            # can't otherwise swap (Issue 1) — otherwise it's just a wasted reposition.
            if active.id not in ALAKAZAM_IDS and active.id != C.KADABRA and self._bench_attacker_ready():
                return 5000
            return 700
        # Score THIS specific attack by its own damage — not the best available attack.
        # (Strange Hacking 338 does 0 damage, just confuses; scoring it like Psychic made
        # the agent spam it: opponent can't attack, but we deal 0 → stall → we deck out.)
        dmg = self._alakazam_damage(aid, opp)
        if aid == STRANGE_HACKING:
            # Utility only: worth a little to Confuse a threatening Active we can't yet KO,
            # but never over a real attack and never as a stall. Stays below END-beating
            # real attacks; above END so it's a last resort if nothing else can act.
            opp_dangerous = prize_count(opp) >= 2 and self._achievable_hand() * 20 < opp.hp
            return 600 if opp_dangerous else 200
        if dmg <= 0:
            return 500
        # Lethal: if this KO takes our last remaining prize(s), it wins the game now.
        if opp.hp <= dmg and prize_count(opp) >= len(self.me.prize):
            return 90000
        # (7-13: repricing attacks to 6800+3×dmg so ATTACK outranks bench/tech plays was
        # part of a batch that crashed the mirror A/B 83%→28% — reverted with the batch.
        # "Attack earlier, hold fluff" remains unproven; retest it ALONE if ever.)
        score = 1000 + min(dmg, 320)
        if opp.hp <= dmg:
            score += 2500 + prize_count(opp) * 200
        return score

    # — sub-selects —
    def _score_card(self, o):
        card = get_card(self.obs, o.area, o.index, o.playerIndex)
        if card is None:
            return 0
        ctx = self.context
        # Opponent card targeting (e.g. Enhanced Hammer: discard a Special Energy from
        # opp) — strip the Mist/Rock that's blocking Powerful Hand, prefer the Active.
        if o.playerIndex == self.op_index and not isinstance(card, Pokemon):
            if card.id in EFFECT_PREVENT_ENERGY:
                return 2000 + (500 if getattr(o, 'inPlayArea', None) == AreaType.ACTIVE else 0)
            d = card_table.get(card.id)
            if d is not None and d.cardType == CardType.SPECIAL_ENERGY:
                return 300
            return 50
        if ctx in (SelectContext.SWITCH, SelectContext.TO_ACTIVE):
            return self._score_active_choice(o, card)
        if ctx == SelectContext.SETUP_ACTIVE_POKEMON:
            return self._score_setup_active(card)
        if ctx in (SelectContext.SETUP_BENCH_POKEMON, SelectContext.TO_BENCH, SelectContext.TO_FIELD):
            return self._score_to_bench(card)
        if ctx == SelectContext.TO_HAND:
            return self._score_to_hand(card)
        if ctx == SelectContext.ATTACH_TO and isinstance(card, Pokemon):
            return self._score_attach_target(card, o.inPlayArea == AreaType.ACTIVE)
        if ctx in (SelectContext.ATTACH_FROM, SelectContext.TO_HAND_ENERGY):
            return 100 if is_energy(card.id) else 10
        if ctx in (SelectContext.DISCARD, SelectContext.DISCARD_CARD_OR_ATTACHED_CARD,
                   SelectContext.DISCARD_ENERGY, SelectContext.DISCARD_ENERGY_CARD):
            return self._score_discard(card)
        if ctx in (SelectContext.DAMAGE_COUNTER, SelectContext.DAMAGE_COUNTER_ANY):
            if isinstance(card, Pokemon) and o.playerIndex == self.op_index:
                return 10000 + prize_count(card) * 1000 - getattr(card, "hp", 0)
            return 0
        if ctx in (SelectContext.TO_DECK, SelectContext.TO_DECK_BOTTOM, SelectContext.TO_PRIZE):
            # Sacred Ash (TO_DECK from the DISCARD pile): recycle ALL 5 slots with line
            # pokemon — Majkel fills it (his 5-card picks vs our 3; TO_DECK agree 12%).
            if getattr(o, 'area', None) == AreaType.DISCARD:
                cid = card.id
                if cid in (C.ABRA, C.KADABRA, C.ALAKAZAM, C.ALAKAZAM_PSY):
                    return 90
                if cid in (C.DUNSPARCE, C.DUDUNSPARCE):
                    return 70
                d = card_table.get(cid)
                if d is not None and d.cardType == CardType.POKEMON:
                    return 30
                return 5
            return self._score_putback(card)
        return 0

    def _score_attach_target(self, p, is_active):
        if not self._should_fuel(p):
            return -1             # already CAN attack (type-aware) -> don't over-fill
        if p.id in ALAKAZAM_IDS:
            return 8000 + (200 if is_active else 0)
        if p.id in (C.ABRA, C.KADABRA):
            return 1500
        return -1

    def _score_active_choice(self, o, card):
        if not isinstance(card, Pokemon):
            return 0
        if o.playerIndex == self.op_index:
            return self._gust_value(card)
        if o.playerIndex != self.my_index:
            return 0
        # Promote (after a KO) the body that best keeps us in the game:
        #  1) a ready Alakazam (can Powerful Hand now) — energy bonus makes it top.
        #  2) any Alakazam (online next turn after we attach 1).
        #  3) the tankiest survivor (Dudunsparce 140 / Kadabra 80) so we don't just feed
        #     the opponent a free prize off a 50-HP Abra; a Kadabra can also evolve into
        #     Alakazam next turn. NEVER strand the win-con behind a fragile chump-promote.
        # Promotion order MEASURED against the Elo≥1150 Alakazam pool: they promote the
        # EVOLUTION LINE (Abra/Kadabra → becomes the Alakazam attacker), NOT the Dudunsparce
        # wall (a draw-engine dead end that can't pressure). We over-promoted Dudunsparce.
        score = len(card.energies) * 10
        if card.id in ALAKAZAM_IDS:
            score += 200         # a powered Alakazam = our attacker
        elif card.id == C.KADABRA:
            score += 95          # 80 HP, one evolve from Alakazam — keep the line going
                                 # (7-08: flipping Abra above Kadabra per 16 divergent Majkel
                                 # picks LOST the mirror A/B 29% — the promoted Kadabra is a
                                 # next-turn attacker via evolve; keep the measured order.)
        elif card.id == C.ABRA:
            score += 80          # continues the line to Alakazam (top pilots promote it)
        elif card.id == C.DUDUNSPARCE:
            score += 40          # 140 HP wall but a dead end — don't strand the win-con
        elif card.id in (C.PSYDUCK, C.SHAYMIN, C.GENESECT):
            score -= 20          # tech bodies: don't promote into the attacker slot
        score += getattr(card, 'hp', 0) // 30   # mild "promote the survivor" tiebreak
        return score + 1

    def _score_setup_active(self, card):
        # Opening-active choice. MEASURED (in-process cabt, 60 games vs Lucario):
        # opening Abra      -> 26% loss, 0 no-offense (evolves in place -> Alakazam fast)
        # opening Dunsparce -> 57% loss, 5 no-offense (70HP body, no attacker path)
        # opening Psyduck/Genesect (pure tech) -> ~60% loss (fragile, can't ever attack).
        # So: Abra >> Dunsparce > (anything that can become an attacker) >> tech basics.
        # Tech basics (Psyduck 858 / Shaymin 343 / Genesect 142) have NO offensive line
        # and must be the last resort — opening them strands us with a dead active.
        if card is None:
            return 0
        if card.id == C.ABRA:
            return 50          # the evolution line -> Alakazam: always preferred
        if card.id == C.DUNSPARCE:
            return 30          # draw engine; digs into Abra but slow to pressure
        if card.id in (C.PSYDUCK, C.SHAYMIN, C.GENESECT):
            return 1           # pure tech, fragile, no attack -> last resort only
        return 5

    def _score_to_bench(self, card):
        if card is None:
            return 0
        d = card_table.get(card.id)
        if d is None or d.cardType != CardType.POKEMON:
            return 0
        cid = card.id; n = self.field[cid]
        if cid == C.ABRA:
            return 200 - 30 * n   # Majkel benches Abra over Dunsparce ~3:1
        if cid == C.DUNSPARCE:
            return 140 - 30 * n
        if cid == C.SHAYMIN:
            return 150 if (n == 0 and self._opp_threatens_bench()) else -1
        if cid == C.PSYDUCK:
            return 90 if (n == 0 and self._opp_has_self_ko_ability()) else -1
        if cid == C.FEZANDIPITI:
            return 95 if n == 0 else -1
        return 100 - 20 * n

    def _score_to_hand(self, card):
        if card is None:
            return 0
        cid = card.id
        score = 200 - self.hand[cid] * 40
        # Majkel (7-05, TO_HAND 1503 decisions): grab the ALAKAZAM LINE (Abra/Kadabra/
        # Alakazam, his 634 picks) — do NOT hoard Dudunsparce (our 379x over-grab; the
        # engine shuffles itself back and re-benching is cheap).
        engine_online = self.field[C.DUDUNSPARCE] >= 1
        if cid == C.DUDUNSPARCE:
            # Majkel doesn't re-fetch the self-recycling engine (his 79 vs our 427 grabs) —
            # the LINE pieces come first even when the engine is offline.
            score += 45 if not engine_online else -10
        elif cid == C.DUNSPARCE:
            score += 70 if self.field[C.DUDUNSPARCE] + self.field[C.DUNSPARCE] < 1 else -10
        elif cid == C.ABRA:
            score += 85 if self.field[C.ALAKAZAM] + self.field[C.KADABRA] + self.field[C.ABRA] < 3 else 10
        elif cid == C.KADABRA:
            score += 80
        elif cid == C.ALAKAZAM:
            # his #1 grab (336x): spares feed Sacred Ash recycling & the 2nd attacker
            score += 85 if self.hand[C.ALAKAZAM] == 0 else 40
        elif cid == C.ENRICHING_ENERGY:
            score += 65   # ACE SPEC — Majkel grabs it 54x vs our 1x
        elif is_energy(cid):
            # When starved, fetch a {P} energy (the only kind that fuels our attacks) — an
            # Enriching (Colorless) doesn't help, so don't prioritise it.
            if self._energy_starved() and ENERGY_PROVIDES.get(cid) == EnergyType.PSYCHIC:
                score += 300
            else:
                score += 30
        return score

    def _score_discard(self, card):
        if card is None:
            return 0
        cid = card.id
        if is_energy(cid):
            return 20 if self.hand[cid] >= 3 else -40
        if self.hand[cid] >= 2:
            return 60
        if cid in (C.ABRA, C.KADABRA, C.ALAKAZAM, C.DUNSPARCE, C.DUDUNSPARCE):
            return -50 if self.field[cid] == 0 else 5
        if cid in (C.HILDA, C.DAWN) and self.state.supporterPlayed:
            return 30
        return 0

    def _score_putback(self, card):
        # TO_DECK (Majkel agree 2%→): return SPARE line pieces to the deck freely — they're
        # re-searchable (Dawn/Poké Pad/Hilda); only protect a piece the board still lacks.
        if card is None:
            return 0
        cid = card.id
        if self.hand[cid] >= 2:
            return 70
        if cid in (C.ABRA, C.KADABRA, C.ALAKAZAM, C.DUNSPARCE, C.DUDUNSPARCE):
            return -40 if self.field[cid] == 0 else 60
        return 10


def agent(obs_dict):
    global pre_turn
    try:
        if isinstance(obs_dict, dict) and obs_dict.get("select") is None:
            _DIAG["deck_returns"] += 1
            return my_deck
    except Exception:
        pass
    _DIAG["decisions"] += 1
    try:
        obs = to_observation_class(obs_dict)
        if obs.select is None:
            _DIAG["deck_returns"] += 1; _DIAG["decisions"] -= 1
            return my_deck
        if obs.current is not None and pre_turn != obs.current.turn:
            pre_turn = obs.current.turn
        try:
            sel = AlakazamPolicy(obs).choose()
            _DIAG["policy_ok"] += 1
            return sel
        except Exception as exc:
            _diag_record_error(exc); _DIAG["policy_fallback"] += 1
            return _legal_fallback(obs.select)
    except Exception as exc:
        _diag_record_error(exc); _DIAG["obs_fallback"] += 1
        return _legal_fallback_from_dict(obs_dict if isinstance(obs_dict, dict) else {})
