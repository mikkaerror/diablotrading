import unittest
from unittest.mock import patch

import inferno_ai_basket_review as rv


class DisciplineWatchTests(unittest.TestCase):
    def test_avoid_names_flagged_do_not_average_down(self):
        cp = {"ranking": [
            {"symbol": "ORCL", "tag": "AVOID"},
            {"symbol": "MSFT", "tag": "REDUCE"},
            {"symbol": "STX", "tag": "LEADER"},
            {"symbol": "OTEX", "tag": "AVOID"},
        ]}
        al = {"events": []}
        dw = rv.discipline_watch(al, cp)
        self.assertEqual(dw["doNotAverageDown"], ["ORCL", "OTEX"])
        self.assertEqual(dw["reentryConfirmed"], [])

    def test_reentry_crossings_flagged(self):
        cp = {"ranking": [{"symbol": "NVDA", "tag": "LEADER"}]}
        al = {"events": [
            {"sym": "AAOI", "kind": "REENTRY"},
            {"sym": "SMCI", "kind": "EXIT"},
            {"sym": "GLW", "kind": "REENTRY"},
        ]}
        dw = rv.discipline_watch(al, cp)
        self.assertEqual(dw["reentryConfirmed"], ["AAOI", "GLW"])
        self.assertEqual(dw["doNotAverageDown"], [])

    def test_handles_empty_inputs(self):
        dw = rv.discipline_watch({}, {})
        self.assertEqual(dw, {"doNotAverageDown": [], "reentryConfirmed": []})


class DigestSizingBlockTests(unittest.TestCase):
    def _base(self, sizing):
        return {
            "alerts": {"events": [], "emailed": {}},
            "composite": {"ranking": [{"symbol": "NVDA", "tag": "LEADER"}]},
            "benchmark": {"error": "no benchmark"},
            "sizing": sizing,
        }

    def test_sizing_block_renders_weights_and_buckets(self):
        sizing = {
            "signalsTrusted": True, "investedWeight": 0.84, "cashWeight": 0.16,
            "bucketTotals": {"AI-capex hardware complex": 0.60,
                             "Industrials / bearings": 0.136},
            "unclassifiedSymbols": [],
            "targets": [
                {"symbol": "FTNT", "targetWeight": 0.08, "currentWeight": None,
                 "delta": None, "action": "—"},
                {"symbol": "ORCL", "targetWeight": 0.0, "currentWeight": None,
                 "delta": None, "action": "—"},
            ],
        }
        out = rv.digest(self._base(sizing))
        self.assertIn("TARGET SIZING:", out)
        self.assertIn("cash 16%", out)
        self.assertIn("FTNT 8.0%", out)
        self.assertIn("AI-capex hardware complex", out)

    def test_sizing_block_shows_actions_when_current_weights_given(self):
        sizing = {
            "signalsTrusted": True, "investedWeight": 0.5, "cashWeight": 0.5,
            "bucketTotals": {}, "unclassifiedSymbols": [],
            "targets": [
                {"symbol": "ORCL", "targetWeight": 0.0, "currentWeight": 0.10,
                 "delta": -0.10, "action": "EXIT"},
                {"symbol": "NVDA", "targetWeight": 0.05, "currentWeight": 0.01,
                 "delta": 0.04, "action": "ADD"},
            ],
        }
        out = rv.digest(self._base(sizing))
        self.assertIn("actions vs current book:", out)
        self.assertIn("[EXIT] ORCL", out)
        self.assertIn("[ADD ] NVDA", out)

    def test_sizing_block_reports_fail_closed(self):
        sizing = {"signalsTrusted": False, "reason": "composite inputs not trusted"}
        out = rv.digest(self._base(sizing))
        self.assertIn("fail-closed", out)
        self.assertNotIn("invested", out)

    def test_digest_without_sizing_key_still_works(self):
        r = self._base(None)
        r.pop("sizing")
        out = rv.digest(r)
        self.assertNotIn("TARGET SIZING:", out)
        self.assertIn("Decision-support only", out)

    def test_uncategorized_names_are_warned(self):
        sizing = {
            "signalsTrusted": True, "investedWeight": 0.5, "cashWeight": 0.5,
            "bucketTotals": {}, "unclassifiedSymbols": ["MYSTERY"],
            "targets": [{"symbol": "MYSTERY", "targetWeight": 0.05,
                         "currentWeight": None, "delta": None, "action": "—"}],
        }
        out = rv.digest(self._base(sizing))
        self.assertIn("uncategorized", out)
        self.assertIn("MYSTERY", out)


