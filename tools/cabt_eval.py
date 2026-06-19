"""Evaluate our agent in the OFFICIAL cabt environment (kaggle_environments 1.30.1,
same version as the ladder). More accurate than the ctypes harness.

Prepares opponent dirs from the sample-agent notebooks (+ consensus decks), patches
their cwd-based deck loading so they run under cabt, then plays N matches.

Usage: venv/bin/python tools/cabt_eval.py <our_agent_dir> <opp> [games]
  our_agent_dir: agents/bellibolt | agents/typhlosion | agents/alakazam
  opp: crustle | lucario | abomasnow | dragapult | mirror
"""
import sys, os, json, warnings
warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT + '/docs/official/models/cg-lib')
from collections import Counter
from cg.api import all_card_data
ct = {c.cardId: c for c in all_card_data()}

# cwd-independent deck loader prepended to every (opponent) agent so it works in cabt.
DECK_FIX = (
    "import os as _os, sys as _sys\n"
    "if not _os.path.exists('deck.csv'):\n"
    "    for _p in list(_sys.path):\n"
    "        if _p and _os.path.exists(_os.path.join(_p,'deck.csv')):\n"
    "            _os.chdir(_p); break\n"
)

CONSENSUS = {
    # 8 basics (4 Dwebble + 4 Fezandipiti ex): the real meta Crustle runs only ~4
    # basics and bricks too often to be a fair test opponent.
    'crustle': [344]*4+[345]*4+[140]*4+[1086]*4+[1147]*4+[1212]*4+[1224]*4+[1264]*4+[1159]*1+[18]*4+[11]*4+[14]*4+[6]*15,
    'lucario': [673,673,674,674,675,675,676,676,676,677,677,677,678,678,678,678,1102,1102,1102,1102,
                1123,1123,1141,1141,1141,1141,1142,1142,1142,1142,1152,1152,1152,1152,1159,1182,1182,
                1192,1192,1192,1192,1227,1227,1227,1227,1252,1252]+[6]*13,
}
NB = {
    'crustle': ('beating-the-day-1-1-crustle-bot.ipynb', 4),
    'lucario': ('a-sample-rule-based-agent-mega-lucario-ex-deck.ipynb', 2),
    'abomasnow': ('a-sample-rule-based-agent-mega-abomasnow-ex-deck.ipynb', 2),
    'dragapult': ('a-sample-rule-based-agent-dragapult-ex-deck.ipynb', 3),
}


def dk(d):
    cc = Counter(d); poke = [(k, v) for k, v in cc.items() if k in ct and k < 1000 and ct[k].hp]
    if not poke: return '?'
    for pid, _ in sorted(poke, key=lambda x: -x[1]):
        if getattr(ct[pid], 'megaEx', 0) or getattr(ct[pid], 'ex', 0): return ct[pid].name
    for pid, _ in sorted(poke, key=lambda x: -x[1]):
        if getattr(ct[pid], 'stage1', 0) or getattr(ct[pid], 'stage2', 0): return ct[pid].name
    return ct[max(poke, key=lambda x: x[1])[0]].name


def consensus_deck(arch_name):
    """Most common winning decklist for an archetype, from the 6-17 episodes.
    DETERMINISTIC: sorts the episode list and the tie-break so the SAME deck is produced
    every run (a non-deterministic opponent makes cross-run A/B meaningless)."""
    import zipfile
    z = zipfile.ZipFile('/tmp/ep17/pokemon-tcg-ai-battle-episodes-2026-06-17.zip')
    builds = Counter()
    for n in sorted(x for x in z.namelist() if x.endswith('.json')):
        try:
            data = json.loads(z.read(n)); rw = data['rewards']
            if rw[0] == rw[1]: continue
            w = 0 if rw[0] > rw[1] else 1
            d = data['steps'][1][w]['action']
            if dk(d) == arch_name and len(d) == 60:
                builds[tuple(sorted(d))] += 1
                if sum(builds.values()) > 120: break   # larger, representative sample
        except Exception:
            continue
    if not builds:
        return None
    best = max(builds.items(), key=lambda kv: (kv[1], kv[0]))   # count, then sorted tuple
    return list(best[0])


