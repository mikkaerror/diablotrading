#!/usr/bin/env bash
set -euo pipefail

ROOT="${INFERNO_ROOT:-$(cd "$(dirname "$0")" && pwd)}"
cd "$ROOT"

LIMIT="${INFERNO_MODEL_REFRESH_LIMIT:-20}"
BACKTEST_ROOT="${BACKTEST_ROOT:-$HOME/PycharmProjects/Backtest3.0}"
BACKTEST_PYTHON="${BACKTEST_PYTHON:-$BACKTEST_ROOT/venv/bin/python}"
REFRESH_TRACKER=1
WARNING_COUNT=0
SCHWAB_READY=0
LOCK_DIR="data/inferno_daily_model_refresh.lockdir"

mkdir -p data
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Daily model refresh already running; exiting without starting a duplicate."
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT INT TERM

run_advisory() {
  local label="$1"
  shift
  set +e
  "$@"
  local status=$?
  set -e
  if [[ "$status" -ne 0 ]]; then
    WARNING_COUNT=$((WARNING_COUNT + 1))
    echo "Advisory warning: $label exited $status; continuing."
  fi
}

run_strategy_alternative_pricing() {
  # Keep the wrapper's scanner-before-pricing contract without directly
  # executing a repository shell file from a background Documents process.
  python3 inferno_paper_variant_scanner.py run >/dev/null || return $?
  # This bounded supplemental tape is read-only and deliberately does not
  # replace the primary Schwab options snapshot.  A fetch failure is advisory:
  # pricing still runs against the core tape and remains fail-closed on gaps.
  run_advisory "strategy quote coverage" python3 inferno_strategy_quote_coverage.py run --limit 6 --variants-per-ticker 3
  python3 inferno_strategy_alternative_pricing.py "$@"
}

skip_schwab_step() {
  local label="$1"
  WARNING_COUNT=$((WARNING_COUNT + 1))
  echo "Advisory warning: $label skipped; Schwab OAuth reauthorization is required."
}

if [[ "${1:-}" == "--skip-tracker" ]]; then
  REFRESH_TRACKER=0
  shift
fi

echo "1/18 Schwab OAuth preflight"
if python3 inferno_schwab_oauth.py ensure; then
  SCHWAB_READY=1
else
  WARNING_COUNT=$((WARNING_COUNT + 1))
  echo "Advisory warning: Schwab OAuth preflight failed; continuing non-Schwab refreshes."
fi

if [[ "$REFRESH_TRACKER" == "1" ]]; then
  echo "2/18 Tracker and morning model refresh"
  # A transient vendor failure in the read-only dawn lane must not prevent the
  # downstream research-only reports (including the deposit growth stack) from
  # refreshing. The warning remains visible in the final run summary.
  run_advisory "tracker and morning model refresh" "$BACKTEST_PYTHON" inferno_dawn_pipeline.py --skip-email --refresh-prices
else
  echo "2/18 Tracker refresh skipped by operator"
fi

echo "3/18 Schwab account truth"
if [[ "$SCHWAB_READY" == "1" ]]; then
  # OAuth can be valid while an individual read-only endpoint is temporarily
  # unavailable. Record that as an advisory and continue to the final doctor
  # pass rather than abandoning the whole refresh with stale diagnostics.
  run_advisory "Schwab account truth" python3 inferno_schwab_account_sync.py build --skip-refresh --quiet
  run_advisory "Schwab transaction ledger" python3 inferno_schwab_transaction_ledger.py build --skip-refresh --quiet
else
  skip_schwab_step "Schwab account truth"
  skip_schwab_step "Schwab transaction ledger"
fi

echo "4/18 Schwab option-chain tape"
if [[ "$SCHWAB_READY" == "1" ]]; then
  run_advisory "Schwab option-chain tape" python3 inferno_schwab_daily_ops.py --skip-refresh --quiet
  run_advisory "snapshot price overlay" python3 inferno_snapshot_price_overlay.py --quiet
else
  skip_schwab_step "Schwab option-chain tape"
fi

echo "5/18 Schwab price history"
if [[ "$SCHWAB_READY" == "1" ]]; then
  run_advisory "Schwab price history" python3 inferno_schwab_price_history.py --from-snapshot --limit "$LIMIT" --skip-refresh --quiet
