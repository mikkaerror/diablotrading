from __future__ import annotations

"""Adversarial tests for inferno_evidence_strength.

Counter-arguments the module must survive:

1. Empty input → 'no-evidence', strength == 0.0.
2. Geometric mean punishes the weakest component (asymmetric vs arithmetic).
3. A single component at 0 drives composite to 0 (math invariant).
4. Missing devil's-advocate data drops that component, doesn't zero composite.
5. All-winning strategy with N >= target should hit 'strong'.
6. Wilson lower at exactly 0.5 yields wilsonStrength == 0.
7. Sample size above target caps strength at 1.0 (no negative slope past target).
8. Negative expectancy lower bound yields expectancyStrength == 0.
9. researchOnly / promotable / diagnosticOnly contract frozen.
"""

import unittest

import inferno_evidence_strength as es


def closed_records(r_units: list[float]) -> list[dict]:
    return [
        {
            "strategy": "Test",
            "outcome": {"status": "closed"},
            "estimatedPnl": float(value),
            "maxLossDollars": 1.0,
        }
        for value in r_units
    ]


class StageContractTests(unittest.TestCase):
    def test_stage_is_research_only(self) -> None:
        self.assertTrue(es.EVIDENCE_STRENGTH_STAGE.endswith("research-only"))

    def test_payload_freezes_contract(self) -> None:
        payload = es.build_strength(
            shadow_loader=lambda: [],
            devils_advocate_loader=lambda: None,
        )
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["diagnosticOnly"])


class ComponentMathTests(unittest.TestCase):
    def test_sample_size_capped_at_one(self) -> None:
        self.assertEqual(es.sample_size_strength(es.TARGET_SAMPLES * 2), 1.0)
        self.assertEqual(es.sample_size_strength(es.TARGET_SAMPLES), 1.0)
        self.assertEqual(es.sample_size_strength(0), 0.0)

    def test_wilson_strength_at_coinflip_is_zero(self) -> None:
        self.assertEqual(es.wilson_strength(0.5), 0.0)
        self.assertEqual(es.wilson_strength(0.0), 0.0)
        self.assertAlmostEqual(es.wilson_strength(0.75), 0.5)
        self.assertEqual(es.wilson_strength(1.0), 1.0)

    def test_expectancy_strength_negative_clamped(self) -> None:
        self.assertEqual(es.expectancy_strength(-0.5), 0.0)
        self.assertEqual(es.expectancy_strength(0.0), 0.0)
        self.assertAlmostEqual(es.expectancy_strength(es.TARGET_EXPECTANCY_R), 1.0)
        # Above target stays clamped at 1.
        self.assertEqual(es.expectancy_strength(es.TARGET_EXPECTANCY_R * 5), 1.0)

    def test_falsification_strength_no_strategies_returns_none(self) -> None:
        self.assertIsNone(es.falsification_strength(0, 0))

    def test_falsification_strength_basic(self) -> None:
        self.assertEqual(es.falsification_strength(3, 5), 0.6)


class CompositeStrengthTests(unittest.TestCase):
    def test_empty_components_returns_zero(self) -> None:
        strength, active = es.composite_strength({})
        self.assertEqual(strength, 0.0)
        self.assertEqual(active, [])

    def test_all_none_returns_zero(self) -> None:
        strength, active = es.composite_strength({"a": None, "b": None})
        self.assertEqual(strength, 0.0)
        self.assertEqual(active, [])

    def test_single_component_zero_caps_composite_at_floor(self) -> None:
        # Geometric mean of (0.9, 0.9, 0.001) is small, demonstrating that
        # one weak component drags the whole composite down.
        strong = es.composite_strength({"a": 0.9, "b": 0.9, "c": 0.9})[0]
        weak = es.composite_strength({"a": 0.9, "b": 0.9, "c": 0.001})[0]
        self.assertLess(weak, 0.2)
        self.assertGreater(strong, 0.8)
        # And dramatically less than arithmetic mean (which would be ~0.6).
        self.assertLess(weak, (0.9 + 0.9 + 0.001) / 3)

    def test_skipping_none_components(self) -> None:
        # falsification=None should be skipped, not zeroed.
        strength_full, active_full = es.composite_strength({"a": 0.8, "b": 0.8, "c": 0.8})
        strength_skip, active_skip = es.composite_strength({"a": 0.8, "b": 0.8, "c": 0.8, "d": None})
        self.assertEqual(strength_full, strength_skip)
        self.assertNotIn("d", active_skip)

    def test_composite_caps_at_one(self) -> None:
        strength, _ = es.composite_strength({"a": 1.5, "b": 1.5})  # over-1 input
        # _clamp pulls back to 1.0.
        self.assertLessEqual(strength, 1.0)


