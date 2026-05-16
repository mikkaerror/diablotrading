from __future__ import annotations

"""Regression tests for the data-trust and next-week readiness auditor."""

import unittest
from datetime import timedelta
from unittest.mock import patch

from inferno_data_readiness_audit import build_audit
from inferno_config import local_now


class InfernoDataReadinessAuditTests(unittest.TestCase):
    """Verify trust tiers and readiness verdicts stay honest."""

    @patch("inferno_data_readiness_audit.load_json_file")
    def test_audit_marks_daily_prep_ready_when_core_artifacts_are_fresh(self, mock_load_json_file) -> None:
        now = local_now()
        snapshot_at = now.isoformat()
        market_context_at = (now + timedelta(seconds=1)).isoformat()
        queue_at = (now + timedelta(seconds=2)).isoformat()
        strike_at = (now + timedelta(minutes=5)).isoformat()
        snapshot = {
            "generatedAt": snapshot_at,
            "rows": [
                {
                    "ticker": "NVDA",
                    "daysUntilEarnings": 9,
                    "atrPercent": 4.2,
                    "atrZScore": 1.1,
                    "atr20Day": 12.4,
                    "ivRank": 44,
                    "ivRankChange": 0.18,
                }
            ],
        }
        market_context = {
            "generatedAt": market_context_at,
            "populatedRows": 1,
            "totalRows": 1,
            "averageRvol": 1.31,
        }
        execution_queue = {"generatedAt": queue_at, "count": 1}
        strike_plan = {"generatedAt": strike_at, "count": 1, "liveTradingAllowed": False}
        export_verifier = {"verdict": "manual-check"}
        session_probe = {"ok": False, "summary": "no visible thinkorswim window detected"}
        mock_load_json_file.side_effect = [
            snapshot,
            execution_queue,
            strike_plan,
            market_context,
            export_verifier,
            session_probe,
        ]

        report = build_audit()
        self.assertEqual(report["verdict"], "ready-for-next-week-prep")
        self.assertTrue(report["dailyPrepReady"])
        self.assertFalse(report["brokerExecutionReady"])

        metric_index = {item["key"]: item for item in report["metrics"]}
        self.assertEqual(metric_index["earnings_calendar"]["trustTier"], "daily-safe")
        self.assertEqual(metric_index["iv_rank_family"]["trustTier"], "research-grade")
        self.assertEqual(metric_index["broker_execution"]["status"], "blocked")

    @patch("inferno_data_readiness_audit.load_json_file")
    def test_audit_fails_when_snapshot_is_stale_or_negative(self, mock_load_json_file) -> None:
        snapshot = {
            "generatedAt": "2026-04-30T07:00:00-10:00",
            "rows": [
                {"ticker": "AMD", "daysUntilEarnings": -2, "atrPercent": 4.0, "atrZScore": 1.0, "atr20Day": 4.4}
            ],
        }
        market_context = {
            "generatedAt": "2026-04-30T07:00:01-10:00",
            "populatedRows": 1,
            "totalRows": 1,
            "averageRvol": 1.05,
        }
        mock_load_json_file.side_effect = [
            snapshot,
            {"generatedAt": "2026-04-30T07:00:02-10:00", "count": 0},
            {"generatedAt": "2026-04-30T07:05:00-10:00", "count": 0, "liveTradingAllowed": False},
            market_context,
            {"verdict": "manual-check"},
            {"ok": False, "summary": "no visible thinkorswim window detected"},
        ]

        report = build_audit()
        self.assertEqual(report["verdict"], "needs-refresh")
        self.assertFalse(report["dailyPrepReady"])
        self.assertIn("Broker Confirmation / Execution Authority", report["blockedMetrics"])


if __name__ == "__main__":
    unittest.main()