def prep_opponent(opp):
    d = f'/tmp/cabt_{opp}'; os.makedirs(d, exist_ok=True)
    nbfile, ci = NB[opp]
    nb = json.load(open(ROOT + '/docs/official/models/' + nbfile))
    src = ''.join(nb['cells'][ci]['source'])
    if src.startswith('%%'):
        src = src.split('\n', 1)[1]
    open(d + '/main.py', 'w').write(DECK_FIX + src)
    deck = CONSENSUS.get(opp)
    if deck is None:
        # Cache the generated consensus deck to a STABLE file so the opponent is pinned
        # across runs (otherwise A/B comparisons are run against different opponents).
        cache = ROOT + f'/tools/.opp_cache_{opp}.csv'
        if os.path.exists(cache):
            deck = [int(x) for x in open(cache) if x.strip()]
        else:
            archname = {'abomasnow': 'Mega Abomasnow ex', 'dragapult': 'Dragapult ex'}[opp]
            deck = consensus_deck(archname)
            open(cache, 'w').write('\n'.join(map(str, deck)))
    open(d + '/deck.csv', 'w').write('\n'.join(map(str, deck)))
    if not os.path.exists(d + '/cg'):
        import shutil; shutil.copytree(ROOT + '/docs/official/models/cg-lib/cg', d + '/cg')
    return d + '/main.py'


def main():
    our_dir = sys.argv[1] if len(sys.argv) > 1 else 'agents/bellibolt'
    opp = sys.argv[2] if len(sys.argv) > 2 else 'crustle'
    games = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    our = ROOT + '/' + our_dir + '/main.py'
    if not os.path.exists(ROOT + '/' + our_dir + '/cg'):
        import shutil; shutil.copytree(ROOT + '/docs/official/models/cg-lib/cg', ROOT + '/' + our_dir + '/cg')
    # Load OUR agent as a pre-built callable so its deck is read ONCE at cwd=ROOT. cabt does
    # not set __file__, so a file-loaded agent falls back to a cwd-relative 'deck.csv'; the
    # opponent's DECK_FIX chdir's cwd away and our agent would otherwise pilot the OPPONENT's
    # deck in later games / odd seats (this silently corrupted every prior cabt result).
    def _our_cb():
        from kaggle_environments.agent import get_last_callable
        cur = os.getcwd(); os.chdir(ROOT)
        try:
            cb = get_last_callable(open(our).read(), path=our)
        finally:
            os.chdir(cur)
        md = getattr(cb, '__globals__', {}).get('my_deck')
        assert md and len(md) == 60, f'our deck failed to load ({md and len(md)})'
        return cb
    our_cb = _our_cb()
    oppfile = _our_cb() if opp == 'mirror' else prep_opponent(opp)
    from kaggle_environments import make
    w = [0, 0, 0]
    for g in range(games):
        env = make('cabt')
        # alternate seat
        order = [our_cb, oppfile] if g % 2 == 0 else [oppfile, our_cb]
        res = env.run(order)
        r = [s.get('reward') for s in res[-1]]
        us = 0 if g % 2 == 0 else 1
        ro, ru = r[1 - us], r[us]
        if ru is None: w[1] += 1          # we errored -> loss
        elif ro is None: w[0] += 1        # opp errored -> win
        elif ru > ro: w[0] += 1
        elif ro > ru: w[1] += 1
        else: w[2] += 1
        print(f'  game {g+1}/{games}: us={ru} opp={ro}', flush=True)
    t = w[0] + w[1]
    print(f'[cabt] {our_dir} vs {opp}: {w[0]}W/{w[1]}L/{w[2]}D = {w[0]/t*100:.0f}%' if t else 'no decisive games')


if __name__ == '__main__':
    main()
