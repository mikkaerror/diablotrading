"""Tests for inferno_trade_conviction_audit.

The single most important property of this module is *not yes-man behaviour*:
even on a maximally clean ticket the auditor must surface a bear point and
state-of-evidence honesty. These tests pin that property in place so a future
refactor cannot silently make the auditor agreeable.
"""

from __future__ import annotations

import unittest

import inferno_trade_conviction_audit as audit


def _ticket(**overrides):
    base = {
        "ticker": "TEST",
        "structure": "Vertical Call",
        "allocation": 53.64,
        "readiness": 99,
        "confidence": 2,
        "dte": 8,
    }
    base.update(overrides)
    return base


def _brief(**overrides):
    base = {
        "ticker": "TEST",
        "tracker": {
            "readiness": 99,
            "confidence": 2,
            "daysUntilEarnings": 8,
            "atrPercent": 3.0,
            "ivRank": 50.0,
            "rec1": "VERTICAL CALL (10)",
            "trend": "Bullish",
            "rvol": 0.8,
            "distanceToSupportPct": 12.0,
            "distanceToResistancePct": 10.0,
        },
        "edge": {
            "category": "AI/Compute Picks",
            "lane": "Catalyst Trade Candidate",
            "edgeScore": 80.0,
            "sector": "Technology",
        },
        "exposure": {
            "alreadyInSlate": False,
            "largestSector": "Industrials",
            "largestSectorShare": 0.2,
            "setupShares": {"Vertical Call": 0.2},
            "marketRegime": "bullish-elevated",
        },
    }
    # shallow override
    for key, value in overrides.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            base[key].update(value)
        else:
            base[key] = value
    return base


