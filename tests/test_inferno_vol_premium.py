from __future__ import annotations

"""Adversarial tests for inferno_vol_premium.

Counter-arguments the module must survive:

1. Empty input → 'no-evidence'.
2. Missing IV rank → bucket 'unknown'; record skipped from cube.
3. Strategy → vol direction map handles substrings and unknowns.
4. IV bucket boundaries are correct at 33, 66, and 100.
5. Two-sample bootstrap on empty input returns (0,0,0).
6. Equal means yield discriminator CI straddling zero → uncertain.
7. Large positive lift yields vrp-real verdict.
8. Large negative lift yields vrp-absent verdict.
9. Insufficient sample on either side → 'insufficient' verdict.
10. researchOnly/promotable/diagnosticOnly contract frozen.
"""

import unittest

import inferno_vol_premium as vp


def closed_record(strategy: str, r: float, iv_rank: float | None) -> dict:
    return {
        "strategy": strategy,
        "outcome": {"status": "closed"},
        "estimatedPnl": float(r),
        "maxLossDollars": 1.0,
        "ivRank": iv_rank,
    }


class ContractTests(unittest.TestCase):
    def test_stage_is_research_only(self) -> None:
        self.assertTrue(vp.VOL_PREMIUM_STAGE.endswith("research-only"))

    def test_payload_freezes_contract(self) -> None:
        payload = vp.build_vol_premium(shadow_loader=lambda: [])
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["diagnosticOnly"])


class ClassifyVolDirectionTests(unittest.TestCase):
    def test_exact_match(self) -> None:
        self.assertEqual(vp.classify_vol_direction("Iron Condor"), "short-vol")
        self.assertEqual(vp.classify_vol_direction("Vertical Call"), "long-vol")
        self.assertEqual(vp.classify_vol_direction("Calendar"), "vega-neutral")

    def test_substring_fallback(self) -> None:
        # "Bull Put Credit Spread" should still match "credit spread".
        self.assertEqual(vp.classify_vol_direction("Bull Put Credit Spread"), "short-vol")

    def test_unknown(self) -> None:
        self.assertEqual(vp.classify_vol_direction("Mystery Box"), "unknown")
        self.assertEqual(vp.classify_vol_direction(""), "unknown")


class ClassifyIVBucketTests(unittest.TestCase):
    def test_boundaries(self) -> None:
        self.assertEqual(vp.classify_iv_bucket(0), "low")
        self.assertEqual(vp.classify_iv_bucket(32.99), "low")
        self.assertEqual(vp.classify_iv_bucket(33), "mid")
        self.assertEqual(vp.classify_iv_bucket(65.99), "mid")
        self.assertEqual(vp.classify_iv_bucket(66), "high")
        self.assertEqual(vp.classify_iv_bucket(100), "high")

    def test_none(self) -> None:
        self.assertEqual(vp.classify_iv_bucket(None), "unknown")

    def test_negative(self) -> None:
        self.assertEqual(vp.classify_iv_bucket(-5), "unknown")

    def test_non_numeric(self) -> None:
        self.assertEqual(vp.classify_iv_bucket("nope"), "unknown")


class BootstrapMeanDiffTests(unittest.TestCase):
    def test_empty_returns_zeros(self) -> None:
        point, lo, hi = vp.bootstrap_mean_diff([], [1.0])
        self.assertEqual((point, lo, hi), (0.0, 0.0, 0.0))
        point2, lo2, hi2 = vp.bootstrap_mean_diff([1.0], [])
        self.assertEqual((point2, lo2, hi2), (0.0, 0.0, 0.0))

    def test_n_one_each_collapses(self) -> None:
        point, lo, hi = vp.bootstrap_mean_diff([2.0], [1.0])
        self.assertEqual(point, 1.0)
        self.assertEqual(lo, 1.0)
        self.assertEqual(hi, 1.0)

    def test_clear_positive_lift(self) -> None:
        a = [1.0] * 20  # high bucket
        b = [-0.5] * 20  # low bucket
        point, lo, hi = vp.bootstrap_mean_diff(a, b, resamples=500)
        self.assertAlmostEqual(point, 1.5, places=4)
        self.assertGreater(lo, 0)  # CI excludes zero

    def test_clear_negative_lift(self) -> None:
        a = [-0.5] * 20
        b = [1.0] * 20
        point, lo, hi = vp.bootstrap_mean_diff(a, b, resamples=500)
        self.assertAlmostEqual(point, -1.5, places=4)
        self.assertLess(hi, 0)  # CI is entirely negative

    def test_equal_means_ci_straddles_zero(self) -> None:
        a = [0.5, -0.5] * 10
        b = [0.5, -0.5] * 10
        point, lo, hi = vp.bootstrap_mean_diff(a, b, resamples=500)
        self.assertAlmostEqual(point, 0.0, places=4)
        self.assertLessEqual(lo, 0)
        self.assertGreaterEqual(hi, 0)


