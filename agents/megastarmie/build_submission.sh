#!/usr/bin/env bash
# Pack this agent (main.py + deck.csv + the cg engine) into submission.tar.gz.
# Provide the engine path:  CG_LIB_PATH=/path/to/cg-lib/cg bash build_submission.sh
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
cp "$SRC/main.py" "$TMP/main.py"
cp "$SRC/deck.csv" "$TMP/deck.csv"
# Bundle the shared base policy (single source of truth at agents/_base/) as a sibling so the
# self-contained submission can `import policy_base`. -L dereferences the dev symlink.
cp -L "$SRC/policy_base.py" "$TMP/policy_base.py"
[ -n "${CG_LIB_PATH:-}" ] && cp -r "$CG_LIB_PATH" "$TMP/cg"
( cd "$TMP" && tar -czf "$SRC/submission.tar.gz" . )
echo "Done: $SRC/submission.tar.gz"
tar -tzf "$SRC/submission.tar.gz" | grep -E "main|deck|policy_base"