else
  skip_schwab_step "Schwab price history"
fi

echo "6/18 Schwab-derived TOS metrics"
if [[ "$SCHWAB_READY" == "1" ]]; then
  run_advisory "Schwab-derived TOS metrics" python3 inferno_schwab_tos_metrics_sync.py --from-snapshot --limit "$LIMIT" --skip-refresh --quiet
else
  skip_schwab_step "Schwab-derived TOS metrics"
fi

echo "7/18 Formula and theory audits"
run_advisory "TOS formula audit" python3 inferno_tos_formula_audit.py --limit "$LIMIT"
run_advisory "TOS metric theory audit" python3 inferno_tos_metric_theory_audit.py --limit "$LIMIT"

echo "8/18 Live account and position review"
run_advisory "live account sync" python3 inferno_live_account_sync.py build
run_advisory "live position review" python3 inferno_live_position_review.py build

echo "9/18 Bounded paper-evidence goal loop"
run_advisory "evidence goal loop" python3 inferno_evidence_goal_loop.py run --max-iterations 2

echo "10/18 Research, expected-move, and calibration cycle"
run_advisory "research cycle" python3 inferno_research_cycle.py

echo "11/18 Net-R, DTE, behavior, and process controls"
run_advisory "expectancy ledger" python3 inferno_expectancy_ledger.py build
run_advisory "DTE policy analysis" python3 inferno_dte_policy_analysis.py build
run_advisory "trading behavior audit" python3 inferno_trading_behavior_audit.py build
run_advisory "process compliance" python3 inferno_process_compliance.py build

echo "12/18 Strategy alternatives, supplemental quote coverage, short-premium monitor, and shadow comparison"
run_advisory "ticket cap policy" python3 inferno_ticket_cap_policy.py
run_advisory "strategy alternative scorer" python3 inferno_strategy_alternative_scorer.py
run_advisory "strategy alternative pricing" run_strategy_alternative_pricing --limit 6 --variants-per-ticker 3
run_advisory "short premium study" python3 inferno_short_premium_study.py run
run_advisory "strategy shadow comparison" python3 inferno_strategy_shadow_comparison.py

echo "13/18 Paper selection sync"
run_advisory "paper test director" python3 inferno_paper_test_director.py build
run_advisory "paper blocker swarm" python3 inferno_paper_blocker_swarm.py run
run_advisory "paper bottleneck reducer" python3 inferno_paper_bottleneck_reducer.py build
run_advisory "paper evidence audit" python3 inferno_paper_evidence_loop.py build

echo "14/18 Portfolio heat and wheel feasibility"
run_advisory "portfolio heat" python3 inferno_portfolio_heat.py build
run_advisory "wheel shadow" python3 inferno_wheel_shadow.py build

echo "15/18 Full-tracker taxonomy, registry, role review, blank role-policy packet, role-policy contract, capital, and market-mastery refresh"
run_advisory "full-tracker taxonomy" python3 inferno_tracker_taxonomy.py run
run_advisory "full-tracker registry" python3 inferno_tracker_registry.py run
run_advisory "full-tracker role review" python3 inferno_tracker_role_review.py run
run_advisory "full-tracker blank role-policy packet" python3 inferno_tracker_role_policy_packet.py run
run_advisory "full-tracker role-policy contract" python3 inferno_tracker_role_policy.py run
run_advisory "deposit plan" python3 inferno_deposit_plan.py
run_advisory "cash attribution" python3 inferno_cash_attribution.py
run_advisory "growth stack" python3 inferno_growth_stack.py run
run_advisory "account optimization" python3 inferno_account_optimization.py
run_advisory "market mastery plan" python3 inferno_market_mastery_plan.py

echo "16/18 Capital launch snapshot"
run_advisory "capital launch check" python3 inferno_central_command.py capital-check --deployable-cash 0

echo "17/20 Model command center"
run_advisory "model command center" python3 inferno_model_command_center.py build

echo "18/20 Doctor"
run_advisory "doctor" python3 inferno_doctor.py

echo "19/20 Central handoff"
run_advisory "central handoff" python3 inferno_central_command.py status

echo "20/20 Usage handoff"
run_advisory "usage handoff" python3 inferno_usage_optimizer.py build

echo "Daily model refresh complete. Advisory warnings=$WARNING_COUNT."
