from __future__ import annotations

import os
from collections import defaultdict, Counter

from cg.api import (
    AreaType, Card, CardType, EnergyType, Observation, OptionType, Pokemon,
    SelectContext, all_card_data, all_attack, to_observation_class,
)


# ── Card IDs (Hop's Trevenant — single-prize aggro that trades up vs ex decks) ──
class C:
    PHANTUMP = 878        # Basic {P} 70HP -> Trevenant
    TREVENANT = 879       # Stage1 140HP: Horrifying Revenge (cheap revenge) / Corner (lock)
    SNORLAX = 304         # Basic 150HP: ability Extra Helpings (+30 Hop's dmg), Dynamic Press
    CRAMORANT = 311       # Basic 110HP: Fickle Spitting 120 for {C} (only if opp at 3-4 prizes)

    MIST_ENERGY = 11      # special: provides {C}; prevents EFFECTS of attacks done to holder
    TELEPATH = 19         # special: provides {P}; on attach to {P} mon -> search 2 Basic {P} to bench

    SECRET_BOX = 1092     # discard 3: grab Item+Tool+Supporter+Stadium
    NIGHT_STRETCHER = 1097
    HOPS_BAG = 1115       # search 2 Basic Hop's -> bench (setup engine)
    POKEGEAR = 1122       # dig 7 for a Supporter
    TRANSCEIVER = 1134    # search a "Team Rocket" Supporter (-> Petrel)
    POKE_PAD = 1152       # search a non-Rule-Box Pokémon -> hand
    CHOICE_BAND = 1171    # TOOL: holder's attacks cost {C} less AND +30 to opp Active
    BOSS = 1182           # gust
    PETREL = 1219         # search ANY Trainer -> hand (toolbox glue)
    HILDA = 1225          # search Evolution Pokémon + Energy -> hand
    LILLIE_DET = 1227     # shuffle hand, draw 6 (8 if 6 prizes left) — main draw
    POSTWICK = 1255       # STADIUM: Hop's attacks +30 to opp Active (both players)


HORRIFYING_REVENGE = 1267  # Trevenant: 30, +100 if a Hop's was KO'd by an attack last opp turn
CORNER = 1268              # Trevenant: 90 [P,C,C], opp can't retreat next turn
FICKLE_SPITTING = 433      # Cramorant: 120 [C], does nothing unless opp has exactly 3-4 prizes
DYNAMIC_PRESS = 422        # Snorlax: 140 [C,C,C], 80 self-damage
SPLASHING_DODGE = 1266     # Phantump: 10 [C], coin-flip self-protect

HOPS_POKEMON = {C.PHANTUMP, C.TREVENANT, C.SNORLAX, C.CRAMORANT}
ATTACKER_IDS = {C.TREVENANT}                  # the main attacker line
ENERGY_IDS = {C.MIST_ENERGY, C.TELEPATH}
LOW_DECK_COUNT = 6
pre_turn = -1

# revenge tracker: a Hop's Pokémon KO'd during the opponent's last turn powers Horrifying
# Revenge (+100). We can't see logs, so detect a DROP in our board count between our turns
# (conservative: false-negatives only — we never over-claim lethal). Reset when turn rewinds.
_GAME = {"turn": -10, "mycount": None, "revenge": False}

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

# attack cost (count) + energy-type list; what each energy card provides.
ATTACK_COST_ENERGIES = {}
for _a in all_attack():
    ATTACK_COST_ENERGIES[_a.attackId] = list(_a.energies or [])
ENERGY_PROVIDES = {}
for _c in all_card:
    if _c.cardType in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY):
        ENERGY_PROVIDES[_c.cardId] = getattr(_c, 'energyType', 0)

# Effect-prevention special energy (Mist) — informational; here we mainly USE Mist ourselves.
EFFECT_PREVENT_ENERGY = set()
for _c in all_card:
    for _s in (_c.skills or []):
        _t = (_s.text or '')
        if 'effects of attacks' in _t and 'prevent' in _t.lower() \
                and _c.cardType in (CardType.SPECIAL_ENERGY, CardType.BASIC_ENERGY):
            EFFECT_PREVENT_ENERGY.add(_c.cardId)


