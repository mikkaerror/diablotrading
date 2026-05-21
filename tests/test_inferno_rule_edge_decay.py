"""Contract tests for inferno_rule_edge_decay.

Pinned invariants:
  - Module is research-only and promotable=False.
  - Wilson lower bound math is correct on hand-computed cases.
  - Half-life estimator returns None on degenerate inputs and a positive
    finite number on a synthetic decaying sequence.
  - _bullet_predicted_outcome scores bear-side bullets correct on
    losers and bull-side bullets correct on winners.
  - Hit-rate verdict is "insufficient" until MIN_SAMPLES_FOR_VERDICT is
    reached, then flips to retire-candidate / healthy by Wilson lower.
  - Empty-data case produces 'awaiting-closed-outcomes' without crashing.
  - Citations include GRINOLD-1989 and ADAMS-MACKAY-2007.
"""

from __future__ import annotations

import math
import unittest

from inferno_rule_edge_decay import (
    DECAY_STAGE,
    MIN_SAMPLES_FOR_VERDICT,
    WILSON_LOWER_RETIRE_FLOOR,
    WILSON_Z,
    _bullet_predicted_outcome,
    build_rule_edge_decay,
    compute_rule_decay,
    exponential_half_life,
    rule_edge_decay_text,
    wilson_lower,
)


class WilsonLowerTests(unittest.TestCase):
    def test_zero_n_returns_zero(self):
        self.assertEqual(wilson_lower(0, 0), 0.0)

    def test_all_wins_below_one(self):
        """Wilson lower is strictly less than 1.0 even at perfect record."""
        self.assertTrue(0 < wilson_lower(10, 10) < 1.0)

    def test_all_losses_returns_zero_or_near_zero(self):
        self.assertEqual(wilson_lower(0, 10), 0.0)

    def test_monotonic_in_wins(self):
        """More wins at constant n → higher Wilson lower."""
        self.assertLess(wilson_lower(5, 10), wilson_lower(7, 10))

    def test_monotonic_in_n_for_fixed_rate(self):
        """For the same hit rate, more samples → higher Wilson lower."""
        self.assertLess(wilson_lower(5, 10), wilson_lower(50, 100))

    def test_matches_known_value(self):
        """50/100 → roughly 0.40-0.41 (textbook Wilson 95% lower)."""
        wl = wilson_lower(50, 100, z=WILSON_Z)
        self.assertAlmostEqual(wl, 0.404, delta=0.01)


class HalfLifeTests(unittest.TestCase):
    def test_short_series_returns_none(self):
        self.assertIsNone(exponential_half_life([0.5, 0.3]))

    def test_all_zero_returns_none(self):
        self.assertIsNone(exponential_half_life([0.0, 0.0, 0.0]))

    def test_constant_returns_none(self):
        """No slope → no decay → None."""
        self.assertIsNone(exponential_half_life([0.5, 0.5, 0.5, 0.5]))

    def test_decaying_returns_positive_half_life(self):
        # Synthetic: h(t) = 0.8 * exp(-0.1 * t) ≈ half-life of ln(2)/0.1 ≈ 6.93
        rates = [0.8 * math.exp(-0.1 * t) for t in range(10)]
        hl = exponential_half_life(rates)
        self.assertIsNotNone(hl)
        assert hl is not None  # for type-checker
        self.assertAlmostEqual(hl, math.log(2) / 0.1, delta=0.5)

    def test_growing_returns_none(self):
        """The estimator refuses to call growth a half-life."""
        rates = [0.2 * math.exp(0.1 * t) for t in range(10)]
        self.assertIsNone(exponential_half_life(rates))


class BulletScoringTests(unittest.TestCase):
    def test_bear_bullet_correct_on_loser(self):
        self.assertTrue(_bullet_predicted_outcome("bear", -100.0))

    def test_bear_bullet_wrong_on_winner(self):
        self.assertFalse(_bullet_predicted_outcome("bear", 100.0))

    def test_bull_bullet_correct_on_winner(self):
        self.assertTrue(_bullet_predicted_outcome("bull", 100.0))

    def test_bull_bullet_wrong_on_loser(self):
        self.assertFalse(_bullet_predicted_outcome("bull", -100.0))

    def test_disagreement_counts_as_bear_side(self):
        self.assertTrue(_bullet_predicted_outcome("disagreements", -50.0))
        self.assertFalse(_bullet_predicted_outcome("disagreements", 50.0))

    def test_falsification_trigger_counts_as_bear_side(self):
        self.assertTrue(_bullet_predicted_outcome("falsificationTriggers", -50.0))

    def test_blowup_risk_counts_as_bear_side(self):
        self.assertTrue(_bullet_predicted_outcome("blowUpRisks", -200.0))


