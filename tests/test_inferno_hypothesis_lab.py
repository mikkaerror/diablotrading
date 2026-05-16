from __future__ import annotations

"""Regression tests for the hypothesis lab.

The lab must:
- never set ``promotable=True`` or ``researchOnly=False``
- generate hypotheses across all five templates when the inputs warrant it
- rank by testConfidence
- produce deterministic ids that the ledger can dedupe on
- render an operator-readable memo
"""

import unittest

from inferno_hypothesis_lab import (
    HYPOTHESIS_LAB_STAGE,
    _test_confidence,
    build_hypothesis_lab,
    hypothesis_lab_text,
)


def _record(
    ticker: str,
    pnl: float | None,
    *,
    strategy: str = "LONG_STRADDLE",
    regime: str = "bullish-normal",
    sector: str = "Technology",
    iv_rank: float = 30.0,
    days_to_earnings: float = 5,
) -> dict:
    return {
        "ticker": ticker,
        "strategy": strategy,
        "regime": regime,
        "sector": sector,
        "ivRank": iv_rank,
        "daysToEarnings": days_to_earnings,
        "riskVerdict": {"metrics": {"maxLossDollars": 100.0}},
        "outcome": {
            "status": "closed" if pnl is not None else "open",
            "estimatedPnl": pnl,
        },
    }


class HypothesisLabTests(unittest.TestCase):
    def test_research_only_is_immutable(self) -> None:
        payload = build_hypothesis_lab(shadow_records=[], pending_records=[])
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertEqual(payload["stage"], HYPOTHESIS_LAB_STAGE)

    def test_generates_dimension_edge_hypothesis(self) -> None:
        shadow = [_record(f"T{i}", pnl=1.0) for i in range(6)]
        shadow.append(_record("T6", pnl=-1.0))
        payload = build_hypothesis_lab(shadow_records=shadow, pending_records=[])
        templates = {h["template"] for h in payload["topHypotheses"]}
        self.assertIn("dimension-edge", templates)

    def test_generates_anti_edge_hypothesis(self) -> None:
        # 5 losses for CALL_DEBIT_SPREAD in bearish regime.
        # Wilson upper for 0/6 ≈ 0.39 which is below the 0.42 anti-edge floor;
        # 5 losses would not be enough evidence to call an anti-edge.
        shadow = [
            _record(f"L{i}", pnl=-1.0, strategy="CALL_DEBIT_SPREAD", regime="bearish")
            for i in range(6)
        ]
        payload = build_hypothesis_lab(shadow_records=shadow, pending_records=[])
        templates = {h["template"] for h in payload["allHypotheses"]}
        self.assertIn("dimension-anti-edge", templates)

    def test_pending_match_to_edge_surfaces(self) -> None:
        shadow = [_record(f"T{i}", pnl=1.0) for i in range(6)]
        pending = [_record("PEND", pnl=None)]
        payload = build_hypothesis_lab(shadow_records=shadow, pending_records=pending)
        templates = {h["template"] for h in payload["allHypotheses"]}
        self.assertIn("pending-match-edge", templates)

    def test_pending_mismatch_with_anti_edge_surfaces(self) -> None:
        # Wilson upper for 0/6 ≈ 0.39 which is below the 0.42 anti-edge floor;
        # 5 losses would not be enough evidence to call an anti-edge.
        shadow = [
            _record(f"L{i}", pnl=-1.0, strategy="CALL_DEBIT_SPREAD", regime="bearish")
            for i in range(6)
        ]
        pending = [
            _record("PEND", pnl=None, strategy="CALL_DEBIT_SPREAD", regime="bearish")
        ]
        payload = build_hypothesis_lab(shadow_records=shadow, pending_records=pending)
        templates = {h["template"] for h in payload["allHypotheses"]}
        self.assertIn("pending-mismatch", templates)

    def test_insufficient_but_trending_when_small_cell_wins(self) -> None:
        # Only 2 records in a Vertical Call cell, both wins.
        shadow = [
            _record("X1", pnl=1.0, strategy="Vertical Call"),
            _record("X2", pnl=1.0, strategy="Vertical Call"),
        ]
        payload = build_hypothesis_lab(shadow_records=shadow, pending_records=[])
        templates = {h["template"] for h in payload["allHypotheses"]}
        self.assertIn("insufficient-but-trending", templates)

    def test_test_confidence_increases_with_evidence(self) -> None:
        low = {
            "sampleSize": 2,
            "winRateLower": 0.2,
            "expectancyLower": -0.5,
        }
        high = {
            "sampleSize": 30,
            "winRateLower": 0.6,
            "expectancyLower": 0.5,
        }
        self.assertLess(_test_confidence(low), _test_confidence(high))

    def test_hypotheses_are_sorted_by_test_confidence(self) -> None:
        shadow = [_record(f"T{i}", pnl=1.0) for i in range(6)]
        payload = build_hypothesis_lab(shadow_records=shadow, pending_records=[])
        top = payload["topHypotheses"]
        confidences = [h["testConfidence"] for h in top]
        self.assertEqual(confidences, sorted(confidences, reverse=True))

    def test_ids_are_deterministic_across_runs(self) -> None:
        shadow = [_record(f"T{i}", pnl=1.0) for i in range(6)]
        first = build_hypothesis_lab(shadow_records=shadow, pending_records=[])
        second = build_hypothesis_lab(shadow_records=shadow, pending_records=[])
        self.assertEqual(
            sorted(h["id"] for h in first["allHypotheses"]),
            sorted(h["id"] for h in second["allHypotheses"]),
        )

    def test_text_renderer_includes_each_section(self) -> None:
        shadow = [_record(f"T{i}", pnl=1.0) for i in range(6)]
        payload = build_hypothesis_lab(shadow_records=shadow, pending_records=[])
        rendered = hypothesis_lab_text(payload)
        self.assertIn("Hypothesis Lab", rendered)
        self.assertIn("Top hypotheses", rendered)
        self.assertIn("Reminders:", rendered)


if __name__ == "__main__":
    unittest.main()
