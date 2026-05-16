from __future__ import annotations

"""Regression tests for ticker-universe hydration auditing."""

import unittest
from unittest.mock import patch

import pandas as pd

from morning_inferno_pipeline import (
    build_ticker_universe_audit,
    read_sheet_rows_from_table,
    repair_setup_and_trigger_columns,
    sync_price_column_if_needed,
)


HEADERS = [
    "Ticker",
    "ATR%",
    "IV Rank",
    "Next Earnings",
    "Price",
    "EPS",
    "PE",
    "Days until earnings",
    "Setup Rec",
    '"Urgency"',
    "Signal Trigger",
    "Confidence (3 MAX)",
    "IV Rank Change (5-day delta)",
    "ATR% Z-Score",
    "20 Day ATR",
    "REC 1-13",
    "Rec2",
    "Value Score",
    "Momentum Score",
    "Squeeze Score",
    "Ready Score",
    "Priority",
    "$RVOL",
    "Trend",
    "Support",
    "Resistance",
    "% To Support",
    "% To Resistance",
]


def make_row(**overrides: str) -> list[str]:
    """Build one fake tracker row with stable defaults."""
    values = {
        "Ticker": "AAPL",
        "ATR%": "4.2",
        "IV Rank": "35.0",
        "Next Earnings": "5/20/2026",
        "Price": "$200.00",
        "EPS": "4.2",
        "PE": "30.0",
        "Days until earnings": "15",
        "Setup Rec": "Vertical Call",
        '"Urgency"': "Watchlist",
        "Signal Trigger": "✅",
        "Confidence (3 MAX)": "2",
        "IV Rank Change (5-day delta)": "0.11",
        "ATR% Z-Score": "1.2",
        "20 Day ATR": "$8.50",
        "REC 1-13": "VERTICAL (11)",
        "Rec2": "STRADDLE (4.2)",
        "Value Score": "1.10",
        "Momentum Score": "0.70",
        "Squeeze Score": "1.00",
        "Ready Score": "0.95",
        "Priority": "5.25",
        "$RVOL": "1.35",
        "Trend": "Bullish",
        "Support": "188.0",
        "Resistance": "212.0",
        "% To Support": "6.0",
        "% To Resistance": "6.0",
    }
    values.update(overrides)
    return [values.get(header, "") for header in HEADERS]


