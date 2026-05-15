from __future__ import annotations

"""Adversarial tests for inferno_information_gain.

Counter-arguments the module must survive:

1. Empty data → 'no-evidence'.
2. Below MIN_MI_SAMPLES → 'insufficient' regardless of NMI.
3. Constant feature → MI is zero.
4. Constant outcome → MI is zero (no entropy to resolve).
5. Perfect feature-outcome agreement → NMI = 1, p ≈ 0.
6. Independent (random) feature → low NMI, high p-value.
7. Mismatched feature/outcome list lengths raises.
8. Entropy of fair coin == 1 bit.
9. Permutation p-value is in (0, 1].
10. researchOnly / promotable / diagnosticOnly contract frozen.
"""

import random
import unittest

import inferno_information_gain as ig


class ContractTests(unittest.TestCase):
    def test_stage(self) -> None:
        self.assertTrue(ig.INFORMATION_GAIN_STAGE.endswith("research-only"))

    def test_contract_frozen(self) -> None:
        payload = ig.build_information_gain(shadow_loader=lambda: [])
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["diagnosticOnly"])


class EntropyTests(unittest.TestCase):
    def test_fair_coin_entropy_is_one_bit(self) -> None:
        self.assertAlmostEqual(ig.entropy([0.5, 0.5]), 1.0, places=6)

    def test_certain_event_entropy_is_zero(self) -> None:
        self.assertEqual(ig.entropy([1.0, 0.0]), 0.0)

    def test_outcome_entropy_constant_outcome(self) -> None:
        self.assertEqual(ig.outcome_entropy([True] * 20), 0.0)
        self.assertEqual(ig.outcome_entropy([False] * 20), 0.0)


