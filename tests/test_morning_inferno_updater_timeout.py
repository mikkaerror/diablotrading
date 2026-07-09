from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import morning_inferno_pipeline as pipeline


class MorningInfernoUpdaterTimeoutTests(unittest.TestCase):
    def test_updater_timeout_is_recorded_and_retried(self) -> None:
        with (
            patch("morning_inferno_pipeline.UPDATER_SCRIPT_RETRIES", 2),
            patch("morning_inferno_pipeline.UPDATER_SCRIPT_TIMEOUT_SECONDS", 7),
            patch("morning_inferno_pipeline.sleep_for_retry"),
            patch(
                "morning_inferno_pipeline.run_updater_subprocess",
                side_effect=subprocess.TimeoutExpired(["python", "slow.py"], 7, output="partial"),
            ),
        ):
            completed, attempts = pipeline.run_script_with_retries(
                "slow.py",
                Path("/tmp/backtest"),
                Path("/usr/bin/python3"),
            )

        self.assertEqual(completed.returncode, pipeline.UPDATER_SCRIPT_TIMEOUT_RETURN_CODE)
        self.assertEqual(len(attempts), 2)
        self.assertTrue(all(attempt["timedOut"] for attempt in attempts))
        self.assertEqual(attempts[0]["timeoutSeconds"], 7)
        self.assertIn("timed out after 7s", attempts[0]["stderr"])
        self.assertEqual(attempts[0]["stdout"], "partial")

    def test_timeout_can_recover_through_internal_fallback(self) -> None:
        timed_out = subprocess.CompletedProcess(
            ["python", "slow.py"],
            pipeline.UPDATER_SCRIPT_TIMEOUT_RETURN_CODE,
            stdout="",
            stderr="slow.py timed out after 7s",
        )
        attempts = [
            {
                "attempt": 1,
                "returncode": pipeline.UPDATER_SCRIPT_TIMEOUT_RETURN_CODE,
                "stdout": "",
                "stderr": "slow.py timed out after 7s",
                "timedOut": True,
                "timeoutSeconds": 7,
            }
        ]

        with (
            patch("morning_inferno_pipeline.UPDATER_SCRIPTS", ("slow.py",)),
            patch("morning_inferno_pipeline.run_script_with_retries", return_value=(timed_out, attempts)),
            patch(
                "morning_inferno_pipeline.validate_updater_columns",
                return_value={"ok": True},
            ),
            patch("morning_inferno_pipeline.run_internal_fallback", return_value={"updated": 3}),
        ):
            results = pipeline.run_updaters(Path("/tmp/backtest"), Path("/usr/bin/python3"), "Sheet")

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"])
        self.assertTrue(results[0]["recovered"])
        self.assertEqual(results[0]["returncode"], 0)
        self.assertEqual(results[0]["attempts"], attempts)
        self.assertEqual(results[0]["fallback"], {"updated": 3})


if __name__ == "__main__":
    unittest.main()
