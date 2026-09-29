from __future__ import annotations

import unittest
from datetime import date

import inferno_short_premium_shadow as cs


def chain(expiry="2026-10-16", spot=100.0, half_spread=0.05):
    """Symmetric synthetic chain: straddle at 100 is ~10 (5 + 5)."""
    rows = []
    for strike in range(80, 121, 5):
        call_mid = max(0.2, 5.0 - 0.45 * (strike - spot)) if strike >= spot else (spot - strike) + 5.0
        put_mid = max(0.2, 5.0 - 0.45 * (spot - strike)) if strike <= spot else (strike - spot) + 5.0
        for side, mid in (("CALL", call_mid), ("PUT", put_mid)):
            rows.append({"putCall": side, "strikePrice": float(strike), "expirationDate": expiry,
                         "bid": round(mid - half_spread, 2), "ask": round(mid + half_spread, 2)})
    return rows


class CondorBuildTests(unittest.TestCase):
    def test_sells_the_implied_move_with_defined_wings(self):
        condor, reason = cs.build_iron_fly(chain(), 100.0, date(2026, 10, 14), date(2026, 10, 10))
        self.assertEqual(reason, "")
        k = condor["strikes"]
        self.assertEqual((k["shortPut"], k["shortCall"]), (100.0, 100.0))
        self.assertEqual((k["longPut"], k["longCall"]), (80.0, 120.0))
        self.assertAlmostEqual(condor["impliedMovePct"], 0.10)
        self.assertAlmostEqual(condor["entryCredit"], 9.4)  # 4.95 + 4.95 - 0.25 - 0.25
        self.assertLess(condor["entryCredit"], condor["midCredit"])
        self.assertAlmostEqual(condor["maxLossDollars"], (20 - 9.4) * 100, places=2)

    def test_expiry_must_follow_earnings_within_21_days(self):
        self.assertIsNone(cs.build_iron_fly(chain("2026-10-14"), 100.0, date(2026, 10, 14), date(2026, 10, 10))[0])
        self.assertIsNone(cs.build_iron_fly(chain("2026-11-20"), 100.0, date(2026, 10, 14), date(2026, 10, 10))[0])

    def test_wide_short_legs_are_skipped(self):
        condor, reason = cs.build_iron_fly(chain(half_spread=4.0), 100.0, date(2026, 10, 14), date(2026, 10, 10))
        self.assertIsNone(condor)
        self.assertTrue(reason)

    def test_settlement_is_capped_by_wings(self):
        rec = {"strikes": {"shortPut": 90.0, "longPut": 85.0, "shortCall": 110.0, "longCall": 115.0},
               "entryCredit": 1.0, "maxLossDollars": 400.0, "spot": 100.0}
        self.assertEqual(cs.settle(rec, 100.0)["estimatedPnl"], 100.0)
        self.assertEqual(cs.settle(rec, 130.0)["estimatedPnl"], -400.0)
        self.assertEqual(cs.settle(rec, 130.0)["estimatedReturnOnRisk"], -1.0)
        self.assertEqual(cs.settle(rec, 88.0)["estimatedPnl"], -100.0)
        self.assertIsNone(cs.settle(rec, 100.0)["midFillReturnOnRisk"])
        rec["midCredit"] = 1.5
        self.assertAlmostEqual(cs.settle(rec, 100.0)["midFillReturnOnRisk"], 1.5 / 3.5, places=5)


class CondorLedgerTests(unittest.TestCase):
    def _options(self, generated="2026-10-10T12:00:00-06:00", regular="True"):
        return {"generatedAt": generated, "rows": [
            {"symbol": "ABC", "status": "ok", "underlyingPrice": "100", "quoteSessionIsRegular": regular,
             "contracts": chain()},
            {"symbol": "FAR", "status": "ok", "underlyingPrice": "100", "quoteSessionIsRegular": "True",
             "contracts": chain()},
        ]}

    snapshot = {"rows": [{"ticker": "ABC", "nextEarnings": "2026-10-14"},
                         {"ticker": "FAR", "nextEarnings": "2026-11-30"}]}

    def test_capture_once_per_event_and_window(self):
        ledger = {"items": []}
        added, _ = cs.capture(self._options(), self.snapshot, ledger)
        again, _ = cs.capture(self._options("2026-10-11T12:00:00-06:00"), self.snapshot, ledger)
        self.assertEqual((added, again), (1, 0))
        self.assertEqual(ledger["items"][0]["eventId"], "ABC|2026-10-14")
        self.assertTrue(ledger["items"][0]["shadowOnly"])

    def test_non_regular_session_is_skipped(self):
        ledger = {"items": []}
        added, skips = cs.capture(self._options(regular="False"), self.snapshot, ledger)
        self.assertEqual(added, 0)
        self.assertEqual(skips[0]["ticker"], "ABC")

    def test_review_waits_for_expiration_then_settles(self):
        ledger = {"items": []}
        cs.capture(self._options(), self.snapshot, ledger)
        price = lambda t, d: {"price": 100.0, "priceDate": d.isoformat()}
        self.assertEqual(cs.review(ledger, price, date(2026, 10, 16)), 0)
        self.assertEqual(cs.review(ledger, price, date(2026, 10, 17)), 1)
        self.assertEqual(ledger["items"][0]["outcome"]["status"], "closed")
        self.assertGreater(ledger["items"][0]["outcome"]["estimatedPnl"], 0)

    def test_summary_uses_v2_clock_not_v1(self):
        ledger = {"items": []}
        cs.capture(self._options(), self.snapshot, ledger)
        cs.review(ledger, lambda t, d: {"price": 100.0}, date(2026, 10, 17))
        summary = cs.summarize(ledger, date(2026, 11, 1))
        self.assertNotIn("timebox-expired-without-breadth", summary["killReasons"])
        self.assertEqual(summary["verdict"], "forward-short-premium-collecting")
        late = cs.summarize(ledger, date(2027, 3, 1))
        self.assertEqual(late["verdict"], "forward-short-premium-killed")
        self.assertFalse(summary["promotionEligible"])


if __name__ == "__main__":
    unittest.main()
