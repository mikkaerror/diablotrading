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
                 patch.object(preflight, "_artifact_check", return_value=common_check) as artifact_check, \
                 patch.object(preflight, "build_freshness_panel", return_value={"rows": []}), \
                 patch.object(preflight, "build_tos_visibility_summary", return_value={"message": "TOS is running but hidden"}):
                payload = preflight.build_reporting_preflight()

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["verdict"], "ready")
            self.assertEqual(payload["warningCount"], 1)
            self.assertTrue(data_file.exists())
            self.assertIn("Warnings: 1", text_file.read_text(encoding="utf-8"))
            self.assertIn("ticket cap policy", [call.args[0] for call in artifact_check.call_args_list])

    def test_schwab_check_fails_when_reauthorization_is_required(self) -> None:
        status = {
            "envFileExists": True,
            "clientIdConfigured": True,
            "clientSecretConfigured": True,
            "tokenFileExists": True,
            "accessTokenPresent": True,
            "refreshTokenPresent": True,
            "reauthorizationRequired": True,
            "accessTokenExpiresAt": "2026-06-29T14:30:21+00:00",
            "refreshTokenExpiresAt": None,
            "lastRefreshErrorAt": "2026-06-29T16:16:49+00:00",
        }

        with patch.object(preflight, "schwab_token_status", return_value=status), \
             patch.object(preflight, "load_schwab_config", return_value={}):
            result = preflight._schwab_check()

        self.assertFalse(result["ok"])
        self.assertEqual(result["severity"], "fail")
        self.assertTrue(result["detail"]["reauthorizationRequired"])

    def test_doctor_check_warns_on_fresh_attention_without_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            doctor_text = Path(temp_dir) / "doctor.txt"
            doctor_text.write_text(
                "Inferno Doctor\n\n[PASS] Schwab OAuth: ready\n[WARN] Watchdog status: stale\n\n"
                "Desk status: 2 item(s) need attention\n",
                encoding="utf-8",
            )

            with patch.object(preflight, "DOCTOR_TEXT_FILE", doctor_text):
                result = preflight._doctor_check()

        self.assertTrue(result["ok"])
        self.assertEqual(result["severity"], "warn")

    def test_doctor_check_fails_on_explicit_failed_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            doctor_text = Path(temp_dir) / "doctor.txt"
            doctor_text.write_text(
                "Inferno Doctor\n\n[FAIL] Schwab OAuth: reauthorization required\n\n"
                "Desk status: 1 item(s) need attention\n",
                encoding="utf-8",
            )

            with patch.object(preflight, "DOCTOR_TEXT_FILE", doctor_text):
                result = preflight._doctor_check()

        self.assertFalse(result["ok"])
        self.assertEqual(result["severity"], "fail")


if __name__ == "__main__":
    unittest.main()
