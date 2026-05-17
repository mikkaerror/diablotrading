from __future__ import annotations

"""Regression tests for live-account synchronization."""

import unittest
from unittest.mock import patch

from inferno_live_account_sync import build_live_account_sync, load_statement


class InfernoLiveAccountSyncTests(unittest.TestCase):
    """Protect the live sync layer from drifting into unsafe or noisy behavior."""

    @patch("inferno_live_account_sync.TOS_ALLOW_LIVE_READONLY", True)
    @patch("inferno_live_account_sync.TOS_ALLOWED_ACCOUNT_SUFFIXES", ("1234",))
    @patch("inferno_live_account_sync.probe_tos_session", return_value={"accountMode": "unknown", "accountSuffixCandidates": [], "summary": "n/a"})
    @patch("inferno_live_account_sync.save_live_account_sync")
    @patch("inferno_live_account_sync.load_json_file")
    def test_build_live_account_sync_returns_healthy_when_positions_match_tracker(
        self,
        mock_load_json_file,
        _mock_save_live_account_sync,
        _mock_probe_tos_session,
    ) -> None:
        statement = {
            "ok": True,
            "generatedAt": "2026-05-09T21:00:00-06:00",
            "accountMode": "live",
            "accountSuffixCandidates": ["11111234"],
            "netLiquidatingValue": "$1000.00",
            "totalCash": "$200.00",
            "positions": [
                {
                    "symbol": "FLR",
                    "description": "FLUOR CORP NEW",
                    "qty": 4,
                    "mark": 43.44,
                    "markValue": 173.76,
                    "plOpen": 1.24,
                    "plPercent": 0.72,
                    "derivedTradePrice": 43.13,
                }
            ],
        }
        snapshot = {
            "rows": [
                {
                    "ticker": "FLR",
                    "priority": 7.58,
                    "readyScore": 3.42,
                    "longTermScore": 2.0,
                    "setupRec": "Vertical Call",
                    "urgency": "Watchlist",
                    "nextEarnings": "2026-05-16",
                    "daysUntilEarnings": 7,
                    "accumulationBias": "Nibble",
                    "status": "ready",
                    "marketContext": {
                        "alignmentLabel": "Aligned",
                        "alignmentScore": 100.0,
                        "trend": {"label": "Bullish"},
                        "rvol": 5.08,
                        "support": 42.75,
                        "resistance": 54.65,
                    },
                }
            ]
        }
        mock_load_json_file.side_effect = [statement, None, snapshot]

        report = build_live_account_sync(refresh_statement=False)

        self.assertTrue(report["ok"])
        self.assertEqual(report["verdict"], "healthy")
        self.assertEqual(report["matchedSuffix"], "1234")
        self.assertEqual(report["counts"]["positions"], 1)
        self.assertEqual(report["counts"]["matchedPositions"], 1)
        self.assertEqual(report["positions"][0]["bucket"], "catalyst-active")

    @patch("inferno_live_account_sync.TOS_ALLOW_LIVE_READONLY", True)
    @patch("inferno_live_account_sync.TOS_ALLOWED_ACCOUNT_SUFFIXES", ("1234",))
    @patch("inferno_live_account_sync.probe_tos_session", return_value={"accountMode": "unknown", "accountSuffixCandidates": [], "summary": "n/a"})
    @patch("inferno_live_account_sync.save_live_account_sync")
    @patch("inferno_live_account_sync.load_json_file")
    def test_build_live_account_sync_flags_unmatched_positions_for_review(
        self,
        mock_load_json_file,
        _mock_save_live_account_sync,
        _mock_probe_tos_session,
    ) -> None:
        statement = {
            "ok": True,
            "generatedAt": "2026-05-09T21:00:00-06:00",
            "accountMode": "live",
            "accountSuffixCandidates": ["11111234"],
            "netLiquidatingValue": "$1000.00",
            "totalCash": "$200.00",
            "positions": [
                {
                    "symbol": "XYZ",
                    "description": "Mystery Name",
                    "qty": 10,
                    "mark": 50.0,
                    "markValue": 500.0,
                    "plOpen": -10.0,
                    "plPercent": -12.0,
                    "derivedTradePrice": 51.0,
                }
            ],
        }
        snapshot = {"rows": []}
        mock_load_json_file.side_effect = [statement, None, snapshot]

        report = build_live_account_sync(refresh_statement=False)

        self.assertTrue(report["ok"])
        self.assertEqual(report["verdict"], "attention")
        self.assertEqual(report["counts"]["unmatchedPositions"], 1)
        self.assertIn("concentration", report["positions"][0]["riskFlags"])
        self.assertIn("untracked", report["positions"][0]["riskFlags"])

    @patch("inferno_live_account_sync.TOS_ALLOW_LIVE_READONLY", True)
    @patch("inferno_live_account_sync.TOS_ALLOWED_ACCOUNT_SUFFIXES", ("1234",))
    @patch("inferno_live_account_sync.probe_tos_session", return_value={"accountMode": "unknown", "accountSuffixCandidates": [], "summary": "n/a"})
    @patch("inferno_live_account_sync.save_live_account_sync")
    @patch("inferno_live_account_sync.load_json_file")
    def test_build_live_account_sync_blocks_unapproved_live_account(
        self,
        mock_load_json_file,
        _mock_save_live_account_sync,
        _mock_probe_tos_session,
    ) -> None:
        statement = {
            "ok": True,
            "generatedAt": "2026-05-09T21:00:00-06:00",
            "accountMode": "live",
            "accountSuffixCandidates": ["11112222"],
            "netLiquidatingValue": "$1000.00",
            "totalCash": "$200.00",
            "positions": [],
        }
        snapshot = {"rows": []}
        mock_load_json_file.side_effect = [statement, None, snapshot]

        report = build_live_account_sync(refresh_statement=False)

        self.assertFalse(report["ok"])
        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("not approved", report["message"])

    @patch("inferno_live_account_sync.TOS_ALLOW_LIVE_READONLY", True)
    @patch("inferno_live_account_sync.TOS_ALLOWED_ACCOUNT_SUFFIXES", ("1234",))
    @patch(
        "inferno_live_account_sync.probe_tos_session",
        return_value={
            "accountMode": "live",
            "accountSuffixCandidates": ["11111234"],
            "summary": "main window live via thinkorswim | current panel Monitor/Account Statement | safety safe | account live",
        },
    )
    @patch("inferno_live_account_sync.save_live_account_sync")
    @patch("inferno_live_account_sync.load_json_file")
    def test_build_live_account_sync_uses_session_probe_when_statement_mode_is_unknown(
        self,
        mock_load_json_file,
        _mock_save_live_account_sync,
        _mock_probe_tos_session,
    ) -> None:
        statement = {
            "ok": True,
            "generatedAt": "2026-05-09T21:00:00-06:00",
            "accountMode": "unknown",
            "accountSuffixCandidates": [],
            "netLiquidatingValue": "$2,900.81",
            "totalCash": "$542.46",
            "positions": [
                {"symbol": "THR", "description": "THERMON GROUP HLDGS", "qty": 3, "mark": 64.69, "markValue": 194.07}
            ],
        }
        snapshot = {"rows": []}
        mock_load_json_file.side_effect = [statement, None, snapshot]

        report = build_live_account_sync(refresh_statement=False)

        self.assertTrue(report["ok"])
        self.assertEqual(report["accountMode"], "live")
        self.assertEqual(report["matchedSuffix"], "1234")

    @patch("inferno_live_account_sync.scrape_account_statement")
    @patch("inferno_live_account_sync.load_json_file")
    def test_load_statement_uses_last_good_artifact_when_refresh_scrape_fails(
        self,
        mock_load_json_file,
        mock_scrape_account_statement,
    ) -> None:
        mock_scrape_account_statement.return_value = {"ok": False, "message": "window not visible"}
        mock_load_json_file.return_value = {"ok": True, "accountMode": "live", "accountSuffixCandidates": ["11111234"]}

        statement = load_statement(refresh=True)

        self.assertTrue(statement["ok"])
        self.assertEqual(statement["_refreshFallback"], "window not visible")

    @patch("inferno_live_account_sync.scrape_account_statement")
    @patch("inferno_live_account_sync.load_json_file")
    def test_load_statement_prefers_last_good_when_latest_artifact_failed(
        self,
        mock_load_json_file,
        mock_scrape_account_statement,
    ) -> None:
        """Closed-TOS low-power probes should not poison live-sync artifacts."""
        latest_failed = {"ok": False, "message": "thinkorswim main window is not visible"}
        last_good = {"ok": True, "accountMode": "live", "accountSuffixCandidates": ["11111234"]}
        mock_load_json_file.side_effect = [latest_failed, last_good]

        statement = load_statement(refresh=False)

        self.assertTrue(statement["ok"])
        self.assertEqual(statement["accountMode"], "live")
        mock_scrape_account_statement.assert_not_called()


if __name__ == "__main__":
    unittest.main()
