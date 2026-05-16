from __future__ import annotations

"""Regression tests for the strike-selector setup-concentration governor.

The governor's only job is to demote — never promote. These tests freeze that
contract so any future change that accidentally widens the gate or flips the
``ok`` flag will fail loudly.
"""

import unittest
from unittest.mock import patch

import pandas as pd

from inferno_strike_selector import (
    SETUP_CONCENTRATION_DEMOTION_REASON,
    SETUP_CONCENTRATION_LIMIT,
    apply_setup_concentration_governor,
    cap_aware_long_strangle_plan,
    load_execution_queue,
    setup_share_counts,
)


def plan(ticker: str, setup: str, ok: bool = True) -> dict:
    """Build a minimal strike-plan item shaped like build_strike_plan output."""
    return {
        "ticker": ticker,
        "setupRec": setup,
        "ok": ok,
        "riskUnits": 0.9,
        "liveTradingAllowed": False,
    }


class SetupConcentrationGovernorTests(unittest.TestCase):
    """Verify the governor demotes excess concentration without promoting."""

    def test_default_limit_is_sixty_percent(self) -> None:
        """The committed concentration limit must remain 0.6 (60%)."""
        self.assertEqual(SETUP_CONCENTRATION_LIMIT, 0.6)

    def test_share_counts_reflect_only_undemoted_ok_plans(self) -> None:
        plans = [
            plan("CEG", "Straddle"),
            plan("MRVL", "Straddle"),
            plan("DELL", "Straddle"),
            plan("THR", "Vertical Call"),
            plan("FAILED", "Straddle", ok=False),
        ]
        shares = setup_share_counts(plans)
        # FAILED is excluded; 3/4 = 0.75 Straddle, 1/4 = 0.25 Vertical Call
        self.assertAlmostEqual(shares["Straddle"], 0.75, places=4)
        self.assertAlmostEqual(shares["Vertical Call"], 0.25, places=4)

    def test_governor_demotes_excess_straddles_when_above_limit(self) -> None:
        """Five OK plans with four Straddles should demote one Straddle."""
        plans = [
            plan("CEG", "Straddle"),
            plan("MRVL", "Straddle"),
            plan("DELL", "Straddle"),
            plan("VNET", "Straddle"),
            plan("THR", "Vertical Call"),
        ]
        # 4/5 = 80% Straddle; cap at 60% means floor(0.6 * 5) = 3 Straddles
        annotated, summary = apply_setup_concentration_governor(plans)
        demoted = [item for item in annotated if item.get("concentrationDemoted")]
        primary = [item for item in annotated if not item.get("concentrationDemoted")]
        self.assertEqual(len(demoted), 1)
        # The last-in-order Straddle is the one that drops to shadow.
        self.assertEqual(demoted[0]["ticker"], "VNET")
        self.assertEqual(demoted[0]["concentrationDemotionReason"], SETUP_CONCENTRATION_DEMOTION_REASON)
        # The governor must never flip ``ok`` from True to False.
        for item in annotated:
            if item["ticker"] == "VNET":
                self.assertTrue(item["ok"])
        self.assertEqual(len(primary), 4)
        self.assertEqual(len(summary["demoted"]), 1)

    def test_governor_leaves_balanced_slate_alone(self) -> None:
        """Slates that already respect the cap stay fully primary."""
        plans = [
            plan("CEG", "Straddle"),
            plan("MRVL", "Straddle"),
            plan("THR", "Vertical Call"),
            plan("DELL", "Iron Condor"),
        ]
        annotated, summary = apply_setup_concentration_governor(plans)
        self.assertFalse(any(item.get("concentrationDemoted") for item in annotated))
        self.assertEqual(summary["demoted"], [])

    def test_governor_never_promotes_failed_plans(self) -> None:
        """Failed plans must stay failed — the governor must not flip ok=False to True."""
        plans = [
            plan("CEG", "Straddle"),
            plan("MRVL", "Straddle"),
            plan("DELL", "Straddle"),
            plan("FAILED", "Vertical Call", ok=False),
        ]
        annotated, _ = apply_setup_concentration_governor(plans)
        failed = next(item for item in annotated if item["ticker"] == "FAILED")
        self.assertFalse(failed["ok"])
        self.assertNotIn("concentrationDemoted", failed)

    def test_governor_is_idempotent(self) -> None:
        """Running the governor twice must not demote new plans on the second pass."""
        plans = [
            plan("CEG", "Straddle"),
            plan("MRVL", "Straddle"),
            plan("DELL", "Straddle"),
            plan("VNET", "Straddle"),
            plan("THR", "Vertical Call"),
        ]
        first_pass, _ = apply_setup_concentration_governor(plans)
        second_pass, summary = apply_setup_concentration_governor(first_pass)
        # Total demoted across both runs must match the first run only.
        first_demoted = sum(1 for item in first_pass if item.get("concentrationDemoted"))
        second_demoted = sum(1 for item in second_pass if item.get("concentrationDemoted"))
        self.assertEqual(first_demoted, second_demoted)
        # The summary's freshly-demoted list on the second run must be empty,
        # because demoted plans are excluded from share counts already.
        self.assertEqual(summary["demoted"], [])

    def test_share_summary_reflects_post_demotion_state(self) -> None:
        plans = [
            plan("CEG", "Straddle"),
            plan("MRVL", "Straddle"),
            plan("DELL", "Straddle"),
            plan("VNET", "Straddle"),
            plan("THR", "Vertical Call"),
        ]
        _, summary = apply_setup_concentration_governor(plans)
        self.assertGreaterEqual(summary["preDemotionShares"]["Straddle"], 0.7)
        self.assertLessEqual(summary["postDemotionShares"]["Straddle"], 0.75)
        # 3 Straddles + 1 Vertical Call survive primary => 0.75/0.25
        self.assertAlmostEqual(summary["postDemotionShares"]["Straddle"], 0.75, places=4)
        self.assertAlmostEqual(summary["postDemotionShares"]["Vertical Call"], 0.25, places=4)


