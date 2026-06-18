"""Human-vs-AI web sandbox for the PTCG agent.

You pilot the Ethan's Typhlosion (Quilava) deck; the computer plays a meta deck
(Crustle / Lucario). At every one of YOUR decisions the panel shows what OUR
agent would do and the score it gives each legal option — so you can compare your
intuition with the strategy and spot where the agent is wrong (optimization points).

Run:  venv/bin/python web/server.py   then open http://localhost:8000
"""
import sys, os, json, ctypes, types
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT + '/docs/official/models/cg-lib')
from cg.game import battle_start, battle_finish, _get_battle_data
from cg.api import (to_observation_class, all_card_data, all_attack,
                    OptionType, SelectContext, AreaType)
from cg.sim import lib, Battle

CT = {c.cardId: c for c in all_card_data()}
AT = {a.attackId: a for a in all_attack()}
CTX = {v: k for k, v in vars(SelectContext).items() if isinstance(v, int)}


def cname(cid):
    c = CT.get(cid)
    return (c.name if c else f"#{cid}")


# ── load OUR agent (human side + AI suggestions) ─────────────────────────────
QDECK = [int(l) for l in open(ROOT + '/agents/typhlosion/deck.csv') if l.strip()]
qmod = types.ModuleType('qmod'); qmod.__file__ = ROOT + '/agents/typhlosion/main.py'
os.chdir(ROOT + '/agents/typhlosion')
exec(compile(open(ROOT + '/agents/typhlosion/main.py').read(), qmod.__file__, 'exec'), qmod.__dict__)
os.chdir(ROOT)


def load_opp(kind):
    if kind == 'lucario':
        nb = json.load(open(ROOT + '/docs/official/models/a-sample-rule-based-agent-mega-lucario-ex-deck.ipynb'))
        src = ''.join(nb['cells'][2]['source']).split('\n', 1)[1]
        deck = [673,673,674,674,675,675,676,676,676,677,677,677,678,678,678,678,
                1102,1102,1102,1102,1123,1123,1141,1141,1141,1141,1142,1142,1142,1142,
                1152,1152,1152,1152,1159,1182,1182,1192,1192,1192,1192,1227,1227,1227,1227,
                1252,1252]+[6]*13
    else:  # crustle
        nb = json.load(open(ROOT + '/docs/official/models/beating-the-day-1-1-crustle-bot.ipynb'))
        src = ''.join(nb['cells'][4]['source'])
        src = src.split('\n', 1)[1] if src.startswith('%%') else src
        deck = [344]*4+[345]*4+[1086]*4+[1147]*4+[1212]*4+[1224]*4+[1264]*4+[1159]*1+[18]*4+[11]*4+[14]*4+[6]*19
    d = '/tmp/web_opp_' + kind; os.makedirs(d, exist_ok=True)
    open(d + '/deck.csv', 'w').write('\n'.join(map(str, deck)))
    m = types.ModuleType('opp_' + kind); m.__file__ = d + '/main.py'
    os.chdir(d); exec(compile(src, m.__file__, 'exec'), m.__dict__); os.chdir(ROOT)
    return m, deck


# ── game session (single global game; single-threaded server) ────────────────
GAME = {'obs_dict': None, 'opp_mod': None, 'opp_deck': None, 'human': 0, 'over': True}


def _select(indices):
    arg = (ctypes.c_int * len(indices))(*indices)
    lib.Select(Battle.battle_ptr, arg, len(indices))
    return _get_battle_data()


def _advance_opponent():
    """Auto-play the opponent until it's the human's decision or game over."""
    g = GAME
    for _ in range(500):
        obs = to_observation_class(g['obs_dict'])
        if obs.current.result != -1 or obs.select is None:
            g['over'] = obs.current.result != -1
            return
        if obs.current.yourIndex == g['human']:
            return
        try:
            action = g['opp_mod'].agent(g['obs_dict'])
        except Exception:
            n = len(obs.select.option); action = list(range(min(max(0, obs.select.minCount), n)))
        g['obs_dict'] = _select(action)


def poke_json(p):
    if p is None:
        return None
    return {'id': p.id, 'name': cname(p.id).replace("Ethan's ", "").replace("Iono's ", ""),
            'hp': p.hp, 'maxHp': p.maxHp, 'energy': len(p.energies),
            'tools': [cname(t.id) for t in p.tools]}


def option_ids(obs, opt, my_index):
    """(cardId, attackId) for an option, so the UI can show its card details."""
    try:
        t = opt.type
        if t == OptionType.ATTACK:
            return (obs.current.players[my_index].active[0].id
                    if obs.current.players[my_index].active else None), opt.attackId
        if t in (OptionType.PLAY, OptionType.EVOLVE):
            c = qmod.get_card(obs, AreaType.HAND, opt.index, my_index)
            return (c.id if c else None), None
        if t == OptionType.ABILITY:
            c = qmod.get_card(obs, opt.area, opt.index, my_index)
            return (c.id if c else None), None
        if t in (OptionType.ENERGY, OptionType.ATTACH):
            c = qmod.get_card(obs, opt.inPlayArea, opt.inPlayIndex, my_index)
            return (c.id if c else None), None
        if t == OptionType.CARD:
            c = qmod.get_card(obs, getattr(opt, 'area', None) or AreaType.HAND, opt.index, my_index)
            return (c.id if c else None), None
    except Exception:
        pass
    return None, None