class DigestPortfolioBlockTests(unittest.TestCase):
    def _base(self, holdings):
        return {
            "alerts": {"events": [], "emailed": {}},
            "composite": {"ranking": [{"symbol": "NVDA", "tag": "LEADER"}]},
            "benchmark": {"error": "no benchmark"},
            "holdings": holdings,
        }

    def _hp(self, **over):
        hp = {
            "nlv": 706.41, "heldCount": 2,
            "holdings": [
                {"symbol": "TE", "weightPct": 34.1, "plPercent": -27.3,
                 "trendState": "below-200d", "action": "HOLD-CORE",
                 "longTermHold": True},
                {"symbol": "XYZ", "weightPct": 10.0, "plPercent": -2.0,
                 "trendState": "below-200d", "action": "EXIT",
                 "longTermHold": False},
            ],
            "longTermHoldsBelowTrend": ["TE"],
            "gaps": {"overlapCount": 0, "heldNotOnWatchlist": ["TE", "XYZ"]},
            "accountScale": {"minPositionDollars": 10.60, "maxPositionDollars": 56.51},
        }
        hp.update(over)
        return hp

    def test_portfolio_block_leads_the_digest(self):
        out = rv.digest(self._base(self._hp()))
        self.assertIn("PORTFOLIO (live book)", out)
        # the book must appear before the watchlist tags
        self.assertLess(out.index("PORTFOLIO"), out.index("COMPOSITE TAGS"))

    def test_core_holds_marked_and_never_shown_as_exit(self):
        out = rv.digest(self._base(self._hp()))
        self.assertIn("HOLD-CORE [core]", out)
        self.assertIn("awareness only", out)

    def test_non_core_exit_is_shown(self):
        out = rv.digest(self._base(self._hp()))
        self.assertIn("XYZ", out)
        self.assertIn("EXIT", out)

    def test_account_scale_line_present(self):
        out = rv.digest(self._base(self._hp()))
        self.assertIn("1.5% position = $10.60", out)

    def test_holdings_error_is_surfaced(self):
        out = rv.digest(self._base({"error": "holdings join unavailable: boom"}))
        self.assertIn("PORTFOLIO: holdings join unavailable", out)

    def test_digest_without_holdings_still_works(self):
        r = self._base(None)
        r.pop("holdings")
        out = rv.digest(r)
        self.assertNotIn("PORTFOLIO", out)
        self.assertIn("COMPOSITE TAGS", out)


class MomentumSourceTests(unittest.TestCase):
    """Momentum must prefer the Schwab-derived artifact over plan-limited FMP data."""

    def test_momentum_path_is_used_verbatim_when_supplied(self):
        import json, tempfile, os
        art = {"ranking": [{"symbol": "NVDA", "blended": 12.3}], "signalsTrusted": True}
        with tempfile.TemporaryDirectory() as d:
            mpath = os.path.join(d, "mom.json")
            qpath = os.path.join(d, "q.json")
            bpath = os.path.join(d, "b.json")
            for p, payload in ((mpath, art), (qpath, []), (bpath, [])):
                with open(p, "w") as fh:
                    json.dump(payload, fh)
            # ``run`` deliberately persists production artifacts. This test
            # supplies intentionally incomplete fixture quotes, so persistence
            # must be mocked or the test would overwrite the real composite
            # with a fail-closed empty artifact.
            with (
                patch.object(rv.alerts, "run", return_value={"events": []}),
                patch.object(rv.composite, "save") as save_composite,
                patch.object(rv.benchmark, "save") as save_benchmark,
                patch.object(rv.sizing, "save") as save_sizing,
            ):
                r = rv.run(qpath, None, bpath, send=False, momentum_path=mpath)
        self.assertEqual(r["momentum"], art)
        save_composite.assert_called_once()
        save_benchmark.assert_not_called()
        save_sizing.assert_not_called()


if __name__ == "__main__":
    unittest.main()
