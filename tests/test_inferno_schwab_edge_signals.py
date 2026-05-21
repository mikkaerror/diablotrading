"""Contract tests for inferno_schwab_edge_signals.

Pinned invariants:
  - Module is research-only and promotable=False (broker submit stays OFF).
  - Tier 0 verdict fails when ANY of: quality<70, atm spread>20%, atm
    liquidity<50, or a hard fail flag is present.
  - Tier 0 verdict passes only when all four pass.
  - IV bucketing follows the documented thresholds.
  - Side-skew lean reports balanced / put-rich / call-rich correctly.
  - Lane is one of {tradable-research, calibration-watch, thin-data, no-chain}.
  - Aggregate summary produces non-negative lane counts that sum to row count.
  - Empty-source case returns a clean 'no-source' or 'no-rows' verdict
    without crashing.
  - Citations list includes HASBROUCK-1991, ALMGREN-CHRISS-2000.
"""

from __future__ import annotations

import unittest

from inferno_schwab_edge_signals import (
    EDGE_SIGNALS_STAGE,
    SIDE_SKEW_FLAG_ABS,
    TIER0_MAX_ATM_SPREAD_PCT,
    TIER0_MIN_ATM_LIQUIDITY,
    TIER0_MIN_QUALITY_SCORE,
    _classify_row,
    _iv_bucket,
    _lane_for_row,
    _regime_summary,
    _side_skew,
    _tier0_verdict,
    build_schwab_edge_signals,
    schwab_edge_signals_text,
)


def _clean_row(**overrides):
    """A fixture row that, by default, passes Tier 0 with a balanced Tier 1."""
    base = {
        "symbol": "TEST",
        "status": "ok",
        "quoteQualityScore": 85,
        "quoteQualityLabel": "institutional",
        "qualityFlags": [],
        "atmSpreadPct": 0.05,
        "atmLiquidityScore": 90,
        "atmImpliedVolatility": 0.40,
        "atmImpliedMovePct": 0.04,
        "atmExpectedMoveBucket": "normal",
        "sideStats": {
            "CALL": {"avgImpliedVolatility": 0.40},
            "PUT": {"avgImpliedVolatility": 0.40},
        },
    }
    base.update(overrides)
    return base


class Tier0Tests(unittest.TestCase):
    def test_clean_row_passes(self):
        verdict = _tier0_verdict(_clean_row())
        self.assertTrue(verdict["pass"])
        self.assertEqual(verdict["reasons"], [])

    def test_low_quality_fails(self):
        verdict = _tier0_verdict(_clean_row(quoteQualityScore=TIER0_MIN_QUALITY_SCORE - 1))
        self.assertFalse(verdict["pass"])
        self.assertTrue(any("quality<" in r for r in verdict["reasons"]))

    def test_wide_spread_fails(self):
        verdict = _tier0_verdict(_clean_row(atmSpreadPct=TIER0_MAX_ATM_SPREAD_PCT + 0.01))
        self.assertFalse(verdict["pass"])
        self.assertTrue(any("atm-spread>" in r for r in verdict["reasons"]))

    def test_thin_liquidity_fails(self):
        verdict = _tier0_verdict(_clean_row(atmLiquidityScore=TIER0_MIN_ATM_LIQUIDITY - 1))
        self.assertFalse(verdict["pass"])
        self.assertTrue(any("atm-liq<" in r for r in verdict["reasons"]))

    def test_hard_fail_flag(self):
        verdict = _tier0_verdict(_clean_row(qualityFlags=["empty-chain"]))
        self.assertFalse(verdict["pass"])
        self.assertTrue(any("hard-flags=" in r for r in verdict["reasons"]))


class Tier1Tests(unittest.TestCase):
    def test_iv_bucket_thresholds(self):
        self.assertEqual(_iv_bucket(None), "unknown")
        self.assertEqual(_iv_bucket(0.10), "very-low")
        self.assertEqual(_iv_bucket(0.30), "low")
        self.assertEqual(_iv_bucket(0.45), "normal")
        self.assertEqual(_iv_bucket(0.70), "elevated")
        self.assertEqual(_iv_bucket(1.20), "extreme")

    def test_side_skew_balanced(self):
        s = _side_skew(
            {"CALL": {"avgImpliedVolatility": 0.40}, "PUT": {"avgImpliedVolatility": 0.40}}
        )
        self.assertEqual(s["lean"], "balanced")

    def test_side_skew_put_rich(self):
        s = _side_skew(
            {
                "CALL": {"avgImpliedVolatility": 0.40},
                "PUT": {"avgImpliedVolatility": 0.40 + SIDE_SKEW_FLAG_ABS + 0.01},
            }
        )
        self.assertEqual(s["lean"], "put-rich")

    def test_side_skew_call_rich(self):
        s = _side_skew(
            {
                "CALL": {"avgImpliedVolatility": 0.40 + SIDE_SKEW_FLAG_ABS + 0.01},
                "PUT": {"avgImpliedVolatility": 0.40},
            }
        )
        self.assertEqual(s["lean"], "call-rich")

    def test_side_skew_unknown(self):
        s = _side_skew({"CALL": {}, "PUT": {}})
        self.assertEqual(s["lean"], "unknown")


