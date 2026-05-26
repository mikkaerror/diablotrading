from __future__ import annotations

"""Tests for Schwab-driven TOS custom metric sync."""

import tempfile
import unittest
from pathlib import Path

from inferno_schwab_price_history import build_report
from inferno_schwab_tos_metrics_sync import build_sync_report
from inferno_tos_custom_metrics import build_custom_metrics_report, summarize_custom_metrics


def sample_history_payload(symbol: str = "TEST", days: int = 30) -> dict[str, object]:
    """Build deterministic daily candles with enough bars for all formulas."""
    base_ms = 1_700_000_000_000
    candles = []
    for day in range(1, days + 1):
        candles.append(
            {
                "datetime": base_ms + day * 86_400_000,
                "open": float(day),
                "high": float(day + 1),
                "low": float(day - 1),
                "close": float(day),
                "volume": 3000 if day == days else 1000,
            }
        )
    return {"symbol": symbol, "empty": False, "candles": candles}


class SchwabTosMetricsSyncTests(unittest.TestCase):
    def test_schwab_history_report_becomes_canonical_custom_metrics(self) -> None:
        history_report = build_report(
            ["TEST"],
            fixture_payloads={"TEST": sample_history_payload()},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            custom_report = build_custom_metrics_report(
                schwab_history_report=history_report,
                registry_path=Path(tmpdir) / "missing-registry.json",
            )

        values = custom_report["values"]
        metrics = values["byTicker"]["TEST"]
        summary = summarize_custom_metrics(metrics)

        self.assertEqual(custom_report["verdict"], "custom-metrics-accounted")
        self.assertEqual(values["sourceProvider"], "schwab-price-history")
        self.assertEqual(values["tickerCount"], 1)
        self.assertEqual(values["metricValueCount"], 6)
        self.assertEqual(metrics["tos_rvol"]["value"], 2.81)
        self.assertEqual(metrics["tos_atr_percent"]["raw"], "6.7%")
        self.assertTrue(metrics["tos_rvol"]["hasThinkScript"])
        self.assertTrue(summary["formulaReproduced"])
        self.assertEqual(summary["sourceStatus"], "captured")

    def test_sync_report_exposes_bridge_counts_without_authority_change(self) -> None:
        history_report = build_report(
            ["TEST"],
            fixture_payloads={"TEST": sample_history_payload()},
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_report = build_custom_metrics_report(
                schwab_history_report=history_report,
                registry_path=Path(tmpdir) / "missing-registry.json",
            )

        sync_report = build_sync_report(
            price_history_report=history_report,
            custom_metrics_report=custom_report,
            symbols=["TEST"],
        )

        self.assertFalse(sync_report["authorityChanged"])
        self.assertFalse(sync_report["brokerSubmitAllowed"])
        self.assertEqual(sync_report["sourceStatus"], "fixture")
        self.assertEqual(sync_report["customMetricsVerdict"], "custom-metrics-accounted")
        self.assertEqual(sync_report["metricValueCount"], 6)


if __name__ == "__main__":
    unittest.main()
