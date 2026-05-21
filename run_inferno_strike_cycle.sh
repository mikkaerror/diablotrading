#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

deployable_cash="${INFERNO_DEPLOYABLE_CASH:-}"
selector_args=()
while (( $# )); do
  case "$1" in
    --deployable-cash)
      deployable_cash="${2:-}"
      shift 2
      ;;
    --deployable-cash=*)
      deployable_cash="${1#*=}"
      shift
      ;;
    *)
      selector_args+=("$1")
      shift
      ;;
  esac
done

set +e
python3 inferno_schwab_daily_ops.py --quiet
schwab_status=$?
set -e
if [[ "$schwab_status" -ne 0 ]]; then
  echo "Warning: Schwab daily ops refresh did not complete; strike selector will use latest saved chain data." >&2
fi

set +e
python3 inferno_strike_selector.py build --record-ledger "${selector_args[@]}"
selector_status=$?
set -e

python3 inferno_downloads_manager.py scan
python3 inferno_tos_fill_ingest.py ingest
python3 inferno_shadow_evidence.py build
python3 inferno_performance_analytics.py build
python3 inferno_strategy_lab.py build
python3 inferno_exposure_analytics.py build
python3 inferno_broker_preview.py build
python3 inferno_authority_controller.py build
if [[ -n "$deployable_cash" ]]; then
  python3 inferno_capital_allocator.py build --deployable-cash "$deployable_cash"
else
  python3 inferno_capital_allocator.py build
fi
python3 inferno_tos_sandbox.py build
python3 inferno_paper_test_director.py build
python3 inferno_paper_evidence_loop.py build
python3 inferno_paper_exit_auditor.py build

exit "$selector_status"
