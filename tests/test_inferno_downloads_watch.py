from __future__ import annotations

"""Regression tests for the Downloads watch TOS export safety gate."""

import unittest
from unittest.mock import patch

from inferno_downloads_watch import run_watch


class DownloadsWatchTests(unittest.TestCase):
    """Verify the watcher can ingest files without surprise-opening TOS."""

    def _run_with_common_mocks(self, *, automation: bool) -> tuple[dict, object]:
        """Run the watcher with filesystem and broker side effects mocked."""
        with patch("inferno_downloads_watch.automation_skip_reason", return_value=None), patch(
            "inferno_downloads_watch.verify_export_bridge",
            return_value={
                "verdict": "ready-live-readonly",
                "message": "live readonly session verified",
                "enabled": True,
                "appRunning": True,
                "shortcutValid": True,
                "systemEventsOk": True,
                "sessionProbe": {
                    "summary": "main window live",
                    "currentPanel": "Monitor/Account Statement",
                    "currentPanelSafety": "safe",
                },
            },
        ), patch("inferno_downloads_watch.run_export_bridge", return_value={"status": "triggered"}) as export_mock, patch(
            "inferno_downloads_watch.import_downloads",
            return_value={
                "importedFiles": 0,
                "importedRows": 0,
                "quarantinedFiles": 0,
                "sourceDir": "/tmp/downloads",
            },
        ), patch(
            "inferno_downloads_watch.ingest_fill_log",
            return_value={"processedRows": 0, "importedRows": 0, "closedRows": 0, "unmatchedRows": []},
        ), patch("inferno_downloads_watch.save_watch_report"):
            return run_watch(export_first=True, automation=automation), export_mock

    @patch("inferno_downloads_watch.TOS_BACKGROUND_EXPORT_ALLOWED", False)
    def test_background_export_first_fails_closed_without_opt_in(self) -> None:
        report, export_mock = self._run_with_common_mocks(automation=True)

        export_mock.assert_not_called()
        self.assertEqual(report["exportBridge"]["status"], "background-export-disabled")
        self.assertIn("TOS_BACKGROUND_EXPORT_ALLOWED", report["exportBridge"]["message"])
        self.assertEqual(report["downloadsManager"]["importedFiles"], 0)

    @patch("inferno_downloads_watch.TOS_BACKGROUND_EXPORT_ALLOWED", False)
    def test_manual_export_first_can_still_trigger_export_bridge(self) -> None:
        report, export_mock = self._run_with_common_mocks(automation=False)

        export_mock.assert_called_once()
        self.assertEqual(report["exportBridge"]["status"], "triggered")


if __name__ == "__main__":
    unittest.main()
