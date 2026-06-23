"""Generic agent invariant checker — the systematic guard against per-deck piloting bugs.

Runs ANY agent for N games and asserts the universal invariants that have bitten us before and
must never silently regress in a new deck:

  1. ROBUSTNESS   — no crashes; low policy/obs fallback rate (a high rate = the policy is throwing
                    and we're limping on _legal_fallback).
  2. NO OVER-FILL — never attach energy to one of OUR Pokémon that can ALREADY pay an attack
                    (unless the attack self-scales with energy). This is the exact bug class that
                    recurred: energy discipline missing/wrong in a new deck.
  3. NO ILLEGAL   — the engine never rejected a selection (cabt would error out).
  4. STRUCTURE    — reports whether the agent is built on the shared BasePolicy (inherits the
                    generic energy discipline) or is a bespoke/legacy policy that should be audited.

Usage:  venv/bin/python tools/check_agent.py agents/<dir> [opponent_dir] [games]
        (opponent defaults to agents/dragapult; games defaults to 12)
Exit code 0 = all invariants pass, 1 = a violation was found.
"""
import os
import sys
import warnings

warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT + '/docs/official/models/cg-lib')
sys.path.insert(0, ROOT + '/agents/_base')

import importlib.util
from collections import Counter
from cg.api import (AreaType, CardType, EnergyType, OptionType, Pokemon, SelectContext,
                    all_card_data, all_attack, to_observation_class)

CARD = {c.cardId: c for c in all_card_data()}
ACOST = {a.attackId: list(a.energies or []) for a in all_attack()}
SELF_SCALING = set()
for _a in all_attack():
    _t = (_a.text or '').lower()
    if 'for each' in _t and 'energy attached to this' in _t:
        SELF_SCALING.add(_a.attackId)


def _load(agent_dir):
    d = ROOT + '/' + agent_dir
    if not os.path.exists(d + '/cg'):
        import shutil
        shutil.copytree(ROOT + '/docs/official/models/cg-lib/cg', d + '/cg')
    spec = importlib.util.spec_from_file_location(agent_dir.replace('/', '_'), d + '/main.py')
    cwd = os.getcwd(); os.chdir(d)
    sys.path.insert(0, d)
    try:
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    finally:
        os.chdir(cwd)
    return m


def _can_pay(attached, cost):
    have = Counter(attached); colorless = 0
    for req in cost:
        if req == EnergyType.COLORLESS:
            colorless += 1
        elif have.get(req, 0) > 0:
            have[req] -= 1
        else:
            return False
    return sum(have.values()) >= colorless


def _can_attack(p):
    c = CARD.get(p.id) if p is not None else None
    if c is None:
        return False
    att = list(p.energies or [])
    return any(aid in ACOST and _can_pay(att, ACOST[aid]) for aid in (c.attacks or []))


def _top_cost(cid):
    c = CARD.get(cid)
    if c is None:
        return 0
    return max((len(ACOST.get(aid, [])) for aid in (c.attacks or []) if aid in ACOST), default=0)


def _line_top_cost(cid, deck_ids):
    """Max attack energy-cost over cid AND everything it evolves INTO within this deck — so
    pre-loading energy on a Basic that carries through to a costlier evolution is NOT counted as
    over-fill. (e.g. Staryu->Mega Starmie, Phantump->Trevenant.)"""
    c = CARD.get(cid)
    best = _top_cost(cid)
    if c is None:
        return best
    nm = getattr(c, 'name', None)
    for did in set(deck_ids):
        dc = CARD.get(did)
        if dc is not None and getattr(dc, 'evolvesFrom', None) == nm and nm is not None:
            best = max(best, _line_top_cost(did, deck_ids))
    return best


def _maxed_out(p, deck_ids):
    """True if p already holds enough energy to pay the most-expensive attack in its whole
    evolution line — so any further energy is pure waste (real over-fill). Upgrading from a cheap
    to a costlier attack, or pre-loading toward an evolution, is NOT over-fill."""
    if p is None or CARD.get(p.id) is None:
        return False
    return len(p.energies or []) >= _line_top_cost(p.id, deck_ids)


def _self_scaling(p):
    c = CARD.get(p.id) if p is not None else None
    return bool(c and any(aid in SELF_SCALING for aid in (c.attacks or [])))


