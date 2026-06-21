"""Meta analyzer — daily ladder episode → deck-archetype landscape.

Streams a Kaggle episode .zip (do NOT extract: ~21GB unpacked) and reports, for that
day's real ladder games:

  1. FIELD distribution + win rate per archetype (whole field).
  2. TOP-TIER slice: among players whose ladder Elo >= --elo (default 1250, mapped from
     the downloaded leaderboard CSV by TeamName), what they actually run and how it does.
     This is the signal for "what the new top decks are" — not the noisy whole field.
  3. ARCHETYPE x ARCHETYPE matchup win rates for the biggest decks (rock-paper-scissors).

Archetype label = the headline Pokémon (megaEx > ex > stage2/1 > most-copied), same rule
as tools/cabt_eval.dk so labels line up across our tooling.

Player Elo comes from the leaderboard CSV (episode JSON has no score). Download once:
  venv/bin/kaggle competitions leaderboard pokemon-tcg-ai-battle --download -p /tmp/lb

Usage:
  venv/bin/python tools/meta_analyze.py <episode_zip> [--elo 1250] [--max N] [--lb /tmp/lb]
  venv/bin/python tools/meta_analyze.py /tmp/ep19/pokemon-tcg-ai-battle-episodes-2026-06-19.zip
"""
import sys, os, json, csv, glob, zipfile, argparse, warnings
from collections import Counter, defaultdict
warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT + '/docs/official/models/cg-lib')
from cg.api import all_card_data

CT = {c.cardId: c for c in all_card_data()}

# Generic draw/search ENGINE Pokémon shared across many decks — they are NEVER the deck's
# win condition, so they must not become the archetype label. (Without this, Alakazam decks
# get mislabelled "Fezandipiti ex" because Fezandipiti ex is an ex and outranks the stage-2
# Alakazam.) Match by name substring so all printings/owners are covered.
SUPPORT = ('Fezandipiti', 'Dudunsparce', 'Dunsparce', 'Shaymin', 'Fan Rotom', 'Rotom',
           'Dedenne', 'Genesect', 'Lumineon', 'Radiant', 'Mew ', 'Snorlax', 'Bibarel',
           'Bidoof', 'Lechonk', 'Squawkabilly')


def _is_support(pid):
    nm = CT[pid].name or ''
    return any(s in nm for s in SUPPORT)


def dk(deck):
    """Archetype label for a 60-card list: the WIN-CONDITION Pokémon, ignoring shared draw/
    search engines (SUPPORT). Priority megaEx>ex>stage2>stage1>most copies; pre-evos never
    outrank their evolution because higher stages are checked first."""
    cc = Counter(deck)
    poke = [(k, v) for k, v in cc.items() if k in CT and k < 1000 and CT[k].hp]
    core = [p for p in poke if not _is_support(p[0])] or poke   # fall back if all support
    for rank in ('megaEx', 'ex'):
        cand = [p for p in sorted(core, key=lambda x: -x[1]) if getattr(CT[p[0]], rank, 0)]
        if cand:
            return CT[cand[0][0]].name
    for stage in ('stage2', 'stage1'):
        cand = [p for p in sorted(core, key=lambda x: -x[1]) if getattr(CT[p[0]], stage, 0)]
        if cand:
            return CT[cand[0][0]].name
    if not core:
        return '?'
    return CT[max(core, key=lambda x: x[1])[0]].name