class ClassifyDiscriminatorTests(unittest.TestCase):
    def test_insufficient(self) -> None:
        self.assertEqual(
            vp.classify_discriminator(
                sample_count_high=2, sample_count_low=10, lower=0.5, upper=1.0,
            ),
            "insufficient",
        )

    def test_vrp_real_when_lower_positive(self) -> None:
        self.assertEqual(
            vp.classify_discriminator(
                sample_count_high=10, sample_count_low=10, lower=0.1, upper=1.0,
            ),
            "vrp-real",
        )

    def test_vrp_absent_when_upper_nonpositive(self) -> None:
        self.assertEqual(
            vp.classify_discriminator(
                sample_count_high=10, sample_count_low=10, lower=-1.0, upper=-0.1,
            ),
            "vrp-absent",
        )

    def test_vrp_uncertain_when_ci_straddles_zero(self) -> None:
        self.assertEqual(
            vp.classify_discriminator(
                sample_count_high=10, sample_count_low=10, lower=-0.2, upper=0.3,
            ),
            "vrp-uncertain",
        )


class BuildVolPremiumTests(unittest.TestCase):
    def test_no_records(self) -> None:
        payload = vp.build_vol_premium(shadow_loader=lambda: [])
        self.assertEqual(payload["verdict"], "no-evidence")

    def test_short_vol_real_in_high_iv(self) -> None:
        records = (
            [closed_record("Iron Condor", 1.0, iv) for iv in [80] * 15]
            + [closed_record("Iron Condor", -0.8, iv) for iv in [20] * 15]
        )
        payload = vp.build_vol_premium(shadow_loader=lambda: records, resamples=500)
        # Find short-vol discriminator.
        short = next(d for d in payload["discriminators"] if d["direction"] == "short-vol")
        self.assertEqual(short["verdict"], "vrp-real")
        self.assertGreater(short["lower"], 0)

    def test_insufficient_when_one_bucket_thin(self) -> None:
        records = (
            [closed_record("Iron Condor", 1.0, 80) for _ in range(10)]
            + [closed_record("Iron Condor", -0.5, 20) for _ in range(2)]  # below min
        )
        payload = vp.build_vol_premium(shadow_loader=lambda: records, resamples=300)
        short = next(d for d in payload["discriminators"] if d["direction"] == "short-vol")
        self.assertEqual(short["verdict"], "insufficient")

    def test_missing_iv_record_goes_into_unknown_bucket(self) -> None:
        records = [closed_record("Iron Condor", 1.0, None) for _ in range(8)]
        payload = vp.build_vol_premium(shadow_loader=lambda: records, resamples=200)
        cube = payload["cube"]["short-vol"]
        self.assertIn("unknown", cube)
        self.assertNotIn("high", cube)


class TextRenderTests(unittest.TestCase):
    def test_text_contains_sections(self) -> None:
        records = (
            [closed_record("Iron Condor", 1.0, iv) for iv in [80] * 10]
            + [closed_record("Iron Condor", -0.5, iv) for iv in [20] * 10]
        )
        payload = vp.build_vol_premium(shadow_loader=lambda: records, resamples=200)
        text = vp.vol_premium_text(payload)
        self.assertIn("Vol Premium", text)
        self.assertIn("Verdict:", text)
        self.assertIn("Discriminators", text)
        self.assertIn("Cube", text)


if __name__ == "__main__":
    unittest.main()
