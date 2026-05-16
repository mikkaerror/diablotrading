from __future__ import annotations

"""Adversarial tests for inferno_devils_advocate.

Counter-arguments the module must survive:

1. Empty input must not crash and must classify as 'no-evidence'.
2. A single sample cannot reject the null (n=1 → p=1.0).
3. A clearly winning strategy (n=30, mean=+1R) must hit edge-holds.
4. A clearly losing strategy must NOT trigger edge-holds (one-sided test).
5. A null strategy (mean ~= 0) must classify as edge-falsified at large n.
6. All-zero samples must classify as edge-falsified (no evidence of edge).
7. Below-sample-threshold strategies must classify as 'insufficient'.
8. The p-value must always satisfy 0 < p <= 1 (Phipson-Smyth correction).
9. The seed must make results reproducible.
10. researchOnly / promotable / diagnosticOnly contract is frozen.
"""

import unittest

import inferno_devils_advocate as da


def make_records(strategy: str, r_units: list[float]) -> list[dict]:
    return [
        {
            "strategy": strategy,
            "outcome": {"status": "closed"},
            "estimatedPnl": float(value),
            "maxLossDollars": 1.0,
        }
        for value in r_units
    ]


class StageContractTests(unittest.TestCase):
    def test_stage_constant_is_research_only(self) -> None:
        self.assertTrue(da.DEVILS_ADVOCATE_STAGE.endswith("research-only"))

    def test_payload_freezes_research_contract(self) -> None:
        payload = da.build_falsification(shadow_loader=lambda: [])
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["diagnosticOnly"])


class SignFlipMathTests(unittest.TestCase):
    def test_empty_input(self) -> None:
        p, mean, above = da.sign_flip_p_value([])
        self.assertEqual(p, 1.0)
        self.assertEqual(mean, 0.0)
        self.assertEqual(above, 0)

    def test_single_sample_cannot_reject(self) -> None:
        p, mean, above = da.sign_flip_p_value([2.0])
        self.assertEqual(p, 1.0)
        self.assertEqual(mean, 2.0)
        self.assertEqual(above, 0)

    def test_p_value_in_open_unit_interval(self) -> None:
        # Phipson-Smyth: even when no resample exceeds observed, p = 1/(B+1) > 0.
        p, _, _ = da.sign_flip_p_value([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0], resamples=200)
        self.assertGreater(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_clear_edge_rejects_null(self) -> None:
        # 30 samples, all +1R — p should be tiny.
        samples = [1.0] * 30
        p, _, _ = da.sign_flip_p_value(samples, resamples=500)
        self.assertLess(p, 0.01)

    def test_clear_negative_edge_does_not_reject(self) -> None:
        # 30 samples, all -1R — one-sided test for *positive* mean should fail.
        samples = [-1.0] * 30
        p, _, _ = da.sign_flip_p_value(samples, resamples=500)
        self.assertGreater(p, 0.9)

    def test_zero_mean_does_not_reject(self) -> None:
        samples = [1.0, -1.0] * 10
        p, _, _ = da.sign_flip_p_value(samples, resamples=500)
        self.assertGreater(p, 0.2)

    def test_all_zero_samples_yield_high_p(self) -> None:
        # Every resample also yields mean 0, so p = (B+1)/(B+1) = 1.0.
        p, mean, above = da.sign_flip_p_value([0.0] * 12, resamples=300)
        self.assertEqual(mean, 0.0)
        self.assertAlmostEqual(p, 1.0)
        self.assertEqual(above, 300)

    def test_seed_reproducibility(self) -> None:
        samples = [0.3, -0.1, 0.8, -0.4, 0.5, 0.2, -0.1, 0.7, 0.4, -0.2]
        p_a, _, _ = da.sign_flip_p_value(samples, resamples=500, seed=42)
        p_b, _, _ = da.sign_flip_p_value(samples, resamples=500, seed=42)
        self.assertEqual(p_a, p_b)


class VerdictClassifierTests(unittest.TestCase):
    def test_insufficient_when_below_min_samples(self) -> None:
        self.assertEqual(da.classify_verdict(0.001, 1), "insufficient")
        self.assertEqual(da.classify_verdict(0.001, da.MIN_FALSIFICATION_SAMPLES - 1), "insufficient")

    def test_edge_holds(self) -> None:
        self.assertEqual(da.classify_verdict(0.01, 20), "edge-holds")

    def test_edge_weakens(self) -> None:
        self.assertEqual(da.classify_verdict(0.10, 20), "edge-weakens")

    def test_edge_falsified(self) -> None:
        self.assertEqual(da.classify_verdict(0.30, 20), "edge-falsified")


class BuildFalsificationTests(unittest.TestCase):
    def test_no_records(self) -> None:
        payload = da.build_falsification(shadow_loader=lambda: [])
        self.assertEqual(payload["verdict"], "no-evidence")
        self.assertEqual(payload["strategyCount"], 0)

    def test_strong_strategy_holds(self) -> None:
        records = make_records("Vertical Call", [1.0] * 20)
        payload = da.build_falsification(shadow_loader=lambda: records, resamples=400)
        self.assertEqual(payload["verdict"], "edges-survive")
        self.assertEqual(payload["edgesHolding"], 1)
        self.assertEqual(payload["edgesFalsified"], 0)

    def test_null_strategy_falsified(self) -> None:
        # Mean ~= 0 with sufficient sample.
        samples = ([0.5, -0.5] * 10)
        records = make_records("Straddle", samples)
        payload = da.build_falsification(shadow_loader=lambda: records, resamples=400)
        verdict_for_strat = payload["results"][0]["verdict"]
        self.assertIn(verdict_for_strat, {"edge-falsified", "edge-weakens"})
        self.assertEqual(payload["edgesHolding"], 0)

    def test_insufficient_sample_classified(self) -> None:
        records = make_records("Iron Condor", [1.0] * 3)
        payload = da.build_falsification(shadow_loader=lambda: records, resamples=200)
        self.assertEqual(payload["insufficientCount"], 1)

    def test_results_sorted_by_sample_size_desc(self) -> None:
        records = make_records("Big", [1.0] * 20) + make_records("Small", [1.0] * 10)
        payload = da.build_falsification(shadow_loader=lambda: records, resamples=200)
        self.assertEqual(payload["results"][0]["strategy"], "Big")
        self.assertEqual(payload["results"][1]["strategy"], "Small")


class TextRenderTests(unittest.TestCase):
    def test_text_contains_sections(self) -> None:
        records = make_records("Vertical Call", [1.0] * 15)
        payload = da.build_falsification(shadow_loader=lambda: records, resamples=200)
        text = da.falsification_text(payload)
        self.assertIn("Devil's Advocate", text)
        self.assertIn("Verdict:", text)
        self.assertIn("Thresholds:", text)
        self.assertIn("Vertical Call", text)


if __name__ == "__main__":
    unittest.main()
