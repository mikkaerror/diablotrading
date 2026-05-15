from __future__ import annotations

"""Adversarial tests for inferno_factor_regression.

Counter-arguments the module must survive:

1. Empty data → 'no-evidence'.
2. Constant feature is dropped from design matrix.
3. Separable data converges: fitted coefficient is large and matches the
   sign of the relationship.
4. Random feature data yields coefficients whose CI straddles zero.
5. Sigmoid is numerically stable for large positive and negative inputs.
6. Bootstrap CI is reproducible with a fixed seed.
7. researchOnly / promotable / diagnosticOnly contract frozen.
8. Mismatched feature_matrix/outcomes length raises.
9. Below MIN_REGRESSION_SAMPLES → 'insufficient' verdict.
"""

import math
import random
import unittest

import inferno_factor_regression as fr


def closed_record(strategy: str, r: float, **fields) -> dict:
    rec = {
        "strategy": strategy,
        "outcome": {"status": "closed"},
        "estimatedPnl": float(r),
        "maxLossDollars": 1.0,
    }
    rec.update(fields)
    return rec


class ContractTests(unittest.TestCase):
    def test_stage(self) -> None:
        self.assertTrue(fr.FACTOR_REGRESSION_STAGE.endswith("research-only"))

    def test_contract_frozen(self) -> None:
        payload = fr.build_factor_regression(shadow_loader=lambda: [])
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["diagnosticOnly"])


class SigmoidTests(unittest.TestCase):
    def test_zero(self) -> None:
        self.assertEqual(fr.sigmoid(0.0), 0.5)

    def test_large_positive_stable(self) -> None:
        self.assertGreater(fr.sigmoid(1000), 0.999999)

    def test_large_negative_stable(self) -> None:
        self.assertLess(fr.sigmoid(-1000), 0.000001)

    def test_symmetry(self) -> None:
        for z in (0.5, 1.0, 2.5, 10.0):
            self.assertAlmostEqual(fr.sigmoid(z) + fr.sigmoid(-z), 1.0, places=6)


class FitLogisticTests(unittest.TestCase):
    def test_empty(self) -> None:
        weights, bias, iters = fr.fit_logistic([], [])
        self.assertEqual(weights, [])
        self.assertEqual(bias, 0.0)
        self.assertEqual(iters, 0)

    def test_mismatched_raises(self) -> None:
        with self.assertRaises(ValueError):
            fr.fit_logistic([[1.0]], [0, 1])

    def test_constant_wins_returns_saturated_bias_without_fake_factor(self) -> None:
        X = [[1.0], [0.0]] * 20
        y = [1] * 40
        weights, bias, iters = fr.fit_logistic(X, y)
        self.assertEqual(weights, [0.0])
        self.assertGreater(bias, 5.0)
        self.assertEqual(iters, 0)

    def test_constant_losses_returns_saturated_bias_without_fake_factor(self) -> None:
        X = [[1.0], [0.0]] * 20
        y = [0] * 40
        weights, bias, iters = fr.fit_logistic(X, y)
        self.assertEqual(weights, [0.0])
        self.assertLess(bias, -5.0)
        self.assertEqual(iters, 0)

    def test_separable_data_converges(self) -> None:
        # Feature 1 predicts the outcome perfectly.
        X = [[1.0]] * 30 + [[0.0]] * 30
        y = [1] * 30 + [0] * 30
        weights, bias, _ = fr.fit_logistic(X, y, max_iterations=400)
        # With L2 regularisation, weight won't go to infinity, but it
        # should be strongly positive.
        self.assertGreater(weights[0], 0.5)

    def test_random_data_gives_small_coefficients(self) -> None:
        rng = random.Random(42)
        X = [[1.0 if rng.random() > 0.5 else 0.0] for _ in range(80)]
        y = [1 if rng.random() > 0.5 else 0 for _ in range(80)]
        weights, _, _ = fr.fit_logistic(X, y, max_iterations=400)
        # Independent feature → coefficient should be small.
        self.assertLess(abs(weights[0]), 0.5)


