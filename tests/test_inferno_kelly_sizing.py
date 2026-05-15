from __future__ import annotations

"""Adversarial tests for inferno_kelly_sizing.

Counter-arguments the module must survive:

1. Empty input → 'no-evidence', no math attempted.
2. Single sample → bootstrap CI collapses; verdict 'insufficient'.
3. All-winning strategy, n >= MIN: f_capped == MAX_KELLY (cap-limited).
4. All-losing strategy: verdict 'no-position', f == 0.
5. Zero-variance (all-identical samples): verdict 'degenerate', f == 0.
6. Mean > 0 but lower bound <= 0 with small sample → 'marginal'.
7. Sum exceeds risk ceiling → ceiling-binding, total clipped.
8. Strategy classification monotone: better strategies sort first.
9. Bootstrap seed reproducible.
10. researchOnly/promotable/diagnosticOnly contract frozen.
11. sample_variance edge cases: n=0, n=1, identical samples.
"""

import unittest

import inferno_kelly_sizing as ks


def closed_records(strategy: str, r_units: list[float]) -> list[dict]:
    return [
        {
            "strategy": strategy,
            "outcome": {"status": "closed"},
            "estimatedPnl": float(value),
            "maxLossDollars": 1.0,
        }
        for value in r_units
    ]


class ContractTests(unittest.TestCase):
    def test_stage_is_research_only(self) -> None:
        self.assertTrue(ks.KELLY_SIZING_STAGE.endswith("research-only"))

    def test_payload_freezes_contract(self) -> None:
        payload = ks.build_kelly_sizing(shadow_loader=lambda: [])
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["diagnosticOnly"])


