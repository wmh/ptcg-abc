from __future__ import annotations
import os, sys, time, random
from collections import defaultdict

from cg.api import (
    AreaType, Card, CardType, EnergyType, Observation, OptionType,
    Pokemon, SelectContext, all_card_data, to_observation_class,
)

# ---------- Forward Search API (optional) ----------
_SEARCH_OK = False
try:
    from cg.api import search_begin, search_step, search_end, SearchState
    _SEARCH_OK = True
except Exception:
    pass

# ============================================================
# CONFIGURATION
# ============================================================
USE_SEARCH      = True
SEARCH_BUDGET   = 1.8        # seconds per decision
SEARCH_CANDS    = 6          # top-k actions to evaluate
SEARCH_DEPTH    = 40         # max forward steps
LOW_DECK        = 8          # anti-deckout threshold
MEGA_BRAVE_ID   = 983        # attack ID for Mega Brave
CRUSTLE_AWARE   = True       # route around Crustle's anti-ex wall
MAX_TURN_ACTIONS = 45        # anti-stall guard

# ============================================================
# CARD IDS  (Mega Lucario ex Deck)
# ============================================================
class C:
    MAKUHITA             = 673
    HARIYAMA             = 674
    LUNATONE             = 675
    SOLROCK              = 676
    RIOLU                = 677
    MEGA_LUCARIO_EX      = 678
    CRUSTLE              = 345
    BASIC_FIGHTING       = 6
    DUSK_BALL            = 1102
    SWITCH               = 1123
    PREMIUM_POWER_PRO    = 1141
    FIGHTING_GONG        = 1142
    POKE_PAD             = 1152
    HERO_CAPE            = 1159
    BOSS_ORDERS          = 1182
    CARMINE              = 1192
    LILLIE_DETERMINATION = 1227
    GRAVITY_MOUNTAIN     = 1252
    LUMIOSE_CITY         = 1267
    LILLIES_PEARL        = 1172
    LEGACY_ENERGY        = 12

# ---------- Hardcoded deck (60 cards) ----------
MY_DECK = [
    673,673, 674,674, 675,675, 676,676,676,
    677,677,677, 678,678,678,678,
    1102,1102,1102,1102, 1123,1123,
    1141,1141,1141,1141, 1142,1142,1142,1142,
    1152,1152,1152,1152, 1159,
    1182,1182, 1192,1192,1192,1192,
    1227,1227,1227,1227, 1252,1252,
    6,6,6,6,6,6,6,6,6,6,6,6,6,
]

# ---------- Card metadata ----------
_all = all_card_data()
CARD_DB = {c.cardId: c for c in _all}

# ---------- Global state ----------
_plan    = None
_turn    = -1
_ab_used = False

# ============================================================
# HELPERS
# ============================================================
def _get(obs, area, idx, pi):
    try:
        ps = obs.current.players[pi]
        match area:
            case AreaType.DECK:    return obs.select.deck[idx]
            case AreaType.HAND:    return ps.hand[idx]
            case AreaType.DISCARD: return ps.discard[idx]
            case AreaType.ACTIVE:  return ps.active[idx]
            case AreaType.BENCH:   return ps.bench[idx]
            case AreaType.PRIZE:   return ps.prize[idx]
            case AreaType.STADIUM: return obs.current.stadium[idx]
            case AreaType.LOOKING: return obs.current.looking[idx]
    except Exception:
        pass
    return None

def _prizes(p):
    d = CARD_DB.get(p.id)
    if d is None: return 1
    n = 3 if d.megaEx else 2 if d.ex else 1
    for c in p.energyCards:
        if c.id == C.LEGACY_ENERGY: n -= 1
    for c in p.tools:
        if c.id == C.LILLIES_PEARL and d.name and "Lillie" in d.name: n -= 1
    return max(0, n)

def _tgt_score(p):
    d = CARD_DB.get(p.id)
    s = _prizes(p) * 1000 + len(p.energies) * 150 + len(p.tools) * 100
    if d:
        s += 250 if d.stage2 else 130 if d.stage1 else 0
    if p.id in (144, 322, 323, 337): s -= 200
    if p.id == 112 and len(p.energies) >= 1: s += 300
    s += p.hp
    return s

# ============================================================
# ATTACK PLAN
# ============================================================
class Plan:
    __slots__ = ('atk','tgt','aidx','rhp','need_e')
    def __init__(self, atk=-1, tgt=-1, aidx=-1, rhp=-1, ne=False):
        self.atk=atk; self.tgt=tgt; self.aidx=aidx; self.rhp=rhp; self.need_e=ne

