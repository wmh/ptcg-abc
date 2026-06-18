"""Behavior cloning for the Iono's Bellibolt ex agent.

Learns a conditional-logit (softmax over legal options) scoring model from the
MAIN-phase decisions of WINNING Bellibolt players in the ladder replay data, then
exports pure-Python weights to submit/bc_weights.py for the agent to use.

Usage: python3 train_bc.py [max_games]
"""
import json, sys, os, zipfile, types, random
from collections import Counter

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT + '/docs/official/models/cg-lib')
from cg.api import all_card_data, to_observation_class, OptionType

ct = {c.cardId: c for c in all_card_data()}

# Load the agent module (shares the feature extractor + constants).
mod = types.ModuleType('belli_main')
mod.__file__ = ROOT + '/submit/main.py'
os.chdir(ROOT + '/submit')
exec(compile(open(ROOT + '/submit/main.py').read(), ROOT + '/submit/main.py', 'exec'), mod.__dict__)
os.chdir(ROOT)
BellipoltPolicy = mod.BellipoltPolicy
BC_DIM = mod.BC_DIM

ZIP = '/tmp/ep17/pokemon-tcg-ai-battle-episodes-2026-06-17.zip'
ELITE = {'onechan1', 'Kyo_s_s', 'Wasabi', 'DENPA92'}
ELITE_ONLY = os.environ.get('ELITE_ONLY', '0') == '1'


def deck_key(d):
    cc = Counter(d)
    poke = [(k, v) for k, v in cc.items() if k in ct and k < 1000 and ct[k].hp and ct[k].hp > 0]
    if not poke:
        return '?'
    for pid, _ in sorted(poke, key=lambda x: -x[1]):
        if getattr(ct[pid], 'megaEx', False):
            return ct[pid].name
    for pid, _ in sorted(poke, key=lambda x: -x[1]):
        if getattr(ct[pid], 'ex', False):
            return ct[pid].name
    return ct[max(poke, key=lambda x: x[1])[0]].name


def collect(max_games):
    z = zipfile.ZipFile(ZIP)
    names = [n for n in z.namelist() if n.endswith('.json')]
    random.seed(0)
    random.shuffle(names)
    decisions = []  # list of (feature_matrix [n,dim], chosen_idx)
    games = 0
    for name in names:
        if games >= max_games:
            break
        try:
            data = json.loads(z.read(name))
            rewards = data['rewards']
            if len(rewards) < 2:
                continue
            winner = 0 if rewards[0] > rewards[1] else (1 if rewards[1] > rewards[0] else -1)
            if winner < 0:
                continue
            agents = [a['Name'] for a in data['info']['Agents']]
            for pi in (winner,):  # learn only from the WINNING side
                if ELITE_ONLY and agents[pi] not in ELITE:
                    continue
                if deck_key(data['steps'][1][pi]['action']) != "Iono’s Bellibolt ex":
                    continue
                games += 1
                for step in data['steps']:
                    if len(step) <= pi:
                        continue
                    od = step[pi].get('observation', {})
                    act = step[pi].get('action', [])
                    sel = od.get('select')
                    if sel is None or sel.get('context') != 0:
                        continue
                    opts = sel.get('option', [])
                    if len(opts) < 2:
                        continue
                    # chosen index: explicit single index, or the END option for empty action
                    if act and len(act) == 1:
                        chosen = act[0]
                    elif not act:
                        chosen = next((i for i, o in enumerate(opts)
                                       if o.get('type') == OptionType.END), None)
                        if chosen is None:
                            continue
                    else:
                        continue  # multi-select, skip
                    if not (0 <= chosen < len(opts)):
                        continue
                    try:
                        obs = to_observation_class(od)
                        pol = BellipoltPolicy(obs)
                        F = [pol._bc_features(o) for o in obs.select.option]
                    except Exception:
                        continue
                    if len(F) != len(opts):
                        continue
                    decisions.append((np.asarray(F, dtype=np.float64), chosen))
        except Exception:
            pass
    return decisions, games


def train(decisions, dim, epochs=300, lr=0.5, l2=1e-4):
    w = np.zeros(dim)
    # Adam
    m = np.zeros(dim); v = np.zeros(dim); b1, b2, eps = 0.9, 0.999, 1e-8
    for ep in range(epochs):
        grad = np.zeros(dim); loss = 0.0
        for F, ci in decisions:
            s = F @ w
            s -= s.max()
            p = np.exp(s); p /= p.sum()
            loss += -np.log(p[ci] + 1e-12)
            p[ci] -= 1.0
            grad += p @ F  # sum_i (p_i - 1{i=ci}) f_i
        grad = grad / len(decisions) + l2 * w
        t = ep + 1
        m = b1 * m + (1 - b1) * grad
        v = b2 * v + (1 - b2) * grad * grad
        mh = m / (1 - b1 ** t); vh = v / (1 - b2 ** t)
        w -= lr * mh / (np.sqrt(vh) + eps)
        if ep % 50 == 0 or ep == epochs - 1:
            # top-1 accuracy
            correct = sum(1 for F, ci in decisions if int((F @ w).argmax()) == ci)
            print(f'  epoch {ep:3d}  loss={loss/len(decisions):.4f}  top1_acc={correct/len(decisions):.3f}')
    return w


def main():
    max_games = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    print(f'Collecting from up to {max_games} winning Bellibolt games...')
    decisions, games = collect(max_games)
    print(f'Games used: {games}, MAIN decisions: {len(decisions)}')
    if len(decisions) < 200:
        print('Not enough data.'); return
    # train/val split
    random.seed(1); random.shuffle(decisions)
    nval = len(decisions) // 5
    val, tr = decisions[:nval], decisions[nval:]
    w = train(tr, BC_DIM)
    vacc = sum(1 for F, ci in val if int((F @ w).argmax()) == ci) / len(val)
    bacc = sum(1 for F, ci in val if 0 == ci) / len(val)  # baseline: always option 0
    print(f'Validation top1_acc={vacc:.3f}  (baseline first-option={bacc:.3f})')
    out = ROOT + '/submit/bc_weights.py'
    with open(out, 'w') as f:
        f.write('# Auto-generated by train_bc.py — conditional-logit BC weights.\n')
        f.write('BC_WEIGHTS = [\n')
        for x in w:
            f.write(f'    {x:.6f},\n')
        f.write(']\n')
    print(f'Wrote {out} ({len(w)} weights)')


if __name__ == '__main__':
    main()
