from __future__ import annotations

"""Tests for the provider-backed earnings-history fetch (offline, fake provider)."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

import inferno_earnings_history_fetch as fetch
import inferno_event_move_calibration as cal
from server import load_json_file


def fake_provider(symbol: str):
    if symbol == "EMPTY":
        return [], {}
    dates = ["2026-06-10", "2026-03-11", "2025-12-10", "2026-12-09"]  # last one is in the future
    closes = {
        "2026-06-09": 100.0, "2026-06-10": 104.0, "2026-06-11": 112.0,
        "2026-03-10": 90.0, "2026-03-11": 88.0, "2026-03-12": 81.0,
        "2025-12-09": 80.0, "2025-12-10": 80.5, "2025-12-11": 84.0,
    }
    return dates, closes


class EarningsHistoryFetchTests(unittest.TestCase):
    def test_realized_move_uses_t_minus_1_to_t_plus_1(self) -> None:
        _, closes = fake_provider("ABC")
        self.assertAlmostEqual(fetch.realized_move(closes, "2026-06-10"), 12.0, places=3)
        self.assertAlmostEqual(fetch.realized_move(closes, "2026-03-11"), 10.0, places=3)
        self.assertIsNone(fetch.realized_move({}, "2026-06-10"))

    def test_build_rows_keeps_past_events_only_and_prefers_local_closes(self) -> None:
        local = {"ABC": {"2026-06-09": 100.0, "2026-06-11": 120.0}}  # Schwab closes override provider
        rows, diag = fetch.build_rows(["ABC", "EMPTY"], provider=fake_provider, local_close_map=local, today=date(2026, 9, 7))
        self.assertEqual([r["earningsDate"] for r in rows], ["2026-06-10", "2026-03-11", "2025-12-10"])
        self.assertEqual(rows[0]["realizedAbsMovePct"], "20.0000")
        self.assertEqual(rows[0]["impliedMovePct"], "")
        self.assertEqual(rows[0]["source"], fetch.PROVIDER_SOURCE)
        self.assertEqual(diag[1], {"symbol": "EMPTY", "providerDates": 0, "pastInWindow": 0, "eventsKept": 0})

    def test_end_to_end_into_backfill_and_calibration_curated_basis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "fetched.csv"
            backfill = Path(tmp) / "backfill.json"
            payload = fetch.build_fetch(symbols=["ABC"], provider=fake_provider, local_close_map={}, csv_path=csv_path, backfill_path=backfill)
            self.assertEqual(payload["verdict"], "fetched")
            self.assertTrue(payload["researchOnly"])
            self.assertEqual(payload["eventCount"], 3)
            stored = load_json_file(backfill)
            self.assertEqual(len(stored["records"]), 3)
            self.assertIsNone(stored["records"][0]["impliedMovePct"])
            self.assertEqual(stored["records"][0]["source"], fetch.PROVIDER_SOURCE)
            calibration = cal.build_calibration(price_history={"rows": []}, backfill=stored)
            abc = calibration["symbols"][0]
            self.assertEqual(abc["eventSource"], cal.CURATED_SOURCE)
            self.assertEqual(abc["events"][0]["dateSource"], fetch.PROVIDER_SOURCE)
            self.assertTrue(abc["benchmarkReady"])

    def test_provider_empty_does_not_touch_backfill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backfill = Path(tmp) / "backfill.json"
            backfill.write_text('{"records": [{"ticker": "OLD"}]}', encoding="utf-8")
            payload = fetch.build_fetch(symbols=["EMPTY"], provider=fake_provider, local_close_map={}, csv_path=Path(tmp) / "x.csv", backfill_path=backfill)
            self.assertEqual(payload["verdict"], "provider-empty")
            self.assertIn("OLD", backfill.read_text(encoding="utf-8"))
