from __future__ import annotations

"""Tests for the research-only event-move calibration."""

import unittest

import inferno_event_move_calibration as cal


def _candles(days: int, base: float = 100.0, drift_range: float = 1.0) -> list[dict]:
    rows = []
    price = base
    for i in range(days):
        rows.append({"datetime": f"2026-01-{(i % 28) + 1:02d}T05:00:00+00:00", "open": price, "high": price + drift_range, "low": price - drift_range, "close": price, "volume": 1_000_000})
    return rows


class EventMoveCalibrationTests(unittest.TestCase):
    def test_infers_volume_confirmed_large_move_days_with_spacing(self) -> None:
        candles = _candles(200)
        # Two "events": +12% on day 60 with 4x volume, -15% on day 150 with 3x volume, and a
        # 9% move on day 70 that is too close to day 60 to count.
        for idx, pct, vol in ((60, 0.12, 4_000_000), (70, 0.09, 4_000_000), (150, -0.15, 3_000_000)):
            prev = candles[idx - 1]["close"]
            candles[idx].update({"close": prev * (1 + pct), "high": prev * (1 + max(pct, 0)) + 1, "low": prev * (1 + min(pct, 0)) - 1, "volume": vol})
            for later in candles[idx + 1 :]:
                later.update({"open": candles[idx]["close"], "close": candles[idx]["close"], "high": candles[idx]["close"] + 1, "low": candles[idx]["close"] - 1})
        events = cal.infer_events(candles)
        self.assertEqual(len(events), 2)
        self.assertAlmostEqual(events[0]["realizedAbsMovePct"], 12.0, places=1)
        self.assertAlmostEqual(events[1]["realizedAbsMovePct"], 15.0, places=1)
        self.assertGreater(events[0]["moveAtrMultiple"], 3.0)
        self.assertEqual(events[0]["eventSource"], cal.INFERRED_SOURCE)

    def test_quiet_series_yields_no_events(self) -> None:
        self.assertEqual(cal.infer_events(_candles(200)), [])

    def test_build_prefers_curated_backfill_and_is_research_only(self) -> None:
        history = {"generatedAt": "2026-09-04", "rows": [{"symbol": "ABC", "candles": _candles(200)}, {"symbol": "SHORT", "candles": _candles(10)}]}
        backfill = {"events": [{"ticker": "ABC", "earningsDate": "2026-05-01", "impliedMovePct": 9.0, "realizedAbsMovePct": 7.5}, {"ticker": "ABC", "earningsDate": "2026-02-01", "impliedMovePct": 8.0, "realizedAbsMovePct": 12.5}]}
        payload = cal.build_calibration(price_history=history, backfill=backfill)
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["authorityChanged"])
        abc = next(s for s in payload["symbols"] if s["symbol"] == "ABC")
        self.assertEqual(abc["eventSource"], cal.CURATED_SOURCE)
        self.assertTrue(abc["benchmarkReady"])
        self.assertEqual(abc["medianRealizedAbsMovePct"], 10.0)
        self.assertEqual(payload["skipped"][0]["symbol"], "SHORT")
        self.assertEqual(cal.symbol_benchmarks(payload)["ABC"]["eventCount"], 2)
        self.assertIn("research-only", cal.calibration_text(payload))
        self.assertIn(payload["verdict"], {"descriptive", "insufficient-data"})
        self.assertTrue(payload["biasDisclosure"])
        self.assertIn("Bias disclosure", cal.calibration_text(payload))

    def test_single_event_is_not_benchmark_ready(self) -> None:
        summary = cal.symbol_summary("ONE", [{"realizedAbsMovePct": 9.0, "moveAtrMultiple": 2.0}], cal.INFERRED_SOURCE)
        self.assertFalse(summary["benchmarkReady"])