class TradeConvictionAuditTests(unittest.TestCase):

    # ─────────── core invariants ───────────

    def test_clean_ticket_still_gets_a_bear(self):
        """Even when no rule fires, the auditor must produce at least one bear
        bullet (state-of-evidence). This is the no-yes-man invariant."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket()]},
            decision_briefs={"briefs": [_brief()]},
            evidence={"verdict": "no-evidence", "totalSamples": 0},
            devils={"verdict": "no-evidence", "strategyCount": 0},
            vol_premium={"verdict": "no-evidence"},
            regime={"verdict": "no-evidence"},
        )
        self.assertEqual(report["auditCount"], 1)
        bear = report["audits"][0]["bear"]
        self.assertTrue(bear, "auditor must produce at least one bear bullet")
        joined = " | ".join(bear)
        self.assertIn("prior-only", joined.lower())

    def test_unclassified_edge_is_a_disagreement_even_at_readiness_99(self):
        """Readiness 99 + edge=Unclassified is the classic 'gate-pass but no
        thesis' case — must show up as a disagreement, not a bull bullet."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket(ticker="MOD")]},
            decision_briefs={"briefs": [_brief(
                ticker="MOD",
                edge={"category": "Unclassified", "lane": "Ignore For Theme", "sector": "Consumer Cyclical"},
            )]},
            evidence={"verdict": "no-evidence", "totalSamples": 0},
            devils={"verdict": "no-evidence", "strategyCount": 0},
        )
        a = report["audits"][0]
        joined_disagreements = " | ".join(a["disagreements"])
        self.assertIn("thesis is missing", joined_disagreements)

    def test_sector_concentration_fires_disagreement(self):
        """If proposed ticker shares the dominant sector, surface it."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket(ticker="AVGO")]},
            decision_briefs={"briefs": [_brief(
                ticker="AVGO",
                edge={"sector": "Technology"},
                exposure={"largestSector": "Technology", "largestSectorShare": 0.6,
                          "setupShares": {"Vertical Call": 0.6}},
            )]},
            evidence={"totalSamples": 0},
            devils={"strategyCount": 0},
        )
        a = report["audits"][0]
        bear_joined = " | ".join(a["bear"])
        self.assertIn("60% in Technology", bear_joined)
        # And in disagreements:
        dis_joined = " | ".join(a["disagreements"])
        self.assertIn("Technology", dis_joined)

    def test_long_straddle_always_carries_vrp_bear(self):
        """Long vol must always cite the variance risk premium drag."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket(structure="Straddle")]},
            decision_briefs={"briefs": [_brief(tracker={"rec1": "STRADDLE (12)", "ivRank": 50.0})]},
            evidence={"totalSamples": 0},
            devils={"strategyCount": 0},
        )
        bear = " | ".join(report["audits"][0]["bear"])
        self.assertIn("VRP-BK03", bear)
        self.assertIn("ANDR18", bear)

    def test_falsification_triggers_are_pre_committed(self):
        """Every ticket must carry at least the two universal triggers."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket()]},
            decision_briefs={"briefs": [_brief()]},
            evidence={"totalSamples": 0},
            devils={"strategyCount": 0},
        )
        triggers = report["audits"][0]["falsificationTriggers"]
        joined = " | ".join(triggers)
        self.assertIn("edges-falsified", joined)
        self.assertIn("decaying", joined)

    def test_no_briefing_means_empty_audit_not_crash(self):
        report = audit.build_conviction_audit(
            briefing={"candidates": []},
            decision_briefs={"briefs": []},
            evidence={"totalSamples": 0},
            devils={"strategyCount": 0},
        )
        self.assertEqual(report["auditCount"], 0)
        text = audit.conviction_audit_text(report)
        self.assertIn("No ready-to-execute tickets", text)

    def test_research_only_flags_pinned(self):
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket()]},
            decision_briefs={"briefs": [_brief()]},
            evidence={"totalSamples": 0},
            devils={"strategyCount": 0},
        )
        self.assertTrue(report["diagnosticOnly"])
        self.assertTrue(report["researchOnly"])
        self.assertFalse(report["promotable"])

    def test_conviction_tag_downgrades_when_bear_outweighs_bull(self):
        """A ticket with more bear than bull should not be tagged supportable."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket(structure="Straddle")]},
            decision_briefs={"briefs": [_brief(
                tracker={"rec1": "STRADDLE (10)", "ivRank": 85.0,
                         "distanceToResistancePct": 2.0, "trend": "Bullish"},
                edge={"category": "Unclassified", "lane": "Ignore For Theme",
                      "sector": "Technology"},
                exposure={"largestSector": "Technology", "largestSectorShare": 0.6,
                          "setupShares": {"Straddle": 0.6}},
            )]},
            evidence={"totalSamples": 0},
            devils={"strategyCount": 0},
        )
        tag = report["audits"][0]["convictionTag"]
        self.assertIn(tag, {"mixed", "weak"})

    def test_short_dte_long_premium_carries_theta_acceleration_bear(self):
        """Any long-premium structure inside the 30-DTE window must carry
        the theta-acceleration bear, citing THETA-CURVE."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket(structure="Vertical Call", dte=8)]},
            decision_briefs={"briefs": [_brief()]},
            evidence={"totalSamples": 0},
            devils={"strategyCount": 0},
        )
        bear = " | ".join(report["audits"][0]["bear"])
        self.assertIn("THETA-CURVE", bear)
        self.assertIn("3-5", bear)

    def test_long_straddle_surfaces_calendar_spread_as_disagreement(self):
        """If the chosen structure buys vol, the auditor must name the
        calendar-spread alternative as a disagreement."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket(structure="Straddle")]},
            decision_briefs={"briefs": [_brief(tracker={"rec1": "STRADDLE (10)"})]},
            evidence={"totalSamples": 0},
            devils={"strategyCount": 0},
        )
        disagreements = " | ".join(report["audits"][0]["disagreements"])
        self.assertIn("CAL-SPREAD", disagreements)
        self.assertIn("calendar spread", disagreements)

    def test_cboe_72_fact_appears_in_long_straddle_bear(self):
        """The CBOE 10-yr S&P frequency must be quoted for long premium."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket(structure="Straddle")]},
            decision_briefs={"briefs": [_brief(tracker={"rec1": "STRADDLE (10)"})]},
            evidence={"totalSamples": 0},
            devils={"strategyCount": 0},
        )
        bear = " | ".join(report["audits"][0]["bear"])
        self.assertIn("CBOE-72", bear)
        self.assertIn("28%", bear)

    def test_pead_trigger_present_on_every_audit(self):
        """The PEAD-roll falsification trigger must appear on every
        audit; rolling past planned exit silently changes the bet."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket()]},
            decision_briefs={"briefs": [_brief()]},
            evidence={"totalSamples": 0},
            devils={"strategyCount": 0},
        )
        triggers = " | ".join(report["audits"][0]["falsificationTriggers"])
        self.assertIn("BT89", triggers)
        self.assertIn("PEAD", triggers)

    def test_state_of_evidence_cites_deflated_sharpe(self):
        """López de Prado multi-trial correction must be quoted in
        state-of-evidence — relevant regardless of sample count."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket()]},
            decision_briefs={"briefs": [_brief()]},
            evidence={"totalSamples": 100},  # even with samples, multi-trial matters
            devils={"strategyCount": 0},
        )
        soe = " | ".join(report["audits"][0]["stateOfEvidence"])
        self.assertIn("LdP-DSR", soe)
        self.assertIn("multi-trial", soe)

    def test_state_of_evidence_cites_rotando_thorp(self):
        """Quarter-Kelly cap must reference the Rotando-Thorp 1992 result."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket()]},
            decision_briefs={"briefs": [_brief()]},
            evidence={"totalSamples": 0},
            devils={"strategyCount": 0},
        )
        soe = " | ".join(report["audits"][0]["stateOfEvidence"])
        self.assertIn("RT92", soe)
        self.assertIn("quarter-Kelly", soe)

    def test_blowup_risks_section_present_on_every_audit(self):
        """The BLOW-UP RISKS section must exist on every audit ticket."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket()]},
            decision_briefs={"briefs": [_brief()]},
            evidence={"totalSamples": 0},
            devils={"strategyCount": 0},
        )
        a = report["audits"][0]
        self.assertIn("blowupRisks", a)
        self.assertIsInstance(a["blowupRisks"], list)

    def test_naked_short_structure_fires_hard_block_blowup(self):
        """Undefined-loss structures must surface as a HARD BLOCK in the
        blow-up risks list — Niederhoffer/Cordier rule."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket(structure="NAKED CALL 50")]},
            decision_briefs={"briefs": [_brief(tracker={"rec1": "NAKED CALL 50"})]},
            evidence={"totalSamples": 0},
            devils={"strategyCount": 0},
        )
        risks = " | ".join(report["audits"][0]["blowupRisks"])
        self.assertIn("HARD BLOCK", risks)
        self.assertIn("Niederhoffer", risks)

    def test_concentration_surfaces_ltcm_archegos_pattern(self):
        """Slate concentration matching ticket sector must cite LTCM/Hwang."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket()]},
            decision_briefs={"briefs": [_brief(
                edge={"sector": "Technology"},
                exposure={"largestSector": "Technology", "largestSectorShare": 0.6,
                          "setupShares": {"Vertical Call": 0.6}},
            )]},
            evidence={"totalSamples": 0},
            devils={"strategyCount": 0},
        )
        risks = " | ".join(report["audits"][0]["blowupRisks"])
        self.assertIn("LTCM", risks)
        self.assertIn("Hwang", risks)

    def test_blowup_risks_always_include_dont_roll_loser(self):
        """Karen-the-Supertrader antipattern — close losers, do not roll —
        must surface for every option ticket as a reminder."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket()]},
            decision_briefs={"briefs": [_brief()]},
            evidence={"totalSamples": 0},
            devils={"strategyCount": 0},
        )
        risks = " | ".join(report["audits"][0]["blowupRisks"])
        self.assertIn("Karen Bruton", risks)
        self.assertIn("close", risks.lower())

    def test_rendered_text_contains_required_sections(self):
        """The human-facing report must always include all eight sections."""
        report = audit.build_conviction_audit(
            briefing={"candidates": [_ticket()]},
            decision_briefs={"briefs": [_brief()]},
            evidence={"totalSamples": 0},
            devils={"strategyCount": 0},
        )
        text = audit.conviction_audit_text(report)
        for section in (
            "BULL CASE",
            "BEAR CASE",
            "DISAGREEMENTS",
            "FALSIFICATION TRIGGERS",
            "STATE OF EVIDENCE",
            "BLOW-UP RISKS",
            "REFERENCES",
            "REMINDERS",
        ):
            self.assertIn(section, text, f"missing section: {section}")


if __name__ == "__main__":
    unittest.main()
