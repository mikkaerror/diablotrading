from __future__ import annotations

"""Regression tests for the while-away operator packet."""

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import inferno_while_away_packet as wap


class InfernoWhileAwayPacketTests(unittest.TestCase):
    """Protect the travel-mode packet's safety and anti-double-count contract."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.reports = self.root / "reports"
        self.data.mkdir()
        self.reports.mkdir()

        patches = [
            ("ROOT", self.root),
            ("WHILE_AWAY_PACKET_FILE", self.data / "inferno_while_away_packet.json"),
            ("WHILE_AWAY_PACKET_TEXT_FILE", self.reports / "while_away_latest.txt"),
            ("SCHWAB_ACCOUNT_SYNC_FILE", self.data / "inferno_schwab_account_sync.json"),
            ("LIVE_ACCOUNT_SYNC_FILE", self.data / "inferno_live_account_sync.json"),
            ("LIVE_POSITION_REVIEW_FILE", self.data / "inferno_live_position_review.json"),
            ("LIVE_BOOK_REVIEW_PACKET_FILE", self.data / "inferno_live_book_review_packet.json"),
            ("CAPITAL_DEPLOYMENT_READINESS_FILE", self.data / "inferno_capital_deployment_readiness.json"),
            ("RISK_GATE_AUDIT_FILE", self.data / "inferno_risk_gate_audit.json"),
            ("TOS_METRIC_THEORY_AUDIT_FILE", self.data / "inferno_tos_metric_theory_audit.json"),
            ("SCHWAB_TOS_METRICS_SYNC_FILE", self.data / "inferno_schwab_tos_metrics_sync.json"),
            ("PAPER_TEST_DIRECTOR_FILE", self.data / "inferno_paper_test_director.json"),
            ("PAPER_MTM_FILE", self.data / "inferno_paper_mark_to_market.json"),
            ("STRATEGY_SHADOW_COMPARISON_FILE", self.data / "inferno_strategy_shadow_comparison.json"),
            ("CAPITAL_SCALING_FILE", self.data / "inferno_capital_scaling.json"),
        ]
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in patches:
            self.stack.enter_context(patch.object(wap, name, value))

    def write_json(self, name: str, payload: dict[str, object]) -> None:
        (self.data / name).write_text(json.dumps(payload), encoding="utf-8")

    def seed_common_artifacts(
        self,
        *,
        hard_blockers: int = 1,
        capital_verdict: str = "not-ready",
        risk_verdict: str = "blocked",
        manual_allowed: bool = False,
    ) -> None:
        self.write_json(
            "inferno_schwab_account_sync.json",
            {
                "verdict": "healthy",
                "matchedSuffix": "8499",
                "netLiquidatingValue": 1224.66,
                "totalCash": 167.88,
                "counts": {"positions": 4},
            },
        )
        self.write_json(
            "inferno_live_account_sync.json",
            {
                "verdict": "attention" if hard_blockers else "healthy",
                "accountDataSource": "schwab-account-api",
                "matchedSuffix": "8499",
                "netLiquidatingValue": 1224.66,
                "totalCash": 167.88,
            },
        )
        self.write_json(
            "inferno_live_position_review.json",
            {"verdict": "review", "counts": {"fragile": hard_blockers}},
        )
        self.write_json(
            "inferno_live_book_review_packet.json",
            {
                "verdict": "blocked" if hard_blockers else "clear",
                "counts": {"positions": 1, "hardBlockers": hard_blockers, "warnings": 0, "supported": 0 if hard_blockers else 1},
                "unlockChecklist": ["Resolve TE before sizing new capital."] if hard_blockers else [],
                "positions": [
                    {
                        "symbol": "TE",
                        "unlockEffect": "hard-blocks-new-capital" if hard_blockers else "does-not-block",
                        "posture": "fragile" if hard_blockers else "supported",
                        "reviewHeat": 100 if hard_blockers else 10,
                        "math": {
                            "weightPct": 35.99,
                            "plCushionPct": 32.5,
                            "supportCushionPct": 58.35,
                            "resistanceHeadroomPct": -14.43,
                        },
                        "reviewPrompts": ["Decide whether TE still deserves to exist before adding exposure."],
                    }
                ],
            },
        )
        self.write_json(
            "inferno_capital_deployment_readiness.json",
            {
                "verdict": capital_verdict,
                "deploymentDate": "2026-05-27",
                "manualDeploymentAllowed": manual_allowed,
                "autoLiveAllowed": False,
                "guardrails": {
                    "deployableCash": 167.88,
                    "maxOptionsRisk": 41.97,
                    "maxStarterTicket": 41.97,
                    "maxLongTermBuy": 67.15,
                    "reserveCash": 58.76,
                },
                "blockers": ["Live position review has fragile holding(s)."] if hard_blockers else [],
                "warnings": ["Paper evidence still needs 30 closed outcomes."],
            },
        )
        self.write_json(
            "inferno_risk_gate_audit.json",
            {
                "verdict": risk_verdict,
                "summary": {
                    "hardFails": 1 if risk_verdict == "blocked" else 0,
                    "promotionFails": 2,
                    "warnings": 1,
                    "blockedGateIds": ["live-position-fragility"] if risk_verdict == "blocked" else [],
                },
                "gates": [
                    {
                        "id": "live-position-fragility",
                        "name": "Live position fragility",
                        "severity": "hard",
                        "status": "fail" if risk_verdict == "blocked" else "pass",
                        "detail": "fragile=1" if risk_verdict == "blocked" else "fragile=0",
                        "nextAction": "Resolve fragile live holdings.",
                    }
                ],
            },
        )
        self.write_json(
            "inferno_schwab_tos_metrics_sync.json",
            {
                "sourceStatus": "ok",
                "customMetricsVerdict": "custom-metrics-accounted",
                "metricValueCount": 72,
            },
        )
        self.write_json(
            "inferno_tos_metric_theory_audit.json",
            {
                "verdict": "formula-policy-needs-review",
                "postureCounts": {"supports-thesis": 4, "challenges-thesis": 3},
                "formulaTheory": {
                    "tos_momentum": {
                        "theoryVerdict": "revise-before-ranking",
                        "decisionRole": "short-term directional impulse",
                        "preferredCompanion": "momentumPct and momentumAtrMultiple",
                    }
                },
                "redundancy": {
                    "highCorrelationPairs": [
                        {"left": "rvolTos", "right": "rvolPrior30", "spearman": 1.0},
                        {"left": "strengthLatest", "right": "closeLocation5d", "spearman": 0.82},
                    ]
                },
                "nextActions": ["Do not double-count highly correlated companion features."],
            },
        )
        self.write_json(
            "inferno_paper_test_director.json",
            {
                "verdict": "auto-paper-selected",
                "counts": {"remainingForPromotion": 30, "autoPaperSelected": 1},
            },
        )
        self.write_json(
            "inferno_paper_mark_to_market.json",
            {
                "generatedAt": "2026-05-27T04:00:00+00:00",
                "verdict": "disabled",
                "fetchStatus": "disabled",
                "openPositionCount": 2,
                "marksByTicketId": {"ticket-1": {}, "ticket-2": {}},
            },
        )
        self.write_json(
            "inferno_strategy_shadow_comparison.json",
            {
                "verdict": "shadow-compare-ready",
                "paperStageAllowed": 0,
                "counts": {"trackedCondors": 3},
                "register": [
                    {
                        "ticker": "MRVL",
                        "registerStatus": "shadow-compare-open",
                        "bestPassingVariant": {
                            "strategy": "IRON_CONDOR",
                            "plan": {"expiration": "2026-06-18"},
                        },
                    }
                ],
            },
        )
        self.write_json("inferno_capital_scaling.json", {"verdict": "ack-required"})

    def test_monitor_only_packet_keeps_travel_window_read_only(self) -> None:
        self.seed_common_artifacts()

        packet = wap.build_while_away_packet()
        rendered = wap.render_while_away_packet(packet)

        self.assertEqual(packet["verdict"], "monitor-only")
        self.assertTrue(packet["researchOnly"])
        self.assertFalse(packet["promotable"])
        self.assertFalse(packet["authority"]["brokerSubmitAllowed"])
        self.assertFalse(packet["authority"]["touchesBrokerOrders"])
        self.assertEqual(packet["account"]["source"], "schwab-account-api")
        self.assertEqual(packet["capital"]["maxOptionsRisk"], 41.97)
        self.assertEqual(packet["paperEvidence"]["markToMarket"]["fetchStatus"], "disabled")
        self.assertEqual(packet["paperEvidence"]["markToMarket"]["markedTickets"], 2)
        self.assertEqual(packet["liveBook"]["topPositions"][0]["symbol"], "TE")
        self.assertIn("No automated broker submit.", packet["operatorActions"]["blocked"])
        self.assertIn("monitor-only", rendered)
        self.assertIn("Paper MTM: disabled | open 2 | marked 2", rendered)
        self.assertIn("Do not double-count rvolTos + rvolPrior30", rendered)
        self.assertTrue((self.reports / "while_away_latest.txt").exists())

    def test_clean_manual_state_is_manual_review_ready_not_auto_live(self) -> None:
        self.seed_common_artifacts(
            hard_blockers=0,
            capital_verdict="manual-ready",
            risk_verdict="clear",
            manual_allowed=True,
        )

        packet = wap.build_while_away_packet()

        self.assertEqual(packet["verdict"], "manual-review-ready")
        self.assertTrue(packet["capital"]["manualDeploymentAllowed"])
        self.assertFalse(packet["capital"]["autoLiveAllowed"])
        self.assertIn(
            "Consider manual orders only after a fresh capital-readiness rerun and explicit final confirmation.",
            packet["operatorActions"]["allowed"],
        )


if __name__ == "__main__":
    unittest.main()
