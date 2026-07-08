from __future__ import annotations

"""Tests for inferno_math_config.

The central config module is the audit surface for every math knob. The
tests here are explicitly *boring* — they pin down invariants so a future
change can't silently drift any threshold or vocabulary item.

Counter-arguments the module must survive:

1. Same module_seed input always yields same output (determinism).
2. Different module_seed inputs almost certainly yield different outputs.
3. Empty module_name raises (no silent zero seed).
4. All seeds are in [0, 2^31).
5. Snapshot dict contains every documented knob.
6. Verdict vocabulary contains every word the math layer emits.
7. Operator levels map to monotonically increasing percentile gates.
8. Promotion thresholds match the RISK_POLICY docs (sanity floor).
"""

import unittest

import inferno_math_config as mc


class SeedDeterminismTests(unittest.TestCase):
    def test_module_seed_is_deterministic(self) -> None:
        a = mc.module_seed("inferno_devils_advocate")
        b = mc.module_seed("inferno_devils_advocate")
        self.assertEqual(a, b)

    def test_different_names_yield_different_seeds(self) -> None:
        names = [
            "inferno_devils_advocate",
            "inferno_evidence_strength",
            "inferno_kelly_sizing",
            "inferno_vol_premium",
            "inferno_bayesian_winrate",
            "inferno_regime_drift",
            "inferno_information_gain",
            "inferno_walk_forward",
            "inferno_factor_regression",
            "inferno_slate_normalizer",
            "inferno_paper_bootstrap",
        ]
        seeds = {n: mc.module_seed(n) for n in names}
        # No collisions across our actual module names.
        self.assertEqual(len(set(seeds.values())), len(names))

    def test_seed_in_signed_int32_range(self) -> None:
        for name in ("a", "b", "c", "inferno_x"):
            s = mc.module_seed(name)
            self.assertGreaterEqual(s, 0)
            self.assertLess(s, 2 ** 31)

    def test_empty_module_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            mc.module_seed("")
        with self.assertRaises(ValueError):
            mc.module_seed(None)  # type: ignore[arg-type]


class OperatorLevelTests(unittest.TestCase):
    def test_default_is_top_20(self) -> None:
        self.assertEqual(mc.gate_percentile_for_level("default"), 80.0)

    def test_unknown_level_falls_back_to_default(self) -> None:
        self.assertEqual(mc.gate_percentile_for_level("not-a-level"), 80.0)

    def test_levels_are_monotonically_pickier(self) -> None:
        # Each step up the picky ladder should raise the percentile threshold.
        self.assertLess(
            mc.gate_percentile_for_level("default"),
            mc.gate_percentile_for_level("ackman"),
        )
        self.assertLess(
            mc.gate_percentile_for_level("ackman"),
            mc.gate_percentile_for_level("buffett"),
        )
        self.assertLess(
            mc.gate_percentile_for_level("buffett"),
            mc.gate_percentile_for_level("simons"),
        )

    def test_levels_are_case_insensitive(self) -> None:
        self.assertEqual(
            mc.gate_percentile_for_level("Buffett"),
            mc.gate_percentile_for_level("buffett"),
        )


class VerdictVocabTests(unittest.TestCase):
    def test_vocab_is_immutable_frozenset(self) -> None:
        self.assertIsInstance(mc.VERDICT_VOCAB, frozenset)

    def test_vocab_includes_universal_bands(self) -> None:
        for band in ("strong", "moderate", "weak", "insufficient", "no-evidence"):
            self.assertIn(band, mc.VERDICT_VOCAB)

    def test_vocab_covers_every_module_emitting_verdicts(self) -> None:
        # If a module emits a verdict not in the vocabulary, the audit
        # surface has drifted. Pin the major ones here.
        required = {
            "edge-holds", "edge-falsified",            # devils advocate
            "survives", "decays", "reverses",          # walk-forward
            "stable", "unstable",                      # regime drift
            "sized", "cap-limited", "no-position",     # kelly
            "ranked", "ready-to-seed", "no-candidates",
            "clean", "violations-detected",
        }
        for verdict in required:
            self.assertIn(verdict, mc.VERDICT_VOCAB, f"missing verdict: {verdict}")


