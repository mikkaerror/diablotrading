"""Contract tests for the Phase A/B/C signal wiring in
inferno_trade_conviction_audit.

Pinned invariants:
  - Missing or empty Phase artifacts add ZERO bullets (additive only).
  - Outcome attribution: a comfortable-win in the same family adds a bear
    bullet with the ECKHARDT-MW93 + BHB-1986 citations.
  - Rule edge decay: retire-candidate(s) present add a bear bullet with
    the MCLEAN-PONTIFF-2016 + ADAMS-MACKAY-2007 citations.
  - Slippage: anchored family with median slip ≥ 10% adds a bear bullet
    with ROLL-1984 + HASBROUCK-1991 citations.
  - Portfolio correlation: family share ≥ 40% adds a bear bullet with
    MARKOWITZ-1952 + DALIO-HOLY-GRAIL + GRINOLD-1989 citations.
  - Drawdown protocol: non-normal sizing regime adds a *disagreement*
    bullet (sizing, not thesis) with YOUNG-1991 + MARTIN-1989 citations.
  - Consensus monitor: crowded-watch / consensus-extreme adds a bear
    bullet with STEIN-2009 + LOU-POLK-2013 + KHANDANI-LO-2007 citations.
  - Top-level payload carries the six Phase verdicts.
  - Family + direction classifiers handle the live ledger's snake_case
    structure strings.

These tests do not mutate any artifact. They construct minimal payloads
and pass them as kwargs through build_conviction_audit.
"""

from __future__ import annotations

import unittest

import inferno_trade_conviction_audit as audit


