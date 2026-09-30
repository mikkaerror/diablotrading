from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import inferno_earnings_runner as er


def contracts(spot=100.0, exps=("2026-10-16", "2026-11-06"), mid_shift=0.0, half=0.05):
    out = []
    for exp in exps:
        for k in range(70, 131, 5):
            c = max(0.3, 5.0 - 0.4 * (k - spot)) if k >= spot else (spot - k) + 5.0
            p = max(0.3, 5.0 - 0.4 * (spot - k)) if k <= spot else (k - spot) + 5.0
            for side, mid in (("CALL", c + mid_shift), ("PUT", p + mid_shift)):
                out.append({"putCall": side, "strikePrice": float(k), "expirationDate": exp,
                            "bid": round(mid - half, 2), "ask": round(mid + half, 2)})
    return out


def opts(day, ticker="ABC", **kw):
    return {"generatedAt": f"{day}T10:00:00-06:00", "rows": [
        {"symbol": ticker, "status": "ok", "underlyingPrice": kw.pop("spot", 100.0),
         "atmImpliedMovePct": 0.08, "contracts": contracts(**kw)}]}


def history(ticker, closes):
    return {"rows": [{"symbol": ticker, "candles": [
        {"datetime": d, "open": c, "high": h, "low": lo, "close": c} for d, c, h, lo in closes]}]}


class RunupTests(unittest.TestCase):
    snap = {"rows": [{"ticker": "ABC", "nextEarnings": "2026-10-14", "atrPercent": 4.0}]}
    quiet = history("ABC", [("2026-10-06", 100.0, 101, 99), ("2026-10-07", 100.5, 101, 99)])

    def test_quiet_day_entry_then_exit_before_report(self):
        L = {"records": []}
        r = er.collect(L, opts("2026-10-08"), self.snap, self.quiet, [], date(2026, 10, 8))
        self.assertEqual(r["added"], 1)
        rec = L["records"][0]
        self.assertEqual((rec["arm"], rec["structure"], rec["expiration"]), ("A", "LONG_STRADDLE", "2026-10-16"))
        self.assertAlmostEqual(rec["entry"], 10.1)  # both legs at the ask
        er.collect(L, opts("2026-10-13", mid_shift=1.0), self.snap, self.quiet, [], date(2026, 10, 13))
        self.assertEqual(rec["status"], "open")
        er.collect(L, {"rows": []}, self.snap, self.quiet, [], date(2026, 10, 14))
        self.assertEqual(rec["status"], "closed")
        self.assertAlmostEqual(rec["exit"], 11.9)  # both legs at the bid, after the run-up
        self.assertGreater(rec["returnOnDebit"], 0)
        self.assertIn("before the report", rec["exitHow"])

    def test_loud_day_is_skipped(self):
        loud = history("ABC", [("2026-10-06", 100.0, 101, 99), ("2026-10-07", 104.0, 105, 99)])
        L = {"records": []}
        r = er.collect(L, opts("2026-10-08"), self.snap, loud, [], date(2026, 10, 8))
        self.assertEqual(r["added"], 0)
        self.assertIn("A ABC: not a quiet day", r["skips"])

    def test_no_capture_before_report_is_unscored(self):
        L = {"records": []}
        er.collect(L, opts("2026-10-08"), self.snap, self.quiet, [], date(2026, 10, 8))
        er.collect(L, {"rows": []}, self.snap, self.quiet, [], date(2026, 10, 14))
        self.assertEqual(L["records"][0]["status"], "unscored")