class ComputeRuleDecayTests(unittest.TestCase):
    """Synthetic ticket + audit data to exercise the rule decay engine."""

    def test_no_data_returns_empty(self):
        rows = compute_rule_decay(closed_tickets=[], audit_history={})
        self.assertEqual(rows, [])

    def test_insufficient_samples_yields_insufficient_verdict(self):
        # Below MIN_SAMPLES_FOR_VERDICT → 'insufficient' regardless of wl.
        n = MIN_SAMPLES_FOR_VERDICT - 1
        tickets = [
            {"ticketId": f"T{i}", "ticker": "AAA", "realizedPnl": -10.0}
            for i in range(n)
        ]
        audit = {
            f"T{i}": [{"section": "bear", "tag": "PTJ-RR", "note": ""}]
            for i in range(n)
        }
        rows = compute_rule_decay(tickets, audit)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["verdict"], "insufficient")
        self.assertEqual(row["n"], n)
        self.assertEqual(row["hits"], n)

    def test_healthy_when_wilson_above_floor(self):
        # 20 hits / 20 → Wilson lower is well above 0.50
        n = 20
        tickets = [
            {"ticketId": f"T{i}", "ticker": "AAA", "realizedPnl": -10.0}
            for i in range(n)
        ]
        audit = {
            f"T{i}": [{"section": "bear", "tag": "PTJ-RR", "note": ""}]
            for i in range(n)
        }
        rows = compute_rule_decay(tickets, audit)
        self.assertEqual(rows[0]["verdict"], "healthy")
        self.assertGreater(rows[0]["wilsonLower"], WILSON_LOWER_RETIRE_FLOOR)

    def test_retire_candidate_when_wilson_below_floor(self):
        # 5 hits out of 20 → Wilson lower is well below 0.50
        n = 20
        wins = 5
        tickets = [
            {
                "ticketId": f"T{i}",
                "ticker": "AAA",
                "realizedPnl": -10.0 if i < wins else 10.0,
            }
            for i in range(n)
        ]
        audit = {
            f"T{i}": [{"section": "bear", "tag": "PTJ-RR", "note": ""}]
            for i in range(n)
        }
        rows = compute_rule_decay(tickets, audit)
        self.assertEqual(rows[0]["verdict"], "retire-candidate")
        self.assertLess(rows[0]["wilsonLower"], WILSON_LOWER_RETIRE_FLOOR)

    def test_sorting_worst_first(self):
        """Two tags with different Wilson lowers — worst comes first."""
        # Healthy tag
        tickets_a = [
            {"ticketId": f"A{i}", "ticker": "AAA", "realizedPnl": -10.0}
            for i in range(20)
        ]
        audit_a = {f"A{i}": [{"section": "bear", "tag": "GOOD", "note": ""}] for i in range(20)}
        # Failing tag
        tickets_b = [
            {
                "ticketId": f"B{i}",
                "ticker": "BBB",
                "realizedPnl": -10.0 if i < 5 else 10.0,
            }
            for i in range(20)
        ]
        audit_b = {f"B{i}": [{"section": "bear", "tag": "BAD", "note": ""}] for i in range(20)}
        all_tickets = tickets_a + tickets_b
        all_audit = {**audit_a, **audit_b}
        rows = compute_rule_decay(all_tickets, all_audit)
        # BAD is sorted before GOOD because BAD's Wilson lower is lower.
        self.assertEqual(rows[0]["tag"], "BAD")
        self.assertEqual(rows[1]["tag"], "GOOD")


class BuildAndRenderTests(unittest.TestCase):
    def test_module_is_research_only(self):
        self.assertEqual(DECAY_STAGE, "rule-edge-decay-research-only")

    def test_build_against_live_data_returns_valid_payload(self):
        payload = build_rule_edge_decay()
        self.assertFalse(payload["promotable"])
        self.assertEqual(payload["stage"], DECAY_STAGE)
        self.assertIn(
            payload["verdict"],
            {"awaiting-closed-outcomes", "retire-candidates-present", "healthy"},
        )
        # citations include the decay literature
        self.assertIn("GRINOLD-1989", payload["citations"])
        self.assertIn("ADAMS-MACKAY-2007", payload["citations"])
        # thresholds are exposed
        self.assertEqual(
            payload["thresholds"]["wilsonLowerRetireFloor"],
            WILSON_LOWER_RETIRE_FLOOR,
        )

    def test_text_render_includes_key_sections(self):
        payload = build_rule_edge_decay()
        text = rule_edge_decay_text(payload)
        self.assertIn("Inferno Rule Edge Decay", text)
        self.assertIn("Verdict:", text)
        self.assertIn("Reminders:", text)


if __name__ == "__main__":
    unittest.main()
