#!/usr/bin/env python3
"""Debug Mewtwo: play 1 game vs Dragapult, log every decision to stdout."""
import sys, os, warnings, json
warnings.filterwarnings('ignore')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT + '/docs/official/models/cg-lib')
sys.path.insert(0, ROOT + '/agents/_base')

from copy import deepcopy
from kaggle_environments import make
from cg.api import SelectContext, OptionType, all_card_data

CT = {c.cardId: c for c in all_card_data()}
CTX_NAME = {int(c.value): c.name for c in SelectContext}
def cname(cid):
    c = CT.get(cid)
    return c.name if c else f'#{cid}'

# ── load agents ──────────────────────────────────────────────────────────────
def load_mod(agent_dir):
    d = ROOT + '/' + agent_dir
    if not os.path.exists(d + '/cg'):
        import shutil
        shutil.copytree(ROOT + '/docs/official/models/cg-lib/cg', d + '/cg')
    sys.path.insert(0, d)
    import importlib
    spec = importlib.util.spec_from_file_location('ag', d + '/main.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.agent

mw = load_mod('agents/mewtwo')
dp = load_mod('agents/dragapult')

# ── debug wrapper ────────────────────────────────────────────────────────────
dec_log = []

def debug_mw(obs_dict):
    if isinstance(obs_dict, dict) and obs_dict.get('select') is not None:
        s = obs_dict['select']
        ctx = int(s.get('context', -1))
        turn = obs_dict.get('current', {}).get('turn', '?')
        pi = obs_dict['current']['yourIndex']
        pl = obs_dict['current']['players'][pi]
        hand = [cname(c['id']) for c in pl.get('hand', [])]
        active_p = [cname(p['id']) if p else '-' for p in pl.get('active', [])]
        bench_p = [cname(p['id']) if p else '-' for p in pl.get('bench', [])]
        rocket = sum(1 for p in pl.get('active', []) + pl.get('bench', [])
                     if p and p.get('id') in {400, 401, 414, 431})
        
        opts = s.get('option', [])
        choice = mw(obs_dict)
        
        # Decode choice with card names
        chosen_strs = []
        for ci in (choice or []):
            if 0 <= ci < len(opts):
                o = opts[ci]
                ot = o.get('type', -1)
                info = f'[{ci}]'
                if ot == 7:  # PLAY
                    idx = o.get('index', -1)
                    if 0 <= idx < len(pl.get('hand', [])):
                        info += ' PLAY ' + cname(pl['hand'][idx]['id'])
                elif ot == 8:  # ENERGY/ATTACH
                    ei = o.get('index', -1)
                    if 0 <= ei < len(pl.get('hand', [])):
                        ename = cname(pl['hand'][ei]['id'])
                        info += f' ATTACH {ename}'
                elif ot == 9:  # EVOLVE
                    ei = o.get('index', -1)
                    if 0 <= ei < len(pl.get('hand', [])):
                        info += ' EVOLVE ' + cname(pl['hand'][ei]['id'])
                elif ot == 13:  # ATTACK
                    aid = o.get('attackId', 0)
                    info += f' ATTACK aid={aid}'
                elif ot == 10:  # ABILITY
                    info += ' ABILITY'
                elif ot == 12:  # RETREAT
                    info += ' RETREAT'
                chosen_strs.append(info)
        
        dec_log.append({
            'n': len(dec_log), 'turn': turn, 'ctx': ctx,
            'ctx_name': CTX_NAME.get(ctx, str(ctx)),
            'rocket': rocket, 'hand': hand,
            'active': active_p, 'bench': bench_p,
            'choice': choice, 'opt_count': len(opts),
        })
        
        # Print key decisions only
        if ctx in (0, 21, 22, 41):  # MAIN, ATTACH_FROM, ATTACH_TO, IS_FIRST
            print(f'\n[T{turn} {CTX_NAME.get(ctx,str(ctx))}] Rocket={rocket} Active={active_p} Bench={bench_p}')
            print(f'  Hand: {hand}')
            print(f'  => {choice} ({chosen_strs})')
    return mw(obs_dict)

print('=== Mewtwo vs Dragapult (debug) ===')
env = make('cabt')
env.run([debug_mw, dp])

print(f'\n=== GAME OVER ===')
print(f'Total decisions: {len(dec_log)}')
# Summary
for d in dec_log[:30]:
    print(f'  #{d["n"]:3d} T{d["turn"]:2d} {d["ctx_name"]:20s} Rocket={d["rocket"]} → {d["choice"]}')
