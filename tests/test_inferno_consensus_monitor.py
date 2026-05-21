"""Contract tests for inferno_consensus_monitor.

Pinned invariants:
  - Module is research-only and promotable=False.
  - Side-skew signal aggregates put-rich / call-rich / balanced and
    classifies as put-rich-consensus / call-rich-consensus / neutral.
  - Own-side concentration: dominant direction share >= 0.50 → *-heavy.
  - Family fusion: any pair ρ >= 0.70 → 'fused'; else 'diverse'.
  - Verdict ladder: 0 consensus signals → uncrowded; 1 → normal;
    2 → crowded-watch; 3+ → consensus-extreme; all unknown → awaiting-data.
  - Empty input returns 'awaiting-data'.
  - Citations include STEIN-2009 and LOU-POLK-2013.
"""

from __future__ import annotations

import unittest

from inferno_consensus_monitor import (
    CONSENSUS_STAGE,
    FUSED_FAMILY_RHO,
    OWN_SIDE_CONCENTRATION_FLOOR,
    SIDE_SKEW_DOMINANT_FRACTION,
    _aggregate_verdict,
    _family_fusion_signal,
    _side_skew_signal,
    _slate_concentration_signal,
    build_consensus_monitor,
    consensus_monitor_text,
)


class SideSkewSignalTests(unittest.TestCase):
    def test_no_rows_unknown(self):
        out = _side_skew_signal({})
        self.assertEqual(out["lean"], "unknown")

    def test_put_rich_consensus(self):
        out = _side_skew_signal(
            {"summary": {"sideSkewCounts": {"put-rich": 6, "call-rich": 1, "balanced": 3}}}
        )
        self.assertEqual(out["lean"], "put-rich-consensus")
        self.assertGreaterEqual(out["putShare"], SIDE_SKEW_DOMINANT_FRACTION)

    def test_call_rich_consensus(self):
        out = _side_skew_signal(
            {"summary": {"sideSkewCounts": {"put-rich": 1, "call-rich": 7, "balanced": 2}}}
        )
        self.assertEqual(out["lean"], "call-rich-consensus")

    def test_neutral_when_no_side_dominant(self):
        out = _side_skew_signal(
            {"summary": {"sideSkewCounts": {"put-rich": 3, "call-rich": 3, "balanced": 4}}}
        )
        self.assertEqual(out["lean"], "neutral")


class SlateConcentrationSignalTests(unittest.TestCase):
    def test_no_slate_unknown(self):
        out = _slate_concentration_signal({})
        self.assertEqual(out["lean"], "unknown")

    def test_long_vol_heavy(self):
        out = _slate_concentration_signal(
            {
                "slateConcentration": {
                    "headcount": 10,
                    "byDirection": {"long-vol": 7, "long-equity": 3},
                    "effectiveBetCount": 1.7,
                }
            }
        )
        self.assertEqual(out["lean"], "long-vol-heavy")
        self.assertGreaterEqual(out["dominantShare"], OWN_SIDE_CONCENTRATION_FLOOR)

    def test_balanced_when_no_direction_dominant(self):
        out = _slate_concentration_signal(
            {
                "slateConcentration": {
                    "headcount": 10,
                    "byDirection": {"long-vol": 3, "long-equity": 3, "short-vol": 4},
                }
            }
        )
        self.assertEqual(out["lean"], "balanced")


class FamilyFusionSignalTests(unittest.TestCase):
    def test_no_pairs_unknown(self):
        out = _family_fusion_signal({})
        self.assertEqual(out["lean"], "unknown")

    def test_fused_when_high_rho(self):
        out = _family_fusion_signal(
            {"familyCorrelations": {"pairs": [
                {"familyA": "Long Straddle", "familyB": "Vertical Debit",
                 "correlation": FUSED_FAMILY_RHO + 0.05},
            ]}}
        )
        self.assertEqual(out["lean"], "fused")

    def test_diverse_when_low_rho(self):
        out = _family_fusion_signal(
            {"familyCorrelations": {"pairs": [
                {"familyA": "A", "familyB": "B", "correlation": 0.2},
                {"familyA": "A", "familyB": "C", "correlation": -0.1},
            ]}}
        )
        self.assertEqual(out["lean"], "diverse")

    def test_none_correlation_ignored(self):
        out = _family_fusion_signal(
            {"familyCorrelations": {"pairs": [
                {"familyA": "A", "familyB": "B", "correlation": None},
            ]}}
        )
        self.assertEqual(out["lean"], "diverse")


class AggregateVerdictTests(unittest.TestCase):
    def test_all_unknown_is_awaiting(self):
        signals = [{"lean": "unknown"} for _ in range(3)]
        out = _aggregate_verdict(signals)
        self.assertEqual(out["verdict"], "awaiting-data")

    def test_no_consensus_signals_is_uncrowded(self):
        signals = [{"lean": "neutral"}, {"lean": "balanced"}, {"lean": "diverse"}]
        out = _aggregate_verdict(signals)
        self.assertEqual(out["verdict"], "uncrowded")

    def test_one_consensus_signal_is_normal(self):
        signals = [{"lean": "put-rich-consensus"}, {"lean": "balanced"}, {"lean": "diverse"}]
        out = _aggregate_verdict(signals)
        self.assertEqual(out["verdict"], "normal")

    def test_two_consensus_signals_is_crowded_watch(self):
        signals = [
            {"lean": "put-rich-consensus"},
            {"lean": "long-vol-heavy"},
            {"lean": "diverse"},
        ]
        out = _aggregate_verdict(signals)
        self.assertEqual(out["verdict"], "crowded-watch")

    def test_three_consensus_signals_is_extreme(self):
        signals = [
            {"lean": "put-rich-consensus"},
            {"lean": "long-vol-heavy"},
            {"lean": "fused"},
        ]
        out = _aggregate_verdict(signals)
        self.assertEqual(out["verdict"], "consensus-extreme")


class BuildAndRenderTests(unittest.TestCase):
    def test_module_is_research_only(self):
        self.assertEqual(CONSENSUS_STAGE, "consensus-monitor-research-only")

    def test_build_against_live_data(self):
        payload = build_consensus_monitor()
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["researchOnly"])
        self.assertEqual(payload["stage"], CONSENSUS_STAGE)
        self.assertIn(
            payload["verdict"],
            {"awaiting-data", "uncrowded", "normal", "crowded-watch", "consensus-extreme"},
        )
        self.assertIn("STEIN-2009", payload["citations"])
        self.assertIn("LOU-POLK-2013", payload["citations"])
        # The three v1 signals must always be present
        self.assertEqual(len(payload["signals"]), 3)

    def test_text_render_includes_key_sections(self):
        payload = build_consensus_monitor()
        text = consensus_monitor_text(payload)
        self.assertIn("Inferno Consensus Monitor", text)
        self.assertIn("Verdict:", text)
        self.assertIn("PER-SIGNAL READS", text)
        self.assertIn("Reminders:", text)


if __name__ == "__main__":
    unittest.main()