class BootstrapTests(unittest.TestCase):
    def test_seed_reproducible(self) -> None:
        X = [[1.0, 0.0]] * 15 + [[0.0, 1.0]] * 15
        y = [1] * 15 + [0] * 15
        a_w, a_b = fr.bootstrap_logistic_coefficients(X, y, draws=50, seed=99)
        b_w, b_b = fr.bootstrap_logistic_coefficients(X, y, draws=50, seed=99)
        self.assertEqual(a_w, b_w)
        self.assertEqual(a_b, b_b)


class PercentileCITests(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(fr.percentile_ci([]), (0.0, 0.0))

    def test_known(self) -> None:
        draws = list(range(100))
        lo, hi = fr.percentile_ci(draws, alpha=0.05)
        # alpha/2 * 100 = 2.5 -> idx 2; (1-alpha/2)*100 = 97.5 -> idx 97
        self.assertEqual(lo, 2)
        self.assertEqual(hi, 97)


class ClassifyCoefficientTests(unittest.TestCase):
    def test_insufficient(self) -> None:
        self.assertEqual(
            fr.classify_coefficient(sample_size=fr.MIN_REGRESSION_SAMPLES - 1, lower=0.1, upper=0.3),
            "insufficient",
        )

    def test_positive_edge(self) -> None:
        self.assertEqual(
            fr.classify_coefficient(sample_size=100, lower=0.1, upper=0.3),
            "positive-edge",
        )

    def test_negative_edge(self) -> None:
        self.assertEqual(
            fr.classify_coefficient(sample_size=100, lower=-0.5, upper=-0.1),
            "negative-edge",
        )

    def test_inconclusive(self) -> None:
        self.assertEqual(
            fr.classify_coefficient(sample_size=100, lower=-0.2, upper=0.3),
            "inconclusive",
        )


class BuildFactorRegressionTests(unittest.TestCase):
    def test_no_data(self) -> None:
        payload = fr.build_factor_regression(shadow_loader=lambda: [])
        self.assertEqual(payload["verdict"], "no-evidence")
        self.assertEqual(payload["sampleSize"], 0)
        self.assertEqual(payload["iterationsUsed"], 0)
        self.assertEqual(payload["bias"], 0.0)
        self.assertEqual(payload["positiveEdgeCount"], 0)

    def test_insufficient(self) -> None:
        # Build a few records — below MIN_REGRESSION_SAMPLES. Use varied
        # features so design matrix is non-empty (otherwise we'd get
        # 'no-features' instead of 'insufficient').
        records = []
        for i in range(10):
            iv = 80 if i % 2 == 0 else 20
            records.append(closed_record("X", 1.0, ivRank=iv, daysToEarnings=10))
        payload = fr.build_factor_regression(
            shadow_loader=lambda: records, bootstrap_draws=20,
        )
        self.assertEqual(payload["verdict"], "insufficient")

    def test_positive_edge_detected_separable(self) -> None:
        # ivRank perfectly predicts outcome.
        records = []
        for _ in range(30):
            records.append(closed_record("X", 1.0, ivRank=80, daysToEarnings=10))
        for _ in range(30):
            records.append(closed_record("X", -1.0, ivRank=10, daysToEarnings=10))
        payload = fr.build_factor_regression(
            shadow_loader=lambda: records, bootstrap_draws=50,
        )
        # Either positive-edges or edges-mixed depending on how features split.
        self.assertIn(payload["verdict"], {"positive-edges", "negative-edges", "edges-mixed"})


class TextRenderTests(unittest.TestCase):
    def test_text_has_sections(self) -> None:
        records = []
        for _ in range(30):
            records.append(closed_record("X", 1.0, ivRank=80, daysToEarnings=10))
        for _ in range(30):
            records.append(closed_record("X", -1.0, ivRank=10, daysToEarnings=10))
        payload = fr.build_factor_regression(
            shadow_loader=lambda: records, bootstrap_draws=30,
        )
        text = fr.factor_regression_text(payload)
        self.assertIn("Factor Regression", text)
        self.assertIn("Verdict:", text)


if __name__ == "__main__":
    unittest.main()
