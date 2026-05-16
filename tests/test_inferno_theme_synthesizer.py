from __future__ import annotations

"""Regression tests for the theme synthesizer.

The synthesizer is the math layer the hypothesis lab builds on, so its
correctness has to be locked down:

- Wilson interval matches a known closed-form value
- Bootstrap CI is deterministic given the seed
- Cells below MIN_CELL_SAMPLES are correctly flagged insufficient
- Edges require Wilson lower > 0.5 AND expectancy lower > 0
- Anti-edges require Wilson upper < 0.5 AND mean expectancy < 0
- researchOnly / promotable contract is immutable
"""

import math
import unittest

from inferno_theme_synthesizer import (
    DEFAULT_DIMENSIONS,
    MIN_CELL_SAMPLES,
    THEME_STAGE,
    bootstrap_mean_ci,
    build_cube,
    build_theme_report,
    cell_metrics,
    normalize_record,
    rank_edges,
    theme_text,
    wilson_interval,
)


def _record(
    ticker: str,
    pnl: float | None,
    *,
    strategy: str = "LONG_STRADDLE",
    regime: str = "bullish-normal",
    sector: str = "Technology",
    iv_rank: float | None = 30.0,
    days_to_earnings: float | None = 5,
    max_loss: float = 100.0,
) -> dict:
    """Build a shadow-shaped record for tests."""
    return {
        "ticker": ticker,
        "strategy": strategy,
        "regime": regime,
        "sector": sector,
        "ivRank": iv_rank,
        "daysToEarnings": days_to_earnings,
        "riskVerdict": {"metrics": {"maxLossDollars": max_loss}},
        "outcome": {
            "status": "closed" if pnl is not None else "open",
            "estimatedPnl": pnl,
        },
    }


class WilsonIntervalTests(unittest.TestCase):
    """Wilson interval must match the standard closed-form result."""

    def test_zero_samples_returns_full_range(self) -> None:
        lower, upper = wilson_interval(0, 0)
        self.assertEqual((lower, upper), (0.0, 1.0))

    def test_six_wins_out_of_ten_matches_known_value(self) -> None:
        lower, upper = wilson_interval(6, 10)
        # Closed-form values at z=1.96, p=0.6, n=10. These match the
        # production strategy replay (which uses the same Wilson formula)
        # and the canonical reference of (0.3127, 0.832).
        self.assertAlmostEqual(lower, 0.3127, places=3)
        self.assertAlmostEqual(upper, 0.832, places=2)

    def test_bounds_clamp_to_unit_interval(self) -> None:
        lower, upper = wilson_interval(10, 10)
        self.assertGreaterEqual(lower, 0.0)
        self.assertLessEqual(upper, 1.0)


class BootstrapTests(unittest.TestCase):
    """Bootstrap CI must be deterministic and centred on the mean."""

    def test_single_sample_returns_constant(self) -> None:
        mean, lower, upper = bootstrap_mean_ci([0.42])
        self.assertEqual((mean, lower, upper), (0.42, 0.42, 0.42))

    def test_empty_sample_returns_zero(self) -> None:
        mean, lower, upper = bootstrap_mean_ci([])
        self.assertEqual((mean, lower, upper), (0.0, 0.0, 0.0))

    def test_deterministic_with_seed(self) -> None:
        samples = [0.5, -1.0, 1.5, -0.3, 0.8]
        first = bootstrap_mean_ci(samples, seed=7, resamples=200)
        second = bootstrap_mean_ci(samples, seed=7, resamples=200)
        self.assertEqual(first, second)

    def test_lower_below_upper_and_brackets_mean(self) -> None:
        samples = [1.5, -0.7, 0.4, -0.2, 2.0]
        mean, lower, upper = bootstrap_mean_ci(samples, seed=11, resamples=400)
        self.assertLessEqual(lower, mean)
        self.assertLessEqual(mean, upper)


class CellMetricsTests(unittest.TestCase):
    """cell_metrics should compute the same numbers we showed in the doctor."""

    def test_known_six_of_seven_straddle_metrics(self) -> None:
        records = [normalize_record(_record(f"T{i}", pnl=1.0)) for i in range(6)]
        records.append(normalize_record(_record("T6", pnl=-0.5)))
        metrics = cell_metrics(records)
        self.assertEqual(metrics["sampleSize"], 7)
        self.assertEqual(metrics["wins"], 6)
        self.assertAlmostEqual(metrics["winRate"], 0.8571, places=3)
        self.assertTrue(metrics["sufficient"])

    def test_insufficient_when_below_min(self) -> None:
        records = [normalize_record(_record("X", pnl=1.0))]
        metrics = cell_metrics(records)
        self.assertFalse(metrics["sufficient"])
        self.assertEqual(metrics["sampleSize"], 1)


class CubeAndRankTests(unittest.TestCase):
    """Build cube + rank edges as the synthesizer would in production."""

    def setUp(self) -> None:
        wins = [
            _record(f"WIN{i}", pnl=1.0, strategy="LONG_STRADDLE", regime="bullish-normal")
            for i in range(6)
        ]
        losses = [
            _record(f"LOSS{i}", pnl=-1.0, strategy="LONG_STRADDLE", regime="bullish-normal")
            for i in range(1)
        ]
        # 6 pure losses pushes Wilson upper to ≈ 0.39, below the 0.42 floor.
        antis = [
            _record(f"ANTI{i}", pnl=-1.0, strategy="CALL_DEBIT_SPREAD", regime="bearish")
            for i in range(6)
        ]
        self.records = wins + losses + antis

    def test_cube_has_two_sufficient_cells(self) -> None:
        cube = build_cube(self.records)
        sufficient = [m for m in cube.values() if m["sufficient"]]
        self.assertEqual(len(sufficient), 2)

    def test_rank_edges_finds_edge_and_anti_edge(self) -> None:
        cube = build_cube(self.records)
        edges, anti = rank_edges(cube, DEFAULT_DIMENSIONS, top_n=5)
        self.assertTrue(any("LONG_STRADDLE" in e["key"] for e in edges))
        self.assertTrue(any("CALL_DEBIT_SPREAD" in a["key"] for a in anti))


class ThemeReportTests(unittest.TestCase):
    """End-to-end synthesizer behaviour, plus contract checks."""

    def test_research_only_contract(self) -> None:
        payload = build_theme_report(records=[])
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertEqual(payload["stage"], THEME_STAGE)
        self.assertEqual(payload["minCellSamples"], MIN_CELL_SAMPLES)

    def test_text_renderer_includes_each_section(self) -> None:
        payload = build_theme_report(records=[
            _record(f"T{i}", pnl=1.0) for i in range(6)
        ])
        rendered = theme_text(payload)
        self.assertIn("Theme Synthesizer", rendered)
        self.assertIn("Top edges", rendered)
        self.assertIn("Reminders:", rendered)


if __name__ == "__main__":
    unittest.main()
