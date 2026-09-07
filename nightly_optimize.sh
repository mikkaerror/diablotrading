#!/usr/bin/env bash
#
# Nightly always-on optimization loop for the Inferno desk.
#
# What this does, in order:
#   1) refresh upstream data sources (Schwab account / options / price history,
#      live account sync, tracker)
#   2) harvest paper/shadow evidence and close eligible observations
#   3) re-run the research-only diagnostics and recommenders that consume them
#   4) regenerate the reports/ surfaces
#   5) append a daily NLV snapshot to data/nlv_history.csv
#   6) write a single coordination note summarizing what changed
#
# What this DOES NOT do (see CLAUDE.md §8):
#   - approve or reject any paper ticket  (operator runs ./inferno today)
#   - touch the capital-scaling ack file  (operator decision)
#   - mutate authority / live trading flags  (system-locked)
#   - edit the universe / tracker / risk policy constants
#
# Designed to be cron-able. Idempotent. Fails soft per step so one bad
# adapter doesn't kill the whole run. Logs each step's exit code to
# data/nightly_optimize_run.log so you can see what worked.
#
# Usage:
#   ./nightly_optimize.sh              # run the nightly-unique steps (default)
#   ./nightly_optimize.sh --dry-run    # show what would run, do nothing
#   INFERNO_NIGHTLY_RUN_SHARED=1 ./nightly_optimize.sh   # also re-run shared steps
#
# Reporting-noise trim (2026-09-04): run_inferno_daily_model_refresh.sh already
# regenerates the shared research/report surfaces twice a day (06:45 and 16:20
# MT), ending with the command center and doctor. This 18:30 MT loop used to
# regenerate most of them a third time two hours later, so every "_latest"
# artifact churned 3x/day with no new decision content. By default the loop now
# runs only the steps that no other schedule owns (chain history/diff, edge
# signals, basket refresh, post-trade learning layer, portfolio-level layer,
# consensus, velocity/funnel, cohort evaluator, capital scaling, while-away
# packet, NLV snapshot, housekeeping) and then rebuilds the command center so
# they surface. Set INFERNO_NIGHTLY_RUN_SHARED=1 to restore the full loop.
#

set -uo pipefail
cd "${INFERNO_ROOT:-$(dirname "$0")}"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi

PYTHON="${INFERNO_PYTHON:-python3}"
RUN_SHARED="${INFERNO_NIGHTLY_RUN_SHARED:-0}"
RUN_LOG="${INFERNO_NIGHTLY_LOG:-data/nightly_optimize_run.log}"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

mkdir -p data reports
mkdir -p "$(dirname "$RUN_LOG")"

echo "" >> "$RUN_LOG"
echo "=== nightly_optimize run $TIMESTAMP ===" >> "$RUN_LOG"

