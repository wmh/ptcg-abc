"""Decode divergences — like replay_divergence, but DECODES each option into human-readable
form (card name / attack name / option type) so we can derive actual piloting RULES, not just
bare index mismatches. For every decision where our agent disagrees with a top pilot, prints
what the HUMAN chose vs what WE chose, then aggregates by (context, option-type) so patterns pop.

Usage:
  venv/bin/python tools/divergence_decode.py <episode_zip> <agent_dir> --archetype "Hop's Trevenant"
                  [--elo 1150] [--context MAIN] [--max-games 120] [--show 40]
"""
import sys, os, json, zipfile, argparse, importlib.util, warnings
from collections import defaultdict, Counter
warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT + '/docs/official/models/cg-lib')
_spec = importlib.util.spec_from_file_location('ma', ROOT + '/tools/meta_analyze.py')
ma = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ma)
from cg.api import (SelectContext, OptionType, all_card_data, all_attack,
                    to_observation_class, AreaType)

CTX_NAME = {int(c.value): c.name for c in SelectContext}
OPT_NAME = {int(o.value): o.name for o in OptionType}
CT = {c.cardId: c for c in all_card_data()}
AT = {a.attackId: a for a in all_attack()}


def cname(cid):
    c = CT.get(cid)
    return c.name if c else f'#{cid}'


def load_agent(agent_dir):
    cur = os.getcwd()
    os.chdir(ROOT + '/' + agent_dir)
    try:
        spec = importlib.util.spec_from_file_location('our_agent', 'main.py')
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        os.chdir(cur)
    return m


def decode_opt(o, obs, my_index):
    """Human-readable label for one option dict-or-obj."""
    t = getattr(o, 'type', None)
    tn = OPT_NAME.get(int(t), str(t)) if t is not None else '?'
    # card-bearing options: index into hand/board
    def card_at(area, idx, pi):
        try:
            player = obs.current.players[pi]
            if area == AreaType.HAND: seq = player.hand
            elif area == AreaType.ACTIVE: seq = player.active
            elif area == AreaType.BENCH: seq = player.bench
            elif area == AreaType.DISCARD: seq = player.discard
            elif area == AreaType.DECK: seq = getattr(obs.select, 'deck', None)
            else: seq = None
            if seq is not None and idx is not None and 0 <= idx < len(seq) and seq[idx] is not None:
                return cname(seq[idx].id)
        except Exception:
            return None
        return None
    if t == OptionType.ATTACK:
        a = AT.get(getattr(o, 'attackId', None))
        return f'ATTACK:{a.name if a else getattr(o,"attackId",None)}'
    if t in (OptionType.PLAY, OptionType.EVOLVE):
        nm = card_at(AreaType.HAND, getattr(o, 'index', None), my_index)
        return f'{tn}:{nm}'
    if t in (OptionType.ATTACH, OptionType.ENERGY):
        src = card_at(AreaType.HAND, getattr(o, 'index', None), my_index)
        tgt = card_at(getattr(o, 'inPlayArea', None), getattr(o, 'inPlayIndex', None), my_index)
        return f'ATTACH:{src}->{tgt}'
    if t == OptionType.CARD:
        pi = getattr(o, 'playerIndex', my_index)
        nm = card_at(getattr(o, 'area', None), getattr(o, 'index', None), pi)
        if nm is None:
            nm = card_at(getattr(o, 'inPlayArea', None), getattr(o, 'inPlayIndex', None), pi)
        who = 'me' if pi == my_index else 'opp'
        return f'CARD[{who}]:{nm}'
    if t == OptionType.ABILITY:
        return 'ABILITY'
    if t == OptionType.RETREAT:
        return 'RETREAT'
    if t in (OptionType.YES, OptionType.NO, OptionType.END, OptionType.NUMBER):
        return tn
    return tn


