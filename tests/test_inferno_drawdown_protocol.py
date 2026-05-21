"""Contract tests for inferno_drawdown_protocol.

Pinned invariants:
  - Module is research-only and promotable=False.
  - Equity curve is chronological; each row carries equity, peak, drawdown.
  - max_drawdown is non-positive and equals the worst drawdown in the curve.
  - Ulcer Index = √(mean of (100·DD)²); zero curve → zero.
  - Sizing ladder maps depth onto regime + multiplier:
      0% → normal/1.0; −7% → first-cut/0.5; −12% → deep-cut/0.25;
      −18% → no-new-positions/0.0; −25% → full-stop/0.0.
  - Empty input returns 'awaiting-closed-outcomes'.
  - Citations include YOUNG-1991 (Calmar) and MARTIN-1989 (Ulcer).
"""

from __future__ import annotations

import unittest

from inferno_drawdown_protocol import (
    DRAWDOWN_STAGE,
    MIN_OUTCOMES_FOR_CALMAR,
    build_drawdown_protocol,
    build_equity_curve,
    calmar_ratio,
    drawdown_protocol_text,
    max_drawdown,
    sizing_for_drawdown,
    time_to_recoveries,
    ulcer_index,
)


def _ticket(date, pnl, ticker="X", ticket_id=None):
    return {
        "tradeDate": date,
        "createdAt": date,
        "ticker": ticker,
        "ticketId": ticket_id or f"T-{ticker}-{date}",
        "realizedPnl": pnl,
        "status": "closed",
    }


class EquityCurveTests(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(build_equity_curve([]), [])

    def test_monotonic_winners_no_drawdown(self):
        curve = build_equity_curve(
            [_ticket("2026-01-01", 10), _ticket("2026-01-02", 20)]
        )
        self.assertEqual(curve[-1]["equity"], 30)
        self.assertEqual(curve[-1]["drawdown"], 0)

    def test_drawdown_after_winner_then_loser(self):
        curve = build_equity_curve(
            [_ticket("2026-01-01", 100), _ticket("2026-01-02", -25)]
        )
        # Peak 100, equity 75 → drawdown -0.25
        self.assertAlmostEqual(curve[-1]["drawdown"], -0.25, places=4)

    def test_undated_tickets_go_to_end(self):
        curve = build_equity_curve(
            [
                {"realizedPnl": 5, "ticker": "B"},  # undated
                _ticket("2026-01-01", 10, ticker="A"),
            ]
        )
        # A first (dated), B second (undated)
        self.assertEqual(curve[0]["ticker"], "A")
        self.assertEqual(curve[1]["ticker"], "B")


class MaxDrawdownTests(unittest.TestCase):
    def test_no_losses_zero_drawdown(self):
        curve = build_equity_curve(
            [_ticket("2026-01-01", 10), _ticket("2026-01-02", 5)]
        )
        self.assertEqual(max_drawdown(curve), 0.0)

    def test_worst_drawdown(self):
        curve = build_equity_curve(
            [
                _ticket("2026-01-01", 100),
                _ticket("2026-01-02", -50),  # dd = -0.5
                _ticket("2026-01-03", 20),  # equity 70, peak 100, dd = -0.3
            ]
        )
        self.assertAlmostEqual(max_drawdown(curve), -0.5, places=4)


class UlcerIndexTests(unittest.TestCase):
    def test_zero_curve_zero_ulcer(self):
        curve = build_equity_curve(
            [_ticket("2026-01-01", 10), _ticket("2026-01-02", 5)]
        )
        self.assertEqual(ulcer_index(curve), 0.0)

    def test_nonzero_when_drawdown_present(self):
        curve = build_equity_curve(
            [_ticket("2026-01-01", 100), _ticket("2026-01-02", -50)]
        )
        self.assertGreater(ulcer_index(curve), 0)


class TimeToRecoveryTests(unittest.TestCase):
    def test_resolved_drawdown_recorded(self):
        curve = build_equity_curve(
            [
                _ticket("2026-01-01", 100),
                _ticket("2026-01-02", -30),  # dd starts
                _ticket("2026-01-03", -10),  # dd continues
                _ticket("2026-01-04", 50),   # equity 110 > peak 100 → resolved
            ]
        )
        recoveries = time_to_recoveries(curve)
        self.assertEqual(len(recoveries), 1)
        self.assertEqual(recoveries[0], 3)

    def test_unresolved_drawdown_not_counted(self):
        curve = build_equity_curve(
            [_ticket("2026-01-01", 100), _ticket("2026-01-02", -50)]
        )
        self.assertEqual(time_to_recoveries(curve), [])


class SizingLadderTests(unittest.TestCase):
    def test_normal_at_zero(self):
        s = sizing_for_drawdown(0.0)
        self.assertEqual(s["regime"], "normal")
        self.assertEqual(s["multiplier"], 1.0)

    def test_positive_drawdown_treated_as_normal(self):
        """A positive equity-above-peak value is impossible mid-curve but
        protect against bad input."""
        s = sizing_for_drawdown(0.01)
        self.assertEqual(s["multiplier"], 1.0)

    def test_first_cut_at_minus_seven(self):
        s = sizing_for_drawdown(-0.07)
        self.assertEqual(s["regime"], "first-cut")
        self.assertEqual(s["multiplier"], 0.50)

    def test_deep_cut_at_minus_twelve(self):
        s = sizing_for_drawdown(-0.12)
        self.assertEqual(s["regime"], "deep-cut")
        self.assertEqual(s["multiplier"], 0.25)

    def test_no_new_positions_at_minus_eighteen(self):
        s = sizing_for_drawdown(-0.18)
        self.assertEqual(s["regime"], "no-new-positions")
        self.assertEqual(s["multiplier"], 0.0)

    def test_full_stop_at_minus_twenty_five(self):
        s = sizing_for_drawdown(-0.25)
        self.assertEqual(s["regime"], "full-stop")
        self.assertEqual(s["multiplier"], 0.0)


class CalmarTests(unittest.TestCase):
    def test_below_threshold_returns_none(self):
        curve = build_equity_curve(
            [_ticket(f"2026-01-{i:02d}", 5) for i in range(1, MIN_OUTCOMES_FOR_CALMAR)]
        )
        self.assertIsNone(calmar_ratio(curve))


class BuildAndRenderTests(unittest.TestCase):
    def test_module_is_research_only(self):
        self.assertEqual(DRAWDOWN_STAGE, "drawdown-protocol-research-only")

    def test_build_against_live_data(self):
        payload = build_drawdown_protocol()
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["researchOnly"])
        self.assertEqual(payload["stage"], DRAWDOWN_STAGE)
        self.assertIn(
            payload["verdict"],
            {
                "awaiting-closed-outcomes",
                "normal-sizing",
                "first-cut-advised",
                "deep-cut-advised",
                "no-new-positions-advised",
                "full-stop-advised",
            },
        )
        self.assertIn("YOUNG-1991", payload["citations"])
        self.assertIn("MARTIN-1989", payload["citations"])

    def test_text_render_includes_key_sections(self):
        payload = build_drawdown_protocol()
        text = drawdown_protocol_text(payload)
        self.assertIn("Inferno Drawdown Protocol", text)
        self.assertIn("Verdict:", text)
        self.assertIn("SIZING ADVISORY", text)


if __name__ == "__main__":
    unittest.main()
