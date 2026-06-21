"""Battle analyzer — the foundation of the supervisor/sub-agent optimization loop.

Runs N cabt games (our deck vs a meta opponent) and, by replaying the engine event
logs, reports WIN RATE plus DETERMINISTIC behavioural anomalies:

  - attack_no_damage : our ATTACK that placed no HP change on the opponent (per attackId)
                       e.g. Strange Hacking spam, or Powerful Hand blocked by Mist Energy
  - stuck_turn       : our turn with no DRAW / ATTACH / ATTACK at all (got locked / no play)
  - deckout_loss     : we lost with 0 cards left in deck (we milled ourselves out)
  - error_games      : our agent crashed / went INVALID

Win rate is noisy in cabt (±~14pts @ 50 games); the ANOMALY counts are deterministic
and are the reliable signal to optimize against.

Usage:  venv/bin/python tools/battle_analyze.py <agent_dir> [opp|all] [games]
        venv/bin/python tools/battle_analyze.py agents/alakazam all 60
"""
import sys, os, json, importlib.util, warnings
warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT + '/docs/official/models/cg-lib')

# reuse opponent preparation + consensus decks from cabt_eval
_spec = importlib.util.spec_from_file_location('ce', ROOT + '/tools/cabt_eval.py')
ce = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ce)
from cg.api import all_attack, all_card_data

AT = {a.attackId: a for a in all_attack()}
CT = {c.cardId: c for c in all_card_data()}
OPPONENTS = ['crustle', 'lucario', 'abomasnow', 'dragapult', 'iono', 'mirror']

# LogType ids we care about
DRAW, DRAW_REV, TURN_START, TURN_END = 4, 5, 2, 3
ATTACH, ATTACK, HP_CHANGE = 11, 15, 16


def attack_name(aid):
    a = AT.get(aid)
    return a.name if a else f'#{aid}'


def load_our_callable(our_path):
    """Load OUR agent as a callable with its deck loaded ONCE at cwd=ROOT. cabt does NOT
    set __file__, so the agent's deck loader falls back to a cwd-relative 'deck.csv'; the
    opponent's DECK_FIX chdir's cwd away, which otherwise makes our file-loaded agent pick
    up the OPPONENT's deck in later games / odd seats. Pre-building the callable here (and
    passing the callable, not the path, to env.run) immunises us against that drift."""
    from kaggle_environments.agent import get_last_callable
    cur = os.getcwd()
    os.chdir(ROOT)
    try:
        cb = get_last_callable(open(our_path).read(), path=our_path)
    finally:
        os.chdir(cur)
    md = getattr(cb, '__globals__', {}).get('my_deck')
    assert md and len(md) == 60, f'our agent deck failed to load ({md and len(md)} cards)'
    return cb


def deck_attack_ids(agent_dir):
    """The attack IDs of OUR deck's Pokémon — used to identify OUR attacks reliably
    (the log playerIndex is relative-to-observer and flips by seat, so don't trust it)."""
    deck = [int(l) for l in open(ROOT + '/' + agent_dir + '/deck.csv') if l.strip()]
    ids = set()
    for cid in set(deck):
        c = CT.get(cid)
        if c and getattr(c, 'attacks', None):
            ids.update(c.attacks)
    return ids


def our_event_stream(steps, our_idx):
    """Ordered engine events from OUR perspective. Each step is [p0_state, p1_state]; our
    state at index our_idx carries, when we are ACTIVE, the delta of events since our last
    action. Concatenating those deltas reconstructs the full game from our side."""
    stream = []
    for st in steps:
        if our_idx >= len(st):
            continue
        e = st[our_idx]
        if e.get('status') != 'ACTIVE':
            continue
        stream.extend((e.get('observation') or {}).get('logs') or [])
    return stream


