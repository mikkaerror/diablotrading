#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

./run_inferno_paper_test_director.sh
./run_inferno_paper_bottleneck_reducer.sh
./run_inferno_fast_paper_cohort.sh
./run_inferno_paper_mark_to_market.sh
./run_inferno_scenario_evidence.sh
./run_inferno_outcome_review.sh
./run_inferno_paper_evidence_loop.sh
./run_inferno_paper_exit_auditor.sh
./run_inferno_scenario_backtest.sh
