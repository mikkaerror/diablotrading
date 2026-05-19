"""Tests for inferno_blowup_guardrails.

The single most important property of this module: the four hard
guardrails must fire when they should and never silently pass. These
tests pin each guardrail against a realistic violation shape from the
case-study doc.
"""

from __future__ import annotations

import unittest

import inferno_blowup_guardrails as guards


def _ticket(**overrides):
    base = {
        "ticker": "TEST",
        "structure": "Vertical Call",
        "allocation": 53.64,
    }
    base.update(overrides)
    return base


def _brief(ticker="TEST", sector="Industrials"):
    return {
        "ticker": ticker,
        "edge": {"sector": sector},
    }


def _briefing(*tickets):
    return {"sizing": {"tickets": list(tickets), "cash": 1000.0}}


def _briefs(*briefs):
    return {"briefs": list(briefs)}


class BlowupGuardrailsTests(unittest.TestCase):

    # ─────────── G1: defined max loss ───────────

    def test_g1_blocks_naked_short_call(self):
        report = guards.build_guardrails(
            briefing=_briefing(_ticket(structure="NAKED CALL 50")),
            decision_briefs=_briefs(_brief()),
        )
        ticket = report["tickets"][0]
        g1 = next(c for c in ticket["checks"] if c["rule"] == "defined-max-loss")
        self.assertFalse(g1["passed"])
        self.assertIn("undefined", g1["detail"])
        self.assertEqual(report["verdict"], "blocked")

    def test_g1_blocks_short_straddle(self):
        report = guards.build_guardrails(
            briefing=_briefing(_ticket(structure="SHORT STRADDLE 50")),
            decision_briefs=_briefs(_brief()),
        )
        g1 = next(c for c in report["tickets"][0]["checks"] if c["rule"] == "defined-max-loss")
        self.assertFalse(g1["passed"])

    def test_g1_passes_vertical_call(self):
        report = guards.build_guardrails(
            briefing=_briefing(_ticket(structure="Vertical Call")),
            decision_briefs=_briefs(_brief()),
        )
        g1 = next(c for c in report["tickets"][0]["checks"] if c["rule"] == "defined-max-loss")
        self.assertTrue(g1["passed"])

    # ─────────── G2: per-ticket quarter-Kelly ───────────

    def test_g2_fires_when_allocation_exceeds_kelly(self):
        report = guards.build_guardrails(
            briefing=_briefing(_ticket(allocation=600.0)),
            decision_briefs=_briefs(_brief()),
            bankroll=1000.0,
        )
        g2 = next(c for c in report["tickets"][0]["checks"] if c["rule"] == "per-ticket-quarter-kelly")
        self.assertFalse(g2["passed"])

    def test_g2_passes_when_within_kelly(self):
        report = guards.build_guardrails(
            briefing=_briefing(_ticket(allocation=200.0)),
            decision_briefs=_briefs(_brief()),
            bankroll=1000.0,
        )
        g2 = next(c for c in report["tickets"][0]["checks"] if c["rule"] == "per-ticket-quarter-kelly")
        self.assertTrue(g2["passed"])

    # ─────────── G3: daily-total cap ───────────

    def test_g3_fires_when_daily_total_exceeds_cap(self):
        tickets = [_ticket(ticker=f"T{i}", allocation=300.0) for i in range(6)]
        briefs = [_brief(ticker=f"T{i}") for i in range(6)]
        report = guards.build_guardrails(
            briefing=_briefing(*tickets),
            decision_briefs=_briefs(*briefs),
            bankroll=10000.0,
        )
        g3 = next(c for c in report["globalChecks"] if c["rule"] == "daily-total-cap")
        self.assertFalse(g3["passed"])

    # ─────────── G4: concentration ───────────

    def test_g4_fires_on_sector_concentration(self):
        tickets = [_ticket(ticker=f"T{i}") for i in range(5)]
        briefs = [_brief(ticker=f"T{i}", sector="Technology") for i in range(5)]
        report = guards.build_guardrails(
            briefing=_briefing(*tickets),
            decision_briefs=_briefs(*briefs),
        )
        g4 = next(c for c in report["globalChecks"] if c["rule"] == "concentration-caps")
        self.assertFalse(g4["passed"])
        self.assertIn("Technology", g4["detail"])

    def test_g4_fires_on_duplicate_underlying(self):
        report = guards.build_guardrails(
            briefing=_briefing(
                _ticket(ticker="MOD", structure="Vertical Call"),
                _ticket(ticker="MOD", structure="Straddle"),
            ),
            decision_briefs=_briefs(_brief(ticker="MOD")),
        )
        g4 = next(c for c in report["globalChecks"] if c["rule"] == "concentration-caps")
        self.assertFalse(g4["passed"])
        self.assertIn("duplicate", g4["detail"])

    def test_g4_passes_diverse_small_slate(self):
        report = guards.build_guardrails(
            briefing=_briefing(
                _ticket(ticker="MOD", structure="Vertical Call"),
                _ticket(ticker="DY", structure="Straddle"),
            ),
            decision_briefs=_briefs(
                _brief(ticker="MOD", sector="Consumer Cyclical"),
                _brief(ticker="DY", sector="Industrials"),
            ),
        )
        g4 = next(c for c in report["globalChecks"] if c["rule"] == "concentration-caps")
        self.assertTrue(g4["passed"])

    # ─────────── G5/G6: advisory rules ───────────

    def test_g5_fires_when_today_drawdown_exceeds_threshold(self):
        report = guards.build_guardrails(
            briefing=_briefing(_ticket()),
            decision_briefs=_briefs(_brief()),
            bankroll=1000.0,
            closed_today_pnl=-100.0,  # -10% > -5% threshold
        )
        g5 = next(c for c in report["globalChecks"] if c["rule"] == "daily-drawdown-halt")
        self.assertFalse(g5["passed"])
        self.assertTrue(g5["advisory"])  # advisory until realised feed is wired

    def test_g6_fires_at_consecutive_loss_threshold(self):
        report = guards.build_guardrails(
            briefing=_briefing(_ticket()),
            decision_briefs=_briefs(_brief()),
            loss_streak=4,
        )
        g6 = next(c for c in report["globalChecks"] if c["rule"] == "loss-streak-tightening")
        self.assertFalse(g6["passed"])
        self.assertTrue(g6["advisory"])

    # ─────────── verdict + contract ───────────

    def test_clear_verdict_on_clean_small_slate(self):
        report = guards.build_guardrails(
            briefing=_briefing(_ticket(allocation=100.0)),
            decision_briefs=_briefs(_brief()),
            bankroll=1000.0,
        )
        self.assertEqual(report["verdict"], "clear")

    def test_advisory_warn_when_only_advisory_fails(self):
        report = guards.build_guardrails(
            briefing=_briefing(_ticket(allocation=100.0)),
            decision_briefs=_briefs(_brief()),
            bankroll=1000.0,
            loss_streak=5,  # advisory rule fires
        )
        self.assertEqual(report["verdict"], "advisory-warn")

    def test_blocked_verdict_on_hard_failure(self):
        report = guards.build_guardrails(
            briefing=_briefing(_ticket(structure="NAKED CALL 100")),
            decision_briefs=_briefs(_brief()),
        )
        self.assertEqual(report["verdict"], "blocked")

    def test_research_only_flags_pinned(self):
        report = guards.build_guardrails(
            briefing=_briefing(_ticket()),
            decision_briefs=_briefs(_brief()),
        )
        self.assertTrue(report["diagnosticOnly"])
        self.assertTrue(report["researchOnly"])
        self.assertFalse(report["promotable"])

    def test_text_render_contains_all_sections(self):
        report = guards.build_guardrails(
            briefing=_briefing(_ticket()),
            decision_briefs=_briefs(_brief()),
        )
        text = guards.guardrails_text(report)
        for section in (
            "GLOBAL CHECKS",
            "PER-TICKET CHECKS",
            "CONSTANTS",
            "REMINDERS",
        ):
            self.assertIn(section, text)

    def test_each_check_carries_a_case_study(self):
        """Every guardrail bullet must name the historical case it prevents."""
        report = guards.build_guardrails(
            briefing=_briefing(_ticket()),
            decision_briefs=_briefs(_brief()),
        )
        for check in report["globalChecks"]:
            self.assertIn("case", check, "global check missing 'case' field")
            self.assertTrue(check["case"], "global check 'case' field is empty")
        for ticket in report["tickets"]:
            for check in ticket["checks"]:
                self.assertIn("case", check, "per-ticket check missing 'case' field")
                self.assertTrue(check["case"], "per-ticket check 'case' field is empty")


if __name__ == "__main__":
    unittest.main()
