from __future__ import annotations

import os
import time
import random
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

try:
    from cg.api import search_begin, search_step, search_end
    _SEARCH_AVAILABLE = True
except Exception:
    _SEARCH_AVAILABLE = False


# ── Card IDs (Iono's Bellibolt ex deck) ──────────────────────────────────────
class C:
    # Pokémon
    VOLTORB = 265        # Basic, Voltaic Chain (scaling, non-ex)
    TADBULB = 268        # Basic -> Bellibolt ex
    BELLIBOLT_EX = 269   # Stage1 ex, HP280, Thunderous Bolt 230 (+ Electric Streamer ability)
    WATTREL = 270        # Basic -> Kilowattrel
    KILOWATTREL = 271    # Stage1 non-ex, Mach Bolt 70 (+ Flashing Draw ability)

    LIGHTNING_ENERGY = 4

    # Trainers
    LILLIE_DET = 1227     # Supporter: shuffle hand, draw 6/8
    CANARI = 1233         # Supporter: discard 1 -> search up to 4 {L} Pokémon
    BUDDY_POFFIN = 1086   # Item: search 2 basics <=70HP to bench
    ULTRA_BALL = 1121     # Item: discard 2 -> search any Pokémon
    LEVINCIA = 1254       # Stadium: each turn put up to 2 {L} from discard to hand
    NIGHT_STRETCHER = 1097  # Item: 1 Pokémon or basic energy from discard
    POKE_PAD = 1152       # Item: search non-Rule-Box Pokémon
    MAX_ROD = 1110        # Item: up to 5 Pokémon/basic energy from discard
    ENERGY_RETRIEVAL = 1118  # Item: 2 basic energy from discard


# Attack IDs
THUNDEROUS_BOLT = 368  # Bellibolt ex: {L}{L}{L}{C} 230, locks next turn (ex -> blocked by Crustle)
MACH_BOLT = 370        # Kilowattrel: {L}{C}{C} 70 (non-ex)
VOLTAIC_CHAIN = 363    # Voltorb: {C}{C} 20 + 20*lightning-on-board (non-ex)
TINY_CHARGE = 367      # Tadbulb: {L}{C} 30
QUICK_ATTACK = 369     # Wattrel: {L} 10 (+20 coin)

# attackId -> (pokemon_id, energy_required, base_damage, is_ex_attack)
ATTACK_DATA = {
    THUNDEROUS_BOLT: (C.BELLIBOLT_EX, 4, 230, True),
    MACH_BOLT:       (C.KILOWATTREL, 3, 70, False),
    VOLTAIC_CHAIN:   (C.VOLTORB, 2, 20, False),   # base 20, scales below
    TINY_CHARGE:     (C.TADBULB, 2, 30, False),
    QUICK_ATTACK:    (C.WATTREL, 1, 10, False),
}

ATTACKER_IDS = {C.BELLIBOLT_EX, C.KILOWATTREL, C.VOLTORB}
# Our Pokémon weak to Fighting (don't expose to Lucario etc.) vs safe ones.
FIGHTING_WEAK_IDS = {C.BELLIBOLT_EX, C.VOLTORB, C.TADBULB}
SAFE_VS_FIGHTING = {C.KILOWATTREL, C.WATTREL}
# Pokémon whose ability blocks ex/megaEx attacks (Crustle etc.)
IMMUNE_TO_EX = {158, 207, 330, 345}

LOW_DECK_COUNT = 6

pre_turn = -1

# ── Behavior-cloning model (learned from top Bellibolt players' replays) ──────
# Cards we one-hot in features (deck pool).
BC_CARDS = [C.VOLTORB, C.TADBULB, C.BELLIBOLT_EX, C.WATTREL, C.KILOWATTREL,
            C.LILLIE_DET, C.CANARI, C.BUDDY_POFFIN, C.ULTRA_BALL, C.LEVINCIA,
            C.NIGHT_STRETCHER, C.POKE_PAD, C.MAX_ROD, C.ENERGY_RETRIEVAL,
            C.LIGHTNING_ENERGY]
_BC_CARD_INDEX = {cid: i for i, cid in enumerate(BC_CARDS)}
# Fixed feature layout (see _bc_features). Keep in sync with train_bc.py.
_NC = len(BC_CARDS)
BC_DIM = 26 + _NC * 3  # 26 structural + card one-hot + card×turn + card×hand

# Linear behavior cloning was trialled (train_bc.py) but plateaued at ~35% top-1
# accuracy with no win-rate gain (underfit + distribution shift). Kept off; the
# feature extractor + trainer remain for a future nonlinear/RL approach.
USE_BC = False
# Anti-Fighting piloting (use Kilowattrel vs Fighting decks). OFF = pure v1 (the
# proven 836 ladder build). Flip to True only to A/B-test it on the live ladder.
USE_ANTI_FIGHTING = False
try:
    from bc_weights import BC_WEIGHTS  # pure-python list[float] of length BC_DIM
    if len(BC_WEIGHTS) != BC_DIM:
        BC_WEIGHTS = None
except Exception:
    BC_WEIGHTS = None

# ── Diagnostics (kept minimal but compatible with the test harness) ───────────
_DIAG = {"decisions": 0, "policy_ok": 0, "policy_fallback": 0,
         "obs_fallback": 0, "deck_returns": 0, "errors": {},
         "chosen_types": {}, "attack_ids_chosen": {}}