def load_elo(lb_dir):
    """name -> Elo, keyed by leaderboard TeamName (best episode-name match: ~94%)."""
    files = sorted(glob.glob(lb_dir + '/*publicleaderboard*.csv'))
    if not files:
        print(f'[warn] no leaderboard CSV in {lb_dir}; top-tier slice disabled')
        return {}
    elo = {}
    with open(files[-1], encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            try:
                elo[row['TeamName'].strip()] = float(row['Score'])
            except (KeyError, ValueError):
                continue
    print(f'[elo] loaded {len(elo)} teams from {os.path.basename(files[-1])}')
    return elo


def iter_games(zip_path, max_n):
    """Yield (deckA, deckB, winner_idx_or_None, [nameA, nameB]) per episode."""
    z = zipfile.ZipFile(zip_path)
    names = [x for x in z.namelist() if x.endswith('.json')]
    n = 0
    for nm in names:
        if max_n and n >= max_n:
            break
        try:
            d = json.loads(z.read(nm))
            rw = d['rewards']
            decks = [d['steps'][1][0]['action'], d['steps'][1][1]['action']]
            if not (isinstance(decks[0], list) and len(decks[0]) == 60):
                continue
            who = None if rw[0] == rw[1] else (0 if rw[0] > rw[1] else 1)
            pl = [a['Name'] for a in d['info']['Agents']]
            n += 1
            yield decks[0], decks[1], who, pl
        except Exception:
            continue


def report(zip_path, elo_map, elo_cut, max_n):
    field_app, field_win = Counter(), Counter()                 # whole field
    top_app, top_win = Counter(), Counter()                     # players Elo>=cut
    matchup = defaultdict(lambda: [0, 0])                       # (A,B)->[A_wins,total]
    games = top_games = 0
    for dA, dB, who, pl in iter_games(zip_path, max_n):
        if who is None:
            continue
        games += 1
        labels = [dk(dA), dk(dB)]
        for i in (0, 1):
            field_app[labels[i]] += 1
            if who == i:
                field_win[labels[i]] += 1
        # top-tier slice: focal player must clear the Elo cut
        for i in (0, 1):
            if elo_map.get(pl[i], 0) >= elo_cut:
                top_app[labels[i]] += 1
                top_games += 1
                if who == i:
                    top_win[labels[i]] += 1
        # matchup matrix (ordered pair winner)
        a, b = labels
        matchup[(a, b)][1] += 1
        if who == 0:
            matchup[(a, b)][0] += 1
        matchup[(b, a)][1] += 1
        if who == 1:
            matchup[(b, a)][0] += 1

    def tbl(app, win, title, denom_games):
        print(f'\n=== {title} (decisive games={denom_games}) ===')
        print(f'{"archetype":26s} {"field%":>7} {"winrate":>8} {"n":>6}')
        for k, n in app.most_common(15):
            print(f'{k:26s} {n/(2*denom_games)*100:6.1f}% {win[k]/n*100:7.1f}% {n:6d}')

    tbl(field_app, field_win, 'FIELD — all players', games)
    if elo_map:
        tbl(top_app, top_win, f'TOP TIER — Elo>={elo_cut:.0f}', max(top_games // 2, 1))

    # matchup table for the top-8 field decks
    top_decks = [k for k, _ in field_app.most_common(8)]
    print(f'\n=== MATCHUP win% (row vs col, blank=<5 games) — top {len(top_decks)} decks ===')
    hdr = ' ' * 16 + ''.join(f'{d[:7]:>8}' for d in top_decks)
    print(hdr)
    for a in top_decks:
        cells = []
        for b in top_decks:
            w, t = matchup[(a, b)]
            cells.append(f'{w/t*100:7.0f}%' if t >= 5 and a != b else (f'{"—":>8}'))
        print(f'{a[:15]:15s} ' + ''.join(cells))

    out = {'zip': os.path.basename(zip_path), 'games': games,
           'field': {k: {'pct': round(n/(2*games)*100, 1), 'wr': round(field_win[k]/n*100, 1), 'n': n}
                     for k, n in field_app.most_common(20)},
           'top_tier': {k: {'wr': round(top_win[k]/n*100, 1), 'n': n}
                        for k, n in top_app.most_common(20)} if elo_map else {},
           'elo_cut': elo_cut}
    date = ''.join(filter(str.isdigit, os.path.basename(zip_path)))[-8:]
    path = f'/tmp/meta_{date or "x"}.json'
    json.dump(out, open(path, 'w'), ensure_ascii=False, indent=2)
    print(f'\nsaved {path}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('zip')
    ap.add_argument('--elo', type=float, default=1250)
    ap.add_argument('--max', type=int, default=0, help='cap episodes (0=all)')
    ap.add_argument('--lb', default='/tmp/lb')
    a = ap.parse_args()
    report(a.zip, load_elo(a.lb), a.elo, a.max)


if __name__ == '__main__':
    main()
