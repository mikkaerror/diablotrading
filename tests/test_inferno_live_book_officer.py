from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import inferno_live_book_officer as lb


def _w(folder: Path, name: str, payload: dict) -> None:
    (folder / name).write_text(json.dumps(payload), encoding="utf-8")


class LiveBookOfficerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data, self.research = root / "data", root / "research"
        self.data.mkdir()
        self.research.mkdir()
        _w(self.data, "inferno_live_account_sync.json", {"netLiquidatingValue": 1000.0, "totalCash": 300.0})
        _w(self.data, "inferno_live_position_review.json", {"positions": [
            {"symbol": "AAA", "markValue": 200.0, "plPercent": -25.0},
            {"symbol": "BBB", "markValue": 50.0, "plPercent": 10.0},
        ]})
        _w(self.data, "latest_snapshot.json", {"rows": [
            {"ticker": "AAA", "trend": "Bearish", "nextEarnings": "2026-11-05"},
            {"ticker": "BBB", "trend": "Uptrend"},
        ]})
        candles = [{"close": 100.0}] * 200 + [{"close": 80.0}] * 10
        _w(self.data, "inferno_schwab_price_history.json", {"rows": [{"symbol": "AAA", "candles": candles}]})
        _w(self.data, "operator_long_term_holds.json", {"symbols": ["AAA"]})
        _w(self.data, "inferno_capex_flow.json", {"names": [
            {"ticker": "HOT", "action": "BUY", "entryTiming": {"state": "exhaustion"}},
            {"ticker": "EXT", "action": "BUY", "entryTiming": {"state": "extended"}},
        ]})
        _w(self.research, "conviction_plan_draft.json", {
            "status": "draft-unsigned",
            "sleeveTargets": {"operatorHolds": 0.15, "reserve": 0.15},
            "deposit": {"amount": 250, "nextExpected": "2026-10-09",
                        "splitWhileCashAboveReserve": {"core": 0.55, "conviction": 0.45}},
            "coreVehicle": "SMH",
            "thesisCards": {"AAA": {"breaks": "Heavy dilution"}},
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_binding_vs_if_signed(self):
        p = lb.build(self.data, self.research)
        aaa = next(h for h in p["holdings"] if h["symbol"] == "AAA")
        self.assertIn("no adding while under water (playbook 5.4, binding)", aaa["binding"])
        self.assertTrue(any("past the -20% rule" in x for x in aaa["binding"]))
        self.assertTrue(any("never sells" in x for x in aaa["binding"]))
        self.assertTrue(any("survival test: 20%" in x for x in aaa["ifSigned"]))
        self.assertTrue(any("displayed only (operator hold)" in x for x in aaa["ifSigned"]))
        self.assertTrue(any("2026-11-06" in x and "heavy dilution" in x for x in aaa["ifSigned"]))
        bbb = next(h for h in p["holdings"] if h["symbol"] == "BBB")
        self.assertEqual(bbb["binding"], [])
        self.assertEqual(p["planStatus"], "draft-unsigned")
        self.assertFalse(p["brokerSubmitAllowed"])

    def test_deposit_routing_skips_exhausted_and_tranches_extended(self):
        r = lb.build(self.data, self.research)["depositRouting"]
        self.assertEqual((r["core"], r["conviction"], r["convictionName"]), (137.5, 112.5, "EXT"))
        self.assertEqual(r["convictionTranche"], "1/3 now, rest on a pullback")
        text = lb.officer_text(lb.build(self.data, self.research))
        self.assertIn("NOT signed", text)
        self.assertIn("nothing to the holds", text)

    def test_no_routing_when_cash_at_reserve(self):
        _w(self.data, "inferno_live_account_sync.json", {"netLiquidatingValue": 1000.0, "totalCash": 100.0})
        self.assertIsNone(lb.build(self.data, self.research)["depositRouting"])

    def test_sma_needs_history(self):
        self.assertIsNone(lb.sma200_state([{"close": 1.0}] * 50))


if __name__ == "__main__":
    unittest.main()
