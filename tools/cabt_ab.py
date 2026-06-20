"""A/B two of OUR agent dirs against each other in the official cabt env.

Each agent is loaded as a pre-built callable at cwd=ROOT so it reads its OWN deck.csv
once (same trick as cabt_eval._our_cb). Seats alternate every game so first/second
player advantage cancels out.

Usage: venv/bin/python tools/cabt_ab.py <dirA> <dirB> [games]
  e.g.  venv/bin/python tools/cabt_ab.py agents/alakazam_mist agents/alakazam 40
  Reports A's win-rate vs B.
"""
import sys, os, warnings
warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT + '/docs/official/models/cg-lib')


def load_cb(agent_dir):
    our = ROOT + '/' + agent_dir + '/main.py'
    if not os.path.exists(ROOT + '/' + agent_dir + '/cg'):
        import shutil; shutil.copytree(ROOT + '/docs/official/models/cg-lib/cg', ROOT + '/' + agent_dir + '/cg')
    from kaggle_environments.agent import get_last_callable
    cur = os.getcwd(); os.chdir(ROOT + '/' + agent_dir)
    try:
        cb = get_last_callable(open(our).read(), path=our)
    finally:
        os.chdir(cur)
    md = getattr(cb, '__globals__', {}).get('my_deck')
    assert md and len(md) == 60, f'{agent_dir} deck failed to load ({md and len(md)})'
    return cb


def main():
    dirA = sys.argv[1]
    dirB = sys.argv[2]
    games = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    a = load_cb(dirA)
    b = load_cb(dirB)
    from kaggle_environments import make
    w = [0, 0, 0]  # A wins, B wins, draws
    for g in range(games):
        env = make('cabt')
        order = [a, b] if g % 2 == 0 else [b, a]
        res = env.run(order)
        r = [s.get('reward') for s in res[-1]]
        us = 0 if g % 2 == 0 else 1
        ru, ro = r[us], r[1 - us]
        if ru is None: w[1] += 1
        elif ro is None: w[0] += 1
        elif ru > ro: w[0] += 1
        elif ro > ru: w[1] += 1
        else: w[2] += 1
        print(f'  game {g+1}/{games}: A={ru} B={ro}  [{w[0]}W/{w[1]}L/{w[2]}D]', flush=True)
    t = w[0] + w[1]
    print(f'[cabt A/B] {dirA} (A) vs {dirB} (B): {w[0]}W/{w[1]}L/{w[2]}D = A {w[0]/t*100:.0f}%' if t else 'no decisive games')


if __name__ == '__main__':
    main()
