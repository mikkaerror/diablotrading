from __future__ import annotations

"""Regression tests for shared reporting language."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_reporting_summary as summary


class InfernoReportingSummaryTests(unittest.TestCase):
    """Protect freshness and attach-only wording from drifting."""

    def test_live_account_freshness_uses_embedded_schwab_timestamp(self) -> None:
        payload = {
            "generatedAt": "2026-06-13T15:20:46-06:00",
            "accountDataSource": "schwab-account-api",
            "schwabAccountGeneratedAt": "2026-06-08T23:02:41-05:00",
            "statementGeneratedAt": "2026-06-08T23:02:41-05:00",
        }

        self.assertEqual(
            summary.live_account_source_timestamp(payload),
            "2026-06-08T23:02:41-05:00",
        )

    def test_artifact_generated_at_does_not_launder_stale_broker_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "live.json"
            path.write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-06-13T15:20:46-06:00",
                        "accountDataSource": "schwab-account-api",
                        "schwabAccountGeneratedAt": "2026-06-08T23:02:41-05:00",
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(summary, "LIVE_ACCOUNT_SYNC_FILE", path):
                generated_at = summary.artifact_generated_at(path)

        self.assertEqual(generated_at, "2026-06-08T23:02:41-05:00")

    def test_tos_running_but_not_visible_gets_precise_attach_only_wording(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            probe = root / "probe.json"
            verifier = root / "verifier.json"
            probe.write_text(
                json.dumps(
                    {
                        "mainWindowPresent": False,
                        "summary": "no visible thinkorswim window detected",
                        "frontmostApp": "Google Chrome",
                    }
                ),
                encoding="utf-8",
            )
            verifier.write_text(json.dumps({"appRunning": False}), encoding="utf-8")

            with patch.object(summary, "TOS_SESSION_PROBE_FILE", probe), \
                 patch.object(summary, "TOS_EXPORT_VERIFIER_FILE", verifier), \
                 patch.object(summary, "_process_running", return_value=(True, "thinkorswim")):
                status = summary.build_tos_visibility_summary()

        self.assertEqual(status["level"], "running-not-visible")
        self.assertIn("running, but no main window is visible", status["message"])
        self.assertNotIn("intentionally closed", status["message"])

    def test_sanitize_tos_language_replaces_stale_closed_phrase(self) -> None:
        stale = (
            "Desk ok. TOS is intentionally closed for low-performance mode; open it only "
            "for supervised export or manual order staging."
        )
        clean = summary.sanitize_tos_language(
            stale,
            {"message": "TOS is running, but no main window is visible to the attach-only probe."},
        )

        self.assertIn("TOS is running, but no main window is visible", clean)
        self.assertNotIn("intentionally closed", clean)


if __name__ == "__main__":
    unittest.main()