def analyze(zip_path, agent_dir, archetype, elo_cut, max_games, only_ctx, show, player=None):
    elo = ma.load_elo('/tmp/lb')
    m = load_agent(agent_dir)
    agent = m.agent
    z = zipfile.ZipFile(zip_path)
    names = [x for x in z.namelist() if x.endswith('.json')]
    only = None
    if only_ctx:
        only = {int(c.value) for c in SelectContext if c.name == only_ctx}

    # human-choice-label counter for divergent decisions, plus paired examples
    human_pick = defaultdict(Counter)   # ctx -> Counter(human option label)
    our_pick = defaultdict(Counter)     # ctx -> Counter(our option label)
    pairs = defaultdict(list)           # ctx -> [(human_labels, our_labels)]
    agree = defaultdict(lambda: [0, 0])
    games = 0
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
            if player is not None:
                if pl[win] != player:
                    continue
            elif elo.get(pl[win], 0) < elo_cut:
                continue
            decks = [d['steps'][1][0]['action'], d['steps'][1][1]['action']]
            if ma.dk(decks[win]) != archetype:
                continue
            games += 1
            steps = d['steps']
            pi = win
            for t in range(1, len(steps) - 1):
                if pi >= len(steps[t]):
                    continue
                e = steps[t][pi]
                if e.get('status') != 'ACTIVE':
                    continue
                obs_d = e.get('observation') or {}
                sel = obs_d.get('select')
                if not isinstance(sel, dict):
                    continue
                opts = sel.get('option') or []
                if len(opts) <= 1:
                    continue
                ctx = sel.get('context')
                if only and ctx not in only:
                    continue
                nxt = steps[t + 1][pi] if pi < len(steps[t + 1]) else None
                if not nxt or nxt.get('status') != 'ACTIVE' or nxt.get('action') is None:
                    continue
                human = sorted(set(nxt['action']))
                try:
                    ours = sorted(set(agent(obs_d)))
                    obs = to_observation_class(obs_d)
                except Exception:
                    continue
                agree[ctx][1] += 1
                if ours == human:
                    agree[ctx][0] += 1
                    continue
                # decode
                opt_objs = obs.select.option
                hlab = [decode_opt(opt_objs[i], obs, pi) for i in human if i < len(opt_objs)]
                olab = [decode_opt(opt_objs[i], obs, pi) for i in ours if i < len(opt_objs)]
                for l in hlab:
                    human_pick[ctx][l] += 1
                for l in olab:
                    our_pick[ctx][l] += 1
                if len(pairs[ctx]) < show:
                    pairs[ctx].append((hlab, olab))
        except Exception:
            continue

    ctxs = sorted(agree, key=lambda c: agree[c][0] / agree[c][1] if agree[c][1] else 1)
    for ctx in ctxs:
        ag, tot = agree[ctx]
        if ag == tot:
            continue
        name = CTX_NAME.get(ctx, str(ctx))
        print(f'\n===== {name}  agree {ag}/{tot} ({ag/tot*100:.0f}%)  — on DIVERGENT decisions: =====')
        print('  HUMAN picked (label: count):')
        for lab, c in human_pick[ctx].most_common(12):
            print(f'    {c:4d}  {lab}')
        print('  WE picked instead:')
        for lab, c in our_pick[ctx].most_common(12):
            print(f'    {c:4d}  {lab}')
        print('  examples (human || ours):')
        for hlab, olab in pairs[ctx][:show]:
            print(f'    {hlab}  ||  {olab}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('zip'); ap.add_argument('agent_dir')
    ap.add_argument('--archetype', default='Alakazam')
    ap.add_argument('--elo', type=float, default=1150)
    ap.add_argument('--context', default=None, help='restrict to one SelectContext name')
    ap.add_argument('--max-games', type=int, default=120)
    ap.add_argument('--show', type=int, default=25)
    ap.add_argument('--player', default=None, help='restrict to one exact pilot TeamName')
    a = ap.parse_args()
    analyze(a.zip, a.agent_dir, a.archetype, a.elo, a.max_games, a.context, a.show, a.player)


if __name__ == '__main__':
    main()
