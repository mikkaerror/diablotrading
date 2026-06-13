from __future__ import annotations

"""Tests for the one-screen operator entry point."""

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import today


NOW = datetime(2026, 6, 13, 21, 0, tzinfo=timezone.utc)


class TodayFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = Path(self._tmp.name)

    def write_json(self, name: str, payload: dict) -> Path:
        path = self.data / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_fresh_money_is_presented_as_current(self) -> None:
        sync = self.write_json(
            "live.json",
            {
                "generatedAt": "2026-06-13T20:00:00+00:00",
                "netLiquidatingValue": 1000,
                "totalCash": 125,
            },
        )
        state = self.write_json("state.json", {"peakNlv": 1100, "lastNlv": 950})

        output = StringIO()
        with (
            patch.object(today, "LIVE_SYNC", sync),
            patch.object(today, "SCALING_STATE", state),
            redirect_stdout(output),
        ):
            fresh = today.print_money_header(now=NOW)

        self.assertTrue(fresh)
        self.assertIn("Money:  $1,000.00  cash $125.00", output.getvalue())
        self.assertNotIn("STALE", output.getvalue())

    def test_stale_money_is_explicitly_last_known(self) -> None:
        sync = self.write_json(
            "live.json",
            {
                "generatedAt": "2026-06-08T21:00:00+00:00",
                "netLiquidatingValue": 968.28,
                "totalCash": 0,
            },
        )
        state = self.write_json("state.json", {"peakNlv": 1274.58})

        output = StringIO()
        with (
            patch.object(today, "LIVE_SYNC", sync),
            patch.object(today, "SCALING_STATE", state),
            redirect_stdout(output),
        ):
            fresh = today.print_money_header(now=NOW)

        rendered = output.getvalue()
        self.assertFalse(fresh)
        self.assertIn("Money (last known; STALE 5.0d old)", rendered)
        self.assertIn("./run_inferno_schwab_account_sync.sh --json", rendered)

    def test_fresh_wrapper_does_not_hide_stale_schwab_snapshot(self) -> None:
        sync = self.write_json(
            "live.json",
            {
                "generatedAt": "2026-06-13T20:00:00+00:00",
                "accountDataSource": "schwab-account-api",
                "schwabAccountGeneratedAt": "2026-06-08T21:00:00+00:00",
                "netLiquidatingValue": 968.28,
                "totalCash": 0,
            },
        )
        state = self.write_json("state.json", {"peakNlv": 1274.58})

        output = StringIO()
        with (
            patch.object(today, "LIVE_SYNC", sync),
            patch.object(today, "SCALING_STATE", state),
            redirect_stdout(output),
        ):
            fresh = today.print_money_header(now=NOW)

        self.assertFalse(fresh)
        self.assertIn("Money (last known; STALE 5.0d old)", output.getvalue())

    def test_stale_holdings_are_labeled(self) -> None:
        review = self.write_json(
            "positions.json",
            {
                "generatedAt": "2026-06-08T21:00:00+00:00",
                "positions": [
                    {
                        "symbol": "TE",
                        "markValue": 400,
                        "plOpen": 50,
                        "plPercent": 14.29,
                    }
                ],
            },
        )
        sync = self.write_json(
            "live.json",
            {
                "generatedAt": "2026-06-13T20:00:00+00:00",
                "accountDataSource": "schwab-account-api",
                "schwabAccountGeneratedAt": "2026-06-08T21:00:00+00:00",
            },
        )

        output = StringIO()
        with (
            patch.object(today, "LIVE_POSITIONS", review),
            patch.object(today, "LIVE_SYNC", sync),
            redirect_stdout(output),
        ):
            today.print_holdings_section(now=NOW)

        self.assertIn("Holdings (last known; STALE 5.0d old):", output.getvalue())


if __name__ == "__main__":
    unittest.main()