class StrikeSelectorRedundancyTests(unittest.TestCase):
    """Verify strike-selector refresh and capped rehearsal helpers."""

    def test_cap_aware_long_strangle_plan_fits_under_single_ticket_cap(self) -> None:
        calls = pd.DataFrame(
            [
                {"strike": 45.0, "bid": 2.65, "ask": 3.4, "lastPrice": 3.0, "volume": 10, "openInterest": 100, "contractSymbol": "GDSC45", "impliedVolatility": 0.4},
                {"strike": 47.5, "bid": 1.2, "ask": 1.55, "lastPrice": 1.4, "volume": 15, "openInterest": 120, "contractSymbol": "GDSC47.5", "impliedVolatility": 0.38},
            ]
        )
        puts = pd.DataFrame(
            [
                {"strike": 45.0, "bid": 4.8, "ask": 5.6, "lastPrice": 5.2, "volume": 8, "openInterest": 90, "contractSymbol": "GDSP45", "impliedVolatility": 0.41},
                {"strike": 42.5, "bid": 1.55, "ask": 1.95, "lastPrice": 1.8, "volume": 11, "openInterest": 110, "contractSymbol": "GDSP42.5", "impliedVolatility": 0.39},
            ]
        )

        variant = cap_aware_long_strangle_plan(
            {"ticker": "GDS", "price": 45.0},
            "2026-06-18",
            calls,
            puts,
        )

        self.assertIsNotNone(variant)
        self.assertEqual(variant["strategy"], "LONG_STRANGLE")
        self.assertTrue(variant["paperVariantOnly"])
        self.assertLessEqual(float(variant["estimatedMaxLoss"]), 500.0)

    def test_load_execution_queue_rebuilds_when_cached_queue_is_empty(self) -> None:
        snapshot = {"reviewQueueTickers": ["THR", "GDS"]}
        cached_queue = {"generatedAt": "2026-05-12T06:00:00-06:00", "updatedAt": "2026-05-12T06:00:00-06:00", "items": []}
        rebuilt_queue = {
            "generatedAt": "2026-05-12T22:00:00-06:00",
            "updatedAt": "2026-05-12T22:00:00-06:00",
            "items": [{"ticker": "THR"}, {"ticker": "GDS"}],
        }

        def fake_load(path):
            path_text = str(path)
            if path_text.endswith("inferno_execution_queue.json"):
                return cached_queue
            if path_text.endswith("latest_snapshot.json"):
                return snapshot
            if path_text.endswith("inferno_approval_queue.json"):
                return {"items": []}
            return None

        with (
            patch("inferno_strike_selector.load_json_file", side_effect=fake_load),
            patch("inferno_strike_selector.in_current_service_cycle", return_value=True),
            patch("inferno_execution_clerk.build_execution_queue", return_value=rebuilt_queue) as build_queue,
            patch("inferno_execution_clerk.save_execution_queue") as save_queue,
        ):
            result = load_execution_queue()

        self.assertEqual(result, rebuilt_queue)
        build_queue.assert_called_once()
        save_queue.assert_called_once_with(rebuilt_queue)


if __name__ == "__main__":
    unittest.main()
