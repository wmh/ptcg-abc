"""Replay divergence — mine piloting fixes from TOP-PLAYER games.

For every game where a strong player (ladder Elo >= --elo) piloted OUR archetype and WON,
we replay each of their in-game observations through OUR agent and compare our chosen
option(s) to what the human actually did. Decisions where we DISAGREE are the concrete
piloting bugs to fix; they're bucketed by SelectContext so you can see where we differ most
(e.g. ATTACK target, ATTACH, retreat, gust). Forced decisions (a single legal option) are
skipped — only genuine choices count.

Episode obs are directly compatible: steps[t][pi]['observation'] feeds agent(). ALIGNMENT:
the answer to obs[t] is recorded as the NEXT step's action, steps[t+1][pi]['action'] (within
a turn, a player's sub-decisions are consecutive same-pi steps). steps[1]'s action is the deck
(special) and turn-ending decisions land on the opponent's step — both are skipped. We compare
our agent's option indices to the human's as sets.

Usage:
  venv/bin/python tools/replay_divergence.py <episode_zip> <agent_dir> [--elo 1150]
                  [--archetype Alakazam] [--max-games 80] [--lb /tmp/lb]
  venv/bin/python tools/replay_divergence.py /tmp/ep19/...zip agents/alakazam --archetype Alakazam
"""
import sys, os, json, zipfile, argparse, importlib.util, warnings
from collections import defaultdict, Counter
warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT + '/docs/official/models/cg-lib')

# reuse dk() + load_elo() from meta_analyze
_spec = importlib.util.spec_from_file_location('ma', ROOT + '/tools/meta_analyze.py')
ma = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ma)
from cg.api import SelectContext

CTX_NAME = {int(c.value): c.name for c in SelectContext}


def load_agent(agent_dir):
    """Load the agent module at cwd=its dir so its deck.csv resolves; return agent()."""
    cur = os.getcwd()
    os.chdir(ROOT + '/' + agent_dir)
    try:
        spec = importlib.util.spec_from_file_location('our_agent', 'main.py')
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        os.chdir(cur)
    return m.agent


def analyze(zip_path, agent_dir, archetype, elo_cut, max_games, lb_dir):
    elo = ma.load_elo(lb_dir)
    agent = load_agent(agent_dir)
    z = zipfile.ZipFile(zip_path)
    names = [x for x in z.namelist() if x.endswith('.json')]

    per_ctx = defaultdict(lambda: [0, 0])     # context -> [agree, total] over real choices
    samples = defaultdict(list)               # context -> example divergences
    games = decisions = 0
    for nm in names:
        if games >= max_games:
            break
        try:
            d = json.loads(z.read(nm))
            rw = d['rewards']
            if rw[0] == rw[1]:
                continue
            win = 0 if rw[0] > rw[1] else 1
            pl = [a['Name'] for a in d['info']['Agents']]
            decks = [d['steps'][1][0]['action'], d['steps'][1][1]['action']]
            # focal player: the WINNER, who must be a top player on OUR archetype
            pi = win
            if elo.get(pl[pi], 0) < elo_cut:
                continue
            if ma.dk(decks[pi]) != archetype:
                continue
            games += 1
            steps = d['steps']
            for t in range(1, len(steps) - 1):     # skip step 1 (deck); need t+1 for the answer
                if pi >= len(steps[t]):
                    continue
                e = steps[t][pi]
                if e.get('status') != 'ACTIVE':
                    continue
                obs = e.get('observation') or {}
                sel = obs.get('select')
                if not isinstance(sel, dict):
                    continue
                opts = sel.get('option') or []
                if len(opts) <= 1:
                    continue                  # forced — no real choice
                # the human's answer to obs[t] is recorded at the next step, same pi (ACTIVE)
                nxt = steps[t + 1][pi] if pi < len(steps[t + 1]) else None
                if not nxt or nxt.get('status') != 'ACTIVE' or nxt.get('action') is None:
                    continue                  # turn-ending decision (next step is opponent) — skip
                act = nxt.get('action')
                ctx = sel.get('context')
                try:
                    ours = set(agent(obs))
                except Exception:
                    continue
                human = set(act)
                decisions += 1
                agree = ours == human
                per_ctx[ctx][1] += 1
                if agree:
                    per_ctx[ctx][0] += 1
                elif len(samples[ctx]) < 4:
                    samples[ctx].append({'options': len(opts), 'ours': sorted(ours),
                                         'human': sorted(human), 'minmax': [sel.get('minCount'), sel.get('maxCount')]})
        except Exception:
            continue

    print(f'\n=== DIVERGENCE vs {archetype} pilots (Elo>={elo_cut:.0f}) — '
          f'{games} games, {decisions} real decisions ===')
    print(f'{"context":26s} {"agree%":>7} {"n":>5}  (low agree% = where we pilot differently)')
    rows = sorted(per_ctx.items(), key=lambda kv: (kv[1][0] / kv[1][1]) if kv[1][1] else 1)
    for ctx, (ag, tot) in rows:
        name = CTX_NAME.get(ctx, str(ctx))
        print(f'{name:26s} {ag/tot*100:6.1f}% {tot:5d}')
    print('\n--- sample divergences (lowest-agreement contexts) ---')
    for ctx, (ag, tot) in rows[:5]:
        if ag == tot:
            continue
        name = CTX_NAME.get(ctx, str(ctx))
        print(f'[{name}] agree {ag}/{tot}')
        for s in samples[ctx]:
            print(f'    opts={s["options"]} min/max={s["minmax"]}  ours={s["ours"]}  human={s["human"]}')
    out = {'archetype': archetype, 'elo_cut': elo_cut, 'games': games, 'decisions': decisions,
           'by_context': {CTX_NAME.get(c, str(c)): {'agree': a, 'total': t} for c, (a, t) in per_ctx.items()}}
    path = '/tmp/divergence_%s.json' % archetype.replace("'", '').replace(' ', '')
    json.dump(out, open(path, 'w'), ensure_ascii=False, indent=2)
    print(f'\nsaved {path}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('zip')
    ap.add_argument('agent_dir')
    ap.add_argument('--elo', type=float, default=1150)
    ap.add_argument('--archetype', default='Alakazam')
    ap.add_argument('--max-games', type=int, default=80)
    ap.add_argument('--lb', default='/tmp/lb')
    a = ap.parse_args()
    analyze(a.zip, a.agent_dir, a.archetype, a.elo, a.max_games, a.lb)


if __name__ == '__main__':
    main()