# ============================================================
# POLICY ENGINE
# ============================================================
class Policy:
    def __init__(self, obs):
        self.obs = obs
        self.st  = obs.current
        self.sel = obs.select
        self.ctx = self.sel.context
        self.mi  = self.st.yourIndex
        self.me  = self.st.players[self.mi]
        self.op  = self.st.players[1 - self.mi]
        self.mp  = len(self.me.prize)
        self.fc  = defaultdict(int)
        self.hc  = defaultdict(int)
        self.dc  = defaultdict(int)
        self.rdy_luc = False
        self.rdy_har = False
        self.sw = False; self.gust = False
        self.atk = False; self.mb = False
        self.sid = self.st.stadium[0].id if self.st.stadium else 0
        self.facing_crustle = any(p is not None and p.id == C.CRUSTLE for p in (self.op.active + self.op.bench))
        self._count(); self._scan()

    def choose(self):
        global _plan
        if self.ctx == SelectContext.MAIN:
            _plan = self._make_plan()
        scores = [self._sc(o) for o in self.sel.option]
        self._last_scores = scores
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        self._track_ab(ranked)
        return ranked

    # ---------- counting ----------
    def _count(self):
        for p in self.me.active + self.me.bench:
            if p is None: continue
            self.fc[p.id] += 1
            if p.id in (C.MAKUHITA, C.HARIYAMA) and len(p.energies) >= 3: self.rdy_har = True
            if p.id in (C.RIOLU, C.MEGA_LUCARIO_EX) and len(p.energies) >= 2: self.rdy_luc = True
        for c in self.me.hand:    self.hc[c.id] += 1
        for c in self.me.discard: self.dc[c.id] += 1

    def _scan(self):
        if self.ctx != SelectContext.MAIN: return
        for o in self.sel.option:
            if o.type == OptionType.PLAY:
                c = _get(self.obs, AreaType.HAND, o.index, self.mi)
                if c and c.id == C.SWITCH: self.sw = True
                if c and c.id == C.BOSS_ORDERS: self.gust = True
            elif o.type == OptionType.EVOLVE:
                c = _get(self.obs, AreaType.HAND, o.index, self.mi)
                if c and c.id == C.HARIYAMA: self.gust = True
            elif o.type == OptionType.RETREAT: self.sw = True
            elif o.type == OptionType.ATTACK:
                self.atk = True
                if o.attackId == MEGA_BRAVE_ID: self.mb = True

    # ---------- attack plan ----------
    def _base_atk(self, p, ai, bi):
        er = bd = bs = 0
        if p.id == C.MEGA_LUCARIO_EX:
            if ai == 0: er, bd = 1, 130; bs += 60 * min(3, self.dc[C.BASIC_FIGHTING])
            else:       er, bd = 2, 270
            if self.mp in (2, 3): bs -= 500
        elif ai == 1: return None
        elif p.id == C.HARIYAMA: er, bd = 3, 210
        elif p.id == C.MAKUHITA:
            if not self._can_evo(bi): return None
            er, bd, bs = 3, 210, -100
        elif p.id == C.SOLROCK and self.fc[C.LUNATONE] >= 1: er, bd = 1, 70
        return (er, bd, bs) if bd > 0 else None

    def _can_evo(self, bi):
        for o in self.sel.option:
            if o.type != OptionType.EVOLVE: continue
            ti = o.inPlayIndex + (1 if o.inPlayArea == AreaType.BENCH else 0)
            if ti == bi: return True
        return False

    def _make_plan(self):
        best_s, best_p = -1, Plan()
        if self.st.turn < 2: return best_p
        board_me = [self.me.active[0]] + list(self.me.bench) if self.me.active else list(self.me.bench)
        board_op = [self.op.active[0]] + list(self.op.bench) if self.op.active else list(self.op.bench)
        for ai_idx, mp in enumerate(board_me):
            if mp is None: continue
            if ai_idx != 0 and not self.sw: break
            for aidx in range(2):
                r = self._base_atk(mp, aidx, ai_idx)
                if r is None: continue
                er, bd, bs = r
                ec = len(mp.energies)
                if aidx == 1 and ai_idx == 0 and ec >= 2 and not self.mb: break
                ne = False
                if ec < er:
                    if self.hc[C.BASIC_FIGHTING] >= 1 and not self.st.energyAttached:
                        ec += 1; ne = ec >= er
                    if not ne: continue
                for ti, op in enumerate(board_op):
                    if op is None: continue
                    if ti != 0 and not self.gust: break
                    dmg = bd
                    d = CARD_DB.get(op.id)
                    if d:
                        if d.weakness == EnergyType.FIGHTING: dmg *= 2
                        elif d.resistance == EnergyType.FIGHTING: dmg -= 30
                    my_data = CARD_DB.get(mp.id)
                    crustle_immune = (
                        CRUSTLE_AWARE
                        and op.id == C.CRUSTLE
                        and my_data is not None
                        and (my_data.ex or my_data.megaEx)
                    )
                    if crustle_immune:
                        dmg = 0
                    sc = _tgt_score(op)
                    pr = _prizes(op) if op.hp <= dmg else 0
                    if pr == 0: sc *= dmg / max(1, op.hp)
                    if len(self.op.prize) <= pr: sc = 50000
                    if crustle_immune:
                        sc = -10000
                    sc += bs + (220 if ai_idx == 0 else 0) + (300 if ti == 0 else 0) + ec
                    if sc > best_s:
                        best_s = sc
                        best_p = Plan(ai_idx, ti, aidx, op.hp - dmg, ne)
        return best_p

    # ---------- energy targeting ----------
    def _e_sc(self, p, active):
        ec = len(p.energies); s = 8000 + (10 if active else 0)
        if p.id in (C.MAKUHITA, C.HARIYAMA):
            s += (1 if p.id == C.HARIYAMA else 0) + (100 if ec < 3 else 0) - (50 if self.rdy_har else 0)
            if self.facing_crustle and ec < 3:
                s += 900
        elif p.id == C.LUNATONE: s -= 100
        elif p.id == C.SOLROCK: s += 20 if ec < 1 else -100
        elif p.id in (C.RIOLU, C.MEGA_LUCARIO_EX):
            s += (1 if p.id == C.MEGA_LUCARIO_EX else 0) + (100 if ec < 2 else 0) - (50 if self.rdy_luc else 0)
            if self.facing_crustle:
                s -= 500
        return s

    def _low(self): return self.me.deckCount <= LOW_DECK

    # ---------- option scoring ----------
    def _sc(self, o):
        t = o.type
        if t == OptionType.NUMBER: return o.number
        if t == OptionType.YES: return 100 if self.ctx == SelectContext.IS_FIRST else 1
        if t == OptionType.NO: return 0
        if t == OptionType.CARD:   return self._sc_card(o)
        if t == OptionType.PLAY:   return self._sc_play(o)
        if t == OptionType.ATTACH: return self._sc_attach(o)
        if t == OptionType.EVOLVE: return self._sc_evolve(o)
        if t == OptionType.ABILITY: return self._sc_ability(o)
        if t == OptionType.RETREAT:
            return 2000 if _plan and _plan.atk >= 1 else -1
        if t == OptionType.ATTACK:
            if _plan and _plan.aidx == 1: return 1100 if o.attackId == MEGA_BRAVE_ID else 1000
            return 1100 if o.attackId != MEGA_BRAVE_ID else 1000
        return 0

    def _sc_card(self, o):
        c = _get(self.obs, o.area, o.index, o.playerIndex)
        if c is None: return 0
        if self.ctx in (SelectContext.SWITCH, SelectContext.TO_ACTIVE):
            if o.playerIndex != self.mi:
                return 100 if _plan and o.index == _plan.tgt - 1 else 0
            if not isinstance(c, Pokemon): return 0
            s = len(c.energies) * 2
            if _plan and o.index == _plan.atk - 1: s += 100
            if c.id == C.MEGA_LUCARIO_EX: s += 8 if self.mp in (2,3) else 20
            elif c.id == C.HARIYAMA and len(c.energies) >= 2: s += 15
            elif c.id == C.MAKUHITA and len(c.energies) >= 2: s += 10
            elif c.id == C.SOLROCK: s += 5
            elif c.id == C.RIOLU: s += 4
            return s
        if self.ctx == SelectContext.SETUP_ACTIVE_POKEMON:
            if c.id == C.SOLROCK: return 2 if self.st.firstPlayer == self.mi else 4
            if c.id == C.RIOLU: return 3
            if c.id == C.MAKUHITA: return 1
            return 0
        if self.ctx == SelectContext.TO_HAND:
            s = 200 - self.hc.get(c.id, 0) * 100
            cid = c.id
            if cid == C.MAKUHITA:
                s += -10 if self.fc[cid] >= 1 else 10
                if self.facing_crustle:
                    s += 200
            elif cid == C.HARIYAMA:
                s += 20 if self.fc[C.MAKUHITA] >= 1 else -20
                if self.facing_crustle:
                    s += 250
            elif cid == C.LUNATONE: s += -250 if self.fc[cid] >= 1 else 60
            elif cid == C.SOLROCK: s += -250 if self.fc[cid] >= 1 else 50
            elif cid == C.RIOLU:
                ll = self.fc[C.RIOLU] + self.fc[C.MEGA_LUCARIO_EX]
                s += -150 if ll >= 2 else (-3 if ll >= 1 else 40)
            elif cid == C.MEGA_LUCARIO_EX: s += 40 if self.fc[C.RIOLU] >= 1 else -15
            elif cid == C.BASIC_FIGHTING: s += 30 if not _ab_used or not self.st.energyAttached else -1
            return s
        if self.ctx == SelectContext.ATTACH_FROM and isinstance(c, Pokemon):
            return self._e_sc(c, o.area == AreaType.ACTIVE)
        return 0

    def _sc_play(self, o):
        c = _get(self.obs, AreaType.HAND, o.index, self.mi)
        if c is None: return 0
        d = CARD_DB.get(c.id)
        if d and d.cardType == CardType.POKEMON:
            if c.id in (C.LUNATONE, C.SOLROCK) and self.fc[c.id] >= 1: return -1
            if c.id == C.RIOLU and self.fc[C.RIOLU] + self.fc[C.MEGA_LUCARIO_EX] >= 2: return -1
            return 20000
        # Trainer
        if c.id == C.SWITCH: return 6000 if _plan and _plan.atk > 0 else -1
        if c.id == C.PREMIUM_POWER_PRO:
            if self.st.supporterPlayed and _plan and _plan.rhp <= 0: return -1
            if not self.atk:
                ok = not self.st.supporterPlayed and self.hc[C.CARMINE] > 0 and self.hc[C.LILLIE_DETERMINATION] == 0 and not self._low()
                return 3050 if ok else -1
            return 5000
        if c.id == C.BOSS_ORDERS:
            if _plan and _plan.tgt >= 1:
                return 3600 if self.facing_crustle else 3200
            return -1
        if c.id == C.CARMINE: return -1 if self._low() else 3000
        if c.id == C.LILLIE_DETERMINATION: return -1 if self._low() else 3100
        if c.id == C.GRAVITY_MOUNTAIN:
            has_s2 = any(p and CARD_DB.get(p.id) and CARD_DB[p.id].stage2
                         for p in (self.op.active + self.op.bench) if p)
            if has_s2: return 3500
            if self.facing_crustle and self.sid:
                return 3400
            return 1200 if self.sid else -1
        return 10000

    def _sc_attach(self, o):
        c = _get(self.obs, AreaType.HAND, o.index, self.mi)
        p = _get(self.obs, o.inPlayArea, o.inPlayIndex, self.mi)
        if not isinstance(p, Pokemon) or c is None: return 0
        if c.id == C.HERO_CAPE:
            s = 7000
            if p.id == C.RIOLU: s += 100
            elif p.id == C.MEGA_LUCARIO_EX: s += 200
            return s
        s = self._e_sc(p, o.inPlayArea == AreaType.ACTIVE)
        bi = o.inPlayIndex if o.inPlayArea == AreaType.ACTIVE else o.inPlayIndex + 1
        if _plan and bi == _plan.atk and _plan.need_e: s += 200
        return s

    def _sc_evolve(self, o):
        p = _get(self.obs, o.inPlayArea, o.inPlayIndex, self.mi)
        if not isinstance(p, Pokemon): return 0
        if p.id == C.MAKUHITA and _plan and _plan.tgt == 0 and not self.facing_crustle: return -1
        if p.id == C.MAKUHITA and self.facing_crustle: return 9600 + len(p.energies)
        return 9000 + len(p.energies)

    def _sc_ability(self, o):
        c = _get(self.obs, o.area, o.index, self.mi)
        if c is None: return 0
        if c.id == C.LUMIOSE_CITY: return 1
        if c.id == C.LUNATONE and self._low(): return -1
        return 30000

    def _track_ab(self, ranked):
        global _ab_used
        if self.ctx != SelectContext.MAIN or not ranked: return
        o = self.sel.option[ranked[0]]
        if o.type == OptionType.ABILITY:
            c = _get(self.obs, o.area, o.index, self.mi)
            if c and c.id == C.LUNATONE: _ab_used = True

