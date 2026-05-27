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
                json.dumps({"generatedAt": "2026-05-10T10:02:00-06:00", "verdict": "healthy", "message": "", "matchedSuffix": "1234", "accountDataSource": "schwab-account-api", "netLiquidatingValue": 1000.0, "totalCash": 200.0}),
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
                json.dumps({"generatedAt": "2026-05-10T10:03:00-06:00", "verdict": "auto-paper-selected", "counts": {"stageableNow": 0, "autoPaperSelected": 2, "approvalOnly": 1}, "nextActions": ["Stage FLNC in paper only."]}),
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
                ("DEPLOY_PREFLIGHT_FILE", data_dir / "inferno_deploy_preflight.json"),
                ("OPS_MAINTENANCE_FILE", data_dir / "inferno_ops_maintenance.json"),
                ("LIVE_POSITION_REVIEW_FILE", data_dir / "inferno_live_position_review.json"),
                ("LIVE_BOOK_REVIEW_PACKET_FILE", data_dir / "inferno_live_book_review_packet.json"),
                ("WHILE_AWAY_PACKET_FILE", data_dir / "inferno_while_away_packet.json"),
                ("LIVE_ACCOUNT_SYNC_FILE", data_dir / "inferno_live_account_sync.json"),
                ("SCHWAB_ACCOUNT_SYNC_FILE", data_dir / "inferno_schwab_account_sync.json"),
                ("CAPITAL_DEPLOYMENT_READINESS_FILE", data_dir / "inferno_capital_deployment_readiness.json"),
                ("RISK_GATE_AUDIT_FILE", data_dir / "inferno_risk_gate_audit.json"),
                ("PAPER_TEST_DIRECTOR_FILE", data_dir / "inferno_paper_test_director.json"),
                ("PAPER_BOTTLENECK_REDUCER_FILE", data_dir / "inferno_paper_bottleneck_reducer.json"),
                ("PAPER_MTM_FILE", data_dir / "inferno_paper_mark_to_market.json"),
                ("SCENARIO_BACKTEST_FILE", data_dir / "inferno_scenario_backtest.json"),
                ("PAPER_EVIDENCE_LOOP_FILE", data_dir / "inferno_paper_evidence_loop.json"),
                ("PERFORMANCE_ANALYTICS_FILE", data_dir / "inferno_performance_analytics.json"),
                ("STRATEGY_LAB_FILE", data_dir / "inferno_strategy_lab.json"),
                ("SHADOW_EVIDENCE_FILE", data_dir / "inferno_shadow_evidence.json"),
                ("EDGE_RESEARCH_FILE", data_dir / "inferno_edge_research.json"),
                ("CONVICTION_RESEARCH_FILE", data_dir / "inferno_conviction_research.json"),
                ("MATH_VERIFY_FILE", data_dir / "inferno_math_verify.json"),
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
            self.assertEqual(payload["headlineMetrics"]["paperScenarioCount"], 12)
            self.assertEqual(payload["headlineMetrics"]["paperMtmFetchStatus"], "disabled")
            self.assertEqual(payload["headlineMetrics"]["paperMtmOpenPositions"], 2)
            self.assertEqual(payload["headlineMetrics"]["paperMtmMarkedTickets"], 2)
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
            self.assertEqual(payload["headlineMetrics"]["riskGateVerdict"], "blocked")
            self.assertEqual(payload["headlineMetrics"]["riskGateHardFails"], 1)
            self.assertEqual(payload["headlineMetrics"]["mathVerifyVerdict"], "clean")
            self.assertEqual(payload["headlineMetrics"]["mathViolations"], 0)
            self.assertEqual(payload["systemStatus"]["mathVerify"]["verdict"], "clean")
            self.assertEqual(payload["systemStatus"]["strategyLab"]["verdict"], "insufficient-data")
            self.assertEqual(payload["systemStatus"]["schwabAccountSync"]["verdict"], "healthy")
            self.assertEqual(payload["headlineMetrics"]["accountDataSource"], "schwab-account-api")
            self.assertEqual(payload["headlineMetrics"]["accountNetLiquidatingValue"], 1000.0)
            self.assertTrue(payload["executiveSummary"][0].startswith("Capital:"))
            self.assertEqual(payload["reportingMap"][0]["lane"], "handoff")
            self.assertEqual(payload["reportingMap"][1]["lane"], "health")
            self.assertIn("reports/usage_optimizer_latest.txt", payload["recommendedReads"][0])
            self.assertIn("reports/while_away_latest.txt", "\n".join(payload["recommendedReads"]))
            self.assertIn("reports/paper_mark_to_market_latest.txt", "\n".join(payload["recommendedReads"]))
            self.assertEqual(len(payload["activeMissions"]), 1)
            self.assertEqual(len(payload["recentNotes"]), 1)
            self.assertIn("Manual risk review: GDS.", payload["nextActions"])
            self.assertIn("Resolve GDS before sizing new capital.", payload["nextActions"])
            text_report = (reports_dir / "model_command_center_latest.txt").read_text(encoding="utf-8")
            self.assertIn("Inferno Model Command Center", text_report)
            self.assertIn("Deploy preflight: ready-for-pilot", text_report)
            self.assertIn("Schwab account sync: healthy", text_report)
            self.assertIn("Account source: schwab-account-api", text_report)
            self.assertIn("Live book review packet: blocked", text_report)
            self.assertIn("While away packet: monitor-only", text_report)
            self.assertIn("Capital deployment readiness: manual-ready-with-warnings", text_report)
            self.assertIn("Risk gate audit: blocked", text_report)
            self.assertIn("Executive summary:", text_report)
            self.assertIn("Paper bottleneck reducer: scenario-slate-ready", text_report)
            self.assertIn("Paper mark-to-market: disabled", text_report)
            self.assertIn("Paper MTM: disabled | open 2 | marked 2", text_report)
            self.assertIn("Scenario backtest: scenario-backtest-research-only", text_report)
            self.assertIn("Paper scenarios: 12", text_report)
            self.assertIn("Paper top five: FLNC, THR", text_report)
            self.assertIn("Scenario backtest evidence: 4", text_report)
            self.assertIn("Scenario backtest focus: FLNC, THR, MOD", text_report)
            self.assertIn("Math verify: clean", text_report)
            self.assertIn("Math violations: 0", text_report)
            self.assertIn("Canonical report map:", text_report)
            self.assertIn("reports/paper_bottleneck_reducer_latest.csv", text_report)
            self.assertIn("reports/scenario_backtest_latest.txt", text_report)
            self.assertIn("reports/math_verify_latest.txt", text_report)
            self.assertIn("reports/usage_optimizer_latest.txt", text_report)
            self.assertIn("reports/while_away_latest.txt", text_report)
            self.assertIn("reports/paper_mark_to_market_latest.txt", text_report)
            self.assertIn("reports/conviction_research_latest.txt", text_report)
            self.assertIn("Conviction giants: NVDA, AVGO", text_report)
            self.assertIn("Conviction balanced: NVDA, MOD", text_report)

            digest = command_center.onboard_digest(payload)
            self.assertIn("reports/usage_optimizer_latest.txt", digest)
            self.assertIn("reports/central_command_latest.txt", digest)

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
