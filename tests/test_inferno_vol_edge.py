from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from inferno_vol_edge import build_vol_edge, classify, iv30_from_contracts, rv_from_atr, vol_edge_text


def contract(dte, strike, vol, put_call="CALL", spread=0.05, exp=None, oi=100):
    return {"daysToExpiration": dte, "expirationDate": exp or f"E{dte}", "strikePrice": strike,
            "volatility": vol, "putCall": put_call, "spreadPct": spread, "openInterest": oi}


class VolEdgeTests(unittest.TestCase):
    def test_iv30_prefers_35dte_atm_and_skips_weeklies_and_garbage(self):
        contracts = [
            contract(4, 100, 150), contract(4, 100, 150, "PUT"),          # weekly: ignored
            contract(30, 100, 50), contract(30, 100, 54, "PUT"),
            contract(30, 110, 40), contract(58, 100, 45),
            contract(30, 100, -999, "PUT", exp="E30"),                     # placeholder: ignored
        ]
        atm = iv30_from_contracts(contracts, 101)
        self.assertEqual(atm["expiration"], "E30")
        self.assertEqual(atm["strike"], 100)
        self.assertAlmostEqual(atm["iv30"], 0.52)
        self.assertIsNone(iv30_from_contracts([contract(4, 100, 50)], 100))

    def test_rv_and_classes(self):
        self.assertAlmostEqual(rv_from_atr(3.2), round(0.032 / 1.6 * 252 ** 0.5, 4))
        self.assertIsNone(rv_from_atr(None))
        self.assertEqual(classify(1.4), "rich")
        self.assertEqual(classify(0.85), "cheap")
        self.assertEqual(classify(1.1), "fair")
        self.assertEqual(classify(None), "unknown")

    def test_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "inferno_schwab_options.json").write_text(json.dumps({"generatedAt": "t", "rows": [
                {"symbol": "AAA", "status": "ok", "underlyingPrice": 100,
                 "contracts": [contract(35, 100, 60, spread=0.04), contract(35, 100, 60, "PUT", spread=0.06)]},
                {"symbol": "BAD", "status": "error"}]}))
            (data / "latest_snapshot.json").write_text(json.dumps({"rows": [
                {"ticker": "AAA", "atrPercent": 2.0, "daysUntilEarnings": 10, "ivRank": 50}]}))
            p = build_vol_edge(data)
        n = p["names"]["AAA"]
        self.assertEqual(p["coverage"], 1)
        self.assertEqual(n["volClass"], "rich")
        self.assertTrue(n["eventInWindow"])
        self.assertTrue(n["liveLiquid"])
        self.assertFalse(p["authorityChanged"])
        self.assertIn("AAA", vol_edge_text(p))


if __name__ == "__main__":
    unittest.main()
