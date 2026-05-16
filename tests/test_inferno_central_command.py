from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_central_command as central_command


class InfernoCentralCommandTests(unittest.TestCase):
    """Verify the supervisor entrypoint centralizes maintenance and collaboration."""

    def test_build_central_command_combines_maintenance_command_center_and_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            report_file = temp_root / "central_command.json"
            report_text_file = temp_root / "central_command.txt"

            with (
                patch.object(central_command, "CENTRAL_COMMAND_FILE", report_file),
                patch.object(central_command, "CENTRAL_COMMAND_TEXT_FILE", report_text_file),
                patch.object(
                    central_command,
                    "run_maintenance",
                    return_value={"ok": True, "generatedAt": "2026-05-10T15:00:00-06:00"},
                ),
                patch.object(
                    central_command,
                    "build_command_center",
                    return_value={
                        "generatedAt": "2026-05-10T15:00:01-06:00",
                        "headlineMetrics": {
                            "liveSupported": 2,
                            "liveFragile": 1,
                            "paperApprovalOnly": 1,
                            "paperRemainingForPromotion": 30,
                        },
                        "nextActions": ["Manual risk review: GDS."],
                        "activeMissions": [{"id": "mission-1"}],
                        "recentNotes": [{"id": "note-1"}],
                    },
                ),
                patch.object(
                    central_command,
                    "doctor_summary",
                    return_value={"ok": True, "verdict": "healthy", "detail": "Desk status: healthy"},
                ),
            ):
                payload = central_command.build_central_command(
                    backtest_root=temp_root,
                    sheet_name="Earnings Tracker",
                    cloud_region="us-central1",
                )

            saved = json.loads(report_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["verdict"], "healthy")
            self.assertEqual(saved["modelCommandCenter"]["missionCount"], 1)
            self.assertEqual(saved["modelCommandCenter"]["noteCount"], 1)
            self.assertEqual(saved["recommendedNextMove"], "Manual risk review: GDS.")
            self.assertIn("Supervisor verdict: healthy", report_text_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