class RunnerTests(unittest.TestCase):
    def _setup(self, reaction_close, high, low):
        L = {"records": []}
        before = {"rows": [{"ticker": "ABC", "nextEarnings": "2026-10-14", "atrPercent": 4.0}]}
        er.collect(L, opts("2026-10-10", exps=("2026-10-16",)), before, {"rows": []}, [], date(2026, 10, 10))
        after = {"rows": [{"ticker": "ABC", "nextEarnings": "2027-01-20", "atrPercent": 4.0}]}
        hist = history("ABC", [("2026-10-13", 100.0, 101, 99), ("2026-10-15", reaction_close, high, low)])
        return L, after, hist

    def test_gap_that_held_opens_call_spread(self):
        L, after, hist = self._setup(112.0, 113, 104)
        r = er.collect(L, opts("2026-10-15", spot=112.0, exps=("2026-11-20",)), after, hist, [], date(2026, 10, 15))
        rec = [x for x in L["records"] if x["arm"] == "B"][0]
        self.assertEqual(r["added"], 1)
        self.assertEqual((rec["structure"], rec["direction"]), ("CALL_DEBIT_SPREAD", "up"))
        self.assertEqual(rec["legs"][0][1], 110.0)
        self.assertGreaterEqual(rec["legs"][1][1] - rec["legs"][0][1], 0.08 * 112.0)

    def test_gap_that_faded_does_not_trigger(self):
        L, after, hist = self._setup(112.0, 118, 104)  # closed in the middle of the range
        er.collect(L, opts("2026-10-15", spot=112.0, exps=("2026-11-20",)), after, hist, [], date(2026, 10, 15))
        self.assertFalse([x for x in L["records"] if x["arm"] == "B"])
        self.assertEqual(L["nonTriggers"][0]["eventId"], "ABC|2026-10-14")

    def test_take_profit_and_time_exit(self):
        rec = {"arm": "B", "ticker": "ABC", "eventId": "ABC|2026-10-14", "enteredOn": "2026-10-15", "expiration": "2026-11-20",
               "legs": [["CALL", 100.0, "long"], ["CALL", 110.0, "short"]], "entry": 2.0, "status": "open"}
        L = {"records": [rec]}
        rich = {"generatedAt": "x", "rows": [{"symbol": "ABC", "status": "ok", "underlyingPrice": 112.0, "contracts": [
            {"putCall": "CALL", "strikePrice": 100.0, "expirationDate": "2026-11-20", "bid": 12.0, "ask": 12.2},
            {"putCall": "CALL", "strikePrice": 110.0, "expirationDate": "2026-11-20", "bid": 4.8, "ask": 5.0}]}]}
        er.collect(L, rich, {"rows": []}, {"rows": []}, [], date(2026, 10, 16))
        self.assertEqual((rec["status"], rec["exitHow"]), ("closed", "take-profit +50%"))
        self.assertAlmostEqual(rec["returnOnDebit"], 2.5)
        rec2 = {**rec, "status": "open", "enteredOn": "2026-10-01"}
        rec2.pop("exit"); rec2.pop("exitHow")
        L2 = {"records": [rec2]}
        flat = {"generatedAt": "x", "rows": [{"symbol": "ABC", "status": "ok", "underlyingPrice": 100.0, "contracts": [
            {"putCall": "CALL", "strikePrice": 100.0, "expirationDate": "2026-11-20", "bid": 2.5, "ask": 2.7},
            {"putCall": "CALL", "strikePrice": 110.0, "expirationDate": "2026-11-20", "bid": 0.8, "ask": 0.9}]}]}
        er.collect(L2, flat, {"rows": []}, {"rows": []}, [], date(2026, 10, 16))
        self.assertEqual(rec2["exitHow"], "time exit (10 trading days)")
        self.assertAlmostEqual(rec2["returnOnDebit"], -0.2)


class CallsAndBoardTests(unittest.TestCase):
    def test_operator_call_builds_put_spread_and_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calls.csv"
            er.record_call("abc", "down", "guide cut", path)
            calls = er.load_calls(path)
        self.assertEqual(calls[0]["ticker"], "ABC")
        L = {"records": []}
        r = er.collect(L, opts("2026-10-10", exps=("2026-11-13",)), {"rows": []}, {"rows": []}, calls, date(2026, 10, 10))
        self.assertEqual(r["added"], 1)
        rec = L["records"][0]
        self.assertEqual((rec["arm"], rec["structure"], rec["why"]), ("C", "PUT_DEBIT_SPREAD", "guide cut"))
        board = er.scoreboard(L)
        self.assertEqual((board["C"]["open"], board["A"]["closed"]), (1, 0))
        with self.assertRaises(SystemExit):
            er.record_call("abc", "sideways", "", Path(tmp) / "x.csv")

    def test_trading_days(self):
        self.assertEqual(er.trading_days_between(date(2026, 10, 2), date(2026, 10, 9)), 5)


if __name__ == "__main__":
    unittest.main()
