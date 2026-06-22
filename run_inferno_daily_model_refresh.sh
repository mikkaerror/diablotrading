#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

LIMIT="${INFERNO_MODEL_REFRESH_LIMIT:-20}"
REFRESH_TRACKER=1
WARNING_COUNT=0

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

if [[ "${1:-}" == "--skip-tracker" ]]; then
  REFRESH_TRACKER=0
  shift
fi

echo "1/15 Schwab OAuth preflight"
python3 inferno_schwab_oauth.py ensure

if [[ "$REFRESH_TRACKER" == "1" ]]; then
  echo "2/15 Tracker and morning model refresh"
  ./run_inferno_dawn_cycle.sh --skip-email
else
  echo "2/15 Tracker refresh skipped by operator"
fi

echo "3/15 Schwab account truth"
python3 inferno_schwab_account_sync.py build --skip-refresh --quiet

echo "4/15 Schwab option-chain tape"
python3 inferno_schwab_daily_ops.py --skip-refresh --quiet

echo "5/15 Schwab price history"
python3 inferno_schwab_price_history.py --from-snapshot --limit "$LIMIT" --skip-refresh --quiet

echo "6/15 Schwab-derived TOS metrics"
python3 inferno_schwab_tos_metrics_sync.py --from-snapshot --limit "$LIMIT" --skip-refresh --quiet

echo "7/15 Formula and theory audits"
run_advisory "TOS formula audit" ./run_inferno_tos_formula_audit.sh --limit "$LIMIT"
run_advisory "TOS metric theory audit" ./run_inferno_tos_metric_theory_audit.sh --limit "$LIMIT"

echo "8/15 Live account and position review"
run_advisory "live account sync" python3 inferno_live_account_sync.py build
run_advisory "live position review" python3 inferno_live_position_review.py build

echo "9/15 Paper and fast-paper evidence harvest"
run_advisory "paper evidence harvest" ./run_inferno_paper_evidence_harvest.sh

echo "10/15 Research, expected-move, and calibration cycle"
run_advisory "research cycle" ./run_inferno_research_cycle.sh

echo "11/15 Net-R, DTE, behavior, and process controls"
run_advisory "expectancy ledger" ./run_inferno_expectancy_ledger.sh
run_advisory "DTE policy analysis" ./run_inferno_dte_policy_analysis.sh
run_advisory "trading behavior audit" ./run_inferno_trading_behavior_audit.sh
run_advisory "process compliance" ./run_inferno_process_compliance.sh

echo "12/15 Strategy alternatives and shadow comparison"
run_advisory "strategy alternative scorer" ./run_inferno_strategy_alternative_scorer.sh
run_advisory "strategy alternative pricing" ./run_inferno_strategy_alternative_pricing.sh --limit 4 --variants-per-ticker 2
run_advisory "strategy shadow comparison" ./run_inferno_strategy_shadow_comparison.sh

echo "13/15 Portfolio heat and wheel feasibility"
run_advisory "portfolio heat" ./run_inferno_portfolio_heat.sh
run_advisory "wheel shadow" ./run_inferno_wheel_shadow.sh

echo "14/15 Capital and market-mastery refresh"
run_advisory "account optimization" ./run_inferno_account_optimization.sh
run_advisory "market mastery plan" ./run_inferno_market_mastery_plan.sh

echo "15/15 Command center and doctor"
run_advisory "model command center" ./run_inferno_model_command_center.sh
run_advisory "doctor" python3 inferno_doctor.py

echo "Daily model refresh complete. Advisory warnings=$WARNING_COUNT."
