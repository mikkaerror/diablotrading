from __future__ import annotations

"""Tests for the read-only TOS formula drift audit."""

import unittest

import pandas as pd

from inferno_tos_formula_audit import build_formula_audit, formula_audit_text
from inferno_tos_formula_math import build_market_context_from_history


def history(rows: int = 80, *, start: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    close = [start + index * step for index in range(rows)]
    return pd.DataFrame(
        {
            "Close": close,
            "High": [value + 1.0 for value in close],
            "Low": [value - 1.0 for value in close],
            "Volume": [1_000_000 + index * 10_000 for index in range(rows)],
        }
    )


class InfernoTosFormulaAuditTests(unittest.TestCase):
    def test_clean_row_with_matching_values_has_no_flags(self) -> None:
        sample_history = history()
        context = build_market_context_from_history(sample_history, price=179.0)
        snapshot = {
            "generatedAt": "2026-05-25T09:00:00-06:00",
            "rows": [
                {
                    "ticker": "TEST",
                    "price": 179.0,
                    "rvol": context["rvol"],
                    "trend": context["trend"]["label"],
                    "support": context["support"],
                    "resistance": context["resistance"],
                    "ivRankChange": 0.17,
                    "momentumScore": 0.17,
                }
            ],
        }

        audit = build_formula_audit(
            snapshot,
            benchmark=None,
            history_loader=lambda _symbol: sample_history,
        )

        self.assertEqual(audit["verdict"], "formula-sync-clean")
        self.assertEqual(audit["checked"], 1)
        self.assertEqual(audit["rows"][0]["flags"], [])
        self.assertTrue(audit["authority"]["readOnly"])
        self.assertFalse(audit["authority"]["stagesTrades"])

    def test_mismatched_row_flags_formula_drift(self) -> None:
        sample_history = history()
        snapshot = {
            "rows": [
                {
                    "ticker": "TEST",
                    "price": 179.0,
                    "rvol": 0.5,
                    "trend": "Bearish",
                    "support": 10.0,
                    "resistance": 20.0,
                    "ivRankChange": 1.0,
                    "momentumScore": 0.0,
                }
            ],
        }

        audit = build_formula_audit(
            snapshot,
            benchmark=None,
            history_loader=lambda _symbol: sample_history,
        )

        self.assertEqual(audit["verdict"], "formula-drift-review")
        flags = set(audit["rows"][0]["flags"])
        self.assertIn("rvol-drift", flags)
        self.assertIn("trend-mismatch", flags)
        self.assertIn("support-drift", flags)
        self.assertIn("resistance-drift", flags)
        self.assertIn("momentum-drift", flags)
        self.assertIn("read-only diagnostic", formula_audit_text(audit))

    def test_missing_history_reports_insufficient_history_without_trade_authority(self) -> None:
        audit = build_formula_audit(
            {"rows": [{"ticker": "MISS", "price": 10.0}]},
            benchmark=None,
            history_loader=lambda _symbol: pd.DataFrame(),
        )

        self.assertEqual(audit["verdict"], "insufficient-history")
        self.assertEqual(audit["checked"], 0)
        self.assertEqual(audit["loadErrors"][0]["ticker"], "MISS")
        self.assertFalse(audit["authority"]["touchesBroker"])


if __name__ == "__main__":
    unittest.main()
