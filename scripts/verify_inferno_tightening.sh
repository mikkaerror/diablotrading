#!/usr/bin/env bash
# Verify the 2026-05-10 tightening pass end-to-end on the operator's Mac.
# Run from the project root:
#   bash scripts/verify_inferno_tightening.sh
#
# Or from anywhere:
#   bash "<repo-root>/scripts/verify_inferno_tightening.sh"
#
# Read-only by default. Does not place trades. Does not open thinkorswim.

set -uo pipefail

# Resolve project root regardless of where the script was invoked from.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
sep()  { printf '\n────────────────────────────────────────\n'; }

failures=0
run_step() {
    local label="$1"; shift
    sep
    bold "▶ $label"
    if "$@"; then
        bold "✓ $label"
    else
        failures=$((failures+1))
        bold "✗ $label (continuing)"
    fi
}

run_step "Full unittest discover" python3 -m unittest discover tests
run_step "Inferno doctor"          python3 inferno_doctor.py
run_step "Deploy preflight"        ./run_inferno_deploy_preflight.sh
run_step "Ops maintenance sweep"   ./run_inferno_ops_maintenance.sh
run_step "Approval staleness governor (dry inspection)" python3 inferno_approval_queue.py expire
run_step "Strategy replay (research-only backtest)"     python3 inferno_strategy_replay.py
run_step "Promotion gap (research-only diagnostic)"     python3 inferno_promotion_gap.py
run_step "Approval cadence (decide-today batting order)" python3 inferno_approval_cadence.py
run_step "Decision briefs (per-ticker context memos)"   python3 inferno_decision_brief.py
run_step "Daily success scorecard"                      python3 inferno_daily_success.py
run_step "Command center onboard digest"                python3 inferno_model_command_center.py onboard
run_step "Threshold sensitivity sweep (backtest)"       python3 inferno_threshold_sensitivity.py
run_step "TOS export stability (observation-only)"      python3 inferno_tos_export_stability.py --attempts 2 --backoff-seconds 0
run_step "TOS export chain (end-to-end diagnostic)"     python3 inferno_tos_export_chain.py
run_step "Skills audit (research-only)"                 python3 inferno_skills_audit.py
run_step "Heartbeat ledger (liveness summary)"          python3 inferno_heartbeat.py summary
run_step "Theme synthesizer (evidence cube)"            python3 inferno_theme_synthesizer.py
run_step "Hypothesis lab (generate + backtest ideas)"   python3 inferno_hypothesis_lab.py
run_step "Hypothesis ledger (trajectory memory)"        python3 inferno_hypothesis_ledger.py summary
run_step "Counterfactual replay (policy ranking)"       python3 inferno_counterfactual.py
run_step "Brain console (single-screen view)"           python3 inferno_brain_console.py --save
run_step "Watchlist ingest preview"                     python3 inferno_watchlist_ingest.py preview
run_step "Night prep (bedside check)"                   python3 inferno_night_prep.py
run_step "Brain cycle journal (list)"                   python3 inferno_brain_cycle_journal.py list
run_step "Operator daily loop (master read-only run)"   ./run_inferno_daily_loop.sh

sep
if [ "$failures" -eq 0 ]; then
    bold "All verification steps passed."
    exit 0
fi
bold "$failures verification step(s) failed. Review the output above."
exit 1
