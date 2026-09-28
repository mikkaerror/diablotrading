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


class TodayCandidatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = Path(self._tmp.name)

    def test_manual_papermoney_route_is_visible_without_queue_approval(self) -> None:
        director = self.data / "director.json"
        director.write_text(
            json.dumps(
                {
                    "operatorRoutableSlate": [
                        {
                            "ticker": "IREN",
                            "status": "stage-in-papermoney",
                            "operatorRoute": "manual-paperMoney-entry",
                            "strategy": "CALL_DEBIT_SPREAD",
                            "estimatedMaxLoss": 200,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        with patch.object(today, "DIRECTOR", director):
            candidates = today.candidates_today()

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["ticker"], "IREN")
        self.assertIn("manual paperMoney route", today._candidate_line(candidates[0]))

    def test_manual_papermoney_yes_never_calls_approval_queue(self) -> None:
        candidate = {
            "ticker": "IREN",
            "operatorRoute": "manual-paperMoney-entry",
            "status": "stage-in-papermoney",
        }
        output = StringIO()
        with (
            patch.object(today, "_prompt", return_value="y"),
            patch.object(today, "_approve_via_queue") as approve_queue,
            patch.object(today, "_log_decision") as log_decision,
            redirect_stdout(output),
        ):
            result = today.run_one(candidate)

        self.assertEqual(result, "route-confirmed")
        approve_queue.assert_not_called()
        log_decision.assert_called_once()
        self.assertIn("no broker action was taken", output.getvalue())



class TodayDrawdownBannerTests(unittest.TestCase):
    def test_capital_scaling_pause_level_shows_paused_banner(self) -> None:
        payload = {"drawdownState": {"level": "pause", "drawdownFraction": 0.7513,
                                      "capMultiplier": 0.0, "newEntriesAllowed": False}}
        with patch.object(today, "_load_json", return_value=payload):
            banner = today._drawdown_banner_if_needed()
        self.assertIn("PAUSED", banner)
        self.assertIn("75.1%", banner)

    def test_normal_level_is_silent(self) -> None:
        with patch.object(today, "_load_json", return_value={"drawdownState": {"level": "normal"}}):
            self.assertIsNone(today._drawdown_banner_if_needed())


if __name__ == "__main__":
    unittest.main()
