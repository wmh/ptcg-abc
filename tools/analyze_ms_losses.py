#!/usr/bin/env python3
"""Analyze Megastarmie losses vs specific opponents."""
import sys, os, warnings
warnings.filterwarnings('ignore')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT + '/docs/official/models/cg-lib')
sys.path.insert(0, ROOT + '/agents/_base')

import importlib
from kaggle_environments import make
from cg.api import SelectContext, all_card_data

CT = {c.cardId: c for c in all_card_data()}
def cname(cid):
    c = CT.get(cid)
    return c.name if c else f'#{cid}'

# ── load our agent ──────────────────────────────────────────────────────────
def load_our(agent_dir):
    d = ROOT + '/' + agent_dir
    if not os.path.exists(d + '/cg'):
        import shutil
        shutil.copytree(ROOT + '/docs/official/models/cg-lib/cg', d + '/cg')
    sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location('ag', d + '/main.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.agent

# ── load opponent via GenericPolicy ─────────────────────────────────────────
def load_generic(deck_path):
    deck = [int(x) for x in open(ROOT + '/' + deck_path) if x.strip()]
    from generic_policy import make_generic_agent
    return make_generic_agent(deck)

# ── main ────────────────────────────────────────────────────────────────────
def analyze(agent_name, opp_name, opp_path, games=3):
    our = load_our(agent_name)
    opp = load_generic(opp_path)
    
    wins = losses = 0
    all_logs = []
    
    for g in range(games):
        env = make('cabt')
        order = [our, opp] if g % 2 == 0 else [opp, our]
        
        decisions = []
        def wrap(obs_dict):
            if isinstance(obs_dict, dict) and obs_dict.get('select') is not None:
                s = obs_dict['select']
                ctx = s.get('context', -1)
                turn = obs_dict.get('current', {}).get('turn', '?')
                pi = obs_dict['current']['yourIndex']
                pl = obs_dict['current']['players'][pi]
                op = obs_dict['current']['players'][1-pi]
                
                hand = [cname(c['id']) for c in pl.get('hand', [])]
                active = [cname(p['id']) if p else '-' for p in pl.get('active', [])]
                bench = [cname(p['id']) if p else '-' for p in pl.get('bench', [])]
                opp_act = [cname(p['id']) if p else '-' for p in op.get('active', [])]
                opp_bench = [cname(p['id']) if p else '-' for p in op.get('bench', [])]
                
                # Get energies on our active
                act_energies = []
                for p in pl.get('active', []):
                    if p:
                        act_energies = [e.get('energyType', '?') for e in p.get('energies', [])]
                
                if ctx == 0:  # MAIN
                    opts = s.get('option', [])
                    cho = our(obs_dict)
                    chosen = []
                    for ci in (cho or []):
                        if 0 <= ci < len(opts):
                            o = opts[ci]
                            t = o.get('type', -1)
                            info = f'[{ci}]'
                            if t == 7:
                                idx = o.get('index', -1)
                                if 0 <= idx < len(pl.get('hand', [])):
                                    info += ' PLAY ' + cname(pl['hand'][idx]['id'])
                            elif t == 8:
                                ei = o.get('index', -1)
                                if 0 <= ei < len(pl.get('hand', [])):
                                    info += ' ATTACH ' + cname(pl['hand'][ei]['id'])
                            elif t == 9:
                                ei = o.get('index', -1)
                                if 0 <= ei < len(pl.get('hand', [])):
                                    info += ' EVOLVE ' + cname(pl['hand'][ei]['id'])
                            elif t == 13:
                                aid = o.get('attackId', 0)
                                info += ' ATTACK aid=' + str(aid)
                            elif t == 10:
                                info += ' ABILITY'
                            chosen.append(info)
                    
                    decisions.append({
                        'turn': turn, 'hand': list(hand),
                        'active': list(active), 'bench': list(bench),
                        'opp_active': list(opp_act), 'opp_bench': list(opp_bench),
                        'choice': chosen, 'act_energies': act_energies,
                    })
                return our(obs_dict)
            return our(obs_dict)
        
        # Need to pass wrap correctly - but wrap uses our which is mutable...
        # Let's do it differently - attach wrap to a closure
        pass
    return

# Actually let me do this more simply - run games and log via a wrapper class
class GameCapture:
    def __init__(self, our_agent):
        self.our = our_agent
        self.decisions = []
        self.log_file = None
    
    def set_log(self, path):
        self.log_file = open(path, 'w')
    
    def __call__(self, obs_dict):
        if isinstance(obs_dict, dict) and obs_dict.get('select') is not None:
            s = obs_dict['select']
            ctx = s.get('context', -1)
            turn = obs_dict.get('current', {}).get('turn', '?')
            pi = obs_dict['current']['yourIndex']
            pl = obs_dict['current']['players'][pi]
            op = obs_dict['current']['players'][1-pi]
            
            hand = [cname(c['id']) for c in pl.get('hand', [])]
            active = [cname(p['id']) if p else '-' for p in pl.get('active', [])]
            bench = [cname(p['id']) if p else '-' for p in pl.get('bench', [])]
            opp_act = [cname(p['id']) if p else '-' for p in op.get('active', [])]
            opp_bench = [cname(p['id']) if p else '-' for p in op.get('bench', [])]
            
            # Our active's energies
            act_energy_count = 0
            our_active_id = None
            for p in pl.get('active', []):
                if p:
                    our_active_id = p.get('id')
                    act_energy_count = len(p.get('energies', []))
            
            # Check if we have Mega on board
            all_mine = pl.get('active', []) + pl.get('bench', [])
            has_mega = any(p and p.get('id') == 1031 for p in all_mine)
            has_cinderace = any(p and p.get('id') == 666 for p in all_mine)
            has_staryu = any(p and p.get('id') == 1030 for p in all_mine)
            
            if ctx == 0:  # MAIN
                opts = s.get('option', [])
                cho = self.our(obs_dict)
                chosen = []
                for ci in (cho or []):
                    if 0 <= ci < len(opts):
                        o = opts[ci]; t = o.get('type', -1)
                        info = f'[{ci}]'
                        if t == 7:
                            idx = o.get('index', -1)
                            if 0 <= idx < len(pl.get('hand', [])):
                                cid = pl['hand'][idx]['id']
                                info += ' PLAY ' + cname(cid)
                        elif t == 8:
                            ei = o.get('index', -1)
                            if 0 <= ei < len(pl.get('hand', [])):
                                _id = pl["hand"][ei]["id"]
                                info += " ATTACH " + cname(_id)
                            ei = o.get('index', -1)
                            if 0 <= ei < len(pl.get('hand', [])):
                                _id = pl["hand"][ei]["id"]
                                info += " EVOLVE " + cname(_id)
                            aid = o.get('attackId', 0)
                            info += ' ATTACK aid=' + str(aid)
                        elif t == 10:
                            info += ' ABILITY'
                        chosen.append(info)
                
                msg = f'T{turn:2d} Staryu={int(has_staryu)} Cinderace={int(has_cinderace)} Mega={int(has_mega)} Energy={act_energy_count}'
                msg += f'  Act={active} Bench={bench}  Opp={opp_act}/{opp_bench}'
                msg += f'  Hand={hand}'
                msg += f'  → {chosen}'
                
                if self.log_file:
                    self.log_file.write(msg + '\n')
                    self.log_file.flush()
                self.decisions.append(msg)
        return self.our(obs_dict)

print('=== Megastarmie vs Froslass & Lucario ===')
log = open('/tmp/ms_loss_analysis.log', 'w')

for opp_name, opp_deck in [('Froslass', 'agents/froslass/deck.csv'), 
                            ('Lucario', 'agents/lucario_v3/deck.csv')]:
    print(f'\n--- vs {opp_name} ---')
    log.write(f'\n===== vs {opp_name} =====\n')
    
    opp_agent = load_generic(opp_deck)
    ms_agent = load_our('agents/megastarmie')
    
    for g in range(4):
        cap = GameCapture(ms_agent)
        # Don't set a log file - decisions accumulate in cap.decisions
        
        env = make('cabt')
        order = [cap, opp_agent] if g % 2 == 0 else [opp_agent, cap]
        result_state = env.run(order)
        
        r = [s.get('reward') for s in result_state[-1]]
        us = 0 if g % 2 == 0 else 1
        won = (r[us] or 0) > (r[1-us] or 0)
        result = 'WIN' if won else 'LOSS'
        
        # Print MAIN decisions for this game
        log.write(f'\nGame {g+1}: {result} (rewards={r})\n')
        log.write(f'Decisions: {len(cap.decisions)}\n')
        for d in cap.decisions:
            log.write(f'  {d}\n')
        log.flush()
        
        print(f'  Game {g+1}: {result}  ({len(cap.decisions)} MAIN decisions)')

log.close()
print(f'\nFull log: /tmp/ms_loss_analysis.log')
