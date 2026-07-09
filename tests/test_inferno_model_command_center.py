from __future__ import annotations

"""Regression tests for the shared model command center."""

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import inferno_model_command_center as command_center


class InfernoModelCommandCenterTests(unittest.TestCase):
    """Protect the shared model brain from drifting or losing queue state."""

    def test_build_command_center_aggregates_artifacts_and_queue_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            reports_dir = root / "reports"
            coordination_dir = root / "coordination"
            prompts_dir = coordination_dir / "prompts"
            for path in (data_dir, reports_dir, prompts_dir):
                path.mkdir(parents=True, exist_ok=True)

            (coordination_dir / "active_missions.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "mission-1",
                            "createdAt": "2026-05-10T10:00:00-06:00",
                            "updatedAt": "2026-05-10T10:00:00-06:00",
                            "title": "Wire live dashboard overlay",
                            "body": "Show posture in the UI.",
                            "owner": "shared",
                            "status": "pending",
                            "priority": "high",
                            "tags": ["dashboard"],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (coordination_dir / "model_notes.jsonl").write_text(
                json.dumps(
                    {
                        "id": "note-1",
                        "createdAt": "2026-05-10T10:05:00-06:00",
                        "author": "codex",
                        "title": "Live lane healthy",
                        "body": "Live sync passed.",
                        "priority": "normal",
                        "tags": ["live"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (data_dir / "inferno_deploy_preflight.json").write_text(
                json.dumps({"generatedAt": "2026-05-10T10:00:00-06:00", "verdict": "ready-for-pilot", "message": "all good", "coreReady": True, "cloudReady": True, "brokerDesktopReady": True}),
                encoding="utf-8",
            )
            (data_dir / "inferno_ops_maintenance.json").write_text(
                json.dumps({"generatedAt": "2026-05-10T10:01:00-06:00", "ok": True}),
                encoding="utf-8",
            )
            (data_dir / "inferno_live_account_sync.json").write_text(
                json.dumps({"generatedAt": "2026-05-10T10:02:00-06:00", "verdict": "healthy", "message": "", "matchedSuffix": "1234", "accountDataSource": "schwab-account-api", "netLiquidatingValue": 1000.0, "totalCash": 0.0}),
                encoding="utf-8",
            )
            (data_dir / "inferno_schwab_account_sync.json").write_text(
                json.dumps({"generatedAt": "2026-05-10T10:01:30-06:00", "stage": "schwab-account-sync-read-only", "verdict": "healthy", "message": "", "matchedSuffix": "1234", "brokerReadOnly": True, "orderEndpointsAllowed": False, "netLiquidatingValue": 1000.0, "totalCash": 200.0}),
                encoding="utf-8",
            )
            (data_dir / "inferno_live_position_review.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:00-06:00",
                        "verdict": "review",
                        "message": "review one holding",
                        "counts": {"supported": 2, "review": 0, "fragile": 1},
                        "nextActions": ["Manual risk review: GDS."],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_capital_deployment_readiness.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:30-06:00",
                        "deploymentDate": "2026-05-15",
                        "verdict": "manual-ready-with-warnings",
                        "message": "manual only",
                        "manualDeploymentAllowed": True,
                        "autoLiveAllowed": False,
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_capital_scenario_matrix.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:35-06:00",
                        "stage": "capital-scenario-matrix",
                        "verdict": "all-blocked",
                        "deploymentDate": "2026-07-06",
                        "scenarioCount": 3,
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_deposit_plan.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:36-06:00",
                        "stage": "deposit-plan-research-only",
                        "verdict": "configured",
                        "researchOnly": True,
                        "authorityChanged": False,
                        "plan": {
                            "amountDollars": 250.0,
                            "intervalDays": 14,
                            "annualPlannedDollars": 6500.0,
                        },
                        "schedule": {
                            "nextDepositDate": "2026-05-15",
                            "daysUntilNextDeposit": 5,
                        },
                        "forecastWindows": {
                            "30Days": {"depositCount": 2, "grossDeposits": 500.0},
                            "90Days": {"depositCount": 6, "grossDeposits": 1500.0},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_cash_attribution.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:37-06:00",
                        "stage": "cash-attribution-research-only",
                        "verdict": "attribution-incomplete",
                        "researchOnly": True,
                        "authorityChanged": False,
                        "brokerCash": {"cash": 0.0},
                        "latestCashChange": {"deltaCash": -250.0},
                        "latestCashClassification": {
                            "classification": "cash-decrease-unattributed-without-transaction-ledger"
                        },
                        "realizedOptionsProfit": {"known": False},
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_ticket_cap_policy.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:38-06:00",
                        "stage": "ticket-cap-policy-research-only",
                        "verdict": "active",
                        "researchOnly": True,
                        "authorityChanged": False,
                        "requestedBand": {
                            "minTicketDollars": 250.0,
                            "targetTicketDollars": 250.0,
                            "maxTicketDollars": 500.0,
                        },
                        "constructionBand": {
                            "minTargetDollars": 250.0,
                            "targetTicketDollars": 250.0,
                            "hardCapDollars": 500.0,
                        },
                        "effectiveBand": {
                            "minTargetDollars": 250.0,
                            "targetTicketDollars": 250.0,
                            "hardCapDollars": 500.0,
                            "sourceRiskCapSource": "paper-budget",
                        },
                        "liveCapitalBand": {
                            "hardCapDollars": 0.0,
                            "sourceRiskCapSource": "ack",
                            "drawdownLevel": "pause",
                            "newEntriesAllowed": False,
                        },
                        "callOptionsPosture": {
                            "mode": "aggressive-defined-risk",
                            "aggressiveCallResearchEnabled": True,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_account_optimization.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:39-06:00",
                        "stage": "account-optimization-research-only",
                        "verdict": "protect-and-prove",
                        "researchOnly": True,
                        "promotable": False,
                        "authorityChanged": False,
                        "nextActions": [
                            "Close and score the 4 fast-paper simulations at the first eligible later-session quote, then open the next diversified cohort.",
                            "Keep live options max-loss authority at $0 until the strategy lab becomes promotable.",
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_live_book_review_packet.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:20-06:00",
                        "verdict": "blocked",
                        "capitalReadinessVerdict": "not-ready",
                        "manualDeploymentAllowed": False,
                        "autoLiveAllowed": False,
                        "counts": {"hardBlockers": 1, "warnings": 1, "supported": 1},
                        "unlockChecklist": ["Resolve GDS before sizing new capital."],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_while_away_packet.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:25-06:00",
                        "stage": "while-away-operator-packet",
                        "verdict": "monitor-only",
                        "researchOnly": True,
                        "promotable": False,
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_risk_gate_audit.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:45-06:00",
                        "verdict": "blocked",
                        "message": "Hard risk gates are blocking new deployment.",
                        "liveTradingAllowed": False,
                        "summary": {"hardFails": 1, "promotionFails": 2, "warnings": 1},
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_paper_test_director.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:00-06:00",
                        "verdict": "auto-paper-selected",
                        "counts": {
                            "stageableNow": 0,
                            "autoPaperSelected": 2,
                            "approvalOnly": 1,
                            "constructionWatch": 3,
                        },
                        "nextActions": ["Stage FLNC in paper only."],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_paper_blocker_swarm.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:05-06:00",
                        "stage": "paper-blocker-swarm-research-only",
                        "verdict": "fixable-blockers-present",
                        "dominantLane": "data_freshness",
                        "researchOnly": True,
                        "promotable": False,
                        "counts": {
                            "fixableByTooling": 1,
                            "strategyFallbackSuggested": 1,
                        },
                        "rewards": {"outcomeReward": 0.0},
                        "nextActions": ["Refresh divergent paper candidate data."],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_paper_bottleneck_reducer.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:30-06:00",
                        "verdict": "scenario-slate-ready",
                        "scenarioTarget": 12,
                        "counts": {"scenarios": 12, "executablePaper": 0, "shadowOnly": 12},
                        "topFiveFocus": [{"ticker": "FLNC"}, {"ticker": "THR"}],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_fast_paper_cohort.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:32-06:00",
                        "stage": "fast-paper-cohort-research-only",
                        "verdict": "no-priceable-candidates",
                        "researchOnly": True,
                        "promotable": False,
                        "brokerSubmitAllowed": False,
                        "liveTradingAllowed": False,
                        "counts": {
                            "selectedToday": 0,
                            "closedToday": 4,
                            "open": 0,
                            "closedLifetime": 24,
                        },
                        "backlogSlate": [],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_paper_mark_to_market.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:35-06:00",
                        "stage": "paper-mark-to-market-research-only",
                        "verdict": "disabled",
                        "fetchStatus": "disabled",
                        "researchOnly": True,
                        "promotable": False,
                        "openPositionCount": 2,
                        "marksByTicketId": {"ticket-1": {}, "ticket-2": {}},
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_trade_management.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:40-06:00",
                        "stage": "trade-management-research-only",
                        "verdict": "actions-recommended",
                        "researchOnly": True,
                        "promotable": False,
                        "authorityChanged": False,
                        "openPositionCount": 2,
                        "actionableCount": 1,
                        "verdictCounts": {"hold": 1, "take-profit-1": 1},
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_scenario_backtest.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:03:45-06:00",
                        "stage": "scenario-backtest-research-only",
                        "researchOnly": True,
                        "promotable": False,
                        "scenarioCount": 12,
                        "closedEvidenceCount": 4,
                        "counts": {"verdictCounts": {"insufficient-data": 10, "mixed": 2}},
                        "topFocus": [{"ticker": "FLNC"}, {"ticker": "THR"}, {"ticker": "MOD"}],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_paper_evidence_loop.json").write_text(
                json.dumps({"generatedAt": "2026-05-10T10:04:00-06:00", "verdict": "approval-bottleneck", "counts": {"remainingForPromotion": 30}, "actions": ["Convert approvals into closed scored evidence."]}),
                encoding="utf-8",
            )
            (data_dir / "inferno_performance_analytics.json").write_text(
                json.dumps({"generatedAt": "2026-05-10T10:04:00-06:00", "verdict": "evidence-building", "message": "Need more samples."}),
                encoding="utf-8",
            )
            (data_dir / "inferno_strategy_lab.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:05:00-06:00",
                        "deskVerdict": {
                            "level": "insufficient-data",
                            "message": "Need more scored tickets.",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_shadow_evidence.json").write_text(
                json.dumps({"generatedAt": "2026-05-10T10:05:00-06:00", "trackedCount": 34, "closedCount": 10}),
                encoding="utf-8",
            )
            (data_dir / "inferno_edge_research.json").write_text(
                json.dumps({"generatedAt": "2026-05-10T10:06:00-06:00", "ranked": [{"ticker": "THR"}, {"ticker": "FLR"}]}),
                encoding="utf-8",
            )
            (data_dir / "inferno_conviction_research.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:06:30-06:00",
                        "stage": "conviction-research-only",
                        "researchOnly": True,
                        "promotable": False,
                        "behemoths": [{"ticker": "NVDA"}, {"ticker": "AVGO"}],
                        "sleepers": [{"ticker": "MOD"}],
                        "nearTermWinners": [{"ticker": "MRVL"}],
                        "bestBalanced": [{"ticker": "NVDA"}, {"ticker": "MOD"}],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_math_verify.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:07:00-06:00",
                        "verdict": "clean",
                        "totalViolations": 0,
                        "missingArtifacts": 0,
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_market_mastery_plan.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:07:30-06:00",
                        "stage": "market-mastery-research-only",
                        "verdict": "research-plan-ready",
                        "researchOnly": True,
                        "promotable": False,
                        "nextActions": [
                            "M01: Restore fresh Schwab account and option truth - Refresh account data."
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_score_threshold_audit.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-10T10:08:00-06:00",
                        "stage": "score-threshold-audit-research-only",
                        "verdict": "calibrate-scores-do-not-loosen-gates",
                        "researchOnly": True,
                        "promotable": False,
                        "counts": {"thresholdsCataloged": 21, "findings": 8, "p1Findings": 4, "p2Findings": 4},
                    }
                ),
                encoding="utf-8",
            )

            patches = [
                ("ROOT", root),
                ("DATA_DIR", data_dir),
                ("REPORTS_DIR", reports_dir),
                ("COORDINATION_DIR", coordination_dir),
                ("PROMPTS_DIR", prompts_dir),
                ("MODEL_NOTES_FILE", coordination_dir / "model_notes.jsonl"),
                ("ACTIVE_MISSIONS_FILE", coordination_dir / "active_missions.json"),
                ("MODEL_COMMAND_CENTER_FILE", data_dir / "inferno_model_command_center.json"),
                ("MODEL_COMMAND_CENTER_TEXT_FILE", reports_dir / "model_command_center_latest.txt"),
                ("MODEL_COMMAND_CENTER_ONBOARD_TEXT_FILE", reports_dir / "model_command_center_onboard_latest.txt"),
                ("DEPLOY_PREFLIGHT_FILE", data_dir / "inferno_deploy_preflight.json"),
                ("OPS_MAINTENANCE_FILE", data_dir / "inferno_ops_maintenance.json"),
                ("LIVE_POSITION_REVIEW_FILE", data_dir / "inferno_live_position_review.json"),
                ("LIVE_BOOK_REVIEW_PACKET_FILE", data_dir / "inferno_live_book_review_packet.json"),
                ("WHILE_AWAY_PACKET_FILE", data_dir / "inferno_while_away_packet.json"),
                ("LIVE_ACCOUNT_SYNC_FILE", data_dir / "inferno_live_account_sync.json"),
                ("SCHWAB_ACCOUNT_SYNC_FILE", data_dir / "inferno_schwab_account_sync.json"),
                ("CAPITAL_DEPLOYMENT_READINESS_FILE", data_dir / "inferno_capital_deployment_readiness.json"),
                ("CAPITAL_SCENARIO_MATRIX_FILE", data_dir / "inferno_capital_scenario_matrix.json"),
                ("DEPOSIT_PLAN_FILE", data_dir / "inferno_deposit_plan.json"),
                ("CASH_ATTRIBUTION_FILE", data_dir / "inferno_cash_attribution.json"),
                ("TICKET_CAP_POLICY_FILE", data_dir / "inferno_ticket_cap_policy.json"),
                ("ACCOUNT_OPTIMIZATION_FILE", data_dir / "inferno_account_optimization.json"),
                ("RISK_GATE_AUDIT_FILE", data_dir / "inferno_risk_gate_audit.json"),
                ("PAPER_TEST_DIRECTOR_FILE", data_dir / "inferno_paper_test_director.json"),
                ("PAPER_BLOCKER_SWARM_FILE", data_dir / "inferno_paper_blocker_swarm.json"),
                ("PAPER_BOTTLENECK_REDUCER_FILE", data_dir / "inferno_paper_bottleneck_reducer.json"),
                ("FAST_PAPER_COHORT_FILE", data_dir / "inferno_fast_paper_cohort.json"),
                ("PAPER_MTM_FILE", data_dir / "inferno_paper_mark_to_market.json"),
                ("TRADE_MANAGEMENT_FILE", data_dir / "inferno_trade_management.json"),
                ("SCENARIO_BACKTEST_FILE", data_dir / "inferno_scenario_backtest.json"),
                ("PAPER_EVIDENCE_LOOP_FILE", data_dir / "inferno_paper_evidence_loop.json"),
                ("PERFORMANCE_ANALYTICS_FILE", data_dir / "inferno_performance_analytics.json"),
                ("STRATEGY_LAB_FILE", data_dir / "inferno_strategy_lab.json"),
                ("SHADOW_EVIDENCE_FILE", data_dir / "inferno_shadow_evidence.json"),
                ("EDGE_RESEARCH_FILE", data_dir / "inferno_edge_research.json"),
                ("CONVICTION_RESEARCH_FILE", data_dir / "inferno_conviction_research.json"),
                ("MATH_VERIFY_FILE", data_dir / "inferno_math_verify.json"),
                ("MARKET_MASTERY_PLAN_FILE", data_dir / "inferno_market_mastery_plan.json"),
                ("SCORE_THRESHOLD_AUDIT_FILE", data_dir / "inferno_score_threshold_audit.json"),
                ("STRATEGY_ALTERNATIVE_SCORER_FILE", data_dir / "inferno_strategy_alternative_scorer.json"),
                ("STRATEGY_ALTERNATIVE_PRICING_FILE", data_dir / "inferno_strategy_alternative_pricing.json"),
                ("STRATEGY_SHADOW_COMPARISON_FILE", data_dir / "inferno_strategy_shadow_comparison.json"),
                ("EXPECTANCY_LEDGER_FILE", data_dir / "inferno_expectancy_ledger.json"),
                ("DTE_POLICY_ANALYSIS_FILE", data_dir / "inferno_dte_policy_analysis.json"),
                ("TRADING_BEHAVIOR_AUDIT_FILE", data_dir / "inferno_trading_behavior_audit.json"),
                ("PROCESS_COMPLIANCE_FILE", data_dir / "inferno_process_compliance.json"),
                ("PORTFOLIO_HEAT_FILE", data_dir / "inferno_portfolio_heat.json"),
                ("WHEEL_SHADOW_FILE", data_dir / "inferno_wheel_shadow.json"),
            ]
            with ExitStack() as stack:
                for name, value in patches:
                    stack.enter_context(patch.object(command_center, name, value))
                payload = command_center.build_command_center()

            self.assertEqual(payload["systemStatus"]["deployPreflight"]["verdict"], "ready-for-pilot")
            self.assertEqual(payload["headlineMetrics"]["liveFragile"], 1)
            self.assertEqual(payload["headlineMetrics"]["liveBookHardBlockers"], 1)
            self.assertEqual(payload["headlineMetrics"]["liveBookWarnings"], 1)
            self.assertEqual(payload["headlineMetrics"]["whileAwayVerdict"], "monitor-only")
            self.assertEqual(payload["headlineMetrics"]["paperAutoSelected"], 2)
            self.assertEqual(payload["headlineMetrics"]["paperApprovalOnly"], 1)
            self.assertEqual(payload["headlineMetrics"]["paperConstructionWatch"], 3)
            self.assertEqual(payload["headlineMetrics"]["paperBlockerSwarmVerdict"], "fixable-blockers-present")
            self.assertEqual(payload["headlineMetrics"]["paperBlockerSwarmDominantLane"], "data_freshness")
            self.assertEqual(payload["headlineMetrics"]["paperBlockerSwarmFixableByTooling"], 1)
            self.assertEqual(payload["headlineMetrics"]["paperBlockerSwarmFallbacks"], 1)
            self.assertEqual(payload["headlineMetrics"]["paperScenarioCount"], 12)
            self.assertEqual(payload["headlineMetrics"]["paperMtmFetchStatus"], "disabled")
            self.assertEqual(payload["headlineMetrics"]["paperMtmOpenPositions"], 2)
            self.assertEqual(payload["headlineMetrics"]["paperMtmMarkedTickets"], 2)
            self.assertEqual(payload["headlineMetrics"]["tradeManagementVerdict"], "actions-recommended")
            self.assertEqual(payload["headlineMetrics"]["tradeManagementActionable"], 1)
            self.assertEqual(payload["headlineMetrics"]["paperScenarioTopFive"], ["FLNC", "THR"])
            self.assertEqual(payload["headlineMetrics"]["scenarioClosedEvidenceCount"], 4)
            self.assertEqual(payload["headlineMetrics"]["scenarioBacktestTopFocus"], ["FLNC", "THR", "MOD"])
            self.assertEqual(payload["headlineMetrics"]["edgeRanked"], 2)
            self.assertEqual(payload["headlineMetrics"]["convictionBehemoths"], ["NVDA", "AVGO"])
            self.assertEqual(payload["headlineMetrics"]["convictionSleepers"], ["MOD"])
            self.assertEqual(payload["headlineMetrics"]["convictionNearTermWinners"], ["MRVL"])
            self.assertEqual(payload["headlineMetrics"]["convictionBestBalanced"], ["NVDA", "MOD"])
            self.assertEqual(payload["headlineMetrics"]["capitalDeploymentVerdict"], "manual-ready-with-warnings")
            self.assertFalse(payload["headlineMetrics"]["autoLiveAllowed"])
            self.assertEqual(payload["systemStatus"]["capitalScenarioMatrix"]["verdict"], "all-blocked")
            self.assertEqual(payload["systemStatus"]["depositPlan"]["verdict"], "configured")
            self.assertEqual(payload["systemStatus"]["cashAttribution"]["verdict"], "attribution-incomplete")
            self.assertEqual(payload["systemStatus"]["ticketCapPolicy"]["verdict"], "active")
            self.assertEqual(payload["headlineMetrics"]["depositAmountDollars"], 250.0)
            self.assertEqual(payload["headlineMetrics"]["depositNextDate"], "2026-05-15")
            self.assertEqual(payload["headlineMetrics"]["depositForecast30Days"], 500.0)
            self.assertEqual(payload["headlineMetrics"]["cashAttributionLatestDelta"], -250.0)
            self.assertFalse(payload["headlineMetrics"]["cashAttributionRealizedOptionsKnown"])
            self.assertEqual(payload["headlineMetrics"]["ticketCapConstructionHardCap"], 500.0)
            self.assertEqual(payload["headlineMetrics"]["ticketCapHardCap"], 500.0)
            self.assertEqual(payload["headlineMetrics"]["ticketCapLiveHardCap"], 0.0)
            self.assertEqual(payload["headlineMetrics"]["ticketCapLiveDrawdownLevel"], "pause")
            self.assertEqual(payload["headlineMetrics"]["ticketCapCallPosture"], "aggressive-defined-risk")
            self.assertTrue(payload["headlineMetrics"]["ticketCapAggressiveCalls"])
            self.assertEqual(payload["headlineMetrics"]["riskGateVerdict"], "blocked")
            self.assertEqual(payload["headlineMetrics"]["riskGateHardFails"], 1)
            self.assertEqual(payload["headlineMetrics"]["mathVerifyVerdict"], "clean")
            self.assertEqual(payload["headlineMetrics"]["mathViolations"], 0)
            self.assertEqual(payload["systemStatus"]["mathVerify"]["verdict"], "clean")
            self.assertEqual(payload["systemStatus"]["marketMasteryPlan"]["verdict"], "research-plan-ready")
            self.assertEqual(payload["systemStatus"]["scoreThresholdAudit"]["verdict"], "calibrate-scores-do-not-loosen-gates")
            self.assertEqual(payload["headlineMetrics"]["scoreThresholdAuditVerdict"], "calibrate-scores-do-not-loosen-gates")
            self.assertEqual(payload["headlineMetrics"]["scoreThresholdAuditCounts"]["thresholdsCataloged"], 21)
            self.assertEqual(payload["systemStatus"]["strategyLab"]["verdict"], "insufficient-data")
            self.assertEqual(payload["systemStatus"]["schwabAccountSync"]["verdict"], "healthy")
            self.assertEqual(payload["headlineMetrics"]["accountDataSource"], "schwab-account-api")
            self.assertEqual(payload["headlineMetrics"]["accountNetLiquidatingValue"], 1000.0)
            self.assertEqual(payload["headlineMetrics"]["accountTotalCash"], 0.0)
            self.assertTrue(payload["executiveSummary"][0].startswith("Capital:"))
            self.assertEqual(payload["controlSurface"]["entrypoint"], "./inferno")
            self.assertIn("./inferno sync", {item["command"] for item in payload["controlSurface"]["commands"]})
            self.assertIn("./inferno usage", {item["command"] for item in payload["controlSurface"]["commands"]})
            self.assertIn("./inferno preflight", {item["command"] for item in payload["controlSurface"]["commands"]})
            self.assertIn("./inferno oauth", {item["command"] for item in payload["controlSurface"]["commands"]})
            self.assertIn("./inferno action-pulse", {item["command"] for item in payload["controlSurface"]["commands"]})
            self.assertIn("./inferno deposit-plan", {item["command"] for item in payload["controlSurface"]["commands"]})
            self.assertIn("./inferno cash-ledger", {item["command"] for item in payload["controlSurface"]["commands"]})
            self.assertIn("./inferno ticket-cap", {item["command"] for item in payload["controlSurface"]["commands"]})
            self.assertIn("./inferno daily-ops", {item["command"] for item in payload["controlSurface"]["commands"]})
            self.assertIn("./inferno capital-check", {item["command"] for item in payload["controlSurface"]["commands"]})
            self.assertIn("./inferno strike-cycle", {item["command"] for item in payload["controlSurface"]["commands"]})
            self.assertIn("./inferno approvals", {item["command"] for item in payload["controlSurface"]["commands"]})
            self.assertEqual(payload["reportingMap"][0]["lane"], "handoff")
            self.assertEqual(payload["reportingMap"][1]["lane"], "health")
            self.assertIn("reports/usage_optimizer_latest.txt", payload["recommendedReads"][0])
            self.assertIn("reports/model_command_center_onboard_latest.txt", payload["recommendedReads"][1])
            self.assertIn("reports/while_away_latest.txt", "\n".join(payload["recommendedReads"]))
            self.assertIn("reports/paper_blocker_swarm_latest.txt", "\n".join(payload["recommendedReads"]))
            self.assertIn("reports/paper_mark_to_market_latest.txt", "\n".join(payload["recommendedReads"]))
            self.assertIn("reports/trade_management_latest.txt", "\n".join(payload["recommendedReads"]))
            self.assertEqual(len(payload["activeMissions"]), 1)
            self.assertEqual(len(payload["recentNotes"]), 1)
            self.assertIn("Manual risk review: GDS.", payload["nextActions"])
            self.assertIn("Resolve GDS before sizing new capital.", payload["nextActions"])
            self.assertIn("Refresh divergent paper candidate data.", payload["nextActions"])
            self.assertNotIn(
                "Close and score the 4 fast-paper simulations at the first eligible later-session quote, then open the next diversified cohort.",
                payload["nextActions"],
            )
            self.assertIn(
                "Fast-paper due simulations are closed; wait for market-open refresh to find new priceable candidates.",
                payload["nextActions"],
            )
            self.assertTrue(payload["nextActions"][0].startswith("M01:"))
            text_report = (reports_dir / "model_command_center_latest.txt").read_text(encoding="utf-8")
            onboard_report = (reports_dir / "model_command_center_onboard_latest.txt").read_text(encoding="utf-8")
            self.assertIn("Inferno Model Command Center", text_report)
            self.assertIn("Unified control surface: ./inferno", text_report)
            self.assertIn("./inferno sync", text_report)
            self.assertIn("Deploy preflight: ready-for-pilot", text_report)
            self.assertIn("Schwab account sync: healthy", text_report)
            self.assertIn("Account source: schwab-account-api", text_report)
            self.assertIn("Account cash: 0.0", text_report)
            self.assertIn("Live book review packet: blocked", text_report)
            self.assertIn("While away packet: monitor-only", text_report)
            self.assertIn("Capital deployment readiness: manual-ready-with-warnings", text_report)
            self.assertIn("Capital scenario matrix: all-blocked", text_report)
            self.assertIn("Deposit plan: configured", text_report)
            self.assertIn("Cash attribution: attribution-incomplete", text_report)
            self.assertIn("Ticket cap policy: active", text_report)
            self.assertIn("call posture aggressive-defined-risk", text_report)
            self.assertIn("Risk gate audit: blocked", text_report)
            self.assertIn("Executive summary:", text_report)
            self.assertIn("Paper blocker swarm: fixable-blockers-present", text_report)
            self.assertIn("dominant data_freshness", text_report)
            self.assertIn("Paper bottleneck reducer: scenario-slate-ready", text_report)
            self.assertIn("Paper mark-to-market: disabled", text_report)
            self.assertIn("Paper MTM: disabled | open 2 | marked 2", text_report)
            self.assertIn("Trade management: actions-recommended", text_report)
            self.assertIn("actionable 1", text_report)
            self.assertIn("Scenario backtest: scenario-backtest-research-only", text_report)
            self.assertIn("Paper scenarios: 12", text_report)
            self.assertIn("Paper top five: FLNC, THR", text_report)
            self.assertIn("Fast paper: no-priceable-candidates | opened 0 | closed 4 | open 0", text_report)
            self.assertNotIn("Close and score the 4 fast-paper simulations", text_report)
            self.assertIn("Fast-paper due simulations are closed; wait for market-open refresh", text_report)
            self.assertIn("Scenario backtest evidence: 4", text_report)
            self.assertIn("Scenario backtest focus: FLNC, THR, MOD", text_report)
            self.assertIn("Math verify: clean", text_report)
            self.assertIn("Market mastery plan: research-plan-ready", text_report)
            self.assertIn("Score threshold audit: calibrate-scores-do-not-loosen-gates", text_report)
            self.assertIn("Math violations: 0", text_report)
            self.assertIn("Canonical report map:", text_report)
            self.assertIn("reports/paper_bottleneck_reducer_latest.csv", text_report)
            self.assertIn("reports/scenario_backtest_latest.txt", text_report)
            self.assertIn("reports/math_verify_latest.txt", text_report)
            self.assertIn("reports/usage_optimizer_latest.txt", text_report)
            self.assertIn("reports/while_away_latest.txt", text_report)
            self.assertIn("reports/capital_scenario_matrix_latest.txt", text_report)
            self.assertIn("reports/deposit_plan_latest.txt", text_report)
            self.assertIn("reports/cash_attribution_latest.txt", text_report)
            self.assertIn("reports/ticket_cap_policy_latest.txt", text_report)
            self.assertIn("reports/paper_blocker_swarm_latest.txt", text_report)
            self.assertIn("reports/paper_mark_to_market_latest.txt", text_report)
            self.assertIn("reports/trade_management_latest.txt", text_report)
            self.assertIn("reports/conviction_research_latest.txt", text_report)
            self.assertIn("reports/market_mastery_next_actions_latest.txt", text_report)
            self.assertIn("Conviction giants: NVDA, AVGO", text_report)
            self.assertIn("Conviction balanced: NVDA, MOD", text_report)

            digest = command_center.onboard_digest(payload)
            self.assertIn("reports/usage_optimizer_latest.txt", digest)
            self.assertIn("reports/model_command_center_onboard_latest.txt", digest)
            self.assertIn("reports/central_command_latest.txt", digest)
            self.assertEqual(onboard_report, digest)

    def test_active_market_mastery_actions_skip_resolved_tasks(self) -> None:
        actions = command_center.active_market_mastery_actions(
            {
                "tasks": [
                    {
                        "id": "M01",
                        "title": "Restore fresh Schwab truth",
                        "status": "ready",
                        "action": "Refresh account/options/price history.",
                    },
                    {
                        "id": "M02",
                        "title": "Close due paper positions",
                        "status": "clear",
                        "action": "Resolve close-now paper positions.",
                    },
                    {
                        "id": "M03",
                        "title": "Fix stale command-center source",
                        "status": "action-now",
                        "action": "Prefer Schwab account truth over stale TOS statements.",
                    },
                    {
                        "id": "M04",
                        "title": "Decision card",
                        "status": "implemented",
                        "action": "Keep the current card.",
                    },
                    {
                        "id": "M05",
                        "title": "Research-only strategy check",
                        "status": "build-next",
                        "action": "Make the backtest reproducible before promotion.",
                    },
                ]
            }
        )

        self.assertEqual(
            actions,
            [
                "M03: Fix stale command-center source - Prefer Schwab account truth over stale TOS statements.",
                "M05: Research-only strategy check - Make the backtest reproducible before promotion.",
            ],
        )

    def test_active_market_mastery_actions_falls_back_to_legacy_next_actions(self) -> None:
        actions = command_center.active_market_mastery_actions(
            {"nextActions": ["legacy one", "legacy two", "legacy three"]},
            limit=2,
        )

        self.assertEqual(actions, ["legacy one", "legacy two"])

    def test_account_headline_prefers_healthy_schwab_over_tos_statement(self) -> None:
        metrics = command_center.account_headline_metrics(
            {
                "accountDataSource": "tos-account-statement",
                "netLiquidatingValue": "$1,108.08",
                "totalCash": "$167.88",
            },
            {
                "verdict": "healthy",
                "brokerReadOnly": True,
                "netLiquidatingValue": 767.31,
                "totalCash": 0.0,
            },
        )

        self.assertEqual(metrics["accountDataSource"], "schwab-account-api")
        self.assertEqual(metrics["accountNetLiquidatingValue"], 767.31)
        self.assertEqual(metrics["accountTotalCash"], 0.0)

    def test_account_headline_keeps_live_sync_when_already_schwab_sourced(self) -> None:
        metrics = command_center.account_headline_metrics(
            {
                "accountDataSource": "schwab-account-api",
                "netLiquidatingValue": 1000.0,
                "totalCash": 0.0,
            },
            {
                "verdict": "healthy",
                "brokerReadOnly": True,
                "netLiquidatingValue": 999.0,
                "totalCash": 200.0,
            },
        )

        self.assertEqual(metrics["accountDataSource"], "schwab-account-api")
        self.assertEqual(metrics["accountNetLiquidatingValue"], 1000.0)
        self.assertEqual(metrics["accountTotalCash"], 0.0)

    def test_note_and_mission_helpers_persist_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            coordination_dir = root / "coordination"
            prompts_dir = coordination_dir / "prompts"
            data_dir = root / "data"
            reports_dir = root / "reports"
            for path in (coordination_dir, prompts_dir, data_dir, reports_dir):
                path.mkdir(parents=True, exist_ok=True)

            patches = [
                ("ROOT", root),
                ("DATA_DIR", data_dir),
                ("REPORTS_DIR", reports_dir),
                ("COORDINATION_DIR", coordination_dir),
                ("PROMPTS_DIR", prompts_dir),
                ("MODEL_NOTES_FILE", coordination_dir / "model_notes.jsonl"),
                ("ACTIVE_MISSIONS_FILE", coordination_dir / "active_missions.json"),
                ("MODEL_COMMAND_CENTER_FILE", data_dir / "inferno_model_command_center.json"),
                ("MODEL_COMMAND_CENTER_TEXT_FILE", reports_dir / "model_command_center_latest.txt"),
                ("MODEL_COMMAND_CENTER_ONBOARD_TEXT_FILE", reports_dir / "model_command_center_onboard_latest.txt"),
            ]
            with ExitStack() as stack:
                for name, value in patches:
                    stack.enter_context(patch.object(command_center, name, value))
                command_center.ensure_command_center_dirs()
                note = command_center.append_note(author="claude", title="Checkpoint", body="Read the repo.", tags=["handoff"])
                mission = command_center.add_mission(title="Next step", body="Wire the dashboard.", owner="shared", tags=["ui"])
                updated = command_center.update_mission(mission["id"], status="in-progress", owner="codex")

            self.assertEqual(note["author"], "claude")
            self.assertEqual(updated["status"], "in-progress")
            self.assertEqual(updated["owner"], "codex")
            missions = json.loads((coordination_dir / "active_missions.json").read_text(encoding="utf-8"))
            self.assertEqual(len(missions), 1)
            self.assertEqual(missions[0]["status"], "in-progress")


if __name__ == "__main__":
    unittest.main()
