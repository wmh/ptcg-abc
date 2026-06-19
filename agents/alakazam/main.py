from __future__ import annotations

import os
from collections import defaultdict

from cg.api import (
    AreaType, Card, CardType, EnergyType, Observation, OptionType, Pokemon,
    SelectContext, all_card_data, to_observation_class,
)


# ── Card IDs (胡地小人 / Alakazam + Dudunsparce single-prize) ─────────────────
class C:
    ABRA = 741            # Basic -> Kadabra
    KADABRA = 742         # Stage1 (Psychic Draw on evolve) -> Alakazam
    ALAKAZAM = 743        # Stage2 attacker: Powerful Hand = 20 dmg x cards in hand
    DUNSPARCE = 305       # Basic -> Dudunsparce
    DUDUNSPARCE = 66      # Stage1 draw engine (Run Away Draw)
    PSYDUCK = 858         # Damp (ability lock tech)
    SHAYMIN = 343         # Flower Curtain (protect non-Rule-Box bench)
    GENESECT = 142        # ACE Nullifier (with tool)

    PSYCHIC_ENERGY = 5
    TELEPATH_ENERGY = 19  # special, provides {P}
    ENRICHING_ENERGY = 13 # ACE SPEC energy

    BUDDY_POFFIN = 1086
    POKE_PAD = 1152
    HILDA = 1225          # Supporter: search Evolution + Energy
    DAWN = 1231           # Supporter: search Basic+Stage1+Stage2
    RARE_CANDY = 1079
    BOSS_ORDERS = 1182
    BATTLE_CAGE = 1264    # Stadium: block bench damage counters
    LUCKY_HELMET = 1156   # Tool: draw 2 when damaged
    WONDROUS_PATCH = 1146
    NIGHT_STRETCHER = 1097
    SACRED_ASH = 1129
    LANA_AID = 1184


POWERFUL_HAND = 1072   # Alakazam: place 2 counters (20 dmg) per card in hand, on opp Active
SUPER_PSY_BOLT = 1071  # Kadabra: 30
ABRA_TELEPORT = 1070   # Abra: 10 + switch
DUDUN_LAND_CRUSH = 76  # Dudunsparce: 90 (rarely; engine instead)
DUNSPARCE_TRADE = 423  # Dunsparce: switch
DUNSPARCE_RAM = 424