class ClassificationTests(unittest.TestCase):
    def test_no_evidence_when_no_samples(self) -> None:
        self.assertEqual(es.classify_verdict(0.99, 0), "no-evidence")

    def test_thresholds(self) -> None:
        self.assertEqual(es.classify_verdict(0.80, 10), "strong")
        self.assertEqual(es.classify_verdict(0.50, 10), "moderate")
        self.assertEqual(es.classify_verdict(0.25, 10), "weak")
        self.assertEqual(es.classify_verdict(0.10, 10), "insufficient")


class BuildStrengthTests(unittest.TestCase):
    def test_no_data(self) -> None:
        payload = es.build_strength(
            shadow_loader=lambda: [],
            devils_advocate_loader=lambda: None,
        )
        self.assertEqual(payload["verdict"], "no-evidence")
        self.assertEqual(payload["strength"], 0.0)
        self.assertEqual(payload["totalSamples"], 0)

    def test_strong_evidence(self) -> None:
        # 80 winning samples, +1R each.
        records = closed_records([1.0] * 80)
        da = {"edgesHolding": 3, "strategyCount": 3, "verdict": "edges-survive"}
        payload = es.build_strength(
            shadow_loader=lambda: records,
            devils_advocate_loader=lambda: da,
        )
        self.assertEqual(payload["verdict"], "strong")
        self.assertGreater(payload["strength"], 0.7)
        self.assertEqual(payload["wins"], 80)
        self.assertEqual(payload["losses"], 0)

    def test_weak_when_one_component_is_weak(self) -> None:
        # Strong on sample size + wilson + expectancy, but devil's advocate
        # falsified everything (0/3 holding) — composite should drop hard.
        records = closed_records([1.0] * 80)
        da = {"edgesHolding": 0, "strategyCount": 3, "verdict": "edges-falsified"}
        payload = es.build_strength(
            shadow_loader=lambda: records,
            devils_advocate_loader=lambda: da,
        )
        # 0/3 falsification = 0 component, geometric mean → 0.
        self.assertLessEqual(payload["strength"], 0.05)
        self.assertEqual(payload["edgesHolding"], 0)
        self.assertEqual(payload["weakestComponent"], "falsification")

    def test_missing_da_drops_component_not_strength(self) -> None:
        records = closed_records([1.0] * 80)
        payload = es.build_strength(
            shadow_loader=lambda: records,
            devils_advocate_loader=lambda: None,
        )
        # No DA, so falsification component is None — composite is over the
        # three other components, which are all strong.
        self.assertGreater(payload["strength"], 0.5)
        self.assertNotIn("falsification", payload["activeComponents"])

    def test_negative_expectancy_zeroes_that_component(self) -> None:
        records = closed_records([-1.0] * 80)
        payload = es.build_strength(
            shadow_loader=lambda: records,
            devils_advocate_loader=lambda: None,
        )
        self.assertEqual(payload["components"]["expectancyLower"], 0.0)
        self.assertEqual(payload["losses"], 80)
        # Composite collapses because expectancyLower == 0.
        self.assertLess(payload["strength"], 0.1)

    def test_weakest_component_surfaced(self) -> None:
        records = closed_records([1.0] * 80)
        da = {"edgesHolding": 1, "strategyCount": 5, "verdict": "edges-weak"}
        payload = es.build_strength(
            shadow_loader=lambda: records,
            devils_advocate_loader=lambda: da,
        )
        # falsification = 1/5 = 0.2, which should be the weakest of the four.
        self.assertEqual(payload["weakestComponent"], "falsification")