def analyze_game(steps, our_idx, we_lost, our_atk_ids):
    """Detect anomalies in one game. OUR attacks are identified by attackId (the log
    playerIndex is relative-to-observer and unreliable across seats)."""
    ev = our_event_stream(steps, our_idx)
    res = {'attack_no_damage': {}, 'damaging_attacks': 0, 'deckout_loss': 0, 'no_offense_loss': 0}

    # For each of OUR attacks (attackId in our deck), did an HP change follow before the
    # attack resolved (next ATTACK / turn boundary)? If not -> it dealt 0 (anomaly).
    for i, e in enumerate(ev):
        if e.get('type') == ATTACK and e.get('attackId') in our_atk_ids:
            dealt = False
            for f in ev[i + 1:]:
                t = f.get('type')
                if t in (ATTACK, TURN_END, TURN_START):
                    break
                if t == HP_CHANGE and f.get('value', 0) != 0:
                    dealt = True; break
            if dealt:
                res['damaging_attacks'] += 1
            else:
                aid = e.get('attackId')
                res['attack_no_damage'][aid] = res['attack_no_damage'].get(aid, 0) + 1

    # deckout: we lost with 0 deck left (read our deckCount from the last obs we saw).
    if we_lost:
        deck = None
        for st in reversed(steps):
            for e in st:
                obs = e.get('observation') or {}
                cur = obs.get('current') or {}
                pls = cur.get('players')
                if pls and len(pls) > our_idx and isinstance(pls[our_idx], dict):
                    d = pls[our_idx].get('deck')
                    if isinstance(d, (int, list)):
                        deck = len(d) if isinstance(d, list) else d
                        break
            if deck is not None:
                break
        if deck == 0:
            res['deckout_loss'] = 1

    # no_offense_loss: a loss in which we landed <=1 damaging attack the whole game ->
    # we got stuck / never pressured (item-locked, no energy, all attacks blocked, etc.).
    if we_lost and res['damaging_attacks'] <= 1:
        res['no_offense_loss'] = 1

    # prize race: read the final remaining-prize counts (start at 6; lower = closer to win).
    our_rem = opp_rem = 6
    for st in reversed(steps):
        if our_idx >= len(st):
            continue
        cur = (st[our_idx].get('observation') or {}).get('current') or {}
        yi = cur.get('yourIndex'); pls = cur.get('players')
        if yi is None or not pls or len(pls) < 2:
            continue
        op, pp = pls[yi].get('prize'), pls[1 - yi].get('prize')
        if isinstance(op, list) and isinstance(pp, list):
            our_rem, opp_rem = len(op), len(pp); break
    res['prizes_taken'] = 6 - our_rem        # how many prizes WE took
    res['opp_prizes_taken'] = 6 - opp_rem

    # classify WHY we lost (dominant cause) -> drives what to fix
    res['loss_class'] = None
    if we_lost:
        if res['deckout_loss']:
            res['loss_class'] = 'deckout'              # milled ourselves out
        elif res['damaging_attacks'] <= 1:
            res['loss_class'] = 'no_offense'           # never got to attack (locked/starved)
        elif res['prizes_taken'] <= 1:
            res['loss_class'] = 'blown_out'            # attacked but got run over on prizes
        elif res['prizes_taken'] >= 3:
            res['loss_class'] = 'close_race'           # traded evenly, lost on the wire
        else:
            res['loss_class'] = 'traded_lost'
    return res


