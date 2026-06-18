from __future__ import annotations

import os
from collections import defaultdict

from cg.api import (
    AreaType,
    Card,
    CardType,
    EnergyType,
    Observation,
    OptionType,
    Pokemon,
    SelectContext,
    all_card_data,
    to_observation_class,
)


# ── Card IDs (Ethan's Typhlosion + Dudunsparce) ──────────────────────────────
class C:
    CYNDAQUIL = 352       # Basic -> Quilava
    QUILAVA = 353         # Stage1 -> Typhlosion; ability fetches Ethan's Adventure
    TYPHLOSION = 354      # Stage2 attacker (Buddy Blast / Steam Artillery), weak WATER
    DUNSPARCE = 65        # Basic -> Dudunsparce
    DUDUNSPARCE = 66      # Stage1 draw engine (Run Away Draw)
    VICTINI = 202         # Victory Cheer: +10 to our Evolution {R} attacks

    FIRE_ENERGY = 2
    LEGACY_ENERGY = 12

    ETHAN_ADVENTURE = 1215  # Item: search 3 Ethan's Pokémon / {R} energy (fuels Buddy Blast)
    BUDDY_POFFIN = 1086
    ULTRA_BALL = 1121
    POKEGEAR = 1122
    POKE_PAD = 1152
    LILLIE_DET = 1227
    CHEREN = 1224
    RARE_CANDY = 1079
    REDEEMABLE_TICKET = 1114
    SACRED_ASH = 1129
    BOSS_ORDERS = 1182      # Supporter: gust 1 opponent benched Pokémon to Active
    BRAVE_BANGLE = 1175     # Tool: non-ex holder does +30 to opponent Active ex
    HERO_CAPE = 1159        # Tool (ACE SPEC): +100 HP

IMMUNE_TO_EX = {158, 207, 330, 345}


# Attack IDs
BUDDY_BLAST = 490       # Typhlosion: 40 + 60 per Ethan's Adventure in discard, e[R,C]
STEAM_ARTILLERY = 491   # Typhlosion: 160, e[R,R,C]
COMBUSTION = 489        # Quilava: 40
EMBER = 488             # Cyndaquil: 30 (discard an energy)
LAND_CRUSH = None       # Dudunsparce 90 (we mainly use it as draw engine)
FLARE = 273             # Victini: 30

ENERGY_TYPES = {C.FIRE_ENERGY, C.LEGACY_ENERGY}
LOW_DECK_COUNT = 6
pre_turn = -1

_DIAG = {"decisions": 0, "policy_ok": 0, "policy_fallback": 0,
         "obs_fallback": 0, "deck_returns": 0, "errors": {}}


def _diag_record_error(exc):
    key = type(exc).__name__ + ": " + str(exc)[:160]
    _DIAG["errors"][key] = _DIAG["errors"].get(key, 0) + 1


def diag_reset():
    _DIAG.update({"decisions": 0, "policy_ok": 0, "policy_fallback": 0,
                  "obs_fallback": 0, "deck_returns": 0, "errors": {}})


def diag_snapshot():
    snap = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _DIAG.items()}
    snap["fallback_rate"] = (snap.get("policy_fallback", 0) + snap.get("obs_fallback", 0)) / max(1, snap["decisions"])
    return snap


def _resolve_deck_path():
    import sys
    cands = []
    if "__file__" in globals():
        cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "deck.csv"))
    cands += ["deck.csv", "/kaggle_simulations/agent/deck.csv"]
    # kaggle_environments execs the agent without __file__ but appends the agent
    # dir to sys.path — scan it so deck.csv is found in the official cabt env too.
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
    minc = max(0, min(select.minCount, n))
    maxc = max(minc, min(select.maxCount, n))
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
        n = len(select.option)
        return list(range(min(max(0, select.minCount), n)))
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
    if d is None:
        return 1
    return 3 if d.megaEx else 2 if d.ex else 1


def is_energy(cid):
    d = card_table.get(cid)
    return cid in ENERGY_TYPES or (d is not None and d.cardType in (CardType.BASIC_ENERGY, CardType.SPECIAL_ENERGY))


