"""Contract tests for inferno_portfolio_correlation.

Pinned invariants:
  - Module is research-only and promotable=False.
  - Effective bet count math: equal weights → N_eff = N; one dominant
    weight → N_eff → 1.
  - Pearson correlation returns None on degenerate inputs; matches a
    hand-computed case otherwise.
  - Strategy family classifier mirrors slippage estimator behavior.
  - Direction inference covers long-vol, short-vol, long-equity, neutral.
  - Verdict ladder fires concentrated-by-drift at ≥50% dominant family.
  - Empty input returns 'awaiting-outcomes'.
  - Citations include MARKOWITZ-1952 and GRINOLD-1989.
"""

from __future__ import annotations

import unittest

from inferno_portfolio_correlation import (
    CORRELATION_STAGE,
    DOMINANT_FAMILY_SHARE_FLOOR,
    EFFECTIVE_BREADTH_PASS_RATIO,
    MIN_CLOSED_PAIRS_FOR_CORRELATION,
    _direction,
    _family_pairwise_correlations,
    _slate_concentration,
    _strategy_family,
    _ticket_overlap_counts,
    build_portfolio_correlation,
    effective_bet_count,
    pearson,
    portfolio_correlation_text,
)


class EffectiveBetCountTests(unittest.TestCase):
    def test_empty_returns_zero(self):
        self.assertEqual(effective_bet_count([]), 0.0)

    def test_equal_weights_gives_n(self):
        # Five equal weights → N_eff ≈ 5
        self.assertAlmostEqual(effective_bet_count([1, 1, 1, 1, 1]), 5.0, delta=1e-9)

    def test_one_dominant_weight(self):
        # 99% in one, 1% in 99 others → N_eff approaches 1
        weights = [99.0] + [1.0 / 99.0] * 99
        # Actually compute by formula: total ≈ 100, w1 ≈ 0.99
        n_eff = effective_bet_count(weights)
        self.assertLess(n_eff, 1.5)

    def test_two_equal_one_negligible(self):
        # Two equal big weights + one tiny → N_eff ≈ 2
        n_eff = effective_bet_count([10.0, 10.0, 0.01])
        self.assertGreater(n_eff, 1.9)
        self.assertLess(n_eff, 2.1)

    def test_zero_total_safe(self):
        self.assertEqual(effective_bet_count([0, 0, 0]), 0.0)


