"""Shared base policy for all ladder agents — the SINGLE SOURCE OF TRUTH for the generic,
deck-agnostic piloting logic that every deck needs and that kept getting re-implemented (and
re-broken) per deck.

Why this exists: agents are submitted as self-contained `main.py + deck.csv + cg/`, so the
scaffolding used to be COPY-PASTED into each main.py. That meant a fix made in one deck (e.g.
"never over-attach energy past what an attack costs") did NOT propagate to the next deck — a
new deck could silently omit or break it. This base fixes that:

  * The generic ENERGY DISCIPLINE (`can_attack`/`should_fuel`/`attach_helps`) lives here and is
    INHERITED — it is impossible for a subclass to over-fill energy unless it deliberately
    overrides `score_attach`. It is derived from each attack's real cost (card data), never
    hardcoded per card, so it is correct for ANY deck by construction.
  * Deck-specific decisions are `@abstractmethod`s — Python REFUSES to instantiate a subclass
    that forgets one, so a new-deck author is forced to consciously handle each (incl. the
    deck-specific go-first/second choice, a repeated source of bugs).

A deck's main.py: `from policy_base import BasePolicy, make_agent, ...`, subclass BasePolicy,
implement the abstract hooks, then `agent = make_agent(MyPolicy, my_deck, DIAG)`.
The Kaggle/cabt loader appends the agent dir to sys.path, so the sibling import works once
build_submission.sh bundles this file alongside main.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter, defaultdict

from cg.api import (
    AreaType, Card, CardType, EnergyType, Observation, OptionType, Pokemon,
    SelectContext, all_card_data, all_attack, to_observation_class,
)

# ── card/attack data + auto-built, deck-agnostic lookup tables ────────────────
all_card = all_card_data()
card_table = {c.cardId: c for c in all_card}
attack_table = {a.attackId: a for a in all_attack()}

ATTACK_COST = {}                 # attackId -> number of energies in its cost
ATTACK_COST_ENERGIES = {}        # attackId -> list[EnergyType] (0=Colorless, 5=Psychic …)
SELF_SCALING_ATTACKS = set()     # attacks whose damage grows with energy on the attacker itself
for _a in all_attack():
    ATTACK_COST[_a.attackId] = len(_a.energies or [])
    ATTACK_COST_ENERGIES[_a.attackId] = list(_a.energies or [])
    _t = (_a.text or '').lower()
    if 'for each' in _t and 'energy attached to this' in _t:
        SELF_SCALING_ATTACKS.add(_a.attackId)

ENERGY_PROVIDES = {}             # energy cardId -> EnergyType it provides (base value)
for _c in all_card:
    if _c.cardType in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY):
        ENERGY_PROVIDES[_c.cardId] = getattr(_c, 'energyType', 0)

BENCH_DAMAGE_ATTACKS = set()     # attacks that hit the bench (spread/snipe)
for _a in all_attack():
    _t = (_a.text or '').lower()
    if ('benched' in _t and 'damage' in _t) or ('to each of your opponent' in _t and 'damage' in _t):
        BENCH_DAMAGE_ATTACKS.add(_a.attackId)

EFFECT_PREVENT_ENERGY = set()    # Mist / Rock-Fighting energy: prevents EFFECTS of attacks on holder
EFFECT_PREVENT_SELF = set()      # a Pokémon whose own ability prevents effects of attacks on itself
for _c in all_card:
    for _s in (_c.skills or []):
        _t = (_s.text or '')
        if 'effects of attacks' in _t and 'prevent' in _t.lower():
            if _c.cardType in (CardType.SPECIAL_ENERGY, CardType.BASIC_ENERGY):
                EFFECT_PREVENT_ENERGY.add(_c.cardId)
            elif 'to this Pokémon' in _t or 'to this Pok' in _t:
                EFFECT_PREVENT_SELF.add(_c.cardId)

ITEM_LOCK_IDS = set()
for _c in all_card:
    for _s in (_c.skills or []):
        _t = (_s.text or '')
        if 'Item' in _t and 'Active Spot' in _t and 'play' in _t and ('opponent' in _t or 'neither' in _t):
            ITEM_LOCK_IDS.add(_c.cardId)


# ── generic module helpers ───────────────────────────────────────────────────
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


def legal_fallback(select):
    try:
        n = len(select.option); return list(range(min(max(0, select.minCount), n)))
    except Exception:
        return []


def legal_fallback_from_dict(obs_dict):
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


def is_evolution(cid):
    d = card_table.get(cid)
    return bool(d and (d.stage1 or d.stage2))


# ── Prize-card deduction (adopted from the shared "Gold Medal Starmie 1250" agent) ──────────
# Deduces which of OUR OWN cards are in the face-down Prize pile: decklist minus everything
# currently visible (deck-during-search, hand, board+pre-evos+energy+tools, discard, stadium,
# in-flight effect card) == the prized set, but ONLY when it exactly equals the prize count.
# Conservative by design: returns "unknown" (None) whenever the observation is ambiguous, because
# a WRONG prize belief is worse than none. Persists across decisions (held in the agent wrapper).
class PrizeTracker:
    def __init__(self, decklist):
        self._decklist = list(decklist)
        self._deck_total = Counter(self._decklist)
        self._prized = None
        self._last_prize_count = None
        self._last_hand_by_serial = {}

    def deck_total(self, card_id):
        return self._deck_total.get(card_id, 0)

    def update(self, obs, obs_dict=None):
        yi = obs.current.yourIndex
        player = obs.current.players[yi]
        prize_count = len(player.prize)
        hand_by_serial = {c.serial: c.id for c in (player.hand or [])
                          if c is not None and getattr(c, "serial", None) is not None}
        if (self._prized is not None and self._last_prize_count is not None
                and prize_count < self._last_prize_count):
            taken = self._last_prize_count - prize_count
            card_ids = self._prize_to_hand(obs_dict, yi)
            if len(card_ids) != taken:
                card_ids = [cid for serial, cid in hand_by_serial.items()
                            if serial not in self._last_hand_by_serial]
            if len(card_ids) != taken or not self._remove(card_ids):
                self._prized = None
        self._last_prize_count = prize_count
        self._last_hand_by_serial = hand_by_serial
        if self._prized is not None:
            return
        if obs.select is None or getattr(obs.select, "deck", None) is None:
            return
        if len(obs.select.deck) != player.deckCount:
            return
        inferred = self._deduce(obs, player, yi)
        if inferred is not None:
            self._prized = inferred

    def _deduce(self, obs, player, pi):
        remaining = Counter(self._decklist)

        def sub(card):
            if card is not None:
                remaining[card.id] -= 1
        for card in obs.select.deck:
            sub(card)
        for card in player.hand or []:
            sub(card)
        for pk in list(player.active or []) + list(player.bench or []):
            if pk is None:
                continue
            sub(pk)
            for c in getattr(pk, "preEvolution", None) or []:
                sub(c)
            for c in getattr(pk, "energyCards", None) or []:
                sub(c)
            for c in getattr(pk, "tools", None) or []:
                sub(c)
        for card in player.discard or []:
            sub(card)
        for card in obs.current.stadium or []:
            if card is not None and getattr(card, "playerIndex", None) == pi:
                remaining[card.id] -= 1
        effect = getattr(obs.select, "effect", None)
        if effect is not None and getattr(effect, "playerIndex", None) == pi:
            if remaining.get(effect.id, 0) > 0:
                remaining[effect.id] -= 1
        if any(c < 0 for c in remaining.values()):
            return None
        inferred = Counter({cid: c for cid, c in remaining.items() if c > 0})
        if sum(inferred.values()) != len(player.prize):
            return None
        return inferred

    def _remove(self, card_ids):
        rem = Counter(card_ids)
        if any(self._prized.get(cid, 0) < c for cid, c in rem.items()):
            return False
        self._prized.subtract(rem)
        self._prized += Counter()
        return True

    def _prize_to_hand(self, obs_dict, pi):
        if not isinstance(obs_dict, dict):
            return []
        return [log["cardId"] for log in obs_dict.get("logs", [])
                if log.get("playerIndex") == pi
                and log.get("fromArea") in (6, "PRIZE", "Prize")
                and log.get("toArea") in (2, "HAND", "Hand")
                and log.get("cardId") is not None]

    def is_prized(self, card_id):
        if self._prized is None:
            return None
        return self._prized.get(card_id, 0) > 0

    def prized_count(self, card_id):
        if self._prized is None:
            return None
        return self._prized.get(card_id, 0)

    def prized_cards(self):
        return self._prized.copy() if self._prized is not None else None


# ── the base policy ──────────────────────────────────────────────────────────
class BasePolicy(ABC):
    # —— deck-specific config a subclass MUST set (class attributes) ——
    ENERGY_TYPES: set = set()      # energy card IDs in THIS deck (basic + special)
    ATTACKER_IDS: set = set()      # the win-con attacker card IDs

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
        self.tracker = None          # set by make_agent() to a persistent PrizeTracker
        self.field = defaultdict(int)
        self.hand = defaultdict(int)
        self.discard = defaultdict(int)
        for p in self.my_board():
            if p is not None:
                self.field[p.id] += 1
        for c in self.me.hand:
            self.hand[c.id] += 1
        for c in self.me.discard:
            self.discard[c.id] += 1

    # —— board / energy helpers ——
    def my_board(self):
        return self.me.active + self.me.bench

    def is_energy(self, cid):
        d = card_table.get(cid)
        return cid in self.ENERGY_TYPES or (
            d is not None and d.cardType in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY))

    def energy_count(self, p):
        # The engine already expands special energies (e.g. an energy that provides {C}{C}{C})
        # in p.energies, so len(p.energies) is the true effective energy count.
        return len(p.energies) if p is not None else 0

    @staticmethod
    def can_pay(attached, cost):
        """Can `attached` (list[EnergyType]) pay `cost` (list[EnergyType], 0=Colorless)?
        Specific types must be met by that exact type; Colorless by anything left over."""
        have = Counter(attached)
        colorless = 0
        for req in cost:
            if req == EnergyType.COLORLESS:
                colorless += 1
            elif have.get(req, 0) > 0:
                have[req] -= 1
            else:
                return False
        return sum(have.values()) >= colorless

    def payable_attacks(self, p):
        c = card_table.get(p.id) if p is not None else None
        if c is None:
            return []
        att = list(p.energies or [])
        return [aid for aid in (c.attacks or [])
                if aid in ATTACK_COST_ENERGIES and self.can_pay(att, ATTACK_COST_ENERGIES[aid])]

    def can_attack(self, p):
        """TYPE-AWARE: can p actually pay one of its attacks with its CURRENT energy?"""
        return bool(self.payable_attacks(p))

    def should_fuel(self, p):
        """GENERIC ENERGY DISCIPLINE — the rule new decks kept missing. Attach more energy ONLY
        while p still cannot pay ANY of its attacks (type-aware), so we NEVER over-fill past what
        an attack costs — UNLESS an attack scales with energy attached to ITSELF (then keep
        attaching for more damage). Derived from real attack costs; correct for any deck."""
        c = card_table.get(p.id) if p is not None else None
        if c is None or not (c.attacks or []):
            return False
        if any(aid in SELF_SCALING_ATTACKS for aid in (c.attacks or [])):
            return True
        return not self.can_attack(p)

    def attach_helps(self, p, src):
        """Would attaching energy card `src` actually let p pay an attack it currently can't?
        (e.g. a Colorless energy onto a Pokémon that needs a specific type does NOT help.)
        Subclasses with a variable-provision energy (provides more on an evolution) should
        override `provided_by` rather than this."""
        if src is None:
            return True
        new = list(p.energies or []) + self.provided_by(src, p)
        c = card_table.get(p.id)
        return any(aid in ATTACK_COST_ENERGIES and self.can_pay(new, ATTACK_COST_ENERGIES[aid])
                   for aid in (c.attacks or []))

    def provided_by(self, src, target):
        """EnergyType list that attaching card `src` to `target` would add. Default = its base
        provision. Override for special energies whose provision depends on the target."""
        return [ENERGY_PROVIDES.get(src.id, EnergyType.COLORLESS)]

    # —— prize knowledge (None = unknown; never act on None) ——
    def is_prized(self, card_id):
        return self.tracker.is_prized(card_id) if self.tracker else None

    def prized_count(self, card_id):
        return self.tracker.prized_count(card_id) if self.tracker else None

    def copies_in_deck(self, card_id):
        """How many copies of card_id are still in our deck (findable by a search) — decklist total
        minus what's visible (hand/board/discard) minus what's prized. None if prizes unknown."""
        if self.tracker is None:
            return None
        pc = self.tracker.prized_count(card_id)
        if pc is None:
            return None
        seen = self.field[card_id] + self.hand[card_id] + self.discard[card_id]
        return max(0, self.tracker.deck_total(card_id) - seen - pc)

    def effect_prevented(self, target):
        if target is None:
            return False
        if target.id in EFFECT_PREVENT_SELF:
            return True
        for e in (getattr(target, 'energyCards', None) or []):
            if getattr(e, 'id', None) in EFFECT_PREVENT_ENERGY:
                return True
        return False

    def have_ready_attacker(self):
        return any(p is not None and p.id in self.ATTACKER_IDS and self.can_attack(p)
                   for p in self.my_board())

    def bench_attacker_ready(self):
        return any(p is not None and p.id in self.ATTACKER_IDS and self.can_attack(p)
                   for p in self.me.bench)

    # —— dispatch ——
    def rank(self):
        if not self.select.option or self.select.maxCount == 0:
            return [], []
        scores = [self.score(o) for o in self.select.option]
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return ranked, scores

    def choose(self):
        ranked, scores = self.rank()
        return normalize_selection(ranked, scores, self.select)

    def score(self, o):
        t = o.type
        if self.context == SelectContext.IS_FIRST:
            # DECK-SPECIFIC — must be set consciously (abstract go_first()).
            return 100 if (t == OptionType.YES) == bool(self.go_first()) else 0
        if self.context == SelectContext.MULLIGAN:
            return 0 if t == OptionType.YES else 100
        if t == OptionType.NUMBER:
            return o.number if o.number is not None else 0
        if t == OptionType.YES:
            return 1
        if t == OptionType.NO:
            return 0
        if t == OptionType.CARD:
            return self.score_card(o)
        if t == OptionType.PLAY:
            return self.score_play(o)
        if t in (OptionType.ENERGY, OptionType.ATTACH):
            return self.score_attach(o)
        if t == OptionType.EVOLVE:
            return self.score_evolve(o)
        if t == OptionType.ABILITY:
            return self.score_ability(o)
        if t == OptionType.RETREAT:
            return self.score_retreat()
        if t == OptionType.ATTACK:
            return self.score_attack(o)
        if t == OptionType.END:
            return 0
        return 0

    def score_play(self, o):
        card = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        if card is None:
            return 0
        d = card_table.get(card.id)
        if d is None:
            return 0
        if d.cardType == CardType.POKEMON:
            return self.score_play_poke(card)
        return self.score_play_trainer(card)

    # —— GENERIC energy-attach scoring (over-fill-proof) ——
    def score_attach(self, o):
        """Default: attach only while the target still can't pay an attack (should_fuel) and the
        source actually helps. Concentrates on attackers. Over-fill is impossible here. Override
        only to add special-energy timing (and still gate on should_fuel for the build-up case)."""
        p = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
        if not isinstance(p, Pokemon):
            return 0
        if not self.should_fuel(p):
            return -1
        src = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        if not self.attach_helps(p, src):
            return -1
        is_active = o.inPlayArea == AreaType.ACTIVE
        return self.attach_priority(p, is_active)

    def attach_priority(self, p, is_active):
        """How much we want to fuel THIS body (already gated by should_fuel). Default: attackers
        first, with a small concentration tiebreak so we finish one body before spreading."""
        concentrate = self.energy_count(p) * 600
        if p.id in self.ATTACKER_IDS:
            return 8000 + concentrate + (300 if is_active else 0)
        return -1

    def score_card(self, o):
        card = get_card(self.obs, o.area, o.index, o.playerIndex)
        if card is None:
            return 0
        ctx = self.context
        if o.playerIndex == self.op_index and not isinstance(card, Pokemon):
            return self.score_opp_card(o, card)
        if ctx in (SelectContext.SWITCH, SelectContext.TO_ACTIVE):
            return self.score_active_choice(o, card)
        if ctx == SelectContext.SETUP_ACTIVE_POKEMON:
            return self.score_setup_active(card)
        if ctx in (SelectContext.SETUP_BENCH_POKEMON, SelectContext.TO_BENCH, SelectContext.TO_FIELD):
            return self.score_to_bench(card)
        if ctx == SelectContext.TO_HAND:
            return self.score_to_hand(card)
        if ctx in (SelectContext.EVOLVES_TO, SelectContext.EVOLVES_FROM):
            return self.score_evolves_choice(card)
        if ctx == SelectContext.ATTACH_TO:
            if isinstance(card, Pokemon):
                if not self.should_fuel(card):
                    return -1
                return self.attach_priority(card, o.inPlayArea == AreaType.ACTIVE)
            return 100 if self.is_energy(card.id) else 10
        if ctx in (SelectContext.ATTACH_FROM, SelectContext.TO_HAND_ENERGY):
            return 100 if self.is_energy(card.id) else 10
        if ctx in (SelectContext.DISCARD, SelectContext.DISCARD_CARD_OR_ATTACHED_CARD,
                   SelectContext.DISCARD_ENERGY, SelectContext.DISCARD_ENERGY_CARD):
            return self.score_discard(card)
        if ctx in (SelectContext.DAMAGE_COUNTER, SelectContext.DAMAGE_COUNTER_ANY, SelectContext.DAMAGE):
            if isinstance(card, Pokemon) and o.playerIndex == self.op_index:
                return self.score_spread_target(card)
            return 0
        if ctx in (SelectContext.TO_DECK, SelectContext.TO_DECK_BOTTOM, SelectContext.TO_PRIZE):
            return self.score_putback(card)
        return 0

    # —— generic default sub-scorers (subclasses override as needed) ——
    def score_opp_card(self, o, card):
        d = card_table.get(card.id)
        if d is not None and d.cardType in (CardType.SPECIAL_ENERGY, CardType.BASIC_ENERGY):
            if card.id in EFFECT_PREVENT_ENERGY:
                return 2000 + (500 if getattr(o, 'inPlayArea', None) == AreaType.ACTIVE else 0)
            return 300 + (200 if getattr(o, 'inPlayArea', None) == AreaType.ACTIVE else 0)
        return 50

    def score_ability(self, o):
        return 9000

    def score_retreat(self):
        active = self.me.active[0] if self.me.active else None
        if active is None:
            return -1
        if not self.can_attack(active) and self.bench_attacker_ready():
            return 6000
        return -1

    def score_active_choice(self, o, card):
        if not isinstance(card, Pokemon):
            return 0
        if o.playerIndex == self.op_index:
            return self.gust_value(card)
        if o.playerIndex != self.my_index:
            return 0
        score = len(card.energies) * 10
        if card.id in self.ATTACKER_IDS:
            score += 200
        score += getattr(card, 'hp', 0) // 30
        return score + 1

    def gust_value(self, card):
        if not isinstance(card, Pokemon):
            return 0
        return prize_count(card) * 1000 - getattr(card, 'hp', 0) // 10

    def score_spread_target(self, card):
        # Default: snipe the opponent's LOWEST-HP body (deny fragile development), with a KO bonus
        # — never waste spread on a high-HP wall you can't threaten.
        hp = getattr(card, 'hp', 0)
        sc = 4000 - hp * 12 + prize_count(card) * 200
        if hp <= 60:
            sc += 1500
        return sc

    def score_setup_active(self, card):
        if card is None:
            return 0
        return 30 if card.id in self.ATTACKER_IDS else 5

    def score_to_bench(self, card):
        if card is None:
            return 0
        d = card_table.get(card.id)
        if d is None or d.cardType != CardType.POKEMON:
            return 0
        return 100 - 20 * self.field[card.id]

    def score_to_hand(self, card):
        if card is None:
            return 0
        return 200 - self.hand[card.id] * 40

    def score_evolves_choice(self, card):
        return 2000 if card is not None and card.id in self.ATTACKER_IDS else 1000

    def score_discard(self, card):
        if card is None:
            return 0
        cid = card.id
        if self.is_energy(cid):
            return 20 if self.hand[cid] >= 3 else -40
        if self.hand[cid] >= 2:
            return 60
        return 0

    def score_putback(self, card):
        if card is None:
            return 0
        if self.hand[card.id] >= 2:
            return 60
        return 10

    # —— ABSTRACT deck hooks: a subclass MUST implement these ——
    @abstractmethod
    def go_first(self) -> bool:
        """Take the first turn? DECK-SPECIFIC — read it from the top pilots' IS_FIRST choice
        (a setup deck usually wants first; an attack-on-T1 deck may want second). Forcing this to
        be implemented stops the recurring 'assumed the wrong one' bug."""

    @abstractmethod
    def score_play_poke(self, card):
        """Priority for playing this Basic Pokémon from hand to the bench."""

    @abstractmethod
    def score_play_trainer(self, card):
        """Priority for playing this Trainer/Energy card from hand."""

    @abstractmethod
    def score_evolve(self, o):
        """Priority for this evolution."""

    @abstractmethod
    def score_attack(self, o):
        """Priority for this attack (score THIS attack by its own value; include lethal/KO logic)."""


def make_agent(policy_cls, my_deck, diag):
    """Build the robust agent(obs_dict) entrypoint for a BasePolicy subclass.
    Holds a persistent PrizeTracker across decisions and attaches it to each policy instance."""
    state = {"pre_turn": -1, "tracker": PrizeTracker(my_deck)}

    def _record_error(exc):
        k = type(exc).__name__ + ": " + str(exc)[:160]
        diag["errors"][k] = diag["errors"].get(k, 0) + 1

    def agent(obs_dict):
        try:
            if isinstance(obs_dict, dict) and obs_dict.get("select") is None:
                diag["deck_returns"] += 1
                return my_deck
        except Exception:
            pass
        diag["decisions"] += 1
        try:
            obs = to_observation_class(obs_dict)
            if obs.select is None:
                diag["deck_returns"] += 1; diag["decisions"] -= 1
                return my_deck
            if obs.current is not None and state["pre_turn"] != obs.current.turn:
                state["pre_turn"] = obs.current.turn
            try:
                try:
                    state["tracker"].update(obs, obs_dict)   # prize deduction (best-effort)
                except Exception:
                    pass
                pol = policy_cls(obs)
                pol.tracker = state["tracker"]
                sel = pol.choose()
                diag["policy_ok"] += 1
                return sel
            except Exception as exc:
                _record_error(exc); diag["policy_fallback"] += 1
                return legal_fallback(obs.select)
        except Exception as exc:
            _record_error(exc); diag["obs_fallback"] += 1
            return legal_fallback_from_dict(obs_dict if isinstance(obs_dict, dict) else {})

    return agent


def new_diag():
    return {"decisions": 0, "policy_ok": 0, "policy_fallback": 0,
            "obs_fallback": 0, "deck_returns": 0, "errors": {}}
