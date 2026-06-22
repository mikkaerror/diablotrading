#!/usr/bin/env bash
#
# Nightly always-on optimization loop for the Inferno desk.
#
# What this does, in order:
#   1) refresh upstream data sources (Schwab account / options / price history,
#      live account sync, tracker)
#   2) harvest paper/shadow evidence and close eligible observations
#   3) re-run the research-only recommenders that consume them
#   4) regenerate the reports/ surfaces
#   5) append a daily NLV snapshot to data/nlv_history.csv
#   6) write a single coordination note summarizing what changed
#
# What this DOES NOT do (see CLAUDE.md §8):
#   - approve or reject any paper ticket  (operator runs ./today.sh)
#   - touch the capital-scaling ack file  (operator decision)
#   - mutate authority / live trading flags  (system-locked)
#   - edit the universe / tracker / risk policy constants
#
# Designed to be cron-able. Idempotent. Fails soft per step so one bad
# adapter doesn't kill the whole run. Logs each step's exit code to
# data/nightly_optimize_run.log so you can see what worked.
#
# Usage:
#   ./nightly_optimize.sh              # run all steps
#   ./nightly_optimize.sh --dry-run    # show what would run, do nothing
#

set -uo pipefail
cd "$(dirname "$0")"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi

PYTHON="${INFERNO_PYTHON:-python3}"
RUN_LOG="data/nightly_optimize_run.log"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

mkdir -p data reports

echo "" >> "$RUN_LOG"
echo "=== nightly_optimize run $TIMESTAMP ===" >> "$RUN_LOG"

run_step() {
  local label="$1"
  shift
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] $label: $*"
    return 0
  fi
  echo "  -> $label" | tee -a "$RUN_LOG"
  "$@" >> "$RUN_LOG" 2>&1
  local rc=$?
  echo "     exit=$rc" >> "$RUN_LOG"
  return 0
}

# 1) data sources (research-only, read-only)
run_step "schwab account sync"   "$PYTHON" inferno_schwab_account_sync.py --quiet
run_step "live account sync"     "$PYTHON" inferno_live_account_sync.py
run_step "schwab options chain"  "$PYTHON" inferno_schwab_daily_ops.py --quiet
run_step "schwab price history"  "$PYTHON" inferno_schwab_price_history.py --quiet

# 2) evidence harvest (research-only; no approval or staging mutation)
#
# This must run before performance/strategy/velocity. Otherwise a newly closed
# paper outcome can sit in the ledger while the nightly summaries still report
# yesterday's count.
run_step "paper evidence harvest" ./run_inferno_paper_evidence_harvest.sh

# 3) recommenders (research-only)
run_step "capital scaling"       "$PYTHON" inferno_capital_scaling.py
run_step "performance analytics" "$PYTHON" inferno_performance_analytics.py
run_step "strategy lab"          "$PYTHON" inferno_strategy_lab.py
run_step "account optimization"  "$PYTHON" inferno_account_optimization.py
run_step "paper velocity"        "$PYTHON" inferno_paper_velocity.py
run_step "trade management"      "$PYTHON" inferno_trade_management.py
run_step "process compliance"    "$PYTHON" inferno_process_compliance.py build
run_step "net-R expectancy"      "$PYTHON" inferno_expectancy_ledger.py build
run_step "DTE policy analysis"   "$PYTHON" inferno_dte_policy_analysis.py build
run_step "behavior audit"        "$PYTHON" inferno_trading_behavior_audit.py build
run_step "portfolio heat"        "$PYTHON" inferno_portfolio_heat.py build
run_step "wheel shadow"          "$PYTHON" inferno_wheel_shadow.py build
run_step "market mastery plan"   "$PYTHON" inferno_market_mastery_plan.py --quiet

# 4) meta surfaces
run_step "central command"       "$PYTHON" inferno_model_command_center.py
run_step "while-away packet"     "$PYTHON" inferno_while_away_packet.py

# 5) daily NLV snapshot (backlog item #1)
run_step "nlv snapshot"          "$PYTHON" record_nlv_snapshot.py

# 6) coordination note (backlog item #7)
if [[ "$DRY_RUN" == "0" ]]; then
  "$PYTHON" inferno_model_command_center.py note \
    --author automation \
    --title "nightly optimize loop ran" \
    --body "Daily research-only refresh complete. See data/nightly_optimize_run.log for per-step exit codes. No authority touched, no tickets approved." \
    --tags nightly-optimize,research-only,automation \
    >> "$RUN_LOG" 2>&1 || true
fi

echo "=== done $TIMESTAMP ===" >> "$RUN_LOG"
echo "nightly optimize complete -- tail $RUN_LOG for details"
