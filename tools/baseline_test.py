#!/usr/bin/env python3
"""Baseline test — run OUR agent vs a fixed set of opponents using GenericPolicy 
(consistent quality), N games per matchup, record WR.

Usage:
  venv/bin/python tools/baseline_test.py agents/megastarmie  [games_per_opp=40]
  venv/bin/python tools/baseline_test.py agents/trevenant    [games_per_opp=40]
"""
import sys, os, warnings
warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT + '/docs/official/models/cg-lib')
sys.path.insert(0, ROOT + '/agents/_base')

from importlib import util as iutil
from kaggle_environments import make

# ── load our agent ──────────────────────────────────────────────────────────
def load_our_agent(agent_dir):
    d = ROOT + '/' + agent_dir
    if not os.path.exists(d + '/cg'):
        import shutil
        shutil.copytree(ROOT + '/docs/official/models/cg-lib/cg', d + '/cg')
    from kaggle_environments.agent import get_last_callable
    cur = os.getcwd(); os.chdir(d); sys.path.insert(0, d)
    try:
        cb = get_last_callable(open(d + '/main.py').read(), path=d + '/main.py')
    finally:
        os.chdir(cur)
    return cb

# ── load opponent ──────────────────────────────────────────────────────────
def load_main_opponent(agent_dir):
    d = ROOT + '/' + agent_dir
    if not os.path.exists(d + '/cg'):
        import shutil
        shutil.copytree(ROOT + '/docs/official/models/cg-lib/cg', d + '/cg')
    from kaggle_environments.agent import get_last_callable
    cur = os.getcwd(); os.chdir(d); sys.path.insert(0, d)
    try:
        cb = get_last_callable(open(d + '/main.py').read(), path=d + '/main.py')
    finally:
        os.chdir(cur)
    return cb

def load_generic_opponent(deck_path):
    """Load a GenericPolicy pilot for a given deck CSV."""
    deck = [int(x) for x in open(deck_path) if x.strip()]
    from generic_policy import make_generic_agent
    return make_generic_agent(deck)

# ── opponents ──────────────────────────────────────────────────────────────
# Each: (name, type, path)
# type='sample' -> use the agent's main.py directly (official sample)
# type='generic' -> use GenericPolicy + deck.csv
# type='community' -> use the agent's main.py (known 3rd-party pilot)
OPPONENTS = [
    ('Dragapult ex',  'sample',   'agents/dragapult'),
    ('Chandelure',    'generic',  'agents/chandelure/deck.csv'),
    ('Mega Froslass', 'generic',  'agents/froslass/deck.csv'),
    ('Mega Lucario',  'community','agents/lucario_v3'),
    ('Mega Starmie',  'mirror',   None),   # our OWN agent piloted 2x (true mirror)
    ('Mewtwo ex',     'generic',  'agents/mewtwo/deck.csv'),
]

def build_opp(typ, path, our_dir=None):
    if typ == 'sample':
        return load_main_opponent(path)
    elif typ == 'generic':
        return load_generic_opponent(path)
    elif typ == 'community':
        return load_main_opponent(path)
    elif typ == 'mirror' and our_dir:
        # Load our own agent again as a fresh instance for a TRUE mirror match
        return load_main_opponent(our_dir)
    raise ValueError(f'unknown type {typ}')

# ── main ───────────────────────────────────────────────────────────────────
def main():
    our_dir = sys.argv[1] if len(sys.argv) > 1 else 'agents/megastarmie'
    games_per = int(sys.argv[2]) if len(sys.argv) > 2 else 40

    our = load_our_agent(our_dir)
    results = []
    print(f"\n{'='*60}")
    print(f"Baseline: {our_dir}")
    print(f"Games per opponent: {games_per}  |  Total: {games_per * len(OPPONENTS)}")
    print(f"{'='*60}\n")
    for name, typ, path in OPPONENTS:
        opp = build_opp(typ, path, our_dir if typ == 'mirror' else None)
        w = l = d = 0
        for g in range(games_per):
            env = make('cabt')
            order = [our, opp] if g % 2 == 0 else [opp, our]
            res = env.run(order)
            r = [s.get('reward') for s in res[-1]]
            us = 0 if g % 2 == 0 else 1
            ru, ro = r[us], r[1 - us]
            if ru is None: l += 1
            elif ro is None: w += 1
            elif ru > ro: w += 1
            elif ro > ru: l += 1
            else: d += 1
        played = w + l
        wr = (w / played * 100) if played else 0
        ci95 = 1.96 * ((wr/100 * (1 - wr/100)) / played)**0.5 * 100 if played > 0 else 0
        results.append((name, w, l, d, wr, ci95))
        print(f"  {name:20s}  {w:3d}W/{l:2d}L/{d}D  = {wr:4.0f}%  (±{ci95:.0f}%)")
    print(f"\n{'─'*55}")
    # simple average (unweighted)
    avg = sum(r[4] for r in results) / len(results)
    total_w = sum(r[1] for r in results)
    total_l = sum(r[2] for r in results)
    total_p = total_w + total_l
    overall = (total_w / total_p * 100) if total_p else 0
    print(f"  RAW overall WR: {total_w}W/{total_l}L = {overall:.0f}%  ({total_p} decisive games)")
    print(f"  Per-opponent average: {avg:.0f}%")
    print()

if __name__ == '__main__':
    main()
