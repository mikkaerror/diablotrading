from __future__ import annotations

"""Adversarial tests for inferno_slate_normalizer.

Counter-arguments:
1. Empty slate → 'no-evidence', empty rows.
2. All-same values → rank ≈ 50 for every row (tie).
3. Sorted values → rank monotone increasing.
4. Null values get None rank, excluded from denominator.
5. Composite is geometric mean of active component ranks.
6. Top N% gate count is bounded by slate size.
7. Scale invariance: ranks unchanged if every value multiplied by 10.
8. researchOnly/promotable/diagnosticOnly contract frozen.
"""

import unittest

import inferno_slate_normalizer as norm


def make_row(**fields) -> dict:
    base = {"ticker": "T", "readyScore": 5.0, "valueScore": 5.0,
            "momentumScore": 0.5, "squeezeScore": None, "ivRank": 50.0}
    base.update(fields)
    return base


def snap(rows): return {"rows": rows}


class PercentileRankTests(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(norm.percentile_ranks([]), [])

    def test_single_value(self) -> None:
        # Single value: itself is 50th percentile (0 below, 1 equal incl self).
        self.assertEqual(norm.percentile_ranks([5.0]), [50.0])

    def test_all_equal(self) -> None:
        result = norm.percentile_ranks([5.0, 5.0, 5.0, 5.0])
        self.assertTrue(all(r == 50.0 for r in result))

    def test_sorted_monotone(self) -> None:
        result = norm.percentile_ranks([1.0, 2.0, 3.0, 4.0, 5.0])
        for i in range(1, len(result)):
            self.assertGreater(result[i], result[i - 1])

    def test_nulls_preserved_and_excluded(self) -> None:
        result = norm.percentile_ranks([1.0, None, 3.0, None, 5.0])
        self.assertIsNone(result[1])
        self.assertIsNone(result[3])
        # Module rounds to 2 dp; compare with assertAlmostEqual.
        self.assertAlmostEqual(result[0], (0 + 0.5) / 3 * 100, places=1)

    def test_scale_invariance(self) -> None:
        a = norm.percentile_ranks([1.0, 2.0, 3.0, 4.0, 5.0])
        b = norm.percentile_ranks([10.0, 20.0, 30.0, 40.0, 50.0])
        c = norm.percentile_ranks([0.01, 0.02, 0.03, 0.04, 0.05])
        self.assertEqual(a, b)
        self.assertEqual(a, c)


class CompositeRankTests(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertIsNone(norm.composite_rank([None, None, None]))

    def test_single_component(self) -> None:
        self.assertEqual(norm.composite_rank([None, None, 80.0]), 80.0)

    def test_geometric_mean(self) -> None:
        # Geometric mean of 80, 20 = sqrt(1600) = 40.
        self.assertEqual(norm.composite_rank([80.0, 20.0, None]), 40.0)

    def test_weakest_caps(self) -> None:
        # Geometric mean punishes a small component.
        result = norm.composite_rank([90.0, 90.0, 1.0])
        self.assertLess(result, 50)  # cap by the 1.0


class BuildNormalizedTests(unittest.TestCase):
    def test_no_rows(self) -> None:
        payload = norm.build_normalized(snapshot_loader=lambda: {})
        self.assertEqual(payload["verdict"], "no-evidence")

    def test_contract_frozen(self) -> None:
        payload = norm.build_normalized(snapshot_loader=lambda: {})
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["diagnosticOnly"])

    def test_stage(self) -> None:
        self.assertTrue(norm.SLATE_NORMALIZER_STAGE.endswith("research-only"))

    def test_top_n_percent_gate(self) -> None:
        # 10 rows, top-20% gate: 2 should pass.
        rows = [make_row(ticker=f"T{i}", readyScore=float(i)) for i in range(10)]
        payload = norm.build_normalized(
            snapshot_loader=lambda: snap(rows),
            gate_percentile=80,
        )
        self.assertGreaterEqual(payload["passingCount"], 1)
        self.assertLessEqual(payload["passingCount"], 3)

    def test_top_5_percent_gate_is_stricter(self) -> None:
        rows = [make_row(ticker=f"T{i}", readyScore=float(i)) for i in range(20)]
        loose = norm.build_normalized(snapshot_loader=lambda: snap(rows), gate_percentile=80)
        strict = norm.build_normalized(snapshot_loader=lambda: snap(rows), gate_percentile=95)
        self.assertGreater(loose["passingCount"], strict["passingCount"])

    def test_scale_invariance_at_build_level(self) -> None:
        # The broken-scale problem: if all scores are tiny (0-10), the ranks
        # still cleanly separate them.
        rows = [make_row(ticker=f"T{i}", readyScore=i * 0.1) for i in range(10)]
        payload = norm.build_normalized(
            snapshot_loader=lambda: snap(rows),
            gate_percentile=80,
        )
        # The top of the list should be T9 (highest readyScore=0.9).
        self.assertEqual(payload["rows"][0]["ticker"], "T9")


class TextRenderTests(unittest.TestCase):
    def test_text_has_sections(self) -> None:
        rows = [make_row(ticker=f"T{i}", readyScore=float(i)) for i in range(5)]
        payload = norm.build_normalized(snapshot_loader=lambda: snap(rows))
        text = norm.normalized_text(payload)
        self.assertIn("Slate Normalizer", text)
        self.assertIn("Top 20 by composite rank:", text)
        self.assertIn("Thresholds:", text)


if __name__ == "__main__":
    unittest.main()