def _diag_record_error(exc):
    key = type(exc).__name__ + ": " + str(exc)[:160]
    _DIAG["errors"][key] = _DIAG["errors"].get(key, 0) + 1


def diag_reset():
    _DIAG.update({"decisions": 0, "policy_ok": 0, "policy_fallback": 0,
                  "obs_fallback": 0, "deck_returns": 0, "errors": {},
                  "chosen_types": {}, "attack_ids_chosen": {}})


def diag_snapshot():
    snap = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _DIAG.items()}
    dec = max(1, snap.get("decisions", 0))
    snap["fallback_rate"] = (snap.get("policy_fallback", 0) + snap.get("obs_fallback", 0)) / dec
    return snap


# ── Deck loading ─────────────────────────────────────────────────────────────
def _resolve_deck_path() -> str:
    import sys
    cands = []
    if "__file__" in globals():
        cands.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "deck.csv"))
    cands += ["deck.csv", "/kaggle_simulations/agent/deck.csv"]
    cands += [os.path.join(p, "deck.csv") for p in sys.path if p]
    for path in cands:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("deck.csv not found")


DECK_PATH = _resolve_deck_path()
with open(DECK_PATH, "r", encoding="utf-8") as f:
    my_deck = [int(line) for line in f.read().splitlines() if line.strip()]
if len(my_deck) != 60:
    raise ValueError(f"deck.csv must contain 60 card ids, got {len(my_deck)}")

all_card = all_card_data()
card_table = {card.cardId: card for card in all_card}


# ── Generic helpers (reused from the proven scaffolding) ─────────────────────
def normalize_selection(ranked, scores, select):
    n = len(select.option)
    minc = max(0, min(select.minCount, n))
    maxc = max(minc, min(select.maxCount, n))
    out, seen = [], set()
    for i in ranked:
        if not (0 <= i < n) or i in seen:
            continue
        score = scores[i] if i < len(scores) else 0
        if score > 0 or len(out) < minc:
            out.append(i)
            seen.add(i)
        if len(out) >= maxc:
            break
    for i in range(n):
        if len(out) >= minc:
            break
        if i not in seen:
            out.append(i)
            seen.add(i)
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
        opts = sel.get("option") or []
        return list(range(min(max(0, sel.get("minCount", 0)), len(opts))))
    except Exception:
        return []


def _safe_get(seq, index):
    try:
        if seq is None or index is None or index < 0 or index >= len(seq):
            return None
        return seq[index]
    except Exception:
        return None


def get_card(obs, area, index, player_index):
    try:
        player = obs.current.players[player_index]
        match area:
            case AreaType.DECK:
                return _safe_get(getattr(obs.select, "deck", None), index)
            case AreaType.HAND:
                return _safe_get(getattr(player, "hand", None), index)
            case AreaType.DISCARD:
                return _safe_get(getattr(player, "discard", None), index)
            case AreaType.ACTIVE:
                return _safe_get(getattr(player, "active", None), index)
            case AreaType.BENCH:
                return _safe_get(getattr(player, "bench", None), index)
            case AreaType.PRIZE:
                return _safe_get(getattr(player, "prize", None), index)
            case AreaType.STADIUM:
                return _safe_get(getattr(obs.current, "stadium", None), index)
            case AreaType.LOOKING:
                return _safe_get(getattr(obs.current, "looking", None), index)
            case _:
                return None
    except Exception:
        return None


def prize_count(pokemon) -> int:
    data = card_table.get(pokemon.id)
    if data is None:
        return 1
    return 3 if data.megaEx else 2 if data.ex else 1


def _lightning_count(pokemon) -> int:
    try:
        return sum(1 for e in pokemon.energies if e == EnergyType.LIGHTNING)
    except Exception:
        return 0


def target_value(pokemon) -> int:
    """Value of KO-ing / damaging this opponent Pokémon."""
    score = prize_count(pokemon) * 1000
    data = card_table.get(pokemon.id)
    if data is not None:
        if data.stage2:
            score += 200
        elif data.stage1:
            score += 100
    score += len(pokemon.energies) * 120
    score += getattr(pokemon, "hp", 0)
    return score


# ── Value function (board evaluation for shallow search) ─────────────────────
def _attack_dmg_raw(attacker, attack_id, target, board_lightning):
    data = ATTACK_DATA.get(attack_id)
    if data is None or target is None:
        return 0
    _, _req, base, is_ex = data
    if is_ex and target.id in IMMUNE_TO_EX:
        return 0
    dmg = (20 + 20 * board_lightning) if attack_id == VOLTAIC_CHAIN else base
    od = card_table.get(target.id)
    if od is not None:
        if od.weakness == EnergyType.LIGHTNING:
            dmg *= 2
        elif od.resistance == EnergyType.LIGHTNING:
            dmg = max(0, dmg - 30)
    return dmg


def _best_dmg_raw(pokemon, target, board_lightning):
    d = card_table.get(pokemon.id)
    if d is None or target is None:
        return 0
    best = 0
    for a in d.attacks:
        best = max(best, _attack_dmg_raw(pokemon, a, target, board_lightning))
    return best


VALUE_DIM = 22