ENERGY_TYPES = {C.PSYCHIC_ENERGY, C.TELEPATH_ENERGY, C.ENRICHING_ENERGY}
ATTACKER_IDS = {C.ALAKAZAM, C.KADABRA}
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

    def _hand_size(self):
        return self.me.handCount

    def _energy_count(self, p):
        return len(p.energies) if p is not None else 0

    # — damage —
    def _alakazam_damage(self, attack_id, target):
        if target is None:
            return 0
        if attack_id == POWERFUL_HAND:
            return 20 * self._hand_size()    # counter placement -> no weakness
        if attack_id == SUPER_PSY_BOLT:
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
        if a.id == C.ALAKAZAM and self._energy_count(a) >= 1:
            return self._alakazam_damage(POWERFUL_HAND, target)
        if a.id == C.KADABRA and self._energy_count(a) >= 1:
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
                s += 130
        if p.id in (144, 322, 323, 337):     # Squawkabilly ex / Noctowl / Fan Rotom / Archaludon ex
            s -= 200
        if p.id == 112 and len(p.energies) >= 1:   # Munkidori (key disruptor)
            s += 300
        s += getattr(p, 'hp', 0)
        return s

    def _gust_value(self, p):
        d = self._active_best_dmg(p)
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
        if t == OptionType.NUMBER:
            return o.number if o.number is not None else 0
        if t == OptionType.YES:
            return 1
        if t == OptionType.NO:
            return 100 if self.context == SelectContext.IS_FIRST else 0  # go second (setup deck)
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
        card = get_card(self.obs, o.area, o.index, self.my_index)
        if card is None:
            return 0
        if card.id == C.DUDUNSPARCE:
            # Run Away Draw: draw 3 + recycle. Big hand = big Powerful Hand. Use it
            # from BENCH almost every turn unless our deck is about to empty.
            if o.area != AreaType.BENCH:
                return -1
            if self.me.deckCount <= 7:        # draw-engine deck: draw aggressively
                return -1                     # (≤8 guard tested WORSE: cabt 50→36% — its
            return 15000                      #  win-con is a huge hand, so don't stop early)
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
            return 20000 - 250 * n
        if cid == C.DUNSPARCE:
            return 18500 - 250 * n
        if cid == C.SHAYMIN:
            return 17000 if n == 0 else -1
        if cid in (C.PSYDUCK, C.GENESECT):
            return 9000 if n == 0 else -1
        return 14000 - 200 * n

    def _alakazam_ready(self):
        a = self.me.active[0] if self.me.active else None
        return a is not None and a.id == C.ALAKAZAM and self._energy_count(a) >= 1

    def _need_pieces(self):
        return self.field[C.ALAKAZAM] < 1

    def _open_bench(self):
        return sum(1 for p in self.me.bench if p is not None) < getattr(self.me, "benchMax", 5)

    def _score_play_trainer(self, card):
        cid = card.id
        ready = self._alakazam_ready()
        if cid == C.RARE_CANDY:
            if self.field[C.ABRA] >= 1 and self.hand[C.ALAKAZAM] >= 1:
                return 20500
            return -1
        if cid == C.HILDA:
            if self.state.supporterPlayed:
                return -1
            return 12500 if self._need_pieces() else 3000
        if cid == C.DAWN:
            if self.state.supporterPlayed:
                return -1
            return 12000 if self._need_pieces() else 2500
        if cid == C.BUDDY_POFFIN:
            return 13000 if self._open_bench() else 600
        if cid == C.POKE_PAD:
            return 8500 if self._need_pieces() else 400
        if cid == C.BOSS_ORDERS:
            if self.state.supporterPlayed:
                return -1
            ko = self._gust_ko_targets()
            if not ko:
                return -1
            opp_active = self.opponent.active[0] if self.opponent.active else None
            best = max(ko, key=self._gust_value)
            if opp_active is not None and self._active_best_dmg(opp_active) >= opp_active.hp \
                    and prize_count(opp_active) >= prize_count(best):
                return -1
            return 13500
        if cid == C.BATTLE_CAGE:
            if self.state.stadiumPlayed or self.stadium_id == C.BATTLE_CAGE:
                return -1
            return 9500
        if cid == C.LUCKY_HELMET:
            return 7000 if not ready else 1000
        if cid == C.NIGHT_STRETCHER:
            return 6000 if (self.discard.get(C.ALAKAZAM, 0) or self.discard.get(C.ABRA, 0)) else 300
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
        if cid == C.ALAKAZAM:
            return 21000
        if cid == C.KADABRA:
            return 20000
        if cid == C.DUDUNSPARCE:
            return 19000
        return 18000

    # — attach energy —
    def _score_attach(self, o):
        p = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
        if not isinstance(p, Pokemon):
            return 0
        if p.id == C.ALAKAZAM:
            base = 8000 if self._energy_count(p) < 1 else 1200
            if o.inPlayArea == AreaType.ACTIVE:
                base += 200
            return base
        if p.id in (C.ABRA, C.KADABRA):
            return 1500
        return 300

    # — retreat —
    def _score_retreat(self):
        active = self.me.active[0] if self.me.active else None
        opp = self.opponent.active[0] if self.opponent.active else None
        if active is None or opp is None:
            return -1
        if active.id != C.ALAKAZAM:
            for p in self.me.bench:
                if p is not None and p.id == C.ALAKAZAM and self._energy_count(p) >= 1:
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
            return 700   # reposition only
        if active.id in (C.ALAKAZAM, C.KADABRA):
            dmg = self._active_best_dmg(opp)
        else:
            dmg = self._alakazam_damage(aid, opp)
        if dmg <= 0:
            return 500
        # Lethal: if this KO takes our last remaining prize(s), it wins the game now.
        if opp.hp <= dmg and prize_count(opp) >= len(self.me.prize):
            return 90000
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
            return self._score_putback(card)
        return 0

    def _score_attach_target(self, p, is_active):
        if p.id == C.ALAKAZAM:
            return (8000 if self._energy_count(p) < 1 else 1200) + (200 if is_active else 0)
        if p.id in (C.ABRA, C.KADABRA):
            return 1500
        return 300

    def _score_active_choice(self, o, card):
        if not isinstance(card, Pokemon):
            return 0
        if o.playerIndex == self.op_index:
            return self._gust_value(card)
        if o.playerIndex != self.my_index:
            return 0
        score = len(card.energies) * 10
        if card.id == C.ALAKAZAM:
            score += 200
        elif card.id == C.DUDUNSPARCE:
            score += 40
        return score + 1

    def _score_setup_active(self, card):
        # Open with Abra so we can evolve it in the Active spot (fastest path to
        # an online Alakazam — opening with Dunsparce delays Alakazam badly).
        if card is None:
            return 0
        if card.id == C.ABRA:
            return 5
        if card.id == C.DUNSPARCE:
            return 3
        return 1

    def _score_to_bench(self, card):
        if card is None:
            return 0
        d = card_table.get(card.id)
        if d is None or d.cardType != CardType.POKEMON:
            return 0
        cid = card.id; n = self.field[cid]
        if cid == C.ABRA:
            return 200 - 30 * n
        if cid == C.DUNSPARCE:
            return 180 - 30 * n
        if cid == C.SHAYMIN:
            return 150 if n == 0 else -1
        return 100 - 20 * n

    def _score_to_hand(self, card):
        if card is None:
            return 0
        cid = card.id
        score = 200 - self.hand[cid] * 40
        if cid == C.ABRA:
            score += 40 if self.field[C.ALAKAZAM] + self.field[C.KADABRA] + self.field[C.ABRA] < 2 else -10
        elif cid == C.ALAKAZAM:
            score += 60 if self.field[C.ABRA] + self.field[C.KADABRA] >= 1 else 10
        elif cid == C.KADABRA:
            score += 40
        elif cid == C.DUNSPARCE:
            score += 25 if self.field[C.DUDUNSPARCE] + self.field[C.DUNSPARCE] < 1 else -10
        elif is_energy(cid):
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
        if card is None:
            return 0
        if self.hand[card.id] >= 2:
            return 60
        if card.id in (C.ABRA, C.ALAKAZAM, C.DUNSPARCE):
            return -40
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