def run_matchup(our_cb, our_path, opp_name, games, our_atk_ids):
    from kaggle_environments import make
    # mirror: a SECOND independent callable (separate module state) so the two seats don't
    # share our agent's globals. One of OUR decks (bellibolt/typhlosion/alakazam) as the
    # opponent is loaded as a callable so it pilots its real deck (not via the sample-bot
    # path); other opponents come from the consensus sample bots.
    OUR_AGENTS = {'bellibolt', 'typhlosion', 'alakazam'}
    if opp_name == 'mirror':
        oppfile = load_our_callable(our_path)
    elif opp_name in OUR_AGENTS:
        oppfile = load_our_callable(ROOT + '/agents/' + opp_name + '/main.py')
    else:
        oppfile = ce.prep_opponent(opp_name)
    w = [0, 0, 0]           # win / loss / draw
    agg = {'attack_no_damage': {}, 'no_offense_loss': 0, 'deckout_loss': 0, 'error_games': 0}
    loss_classes = {}       # why we lost: deckout / no_offense / blown_out / close_race / traded_lost
    prizes_in_losses = []   # how many prizes we took in games we lost
    examples = []
    for g in range(games):
        env = make('cabt')
        order = [our_cb, oppfile] if g % 2 == 0 else [oppfile, our_cb]
        our_idx = 0 if g % 2 == 0 else 1
        res = env.run(order)
        last = res[-1]
        ru, ro = last[our_idx].get('reward'), last[1 - our_idx].get('reward')
        if last[our_idx].get('status') not in ('DONE', 'ACTIVE', 'INACTIVE'):
            agg['error_games'] += 1
        we_lost = (ru is None) or (ro is not None and ro > ru)
        if ru is None: w[1] += 1
        elif ro is None: w[0] += 1
        elif ru > ro: w[0] += 1
        elif ro > ru: w[1] += 1
        else: w[2] += 1
        a = analyze_game(env.steps, our_idx, we_lost, our_atk_ids)
        for aid, n in a['attack_no_damage'].items():
            agg['attack_no_damage'][aid] = agg['attack_no_damage'].get(aid, 0) + n
        agg['no_offense_loss'] += a['no_offense_loss']
        agg['deckout_loss'] += a['deckout_loss']
        if a.get('loss_class'):
            loss_classes[a['loss_class']] = loss_classes.get(a['loss_class'], 0) + 1
            prizes_in_losses.append(a['prizes_taken'])
        if (a['attack_no_damage'] or a['no_offense_loss'] or a['deckout_loss']) and len(examples) < 5:
            examples.append(g)
        print(f'  game {g+1}/{games}: us={ru} opp={ro}'
              f"{' [0dmg]' if a['attack_no_damage'] else ''}"
              f"{' [no-offense]' if a['no_offense_loss'] else ''}"
              f"{' [deckout]' if a['deckout_loss'] else ''}", flush=True)
    t = w[0] + w[1]
    wr = (w[0] / t * 100) if t else 0
    nd = {attack_name(aid): n for aid, n in sorted(agg['attack_no_damage'].items(), key=lambda x: -x[1])}
    lc = dict(sorted(loss_classes.items(), key=lambda x: -x[1]))
    avg_prize_loss = round(sum(prizes_in_losses) / len(prizes_in_losses), 1) if prizes_in_losses else None
    out = {'opponent': opp_name, 'games': games, 'winrate': round(wr, 1),
           'W': w[0], 'L': w[1], 'attack_no_damage': nd, 'no_offense_loss': agg['no_offense_loss'],
           'deckout_loss': agg['deckout_loss'], 'error_games': agg['error_games'],
           'loss_causes': lc, 'avg_prizes_taken_in_losses': avg_prize_loss,
           'example_games': examples}
    print(f'[analyze] {opp_name}: {w[0]}W/{w[1]}L = {wr:.0f}% | loss-causes={lc} | '
          f'avg-prizes-in-loss={avg_prize_loss}/6 | 0dmg={nd}')
    return out


def main():
    agent_dir = sys.argv[1] if len(sys.argv) > 1 else 'agents/alakazam'
    opp = sys.argv[2] if len(sys.argv) > 2 else 'all'
    games = int(sys.argv[3]) if len(sys.argv) > 3 else 50
    our = ROOT + '/' + agent_dir + '/main.py'
    if not os.path.exists(ROOT + '/' + agent_dir + '/cg'):
        import shutil; shutil.copytree(ROOT + '/docs/official/models/cg-lib/cg', ROOT + '/' + agent_dir + '/cg')
    our_atk_ids = deck_attack_ids(agent_dir)
    our_cb = load_our_callable(our)
    opps = OPPONENTS if opp == 'all' else [opp]
    reports = [run_matchup(our_cb, our, o, games, our_atk_ids) for o in opps]
    name = agent_dir.rstrip('/').split('/')[-1]
    summary = {'agent': agent_dir, 'games_per_matchup': games, 'matchups': reports}
    path = f'/tmp/analyze_{name}.json'
    json.dump(summary, open(path, 'w'), ensure_ascii=False, indent=2)
    print(f'\n=== PROBLEM REPORT ({agent_dir}) — saved {path} ===')
    print(f"  {'matchup':10s} {'WR':>5s}  loss-causes (dominant first) | avg-prizes-taken-in-loss")
    for r in reports:
        lc = ' '.join(f'{k}:{v}' for k, v in r['loss_causes'].items()) or '(no losses)'
        print(f"  {r['opponent']:10s} {r['winrate']:4.0f}%  {lc}  | {r['avg_prizes_taken_in_losses']}/6")
    print("\n  loss-cause legend: deckout=milled out | no_offense=never attacked (locked/"
          "energy-starved) | blown_out=attacked but run over on prizes (≤1 prize) | "
          "close_race=traded evenly, lost on the wire (≥3 prizes) | traded_lost=2 prizes")


if __name__ == '__main__':
    main()
