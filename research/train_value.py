"""Train a board value function (win-probability) for the Bellibolt agent.

Learns from Bellibolt-player states in the ladder replays, labeled by the game
outcome. Exports a small MLP to submit/value_weights.py for shallow forward search.

Usage: python3 train_value.py [max_games]
"""
import json, sys, os, zipfile, types, random
from collections import Counter
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT + '/docs/official/models/cg-lib')
from cg.api import all_card_data, to_observation_class, SelectContext

ct = {c.cardId: c for c in all_card_data()}

mod = types.ModuleType('belli_main')
mod.__file__ = ROOT + '/submit/main.py'
os.chdir(ROOT + '/submit')
exec(compile(open(ROOT + '/submit/main.py').read(), ROOT + '/submit/main.py', 'exec'), mod.__dict__)
os.chdir(ROOT)
value_features = mod.value_features
VALUE_DIM = mod.VALUE_DIM
ZIP = '/tmp/ep17/pokemon-tcg-ai-battle-episodes-2026-06-17.zip'


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
    random.seed(0); random.shuffle(names)
    X, Y = [], []
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
            for pi in range(2):
                if deck_key(data['steps'][1][pi]['action']) != "Iono’s Bellibolt ex":
                    continue
                games += 1
                label = 1.0 if winner == pi else 0.0
                seen_turn = set()
                for step in data['steps']:
                    if len(step) <= pi:
                        continue
                    od = step[pi].get('observation', {})
                    sel = od.get('select')
                    cur = od.get('current')
                    if sel is None or cur is None:
                        continue
                    if sel.get('context') != SelectContext.MAIN:
                        continue
                    turn = cur.get('turn', -1)
                    if turn in seen_turn:      # one sample per turn (reduce correlation)
                        continue
                    seen_turn.add(turn)
                    try:
                        obs = to_observation_class(od)
                        X.append(value_features(obs, pi)); Y.append(label)
                    except Exception:
                        pass
        except Exception:
            pass
    return np.asarray(X), np.asarray(Y), games


def train(X, Y, H=16, epochs=400, lr=0.01, l2=1e-4):
    n, d = X.shape
    rng = np.random.default_rng(0)
    W1 = rng.normal(0, 0.3, (H, d)); b1 = np.zeros(H)
    W2 = rng.normal(0, 0.3, H); b2 = 0.0
    mW1 = np.zeros_like(W1); vW1 = np.zeros_like(W1)
    mb1 = np.zeros_like(b1); vb1 = np.zeros_like(b1)
    mW2 = np.zeros_like(W2); vW2 = np.zeros_like(W2)
    mb2 = 0.0; vb2 = 0.0
    b1c, b2c, eps = 0.9, 0.999, 1e-8

    def fwd(Xb):
        Z = Xb @ W1.T + b1            # [n,H]
        Hd = np.maximum(Z, 0)
        o = Hd @ W2 + b2             # [n]
        p = 1 / (1 + np.exp(-np.clip(o, -30, 30)))
        return Z, Hd, p

    idx = np.arange(n)
    for ep in range(epochs):
        rng.shuffle(idx)
        Xs, Ys = X[idx], Y[idx]
        Z, Hd, p = fwd(Xs)
        # BCE grad
        dp = (p - Ys) / n           # [n]
        gW2 = Hd.T @ dp + l2 * W2
        gb2 = dp.sum()
        dH = np.outer(dp, W2) * (Z > 0)   # [n,H]
        gW1 = dH.T @ Xs + l2 * W1
        gb1 = dH.sum(0)
        t = ep + 1
        for (P, g, m, v) in [('W1', gW1, mW1, vW1)]:
            pass
        # Adam updates (manual)
        mW1 = b1c*mW1 + (1-b1c)*gW1; vW1 = b2c*vW1 + (1-b2c)*gW1*gW1
        W1 -= lr * (mW1/(1-b1c**t)) / (np.sqrt(vW1/(1-b2c**t)) + eps)
        mb1 = b1c*mb1 + (1-b1c)*gb1; vb1 = b2c*vb1 + (1-b2c)*gb1*gb1
        b1 -= lr * (mb1/(1-b1c**t)) / (np.sqrt(vb1/(1-b2c**t)) + eps)
        mW2 = b1c*mW2 + (1-b1c)*gW2; vW2 = b2c*vW2 + (1-b2c)*gW2*gW2
        W2 -= lr * (mW2/(1-b1c**t)) / (np.sqrt(vW2/(1-b2c**t)) + eps)
        mb2 = b1c*mb2 + (1-b1c)*gb2; vb2 = b2c*vb2 + (1-b2c)*gb2*gb2
        b2 -= lr * (mb2/(1-b1c**t)) / (np.sqrt(vb2/(1-b2c**t)) + eps)
        if ep % 80 == 0 or ep == epochs-1:
            _, _, pp = fwd(X)
            loss = -np.mean(Y*np.log(pp+1e-9) + (1-Y)*np.log(1-pp+1e-9))
            acc = np.mean((pp > 0.5) == (Y > 0.5))
            print(f'  epoch {ep:3d}  loss={loss:.4f}  acc={acc:.3f}')
    return W1, b1, W2, b2, fwd


def auc(p, y):
    order = np.argsort(p)
    y = y[order]
    pos = y.sum(); neg = len(y) - pos
    if pos == 0 or neg == 0:
        return 0.5
    rank = np.arange(1, len(y)+1)
    return (rank[y == 1].sum() - pos*(pos+1)/2) / (pos*neg)


def main():
    max_games = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    print(f'Collecting value data from up to {max_games} Bellibolt games...')
    X, Y, games = collect(max_games)
    print(f'Games: {games}, samples: {len(X)}, win-rate of samples: {Y.mean():.3f}')
    if len(X) < 500:
        print('Not enough data'); return
    # split
    rng = np.random.default_rng(1); perm = rng.permutation(len(X))
    X, Y = X[perm], Y[perm]
    nval = len(X)//5
    Xv, Yv, Xt, Yt = X[:nval], Y[:nval], X[nval:], Y[nval:]
    W1, b1, W2, b2, fwd = train(Xt, Yt)
    _, _, pv = fwd(Xv)
    print(f'Validation: acc={np.mean((pv>0.5)==(Yv>0.5)):.3f}  AUC={auc(pv,Yv):.3f}')
    out = ROOT + '/submit/value_weights.py'
    with open(out, 'w') as f:
        f.write('# Auto-generated by train_value.py — board value MLP (win prob).\n')
        f.write('VALUE_NET = (\n')
        f.write('    ' + repr([[round(float(x),5) for x in row] for row in W1]) + ',\n')
        f.write('    ' + repr([round(float(x),5) for x in b1]) + ',\n')
        f.write('    ' + repr([round(float(x),5) for x in W2]) + ',\n')
        f.write('    ' + repr(round(float(b2),5)) + ',\n')
        f.write(')\n')
    print(f'Wrote {out}')


if __name__ == '__main__':
    main()
