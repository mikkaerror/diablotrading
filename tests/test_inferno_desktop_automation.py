from __future__ import annotations

"""Regression tests for the guarded desktop automation coordinator."""

import unittest
from unittest.mock import patch

from inferno_desktop_automation import desktop_verdict, run_desktop_cycle


class DesktopAutomationTests(unittest.TestCase):
    """Verify the local broker-adjacent automation lane stays safe and predictable."""

    def test_desktop_verdict_blocks_when_verifier_fails(self) -> None:
        self.assertEqual(desktop_verdict(False, "blocked", None, None), "blocked")

    def test_desktop_verdict_marks_scheduled_idle(self) -> None:
        self.assertEqual(
            desktop_verdict(True, "ready", {"skipped": True}, {"sandboxReady": True}),
            "scheduled-idle",
        )

    def test_desktop_verdict_marks_ready_with_live_sandbox(self) -> None:
        self.assertEqual(
            desktop_verdict(True, "ready", {"skipped": False}, {"sandboxReady": True}),
            "ready",
        )

    def test_desktop_verdict_stays_review_when_verifier_needs_manual_check(self) -> None:
        self.assertEqual(
            desktop_verdict(True, "manual-check", {"skipped": False}, {"sandboxReady": True}),
            "review",
        )

    @patch("inferno_desktop_automation.save_desktop_report")
    @patch("inferno_desktop_automation.save_tos_sandbox_session")
    @patch(
        "inferno_desktop_automation.scrape_account_statement",
        return_value={
            "ok": True,
            "message": "statement scraped from the live Account Statement pane",
            "accountMode": "live",
            "accountSuffixCandidates": ["11111234"],
            "positions": [{"symbol": "FLR"}, {"symbol": "GDS"}, {"symbol": "THR"}],
            "netLiquidatingValue": "$571.89",
            "totalCash": "$24.15",
        },
    )
    @patch(
        "inferno_desktop_automation.build_tos_sandbox_session",
        return_value={
            "sandboxReady": True,
            "stageableCount": 2,
            "watchlistCount": 1,
            "blockedCount": 0,
            "environment": "thinkorswim-paperMoney",
            "authorityLevel": "paper-evidence-only",
        },
    )
    @patch(
        "inferno_desktop_automation.run_watch",
        return_value={
            "skipped": False,
            "skipReason": None,
            "exportBridge": {"status": "triggered"},
            "downloadsManager": {"importedFiles": 1, "importedRows": 3, "quarantinedFiles": 0},
            "fillIngest": {"processedRows": 3, "importedRows": 2, "closedRows": 1, "unmatchedRows": 0},
        },
    )
    @patch(
        "inferno_desktop_automation.verify_export_bridge",
        return_value={
            "verdict": "ready",
            "message": "preflight clean",
            "appRunning": True,
            "systemEventsOk": True,
            "sessionProbe": {"currentPanel": "Monitor", "currentPanelSafety": "safe"},
        },
    )
    def test_run_cycle_chains_watch_and_sandbox_when_verifier_is_safe(
        self,
        _verify_mock: object,
        watch_mock: object,
        _statement_mock: object,
        sandbox_mock: object,
        save_sandbox_mock: object,
        save_report_mock: object,
    ) -> None:
        report = run_desktop_cycle(export_first=True, automation=False, require_tos_running=True)
        self.assertEqual(report["verdict"], "ready")
        self.assertTrue(report["verifierOk"])
        self.assertEqual(report["downloadsWatch"]["exportBridge"], "triggered")
        self.assertTrue(report["sandbox"]["sandboxReady"])
        self.assertEqual(report["accountStatement"]["positionCount"], 3)
        watch_mock.assert_called_once()
        sandbox_mock.assert_called_once()
        save_sandbox_mock.assert_called_once()
        save_report_mock.assert_called_once()

    @patch("inferno_desktop_automation.save_desktop_report")
    @patch(
        "inferno_desktop_automation.verify_export_bridge",
        return_value={
            "verdict": "blocked",
            "message": "System Events unavailable",
            "appRunning": False,
            "systemEventsOk": False,
            "sessionProbe": {"currentPanel": None, "currentPanelSafety": None},
        },
    )
    @patch("inferno_desktop_automation.run_watch")
    @patch("inferno_desktop_automation.build_tos_sandbox_session")
    def test_run_cycle_stops_cleanly_when_verifier_blocks(
        self,
        sandbox_mock: object,
        watch_mock: object,
        _verify_mock: object,
        save_report_mock: object,
    ) -> None:
        report = run_desktop_cycle(export_first=True, automation=True, require_tos_running=False)
        self.assertEqual(report["verdict"], "blocked")
        self.assertFalse(report["verifierOk"])
        self.assertIn("System Events", report["blockReason"])
        watch_mock.assert_not_called()
        sandbox_mock.assert_not_called()
        save_report_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