# ── generic helpers (proven scaffolding, shared with the other agents) ─────────
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
    return cid in ENERGY_IDS or (d is not None and d.cardType in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY))


# ── Trevenant policy ───────────────────────────────────────────────────────────
class TrevenantPolicy:
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
        self.revenge = _GAME.get("revenge", False)

    def _my_board(self):
        return self.me.active + self.me.bench

    def _bodies(self):
        return [p for p in self._my_board() if p is not None]

    def _open_bench(self):
        return sum(1 for p in self.me.bench if p is not None) < getattr(self.me, "benchMax", 5)

    def _has_snorlax(self):
        return any(p.id == C.SNORLAX for p in self._bodies())

    def _opp_prizes(self):
        return len(self.opponent.prize)

    # — energy / cost —
    def _tool_ids(self, p):
        return [getattr(t, 'id', t) for t in (getattr(p, 'tools', None) or [])]

    def _cost_reduction(self, p):
        return 1 if (p is not None and C.CHOICE_BAND in self._tool_ids(p)) else 0

    @staticmethod
    def _can_pay(attached, cost, reduction=0):
        """Can `attached` (EnergyType list) pay `cost` after waiving `reduction` Colorless?"""
        have = Counter(attached)
        colorless = 0
        reqs = list(cost)
        # apply Choice Band reduction to Colorless requirements first
        for _ in range(reduction):
            if EnergyType.COLORLESS in reqs:
                reqs.remove(EnergyType.COLORLESS)
        for req in reqs:
            if req == EnergyType.COLORLESS:
                colorless += 1
            elif have.get(req, 0) > 0:
                have[req] -= 1
            else:
                return False
        return sum(have.values()) >= colorless

    def _payable_attacks(self, p):
        c = card_table.get(p.id)
        if c is None:
            return []
        attached = list(p.energies or [])
        red = self._cost_reduction(p)
        return [aid for aid in (c.attacks or [])
                if aid in ATTACK_COST_ENERGIES and self._can_pay(attached, ATTACK_COST_ENERGIES[aid], red)]

    def _can_attack(self, p):
        return bool(self._payable_attacks(p))

    def _should_fuel(self, p):
        """Trevenant only needs 1 energy for Horrifying Revenge (0 with Choice Band). Fuel
        the attacker line until it can attack; never over-fill our scarce 8 energy."""
        if p is None or p.id not in (C.PHANTUMP, C.TREVENANT):
            return False
        return not self._can_attack(p)

    # — damage —
    def _flat_boost(self):
        """Stacking +30 boosts to the opponent's Active (before weakness): Postwick stadium,
        our active attacker's Choice Band, and Snorlax's Extra Helpings (in play, no stack)."""
        b = 0
        if self.stadium_id == C.POSTWICK:
            b += 30
        a = self.me.active[0] if self.me.active else None
        if a is not None and C.CHOICE_BAND in self._tool_ids(a):
            b += 30
        if self._has_snorlax():
            b += 30
        return b

    def _attack_damage(self, attacker, aid, target):
        if target is None or attacker is None:
            return 0
        base = 0
        if aid == HORRIFYING_REVENGE:
            base = 30 + (100 if self.revenge else 0)
        elif aid == CORNER:
            base = 90
        elif aid == DYNAMIC_PRESS:
            base = 140
        elif aid == FICKLE_SPITTING:
            base = 120 if self._opp_prizes() in (3, 4) else 0
        elif aid == SPLASHING_DODGE:
            base = 10
        if base <= 0:
            return 0
        dmg = base + self._flat_boost()
        atk_type = getattr(card_table.get(attacker.id), 'energyType', 0)
        od = card_table.get(target.id)
        if od is not None:
            if od.weakness == atk_type and atk_type != EnergyType.COLORLESS:
                dmg *= 2
            elif od.resistance == atk_type and atk_type != EnergyType.COLORLESS:
                dmg = max(0, dmg - 30)
        return dmg

    def _best_attack(self, attacker, target):
        """(attackId, dmg) of the highest-damage attack `attacker` can pay against target."""
        best = (None, 0)
        for aid in self._payable_attacks(attacker):
            d = self._attack_damage(attacker, aid, target)
            if d > best[1]:
                best = (aid, d)
        return best

    def _active_best_dmg(self, target):
        a = self.me.active[0] if self.me.active else None
        if a is None or target is None:
            return 0
        return self._best_attack(a, target)[1]

    def _have_attacker(self):
        a = self.me.active[0] if self.me.active else None
        return a is not None and a.id in ATTACKER_IDS and self._can_attack(a)

    def _bench_attacker_ready(self):
        return any(p is not None and p.id in ATTACKER_IDS and self._can_attack(p)
                   for p in self.me.bench)

    def _target_value(self, p):
        """Worth of removing opponent Pokémon p: prizes dominate (we trade single-prize
        bodies UP into their ex/megaEx), plus invested energy/tools/stage."""
        d = card_table.get(p.id)
        s = prize_count(p) * 1000
        s += len(p.energies) * 120
        s += len(getattr(p, 'tools', []) or []) * 80
        if d is not None:
            if getattr(d, 'stage2', 0):
                s += 200
            elif getattr(d, 'stage1', 0):
                s += 110
        s += getattr(p, 'hp', 0)
        return s

    def _gust_value(self, p):
        d = self._active_best_dmg(p)
        if d >= p.hp:
            if prize_count(p) >= len(self.me.prize):
                return 90000               # KO-ing this wins the game
            return 8000 + self._target_value(p)
        return max(1, d)

    def _gust_ko_targets(self):
        return [p for p in self.opponent.bench if p is not None and self._active_best_dmg(p) >= p.hp]

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
        # Coin-flip / first-or-second choice: keep GO SECOND. Measured against rank-1 Debauchery
        # (200 games), they go second 15/20 — going second lets an aggressive revenge deck attack
        # on its very first turn (the first player can't). NB: the broader Elo≥1150 Trevenant pool
        # goes first, but those are different (Dudunsparce) builds; we mimic Debauchery's build.
        if self.context == SelectContext.IS_FIRST:
            return 100 if t == OptionType.NO else 0
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

    # — abilities —
    def _score_ability(self, o):
        # Snorlax Extra Helpings is a passive (no activation). Any offered ability is fine.
        return 5000

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
        if cid == C.PHANTUMP:
            return 16000 - 200 * n          # the attacker line: bench plenty
        if cid == C.SNORLAX:
            return 15000 if n == 0 else 300  # one Snorlax for the +30 ability; 2nd is dead weight
        if cid == C.CRAMORANT:
            # one Cramorant benched is enough; top pilots don't flood it (we over-played it).
            # Worth more when its 120 Fickle Spitting is live (opp at 3-4 prizes).
            if n == 0:
                return 6000 if self._opp_prizes() in (3, 4) else 3500
            return 800
        return 12000 - 200 * n

    def _need_attacker_pieces(self):
        return self.field[C.TREVENANT] + self.field[C.PHANTUMP] < 2

    def _score_play_trainer(self, card):
        cid = card.id
        opp_active = self.opponent.active[0] if self.opponent.active else None
        # ---- Boss's Orders: gust a KO or the highest-value target ----
        if cid == C.BOSS:
            if self.state.supporterPlayed:
                return -1
            ko = self._gust_ko_targets()
            # if we can already KO the Active and it's worth >= any benched KO, don't gust
            if opp_active is not None and self._active_best_dmg(opp_active) >= opp_active.hp:
                best_gust = max((self._target_value(p) for p in ko), default=-1)
                if self._target_value(opp_active) >= best_gust:
                    return -1
            return 13500 if ko else (2000 if opp_active is not None else -1)
        # ---- Stadium ----
        if cid == C.POSTWICK:
            if self.stadium_id == C.POSTWICK:
                return -1                    # already ours
            if self.state.stadiumPlayed:
                return -1
            return 12000                     # +30 to all our attacks — high priority
        # ---- Draw / search ----
        supporter = card_table.get(cid) is not None and card_table[cid].cardType == CardType.SUPPORTER
        if supporter and self.state.supporterPlayed:
            return -1
        if cid == C.LILLIE_DET:
            # main draw — top pilots lean on it heavily; refuel readily, avoid only when the
            # hand is already large (shuffling away a loaded hand) or the deck is nearly empty.
            if self.me.deckCount <= 2:
                return -1
            return 11000 if self.me.handCount <= 4 else 4000
        if cid == C.HILDA:
            # search Evolution (Trevenant) + Energy — gold early / when we lack the attacker
            return 11500 if self._need_attacker_pieces() or not self._have_attacker() else 4000
        if cid == C.PETREL:
            return 8000                       # toolbox glue: fetch whatever Trainer we need
        if cid == C.POKEGEAR:
            return 5000 if not self.state.supporterPlayed else 1500
        if cid == C.TRANSCEIVER:
            return 4500                       # -> Petrel -> any Trainer
        if cid == C.HOPS_BAG:
            return 10000 if self._open_bench() and self._need_attacker_pieces() else \
                   (6000 if self._open_bench() else 300)
        if cid == C.POKE_PAD:
            return 6000 if self._need_attacker_pieces() else 1500
        if cid == C.SECRET_BOX:
            # discard 3 — only when hand is flush and we need a toolbox piece
            return 4000 if self.me.handCount >= 6 else -1
        if cid == C.NIGHT_STRETCHER:
            need = self.discard.get(C.TREVENANT, 0) or self.discard.get(C.PHANTUMP, 0) \
                or self.discard.get(C.SNORLAX, 0)
            return 6000 if need else 300
        return 8000

    # — evolve —
    def _score_evolve(self, o):
        target = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
        if not isinstance(target, Pokemon):
            return 0
        card = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        cid = card.id if card is not None else None
        if cid == C.TREVENANT:
            # evolve the most-developed / Active Phantump first (gets the attacker online)
            return 20000 + (300 if o.inPlayArea == AreaType.ACTIVE else 0)
        return 18000

    # — attach energy —
    def _score_attach(self, o):
        p = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
        if not isinstance(p, Pokemon):
            return 0
        src = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        # Hop's Choice Band (TOOL): +30 dmg AND -1 {C} cost on the holder. Top pilots band the
        # attacker early (we under-valued this — it fell through to the energy-fuel path which
        # returns -1 once the mon can already attack). Put it on the Active attacker line.
        if src is not None and src.id == C.CHOICE_BAND:
            if p.id in (C.TREVENANT, C.PHANTUMP, C.CRAMORANT) and not self._tool_ids(p):
                return 6000 + (400 if o.inPlayArea == AreaType.ACTIVE else 0)
            return -1
        if not self._should_fuel(p):
            # already able to attack -> only worth attaching to set up Corner on a band-less
            # Active Trevenant that can't pay [P,C,C] yet; otherwise hold our scarce energy.
            return -1
        return self._attach_score(p, src, o.inPlayArea == AreaType.ACTIVE)

    def _attach_score(self, p, src, is_active):
        if p.id not in (C.PHANTUMP, C.TREVENANT):
            return -1
        base = 7000 if p.id == C.TREVENANT else 1500  # carry energy through evolution on Phantump
        if is_active:
            base += 300
        # Telepath onto a {P} Pokémon also fetches 2 Phantump to bench — prefer it while we
        # still want bodies; once the bench is full it's just a {P} source.
        if src is not None and src.id == C.TELEPATH and self._open_bench() and self._need_attacker_pieces():
            base += 400
        return base

    # — retreat —
    def _score_retreat(self):
        active = self.me.active[0] if self.me.active else None
        if active is None:
            return -1
        # promote a ready Trevenant if the Active can't attack (don't sit on a dead Active);
        # Trevenant retreat is 2 though, so only when a benched attacker is actually ready.
        if not (active.id in ATTACKER_IDS and self._can_attack(active)) and self._bench_attacker_ready():
            return 4000
        return -1

    # — attack —
    def _score_attack(self, o):
        active = self.me.active[0] if self.me.active else None
        opp = self.opponent.active[0] if self.opponent.active else None
        if active is None or opp is None:
            return 700
        aid = o.attackId
        dmg = self._attack_damage(active, aid, opp)
        if aid == SPLASHING_DODGE:
            return 600                        # 10 dmg + flip-protect: last resort
        if aid == FICKLE_SPITTING and self._opp_prizes() not in (3, 4):
            return 200                        # does nothing right now
        if aid == DYNAMIC_PRESS:
            # 140 + boosts but 80 self-damage: only when it KOs / is clearly best and Snorlax
            # survives the recoil, else it just suicides our ability-holder.
            if dmg >= opp.hp:
                if prize_count(opp) >= len(self.me.prize):
                    return 90000
                return 3000 + min(dmg, 320)
            return 500
        if dmg <= 0:
            return 400
        # Lethal that takes our last prize(s) wins now.
        if opp.hp <= dmg and prize_count(opp) >= len(self.me.prize):
            return 90000
        score = 1000 + min(dmg, 320)
        if opp.hp <= dmg:
            score += 2500 + prize_count(opp) * 250
        if aid == CORNER:
            score += 150                      # no-retreat lock: minor tiebreak utility
        return score

    # — sub-selects —
    def _score_card(self, o):
        card = get_card(self.obs, o.area, o.index, o.playerIndex)
        if card is None:
            return 0
        ctx = self.context
        if o.playerIndex == self.op_index and not isinstance(card, Pokemon):
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
            return self._attach_score(card, None, o.inPlayArea == AreaType.ACTIVE)
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
            return self._score_putback(card)
        return 0

    def _score_active_choice(self, o, card):
        if not isinstance(card, Pokemon):
            return 0
        if o.playerIndex == self.op_index:
            return self._gust_value(card)
        if o.playerIndex != self.my_index:
            return 0
        # Promote after a KO (TOP-pilot order, from rank-1 Debauchery replays):
        #   1) anything that KOs the opp Active now (win the prize race),
        #   2) Cramorant — the designated 1-prize pivot; Fickle Spitting hits 120 for {C}
        #      when the opp is at 3-4 prizes (a live snipe), and it's cheap to expose,
        #   3) Phantump — cheap body that evolves into the attacker,
        #   4) Trevenant — only forward when it can actually attack (don't expose our
        #      evolved investment to a free KO),
        #   5) Snorlax LAST — Fighting-weak (Lucario) and retreat 4; keep it benched for
        #      the +30 Extra Helpings aura.
        opp = self.opponent.active[0] if self.opponent.active else None
        if opp is not None and self._best_attack(card, opp)[1] >= opp.hp:
            return 5000 + prize_count(opp) * 200 + len(card.energies) * 8
        score = len(card.energies) * 8
        if card.id == C.CRAMORANT:
            score += 150 + (120 if self._opp_prizes() in (3, 4) else 0)
        elif card.id == C.PHANTUMP:
            score += 110
        elif card.id == C.TREVENANT:
            score += 90 + (120 if self._can_attack(card) else 0)
        elif card.id == C.SNORLAX:
            score += 20
        score += getattr(card, 'hp', 0) // 30
        return score + 1

    def _score_setup_active(self, card):
        # Opening Active: Phantump leads (evolves into the Trevenant attacker). Snorlax is a
        # 150HP wall + ability but retreat 4 and weak to Fighting (Lucario) — bench it instead.
        if card is None:
            return 0
        if card.id == C.PHANTUMP:
            return 50
        if card.id == C.CRAMORANT:
            return 20
        if card.id == C.SNORLAX:
            return 15
        return 5

    def _score_to_bench(self, card):
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
        return 100 - 20 * n

    def _score_to_hand(self, card):
        if card is None:
            return 0
        cid = card.id
        score = 200 - self.hand[cid] * 30
        # Search priority MIMICS rank-1 Debauchery (1336, ~our deck). On divergent TO_HAND picks
        # they grab Secret Box (77x), Choice Band (47x) and Hilda (26x) FAR more than Lillie —
        # they assemble GUARANTEED toolbox/attack pieces, not hoard random draw. We previously
        # over-grabbed Lillie (134x). New order: toolbox-assembler / band > consistency-search >
        # raw draw. (6-20 divergence_decode --player "The Debauchery Tea Party".)
        if cid == C.SECRET_BOX:
            score += 130 if self.me.handCount >= 5 else 70   # explosive turn-assembler (needs fodder)
        elif cid == C.CHOICE_BAND:
            # the aggro engine: makes Horrifying Revenge cost 0 and +30 — grab one eagerly.
            score += 115 if self.hand.get(C.CHOICE_BAND, 0) == 0 else 25
        elif cid == C.HILDA:
            score += 100 if (self._need_attacker_pieces() or not self._have_attacker()) else 78
        elif cid == C.HOPS_BAG:
            score += 95 if (self._need_attacker_pieces() or self._open_bench()) else 40
        elif cid == C.LILLIE_DET:
            score += 80                                       # still strong refuel, just below toolbox
        elif cid == C.POKEGEAR:
            score += 55
        elif cid == C.POKE_PAD:
            score += 50
        elif cid == C.TREVENANT:
            # grab the EVOLUTION itself when a Phantump is in play to put it on (human grabbed
            # Trevenant 10x where we grabbed Phantump — get the attacker online a turn sooner).
            score += 82 if self.field[C.PHANTUMP] else 20
        elif cid == C.PHANTUMP:
            score += 60 if self.field[C.PHANTUMP] + self.field[C.TREVENANT] < 2 else 15
        elif cid == C.SNORLAX:
            score += 35 if not self._has_snorlax() else -20
        elif cid == C.BOSS:
            score += 25
        elif is_energy(cid):
            score += 45
        return score

    def _score_discard(self, card):
        if card is None:
            return 0
        cid = card.id
        if is_energy(cid):
            return 25 if self.hand[cid] >= 3 else -40
        if self.hand[cid] >= 3:
            return 60                                   # excess duplicate — safe pitch
        # Hop's Bag is the rank-1 pilot's #1 discard fodder (29x): it's a one-shot SETUP search,
        # NOT draw — once the board is built it's dead weight, so pitch it readily. Keep it only
        # while we still need attacker bodies AND have bench room to land them.
        if cid == C.HOPS_BAG:
            return -30 if (self._need_attacker_pieces() and self._open_bench()) else 50
        # KEEP the real draw/consistency engine (top pilots keep Lillie/Hilda/Secret Box).
        if cid in (C.LILLIE_DET, C.HILDA, C.SECRET_BOX):
            return -45
        if cid in (C.TREVENANT, C.PHANTUMP, C.SNORLAX):
            return -50 if self.field[cid] == 0 else 5
        if cid == C.CHOICE_BAND:
            return 22 if self.hand[cid] >= 2 else 8     # the aggro engine — keep it (rank-1 pitches it less)
        if cid == C.POSTWICK:
            return 45 if self.stadium_id == C.POSTWICK else 14   # redundant once ours is down
        if cid == C.BOSS:
            return 18
        if cid in (C.POKEGEAR, C.POKE_PAD, C.TRANSCEIVER, C.PETREL, C.NIGHT_STRETCHER):
            return 28                                   # utility — fine to pitch (e.g. for Secret Box)
        if cid == C.CRAMORANT and self._opp_prizes() not in (3, 4):
            return 40
        return 12

    def _score_putback(self, card):
        if card is None:
            return 0
        if self.hand[card.id] >= 2:
            return 60
        if card.id in (C.TREVENANT, C.PHANTUMP, C.CHOICE_BAND):
            return -40
        return 10


def _update_revenge(obs):
    """Detect a Hop's KO during the opponent's last turn = a drop in our board count
    between our turns. Conservative (false-negatives only). Reset on turn rewind (new game)."""
    try:
        st = obs.current
        cur = sum(1 for p in (st.players[st.yourIndex].active + st.players[st.yourIndex].bench)
                  if p is not None)
        if st.turn < _GAME["turn"]:                 # a new game started in this process
            _GAME.update({"turn": -10, "mycount": None, "revenge": False})
        if st.turn > _GAME["turn"]:                 # first decision of a new (our) turn
            prev = _GAME["mycount"]
            _GAME["revenge"] = (prev is not None and cur < prev)
            _GAME["mycount"] = cur
            _GAME["turn"] = st.turn
    except Exception:
        pass


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
        _update_revenge(obs)
        try:
            sel = TrevenantPolicy(obs).choose()
            _DIAG["policy_ok"] += 1
            return sel
        except Exception as exc:
            _diag_record_error(exc); _DIAG["policy_fallback"] += 1
            return _legal_fallback(obs.select)
    except Exception as exc:
        _diag_record_error(exc); _DIAG["obs_fallback"] += 1
        return _legal_fallback_from_dict(obs_dict if isinstance(obs_dict, dict) else {})
