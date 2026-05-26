from __future__ import annotations

"""Tests for user-authored TOS custom metric capture."""

import tempfile
import unittest
from pathlib import Path

from inferno_tos_custom_metrics import (
    build_custom_metrics_report,
    discover_tos_custom_quote_sources,
    registry_payload,
    registry_with_tos_sources,
    summarize_custom_metrics,
    values_from_csv,
)


class InfernoTosCustomMetricsTests(unittest.TestCase):
    def test_values_from_csv_maps_registered_custom_columns_and_preserves_unmapped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tos-watchlist.csv"
            path.write_text(
                "Symbol,Strength,RVOL,My Secret Heat,Last\n"
                "NVDA,81.5,1.42,hot,100.25\n"
                "AMD,64.0,0.91,cool,52.10\n",
                encoding="utf-8",
            )

            values = values_from_csv(
                path,
                [
                    {
                        "key": "tos_strength",
                        "displayName": "TOS Strength",
                        "aliases": ["Strength"],
                        "modelRole": "confirmation-strength",
                        "formulaStatus": "captured",
                        "thinkScript": "plot Strength = close;",
                    },
                    {
                        "key": "tos_rvol",
                        "displayName": "TOS RVOL",
                        "aliases": ["RVOL"],
                        "modelRole": "participation",
                        "formulaStatus": "captured",
                        "thinkScript": "plot RVOL = volume;",
                    },
                ],
            )

        self.assertEqual(values["tickerCount"], 2)
        self.assertEqual(values["metricValueCount"], 6)
        self.assertIn("Strength", values["mappedColumns"])
        self.assertIn("RVOL", values["mappedColumns"])
        self.assertIn("My Secret Heat", values["unmappedColumns"])
        self.assertEqual(values["byTicker"]["NVDA"]["tos_strength"]["value"], 81.5)
        self.assertEqual(values["byTicker"]["NVDA"]["tos_my_secret_heat"]["raw"], "hot")

    def test_report_with_values_but_missing_formulas_requests_formula_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "tos.csv"
            csv_path.write_text("Ticker,Strength\nNVDA,81.5\n", encoding="utf-8")

            report = build_custom_metrics_report(values_csv=csv_path, registry_path=Path(tmpdir) / "missing.json")

        self.assertEqual(report["verdict"], "custom-values-captured-needs-formulas")
        self.assertTrue(report["authority"]["readOnly"])
        self.assertFalse(report["authority"]["touchesTos"])
        self.assertIn("tos_strength", report["missingFormulaMetrics"])

    def test_values_from_csv_maps_visible_tos_watchlist_metrics_from_screenshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tos-visible-columns.csv"
            path.write_text(
                "Ticker,RVOL,Pv52H,MOM,ATR%,Str...,SUP/RES *\n"
                "TEST,0.62,97.2,6.32,3.9%,73.6,Neutral\n",
                encoding="utf-8",
            )

            values = values_from_csv(path, registry_payload()["metrics"])

        metrics = values["byTicker"]["TEST"]
        self.assertEqual(values["unmappedColumns"], [])
        self.assertEqual(metrics["tos_rvol"]["value"], 0.62)
        self.assertEqual(metrics["tos_pv52h"]["value"], 97.2)
        self.assertEqual(metrics["tos_momentum"]["value"], 6.32)
        self.assertEqual(metrics["tos_atr_percent"]["value"], 3.9)
        self.assertEqual(metrics["tos_strength"]["value"], 73.6)
        self.assertEqual(metrics["tos_support_resistance_state"]["raw"], "Neutral")

    def test_summarize_custom_metrics_exposes_observed_tos_features_without_gating(self) -> None:
        metrics = {
            "tos_rvol": {"value": 1.61, "raw": "1.61", "hasThinkScript": False},
            "tos_pv52h": {"value": 71.1, "raw": "71.1", "hasThinkScript": False},
            "tos_momentum": {"value": 11.88, "raw": "11.88", "hasThinkScript": False},
            "tos_atr_percent": {"value": 4.3, "raw": "4.3%", "hasThinkScript": False},
            "tos_strength": {"value": 80.9, "raw": "80.9", "hasThinkScript": False},
            "tos_support_resistance_state": {"raw": "Near...", "value": None, "hasThinkScript": False},
        }

        summary = summarize_custom_metrics(metrics)

        self.assertEqual(summary["sourceStatus"], "captured")
        self.assertTrue(summary["observedOnly"])
        self.assertFalse(summary["formulaReproduced"])
        self.assertEqual(summary["rvolBand"], "active")
        self.assertEqual(summary["momentumSign"], "positive")
        self.assertEqual(summary["strengthBand"], "strong")
        self.assertEqual(summary["supportResistanceState"], "Near...")

    def test_report_without_csv_is_clear_about_needed_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report = build_custom_metrics_report(registry_path=Path(tmpdir) / "missing.json")

        self.assertEqual(report["verdict"], "needs-tos-custom-export")
        self.assertEqual(report["values"]["metricValueCount"], 0)
        self.assertIn("run_inferno_schwab_tos_metrics_sync", report["nextActions"][0])

    def test_registry_payload_is_user_editable(self) -> None:
        payload = registry_payload()

        self.assertIn("metrics", payload)
        self.assertGreaterEqual(len(payload["metrics"]), 6)
        self.assertIn("thinkScript", payload["metrics"][0])

    def test_discovers_and_merges_tos_custom_quote_cache_formulas(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "custom_quotes_cache.example.xml"
            path.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<PREFERENCES VERSION="7">
  <CUSTOM_QUOTES_CACHE>
    <QUOTE-0 AGG_PERIOD="d" CODE="def avgVol = Average(volume, 30);&#10;plot x = avgVol;" INDEX="0" NAME="RVOL" PRICE_TYPE="last" VERSION="1"/>
    <QUOTE-1 AGG_PERIOD="d" CODE="plot x = close;" INDEX="1" NAME="OptionsScanv4" PRICE_TYPE="last" VERSION="2"/>
  </CUSTOM_QUOTES_CACHE>
</PREFERENCES>
""",
                encoding="utf-8",
            )

            sources = discover_tos_custom_quote_sources([path])
            merged = registry_with_tos_sources(registry_payload()["metrics"], sources)

        by_key = {item["key"]: item for item in merged}
        self.assertEqual(len(sources), 2)
        self.assertEqual(by_key["tos_rvol"]["formulaStatus"], "captured-from-tos-cache")
        self.assertIn("Average(volume, 30)", by_key["tos_rvol"]["thinkScript"])
        self.assertEqual(by_key["tos_optionsscanv4"]["displayName"], "TOS OptionsScanv4")


if __name__ == "__main__":
    unittest.main()
