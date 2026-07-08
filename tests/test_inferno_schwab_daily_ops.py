from __future__ import annotations

"""Regression tests for the Schwab daily operations layer."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import inferno_config
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
                "paperLiquidityPass": True,
                "liveLiquidityPass": True,
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
                "paperLiquidityPass": False,
                "paperLiquidityBlockReason": "atm-window-spread 30.00% exceeds hard-wide ceiling 25%",
                "liveLiquidityPass": False,
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
                        "paperLiquidityPass": True,
                        "liveLiquidityPass": True,
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
                        "atmWindowMedianSpreadPct": 0.04,
                        "atmWindowOpenInterest": 500,
                        "atmLiquidityScore": 100,
                        "paperLiquidityPass": True,
                        "liveLiquidityPass": True,
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

    def test_load_schwab_env_syncs_read_only_chain_config_after_config_import(self) -> None:
        original_enabled = inferno_config.SCHWAB_OPTIONS_ENABLED
        original_token_file = inferno_config.SCHWAB_TOKEN_FILE
        original_strike_count = inferno_config.SCHWAB_OPTIONS_STRIKE_COUNT
        options_module = ops.sys.modules.get("inferno_schwab_options")
        original_options_enabled = getattr(options_module, "SCHWAB_OPTIONS_ENABLED", None)
        original_options_token_file = getattr(options_module, "SCHWAB_TOKEN_FILE", None)
        original_options_strike_count = getattr(options_module, "SCHWAB_OPTIONS_STRIKE_COUNT", None)
        original_options_chain_params = getattr(options_module, "DEFAULT_CHAIN_PARAMS", None)
        with TemporaryDirectory() as temp_dir:
            token_path = Path(temp_dir) / "schwab_token.json"
            env_path = Path(temp_dir) / ".env.schwab"
            env_path.write_text(
                "\n".join(
                    [
                        "SCHWAB_OPTIONS_ENABLED=1",
                        f"SCHWAB_TOKEN_FILE={token_path}",
                        "SCHWAB_API_BASE_URL=https://api.schwabapi.com",
                        "SCHWAB_OPTIONS_STRIKE_COUNT=16",
                    ]
                ),
                encoding="utf-8",
            )
            try:
                values = ops.load_schwab_env(env_path)

                self.assertEqual(values["SCHWAB_OPTIONS_ENABLED"], "1")
                self.assertTrue(inferno_config.SCHWAB_OPTIONS_ENABLED)
                self.assertEqual(inferno_config.SCHWAB_TOKEN_FILE, token_path)
                self.assertEqual(inferno_config.SCHWAB_OPTIONS_STRIKE_COUNT, 16)
            finally:
                inferno_config.SCHWAB_OPTIONS_ENABLED = original_enabled
                inferno_config.SCHWAB_TOKEN_FILE = original_token_file
                inferno_config.SCHWAB_OPTIONS_STRIKE_COUNT = original_strike_count
                if options_module is not None:
                    options_module.SCHWAB_OPTIONS_ENABLED = original_options_enabled
                    options_module.SCHWAB_TOKEN_FILE = original_options_token_file
                    options_module.SCHWAB_OPTIONS_STRIKE_COUNT = original_options_strike_count
                    options_module.DEFAULT_CHAIN_PARAMS = original_options_chain_params

    def test_top_priority_slate_filters_and_sorts_tracker_rows(self) -> None:
        symbols = ops.top_priority_slate(
            {
                "rows": [
                    {"ticker": "LATE", "priority": 99, "setupRec": "Straddle", "daysUntilEarnings": 45},
                    {"ticker": "AVOID", "priority": 98, "setupRec": "Avoid", "daysUntilEarnings": 2},
                    {"ticker": "AVGO", "priority": 6, "readiness": 90, "setupRec": "Straddle", "daysUntilEarnings": 9},
                    {"ticker": "KEYS", "priority": 8, "readiness": 80, "setupRec": "Vertical Call", "daysUntilEarnings": 14},
                    {"ticker": "OTEX", "priority": 8, "readiness": 95, "setupRec": "Iron Condor", "daysUntilEarnings": 18},
                ]
            },
            n=3,
        )

        self.assertEqual(symbols, ["OTEX", "KEYS", "AVGO"])

    def test_default_symbol_universe_prioritizes_active_paper_and_strategy_rows(self) -> None:
        payloads = {
            ops.LIVE_ACCOUNT_SYNC_FILE: {
                "positions": [
                    {"symbol": "TE"},
                    {"symbol": "HIVE"},
                ]
            },
            ops.PAPER_TEST_DIRECTOR_FILE: {
                "autoPaperSlate": [{"ticker": "MOD"}],
                "researchWatchlist": [{"ticker": "FCX"}],
                "constructionWatchlist": [{"ticker": "GLW"}],
            },
            ops.STRATEGY_ALTERNATIVE_SCORER_FILE: {
                "scorecards": [{"ticker": "GOOG"}, {"ticker": "TXN"}],
            },
            ops.SNAPSHOT_FILE: {
                "rows": [
                    {"ticker": "AVGO", "priority": 7, "readiness": 85, "setupRec": "Straddle", "daysUntilEarnings": 10},
                    {"ticker": "LUNR", "priority": 9, "readiness": 70, "setupRec": "Vertical Call", "daysUntilEarnings": 8},
                    {"ticker": "TE", "priority": 99, "readiness": 99, "setupRec": "Straddle", "daysUntilEarnings": 5},
                    {"ticker": "OLD", "priority": 95, "readiness": 99, "setupRec": "Straddle", "daysUntilEarnings": 42},
                    {"ticker": "SKIP", "priority": 94, "readiness": 99, "setupRec": "Avoid", "daysUntilEarnings": 1},
                ]
            },
            ops.EXECUTION_QUEUE_FILE: {
                "items": [{"ticker": "CCI"}],
                "readyTickers": ["AEHR"],
            },
            ops.APPROVAL_QUEUE_FILE: {"items": [{"symbol": "MRVL"}]},
            ops.WATCHLIST_INPUT_FILE: {"tickers": ["TXN"]},
        }

        with patch.object(ops, "load_json_file", side_effect=lambda path: payloads.get(path, {})):
            symbols = ops.default_symbol_universe(limit=10)

        self.assertEqual(
            symbols,
            ["TE", "HIVE", "MOD", "FCX", "GLW", "GOOG", "TXN", "CCI", "AEHR", "MRVL"],
        )


if __name__ == "__main__":
    unittest.main()