def value_features(obs, my_index=None):
    """Board features from my_index's perspective (default: player-to-move). Length VALUE_DIM."""
    f = [0.0] * VALUE_DIM
    try:
        st = obs.current
        mi = st.yourIndex if my_index is None else my_index
        me = st.players[mi]
        op = st.players[1 - mi]
        my_pz = len(me.prize); op_pz = len(op.prize)
        ma = me.active[0] if me.active else None
        oa = op.active[0] if op.active else None
        my_board = [p for p in (me.active + me.bench) if p is not None]
        op_board = [p for p in (op.active + op.bench) if p is not None]
        board_l = sum(_lightning_count(p) for p in my_board)

        f[0] = my_pz / 6.0
        f[1] = op_pz / 6.0
        f[2] = (op_pz - my_pz) / 6.0                       # +ve = we're ahead in the race
        f[3] = (ma.hp / ma.maxHp) if (ma and ma.maxHp) else 0.0
        f[4] = (len(ma.energies) / 4.0) if ma else 0.0
        f[5] = (oa.hp / oa.maxHp) if (oa and oa.maxHp) else 0.0
        f[6] = min(sum(len(p.energies) for p in my_board), 12) / 12.0
        f[7] = min(board_l, 12) / 12.0
        ready = 0
        for p in my_board:
            if p.id in ATTACKER_IDS:
                d = card_table.get(p.id)
                req = min((ATTACK_DATA[a][1] for a in d.attacks if a in ATTACK_DATA), default=99) if d else 99
                if len(p.energies) >= req:
                    ready += 1
        f[8] = min(ready, 3) / 3.0
        f[9] = min(len(my_board), 6) / 6.0
        f[10] = min(len(op_board), 6) / 6.0
        f[11] = min(me.deckCount, 30) / 30.0
        f[12] = min(me.handCount, 12) / 12.0
        f[13] = min(st.turn, 16) / 16.0
        f[14] = 1.0 if (oa and oa.id in IMMUNE_TO_EX) else 0.0
        odata = card_table.get(oa.id) if oa else None
        f[15] = 1.0 if (odata and (odata.ex or odata.megaEx)) else 0.0
        # can my active KO opp active now?
        f[16] = 1.0 if (ma and oa and _best_dmg_raw(ma, oa, board_l) >= oa.hp) else 0.0
        # do I have a non-ex attacker ready (Crustle answer)?
        f[17] = 1.0 if any(p.id in (C.KILOWATTREL, C.VOLTORB) and len(p.energies) >= 2 for p in my_board) else 0.0
        f[18] = 1.0 if any(p.id == C.BELLIBOLT_EX for p in my_board) else 0.0
        f[19] = min(sum(1 for p in op_board if p.hp <= 70), 4) / 4.0   # fragile opp targets
        f[20] = 1.0 if st.firstPlayer == mi else 0.0
        f[21] = 1.0                                         # bias term
    except Exception:
        pass
    return f


def _relu(x):
    return x if x > 0 else 0.0


def value_estimate(obs, my_index=None):
    """MLP forward pass -> scalar in (0,1) = P(my_index wins). 0.5 if no model."""
    if VALUE_NET is None:
        return 0.5
    try:
        x = value_features(obs, my_index)
        W1, b1, W2, b2 = VALUE_NET  # W1:[H][D], b1:[H], W2:[H], b2:float
        h = []
        for j in range(len(b1)):
            s = b1[j]
            wj = W1[j]
            for k in range(len(x)):
                s += wj[k] * x[k]
            h.append(_relu(s))
        o = b2
        for j in range(len(h)):
            o += W2[j] * h[j]
        # sigmoid
        if o < -30:
            return 0.0
        if o > 30:
            return 1.0
        import math
        return 1.0 / (1.0 + math.exp(-o))
    except Exception:
        return 0.5


try:
    from value_weights import VALUE_NET  # (W1, b1, W2, b2)
except Exception:
    VALUE_NET = None


# ── Shallow value-guided forward search ──────────────────────────────────────
# Trialled: the value net is accurate (AUC 0.87) but 1-ply search with greedy
# rollout did NOT beat plain rules (Crustle ~same, Lucario 18%->8%). The value
# gap between candidate actions is smaller than the net's noise, and the leaf
# (end-of-my-turn) value misses "about to be KO'd by aggro". Kept off; the value
# net + search infra remain for a future deeper / opponent-aware search or RL.
USE_VALUE_SEARCH = False
SEARCH_K = 5               # candidate first-actions to evaluate
SEARCH_NODE_BUDGET = 120
SEARCH_TIME_BUDGET = 2.0   # seconds per decision
SEARCH_ROLLOUT_MAX = 40