run_step() {
  local label="$1"
  shift
  if [[ "$label" == shared:* ]]; then
    if [[ "$RUN_SHARED" != "1" ]]; then
      if [[ "$DRY_RUN" == "1" ]]; then
        echo "[dry-run] skip (owned by daily model refresh) $label"
      else
        echo "  -- skip (owned by daily model refresh) $label" | tee -a "$RUN_LOG"
      fi
      return 0
    fi
    label="${label#shared:}"
  fi
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
#
# One OAuth preflight owns the refresh. Downstream jobs reuse the resulting
# access token and skip their own refresh attempts.
SCHWAB_READY=0
if [[ "$DRY_RUN" == "1" ]]; then
  run_step "schwab oauth preflight" "$PYTHON" inferno_schwab_oauth.py ensure
  SCHWAB_READY=1
else
  echo "  -> schwab oauth preflight" | tee -a "$RUN_LOG"
  if "$PYTHON" inferno_schwab_oauth.py ensure >> "$RUN_LOG" 2>&1; then
    SCHWAB_READY=1
    echo "     exit=0" >> "$RUN_LOG"
  else
    echo "     exit=1" >> "$RUN_LOG"
    echo "     Schwab-dependent refreshes skipped; run OAuth restart once." >> "$RUN_LOG"
  fi
fi

if [[ "$SCHWAB_READY" == "1" ]]; then
  run_step "shared:schwab account sync"   "$PYTHON" inferno_schwab_account_sync.py --skip-refresh --quiet
  run_step "shared:schwab transaction ledger" "$PYTHON" inferno_schwab_transaction_ledger.py build --skip-refresh --quiet
  run_step "shared:schwab options chain"  "$PYTHON" inferno_schwab_daily_ops.py --skip-refresh --quiet
  run_step "schwab chain history" "$PYTHON" inferno_chain_history.py run
  run_step "schwab chain diff"    "$PYTHON" inferno_chain_diff.py run
  run_step "schwab edge signals"   "$PYTHON" inferno_schwab_edge_signals.py run
  run_step "shared:snapshot price overlay" "$PYTHON" inferno_snapshot_price_overlay.py --quiet
  run_step "shared:schwab price history"  "$PYTHON" inferno_schwab_price_history.py --skip-refresh --quiet
  run_step "basket market refresh" "$PYTHON" inferno_ai_basket_refresh.py run --skip-refresh
fi
run_step "shared:live account sync"     "$PYTHON" inferno_live_account_sync.py
run_step "shared:full tracker taxonomy" "$PYTHON" inferno_tracker_taxonomy.py run
run_step "shared:full tracker registry" "$PYTHON" inferno_tracker_registry.py run
run_step "shared:full tracker role review" "$PYTHON" inferno_tracker_role_review.py run
run_step "shared:full tracker blank role-policy packet" "$PYTHON" inferno_tracker_role_policy_packet.py run
run_step "shared:full tracker role-policy contract" "$PYTHON" inferno_tracker_role_policy.py run

# 1b) real past earnings dates + realized moves (yfinance; fail-soft, never
#     clobbers the previous backfill), then the event-move calibration that
#     feeds the expected-move premium hurdle's per-name benchmark
run_step "earnings history fetch" "$PYTHON" inferno_earnings_history_fetch.py run
run_step "event move calibration" "$PYTHON" inferno_event_move_calibration.py run

# 2) bounded evidence goal loop (research-only; no approval or live mutation)
#
# This wraps the harvest in process/authority prechecks, persistent state, an
# independent verifier, bounded retries, and stop-on-no-progress behavior.
# It must run before performance/strategy/velocity so newly closed outcomes are
# included in the nightly summaries.
run_step "evidence goal loop" "$PYTHON" inferno_evidence_goal_loop.py run --max-iterations 2

# 3) diagnostics and recommenders (research-only)
run_step "capital scaling"       "$PYTHON" inferno_capital_scaling.py
run_step "shared:performance analytics" "$PYTHON" inferno_performance_analytics.py
run_step "shared:strategy lab"          "$PYTHON" inferno_strategy_lab.py
run_step "outcome attribution"   "$PYTHON" inferno_outcome_attribution.py run
run_step "rule edge decay"       "$PYTHON" inferno_rule_edge_decay.py run
run_step "slippage estimator"    "$PYTHON" inferno_slippage_estimator.py run
run_step "portfolio correlation" "$PYTHON" inferno_portfolio_correlation.py run
run_step "drawdown protocol"     "$PYTHON" inferno_drawdown_protocol.py run
if [[ "$SCHWAB_READY" == "1" ]]; then
  run_step "consensus monitor"    "$PYTHON" inferno_consensus_monitor.py run
fi
run_step "shared:account optimization"  "$PYTHON" inferno_account_optimization.py
run_step "shared:deposit plan"          "$PYTHON" inferno_deposit_plan.py run
run_step "shared:cash attribution"      "$PYTHON" inferno_cash_attribution.py run
run_step "shared:growth stack"          "$PYTHON" inferno_growth_stack.py run
run_step "paper velocity"        "$PYTHON" inferno_paper_velocity.py
run_step "shared:trade management"      "$PYTHON" inferno_trade_management.py
run_step "shared:process compliance"    "$PYTHON" inferno_process_compliance.py build
run_step "shared:net-R expectancy"      "$PYTHON" inferno_expectancy_ledger.py build
run_step "shared:DTE policy analysis"   "$PYTHON" inferno_dte_policy_analysis.py build
run_step "shared:behavior audit"        "$PYTHON" inferno_trading_behavior_audit.py build
run_step "shared:portfolio heat"        "$PYTHON" inferno_portfolio_heat.py build
run_step "shared:wheel shadow"          "$PYTHON" inferno_wheel_shadow.py build
run_step "funnel diagnostic"     "$PYTHON" inferno_funnel_diagnostic.py run
run_step "shared:short premium study"   "$PYTHON" inferno_short_premium_study.py run
run_step "shared:market mastery plan"   "$PYTHON" inferno_market_mastery_plan.py --quiet
run_step "shared:score threshold audit" "$PYTHON" inferno_score_threshold_audit.py run
run_step "basket data contract"  "$PYTHON" inferno_ai_basket_data_contract.py run
run_step "tech cohort evaluator" "$PYTHON" inferno_tech_cohort_evaluator.py run

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
    --body "Daily research-only refresh complete. See $RUN_LOG for per-step exit codes. No authority touched, no tickets approved." \
    --tags nightly-optimize,research-only,automation \
    >> "$RUN_LOG" 2>&1 || true
fi

# 7) bound runtime log growth without deleting research or paper evidence.
run_step "runtime log housekeeping" "$PYTHON" inferno_housekeeping.py --logs-only --include-external-logs

echo "=== done $TIMESTAMP ===" >> "$RUN_LOG"
echo "nightly optimize complete -- tail $RUN_LOG for details"
