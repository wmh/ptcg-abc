#!/usr/bin/env python3
"""autopsy — daily ladder post-mortem: meta + divergence in one shot.

Usage:
  venv/bin/python tools/autopsy.py [--date 2026-06-22] [--agent-dir agents/dragapult]
                      [--archetype "Dragapult ex"] [--elo 1150] [--max-games 100]

Downloads the latest episode data + leaderboard, runs meta_analyze + divergence_decode,
and saves timestamped reports to /tmp/autopsy/<date>/.

Set KAGGLE_CONFIG_DIR for multi-account setups.
"""
import sys, os, subprocess, argparse, shutil, json
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

KAGGLE = os.path.join(ROOT, 'venv/bin/kaggle')
TOOLS = os.path.join(ROOT, 'tools')
TMP = '/tmp'

TZ_TW = timezone(timedelta(hours=8))
TODAY = datetime.now(TZ_TW).strftime('%Y-%m-%d')


def log(msg):
    print(f'[autopsy] {msg}', flush=True)


def run(cmd, timeout=180):
    """Run a command, return (returncode, stdout)."""
    log(f'$ {cmd}')
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            log(f'  ⚠ exit={r.returncode}: {r.stderr.strip()[:200]}')
        else:
            # Only print last 10 lines of output
            lines = r.stdout.strip().split('\n')
            for L in lines[-10:]:
                log(f'  {L}')
        return r.returncode, r.stdout
    except subprocess.TimeoutExpired:
        log(f'  ⏰ timeout ({timeout}s)')
        return -1, ''
    except FileNotFoundError as e:
        log(f'  ❌ command not found: {e}')
        return -2, ''


def ensure_episodes(date, ep_dir):
    """Download episodes if not already cached."""
    slug = f'pokemon-tcg-ai-battle-episodes-{date}'
    zip_path = os.path.join(ep_dir, f'{slug}.zip')
    if os.path.exists(zip_path):
        log(f'  ✓ episodes cached: {zip_path} ({os.path.getsize(zip_path)>>20}MB)')
        return zip_path
    log(f'  ⬇ downloading {slug}...')
    os.makedirs(ep_dir, exist_ok=True)
    rc, out = run(f'{KAGGLE} datasets download kaggle/{slug} -p {ep_dir}', timeout=600)
    if rc != 0:
        log(f'  ❌ download failed; maybe no episode for {date} yet')
        return None
    return zip_path


def ensure_leaderboard(lb_dir):
    """Download leaderboard CSV."""
    os.makedirs(lb_dir, exist_ok=True)
    # Check if any CSV exists and is recent (< 6 hours old)
    for f in os.listdir(lb_dir):
        if f.endswith('.csv'):
            path = os.path.join(lb_dir, f)
            age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(path))).total_seconds()
            if age < 21600:  # 6 hours
                log(f'  ✓ leaderboard cached: {f} ({age//60:.0f}min old)')
                return lb_dir
    log(f'  ⬇ downloading leaderboard...')
    rc, out = run(f'{KAGGLE} competitions leaderboard pokemon-tcg-ai-battle --download -p {lb_dir}', timeout=60)
    # Unzip if needed
    zips = [f for f in os.listdir(lb_dir) if f.endswith('.zip')]
    for z in zips:
        import zipfile
        with zipfile.ZipFile(os.path.join(lb_dir, z)) as zf:
            zf.extractall(lb_dir)
        os.remove(os.path.join(lb_dir, z))
        log(f'  ✓ extracted {z}')
    return lb_dir


def run_meta(ep_zip, lb_dir, elo, max_games=None):
    """Run meta_analyze.py and save the JSON output."""
    out_json = os.path.join(os.path.dirname(ep_zip), f'meta_{os.path.basename(ep_zip)[:14]}.json')
    cmd = f'{sys.executable} {TOOLS}/meta_analyze.py {ep_zip} --elo {elo} --lb {lb_dir}'
    if max_games:
        cmd += f' --max {max_games}'
    # meta_analyze takes long; run with generous timeout
    rc, out = run(cmd, timeout=600)
    return out


def run_divergence(ep_zip, agent_dir, archetype, elo, max_games, lb_dir):
    """Run divergence_decode.py."""
    cmd = (f'{sys.executable} {TOOLS}/divergence_decode.py {ep_zip} {agent_dir} '
           f'--archetype "{archetype}" --elo {elo} --max-games {max_games} --show 30')
    rc, out = run(cmd, timeout=300)
    return out


def main():
    p = argparse.ArgumentParser(description='Daily ladder post-mortem')
    p.add_argument('--date', default=TODAY, help=f'Episode date (default: {TODAY})')
    p.add_argument('--agent-dir', default='agents/dragapult', help='Agent directory relative to repo root')
    p.add_argument('--archetype', default='Dragapult ex', help='Archetype name for divergence analysis')
    p.add_argument('--elo', type=int, default=1150, help='Top-tier Elo cutoff')
    p.add_argument('--max-games', type=int, default=50, help='Max games for divergence analysis')
    p.add_argument('--skip-download', action='store_true', help='Skip episode download (use cached)')
    args = p.parse_args()

    ep_dir = os.path.join(TMP, f'ep{args.date[-2:]}')
    lb_dir = os.path.join(TMP, 'lb')
    report_dir = os.path.join(TMP, f'autopsy/{args.date}')
    os.makedirs(report_dir, exist_ok=True)

    # ── 1. Ensure data ──
    log('=== Step 1: Ensure data ===')
    if args.skip_download:
        ep_zip = os.path.join(ep_dir, f'pokemon-tcg-ai-battle-episodes-{args.date}.zip')
        if not os.path.exists(ep_zip):
            log(f'  ❌ {ep_zip} not found; remove --skip-download')
            return 1
    else:
        ep_zip = ensure_episodes(args.date, ep_dir)
        if not ep_zip:
            return 1
    lb_dir = ensure_leaderboard(lb_dir)

    # ── 2. Meta analysis ──
    log('\n=== Step 2: Meta analysis ===')
    meta_out = run_meta(ep_zip, lb_dir, args.elo, max_games=800)
    with open(f'{report_dir}/meta.txt', 'w') as f:
        f.write(meta_out or '(empty)')

    # ── 3. Divergence analysis ──
    log('\n=== Step 3: Divergence analysis ===')
    div_out = run_divergence(ep_zip, args.agent_dir, args.archetype, args.elo, args.max_games, lb_dir)
    with open(f'{report_dir}/divergence.txt', 'w') as f:
        f.write(div_out or '(empty)')

    # ── 4. Summary ──
    log('\n=== Summary ===')
    log(f'  Date:     {args.date}')
    log(f'  Agent:    {args.agent_dir} ({args.archetype})')
    log(f'  Reports:  {report_dir}/')
    log(f'    - meta.txt         (field + top-tier distribution)')
    log(f'    - divergence.txt   (piloting gaps vs top players)')

    # Print key findings
    if meta_out:
        for line in meta_out.split('\n'):
            if any(kw in line for kw in ['TOP TIER', 'MATCHUP', 'winrate', 'field%', '------']):
                print(f'    {line}')
    if div_out:
        for line in div_out.split('\n'):
            if any(kw in line for kw in ['agree', 'DIVERGENT', 'HUMAN', 'WE picked', 'examples']):
                print(f'    {line}')

    log('Done.')


if __name__ == '__main__':
    main()