# ============================================================
# FORWARD SEARCH
# ============================================================
def _eval_state(obs):
    st = obs.current
    if st is None: return 0.0
    me = st.players[st.yourIndex]; op = st.players[1 - st.yourIndex]
    v  = (len(op.prize) - len(me.prize)) * 10000.0
    for p in ([me.active[0]] if me.active else []) + list(me.bench):
        if p is None: continue
        v += len(p.energies) * 120.0
        if p.id == C.MEGA_LUCARIO_EX: v += 400
        elif p.id == C.HARIYAMA: v += 200
    if me.active and me.active[0]: v += me.active[0].hp
    if op.active and op.active[0]: v -= op.active[0].hp * 1.5
    v += me.handCount * 5
    return v

def _search(obs_dict, obs):
    if not (_SEARCH_OK and USE_SEARCH): return None
    sel = obs.select
    if sel is None or sel.context != SelectContext.MAIN: return None
    sbi = getattr(obs, "search_begin_input", None) or obs_dict.get("search_begin_input")
    if sbi is None: return None
    base = Policy(obs).choose()
    cands = base[:SEARCH_CANDS]
    best_i, best_v = None, float("-inf")
    t0 = time.time()
    for first in cands:
        if time.time() - t0 > SEARCH_BUDGET: break
        sid = None
        try:
            res = search_begin(sbi)
            if getattr(res, "error", 0) != 0 or res.state is None: return None
            sid = res.state.searchId; cur = res.state.observation
            sel_a = [first]; steps = 0
            while steps < SEARCH_DEPTH:
                ar = search_step(sid, sel_a)
                if getattr(ar, "error", 0) != 0 or ar.state is None: break
                cur = ar.state.observation
                if cur.select is None or cur.current is None: break
                if cur.current.result is not None and cur.current.result != -1: break
                if cur.current.yourIndex != obs.current.yourIndex: break
                sub = Policy(cur).choose()
                if cur.select.context != SelectContext.MAIN:
                    sel_a = sub[:max(1, cur.select.minCount)]
                else:
                    sel_a = [sub[0]]
                    if cur.select.option[sub[0]].type == OptionType.END:
                        ar2 = search_step(sid, sel_a)
                        if ar2.state: cur = ar2.state.observation
                        break
                steps += 1
            v = _eval_state(cur)
            if v > best_v: best_v, best_i = v, first
        except Exception:
            return None
        finally:
            try:
                if sid is not None: search_end()
            except Exception: pass
    if best_i is None: return None
    rest = [i for i in base if i != best_i]
    return [best_i] + rest