class InfernoTickerUniverseAuditTests(unittest.TestCase):
    """Verify new-ticker hydration problems cannot hide in the tracker."""

    def test_audit_reports_healthy_when_tracker_row_is_fully_hydrated(self) -> None:
        raw_rows = [make_row()]
        enriched_rows = read_sheet_rows_from_table(HEADERS, raw_rows)

        audit = build_ticker_universe_audit(HEADERS, raw_rows, enriched_rows)

        self.assertTrue(audit["ok"])
        self.assertEqual(audit["verdict"], "healthy")
        self.assertEqual(audit["counts"]["criticalIssueCount"], 0)
        self.assertEqual(audit["counts"]["advisoryIssueCount"], 0)

    def test_audit_flags_duplicates_missing_cells_and_bad_levels(self) -> None:
        raw_rows = [
            make_row(Ticker="AAPL", Price="", Resistance="180.0"),
            make_row(Ticker="AAPL"),
        ]
        enriched_rows = read_sheet_rows_from_table(HEADERS, raw_rows)

        audit = build_ticker_universe_audit(HEADERS, raw_rows, enriched_rows)

        self.assertFalse(audit["ok"])
        self.assertEqual(audit["verdict"], "attention")
        self.assertIn("AAPL", audit["issues"]["duplicateTickers"])
        self.assertEqual(audit["counts"]["missingCoreRows"], 1)
        self.assertEqual(audit["counts"]["invalidPriceRows"], 1)
        self.assertEqual(audit["counts"]["invalidLevelRows"], 1)

    def test_audit_keeps_unknown_earnings_as_advisory_not_critical(self) -> None:
        raw_rows = [
            make_row(Ticker="SHOP", PE="", **{"Days until earnings": "999"}),
        ]
        enriched_rows = read_sheet_rows_from_table(HEADERS, raw_rows)

        audit = build_ticker_universe_audit(HEADERS, raw_rows, enriched_rows)

        self.assertTrue(audit["ok"])
        self.assertEqual(audit["verdict"], "healthy-with-advisories")
        self.assertEqual(audit["counts"]["criticalIssueCount"], 0)
        self.assertEqual(audit["counts"]["unknownEarningsRows"], 1)
        self.assertEqual(audit["counts"]["missingLongTermRows"], 1)
        self.assertIn("SHOP", audit["advisoryTickers"])

    @patch("morning_inferno_pipeline.update_sheet_range")
    @patch("morning_inferno_pipeline.download_history_with_retries")
    @patch("morning_inferno_pipeline.get_sheet")
    def test_price_sync_repairs_invalid_prices_from_history(
        self,
        mock_get_sheet,
        mock_download_history,
        mock_update_sheet_range,
    ) -> None:
        class FakeSheet:
            def get_all_values(self):
                return [HEADERS, make_row(Ticker="PSTG", Price="#N/A")]

        mock_get_sheet.return_value = FakeSheet()
        mock_download_history.return_value = pd.DataFrame({"Close": [61.23]})

        result = sync_price_column_if_needed(backtest_root="unused", sheet_name="unused")  # type: ignore[arg-type]

        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["repairedTickers"], ["PSTG"])
        mock_update_sheet_range.assert_called_once()
        args = mock_update_sheet_range.call_args[0]
        self.assertEqual(args[1], "E2:E2")
        self.assertEqual(args[2], [["$61.23"]])

    @patch("morning_inferno_pipeline.update_sheet_range")
    @patch("morning_inferno_pipeline.download_history_with_retries")
    @patch("morning_inferno_pipeline.get_sheet")
    def test_price_sync_skips_symbols_with_no_history(
        self,
        mock_get_sheet,
        mock_download_history,
        mock_update_sheet_range,
    ) -> None:
        class FakeSheet:
            def get_all_values(self):
                return [HEADERS, make_row(Ticker="COMM", Price="#N/A")]

        mock_get_sheet.return_value = FakeSheet()
        mock_download_history.return_value = pd.DataFrame(
            columns=["Open", "High", "Low", "Close", "Adj Close", "Volume"]
        )

        result = sync_price_column_if_needed(backtest_root="unused", sheet_name="unused")  # type: ignore[arg-type]

        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["repairedTickers"], [])
        mock_update_sheet_range.assert_not_called()

    @patch("morning_inferno_pipeline.update_sheet_range")
    @patch("morning_inferno_pipeline.google_sheets_call", side_effect=lambda _label, fn: fn())
    @patch("morning_inferno_pipeline.get_sheet")
    def test_setup_trigger_repair_cleans_formula_errors(
        self,
        mock_get_sheet,
        _mock_google_sheets_call,
        mock_update_sheet_range,
    ) -> None:
        class FakeSheet:
            def get_all_values(self):
                return [HEADERS, make_row(Ticker="COMM", **{"Setup Rec": "#VALUE!", "Signal Trigger": "#VALUE!"})]

        mock_get_sheet.return_value = FakeSheet()

        result = repair_setup_and_trigger_columns(backtest_root="unused", sheet_name="unused")  # type: ignore[arg-type]

        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["setupColumn"], "I")
        self.assertEqual(result["triggerColumn"], "K")
        self.assertEqual(mock_update_sheet_range.call_count, 2)
        self.assertEqual(mock_update_sheet_range.call_args_list[0].args[1], "I2:I2")
        self.assertEqual(mock_update_sheet_range.call_args_list[0].args[2], [["Avoid"]])
        self.assertEqual(mock_update_sheet_range.call_args_list[1].args[1], "K2:K2")
        self.assertEqual(mock_update_sheet_range.call_args_list[1].args[2], [["❌"]])


if __name__ == "__main__":
    unittest.main()
