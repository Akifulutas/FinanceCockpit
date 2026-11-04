#!/bin/bash
# Salt-okunur Scalable CLI ornek toplayici. YALNIZ okuma komutlari calistirir.
# Ciktilar masa/var/private/sc_probe/ altina yazilir (gizli, depoya girmez).
set -uo pipefail
SC="${MASA_SC_BIN:-/opt/homebrew/bin/sc}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/var/private/sc_probe"
mkdir -p "$DIR"; chmod 700 "$DIR"
run() { local name="$1"; shift; echo "-> sc $*"; "$SC" "$@" >"$DIR/$name.out" 2>"$DIR/$name.err"; echo $? >"$DIR/$name.rc"; }
"$SC" --version >"$DIR/version.out" 2>&1
run whoami            whoami --json
run context           broker context show --json
run holdings          broker holdings --json
run cash              broker cash-breakdown --json
run transactions      broker transactions --json
run chart_portfolio   broker chart --timeframe 1y --json
run chart_isin        broker chart --isin IE00B3YLTY66 --timeframe 1y --json
run quote             broker quote --isin IE00B3YLTY66 --json
run help_root         --help
run help_login        login --help
run help_tx           broker transactions --help
run help_chart        broker chart --help
run help_quote        broker quote --help
echo; echo "Tamam. Ornekler: $DIR"; ls -la "$DIR"