def _normalize_selection(ordered, scores, select):
    n = len(select.option)
    minc = max(0, min(select.minCount, n))
    maxc = max(minc, min(select.maxCount, n))
    out = []
    seen = set()
    for i in ordered or []:
        if not isinstance(i, int) or i < 0 or i >= n or i in seen:
            continue
        score = scores[i] if scores is not None and i < len(scores) else 0
        if score > 0 or len(out) < minc:
            out.append(i); seen.add(i)
        if len(out) >= maxc:
            break
    for i in range(n):
        if len(out) >= minc:
            break
        if i not in seen:
            out.append(i); seen.add(i)
    return out

# ============================================================
# AGENT ENTRY POINT
# ============================================================
def agent(obs_dict: dict) -> list[int]:
    global _plan, _turn, _ab_used
    try:
        obs = to_observation_class(obs_dict)
    except Exception:
        return MY_DECK if obs_dict.get("select") is None else [0]
    if obs.select is None:
        return MY_DECK
    if _turn != obs.current.turn:
        _turn = obs.current.turn; _ab_used = False; _plan = Plan()
    try:
        if (obs.current is not None and obs.select.context == SelectContext.MAIN
                and getattr(obs.current, 'turnActionCount', 0) >= MAX_TURN_ACTIONS):
            for i, opt in enumerate(obs.select.option):
                if opt.type == OptionType.END:
                    return [i]
        ordered = None
        if USE_SEARCH:
            ordered = _search(obs_dict, obs)
        policy = Policy(obs)
        if ordered is None:
            ordered = policy.choose()
        else:
            policy.choose()
        scores = getattr(policy, '_last_scores', None)
        result = _normalize_selection(ordered, scores, obs.select)
        if result:
            return result
        n = len(obs.select.option)
        return list(range(min(max(0, obs.select.minCount), n)))
    except Exception:
        n = len(obs.select.option)
        k = max(0, obs.select.minCount) if n else 0
        return list(range(min(k, n)))