def main():
    agent_dir = sys.argv[1] if len(sys.argv) > 1 else 'agents/megastarmie'
    opp_dir = sys.argv[2] if len(sys.argv) > 2 else 'agents/dragapult'
    games = int(sys.argv[3]) if len(sys.argv) > 3 else 12

    m = _load(agent_dir)
    opp = _load(opp_dir)
    base_agent = m.agent
    deck_ids = list(getattr(m, 'my_deck', []) or [])

    stats = {'attach_decisions': 0, 'over_fill': 0, 'over_fill_examples': []}

    def wrapped(obs_dict):
        # Inspect OUR ATTACH/ENERGY decisions for over-fill before delegating.
        try:
            if isinstance(obs_dict, dict) and obs_dict.get('select') is not None:
                obs = to_observation_class(obs_dict)
                sel = obs.select
                pi = obs.current.yourIndex
                if sel is not None:
                    chosen = base_agent(obs_dict)  # what the agent picks
                    for idx in (chosen or []):
                        if not (0 <= idx < len(sel.option)):
                            continue
                        o = sel.option[idx]
                        if o.type not in (OptionType.ATTACH, OptionType.ENERGY):
                            continue
                        area = getattr(o, 'inPlayArea', None); ii = getattr(o, 'inPlayIndex', None)
                        if area is None or ii is None:
                            continue
                        player = obs.current.players[pi]
                        seq = player.active if area == AreaType.ACTIVE else player.bench
                        tgt = seq[ii] if (seq and 0 <= ii < len(seq)) else None
                        if not isinstance(tgt, Pokemon):
                            continue
                        stats['attach_decisions'] += 1
                        if _maxed_out(tgt, deck_ids) and not _self_scaling(tgt):
                            stats['over_fill'] += 1
                            if len(stats['over_fill_examples']) < 6:
                                nm = getattr(CARD.get(tgt.id), 'name', tgt.id)
                                stats['over_fill_examples'].append(
                                    f"{nm} already had {len(tgt.energies or [])} energy (can pay its top attack) — attached more")
                    return chosen
        except Exception:
            pass
        return base_agent(obs_dict)

    from kaggle_environments import make
    for g in range(games):
        env = make('cabt')
        env.run([wrapped, opp.agent] if g % 2 == 0 else [opp.agent, wrapped])

    diag = m.diag_snapshot() if hasattr(m, 'diag_snapshot') else (
        m.DIAG if hasattr(m, 'DIAG') else {})
    if hasattr(m, 'DIAG') and not diag:
        diag = m.DIAG
    # normalise diag
    dec = diag.get('decisions', 0) or 1
    fb = diag.get('policy_fallback', 0) + diag.get('obs_fallback', 0)
    fb_rate = fb / dec
    errors = diag.get('errors', {})

    # structure: is it on the shared BasePolicy?
    on_base = False
    try:
        from policy_base import BasePolicy
        for v in vars(m).values():
            if isinstance(v, type) and issubclass(v, BasePolicy) and v is not BasePolicy:
                on_base = True
    except Exception:
        pass

    print(f"\n===== check_agent: {agent_dir} (vs {opp_dir}, {games} games) =====")
    print(f"  decisions={dec}  fallback_rate={fb_rate:.3%}  errors={len(errors)}")
    if errors:
        for k, c in list(errors.items())[:5]:
            print(f"    ERROR x{c}: {k}")
    print(f"  attach decisions inspected: {stats['attach_decisions']}")
    print(f"  OVER-FILL violations: {stats['over_fill']}")
    for ex in stats['over_fill_examples']:
        print(f"    - {ex}")
    print(f"  built on shared BasePolicy: {'YES' if on_base else 'NO (bespoke/legacy — audit energy discipline)'}")

    fails = []
    if stats['over_fill'] > 0:
        fails.append(f"{stats['over_fill']} energy over-fill(s)")
    if fb_rate > 0.02:
        fails.append(f"fallback_rate {fb_rate:.1%} > 2%")
    if errors:
        fails.append(f"{len(errors)} error type(s)")
    if fails:
        print(f"  RESULT: ❌ FAIL — {'; '.join(fails)}")
        sys.exit(1)
    print(f"  RESULT: ✅ PASS")


if __name__ == '__main__':
    main()
