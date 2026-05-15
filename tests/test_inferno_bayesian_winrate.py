from __future__ import annotations

"""Adversarial tests for inferno_bayesian_winrate.

Counter-arguments the module must survive:

1. Empty data → posterior is prior; verdict 'no-evidence'.
2. Weak prior pulls toward 0.5 when sample is tiny.
3. Posterior mean approaches sample mean as n grows.
4. P(p > 0.5) > 0.5 iff posterior mean > 0.5.
5. Credible interval bounds are in [0, 1] and ordered.
6. All wins → posterior mean approaches 1, P(p>0.5) ~ 1.
7. All losses → posterior mean approaches 0, P(p>0.5) ~ 0.
8. Insufficient samples → verdict 'insufficient' regardless of probability.
9. researchOnly / promotable / diagnosticOnly contract frozen.
10. Monte Carlo seed reproducible.
"""

import unittest

import inferno_bayesian_winrate as bw


def closed_records(strategy: str, r_units: list[float]) -> list[dict]:
    return [
        {
            "strategy": strategy,
            "outcome": {"status": "closed"},
            "estimatedPnl": float(v),
            "maxLossDollars": 1.0,
        }
        for v in r_units
    ]


class ContractTests(unittest.TestCase):
    def test_stage_is_research_only(self) -> None:
        self.assertTrue(bw.BAYESIAN_WINRATE_STAGE.endswith("research-only"))

    def test_payload_contract(self) -> None:
        payload = bw.build_bayesian_winrate(shadow_loader=lambda: [], draws=200)
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["diagnosticOnly"])


class PosteriorMathTests(unittest.TestCase):
    def test_prior_dominates_empty(self) -> None:
        a, b = bw.posterior_parameters(0, 0)
        self.assertEqual(a, bw.PRIOR_ALPHA)
        self.assertEqual(b, bw.PRIOR_BETA)
        self.assertEqual(bw.posterior_mean(a, b), 0.5)

    def test_posterior_mean_pulls_toward_prior_when_sample_tiny(self) -> None:
        # 1 win / 0 losses: raw rate is 1.0, but prior pulls toward 0.5.
        a, b = bw.posterior_parameters(1, 0)
        mean = bw.posterior_mean(a, b)
        self.assertLess(mean, 1.0)
        self.assertGreater(mean, 0.5)

    def test_posterior_mean_approaches_sample_mean(self) -> None:
        # 60 wins / 40 losses: raw = 0.6, prior contribution diluted to ~0.598.
        a, b = bw.posterior_parameters(60, 40)
        mean = bw.posterior_mean(a, b)
        self.assertAlmostEqual(mean, (2 + 60) / (2 + 2 + 60 + 40), places=6)
        self.assertAlmostEqual(mean, 62 / 104, places=4)

    def test_credible_interval_in_unit_and_ordered(self) -> None:
        lo, hi = bw.posterior_credible_interval(5, 10, draws=2000, seed=42)
        self.assertGreaterEqual(lo, 0.0)
        self.assertLessEqual(hi, 1.0)
        self.assertLess(lo, hi)

    def test_probability_above_threshold_monotone(self) -> None:
        a, b = bw.posterior_parameters(60, 40)
        p_above_05 = bw.posterior_probability_above(a, b, 0.5, draws=2000, seed=42)
        p_above_055 = bw.posterior_probability_above(a, b, 0.55, draws=2000, seed=42)
        # Probability of exceeding a *higher* threshold cannot exceed probability of exceeding a lower one.
        self.assertGreaterEqual(p_above_05, p_above_055)

    def test_probability_above_threshold_bounds_check(self) -> None:
        with self.assertRaises(ValueError):
            bw.posterior_probability_above(2, 2, 1.5, draws=200)

    def test_seed_reproducible(self) -> None:
        lo_a, hi_a = bw.posterior_credible_interval(7, 7, draws=1000, seed=99)
        lo_b, hi_b = bw.posterior_credible_interval(7, 7, draws=1000, seed=99)
        self.assertEqual((lo_a, hi_a), (lo_b, hi_b))


class ClassifyTests(unittest.TestCase):
    def test_insufficient_below_minimum(self) -> None:
        self.assertEqual(
            bw.classify_strategy(sample_size=bw.MIN_BAYES_SAMPLES - 1, probability_above_edge=0.95),
            "insufficient",
        )

    def test_strong_band(self) -> None:
        self.assertEqual(
            bw.classify_strategy(sample_size=30, probability_above_edge=0.85),
            "edge-strong",
        )

    def test_likely_band(self) -> None:
        self.assertEqual(
            bw.classify_strategy(sample_size=30, probability_above_edge=0.60),
            "edge-likely",
        )

    def test_uncertain_band(self) -> None:
        self.assertEqual(
            bw.classify_strategy(sample_size=30, probability_above_edge=0.30),
            "edge-uncertain",
        )

    def test_rejected_band(self) -> None:
        self.assertEqual(
            bw.classify_strategy(sample_size=30, probability_above_edge=0.10),
            "edge-rejected",
        )


class BuildBayesianTests(unittest.TestCase):
    def test_no_records(self) -> None:
        payload = bw.build_bayesian_winrate(shadow_loader=lambda: [], draws=200)
        self.assertEqual(payload["verdict"], "no-evidence")
        self.assertEqual(payload["strategyCount"], 0)

    def test_all_winning_strategy(self) -> None:
        records = closed_records("Vertical Call", [1.0] * 20)
        payload = bw.build_bayesian_winrate(shadow_loader=lambda: records, draws=1500, seed=1)
        row = payload["rows"][0]
        self.assertEqual(row["wins"], 20)
        self.assertEqual(row["losses"], 0)
        self.assertGreater(row["probabilityAboveEdge"], 0.95)
        self.assertEqual(row["verdict"], "edge-strong")

    def test_all_losing_strategy(self) -> None:
        records = closed_records("Straddle", [-1.0] * 20)
        payload = bw.build_bayesian_winrate(shadow_loader=lambda: records, draws=1500, seed=1)
        row = payload["rows"][0]
        self.assertEqual(row["wins"], 0)
        self.assertEqual(row["losses"], 20)
        self.assertLess(row["probabilityAboveEdge"], 0.05)
        self.assertEqual(row["verdict"], "edge-rejected")

    def test_below_minimum_insufficient(self) -> None:
        records = closed_records("Iron Condor", [1.0] * (bw.MIN_BAYES_SAMPLES - 1))
        payload = bw.build_bayesian_winrate(shadow_loader=lambda: records, draws=400)
        self.assertEqual(payload["rows"][0]["verdict"], "insufficient")


class TextRenderTests(unittest.TestCase):
    def test_text_has_expected_sections(self) -> None:
        records = closed_records("Vertical Call", [1.0] * 15 + [-1.0] * 5)
        payload = bw.build_bayesian_winrate(shadow_loader=lambda: records, draws=400)
        text = bw.bayesian_text(payload)
        self.assertIn("Bayesian Win Rate", text)
        self.assertIn("Verdict:", text)
        self.assertIn("Per-strategy posterior:", text)
        self.assertIn("Vertical Call", text)


if __name__ == "__main__":
    unittest.main()
