"""cabt_gauntlet — run an agent against the REAL current top-100 field, prevalence-weighted.

The old cabt opponents (crustle/lucario/abomasnow) are extinct in the live meta, which is a prime
reason cabt mispredicts the ladder. This gauntlet pits our agent against the ACTUAL top-tier field
(Elo>=1000, from 7-05 episodes — the meta flipped completely ~6-28→7-01):

    Marnie's Grimmsnarl ex 38.6% | Alakazam(741 non-ex) 17.5% | Mega Kangaskhan ex 11.6%
    Cynthia's Garchomp ex 10.4% | Cornerstone Ogerpon ex 6.7% | Dusknoir 3.7% | Cinderace 2.0%

Opponents are our own tuned agents where we have them (Alakazam), and GenericPolicy-piloted
top-player decklists for the new-meta decks (grimmsnarl=iwashi, garchomp=nasuo445,
kangaskhan=zoroark190, ogerpon=btk15049 — all pulled from 7-05 episodes, Elo>=1000).
Games are allocated proportional to field share; reports per-opponent win-rate plus a single
prevalence-WEIGHTED overall.

Usage: venv/bin/python tools/cabt_gauntlet.py agents/<dir> [total_games]
"""
import os
import sys
import warnings

warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT + '/docs/official/models/cg-lib')
sys.path.insert(0, ROOT + '/agents/_base')

# field share (%) in the Elo>=1000 top tier (7-05). Opponent kind: 'agent' = a main.py dir,
# 'generic' = a deck.csv piloted by GenericPolicy.
# THE 5 OPPONENTS = the 5 most-prevalent top-tier decks (~85% of the Elo>=1000 field).
# (Old-meta opponents Trevenant/Dragapult/Lucario-v3/Chandelure dropped — extinct on the ladder.)
FIELD = [
    ('Grimmsnarl', 38.6, 'generic', 'agents/grimmsnarl'),
    ('Alakazam',   17.5, 'agent',   'agents/alakazam'),
    ('Kangaskhan', 11.6, 'generic', 'agents/kangaskhan'),
    ('Garchomp',   10.4, 'generic', 'agents/garchomp'),
    ('Ogerpon',     6.7, 'generic', 'agents/ogerpon'),
]


def _copy_cg(d):
    if not os.path.exists(d + '/cg'):
        import shutil
        shutil.copytree(ROOT + '/docs/official/models/cg-lib/cg', d + '/cg')


def load_main_agent(agent_dir):
    """Load a main.py-based agent, reading its OWN deck.csv (chdir during load)."""
    d = ROOT + '/' + agent_dir
    _copy_cg(d)
    from kaggle_environments.agent import get_last_callable
    cur = os.getcwd(); os.chdir(d)
    sys.path.insert(0, d)
    try:
        cb = get_last_callable(open(d + '/main.py').read(), path=d + '/main.py')
    finally:
        os.chdir(cur)
    return cb


def load_generic_agent(deck_dir):
    deck = [int(x) for x in open(ROOT + '/' + deck_dir + '/deck.csv') if x.strip()]
    from generic_policy import make_generic_agent
    return make_generic_agent(deck)


def build_opponent(kind, path):
    return load_main_agent(path) if kind == 'agent' else load_generic_agent(path)


def main():
    our_dir = sys.argv[1] if len(sys.argv) > 1 else 'agents/megastarmie'
    total = int(sys.argv[2]) if len(sys.argv) > 2 else 160
    our = load_main_agent(our_dir)

    from kaggle_environments import make
    tot_share = sum(f[1] for f in FIELD)
    results = []
    weighted_num = weighted_den = 0.0
    print(f"\n=== cabt_gauntlet: {our_dir} vs the real top-100 field ({total} games) ===")
    for name, share, kind, path in FIELD:
        n = max(6, round(total * share / tot_share))
        try:
            opp = build_opponent(kind, path)
        except Exception as e:
            print(f"  {name:12} SKIP (load failed: {str(e)[:50]})")
            continue
        w = l = d = 0
        for g in range(n):
            env = make('cabt')
            order = [our, opp] if g % 2 == 0 else [opp, our]
            res = env.run(order)
            r = [s.get('reward') for s in res[-1]]
            us = 0 if g % 2 == 0 else 1
            ru, ro = r[us], r[1 - us]
            if ru is None:
                l += 1
            elif ro is None:
                w += 1
            elif ru > ro:
                w += 1
            elif ro > ru:
                l += 1
            else:
                d += 1
        played = w + l
        wr = (w / played * 100) if played else 0
        results.append((name, share, w, l, d, wr))
        weighted_num += share * wr
        weighted_den += share
        print(f"  {name:12} ({share:4.1f}%)  {w:2}W/{l:2}L/{d}D = {wr:3.0f}%")
    if weighted_den:
        print(f"  {'-'*40}")
        print(f"  PREVALENCE-WEIGHTED overall WR: {weighted_num/weighted_den:.1f}%")


if __name__ == '__main__':
    main()
