from __future__ import annotations

"""Regression tests for watchdog handling of intentional email skips."""

import unittest
from datetime import datetime
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

    def test_dns_provider_failure_defers_duplicate_rescue_until_cooldown(self) -> None:
        now = datetime.fromisoformat("2026-07-27T06:10:00-06:00")
        ops_status = {
            "generatedAt": "2026-07-27T06:00:00-06:00",
            "providerFailure": {
                "provider": "google-sheets",
                "failureClass": "dns",
                "retryable": True,
            },
        }
        reasons = ["morning brief email did not send"]

        attempt, suppression, circuit = watchdog.rescue_decision(
            reasons,
            ops_status,
            {},
            now=now,
        )

        self.assertFalse(attempt)
        self.assertIn("provider backoff active", suppression or "")
        self.assertEqual(circuit["consecutiveFailures"], 1)
        self.assertEqual(circuit["nextRetryAt"], "2026-07-27T06:15:00-06:00")

    def test_dns_provider_failure_doubles_backoff_only_after_new_failed_run(self) -> None:
        first_now = datetime.fromisoformat("2026-07-27T06:10:00-06:00")
        first_ops_status = {
            "generatedAt": "2026-07-27T06:00:00-06:00",
            "providerFailure": {
                "provider": "google-sheets",
                "failureClass": "dns",
                "retryable": True,
            },
        }
        _, _, first_circuit = watchdog.rescue_decision(
            ["morning brief email did not send"], first_ops_status, {}, now=first_now
        )

        # The same status does not push the gate forward, so a single bounded
        # probe is allowed once its initial fifteen-minute wait has elapsed.
        attempt, suppression, same_circuit = watchdog.rescue_decision(
            ["morning brief email did not send"],
            first_ops_status,
            {"providerCircuit": first_circuit},
            now=datetime.fromisoformat("2026-07-27T06:16:00-06:00"),
        )
        self.assertTrue(attempt)
        self.assertIsNone(suppression)
        self.assertEqual(same_circuit["consecutiveFailures"], 1)

        # A new failed probe is the only event that doubles the cooldown.
        second_ops_status = dict(first_ops_status, generatedAt="2026-07-27T06:17:00-06:00")
        second_circuit = watchdog.provider_rescue_circuit(
            second_ops_status,
            {"providerCircuit": first_circuit},
            now=datetime.fromisoformat("2026-07-27T06:18:00-06:00"),
        )
        self.assertEqual(second_circuit["consecutiveFailures"], 2)
        self.assertEqual(second_circuit["nextRetryAt"], "2026-07-27T06:47:00-06:00")

    def test_malformed_prior_counter_fails_safe_to_initial_backoff(self) -> None:
        circuit = watchdog.provider_rescue_circuit(
            {
                "generatedAt": "2026-07-27T06:00:00-06:00",
                "providerFailure": {
                    "provider": "google-sheets",
                    "failureClass": "dns",
                    "retryable": True,
                },
            },
            {
                "providerCircuit": {
                    "fingerprint": "google-sheets:dns",
                    "consecutiveFailures": "not-a-number",
                }
            },
            now=datetime.fromisoformat("2026-07-27T06:10:00-06:00"),
        )

        self.assertEqual(circuit["consecutiveFailures"], 1)


if __name__ == "__main__":
    unittest.main()
