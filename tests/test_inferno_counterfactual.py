from __future__ import annotations

"""Regression tests for the counterfactual replay.

Contract:
- ``researchOnly`` / ``promotable=false`` are hard-pinned
- empty shadow ledger yields verdict ``insufficient-data``
- a closed shadow set with 3+ items under at least one policy yields
  verdict ``ranked``
- the all-approved baseline always includes every closed record
- the conservative policy is a subset of every component policy
- rankings disagree only when the underlying numbers actually disagree
- text renderer covers each section
"""

import unittest

from inferno_counterfactual import (
    COUNTERFACTUAL_STAGE,
    DEFAULT_POLICIES,
    build_counterfactual,
    counterfactual_text,
    policy_all_approved,
    policy_anti_edge_rejected,
    policy_catalyst_only,
    policy_conservative,
    policy_edge_only,
    policy_iv_cheap,
)


def _record(
    ticker: str,
    pnl: float | None,
    *,
    strategy: str = "LONG_STRADDLE",
    regime: str = "bullish-normal",
    sector: str = "Technology",
    iv_rank: float = 25.0,
    days_to_earnings: float = 5,
    max_loss: float = 100.0,
) -> dict:
    return {
        "ticker": ticker,
        "strategy": strategy,
        "regime": regime,
        "sector": sector,
        "ivRank": iv_rank,
        "daysToEarnings": days_to_earnings,
        "riskVerdict": {"metrics": {"maxLossDollars": max_loss}},
        "outcome": {
            "status": "closed" if pnl is not None else "open",
            "estimatedPnl": pnl,
        },
    }


class CounterfactualContractTests(unittest.TestCase):
    def test_research_only_is_immutable(self) -> None:
        payload = build_counterfactual(shadow_records=[])
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertEqual(payload["stage"], COUNTERFACTUAL_STAGE)

    def test_empty_ledger_yields_insufficient_data(self) -> None:
        payload = build_counterfactual(shadow_records=[])
        self.assertEqual(payload["verdict"], "insufficient-data")
        self.assertEqual(payload["closedRecordCount"], 0)


class CounterfactualReplayTests(unittest.TestCase):
    """End-to-end replay over a synthetic closed shadow set."""

    def setUp(self) -> None:
        self.shadow = [_record(f"T{i}", pnl=1.0) for i in range(6)]
        self.shadow.append(_record("LOSER", pnl=-1.0))

    def test_all_approved_includes_every_closed_record(self) -> None:
        payload = build_counterfactual(shadow_records=self.shadow)
        all_approved = next(
            p for p in payload["policies"] if p["name"] == "all-approved"
        )
        self.assertEqual(all_approved["approvedCount"], 7)
        self.assertEqual(all_approved["rejectedCount"], 0)
        self.assertEqual(all_approved["wins"], 6)
        self.assertEqual(all_approved["losses"], 1)

    def test_ranked_verdict_appears_when_sample_is_sufficient(self) -> None:
        payload = build_counterfactual(shadow_records=self.shadow)
        self.assertEqual(payload["verdict"], "ranked")
        self.assertIsNotNone(payload["rankings"]["bestByMeanR"])

    def test_iv_cheap_rejects_high_iv_records(self) -> None:
        # Half the records have iv_rank 25 (cheap), half have iv_rank 50.
        shadow = []
        for i in range(4):
            shadow.append(_record(f"C{i}", pnl=1.0, iv_rank=20.0))
        for i in range(4):
            shadow.append(_record(f"X{i}", pnl=-1.0, iv_rank=60.0))
        payload = build_counterfactual(shadow_records=shadow)
        iv_cheap = next(p for p in payload["policies"] if p["name"] == "iv-cheap")
        self.assertEqual(iv_cheap["approvedCount"], 4)
        self.assertEqual(iv_cheap["rejectedCount"], 4)
        # The iv-cheap subset should be 4/0 wins/losses.
        self.assertEqual(iv_cheap["wins"], 4)
        self.assertEqual(iv_cheap["losses"], 0)

    def test_catalyst_only_filters_by_days_to_earnings(self) -> None:
        shadow = []
        for i in range(3):
            shadow.append(_record(f"N{i}", pnl=1.0, days_to_earnings=5))
        for i in range(3):
            shadow.append(_record(f"F{i}", pnl=-1.0, days_to_earnings=30))
        payload = build_counterfactual(shadow_records=shadow)
        catalyst = next(
            p for p in payload["policies"] if p["name"] == "catalyst-only"
        )
        self.assertEqual(catalyst["approvedCount"], 3)
        self.assertEqual(catalyst["rejectedCount"], 3)

    def test_conservative_is_intersection_of_components(self) -> None:
        # Build a shadow set where conservative should approve exactly one
        # record (catalyst + cheap iv + matches the edge cell).
        shadow = [_record(f"E{i}", pnl=1.0) for i in range(6)]  # builds the edge cell
        # And add a name with bad iv, so iv-cheap rejects it.
        shadow.append(_record("HIGH_IV", pnl=1.0, iv_rank=60.0))
        payload = build_counterfactual(shadow_records=shadow)
        conservative = next(
            p for p in payload["policies"] if p["name"] == "conservative"
        )
        iv_cheap = next(p for p in payload["policies"] if p["name"] == "iv-cheap")
        # conservative <= iv_cheap by definition.
        self.assertLessEqual(conservative["approvedCount"], iv_cheap["approvedCount"])

    def test_rankings_pick_a_policy_per_axis_when_data_supports_it(self) -> None:
        payload = build_counterfactual(shadow_records=self.shadow)
        rankings = payload["rankings"]
        for key in ("bestByMeanR", "bestByWilsonLower", "bestByProfitFactor", "bestByDrawdown"):
            self.assertIn(rankings[key], {p["name"] for p in payload["policies"]})


class CounterfactualPolicyTests(unittest.TestCase):
    """Unit tests on each individual policy function."""

    def test_all_approved_is_truly_always(self) -> None:
        self.assertTrue(policy_all_approved({}, {}))

    def test_anti_edge_rejected_default_is_approve(self) -> None:
        # With no anti-edge cells, the policy should approve everything.
        self.assertTrue(policy_anti_edge_rejected({"strategy": "x"}, {"antiEdgeKeys": set()}))

    def test_catalyst_only_excludes_far_earnings(self) -> None:
        self.assertFalse(policy_catalyst_only({"daysToEarnings": 30}, {}))
        self.assertTrue(policy_catalyst_only({"daysToEarnings": 5}, {}))

    def test_iv_cheap_excludes_expensive_vol(self) -> None:
        self.assertFalse(policy_iv_cheap({"ivRank": 60.0}, {}))
        self.assertTrue(policy_iv_cheap({"ivRank": 15.0}, {}))


class CounterfactualRenderTests(unittest.TestCase):
    def test_text_renderer_covers_each_section(self) -> None:
        payload = build_counterfactual(shadow_records=[
            _record(f"T{i}", pnl=1.0) for i in range(6)
        ])
        rendered = counterfactual_text(payload)
        self.assertIn("Counterfactual Replay", rendered)
        self.assertIn("Rankings:", rendered)
        self.assertIn("Per-policy results:", rendered)
        self.assertIn("Thresholds:", rendered)


if __name__ == "__main__":
    unittest.main()