class MutualInformationTests(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(ig.mutual_information([], []), 0.0)

    def test_mismatched_lengths_raises(self) -> None:
        with self.assertRaises(ValueError):
            ig.mutual_information(["a"], [True, False])

    def test_constant_feature_zero_mi(self) -> None:
        features = ["A"] * 20
        outcomes = [True, False] * 10
        self.assertEqual(ig.mutual_information(features, outcomes), 0.0)

    def test_constant_outcome_zero_mi(self) -> None:
        features = ["A", "B"] * 10
        outcomes = [True] * 20
        self.assertEqual(ig.mutual_information(features, outcomes), 0.0)

    def test_perfect_agreement_equals_outcome_entropy(self) -> None:
        # When the feature perfectly determines the outcome, MI = H(Y).
        features = ["win", "loss"] * 10
        outcomes = [True, False] * 10
        h_y = ig.outcome_entropy(outcomes)
        mi = ig.mutual_information(features, outcomes)
        self.assertAlmostEqual(mi, h_y, places=6)
        self.assertAlmostEqual(ig.normalised_mi(mi, h_y), 1.0, places=6)

    def test_independent_low_mi(self) -> None:
        # Random feature should yield near-zero MI.
        rng = random.Random(2026)
        outcomes = [bool(rng.random() > 0.5) for _ in range(200)]
        features = ["high" if rng.random() > 0.5 else "low" for _ in range(200)]
        mi = ig.mutual_information(features, outcomes)
        h_y = ig.outcome_entropy(outcomes)
        self.assertLess(ig.normalised_mi(mi, h_y), 0.1)


class PermutationPValueTests(unittest.TestCase):
    def test_perfect_agreement_p_value_low(self) -> None:
        features = ["win", "loss"] * 15
        outcomes = [True, False] * 15
        mi = ig.mutual_information(features, outcomes)
        p = ig.permutation_p_value(features, outcomes, observed_mi=mi, resamples=300, seed=11)
        self.assertLess(p, 0.05)

    def test_independent_p_value_high(self) -> None:
        rng = random.Random(2027)
        outcomes = [bool(rng.random() > 0.5) for _ in range(200)]
        features = ["high" if rng.random() > 0.5 else "low" for _ in range(200)]
        mi = ig.mutual_information(features, outcomes)
        p = ig.permutation_p_value(features, outcomes, observed_mi=mi, resamples=300, seed=12)
        self.assertGreater(p, 0.05)

    def test_p_value_in_unit_interval(self) -> None:
        features = ["a", "b"] * 10
        outcomes = [True, False] * 10
        p = ig.permutation_p_value(
            features, outcomes,
            observed_mi=ig.mutual_information(features, outcomes),
            resamples=200, seed=42,
        )
        self.assertGreater(p, 0.0)
        self.assertLessEqual(p, 1.0)


class ClassifyTests(unittest.TestCase):
    def test_insufficient_below_min(self) -> None:
        self.assertEqual(
            ig.classify_feature(sample_size=ig.MIN_MI_SAMPLES - 1, nmi=0.9),
            "insufficient",
        )

    def test_band_thresholds(self) -> None:
        self.assertEqual(ig.classify_feature(sample_size=50, nmi=0.5), "strong")
        self.assertEqual(ig.classify_feature(sample_size=50, nmi=0.10), "meaningful")
        self.assertEqual(ig.classify_feature(sample_size=50, nmi=0.02), "faint")
        self.assertEqual(ig.classify_feature(sample_size=50, nmi=0.0), "noise")


class BuildInformationGainTests(unittest.TestCase):
    def test_no_records(self) -> None:
        payload = ig.build_information_gain(shadow_loader=lambda: [])
        self.assertEqual(payload["verdict"], "no-evidence")

    def test_signal_detected_with_perfect_feature(self) -> None:
        # Build records where ivRank perfectly predicts outcome.
        records = []
        for _ in range(20):
            records.append({
                "strategy": "X",
                "outcome": {"status": "closed"},
                "estimatedPnl": 1.0,
                "maxLossDollars": 1.0,
                "ivRank": 80,  # high → win
            })
        for _ in range(20):
            records.append({
                "strategy": "X",
                "outcome": {"status": "closed"},
                "estimatedPnl": -1.0,
                "maxLossDollars": 1.0,
                "ivRank": 10,  # low → loss
            })
        payload = ig.build_information_gain(
            shadow_loader=lambda: records,
            feature_extractors={"ivBucket": ig._iv_bucket},
            permutation_resamples=200,
        )
        self.assertEqual(payload["verdict"], "signal-detected")
        row = payload["rows"][0]
        self.assertEqual(row["feature"], "ivBucket")
        self.assertGreater(row["normalisedMI"], 0.9)

    def test_mixed_feature_value_types_do_not_break_support_count(self) -> None:
        records = []
        for i in range(24):
            records.append({
                "strategy": "X",
                "outcome": {"status": "closed"},
                "estimatedPnl": 1.0 if i % 2 == 0 else -1.0,
                "maxLossDollars": 1.0,
                "custom": i if i % 3 else "unknown",
            })
        payload = ig.build_information_gain(
            shadow_loader=lambda: records,
            feature_extractors={"custom": lambda r: r["custom"]},
            permutation_resamples=20,
        )
        self.assertEqual(payload["rows"][0]["supportSize"], len({r["custom"] for r in records}))


class TextRenderTests(unittest.TestCase):
    def test_text_renders(self) -> None:
        records = [{
            "strategy": "X",
            "outcome": {"status": "closed"},
            "estimatedPnl": 1.0,
            "maxLossDollars": 1.0,
            "ivRank": 80,
        }] * 25
        payload = ig.build_information_gain(
            shadow_loader=lambda: records,
            feature_extractors={"ivBucket": ig._iv_bucket},
            permutation_resamples=100,
        )
        text = ig.information_gain_text(payload)
        self.assertIn("Information Gain", text)
        self.assertIn("Per-feature MI:", text)


if __name__ == "__main__":
    unittest.main()