class PromotionThresholdTests(unittest.TestCase):
    """Sanity floor — these constants must match the published docs."""

    def test_promotion_sample_size_floor(self) -> None:
        self.assertGreaterEqual(mc.MIN_PAPER_SAMPLES_FOR_PROMOTION, 30)

    def test_distinct_event_promotion_floor(self) -> None:
        self.assertGreaterEqual(mc.MIN_DISTINCT_EVENTS_FOR_PROMOTION, 30)

    def test_wilson_floor_above_coinflip(self) -> None:
        self.assertGreater(mc.MIN_WILSON_LOWER_FOR_EDGE, 0.40)
        self.assertLess(mc.MIN_WILSON_LOWER_FOR_EDGE, 0.55)

    def test_devils_advocate_thresholds_ordered(self) -> None:
        self.assertLess(mc.DEVILS_ADVOCATE_HOLD_P, mc.DEVILS_ADVOCATE_WEAKEN_P)

    def test_evidence_strength_ladder_ordered(self) -> None:
        self.assertGreater(mc.EVIDENCE_STRENGTH_STRONG, mc.EVIDENCE_STRENGTH_MODERATE)
        self.assertGreater(mc.EVIDENCE_STRENGTH_MODERATE, mc.EVIDENCE_STRENGTH_WEAK)
        self.assertGreater(mc.EVIDENCE_STRENGTH_WEAK, 0.0)
        self.assertLess(mc.EVIDENCE_STRENGTH_STRONG, 1.0)

    def test_kelly_cap_in_safe_range(self) -> None:
        self.assertGreater(mc.MAX_KELLY_FRACTION, 0.0)
        self.assertLessEqual(mc.MAX_KELLY_FRACTION, 0.50,
                             "more than half-Kelly is dangerous; check the cap")

    def test_max_daily_risk_units_positive(self) -> None:
        self.assertGreater(mc.MAX_DAILY_RISK_UNITS, 0.0)


class SnapshotTests(unittest.TestCase):
    def test_snapshot_returns_dict(self) -> None:
        snap = mc.snapshot()
        self.assertIsInstance(snap, dict)

    def test_snapshot_has_every_documented_field(self) -> None:
        snap = mc.snapshot()
        required = {
            "mathSeed", "defaultBootstrapResamples",
            "defaultPermutationResamples", "defaultPosteriorDraws",
            "defaultAlpha", "defaultZ", "operatorLevel", "gatePercentile",
            "minPaperSamplesForPromotion", "minDistinctEventsForPromotion", "minWilsonLowerForEdge",
            "devilsAdvocateHoldP", "devilsAdvocateWeakenP",
            "evidenceStrengthStrong", "evidenceStrengthModerate",
            "evidenceStrengthWeak", "maxKellyFraction",
            "maxDailyRiskUnits", "verdictVocabSize",
        }
        self.assertTrue(required.issubset(snap.keys()),
                        f"missing keys: {required - snap.keys()}")

    def test_snapshot_seed_matches_master(self) -> None:
        snap = mc.snapshot()
        self.assertEqual(snap["mathSeed"], mc.MATH_SEED)


class DefaultValuesTests(unittest.TestCase):
    """Pin the numerical defaults so a future edit raises a red flag."""

    def test_default_bootstrap_resamples(self) -> None:
        self.assertEqual(mc.DEFAULT_BOOTSTRAP_RESAMPLES, 2000)

    def test_default_permutation_resamples(self) -> None:
        self.assertEqual(mc.DEFAULT_PERMUTATION_RESAMPLES, 1000)

    def test_default_posterior_draws(self) -> None:
        self.assertEqual(mc.DEFAULT_POSTERIOR_DRAWS, 4000)

    def test_default_alpha_is_five_percent(self) -> None:
        self.assertEqual(mc.DEFAULT_ALPHA, 0.05)

    def test_default_z_matches_alpha(self) -> None:
        # z = 1.96 for two-tailed alpha=0.05.
        self.assertAlmostEqual(mc.DEFAULT_Z, 1.96, places=2)


class ClusterBootstrapTests(unittest.TestCase):
    def test_cluster_bootstrap_resamples_whole_events(self) -> None:
        records = [
            {"event": "A", "r": 1.0},
            {"event": "A", "r": 1.0},
            {"event": "B", "r": -1.0},
        ]

        mean, lower, upper = mc.cluster_bootstrap_mean_ci(
            records,
            value_fn=lambda row: row["r"],
            cluster_key_fn=lambda row: row["event"],
            resamples=200,
            seed=1,
        )

        self.assertAlmostEqual(mean, 1.0 / 3.0)
        self.assertLessEqual(lower, mean)
        self.assertGreaterEqual(upper, mean)

    def test_single_cluster_ci_collapses_to_mean(self) -> None:
        mean, lower, upper = mc.cluster_bootstrap_mean_ci(
            [{"event": "A", "r": 1.0}, {"event": "A", "r": -1.0}],
            value_fn=lambda row: row["r"],
            cluster_key_fn=lambda row: row["event"],
        )

        self.assertEqual((mean, lower, upper), (0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
