from __future__ import annotations

"""Regression tests for the Schwab daily operations layer."""

import unittest

import inferno_schwab_daily_ops as ops


class SchwabDailyOpsTests(unittest.TestCase):
    """Pin the read-only classification rules used by daily operations."""

    def test_clean_chain_classifies_as_tradable_research(self) -> None:
        row = ops.classify_chain_row(
            {
                "symbol": "NVDA",
                "quoteQualityScore": 86,
                "quoteQualityLabel": "institutional",
                "atmSpreadQuality": "tight",
                "atmLiquidityScore": 100,
                "qualityFlags": [],
            }
        )

        self.assertEqual(row["lane"], "tradable-research")
        self.assertIn("risk gates", row["action"])

    def test_wide_poor_chain_classifies_as_avoid(self) -> None:
        row = ops.classify_chain_row(
            {
                "symbol": "AVGO",
                "quoteQualityScore": 48,
                "quoteQualityLabel": "poor",
                "atmSpreadQuality": "untradeable",
                "atmLiquidityScore": 42,
                "qualityFlags": ["wide-atm-spread", "thin-atm-liquidity"],
            }
        )

        self.assertEqual(row["lane"], "avoid-chain")
        self.assertTrue(any("wide-atm-spread" in reason for reason in row["reasons"]))

    def test_build_ops_report_keeps_authority_locked(self) -> None:
        report = ops.build_ops_report(
            {
                "status": "fixture",
                "configured": True,
                "generatedAt": "2026-05-20T12:00:00-06:00",
                "rows": [
                    {
                        "symbol": "NVDA",
                        "quoteQualityScore": 86,
                        "quoteQualityLabel": "institutional",
                        "atmSpreadQuality": "tight",
                        "atmLiquidityScore": 100,
                        "qualityFlags": [],
                    }
                ],
                "errors": [],
            },
            symbols=["NVDA"],
        )

        self.assertTrue(report["researchOnly"])
        self.assertFalse(report["brokerSubmitAllowed"])
        self.assertFalse(report["liveTradingAllowed"])
        self.assertEqual(report["laneCounts"]["tradable-research"], 1)

    def test_render_ops_report_surfaces_key_fields(self) -> None:
        payload = ops.build_ops_report(
            {
                "status": "fixture",
                "configured": True,
                "generatedAt": "2026-05-20T12:00:00-06:00",
                "rows": [
                    {
                        "symbol": "NVDA",
                        "quoteQualityScore": 86,
                        "quoteQualityLabel": "institutional",
                        "atmSpreadQuality": "tight",
                        "atmSpreadPct": 0.04,
                        "atmLiquidityScore": 100,
                        "atmImpliedMovePct": 0.059,
                        "atmExpectedMoveDollar": 13.17,
                        "atmStraddleMid": 13.17,
                        "qualityFlags": [],
                    }
                ],
                "errors": [],
            },
            symbols=["NVDA"],
        )

        rendered = ops.render_ops_report(payload)

        self.assertIn("Daily Schwab values to use", rendered)
        self.assertIn("NVDA: tradable-research", rendered)
        self.assertIn("quoteQualityScore / quoteQualityLabel", rendered)


if __name__ == "__main__":
    unittest.main()
