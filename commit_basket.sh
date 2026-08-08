#!/usr/bin/env bash
# commit_basket.sh — host-side commit helper for the AI-basket lane.
#
# Why this exists: agent sessions run against a mounted view of this folder that
# can write files but cannot delete git's lock files. A commit made from that
# side can leave a stale .git/index.lock or .git/HEAD.lock behind, which blocks
# every subsequent commit with "Another git process seems to be running".
# Running this ON YOUR MACHINE clears those stale locks and commits the basket
# work in scoped commits.
#
# Usage:
#   ./commit_basket.sh            # clear locks + commit whatever basket work is pending
#   ./commit_basket.sh --dry-run  # show what would be committed, change nothing
#
# Safety: this ONLY stages basket-lane paths by explicit name. It never runs
# `git add .` and never touches the automation / coordination / capital files
# that belong to the other agent's lane.

set -uo pipefail
cd "$(dirname "$0")" || exit 1

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

# --- 1. clear stale locks (safe: only if no git process is actually running) ---
if pgrep -x git >/dev/null 2>&1; then
  echo "!! A real git process is running. Not touching locks. Try again shortly."
  exit 1
fi
for lock in .git/index.lock .git/HEAD.lock; do
  if [ -e "$lock" ]; then
    echo "clearing stale $lock"
    [ "$DRY" -eq 0 ] && rm -f "$lock"
  fi
done

# --- 2. basket-lane paths, grouped by topic ---
CODE=(
  inferno_ai_basket_config.py
  inferno_ai_basket_alerts.py
  inferno_ai_basket_composite.py
  inferno_ai_basket_momentum.py
  inferno_ai_basket_vs_benchmark.py
  inferno_ai_basket_review.py
  inferno_ai_basket_sizing.py
  inferno_basket_holdings_join.py
  inferno_ai_basket_signal_history.py
  inferno_ai_basket_regime.py
  research/ai_basket_universe.json
  tests/test_inferno_ai_basket_config.py
  tests/test_inferno_ai_basket_alerts.py
  tests/test_inferno_ai_basket_composite.py
  tests/test_inferno_ai_basket_momentum.py
  tests/test_inferno_ai_basket_vs_benchmark.py
  tests/test_inferno_ai_basket_review.py
  tests/test_inferno_ai_basket_sizing.py
  tests/test_inferno_basket_holdings_join.py
  tests/test_inferno_ai_basket_signal_history.py
  tests/test_inferno_ai_basket_regime.py
  tests/test_inferno_basket_artifact_sync.py
)
DOCS=(
  docs/BASKET_VS_SMH_2026-07-13.md
  docs/PORTFOLIO_THESIS_AND_FRAMING_2026-07-13.md
  docs/MOMENTUM_VS_BUYLOW_VERDICT_2026-07-15.md
  docs/BASKET_OPERATING_DECISIONS_2026-07-20.md
)
ARTIFACT=( ai_basket_tracker.html )

commit_group () {
  local msg="$1"; shift
  local present=()
  for f in "$@"; do [ -e "$f" ] && present+=("$f"); done
  [ ${#present[@]} -eq 0 ] && { echo "-- nothing for: $msg"; return 0; }
  if ! git diff --quiet -- "${present[@]}" 2>/dev/null \
     || ! git diff --cached --quiet -- "${present[@]}" 2>/dev/null \
     || git ls-files --others --exclude-standard -- "${present[@]}" | grep -q .; then
    echo "== $msg"
    if [ "$DRY" -eq 1 ]; then
      printf '   would stage: %s\n' "${present[@]}"
    else
      git add -- "${present[@]}" && git commit -q -m "$msg" && echo "   committed."
    fi
  else
    echo "-- clean, skipping: $msg"
  fi
}

# --- 3. run the tests before committing code (never commit a red suite) ---
if [ "$DRY" -eq 0 ]; then
  echo "== running basket test suite"
  if ! python3 -m unittest discover -s tests -p 'test_inferno_*basket*.py' -q >/dev/null 2>&1; then
    echo "!! basket tests FAILED — refusing to commit. Fix them first."
    exit 1
  fi
  echo "   tests green."
fi

commit_group "basket: engines, sizing, and tests"                 "${CODE[@]}"
commit_group "basket: research memos and momentum-vs-buy-low verdict" "${DOCS[@]}"
commit_group "basket: live tracker artifact (vs-SMH + factor exposure)" "${ARTIFACT[@]}"

echo
echo "Done. Current HEAD:"
git log --oneline -3
echo
echo "NOTE: coordination/ and the automation modules were intentionally NOT touched"
echo "      (other agent's lane). Commit those separately if you want them in."