def _determinize_begin(obs, my_index):
    st = obs.current
    me = st.players[my_index]
    op = st.players[1 - my_index]

    def samp(pool, k):
        if k <= 0:
            return []
        if k <= len(pool):
            return random.sample(pool, k)
        return (pool * (k // max(1, len(pool)) + 1))[:k]

    op_active = op.active
    return search_begin(
        obs,
        your_deck=samp(my_deck, me.deckCount),
        your_prize=[1] * len(me.prize),
        opponent_deck=samp(my_deck, op.deckCount),
        opponent_prize=[1] * len(op.prize),
        opponent_hand=[1] * op.handCount,
        opponent_active=[1072] if (len(op_active) > 0 and op_active[0] is None) else [],
    )


def _rollout_my_turn(state, my_index, budget):
    """Play out the rest of my turn greedily (rules); return the leaf observation."""
    obs = state.observation
    for _ in range(SEARCH_ROLLOUT_MAX):
        st = obs.current
        if getattr(st, "result", -1) != -1:
            return obs
        if st.yourIndex != my_index:
            return obs              # opponent to move -> evaluate here
        sel = obs.select
        if sel is None or len(sel.option) == 0:
            return obs
        budget["n"] += 1
        if budget["n"] >= SEARCH_NODE_BUDGET or (time.time() - budget["t0"]) > SEARCH_TIME_BUDGET:
            return obs
        try:
            action = BellipoltPolicy(obs).choose()
            state = search_step(state.searchId, action)
            obs = state.observation
        except Exception:
            return obs
    return obs


def value_search(obs, ranked):
    """Pick the MAIN first-action whose greedy turn-rollout yields the best board value."""
    if not (_SEARCH_AVAILABLE and VALUE_NET is not None):
        return None
    try:
        st = obs.current
        sel = obs.select
        if sel is None or sel.context != SelectContext.MAIN:
            return None
        if sel.maxCount != 1 or len(sel.option) < 2:
            return None
        mi = st.yourIndex
        state = _determinize_begin(obs, mi)
        budget = {"n": 0, "t0": time.time()}
        best_a, best_v = None, -1.0
        for a in ranked[:SEARCH_K]:
            try:
                child = search_step(state.searchId, [a])
            except Exception:
                continue
            leaf = _rollout_my_turn(child, mi, budget)
            v = value_estimate(leaf, mi)
            if v > best_v:
                best_v, best_a = v, a
            if budget["n"] >= SEARCH_NODE_BUDGET or (time.time() - budget["t0"]) > SEARCH_TIME_BUDGET:
                break
        try:
            search_end()
        except Exception:
            pass
        return best_a
    except Exception:
        try:
            search_end()
        except Exception:
            pass
        return None


# ── Bellibolt policy ─────────────────────────────────────────────────────────
class BellipoltPolicy:
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
        self.op_prizes_left = len(self.opponent.prize)
        self.stadium_id = self.state.stadium[0].id if self.state.stadium else 0

        self.field_counts = defaultdict(int)
        self.hand_counts = defaultdict(int)
        self.discard_counts = defaultdict(int)
        self.board_lightning = 0
        self._count_cards()
        self.fighting_threat = self._fighting_threat()

    def _fighting_threat(self) -> bool:
        """Opponent fields Fighting-type Pokémon (e.g. Mega Lucario ex) -> our
        Bellibolt/Voltorb/Tadbulb are weak to Fighting (doubled). Prefer the
        non-Fighting-weak Kilowattrel line as the wall/attacker.
        Gated by USE_ANTI_FIGHTING: False = pure v1 (the proven 836 build)."""
        if not USE_ANTI_FIGHTING:
            return False
        for p in self._opponent_board():
            if p is None:
                continue
            d = card_table.get(p.id)
            if d is not None and d.energyType == EnergyType.FIGHTING:
                return True
        return False

    # — bookkeeping —
    def _count_cards(self):
        for pokemon in self._my_board():
            if pokemon is None:
                continue
            self.field_counts[pokemon.id] += 1
            self.board_lightning += _lightning_count(pokemon)
        for card in self.me.hand:
            self.hand_counts[card.id] += 1
        for card in self.me.discard:
            self.discard_counts[card.id] += 1

    def _my_board(self):
        return self.me.active + self.me.bench

    def _opponent_board(self):
        return self.opponent.active + self.opponent.bench

    def _low_deck(self) -> bool:
        return self.me.deckCount <= LOW_DECK_COUNT

    def _hand_size(self) -> int:
        return sum(self.hand_counts.values())

    # — attack math —
    def _attack_damage(self, attacker, attack_id, target) -> int:
        data = ATTACK_DATA.get(attack_id)
        if data is None or target is None:
            return 0
        _, _req, base, is_ex = data
        if is_ex and target.id in IMMUNE_TO_EX:
            return 0  # Crustle etc. block ex attacks
        if attack_id == VOLTAIC_CHAIN:
            dmg = 20 + 20 * self.board_lightning
        else:
            dmg = base
        op_data = card_table.get(target.id)
        if op_data is not None:
            if op_data.weakness == EnergyType.LIGHTNING:
                dmg *= 2
            elif op_data.resistance == EnergyType.LIGHTNING:
                dmg = max(0, dmg - 30)
        return dmg

    def _best_damage_against(self, pokemon, target) -> int:
        """Best damage this of-our Pokémon could do to target if it could attack."""
        data = card_table.get(pokemon.id)
        if data is None:
            return 0
        best = 0
        for aid in data.attacks:
            best = max(best, self._attack_damage(pokemon, aid, target))
        return best

    # — behavior-cloning features (shared by training + inference) —
    def _option_card_id(self, option):
        try:
            t = option.type
            if t in (OptionType.PLAY, OptionType.EVOLVE):
                c = get_card(self.obs, AreaType.HAND, option.index, self.my_index)
            elif t == OptionType.ABILITY:
                c = get_card(self.obs, option.area, option.index, self.my_index)
            elif t in (OptionType.ATTACH, OptionType.ENERGY):
                c = get_card(self.obs, option.inPlayArea, option.inPlayIndex, self.my_index)
            elif t == OptionType.ATTACK:
                c = self.me.active[0] if self.me.active else None
            else:
                c = None
            return c.id if c is not None else None
        except Exception:
            return None

    def _bc_features(self, option):
        f = [0.0] * BC_DIM
        try:
            t = option.type
            turn = min(self.state.turn, 12) / 12.0
            hand = min(self._hand_size(), 12) / 12.0
            hl = min(self.hand_counts[C.LIGHTNING_ENERGY], 6) / 6.0
            is_play = t == OptionType.PLAY
            is_evo = t == OptionType.EVOLVE
            is_abil = t == OptionType.ABILITY
            is_att = t in (OptionType.ATTACH, OptionType.ENERGY)
            is_ret = t == OptionType.RETREAT
            is_atk = t == OptionType.ATTACK
            is_end = t == OptionType.END
            f[0] = float(is_play); f[1] = float(is_evo); f[2] = float(is_abil)
            f[3] = float(is_att); f[4] = float(is_ret); f[5] = float(is_atk)
            f[6] = float(is_end)
            f[7] = float(not (is_play or is_evo or is_abil or is_att or is_ret or is_atk or is_end))
            f[8] = is_play * turn
            f[9] = is_abil * turn
            f[10] = is_atk * turn
            f[11] = is_end * turn
            f[12] = is_play * hand
            f[13] = is_end * hand
            f[14] = is_abil * hl
            active = self.me.active[0] if self.me.active else None
            opp = self.opponent.active[0] if self.opponent.active else None
            if is_atk and active is not None and opp is not None:
                dmg = self._attack_damage(active, option.attackId, opp)
                data = ATTACK_DATA.get(option.attackId)
                blocked = bool(data and data[3] and opp.id in IMMUNE_TO_EX)
                f[15] = 1.0 if (dmg > 0 and opp.hp <= dmg) else 0.0
                f[16] = min(dmg, 300) / 300.0
                f[17] = float(blocked)
                f[18] = float(option.attackId == THUNDEROUS_BOLT)
            if is_att:
                tgt = get_card(self.obs, option.inPlayArea, option.inPlayIndex, self.my_index)
                if isinstance(tgt, Pokemon):
                    d = card_table.get(tgt.id)
                    req = min((ATTACK_DATA[a][1] for a in d.attacks if a in ATTACK_DATA), default=99) if d else 99
                    f[19] = 1.0 if (tgt.id in ATTACKER_IDS and len(tgt.energies) < req) else 0.0
                    f[20] = float(option.inPlayArea == AreaType.ACTIVE)
                    f[21] = float(tgt.id == C.BELLIBOLT_EX)
            if is_abil:
                cid = self._option_card_id(option)
                f[22] = float(cid == C.BELLIBOLT_EX)
                f[23] = float(cid == C.KILOWATTREL)
                f[24] = float(cid == C.BELLIBOLT_EX and self._needs_more_energy())
            if is_ret and active is not None and opp is not None:
                f[25] = float(self._best_damage_against(active, opp) == 0)
            cid = self._option_card_id(option)
            if cid in _BC_CARD_INDEX:
                ci = _BC_CARD_INDEX[cid]
                f[26 + ci] = 1.0                       # card one-hot
                f[26 + _NC + ci] = turn                # card × turn
                f[26 + 2 * _NC + ci] = hand            # card × hand size
        except Exception:
            pass
        return f

    def _bc_score(self, option) -> float:
        f = self._bc_features(option)
        return sum(w * x for w, x in zip(BC_WEIGHTS, f))

    # — entry —
    def rank(self):
        if not self.select.option or self.select.maxCount == 0:
            return [], []
        if (self.context == SelectContext.MAIN and USE_BC and BC_WEIGHTS is not None):
            scores = [self._bc_score(o) for o in self.select.option]
        else:
            scores = [self._score_option(o) for o in self.select.option]
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return ranked, scores

    def choose(self):
        ranked, scores = self.rank()
        if (self.context == SelectContext.MAIN and USE_BC and BC_WEIGHTS is not None):
            # MAIN = pick the single best action (logits may be negative).
            n = len(self.select.option)
            minc = max(0, min(self.select.minCount, n))
            maxc = max(minc, min(self.select.maxCount, n))
            return ranked[:max(1, maxc)] if maxc >= 1 else ranked[:minc]
        return normalize_selection(ranked, scores, self.select)

    def _score_option(self, option) -> float:
        t = option.type
        if t == OptionType.NUMBER:
            return option.number if option.number is not None else 0
        if t == OptionType.YES:
            return 100 if self.context == SelectContext.IS_FIRST else 1
        if t == OptionType.NO:
            return 0
        if t == OptionType.CARD:
            return self._score_card_choice(option)
        if t == OptionType.PLAY:
            return self._score_play(option)
        if t in (OptionType.ENERGY, OptionType.ATTACH):
            return self._score_attach(option)
        if t == OptionType.EVOLVE:
            return self._score_evolve(option)
        if t == OptionType.ABILITY:
            return self._score_ability(option)
        if t == OptionType.RETREAT:
            return self._score_retreat()
        if t == OptionType.ATTACK:
            return self._score_attack(option)
        if t == OptionType.END:
            return 0
        return 0

    # — MAIN: abilities —
    def _score_ability(self, option) -> float:
        card = get_card(self.obs, option.area, option.index, self.my_index)
        if card is None:
            return 0
        if card.id == C.BELLIBOLT_EX:
            # Electric Streamer: stream Lightning from hand onto an attacker.
            if self.hand_counts[C.LIGHTNING_ENERGY] <= 0:
                return -1
            if self._needs_more_energy():
                return 15000
            return 1500  # extra energy is still useful (Voltaic Chain scaling / backup)
        if card.id == C.KILOWATTREL:
            # Flashing Draw: discard a {L} from Kilowattrel to draw to 6.
            if self._low_deck() or self._hand_size() >= 5:
                return -1
            return 11000
        return 12000

    def _needs_more_energy(self) -> bool:
        """True if any in-play attacker is still short of its attack cost."""
        for pokemon in self._my_board():
            if pokemon is None or pokemon.id not in ATTACKER_IDS:
                continue
            data = card_table.get(pokemon.id)
            if data is None:
                continue
            req = min((ATTACK_DATA[a][1] for a in data.attacks if a in ATTACK_DATA), default=99)
            if len(pokemon.energies) < req:
                return True
        return False

    def _need_lightning_draw(self) -> bool:
        """Stuck: an attacker needs energy but we have no Lightning in hand to stream."""
        return self._needs_more_energy() and self.hand_counts[C.LIGHTNING_ENERGY] == 0

    # — MAIN: play —
    def _score_play(self, option) -> float:
        card = get_card(self.obs, AreaType.HAND, option.index, self.my_index)
        if card is None:
            return 0
        data = card_table.get(card.id)
        if data is None:
            return 0
        if data.cardType == CardType.POKEMON:
            return self._score_play_pokemon(card)
        return self._score_play_trainer(card)

    def _score_play_pokemon(self, card) -> float:
        # Develop the bench; avoid flooding with redundant copies.
        cid = card.id
        n = self.field_counts[cid]
        # vs Fighting, prioritise the Wattrel->Kilowattrel line (Fighting-safe attacker).
        wattrel_bonus = 2500 if self.fighting_threat else 0
        if cid == C.TADBULB:
            return 20000 - 200 * n  # main attacker line (still want Bellibolt engine, benched)
        if cid == C.WATTREL:
            return 19000 + wattrel_bonus - 200 * n
        if cid == C.VOLTORB:
            return 18000 - 300 * n
        return 17000 - 200 * n

    def _score_play_trainer(self, card) -> float:
        cid = card.id
        if cid == C.LILLIE_DET:
            if self._low_deck() or self.state.supporterPlayed:
                return -1
            # Draw only when hand is thin. (Firing it while "stranded without Lightning"
            # was a regression: it shuffles away a built-up board in the slow Crustle grind.)
            return 12000 if self._hand_size() <= 4 else 2600
        if cid == C.CANARI:
            if self.state.supporterPlayed:
                return -1
            # Need {L} Pokémon in play? value getting attackers.
            need = self._count_inplay_attackers() < 2
            return 11500 if need else 1500
        if cid == C.BUDDY_POFFIN:
            return 13000 if self._open_bench() and self._basics_in_deck_likely() else 600
        if cid == C.ULTRA_BALL:
            # Costs 2 cards; use to find a key Pokémon when board is thin.
            if self._count_inplay_attackers() < 2 and self._hand_size() >= 3:
                return 9000
            return 400
        if cid == C.POKE_PAD:
            return 8500 if self._count_inplay_attackers() < 2 else 500
        if cid == C.LEVINCIA:
            return self._score_levincia()
        if cid == C.NIGHT_STRETCHER:
            return 7000 if (self.discard_counts.get(C.BELLIBOLT_EX, 0)
                            or self.discard_counts.get(C.KILOWATTREL, 0)) else 300
        if cid == C.MAX_ROD:
            return 6000 if self.me.discard and self._low_deck() else 200
        if cid == C.ENERGY_RETRIEVAL:
            return 5000 if self.discard_counts.get(C.LIGHTNING_ENERGY, 0) >= 2 \
                and self.hand_counts[C.LIGHTNING_ENERGY] == 0 else 200
        return 9000

    def _score_levincia(self) -> float:
        if self.state.stadiumPlayed:
            return -1
        if self.stadium_id == C.LEVINCIA:
            return -1  # already ours
        # Replace opponent stadium, or set ours to recycle {L}.
        if self.stadium_id and self.stadium_id != C.LEVINCIA:
            return 9500
        if self.discard_counts.get(C.LIGHTNING_ENERGY, 0) >= 1:
            return 8000
        return 1500

    def _count_inplay_attackers(self) -> int:
        return sum(1 for p in self._my_board()
                   if p is not None and p.id in (C.BELLIBOLT_EX, C.KILOWATTREL, C.VOLTORB,
                                                 C.TADBULB, C.WATTREL))

    def _open_bench(self) -> bool:
        bench_used = sum(1 for p in self.me.bench if p is not None)
        return bench_used < getattr(self.me, "benchMax", 5)

    def _basics_in_deck_likely(self) -> bool:
        # Rough: we run 9 basics; if few are in play/hand, deck likely has some.
        in_play_or_hand = (self.field_counts[C.TADBULB] + self.field_counts[C.WATTREL]
                           + self.field_counts[C.VOLTORB]
                           + self.hand_counts[C.TADBULB] + self.hand_counts[C.WATTREL]
                           + self.hand_counts[C.VOLTORB])
        return in_play_or_hand < 9

    # — MAIN: evolve —
    def _score_evolve(self, option) -> float:
        target = get_card(self.obs, option.inPlayArea, option.inPlayIndex, self.my_index)
        if not isinstance(target, Pokemon):
            return 0
        # Evolving into our attackers is top priority.
        card = get_card(self.obs, AreaType.HAND, option.index, self.my_index)
        cid = card.id if card is not None else None
        base = 21000 if cid == C.BELLIBOLT_EX else 20500 if cid == C.KILOWATTREL else 19500
        # vs Fighting, get Kilowattrel online ahead of Bellibolt (our Fighting-safe attacker).
        if self.fighting_threat and cid == C.KILOWATTREL:
            base = 21500
        return base + len(target.energies) * 20

    # — MAIN: attach (manual energy) —
    def _score_attach(self, option) -> float:
        pokemon = get_card(self.obs, option.inPlayArea, option.inPlayIndex, self.my_index)
        if not isinstance(pokemon, Pokemon):
            return 0
        return self._energy_target_score(pokemon, option.inPlayArea == AreaType.ACTIVE)

    def _energy_target_score(self, pokemon, is_active) -> float:
        if pokemon.id not in ATTACKER_IDS:
            base = 200
        else:
            data = card_table.get(pokemon.id)
            req = min((ATTACK_DATA[a][1] for a in data.attacks if a in ATTACK_DATA), default=99) \
                if data else 99
            have = len(pokemon.energies)
            base = 8000 if have < req else 1200
            if pokemon.id == C.BELLIBOLT_EX:
                base += 400  # main attacker
            # vs Fighting decks, power up Kilowattrel (our Fighting-safe attacker) first.
            if self.fighting_threat and pokemon.id == C.KILOWATTREL:
                base += 600
        if is_active:
            base += 150
        return base

    # — MAIN: retreat —
    def _score_retreat(self) -> float:
        active = self.me.active[0] if self.me.active else None
        opp = self.opponent.active[0] if self.opponent.active else None
        if active is None or opp is None:
            return -1
        # vs Fighting: pull a Fighting-weak active (Bellibolt etc.) out of the line of
        # fire if we have a Fighting-safe attacker (Kilowattrel) ready on the bench.
        if self.fighting_threat and active.id in FIGHTING_WEAK_IDS:
            for p in self.me.bench:
                if p is not None and p.id in SAFE_VS_FIGHTING and self._best_damage_against(p, opp) > 0:
                    return 6500
        active_dmg = self._best_damage_against(active, opp)
        if active_dmg > 0:
            return -1  # active can fight; stay
        # Active can't damage opp (e.g. Bellibolt ex vs Crustle). Retreat to a fighter.
        for p in self.me.bench:
            if p is not None and self._best_damage_against(p, opp) > 0:
                return 6000
        return -1

    # — MAIN: attack —
    def _score_attack(self, option) -> float:
        active = self.me.active[0] if self.me.active else None
        opp = self.opponent.active[0] if self.opponent.active else None
        if active is None or opp is None:
            return 800
        dmg = self._attack_damage(active, option.attackId, opp)
        if dmg <= 0:
            return -1  # blocked (ex vs Crustle) or useless — prefer to retreat/setup
        score = 1000 + min(dmg, 280)
        if opp.hp <= dmg:
            score += 2500 + prize_count(opp) * 200  # KO!
        # Thunderous Bolt locks next turn; only matters if a backup attacker isn't ready,
        # but it is our biggest hit — keep using it. Tiny preference handled by damage.
        return score

    # — sub-select contexts —
    def _score_card_choice(self, option) -> float:
        card = get_card(self.obs, option.area, option.index, option.playerIndex)
        if card is None:
            return 0
        ctx = self.context
        if ctx in (SelectContext.SWITCH, SelectContext.TO_ACTIVE):
            return self._score_active_choice(option, card)
        if ctx == SelectContext.SETUP_ACTIVE_POKEMON:
            return self._score_setup_active(card)
        if ctx in (SelectContext.SETUP_BENCH_POKEMON, SelectContext.TO_BENCH, SelectContext.TO_FIELD):
            return self._score_to_bench(card)
        if ctx == SelectContext.TO_HAND:
            return self._score_to_hand(card)
        if ctx == SelectContext.ATTACH_TO:
            if isinstance(card, Pokemon):
                return self._energy_target_score(card, option.inPlayArea == AreaType.ACTIVE)
            return 0
        if ctx in (SelectContext.ATTACH_FROM, SelectContext.TO_HAND_ENERGY):
            # Prefer Lightning energy cards.
            return 100 if card.id == C.LIGHTNING_ENERGY else 10
        if ctx in (SelectContext.DISCARD, SelectContext.DISCARD_CARD_OR_ATTACHED_CARD,
                   SelectContext.DISCARD_ENERGY, SelectContext.DISCARD_ENERGY_CARD):
            return self._score_discard(card)
        if ctx in (SelectContext.DAMAGE_COUNTER, SelectContext.DAMAGE_COUNTER_ANY):
            if isinstance(card, Pokemon) and option.playerIndex == self.op_index:
                return 10000 + prize_count(card) * 1000 - getattr(card, "hp", 0)
            return -target_value(card) if isinstance(card, Pokemon) else 0
        if ctx in (SelectContext.TO_DECK, SelectContext.TO_DECK_BOTTOM,
                   SelectContext.TO_PRIZE, SelectContext.TO_DECK_ENERGY):
            return self._score_putback(card)
        return 0

    def _score_active_choice(self, option, card) -> float:
        if not isinstance(card, Pokemon):
            return 0
        if option.playerIndex != self.my_index:
            return 0  # we don't choose opponent's active here
        opp = self.opponent.active[0] if self.opponent.active else None
        score = len(card.energies) * 10
        if opp is not None and self._best_damage_against(card, opp) > 0:
            score += 200
        # vs Fighting: never promote a Fighting-weak body (Bellibolt/Voltorb/Tadbulb) if a
        # Fighting-safe one (Kilowattrel/Wattrel) is available — keep Bellibolt benched.
        if self.fighting_threat:
            if card.id in SAFE_VS_FIGHTING:
                score += 300
            elif card.id in FIGHTING_WEAK_IDS:
                score -= 250
            return score + 1
        # Prefer a non-ex body vs an immune opponent; prefer Bellibolt otherwise.
        if opp is not None and opp.id in IMMUNE_TO_EX:
            if card.id in (C.KILOWATTREL, C.VOLTORB):
                score += 150
        else:
            if card.id == C.BELLIBOLT_EX:
                score += 120
            elif card.id == C.KILOWATTREL:
                score += 60
        return score + 1

    def _score_setup_active(self, card) -> int:
        if card is None:
            return 0
        # Lead with a body that becomes / is an attacker. Tadbulb -> Bellibolt main line.
        if card.id == C.TADBULB:
            return 5
        if card.id == C.VOLTORB:
            return 4
        if card.id == C.WATTREL:
            return 3
        return 1

    def _score_to_bench(self, card) -> float:
        if card is None:
            return 0
        data = card_table.get(card.id)
        if data is None or data.cardType != CardType.POKEMON:
            return 0
        cid = card.id
        n = self.field_counts[cid]
        if cid == C.TADBULB:
            return 200 - 30 * n
        if cid == C.WATTREL:
            return 190 - 30 * n
        if cid == C.VOLTORB:
            return 170 - 40 * n
        return 100 - 20 * n

    def _score_to_hand(self, card) -> float:
        if card is None:
            return 0
        cid = card.id
        score = 200 - self.hand_counts[cid] * 60
        if cid == C.TADBULB:
            score += 40 if self.field_counts[C.BELLIBOLT_EX] + self.field_counts[C.TADBULB] < 2 else -20
        elif cid == C.BELLIBOLT_EX:
            score += 60 if self.field_counts[C.TADBULB] >= 1 else 0
        elif cid == C.WATTREL:
            score += 30 if self.field_counts[C.KILOWATTREL] + self.field_counts[C.WATTREL] < 1 else -10
        elif cid == C.KILOWATTREL:
            score += 50 if self.field_counts[C.WATTREL] >= 1 else 0
        elif cid == C.VOLTORB:
            score += 25
        elif cid == C.LIGHTNING_ENERGY:
            score += 35
        return score

    def _score_discard(self, card) -> float:
        if card is None:
            return 0
        cid = card.id
        # Positive = safe to discard. Keep Lightning and our key Pokémon.
        if cid == C.LIGHTNING_ENERGY:
            # We can usually spare a Lightning when flush; keep at least some.
            return 20 if self.hand_counts[cid] >= 3 else -60
        if self.hand_counts[cid] >= 2:
            return 60
        if cid in (C.TADBULB, C.WATTREL, C.VOLTORB, C.BELLIBOLT_EX, C.KILOWATTREL):
            return -50 if self.field_counts[cid] == 0 else 5
        if cid in (C.LILLIE_DET, C.CANARI) and self.state.supporterPlayed:
            return 30
        return 0

    def _score_putback(self, card) -> float:
        if card is None:
            return 0
        # Put back the least useful: extra copies, spare energy.
        cid = card.id
        if self.hand_counts[cid] >= 2:
            return 60
        if cid == C.LIGHTNING_ENERGY and self.hand_counts[cid] >= 3:
            return 40
        if cid in (C.TADBULB, C.BELLIBOLT_EX, C.WATTREL, C.KILOWATTREL):
            return -40
        return 10


def agent(obs_dict: dict) -> list[int]:
    global pre_turn

    try:
        select_is_none = isinstance(obs_dict, dict) and obs_dict.get("select") is None
    except Exception:
        select_is_none = False
    if select_is_none:
        _DIAG["deck_returns"] += 1
        return my_deck

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
            policy = BellipoltPolicy(obs)
            ranked, scores = policy.rank()
            selection = normalize_selection(ranked, scores, obs.select)
            # Value-guided shallow search refines the MAIN first-action.
            if (USE_VALUE_SEARCH and obs.select is not None
                    and obs.select.context == SelectContext.MAIN):
                a = value_search(obs, ranked)
                if a is not None:
                    selection = [a]
            _DIAG["policy_ok"] += 1
            return selection
        except Exception as exc:
            _diag_record_error(exc)
            _DIAG["policy_fallback"] += 1
            return _legal_fallback(obs.select)
    except Exception as exc:
        _diag_record_error(exc)
        _DIAG["obs_fallback"] += 1
        return _legal_fallback_from_dict(obs_dict if isinstance(obs_dict, dict) else {})
