from __future__ import annotations

"""Regression tests for watchdog handling of intentional email skips."""

import unittest
from unittest.mock import patch

import inferno_watchdog as watchdog


class InfernoWatchdogTests(unittest.TestCase):
    def test_intentional_skip_email_run_does_not_count_as_failed_email(self) -> None:
        with patch("inferno_watchdog.cycle_reference_day", return_value="2026-07-09"):
            reasons = watchdog.build_failure_reasons(
                {
                    "generatedAt": "2026-07-09T17:35:46-06:00",
                    "ok": True,
                    "emailSent": False,
                    "emailSkipped": True,
                    "emailSkipReason": "skip-email-flag",
                    "updaterScripts": [],
                }
            )

        self.assertEqual(reasons, [])

    def test_skip_email_with_send_error_still_counts_as_failed_email(self) -> None:
        with patch("inferno_watchdog.cycle_reference_day", return_value="2026-07-09"):
            reasons = watchdog.build_failure_reasons(
                {
                    "generatedAt": "2026-07-09T06:35:46-06:00",
                    "ok": True,
                    "emailSent": False,
                    "emailSkipped": True,
                    "emailSkipReason": "skip-email-flag",
                    "emailError": "SMTP timeout",
                    "updaterScripts": [],
                }
            )

        self.assertIn("morning brief email did not send", reasons)


if __name__ == "__main__":
    unittest.main()