# ── Quilava policy ───────────────────────────────────────────────────────────
class QuilavaPolicy:
    def __init__(self, obs: Observation):
        self.obs = obs
        self.state = obs.current
        self.select = obs.select
        self.context = self.select.context
        self.my_index = self.state.yourIndex
        self.op_index = 1 - self.my_index
        self.me = self.state.players[self.my_index]
        self.opponent = self.state.players[self.op_index]
        self.my_prizes_left = len(self.me.prize)
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
        self.adventures_in_discard = self.discard[C.ETHAN_ADVENTURE]
        self.has_victini = self.field[C.VICTINI] >= 1

    def _my_board(self):
        return self.me.active + self.me.bench

    def _opp_board(self):
        return self.opponent.active + self.opponent.bench

    def _low_deck(self):
        return self.me.deckCount <= LOW_DECK_COUNT

    def _hand_size(self):
        return sum(self.hand.values())

    # — damage —
    def _typhlosion_damage(self, attack_id, target):
        if target is None:
            return 0
        if attack_id == BUDDY_BLAST:
            dmg = 40 + 60 * self.adventures_in_discard
        elif attack_id == STEAM_ARTILLERY:
            dmg = 160
        elif attack_id == COMBUSTION:
            dmg = 40
        elif attack_id == FLARE:
            dmg = 30
        elif attack_id == EMBER:
            dmg = 30
        else:
            dmg = 0
        if self.has_victini and attack_id in (BUDDY_BLAST, STEAM_ARTILLERY, COMBUSTION):
            dmg += 10
        od = card_table.get(target.id)
        # Brave Bangle: our non-ex attacker does +30 to an opponent Active {ex}.
        active = self.me.active[0] if self.me.active else None
        if (active is not None and od is not None and (od.ex or od.megaEx)
                and any(t.id == C.BRAVE_BANGLE for t in active.tools)):
            dmg += 30
        if od is not None:
            if od.weakness == EnergyType.FIRE:
                dmg *= 2
            elif od.resistance == EnergyType.FIRE:
                dmg = max(0, dmg - 30)
        return dmg

    def _energy_count(self, p):
        return len(p.energies) if p is not None else 0

    def _active_best_dmg(self, target):
        """Best damage our ACTIVE Typhlosion could do to target this turn."""
        a = self.me.active[0] if self.me.active else None
        if a is None or a.id != C.TYPHLOSION or target is None:
            return 0
        e = len(a.energies)
        best = 0
        if e >= 2:
            best = max(best, self._typhlosion_damage(BUDDY_BLAST, target))
        if e >= 3:
            best = max(best, self._typhlosion_damage(STEAM_ARTILLERY, target))
        return best

    def _gust_ko_targets(self):
        """Opponent BENCH Pokémon our active Typhlosion can KO if gusted up."""
        out = []
        for p in self.opponent.bench:
            if p is None:
                continue
            if self._active_best_dmg(p) >= p.hp:
                out.append(p)
        return out

    def _gust_value(self, p):
        """How much we want opponent Pokémon p as their Active (to attack it)."""
        d = self._active_best_dmg(p)
        if d >= p.hp:   # KO-able: prefer high prize / low HP / fragile setup pieces
            return 5000 + prize_count(p) * 1000 - getattr(p, 'hp', 0)
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
            return 1  # IS_FIRST: don't choose to go first (we prefer going SECOND)
        if t == OptionType.NO:
            # IS_FIRST: choose to go SECOND — lets this Stage-2 setup deck use a
            # Supporter on turn 1 (vs Lucario +14%, Crustle ~same in local A/B).
            return 100 if self.context == SelectContext.IS_FIRST else 0
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
        if card.id == C.QUILAVA:
            # Bonded by the Journey: fetch an Ethan's Adventure when we lack one.
            if self.hand[C.ETHAN_ADVENTURE] == 0 and not self._low_deck():
                return 14000
            return -1
        if card.id == C.DUDUNSPARCE:
            # Run Away Draw (draw 3 + shuffle this Pokémon back). It's the consistency
            # engine — use it almost every turn, BUT:
            #  - only on a BENCHED copy (never shuffle away our active body → would
            #    force a fragile promote, fatal vs aggro), and
            #  - not when our deck is clearly smaller than the opponent's (deck-out risk).
            if o.area != AreaType.BENCH:
                return -1   # only the benched copy — never shuffle away our active body
            # Use it (almost) every turn as the consistency engine; the only stop is a
            # real deck-out risk = OUR deck about to empty (absolute, not "opp hoards").
            if self.me.deckCount <= 7:
                return -1
            return 11000
        if card.id == C.VICTINI:
            return -1  # passive ability, no activation needed normally
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
        cid = card.id
        n = self.field[cid]
        if cid == C.CYNDAQUIL:
            return 20000 - 250 * n          # main attacker line
        if cid == C.DUNSPARCE:
            return 18500 - 250 * n          # draw engine
        if cid == C.VICTINI:
            return 17000 if n == 0 else -1  # one is enough (passive buff)
        return 16000 - 200 * n

    def _score_play_trainer(self, card):
        cid = card.id
        if cid == C.ETHAN_ADVENTURE:
            # Core engine: search 3 + fuels Buddy Blast. Almost always good.
            return 13000 if not self._low_deck() else 2000
        if cid == C.RARE_CANDY:
            # Skip to Typhlosion if we have a Cyndaquil in play and a Typhlosion in hand.
            if self.field[C.CYNDAQUIL] >= 1 and self.hand[C.TYPHLOSION] >= 1:
                return 20500
            return -1
        if cid == C.LILLIE_DET:
            if self._low_deck() or self.state.supporterPlayed:
                return -1
            return 12000 if self._hand_size() <= 4 else 2500
        if cid == C.CHEREN:
            if self.state.supporterPlayed:
                return -1
            return 11500 if self._hand_size() <= 5 else 2000
        if cid == C.POKEGEAR:
            return 9000 if not self.state.supporterPlayed else 300
        if cid == C.BUDDY_POFFIN:
            return 12500 if self._open_bench() else 500
        if cid == C.ULTRA_BALL:
            return 9000 if self._hand_size() >= 3 and self._need_pieces() else 400
        if cid == C.POKE_PAD:
            return 8500 if self._need_pieces() else 500
        if cid == C.SACRED_ASH:
            return 7000 if self._low_deck() and self.me.discard else 200
        if cid == C.REDEEMABLE_TICKET:
            return 6000 if self._low_deck() else 200
        if cid == C.BOSS_ORDERS:
            # Gust a benched target we can KO this turn (disruption + prize).
            if self.state.supporterPlayed:
                return -1
            ko = self._gust_ko_targets()
            if not ko:
                return -1
            opp_active = self.opponent.active[0] if self.opponent.active else None
            best = max(ko, key=self._gust_value)
            # Skip if simply attacking the current active is already as good (KO + >= prize).
            if opp_active is not None and self._active_best_dmg(opp_active) >= opp_active.hp \
                    and prize_count(opp_active) >= prize_count(best):
                return -1
            return 12500
        if cid == C.HERO_CAPE:
            # ACE tool +100 HP -> keep our Typhlosion attacker alive.
            typ = any(p is not None and p.id == C.TYPHLOSION
                      and not any(t.id == C.HERO_CAPE for t in p.tools)
                      for p in (self.me.active + self.me.bench))
            return 9500 if typ else -1
        if cid == C.BRAVE_BANGLE:
            opp_ex = any(p is not None and card_table.get(p.id) is not None
                         and (card_table[p.id].ex or card_table[p.id].megaEx)
                         for p in (self.opponent.active + self.opponent.bench))
            typ = any(p is not None and p.id == C.TYPHLOSION and not p.tools
                      for p in (self.me.active + self.me.bench))
            return (9000 if opp_ex else 3000) if typ else -1
        return 9000

    def _open_bench(self):
        return sum(1 for p in self.me.bench if p is not None) < getattr(self.me, "benchMax", 5)

    def _need_pieces(self):
        # Need a Typhlosion line or Dudunsparce engine online?
        has_attacker = self.field[C.TYPHLOSION] >= 1
        return not has_attacker or self.field[C.CYNDAQUIL] + self.field[C.QUILAVA] < 1

    # — evolve —
    def _score_evolve(self, o):
        target = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
        if not isinstance(target, Pokemon):
            return 0
        card = get_card(self.obs, AreaType.HAND, o.index, self.my_index)
        cid = card.id if card is not None else None
        if cid == C.TYPHLOSION:
            return 21000 + len(target.energies) * 20   # get the attacker online
        if cid == C.QUILAVA:
            return 20000
        if cid == C.DUDUNSPARCE:
            return 19000
        return 18000

    # — attach energy —
    def _score_attach(self, o):
        p = get_card(self.obs, o.inPlayArea, o.inPlayIndex, self.my_index)
        if not isinstance(p, Pokemon):
            return 0
        # Power the Typhlosion (active preferred). Buddy Blast needs 2, Steam needs 3.
        if p.id == C.TYPHLOSION:
            base = 8000 if self._energy_count(p) < 3 else 1500
            if o.inPlayArea == AreaType.ACTIVE:
                base += 200
            return base
        if p.id in (C.CYNDAQUIL, C.QUILAVA):
            return 1500   # will evolve into the attacker
        return 300

    # — retreat —
    def _score_retreat(self):
        active = self.me.active[0] if self.me.active else None
        opp = self.opponent.active[0] if self.opponent.active else None
        if active is None or opp is None:
            return -1
        # Retreat a non-attacker (Cyndaquil/Dunsparce/Victini) for a ready Typhlosion.
        if active.id != C.TYPHLOSION:
            for p in self.me.bench:
                if p is not None and p.id == C.TYPHLOSION and self._energy_count(p) >= 2:
                    return 6000
        return -1

    # — attack —
    def _score_attack(self, o):
        active = self.me.active[0] if self.me.active else None
        opp = self.opponent.active[0] if self.opponent.active else None
        if active is None or opp is None:
            return 800
        aid = o.attackId
        # Ember (Cyndaquil) discards our own Energy — never do it (we run only ~8 energy).
        if aid == EMBER:
            return -1
        # Don't waste a turn chipping with an un-evolved body if a Typhlosion is benched
        # and (nearly) ready — better to develop / promote it. Only suppress if it can't KO.
        if active.id in (C.CYNDAQUIL, C.QUILAVA):
            dmg = self._typhlosion_damage(aid, opp)
            if opp.hp > dmg:  # not a KO
                for p in self.me.bench:
                    if p is not None and p.id == C.TYPHLOSION:
                        return -1
            score = 900 + min(dmg, 120)
            if opp.hp <= dmg:
                score += 2000 + prize_count(opp) * 200
            return score
        if active.id == C.DUDUNSPARCE and aid not in (BUDDY_BLAST, STEAM_ARTILLERY):
            dmg = 90
        else:
            dmg = self._typhlosion_damage(aid, opp)
        if dmg <= 0:
            return 400
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
        if p.id == C.TYPHLOSION:
            return (8000 if len(p.energies) < 3 else 1500) + (200 if is_active else 0)
        if p.id in (C.CYNDAQUIL, C.QUILAVA):
            return 1500
        return 300

    def _score_active_choice(self, o, card):
        if not isinstance(card, Pokemon):
            return 0
        if o.playerIndex == self.op_index:
            # Boss's Orders gust: pick the opponent Pokémon we most want to attack.
            return self._gust_value(card)
        if o.playerIndex != self.my_index:
            return 0
        score = len(card.energies) * 10
        if card.id == C.TYPHLOSION:
            score += 200
        elif card.id == C.DUDUNSPARCE:
            score += 40
        return score + 1

    def _score_setup_active(self, card):
        if card is None:
            return 0
        if card.id == C.CYNDAQUIL:
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
        if cid == C.CYNDAQUIL:
            return 200 - 30 * n
        if cid == C.DUNSPARCE:
            return 180 - 30 * n
        if cid == C.VICTINI:
            return 150 if n == 0 else -1
        return 100 - 20 * n

    def _score_to_hand(self, card):
        if card is None:
            return 0
        cid = card.id
        score = 200 - self.hand[cid] * 50
        if cid == C.CYNDAQUIL:
            score += 40 if self.field[C.TYPHLOSION] + self.field[C.QUILAVA] + self.field[C.CYNDAQUIL] < 2 else -10
        elif cid == C.TYPHLOSION:
            score += 60 if self.field[C.CYNDAQUIL] + self.field[C.QUILAVA] >= 1 else 10
        elif cid == C.ETHAN_ADVENTURE:
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
        if cid in ENERGY_TYPES:
            return 20 if self.hand[cid] >= 3 else -40
        if self.hand[cid] >= 2:
            return 60
        if cid in (C.CYNDAQUIL, C.QUILAVA, C.TYPHLOSION, C.DUNSPARCE, C.DUDUNSPARCE):
            return -50 if self.field[cid] == 0 else 5
        if cid in (C.LILLIE_DET, C.CHEREN) and self.state.supporterPlayed:
            return 30
        return 0

    def _score_putback(self, card):
        if card is None:
            return 0
        if self.hand[card.id] >= 2:
            return 60
        if card.id in (C.CYNDAQUIL, C.TYPHLOSION, C.ETHAN_ADVENTURE):
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
            _DIAG["deck_returns"] += 1
            _DIAG["decisions"] -= 1
            return my_deck
        if obs.current is not None and pre_turn != obs.current.turn:
            pre_turn = obs.current.turn
        try:
            sel = QuilavaPolicy(obs).choose()
            _DIAG["policy_ok"] += 1
            return sel
        except Exception as exc:
            _diag_record_error(exc)
            _DIAG["policy_fallback"] += 1
            return _legal_fallback(obs.select)
    except Exception as exc:
        _diag_record_error(exc)
        _DIAG["obs_fallback"] += 1
        return _legal_fallback_from_dict(obs_dict if isinstance(obs_dict, dict) else {})
