from __future__ import annotations

"""Adversarial tests for inferno_regime_drift.

Counter-arguments the module must survive:

1. Empty data → 'no-evidence'.
2. Stationary stream → no alarms, verdict 'stable'.
3. Step-down in second half → 'decaying' verdict.
4. Step-up in second half → 'improving' verdict.
5. Both up and down alarms → 'unstable'.
6. Alarm fires in baseline half → 'baseline-noisy'.
7. Below MIN_DRIFT_SAMPLES → 'insufficient'.
8. Zero-variance baseline does not crash (std defaults to 1).
9. researchOnly / promotable / diagnosticOnly contract frozen.
"""

import unittest

import inferno_regime_drift as drift


def closed_records(strategy: str, r_units: list[float], timestamps: list[str] | None = None) -> list[dict]:
    if timestamps is None:
        timestamps = [f"2026-01-{i+1:02d}T00:00:00" for i in range(len(r_units))]
    return [
        {
            "strategy": strategy,
            "outcome": {"status": "closed", "closedAt": ts},
            "estimatedPnl": float(v),
            "maxLossDollars": 1.0,
        }
        for v, ts in zip(r_units, timestamps)
    ]


class ContractTests(unittest.TestCase):
    def test_stage(self) -> None:
        self.assertTrue(drift.REGIME_DRIFT_STAGE.endswith("research-only"))

    def test_contract_frozen(self) -> None:
        payload = drift.build_regime_drift(shadow_loader=lambda: [])
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["diagnosticOnly"])


class BaselineStatsTests(unittest.TestCase):
    def test_empty_baseline_defaults(self) -> None:
        mean, std = drift.baseline_stats([], 0)
        self.assertEqual((mean, std), (0.0, 1.0))

    def test_n_one_returns_value_with_std_one(self) -> None:
        mean, std = drift.baseline_stats([0.5], 1)
        self.assertEqual(mean, 0.5)
        self.assertEqual(std, 1.0)

    def test_identical_baseline_uses_default_std(self) -> None:
        mean, std = drift.baseline_stats([0.5, 0.5, 0.5, 0.5], 4)
        self.assertEqual(mean, 0.5)
        self.assertEqual(std, 1.0)


class CusumTracesTests(unittest.TestCase):
    def test_zero_deviation_stream_stays_zero(self) -> None:
        s_pos, s_neg = drift.cusum_traces([1.0] * 20, mean=1.0, std=1.0, allowance=0.5)
        self.assertTrue(all(value == 0.0 for value in s_pos))
        self.assertTrue(all(value == 0.0 for value in s_neg))

    def test_positive_drift_accumulates(self) -> None:
        # All values above the upper tolerance band -> S+ grows monotonically.
        s_pos, s_neg = drift.cusum_traces([5.0] * 10, mean=0.0, std=1.0, allowance=0.5)
        for i in range(1, len(s_pos)):
            self.assertGreater(s_pos[i], s_pos[i - 1])
        self.assertTrue(all(value == 0.0 for value in s_neg))

    def test_negative_drift_accumulates(self) -> None:
        s_pos, s_neg = drift.cusum_traces([-5.0] * 10, mean=0.0, std=1.0, allowance=0.5)
        for i in range(1, len(s_neg)):
            self.assertLess(s_neg[i], s_neg[i - 1])
        self.assertTrue(all(value == 0.0 for value in s_pos))


class ClassifyTests(unittest.TestCase):
    def test_insufficient(self) -> None:
        self.assertEqual(
            drift.classify_drift(sample_size=4, half_index=2, alarm_pos=None, alarm_neg=None),
            "insufficient",
        )

    def test_stable(self) -> None:
        self.assertEqual(
            drift.classify_drift(sample_size=20, half_index=10, alarm_pos=None, alarm_neg=None),
            "stable",
        )

    def test_decaying(self) -> None:
        self.assertEqual(
            drift.classify_drift(sample_size=20, half_index=10, alarm_pos=None, alarm_neg=15),
            "decaying",
        )

    def test_improving(self) -> None:
        self.assertEqual(
            drift.classify_drift(sample_size=20, half_index=10, alarm_pos=14, alarm_neg=None),
            "improving",
        )

    def test_unstable(self) -> None:
        self.assertEqual(
            drift.classify_drift(sample_size=20, half_index=10, alarm_pos=14, alarm_neg=18),
            "unstable",
        )

    def test_baseline_noisy(self) -> None:
        self.assertEqual(
            drift.classify_drift(sample_size=20, half_index=10, alarm_pos=4, alarm_neg=None),
            "baseline-noisy",
        )


class BuildDriftTests(unittest.TestCase):
    def test_no_records(self) -> None:
        payload = drift.build_regime_drift(shadow_loader=lambda: [])
        self.assertEqual(payload["verdict"], "no-evidence")

    def test_stationary_stream(self) -> None:
        # 24 samples, well-behaved random small variation around 0.2R.
        rs = [0.2, 0.1, 0.3, 0.2, 0.15, 0.25, 0.2, 0.1, 0.3, 0.2, 0.15, 0.25] * 2
        records = closed_records("Steady", rs)
        payload = drift.build_regime_drift(shadow_loader=lambda: records)
        self.assertEqual(payload["rows"][0]["verdict"], "stable")

    def test_step_down_decay(self) -> None:
        # First 12 samples win (+1R), next 12 lose (-1R) — classic decay.
        rs = [1.0] * 12 + [-1.0] * 12
        records = closed_records("Decaying", rs)
        payload = drift.build_regime_drift(shadow_loader=lambda: records, alarm_h=2.0)
        self.assertEqual(payload["rows"][0]["verdict"], "decaying")

    def test_step_up_improvement(self) -> None:
        rs = [-1.0] * 12 + [1.0] * 12
        records = closed_records("Improving", rs)
        payload = drift.build_regime_drift(shadow_loader=lambda: records, alarm_h=2.0)
        self.assertEqual(payload["rows"][0]["verdict"], "improving")

    def test_below_minimum_insufficient(self) -> None:
        rs = [0.5] * (drift.MIN_DRIFT_SAMPLES - 1)
        records = closed_records("Tiny", rs)
        payload = drift.build_regime_drift(shadow_loader=lambda: records)
        self.assertEqual(payload["rows"][0]["verdict"], "insufficient")


class TextRenderTests(unittest.TestCase):
    def test_text_has_sections(self) -> None:
        rs = [1.0] * 12 + [-1.0] * 12
        records = closed_records("Decaying", rs)
        payload = drift.build_regime_drift(shadow_loader=lambda: records, alarm_h=2.0)
        text = drift.drift_text(payload)
        self.assertIn("Regime Drift", text)
        self.assertIn("Verdict:", text)
        self.assertIn("Per-strategy CUSUM:", text)
        self.assertIn("Decaying", text)


if __name__ == "__main__":
    unittest.main()
