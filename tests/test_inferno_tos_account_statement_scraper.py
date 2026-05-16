from __future__ import annotations

"""Regression tests for the read-only TOS Account Statement scraper."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_tos_account_statement_scraper as scraper
from inferno_tos_account_statement_scraper import (
    merge_equities_and_pnl,
    parse_key_value_row,
    parse_profit_loss_row,
    save_account_statement_report,
    scrape_account_statement,
)


class TOSAccountStatementScraperTests(unittest.TestCase):
    """Verify the scraper's local parsing logic stays stable."""

    def test_merge_equities_and_pnl_derives_trade_price(self) -> None:
        rows = merge_equities_and_pnl(
            ["FLR, , , FLUOR CORP NEW, +4, 43.44, , 43.44, , $173.76, 0"],
            ["FLR, FLUOR CORP NEW, $1.24, +0.72%, $0.52, $1.24, $0.00, $173.76, 0"],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "FLR")
        self.assertEqual(rows[0]["qty"], 4)
        self.assertAlmostEqual(rows[0]["mark"], 43.44)
        self.assertAlmostEqual(rows[0]["plOpen"], 1.24)
        self.assertAlmostEqual(rows[0]["derivedTradePrice"], 43.13)

    def test_merge_skips_overall_totals_footer(self) -> None:
        rows = merge_equities_and_pnl(
            ["OVERALL TOTALS, 0, , , , , $547.74, 0"],
            [],
        )
        self.assertEqual(rows, [])

    def test_parse_profit_loss_row_maps_visible_columns(self) -> None:
        row = parse_profit_loss_row("THR, THERMON GROUP HLDGS, $35.57, +22.04%, $0.00, $35.57, $0.00, $196.98, 0")
        self.assertEqual(row["symbol"], "THR")
        self.assertAlmostEqual(row["plOpen"], 35.57)
        self.assertAlmostEqual(row["plPercent"], 22.04)
        self.assertAlmostEqual(row["markValue"], 196.98)

    def test_parse_key_value_row_reads_summary_pairs(self) -> None:
        self.assertEqual(parse_key_value_row("Net Liquidating Value, $571.89"), ("Net Liquidating Value", "$571.89"))

    def test_parse_key_value_row_preserves_comma_formatted_money(self) -> None:
        self.assertEqual(
            parse_key_value_row("Net Liquidating Value, $2,900.81"),
            ("Net Liquidating Value", "$2,900.81"),
        )

    def test_save_account_statement_report_preserves_last_good_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            latest_file = base / "latest.json"
            last_good_file = base / "last_good.json"
            text_file = base / "latest.txt"
            good_report = {"generatedAt": "2026-05-09T21:00:00-06:00", "ok": True, "message": "ok", "positions": []}
            failed_report = {"generatedAt": "2026-05-10T01:00:00-06:00", "ok": False, "message": "window missing", "positions": []}

            with (
                patch.object(scraper, "ACCOUNT_STATEMENT_FILE", latest_file),
                patch.object(scraper, "ACCOUNT_STATEMENT_LAST_GOOD_FILE", last_good_file),
                patch.object(scraper, "ACCOUNT_STATEMENT_TEXT_FILE", text_file),
            ):
                save_account_statement_report(good_report)
                save_account_statement_report(failed_report)

            preserved = json.loads(last_good_file.read_text(encoding="utf-8"))
            latest = json.loads(latest_file.read_text(encoding="utf-8"))
            self.assertTrue(preserved["ok"])
            self.assertEqual(preserved["_lastRefreshFailure"], "window missing")
            self.assertFalse(latest["ok"])

    @patch("inferno_tos_account_statement_scraper.save_account_statement_report")
    @patch(
        "inferno_tos_account_statement_scraper.scroll_area_children",
        return_value=[
            {"index": 1, "role": "AXCheckBox", "description": "Equities", "value": "1", "label": "Equities"},
            {"index": 2, "role": "AXStaticText", "description": "$547.74", "value": "$547.74", "label": "$547.74"},
            {"index": 3, "role": "AXTable", "description": "table", "value": "0", "label": "table"},
            {"index": 4, "role": "AXCheckBox", "description": "Profits and Losses", "value": "0", "label": "Profits and Losses"},
            {"index": 5, "role": "AXStaticText", "description": "$41.89", "value": "$41.89", "label": "$41.89"},
            {"index": 6, "role": "AXTable", "description": "table", "value": "0", "label": "table"},
            {"index": 7, "role": "AXCheckBox", "description": "Account Summary", "value": "1", "label": "Account Summary"},
            {"index": 8, "role": "AXTable", "description": "table", "value": "0", "label": "table"},
        ],
    )
    @patch(
        "inferno_tos_account_statement_scraper.table_rows",
        side_effect=[
            ["FLR, , , FLUOR CORP NEW, +4, 43.44, , 43.44, , $173.76, 0"],
            ["FLR, FLUOR CORP NEW, $1.24, +0.72%, $0.52, $1.24, $0.00, $173.76, 0"],
            ["Net Liquidating Value, $571.89"],
        ],
    )
    @patch("inferno_tos_account_statement_scraper.statement_scroll_area_index", return_value=15)
    @patch("inferno_tos_account_statement_scraper.monitor_group_children", return_value=[])
    @patch(
        "inferno_tos_account_statement_scraper.probe_tos_session",
        side_effect=[
            {
                "ok": True,
                "summary": "main window live via thinkorswim | current panel MarketWatch | safety safe | account live",
                "currentPanel": "MarketWatch",
                "monitorSubpanel": None,
                "accountMode": "live",
                "accountSuffixCandidates": ["11111234"],
            },
            {
                "ok": True,
                "summary": "main window live via thinkorswim | current panel Monitor/Account Statement | safety safe | account live",
                "currentPanel": "Monitor",
                "monitorSubpanel": "Account Statement",
                "matchedProcessName": "thinkorswim",
                "splitGroupIndex": 26,
                "monitorGroupIndex": 82,
                "accountMode": "live",
                "accountSuffixCandidates": ["11111234"],
                "labeledButtons": [{"label": "Dump Account", "index": 14}],
            },
        ],
    )
    @patch(
        "inferno_tos_account_statement_scraper.route_to_account_statement",
        return_value={"ok": True, "status": "account-statement-routed", "message": "routed thinkorswim into Monitor > Account Statement"},
    )
    def test_scrape_account_statement_routes_existing_window_when_needed(
        self,
        route_mock,
        _probe_mock,
        _monitor_children_mock,
        _scroll_index_mock,
        _table_rows_mock,
        _scroll_children_mock,
        _save_mock,
    ) -> None:
        report = scrape_account_statement(route_if_needed=True)
        self.assertTrue(report["ok"])
        self.assertEqual(report["positions"][0]["symbol"], "FLR")
        route_mock.assert_called_once_with(dry_run=False, allow_recovery=False)


if __name__ == "__main__":
    unittest.main()