def label_option(obs, opt, my_index):
    t = opt.type
    if t == OptionType.END:
        return '⏹ 結束回合 End Turn'
    if t == OptionType.YES:
        return '✔ YES' + (' (先攻 go first)' if obs.select.context == SelectContext.IS_FIRST else '')
    if t == OptionType.NO:
        return '✘ NO' + (' (後攻 go second)' if obs.select.context == SelectContext.IS_FIRST else '')
    if t == OptionType.NUMBER:
        return f'數字 {opt.number}'
    if t == OptionType.ATTACK:
        a = AT.get(opt.attackId)
        return f'⚔ 攻擊 {a.name} ({a.damage})' if a else f'⚔ Attack #{opt.attackId}'
    if t == OptionType.RETREAT:
        return '↩ 撤退 Retreat'
    if t == OptionType.ABILITY:
        c = qmod.get_card(obs, opt.area, opt.index, my_index)
        return f'✨ 特性 {cname(c.id) if c else ""}'
    if t == OptionType.EVOLVE:
        c = qmod.get_card(obs, AreaType.HAND, opt.index, my_index)
        return f'⬆ 進化 → {cname(c.id) if c else ""}'
    if t in (OptionType.ENERGY, OptionType.ATTACH):
        tgt = qmod.get_card(obs, opt.inPlayArea, opt.inPlayIndex, my_index)
        return f'🔋 貼能量 → {cname(tgt.id).replace(chr(39),"") if tgt else "?"}'
    if t in (OptionType.PLAY, OptionType.CARD, OptionType.TOOL_CARD, OptionType.ENERGY_CARD):
        c = qmod.get_card(obs, getattr(opt, 'area', None) or AreaType.HAND, opt.index, my_index)
        return f'▶ {cname(c.id) if c else "card"}'
    return f'option(type={t})'


def state_json(msg=''):
    g = GAME
    obs = to_observation_class(g['obs_dict']) if g['obs_dict'] else None
    if obs is None:
        return {'started': False, 'msg': msg}
    st = obs.current
    me = st.players[g['human']]; op = st.players[1 - g['human']]
    over = st.result != -1
    out = {
        'started': True, 'over': over, 'msg': msg,
        'result': ('你贏了 🏆' if over and st.result == g['human'] else
                   '電腦贏了 💀' if over and st.result == (1 - g['human']) else
                   '平手' if over else ''),
        'turn': st.turn, 'context': CTX.get(obs.select.context, str(obs.select.context)) if obs.select else None,
        'yourTurn': (obs.select is not None and st.yourIndex == g['human']),
        'me': {'active': poke_json(me.active[0] if me.active else None),
               'bench': [poke_json(b) for b in me.bench if b is not None],
               'prizes': len(me.prize), 'hand': [cname(c.id) for c in (me.hand or [])],
               'deck': me.deckCount},
        'opp': {'active': poke_json(op.active[0] if op.active else None),
                'bench': [poke_json(b) for b in op.bench if b is not None],
                'prizes': len(op.prize), 'handCount': op.handCount, 'deck': op.deckCount},
        'stadium': cname(st.stadium[0].id) if st.stadium else None,
        'options': [], 'ai_pick': [],
    }
    if not over and obs.select is not None and st.yourIndex == g['human']:
        # AI suggestion + per-option scores (our strategy)
        try:
            policy = qmod.QuilavaPolicy(obs)
            ranked, scores = policy.rank()
            ai_pick = qmod.normalize_selection(ranked, scores, obs.select)
        except Exception:
            scores = [0] * len(obs.select.option); ai_pick = []
        out['ai_pick'] = ai_pick
        for i, opt in enumerate(obs.select.option):
            cid, aid = option_ids(obs, opt, g['human'])
            out['options'].append({
                'i': i, 'label': label_option(obs, opt, g['human']),
                'score': round(float(scores[i]), 1) if i < len(scores) else 0,
                'recommended': i in ai_pick, 'cardId': cid, 'attackId': aid,
            })
        out['multi'] = {'min': obs.select.minCount, 'max': obs.select.maxCount}
    return out


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype='application/json'):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ('/', '/index.html'):
            return self._send(200, open(ROOT + '/web/index.html', 'rb').read(), 'text/html; charset=utf-8')
        if u.path == '/card_db.json':
            return self._send(200, open(ROOT + '/web/card_db.json', 'rb').read(), 'application/json; charset=utf-8')
        if u.path == '/new':
            q = parse_qs(u.query)
            opp = q.get('opp', ['crustle'])[0]
            m, deck = load_opp(opp)
            GAME['opp_mod'], GAME['opp_deck'] = m, deck
            GAME['human'] = 0
            GAME['obs_dict'], _ = battle_start(QDECK, deck)
            GAME['over'] = False
            _advance_opponent()
            return self._send(200, json.dumps(state_json(f'新對局 vs {opp}')))
        if u.path == '/state':
            return self._send(200, json.dumps(state_json()))
        return self._send(404, '{}')

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == '/select':
            ln = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(ln) or '{}')
            idx = body.get('indices', [])
            try:
                GAME['obs_dict'] = _select(idx)
                _advance_opponent()
                return self._send(200, json.dumps(state_json()))
            except Exception as e:
                return self._send(200, json.dumps(state_json(f'錯誤: {e}')))
        return self._send(404, '{}')


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f'PTCG sandbox: http://localhost:{port}  (Ctrl-C to stop)')
    HTTPServer(('0.0.0.0', port), H).serve_forever()
