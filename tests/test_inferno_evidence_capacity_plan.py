from __future__ import annotations

"""Tests for the research-only evidence-capacity plan."""

import unittest

import inferno_evidence_capacity_plan as ecp


def _universe():
    rows = []
    # 40 names reporting in week 7, 30 of them eligible; 3 names inside the 21-day window, none eligible
    for i in range(40):
        rows.append({"ticker": f"S{i}", "daysUntilEarnings": 50, "confidence": 2 if i < 30 else 1, "setupRec": "Straddle"})
    for i in range(3):
        rows.append({"ticker": f"N{i}", "daysUntilEarnings": 5, "confidence": 1, "setupRec": "Avoid"})
    return rows


class EvidenceCapacityPlanTests(unittest.TestCase):
    def test_season_profile_applies_front_of_funnel_screens(self) -> None:
        profile = ecp.season_profile(_universe())
        self.assertEqual(profile[7]["reporting"], 40)
        self.assertEqual(profile[7]["eligible"], 30)
        self.assertEqual(profile[0]["reporting"], 3)
        self.assertEqual(profile[0]["eligible"], 0)

    def test_binding_cap_is_the_smallest_weekly_throughput(self) -> None:
        cap = ecp.weekly_capacity(hold_days=3.0)
        self.assertEqual(cap["bindingCap"], min(("queueLimit", "activeIntents", "openPaperTickets", "dailyBudget"), key=lambda k: cap[k]))
        self.assertGreater(cap["weeklyCapacity"], 0)

    def test_projection_is_capacity_bound_in_the_burst_and_flow_bound_off_season(self) -> None:
        profile = ecp.season_profile(_universe())
        out = ecp.project(profile, 5.0, historical_rate=0.5, scored_so_far=3)
        week7 = out["weeks"][7]
        self.assertEqual(week7["ticketsCapacityBound"], 5.0)        # 30 eligible x 2 per event, capped at 5
        self.assertEqual(week7["ticketsHistoricalRate"], 0.5)
        self.assertEqual(out["weeks"][0]["ticketsCapacityBound"], 0)  # nothing eligible
        self.assertIsNone(out["clearWeekAtCapacity"])                # only one burst week in this fixture
        self.assertEqual(out["cumulativeAtHorizonCapacity"], 8.0)

    def test_build_plan_is_research_only_and_reads_velocity_shape(self) -> None:
        payload = ecp.build_plan(snapshot={"rows": _universe()}, velocity={"velocity": {"totalClosed": 3, "weeklyRate30dWindow": 0.47}})
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["authorityChanged"])
        self.assertEqual(payload["counts"]["scoredSoFar"], 3)
        self.assertEqual(payload["historicalWeeklyFillRate"], 0.47)
        self.assertEqual(payload["verdict"], "calendar-starved-now")
        self.assertIn("Binding cap", ecp.plan_text(payload))
