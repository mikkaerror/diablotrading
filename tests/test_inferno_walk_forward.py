from __future__ import annotations

"""Adversarial tests for inferno_walk_forward.

Counter-arguments the module must survive:

1. Empty data → 'no-evidence'.
2. Below MIN_WF_SAMPLES → 'insufficient'.
3. Stationary positive stream → 'survives'.
4. Step-up edge that only appears in validate → 'emerged'.
5. Step-down edge in validate → 'reverses' or 'decays' depending on sign.
6. Negative in both halves → 'no-edge'.
7. Split is exact ⌊n/2⌋ — train + validate == total.
8. researchOnly / promotable / diagnosticOnly contract frozen.
"""

import unittest

import inferno_walk_forward as wf


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
        self.assertTrue(wf.WALK_FORWARD_STAGE.endswith("research-only"))

    def test_contract_frozen(self) -> None:
        payload = wf.build_walk_forward(shadow_loader=lambda: [])
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["diagnosticOnly"])


class SplitTests(unittest.TestCase):
    def test_empty(self) -> None:
        train, validate = wf.split_chronologically([])
        self.assertEqual((train, validate), ([], []))

    def test_odd_count_floor_split(self) -> None:
        train, validate = wf.split_chronologically([1, 2, 3, 4, 5])
        self.assertEqual(train, [1, 2])  # ⌊5/2⌋ = 2
        self.assertEqual(validate, [3, 4, 5])

    def test_even_count_half_split(self) -> None:
        train, validate = wf.split_chronologically([1, 2, 3, 4])
        self.assertEqual(train, [1, 2])
        self.assertEqual(validate, [3, 4])

    def test_train_validate_sum_to_total(self) -> None:
        for n in range(0, 50):
            train, validate = wf.split_chronologically(list(range(n)))
            self.assertEqual(len(train) + len(validate), n)


class ClassifyTests(unittest.TestCase):
    def test_insufficient(self) -> None:
        self.assertEqual(
            wf.classify_walk_forward(
                sample_size=wf.MIN_WF_SAMPLES - 1,
                train_mean=0.5, valid_mean=0.5, pooled_std=1.0,
            ),
            "insufficient",
        )

    def test_survives_within_band(self) -> None:
        self.assertEqual(
            wf.classify_walk_forward(
                sample_size=30, train_mean=0.4, valid_mean=0.3, pooled_std=1.0,
                tolerance_sigma=0.5,
            ),
            "survives",
        )

    def test_decays(self) -> None:
        self.assertEqual(
            wf.classify_walk_forward(
                sample_size=30, train_mean=1.0, valid_mean=0.2, pooled_std=1.0,
                tolerance_sigma=0.5,
            ),
            "decays",
        )

    def test_reverses(self) -> None:
        self.assertEqual(
            wf.classify_walk_forward(
                sample_size=30, train_mean=0.5, valid_mean=-0.5, pooled_std=1.0,
            ),
            "reverses",
        )

    def test_emerged(self) -> None:
        self.assertEqual(
            wf.classify_walk_forward(
                sample_size=30, train_mean=-0.2, valid_mean=0.5, pooled_std=1.0,
            ),
            "emerged",
        )

    def test_no_edge(self) -> None:
        self.assertEqual(
            wf.classify_walk_forward(
                sample_size=30, train_mean=-0.3, valid_mean=-0.4, pooled_std=1.0,
            ),
            "no-edge",
        )


class BuildWalkForwardTests(unittest.TestCase):
    def test_no_data(self) -> None:
        payload = wf.build_walk_forward(shadow_loader=lambda: [])
        self.assertEqual(payload["verdict"], "no-evidence")

    def test_stationary_positive_survives(self) -> None:
        rs = [0.5, 0.4, 0.6, 0.5, 0.4, 0.6] * 4  # 24 samples, all positive
        records = closed_records("Steady", rs)
        payload = wf.build_walk_forward(shadow_loader=lambda: records)
        self.assertEqual(payload["rows"][0]["verdict"], "survives")

    def test_step_down_reverses(self) -> None:
        rs = [1.0] * 12 + [-1.0] * 12  # 24 samples; train all win, validate all lose
        records = closed_records("Reversed", rs)
        payload = wf.build_walk_forward(shadow_loader=lambda: records)
        self.assertEqual(payload["rows"][0]["verdict"], "reverses")

    def test_emerged_when_train_negative(self) -> None:
        rs = [-1.0] * 12 + [1.0] * 12
        records = closed_records("Emerged", rs)
        payload = wf.build_walk_forward(shadow_loader=lambda: records)
        self.assertEqual(payload["rows"][0]["verdict"], "emerged")

    def test_train_plus_validate_equals_total(self) -> None:
        rs = [0.1] * 25  # odd number
        records = closed_records("Steady25", rs)
        payload = wf.build_walk_forward(shadow_loader=lambda: records)
        row = payload["rows"][0]
        self.assertEqual(row["trainSize"] + row["validateSize"], row["sampleSize"])


class TextRenderTests(unittest.TestCase):
    def test_text_has_sections(self) -> None:
        rs = [0.5] * 20
        records = closed_records("Steady", rs)
        payload = wf.build_walk_forward(shadow_loader=lambda: records)
        text = wf.walk_forward_text(payload)
        self.assertIn("Walk-Forward", text)
        self.assertIn("Verdict:", text)
        self.assertIn("Per-strategy walk-forward:", text)


if __name__ == "__main__":
    unittest.main()