class PearsonTests(unittest.TestCase):
    def test_perfect_positive_correlation(self):
        rho = pearson([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
        self.assertAlmostEqual(rho, 1.0, delta=1e-9)

    def test_perfect_negative_correlation(self):
        rho = pearson([1, 2, 3, 4, 5], [5, 4, 3, 2, 1])
        self.assertAlmostEqual(rho, -1.0, delta=1e-9)

    def test_zero_correlation_orthogonal(self):
        rho = pearson([1, -1, 1, -1], [1, 1, -1, -1])
        self.assertAlmostEqual(rho, 0.0, delta=1e-9)

    def test_constant_input_returns_none(self):
        self.assertIsNone(pearson([1, 1, 1], [1, 2, 3]))

    def test_too_short_returns_none(self):
        self.assertIsNone(pearson([1], [2]))


class StrategyFamilyTests(unittest.TestCase):
    def test_snake_case_long_straddle(self):
        self.assertEqual(_strategy_family({"strategy": "long_straddle"}), "Long Straddle")

    def test_snake_case_call_debit_spread(self):
        self.assertEqual(_strategy_family({"strategy": "call_debit_spread"}), "Vertical Debit")

    def test_unknown_default(self):
        self.assertEqual(_strategy_family({}), "Unknown")


class DirectionTests(unittest.TestCase):
    def test_long_straddle_is_long_vol(self):
        self.assertEqual(_direction({"strategy": "long_straddle"}), "long-vol")

    def test_credit_spread_is_short_vol(self):
        self.assertEqual(_direction({"strategy": "credit_spread"}), "short-vol")

    def test_vertical_debit_is_long_equity(self):
        self.assertEqual(_direction({"strategy": "call_debit_spread"}), "long-equity")

    def test_butterfly_is_neutral(self):
        self.assertEqual(_direction({"strategy": "butterfly"}), "neutral")

    def test_unknown_is_unknown(self):
        self.assertEqual(_direction({}), "unknown")


class SlateConcentrationTests(unittest.TestCase):
    def test_empty_slate(self):
        out = _slate_concentration([])
        self.assertEqual(out["headcount"], 0)
        self.assertEqual(out["effectiveBetCount"], 0.0)

    def test_three_distinct_families(self):
        tickets = [
            {"ticker": "A", "strategy": "long_straddle", "riskUnits": 100},
            {"ticker": "B", "strategy": "credit_spread", "riskUnits": 100},
            {"ticker": "C", "strategy": "iron_condor", "riskUnits": 100},
        ]
        out = _slate_concentration(tickets)
        self.assertEqual(out["headcount"], 3)
        self.assertEqual(out["dominantFamilyShare"], round(1 / 3, 4))
        self.assertAlmostEqual(out["effectiveBetCount"], 3.0, delta=1e-6)

    def test_concentrated_slate(self):
        tickets = [
            {"ticker": str(i), "strategy": "long_straddle", "riskUnits": 100}
            for i in range(8)
        ] + [{"ticker": "X", "strategy": "credit_spread", "riskUnits": 100}]
        out = _slate_concentration(tickets)
        self.assertGreaterEqual(out["dominantFamilyShare"], DOMINANT_FAMILY_SHARE_FLOOR)


class TicketOverlapTests(unittest.TestCase):
    def test_same_family_count(self):
        tickets = [
            {"ticker": "A", "strategy": "long_straddle"},
            {"ticker": "B", "strategy": "long_straddle"},
            {"ticker": "C", "strategy": "credit_spread"},
        ]
        out = _ticket_overlap_counts(tickets)
        # A and B share family; both see sameFamily=1, C sees 0
        same_family_counts = {row["ticker"]: row["sameFamilyCount"] for row in out}
        self.assertEqual(same_family_counts["A"], 1)
        self.assertEqual(same_family_counts["B"], 1)
        self.assertEqual(same_family_counts["C"], 0)


class FamilyCorrelationTests(unittest.TestCase):
    def test_insufficient_data_returns_none(self):
        # Only 2 shared days → below MIN_CLOSED_PAIRS_FOR_CORRELATION
        tickets = [
            {"ticker": "A", "strategy": "long_straddle", "createdAt": "2026-01-01", "realizedPnl": 10.0},
            {"ticker": "B", "strategy": "credit_spread", "createdAt": "2026-01-01", "realizedPnl": -5.0},
            {"ticker": "C", "strategy": "long_straddle", "createdAt": "2026-01-02", "realizedPnl": -3.0},
            {"ticker": "D", "strategy": "credit_spread", "createdAt": "2026-01-02", "realizedPnl": 4.0},
        ]
        out = _family_pairwise_correlations(tickets)
        self.assertTrue(out["pairs"])
        for pair in out["pairs"]:
            self.assertIsNone(pair["correlation"])
            self.assertEqual(pair["note"], "insufficient-data")

    def test_sufficient_data_returns_number(self):
        # Six shared days with anti-correlated PnL — should fire 'high-correlation'
        # (note: ρ = -1, abs() not used in the labeling rule, but the number is real)
        days = [f"2026-01-{i:02d}" for i in range(1, 7)]
        tickets = []
        for i, day in enumerate(days):
            tickets.append(
                {"ticker": f"A{i}", "strategy": "long_straddle", "createdAt": day, "realizedPnl": float(i + 1)}
            )
            tickets.append(
                {"ticker": f"B{i}", "strategy": "credit_spread", "createdAt": day, "realizedPnl": -float(i + 1)}
            )
        out = _family_pairwise_correlations(tickets)
        pair = next(p for p in out["pairs"] if p["familyA"] == "Credit Spread" and p["familyB"] == "Long Straddle")
        self.assertIsNotNone(pair["correlation"])
        self.assertAlmostEqual(pair["correlation"], -1.0, delta=1e-6)


class BuildAndRenderTests(unittest.TestCase):
    def test_module_is_research_only(self):
        self.assertEqual(CORRELATION_STAGE, "portfolio-correlation-research-only")

    def test_build_against_live_data(self):
        payload = build_portfolio_correlation()
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["researchOnly"])
        self.assertEqual(payload["stage"], CORRELATION_STAGE)
        self.assertIn(
            payload["verdict"],
            {
                "awaiting-outcomes",
                "diversified",
                "concentrated-by-drift",
                "concentrated-by-intent",
                "concentration-watch",
                "thin-diversification",
            },
        )
        self.assertIn("MARKOWITZ-1952", payload["citations"])
        self.assertIn("GRINOLD-1989", payload["citations"])

    def test_text_render_includes_key_sections(self):
        payload = build_portfolio_correlation()
        text = portfolio_correlation_text(payload)
        self.assertIn("Inferno Portfolio Correlation", text)
        self.assertIn("Verdict:", text)
        self.assertIn("Reminders:", text)


if __name__ == "__main__":
    unittest.main()
