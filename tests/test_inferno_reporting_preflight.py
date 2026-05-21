from __future__ import annotations

"""Regression tests for the read-only reporting preflight."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_reporting_preflight as preflight


class InfernoReportingPreflightTests(unittest.TestCase):
    """Verify reporting preflight stays read-only and operator-friendly."""

    def test_build_reporting_preflight_allows_running_not_visible_tos_as_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_file = root / "preflight.json"
            text_file = root / "preflight.txt"
            common_check = {
                "name": "artifact",
                "ok": True,
                "severity": "pass",
                "generatedAt": "2026-05-21T06:00:00-06:00",
                "ageHours": 1.0,
                "detail": "fresh",
            }

            with patch.object(preflight, "REPORTING_PREFLIGHT_FILE", data_file), \
                 patch.object(preflight, "REPORTING_PREFLIGHT_TEXT_FILE", text_file), \
                 patch.object(preflight, "_smtp_check", return_value={"name": "smtp", "ok": True, "severity": "pass", "detail": "ok"}), \
                 patch.object(preflight, "_schwab_check", return_value={"name": "schwab token", "ok": True, "severity": "pass", "detail": "ok"}), \
                 patch.object(preflight, "_tos_check", return_value={"name": "tos attach-only", "ok": True, "severity": "warn", "level": "running-not-visible", "detail": "TOS is running but hidden"}), \
                 patch.object(preflight, "_doctor_check", return_value={"name": "doctor", "ok": True, "severity": "pass", "detail": "healthy"}), \
                 patch.object(preflight, "_artifact_check", return_value=common_check), \
                 patch.object(preflight, "build_freshness_panel", return_value={"rows": []}), \
                 patch.object(preflight, "build_tos_visibility_summary", return_value={"message": "TOS is running but hidden"}):
                payload = preflight.build_reporting_preflight()

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["verdict"], "ready")
            self.assertEqual(payload["warningCount"], 1)
            self.assertTrue(data_file.exists())
            self.assertIn("Warnings: 1", text_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