def _ticket(structure="Vertical Call", **overrides):
    base = {
        "ticker": "TEST",
        "structure": structure,
        "allocation": 100.0,
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
            "ivRank": 50.0,
            "atrPercent": 3.0,
            "trend": "Bullish",
            "rec1": "VERTICAL CALL (10)",
            "rvol": 1.0,
            "distanceToSupportPct": 10.0,
            "distanceToResistancePct": 10.0,
        },
        "edge": {
            "category": "AI/Compute Picks",
            "lane": "Catalyst Trade Candidate",
            "edgeScore": 75.0,
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
    for key, value in overrides.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            base[key].update(value)
        else:
            base[key] = value
    return base


def _build(**phase_overrides):
    """Call build_conviction_audit with a single clean ticket + Phase kwargs."""
    return audit.build_conviction_audit(
        briefing={"candidates": [_ticket()]},
        decision_briefs={"briefs": [_brief()]},
        evidence={"verdict": "no-evidence", "totalSamples": 0},
        devils={"verdict": "no-evidence", "strategyCount": 0},
        vol_premium={"verdict": "no-evidence"},
        regime={"verdict": "no-evidence"},
        outcome_attribution=phase_overrides.get("outcome_attribution"),
        rule_edge_decay=phase_overrides.get("rule_edge_decay"),
        slippage=phase_overrides.get("slippage"),
        correlation=phase_overrides.get("correlation"),
        drawdown=phase_overrides.get("drawdown"),
        consensus=phase_overrides.get("consensus"),
    )


def _bear(report):
    return " | ".join(report["audits"][0]["bear"])


def _dis(report):
    return " | ".join(report["audits"][0]["disagreements"])


class FamilyClassifierTests(unittest.TestCase):
    def test_snake_case_call_debit_spread(self):
        self.assertEqual(audit._ticket_family("call_debit_spread"), "Vertical Debit")

    def test_display_vertical_call(self):
        self.assertEqual(audit._ticket_family("Vertical Call"), "Vertical Debit")

    def test_long_straddle(self):
        self.assertEqual(audit._ticket_family("long_straddle"), "Long Straddle")

    def test_iron_condor(self):
        self.assertEqual(audit._ticket_family("iron_condor"), "Iron Condor")

    def test_empty_is_unknown(self):
        self.assertEqual(audit._ticket_family(""), "Unknown")


class DirectionClassifierTests(unittest.TestCase):
    def test_straddle_is_long_vol(self):
        self.assertEqual(audit._ticket_direction("long_straddle"), "long-vol")

    def test_credit_is_short_vol(self):
        self.assertEqual(audit._ticket_direction("credit_spread"), "short-vol")

    def test_vertical_call_is_long_equity(self):
        self.assertEqual(audit._ticket_direction("Vertical Call"), "long-equity")


class EmptyArtifactsAddNoBulletsTests(unittest.TestCase):
    """The core safety invariant: when all Phase artifacts are present
    but EMPTY (verdict missing, no payload), the audit must not emit
    any Phase bullets. This pins additive-only behavior.

    Note: passing None for a Phase kwarg means "load from disk", which is
    the production path — that's tested implicitly by the live build, not
    here.
    """

    def test_all_empty_dicts_produce_no_phase_bullets(self):
        report = _build(
            outcome_attribution={},
            rule_edge_decay={},
            slippage={},
            correlation={},
            drawdown={},
            consensus={},
        )
        bear = _bear(report)
        dis = _dis(report)
        for tag in (
            "ECKHARDT-MW93", "MCLEAN-PONTIFF-2016", "ROLL-1984",
            "MARKOWITZ-1952", "STEIN-2009", "YOUNG-1991",
        ):
            self.assertNotIn(tag, bear, f"unexpected {tag} in bear")
            self.assertNotIn(tag, dis, f"unexpected {tag} in disagreements")

    def test_payload_with_keys_but_no_signals_produces_no_phase_bullets(self):
        """Realistic 'awaiting-data' shape: keys exist but lists are empty."""
        report = _build(
            outcome_attribution={"verdict": "awaiting-closed-outcomes", "comfortableWins": []},
            rule_edge_decay={"verdict": "awaiting-closed-outcomes", "retireCandidates": []},
            slippage={"verdict": "no-usable-tickets", "familyAnchors": {}},
            correlation={"verdict": "awaiting-outcomes",
                         "slateConcentration": {"headcount": 0, "byFamily": {}}},
            drawdown={"verdict": "awaiting-closed-outcomes",
                      "sizingAdvisory": {"regime": "normal", "multiplier": 1.0},
                      "metrics": {"currentDrawdown": 0.0}},
            consensus={"verdict": "awaiting-data", "signals": []},
        )
        bear = _bear(report)
        for tag in (
            "ECKHARDT-MW93", "MCLEAN-PONTIFF-2016", "ROLL-1984",
            "MARKOWITZ-1952", "STEIN-2009",
        ):
            self.assertNotIn(tag, bear)


class OutcomeAttributionBulletTests(unittest.TestCase):
    def test_comfortable_win_in_same_family_fires(self):
        attribution = {
            "verdict": "attribution-ready",
            "comfortableWins": [
                {"family": "Vertical Debit", "ticker": "AMD", "pnl": 12.0},
            ],
        }
        report = _build(outcome_attribution=attribution)
        bear = _bear(report)
        self.assertIn("comfortable-win", bear.lower())
        self.assertIn("ECKHARDT-MW93", bear)
        self.assertIn("BHB-1986", bear)

    def test_comfortable_win_in_different_family_does_not_fire(self):
        attribution = {
            "comfortableWins": [
                {"family": "Iron Condor", "ticker": "AMD", "pnl": 12.0},
            ],
        }
        report = _build(outcome_attribution=attribution)
        self.assertNotIn("ECKHARDT-MW93", _bear(report))


class RuleEdgeDecayBulletTests(unittest.TestCase):
    def test_retire_candidate_fires(self):
        decay = {
            "verdict": "retire-candidates-present",
            "retireCandidates": [
                {"tag": "VRP-BK03", "side": "bear", "wilsonLower": 0.35, "n": 22, "hits": 8},
            ],
        }
        report = _build(rule_edge_decay=decay)
        bear = _bear(report)
        self.assertIn("retire candidate", bear.lower())
        self.assertIn("MCLEAN-PONTIFF-2016", bear)


class SlippageBulletTests(unittest.TestCase):
    def test_anchored_family_with_high_slip_fires(self):
        slippage = {
            "verdict": "anchors-ready",
            "familyAnchors": {
                "Vertical Debit": {
                    "verdict": "anchored",
                    "ticketCount": 50,
                    "medianAvgLegSpreadPct": 0.20,
                    "medianEntrySlipPct": 0.35,
                    "maxEntrySlipPct": 2.0,
                    "flaggedCount": 30,
                }
            },
        }
        report = _build(slippage=slippage)
        bear = _bear(report)
        self.assertIn("slippage anchor", bear.lower())
        self.assertIn("ROLL-1984", bear)
        self.assertIn("HASBROUCK-1991", bear)

    def test_low_slip_does_not_fire(self):
        slippage = {
            "verdict": "anchors-ready",
            "familyAnchors": {
                "Vertical Debit": {
                    "verdict": "anchored",
                    "ticketCount": 50,
                    "medianAvgLegSpreadPct": 0.05,
                    "medianEntrySlipPct": 0.02,
                }
            },
        }
        report = _build(slippage=slippage)
        self.assertNotIn("ROLL-1984", _bear(report))

    def test_thin_family_does_not_fire(self):
        """Even if slip is high, a 'thin' family verdict shouldn't fire."""
        slippage = {
            "familyAnchors": {
                "Vertical Debit": {
                    "verdict": "thin",
                    "ticketCount": 5,
                    "medianEntrySlipPct": 0.50,
                }
            },
        }
        report = _build(slippage=slippage)
        self.assertNotIn("ROLL-1984", _bear(report))


class CorrelationBulletTests(unittest.TestCase):
    def test_dominant_family_fires(self):
        corr = {
            "verdict": "concentrated-by-drift",
            "slateConcentration": {
                "headcount": 100,
                "byFamily": {"Vertical Debit": 60, "Long Straddle": 40},
                "effectiveBetCount": 2.1,
            },
        }
        report = _build(correlation=corr)
        bear = _bear(report)
        self.assertIn("MARKOWITZ-1952", bear)
        self.assertIn("DALIO-HOLY-GRAIL", bear)
        self.assertIn("effective bet count", bear.lower())

    def test_diversified_slate_does_not_fire(self):
        corr = {
            "slateConcentration": {
                "headcount": 100,
                "byFamily": {"Vertical Debit": 10, "Long Straddle": 30, "Iron Condor": 25, "Calendar / Diagonal": 35},
                "effectiveBetCount": 3.8,
            },
        }
        report = _build(correlation=corr)
        self.assertNotIn("MARKOWITZ-1952", _bear(report))


class DrawdownDisagreementTests(unittest.TestCase):
    def test_first_cut_regime_produces_disagreement_not_bear(self):
        drawdown = {
            "verdict": "first-cut-advised",
            "sizingAdvisory": {"regime": "first-cut", "multiplier": 0.5},
            "metrics": {"currentDrawdown": -0.07},
        }
        report = _build(drawdown=drawdown)
        dis = _dis(report)
        bear = _bear(report)
        self.assertIn("first-cut", dis)
        self.assertIn("YOUNG-1991", dis)
        # Drawdown bullets are sizing-flavor, must NOT pollute the thesis bears
        self.assertNotIn("YOUNG-1991", bear)

    def test_normal_regime_silent(self):
        drawdown = {
            "verdict": "normal-sizing",
            "sizingAdvisory": {"regime": "normal", "multiplier": 1.0},
            "metrics": {"currentDrawdown": 0.0},
        }
        report = _build(drawdown=drawdown)
        self.assertNotIn("YOUNG-1991", _dis(report))


class ConsensusBulletTests(unittest.TestCase):
    def test_crowded_watch_fires(self):
        consensus = {
            "verdict": "crowded-watch",
            "signals": [
                {"signal": "own-side-concentration", "lean": "long-equity-heavy", "dominantDirection": "long-equity"},
            ],
        }
        report = _build(consensus=consensus)
        bear = _bear(report)
        self.assertIn("STEIN-2009", bear)
        self.assertIn("LOU-POLK-2013", bear)

    def test_consensus_extreme_fires(self):
        consensus = {
            "verdict": "consensus-extreme",
            "signals": [],
        }
        report = _build(consensus=consensus)
        self.assertIn("STEIN-2009", _bear(report))

    def test_normal_verdict_does_not_fire(self):
        consensus = {"verdict": "normal", "signals": []}
        report = _build(consensus=consensus)
        self.assertNotIn("STEIN-2009", _bear(report))


class TopLevelPayloadTests(unittest.TestCase):
    """The Phase verdicts must surface at the top of the payload so the
    operator / command center see them without diving into per-ticket
    bullets."""

    def test_top_level_payload_carries_phase_verdicts(self):
        report = _build(
            outcome_attribution={"verdict": "attribution-ready"},
            rule_edge_decay={"verdict": "healthy"},
            slippage={"verdict": "anchors-ready"},
            correlation={"verdict": "diversified"},
            drawdown={"verdict": "normal-sizing"},
            consensus={"verdict": "uncrowded"},
        )
        self.assertEqual(report["outcomeAttributionVerdict"], "attribution-ready")
        self.assertEqual(report["ruleEdgeDecayVerdict"], "healthy")
        self.assertEqual(report["slippageVerdict"], "anchors-ready")
        self.assertEqual(report["correlationVerdict"], "diversified")
        self.assertEqual(report["drawdownVerdict"], "normal-sizing")
        self.assertEqual(report["consensusVerdict"], "uncrowded")


class StackedSignalsTests(unittest.TestCase):
    """When multiple Phase signals fire on the same ticket, every one
    should appear in its respective list — no cross-contamination."""

    def test_all_six_phase_signals_at_once(self):
        report = _build(
            outcome_attribution={
                "comfortableWins": [{"family": "Vertical Debit", "ticker": "X", "pnl": 5}]
            },
            rule_edge_decay={
                "retireCandidates": [
                    {"tag": "PTJ-MW89", "side": "bear", "wilsonLower": 0.40, "n": 15, "hits": 5}
                ]
            },
            slippage={
                "familyAnchors": {
                    "Vertical Debit": {
                        "verdict": "anchored",
                        "ticketCount": 50,
                        "medianAvgLegSpreadPct": 0.18,
                        "medianEntrySlipPct": 0.42,
                    }
                }
            },
            correlation={
                "slateConcentration": {
                    "headcount": 100,
                    "byFamily": {"Vertical Debit": 70, "Long Straddle": 30},
                    "effectiveBetCount": 1.7,
                }
            },
            drawdown={
                "sizingAdvisory": {"regime": "deep-cut", "multiplier": 0.25},
                "metrics": {"currentDrawdown": -0.12},
            },
            consensus={
                "verdict": "consensus-extreme",
                "signals": [{"signal": "own-side-concentration", "lean": "long-equity-heavy",
                             "dominantDirection": "long-equity"}],
            },
        )
        bear = _bear(report)
        dis = _dis(report)
        # Five Phase signals land in bear:
        for tag in ("ECKHARDT-MW93", "MCLEAN-PONTIFF-2016", "ROLL-1984",
                    "MARKOWITZ-1952", "STEIN-2009"):
            self.assertIn(tag, bear, f"missing {tag} from stacked bear")
        # One Phase signal lands in disagreements (sizing-flavor):
        self.assertIn("YOUNG-1991", dis)


if __name__ == "__main__":
    unittest.main()
