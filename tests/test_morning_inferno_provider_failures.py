from __future__ import annotations

import unittest
from unittest.mock import patch

from morning_inferno_pipeline import ProviderCallError, google_sheets_call, provider_failure_payload


class GoogleSheetsFailureTests(unittest.TestCase):
    def test_dns_failure_stops_immediate_duplicate_retries(self) -> None:
        calls = 0

        def unresolved_call() -> None:
            nonlocal calls
            calls += 1
            raise RuntimeError("NameResolutionError: Failed to resolve oauth2.googleapis.com")

        with patch("morning_inferno_pipeline.sleep_for_retry") as sleep:
            with self.assertRaises(ProviderCallError) as raised:
                google_sheets_call("open Earnings Tracker", unresolved_call, attempts=5)

        error = raised.exception
        self.assertEqual(calls, 1)
        sleep.assert_not_called()
        self.assertEqual(error.failure_class, "dns")
        self.assertTrue(error.retryable)
        self.assertEqual(error.attempts, 1)
        self.assertEqual(
            provider_failure_payload(error),
            {
                "provider": "google-sheets",
                "operation": "open Earnings Tracker",
                "failureClass": "dns",
                "retryable": True,
                "attempts": 1,
                "errorType": "RuntimeError",
            },
        )

    def test_non_retryable_auth_failure_stops_immediately(self) -> None:
        with self.assertRaises(ProviderCallError) as raised:
            google_sheets_call(
                "open Earnings Tracker",
                lambda: (_ for _ in ()).throw(RuntimeError("invalid_grant")),
                attempts=5,
            )

        self.assertEqual(raised.exception.failure_class, "auth")
        self.assertFalse(raised.exception.retryable)
        self.assertEqual(raised.exception.attempts, 1)


if __name__ == "__main__":
    unittest.main()