def asymmetric_records(win_count: int, loss_count: int, win_r: float, loss_r: float) -> list[dict]:
    """Closed records with explicit asymmetric R payoffs (win_r > 0, loss_r < 0)."""
    return closed_records([win_r] * win_count + [loss_r] * loss_count)


class BreakevenAnchorTests(unittest.TestCase):
    """The win-rate axis must be anchored at the payoff-implied breakeven,
    not a flat 0.5 coinflip — otherwise asymmetric positive-expectancy
    structures (long premium, debit spreads) are wrongly labelled no-edge."""

    def test_empirical_breakeven_symmetric_is_half(self) -> None:
        self.assertAlmostEqual(es.empirical_breakeven([1.0, -1.0, 1.0, -1.0]), 0.5)

    def test_empirical_breakeven_three_to_one(self) -> None:
        # avg_win 3, avg_loss 1 -> breakeven 1/(1+3) = 0.25
        self.assertAlmostEqual(es.empirical_breakeven([3.0, 3.0, -1.0, -1.0]), 0.25)

    def test_empirical_breakeven_one_sided_returns_none(self) -> None:
        self.assertIsNone(es.empirical_breakeven([1.0, 1.0, 1.0]))
        self.assertIsNone(es.empirical_breakeven([-1.0, -1.0]))
        self.assertIsNone(es.empirical_breakeven([]))

    def test_wilson_strength_default_anchor_unchanged(self) -> None:
        # Backward compatible: no breakeven arg keeps the 0.5 coinflip map.
        self.assertEqual(es.wilson_strength(0.5), 0.0)
        self.assertAlmostEqual(es.wilson_strength(0.75), 0.5)

    def test_wilson_strength_breakeven_anchor_rewards_sub_half(self) -> None:
        # A 0.30 Wilson lower is no-edge at a 0.5 anchor but positive at 0.25.
        self.assertEqual(es.wilson_strength(0.30, 0.5), 0.0)
        self.assertGreater(es.wilson_strength(0.30, 0.25), 0.0)

    def test_asymmetric_winner_not_labelled_insufficient(self) -> None:
        # 40 wins at +3R, 60 losses at -1R: 40% hit rate but +0.6R expectancy.
        # Under the old 0.5 anchor this collapsed to "insufficient"; with the
        # payoff-implied breakeven (0.25) it must read as real evidence.
        records = asymmetric_records(40, 60, 3.0, -1.0)
        payload = es.build_strength(
            shadow_loader=lambda: records,
            devils_advocate_loader=lambda: None,
        )
        self.assertEqual(payload["winRateBreakeven"], 0.25)
        self.assertEqual(payload["winRateBreakevenSource"], "payoff-implied")
        self.assertTrue(payload["winRateConfirmsEdge"])
        self.assertNotEqual(payload["verdict"], "insufficient")
        self.assertGreater(payload["strength"], 0.3)

    def test_genuine_loser_is_not_rescued(self) -> None:
        # Symmetric 1:1 payoff, 20% win rate, strongly negative expectancy.
        # breakeven is 0.5, win rate is far below it -> no rescue, no edge.
        records = asymmetric_records(20, 80, 1.0, -1.0)
        payload = es.build_strength(
            shadow_loader=lambda: records,
            devils_advocate_loader=lambda: None,
        )
        self.assertAlmostEqual(payload["winRateBreakeven"], 0.5)
        self.assertFalse(payload["winRateConfirmsEdge"])
        self.assertEqual(payload["verdict"], "insufficient")


class TextRenderTests(unittest.TestCase):
    def test_text_contains_sections(self) -> None:
        records = closed_records([1.0] * 80)
        payload = es.build_strength(
            shadow_loader=lambda: records,
            devils_advocate_loader=lambda: {"edgesHolding": 2, "strategyCount": 3, "verdict": "edges-survive"},
        )
        text = es.strength_text(payload)
        self.assertIn("Evidence Strength", text)
        self.assertIn("Verdict:", text)
        self.assertIn("Component scores", text)
        self.assertIn("Thresholds:", text)


if __name__ == "__main__":
    unittest.main()