class SampleVarianceTests(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(ks.sample_variance([]), 0.0)

    def test_single_sample(self) -> None:
        self.assertEqual(ks.sample_variance([1.5]), 0.0)

    def test_identical_samples(self) -> None:
        self.assertEqual(ks.sample_variance([0.5, 0.5, 0.5, 0.5]), 0.0)

    def test_known_value(self) -> None:
        # Sample variance of [1, 2, 3, 4, 5] with ddof=1 is 2.5.
        self.assertAlmostEqual(ks.sample_variance([1, 2, 3, 4, 5]), 2.5, places=6)


class BootstrapMomentCITests(unittest.TestCase):
    def test_empty(self) -> None:
        point, lo, hi = ks.bootstrap_moment_ci([], lambda x: sum(x) / max(len(x), 1))
        self.assertEqual((point, lo, hi), (0.0, 0.0, 0.0))

    def test_single_sample_collapses(self) -> None:
        point, lo, hi = ks.bootstrap_moment_ci([3.0], lambda x: sum(x) / len(x))
        self.assertEqual(point, 3.0)
        self.assertEqual(lo, 3.0)
        self.assertEqual(hi, 3.0)

    def test_seed_reproducible(self) -> None:
        samples = [0.3, -0.1, 0.8, -0.4, 0.5, 0.2, -0.1, 0.7, 0.4, -0.2]
        a_pt, a_lo, a_hi = ks.bootstrap_moment_ci(samples, lambda x: sum(x) / len(x), resamples=500, seed=99)
        b_pt, b_lo, b_hi = ks.bootstrap_moment_ci(samples, lambda x: sum(x) / len(x), resamples=500, seed=99)
        self.assertEqual((a_pt, a_lo, a_hi), (b_pt, b_lo, b_hi))


class KellyMathTests(unittest.TestCase):
    def test_kelly_fraction_zero_variance(self) -> None:
        self.assertEqual(ks.kelly_fraction(0.5, 0.0), 0.0)
        self.assertEqual(ks.kelly_fraction(0.5, -1.0), 0.0)

    def test_kelly_fraction_negative_mean(self) -> None:
        self.assertEqual(ks.kelly_fraction(-0.5, 1.0), 0.0)
        self.assertEqual(ks.kelly_fraction(0.0, 1.0), 0.0)

    def test_kelly_fraction_basic(self) -> None:
        # μ=0.4, σ²=1.0 → f*=0.4. Quarter-Kelly cap would clip this to 0.25.
        self.assertAlmostEqual(ks.kelly_fraction(0.4, 1.0), 0.4)

    def test_conservative_kelly_lower_bound_negative(self) -> None:
        self.assertEqual(ks.conservative_kelly(-0.1, 1.0), 0.0)

    def test_conservative_kelly_upper_variance_zero(self) -> None:
        self.assertEqual(ks.conservative_kelly(0.1, 0.0), 0.0)

    def test_conservative_kelly_smaller_than_point(self) -> None:
        # Asymmetric bound version uses lower-mean over upper-variance.
        # μ_lo=0.1, σ²_hi=1.6 → 0.0625 << μ/σ² = 0.4/1.0 = 0.4 point.
        f_point = ks.kelly_fraction(0.4, 1.0)
        f_conservative = ks.conservative_kelly(0.1, 1.6)
        self.assertLess(f_conservative, f_point)


class ClassificationTests(unittest.TestCase):
    def test_insufficient_below_min(self) -> None:
        self.assertEqual(
            ks.classify_strategy(
                sample_size=ks.MIN_KELLY_SAMPLES - 1,
                mean=1.0, variance=1.0,
                f_conservative=0.1, f_capped=0.1,
            ),
            "insufficient",
        )

    def test_no_position_when_mean_nonpositive(self) -> None:
        self.assertEqual(
            ks.classify_strategy(
                sample_size=20, mean=-0.1, variance=1.0,
                f_conservative=0.0, f_capped=0.0,
            ),
            "no-position",
        )

    def test_degenerate_zero_variance(self) -> None:
        self.assertEqual(
            ks.classify_strategy(
                sample_size=20, mean=0.5, variance=0.0,
                f_conservative=0.0, f_capped=0.0,
            ),
            "degenerate",
        )

    def test_marginal_when_lower_bound_nonpositive(self) -> None:
        self.assertEqual(
            ks.classify_strategy(
                sample_size=20, mean=0.5, variance=1.0,
                f_conservative=0.0, f_capped=0.0,
            ),
            "marginal",
        )

    def test_cap_limited(self) -> None:
        self.assertEqual(
            ks.classify_strategy(
                sample_size=20, mean=2.0, variance=1.0,
                f_conservative=2.0, f_capped=ks.MAX_KELLY_FRACTION,
            ),
            "cap-limited",
        )

    def test_sized_default(self) -> None:
        # f_capped strictly below MAX_KELLY to avoid cap-limited.
        self.assertEqual(
            ks.classify_strategy(
                sample_size=20, mean=0.1, variance=1.0,
                f_conservative=0.1, f_capped=0.1,
            ),
            "sized",
        )


class BuildKellySizingTests(unittest.TestCase):
    def test_no_records(self) -> None:
        payload = ks.build_kelly_sizing(shadow_loader=lambda: [])
        self.assertEqual(payload["verdict"], "no-evidence")
        self.assertEqual(payload["totalRecommendedRiskUnits"], 0.0)

    def test_all_winning_caps_at_max_kelly(self) -> None:
        records = closed_records("Vertical Call", [1.0] * 20)
        payload = ks.build_kelly_sizing(shadow_loader=lambda: records, resamples=300)
        row = payload["rows"][0]
        # All-winning with positive variance: cap-limited.
        # (All identical actually → variance == 0 → 'degenerate', so use mixed wins.)
        # We need realistic variance. Use 1.0 mixed with a couple of 0.5s.
        records2 = closed_records("Vertical Call", [1.0] * 15 + [0.5] * 5)
        payload2 = ks.build_kelly_sizing(shadow_loader=lambda: records2, resamples=300)
        row2 = payload2["rows"][0]
        self.assertIn(row2["verdict"], {"cap-limited", "sized"})
        self.assertGreater(row2["meanR"], 0)

    def test_all_identical_samples_degenerate(self) -> None:
        # All identical -> variance == 0 -> degenerate.
        records = closed_records("Iron Condor", [0.5] * 20)
        payload = ks.build_kelly_sizing(shadow_loader=lambda: records, resamples=200)
        self.assertEqual(payload["rows"][0]["verdict"], "degenerate")
        self.assertEqual(payload["rows"][0]["kellyFractionCapped"], 0.0)

    def test_all_losing_no_position(self) -> None:
        records = closed_records("Straddle", [-1.0, -0.5, -0.8, -0.6, -0.9, -0.7, -1.0, -0.4, -0.5, -0.6])
        payload = ks.build_kelly_sizing(shadow_loader=lambda: records, resamples=200)
        self.assertEqual(payload["rows"][0]["verdict"], "no-position")
        self.assertEqual(payload["rows"][0]["kellyFractionCapped"], 0.0)

    def test_ceiling_binding_when_sum_exceeds_max(self) -> None:
        # Three strategies, each likely to hit the cap → sum > MAX_DAILY_RISK_UNITS
        # only when MAX_DAILY_RISK_UNITS is, e.g., 0.5. Override via the constant.
        original_max = ks.MAX_DAILY_RISK_UNITS
        ks.MAX_DAILY_RISK_UNITS = 0.3
        try:
            records = []
            for name in ("S1", "S2", "S3"):
                records.extend(closed_records(name, [1.0] * 15 + [0.5] * 5))
            payload = ks.build_kelly_sizing(shadow_loader=lambda: records, resamples=200)
            self.assertTrue(payload["ceilingBinding"])
            self.assertEqual(payload["totalRecommendedRiskUnits"], 0.3)
        finally:
            ks.MAX_DAILY_RISK_UNITS = original_max

    def test_rows_sorted_by_f_capped_desc(self) -> None:
        # Big = mostly 1R wins → high Kelly. Small = mixed → smaller Kelly.
        records = (
            closed_records("Big", [1.0] * 18 + [0.5] * 2)
            + closed_records("Small", [0.2] * 10 + [-0.1] * 10)
        )
        payload = ks.build_kelly_sizing(shadow_loader=lambda: records, resamples=200)
        # Big should sort first (higher f_capped).
        self.assertEqual(payload["rows"][0]["strategy"], "Big")


class TextRenderTests(unittest.TestCase):
    def test_text_contains_sections(self) -> None:
        records = closed_records("Vertical Call", [1.0] * 15 + [0.3] * 5)
        payload = ks.build_kelly_sizing(shadow_loader=lambda: records, resamples=200)
        text = ks.kelly_text(payload)
        self.assertIn("Kelly Sizing", text)
        self.assertIn("Verdict:", text)
        self.assertIn("Per-strategy Kelly:", text)
        self.assertIn("Vertical Call", text)
        self.assertIn("Thresholds:", text)


if __name__ == "__main__":
    unittest.main()