class LaneTests(unittest.TestCase):
    def test_no_chain_when_status_not_ok(self):
        row = _clean_row(status="empty-chain")
        out = _classify_row(row)
        self.assertEqual(out["lane"], "no-chain")

    def test_thin_data_when_tier0_fails(self):
        row = _clean_row(quoteQualityScore=40, atmSpreadPct=0.45)
        out = _classify_row(row)
        self.assertEqual(out["lane"], "thin-data")
        self.assertTrue(any("Tier 0 fail" in n for n in out["notes"]))

    def test_calibration_watch_on_extreme_iv(self):
        row = _clean_row(atmImpliedVolatility=1.1)
        out = _classify_row(row)
        self.assertEqual(out["lane"], "calibration-watch")
        self.assertTrue(any("EXTREME" in n for n in out["notes"]))

    def test_calibration_watch_on_hot_move(self):
        row = _clean_row(atmExpectedMoveBucket="hot")
        out = _classify_row(row)
        self.assertEqual(out["lane"], "calibration-watch")

    def test_tradable_research_on_clean_normal_row(self):
        out = _classify_row(_clean_row())
        self.assertEqual(out["lane"], "tradable-research")
        # default lane should still attach at least one diagnostic note
        self.assertTrue(out["notes"])

    def test_lane_is_one_of_allowed(self):
        for row in (
            _clean_row(),
            _clean_row(status="empty-chain"),
            _clean_row(quoteQualityScore=40, atmSpreadPct=0.45),
            _clean_row(atmImpliedVolatility=1.5),
        ):
            lane = _lane_for_row(
                _tier0_verdict(row),
                {
                    "atmIvBucket": _iv_bucket(row.get("atmImpliedVolatility")),
                    "atmExpectedMoveBucket": row.get("atmExpectedMoveBucket") or "unknown",
                    "sideIvSkew": _side_skew(row.get("sideStats") or {}),
                },
                row,
            )
            self.assertIn(
                lane,
                {"tradable-research", "calibration-watch", "thin-data", "no-chain"},
            )


class RegimeSummaryTests(unittest.TestCase):
    def test_counts_sum_to_rows(self):
        rows = [
            _classify_row(_clean_row(symbol="A")),
            _classify_row(_clean_row(symbol="B", quoteQualityScore=40, atmSpreadPct=0.45)),
            _classify_row(_clean_row(symbol="C", atmImpliedVolatility=1.5)),
        ]
        summary = _regime_summary(rows)
        self.assertEqual(summary["rows"], 3)
        self.assertEqual(sum(summary["laneCounts"].values()), 3)

    def test_empty_rows_summary_safe(self):
        summary = _regime_summary([])
        self.assertEqual(summary["rows"], 0)
        self.assertEqual(summary["laneCounts"], {})


class BuildAndRenderTests(unittest.TestCase):
    """The live builder must produce a valid payload no matter what state
    the Schwab source file is in (configured, missing, error)."""

    def test_module_is_research_only(self):
        self.assertEqual(EDGE_SIGNALS_STAGE, "schwab-edge-signals-research-only")

    def test_build_runs_against_current_source(self):
        payload = build_schwab_edge_signals()
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["authorityChanged"])
        self.assertEqual(payload["stage"], EDGE_SIGNALS_STAGE)
        self.assertIn(
            payload["verdict"],
            {
                "no-source",
                "schwab-not-configured",
                "no-rows",
                "edge-actionable",
                "watch-only",
                "thin-data-only",
            },
        )
        # citations include the spread + execution literature
        self.assertIn("HASBROUCK-1991", payload["citations"])
        self.assertIn("ALMGREN-CHRISS-2000", payload["citations"])

    def test_text_render_includes_key_sections(self):
        payload = build_schwab_edge_signals()
        text = schwab_edge_signals_text(payload)
        self.assertIn("Inferno Schwab Edge Signals", text)
        self.assertIn("Verdict:", text)
        self.assertIn("Lane counts:", text)
        self.assertIn("Not built yet", text)
        self.assertIn("Reminders:", text)


if __name__ == "__main__":
    unittest.main()
