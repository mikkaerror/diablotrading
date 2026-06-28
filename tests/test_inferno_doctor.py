from __future__ import annotations

"""Regression tests for overnight doctor freshness handling."""

import unittest
import subprocess
from datetime import datetime
from unittest.mock import patch

from inferno_doctor import (
    block_reason_top_bucket_status,
    concentration_governor_status,
    conviction_research_status,
    cycle_days,
    cycle_reference_day,
    in_current_service_cycle,
    launch_agent_status,
    live_position_review_status,
    model_command_center_status,
    paper_blocker_swarm_status,
    paper_mark_to_market_status,
    paper_test_director_status,
    action_pulse_status,
    research_cycle_status,
    schwab_oauth_status,
    trade_management_status,
    watchdog_run_status,
)


class InfernoDoctorCycleTests(unittest.TestCase):
    """Verify the doctor respects the active operating cycle across midnight."""

    def test_cycle_reference_day_uses_previous_day_before_service_hour(self) -> None:
        now = datetime.fromisoformat("2026-04-30T01:30:00-06:00")
        self.assertEqual(cycle_reference_day(now, service_hour=6), "2026-04-29")
        self.assertEqual(cycle_days(now, service_hour=6), ("2026-04-29", "2026-04-30"))

    def test_cycle_reference_day_uses_previous_market_day_before_monday_service_hour(self) -> None:
        now = datetime.fromisoformat("2026-06-29T01:30:00-06:00")
        self.assertEqual(cycle_reference_day(now, service_hour=6), "2026-06-26")
        self.assertEqual(cycle_days(now, service_hour=6), ("2026-06-26", "2026-06-29"))

    def test_cycle_reference_day_uses_today_after_service_hour(self) -> None:
        now = datetime.fromisoformat("2026-04-30T06:30:00-06:00")
        self.assertEqual(cycle_reference_day(now, service_hour=6), "2026-04-30")
        self.assertEqual(cycle_days(now, service_hour=6), ("2026-04-30",))

    def test_cycle_reference_day_uses_previous_market_day_on_weekend(self) -> None:
        now = datetime.fromisoformat("2026-06-27T13:00:00-06:00")
        self.assertEqual(cycle_reference_day(now, service_hour=6), "2026-06-26")
        self.assertEqual(cycle_days(now, service_hour=6), ("2026-06-26", "2026-06-27"))

    def test_in_current_service_cycle_accepts_previous_day_overnight(self) -> None:
        now = datetime.fromisoformat("2026-04-30T01:30:00-06:00")
        self.assertTrue(
            in_current_service_cycle(
                "2026-04-29T07:45:00-06:00",
                now=now,
                service_hour=6,
            )
        )
        self.assertFalse(
            in_current_service_cycle(
                "2026-04-28T07:45:00-06:00",
                now=now,
                service_hour=6,
            )
        )

    def test_in_current_service_cycle_normalizes_utc_date_boundary(self) -> None:
        now = datetime.fromisoformat("2026-06-26T18:44:00-06:00")
        self.assertTrue(
            in_current_service_cycle(
                "2026-06-27T00:44:28+00:00",
                now=now,
                service_hour=6,
            )
        )

    def test_in_current_service_cycle_accepts_previous_session_on_weekend(self) -> None:
        now = datetime.fromisoformat("2026-06-27T13:00:00-06:00")
        self.assertTrue(
            in_current_service_cycle(
                "2026-06-26T06:05:00-06:00",
                now=now,
                service_hour=6,
            )
        )

    def test_watchdog_run_status_accepts_no_dawn_on_market_closed_day(self) -> None:
        now = datetime.fromisoformat("2026-06-27T13:00:00-06:00")
        ok, detail = watchdog_run_status(
            {
                "checkedAt": "2026-06-27T13:00:00-06:00",
                "ok": False,
                "reasons": ["no dawn-cycle run is recorded for 2026-06-27"],
            },
            now,
        )

        self.assertTrue(ok)
        self.assertIn("market closed", detail)

    def test_watchdog_run_status_warns_on_weekday_missing_dawn(self) -> None:
        now = datetime.fromisoformat("2026-06-29T13:00:00-06:00")
        ok, detail = watchdog_run_status(
            {
                "checkedAt": "2026-06-29T13:00:00-06:00",
                "ok": False,
                "reasons": ["no dawn-cycle run is recorded for 2026-06-29"],
            },
            now,
        )

        self.assertFalse(ok)
        self.assertIn("no dawn-cycle", detail)

    def test_live_position_review_status_accepts_review_as_healthy_lane(self) -> None:
        with patch("inferno_doctor.recent_or_today", return_value=True):
            ok, detail = live_position_review_status(
                {
                    "generatedAt": "2026-05-10T06:30:00-06:00",
                    "ok": True,
                    "verdict": "review",
                    "counts": {"supported": 2, "review": 1, "fragile": 0},
                }
            )
        self.assertTrue(ok)
        self.assertIn("review | supported=2 | review=1 | fragile=0", detail)

    def test_live_position_review_status_warns_when_artifact_missing(self) -> None:
        ok, detail = live_position_review_status({})
        self.assertFalse(ok)
        self.assertEqual(detail, "missing")

    def test_model_command_center_status_accepts_ready_payload(self) -> None:
        with patch("inferno_doctor.recent_or_today", return_value=True):
            ok, detail = model_command_center_status(
                {
                    "generatedAt": "2026-05-10T15:00:00-06:00",
                    "status": "ready",
                    "headlineMetrics": {"liveFragile": 1},
                    "activeMissions": [{"id": "mission-1"}],
                    "recentNotes": [{"id": "note-1"}],
                }
            )
        self.assertTrue(ok)
        self.assertIn("ready | missions=1 | notes=1 | live-fragile=1", detail)

    def test_model_command_center_status_warns_when_missing(self) -> None:
        ok, detail = model_command_center_status({})
        self.assertFalse(ok)
        self.assertEqual(detail, "missing")

    def test_action_pulse_status_accepts_sent_pulse(self) -> None:
        with patch("inferno_doctor.recent_or_today", return_value=True):
            ok, detail = action_pulse_status(
                {
                    "generatedAt": "2026-05-15T07:05:00-06:00",
                    "phaseLabel": "Open Watch",
                    "verdict": "blocked",
                    "delivery": {"status": "sent"},
                }
            )
        self.assertTrue(ok)
        self.assertIn("Open Watch", detail)
        self.assertIn("delivery=sent", detail)

    def test_action_pulse_status_warns_when_missing(self) -> None:
        ok, detail = action_pulse_status({})
        self.assertFalse(ok)
        self.assertEqual(detail, "missing")

    def test_launch_agent_status_warns_on_nonzero_last_exit(self) -> None:
        with patch(
            "inferno_doctor.run_command",
            return_value=subprocess.CompletedProcess(
                args=["launchctl", "print"],
                returncode=0,
                stdout="runs = 3\nlast exit code = 78: EX_CONFIG\n",
                stderr="",
            ),
        ):
            ok, detail = launch_agent_status("io.example.bad")

        self.assertFalse(ok)
        self.assertIn("runs=3", detail)
        self.assertIn("last exit code=78: EX_CONFIG", detail)

    def test_launch_agent_status_accepts_zero_last_exit(self) -> None:
        with patch(
            "inferno_doctor.run_command",
            return_value=subprocess.CompletedProcess(
                args=["launchctl", "print"],
                returncode=0,
                stdout="runs = 1\nlast exit code = 0\n",
                stderr="",
            ),
        ):
            ok, detail = launch_agent_status("io.example.good")

        self.assertTrue(ok)
        self.assertIn("last exit code=0", detail)

    def test_launch_agent_status_accepts_never_exited_before_first_run(self) -> None:
        with patch(
            "inferno_doctor.run_command",
            return_value=subprocess.CompletedProcess(
                args=["launchctl", "print"],
                returncode=0,
                stdout="runs = 0\nlast exit code = (never exited)\n",
                stderr="",
            ),
        ):
            ok, detail = launch_agent_status("io.example.scheduled")

        self.assertTrue(ok)
        self.assertIn("runs=0", detail)
        self.assertIn("last exit code=(never exited)", detail)

    def test_schwab_oauth_status_warns_before_consent_grant_gets_old(self) -> None:
        ok, detail = schwab_oauth_status(
            {
                "clientIdConfigured": True,
                "clientSecretConfigured": True,
                "accessTokenPresent": True,
                "refreshTokenPresent": True,
                "refreshTokenAgeSeconds": 5.25 * 86_400,
                "reauthorizationRequired": False,
            }
        )

        self.assertFalse(ok)
        self.assertIn("restart advisory", detail)
        self.assertIn("5.2d", detail)

    def test_schwab_oauth_status_accepts_fresh_grant(self) -> None:
        ok, detail = schwab_oauth_status(
            {
                "clientIdConfigured": True,
                "clientSecretConfigured": True,
                "accessTokenPresent": True,
                "refreshTokenPresent": True,
                "refreshTokenAgeSeconds": 2 * 86_400,
                "accessTokenNeedsRefresh": False,
                "reauthorizationRequired": False,
            }
        )

        self.assertTrue(ok)
        self.assertIn("consent grant age=2.0d", detail)

    def test_paper_mark_to_market_status_accepts_disabled_fetch(self) -> None:
        with patch("inferno_doctor.recent_or_today", return_value=True):
            ok, detail = paper_mark_to_market_status(
                {
                    "generatedAt": "2026-05-27T04:00:00+00:00",
                    "verdict": "disabled",
                    "fetchStatus": "disabled",
                    "promotable": False,
                    "openPositionCount": 2,
                }
            )
        self.assertTrue(ok)
        self.assertIn("disabled", detail)
        self.assertIn("open=2", detail)
        self.assertIn("research-only=True", detail)

    def test_paper_mark_to_market_status_warns_when_promotable(self) -> None:
        with patch("inferno_doctor.recent_or_today", return_value=True):
            ok, detail = paper_mark_to_market_status(
                {
                    "generatedAt": "2026-05-27T04:00:00+00:00",
                    "verdict": "ok",
                    "promotable": True,
                }
            )
        self.assertFalse(ok)

    def test_paper_blocker_swarm_status_accepts_fixable_research_payload(self) -> None:
        with patch("inferno_doctor.recent_or_today", return_value=True):
            ok, detail = paper_blocker_swarm_status(
                {
                    "generatedAt": "2026-06-24T09:30:00-06:00",
                    "verdict": "fixable-blockers-present",
                    "researchOnly": True,
                    "promotable": False,
                    "dominantLane": "data_freshness",
                    "counts": {"fixableByTooling": 1},
                    "rewards": {"outcomeReward": 0.0},
                }
            )

        self.assertTrue(ok)
        self.assertIn("fixable-blockers-present", detail)
        self.assertIn("dominant=data_freshness", detail)
        self.assertIn("tooling-fixable=1", detail)

    def test_paper_blocker_swarm_status_rejects_outcome_reward_drift(self) -> None:
        with patch("inferno_doctor.recent_or_today", return_value=True):
            ok, detail = paper_blocker_swarm_status(
                {
                    "generatedAt": "2026-06-24T09:30:00-06:00",
                    "verdict": "fixable-blockers-present",
                    "researchOnly": True,
                    "promotable": False,
                    "counts": {"fixableByTooling": 1},
                    "rewards": {"outcomeReward": 1.0},
                }
            )

        self.assertFalse(ok)
        self.assertIn("outcome-reward=1.0", detail)

    def test_trade_management_status_accepts_actions_recommended(self) -> None:
        with patch("inferno_doctor.recent_or_today", return_value=True):
            ok, detail = trade_management_status(
                {
                    "generatedAt": "2026-05-27T04:05:00+00:00",
                    "verdict": "actions-recommended",
                    "researchOnly": True,
                    "promotable": False,
                    "authorityChanged": False,
                    "liveTradingAllowed": False,
                    "brokerSubmitAllowed": False,
                    "openPositionCount": 2,
                    "actionableCount": 1,
                }
            )
        self.assertTrue(ok)
        self.assertIn("actions-recommended", detail)
        self.assertIn("open=2", detail)
        self.assertIn("actionable=1", detail)

    def test_trade_management_status_accepts_awaiting_data(self) -> None:
        with patch("inferno_doctor.recent_or_today", return_value=True):
            ok, detail = trade_management_status(
                {
                    "generatedAt": "2026-05-27T04:05:00+00:00",
                    "verdict": "awaiting-data",
                    "researchOnly": True,
                    "promotable": False,
                    "authorityChanged": False,
                    "liveTradingAllowed": False,
                    "brokerSubmitAllowed": False,
                    "openPositionCount": 1,
                    "actionableCount": 0,
                }
            )
        self.assertTrue(ok)
        self.assertIn("awaiting-data", detail)

    def test_trade_management_status_warns_when_authority_changes(self) -> None:
        with patch("inferno_doctor.recent_or_today", return_value=True):
            ok, detail = trade_management_status(
                {
                    "generatedAt": "2026-05-27T04:05:00+00:00",
                    "verdict": "all-hold",
                    "researchOnly": True,
                    "promotable": False,
                    "authorityChanged": True,
                    "liveTradingAllowed": False,
                    "brokerSubmitAllowed": False,
                }
            )
        self.assertFalse(ok)

    def test_research_cycle_status_accepts_fresh_refresh(self) -> None:
        with patch("inferno_doctor.recent_or_today", return_value=True):
            ok, detail = research_cycle_status(
                {
                    "generatedAt": "2026-05-10T15:00:00-06:00",
                    "verdict": "research-refreshed",
                    "shadow": {"trackedCount": 39, "closedCount": 10},
                    "strategyLab": {"verdict": "insufficient-data", "scoredCount": 0},
                    "scenarioBacktest": {"scenarioCount": 12, "closedEvidenceCount": 2},
                }
            )
        self.assertTrue(ok)
        self.assertIn("research-refreshed", detail)
        self.assertIn("shadow tracked=39", detail)
        self.assertIn("scenarios=12", detail)

    def test_research_cycle_status_warns_when_missing(self) -> None:
        ok, detail = research_cycle_status({})
        self.assertFalse(ok)
        self.assertEqual(detail, "missing")

    def test_conviction_research_status_accepts_research_only_payload(self) -> None:
        with patch("inferno_doctor.recent_or_today", return_value=True):
            ok, detail = conviction_research_status(
                {
                    "generatedAt": "2026-05-18T21:30:00-06:00",
                    "researchOnly": True,
                    "promotable": False,
                    "scoredRows": 40,
                    "behemoths": [{"ticker": "NVDA"}, {"ticker": "AVGO"}],
                    "sleepers": [{"ticker": "MOD"}],
                }
            )
        self.assertTrue(ok)
        self.assertIn("40 scored", detail)
        self.assertIn("giants=NVDA, AVGO", detail)
        self.assertIn("sleepers=MOD", detail)

    def test_conviction_research_status_warns_when_promotable(self) -> None:
        with patch("inferno_doctor.recent_or_today", return_value=True):
            ok, detail = conviction_research_status(
                {
                    "generatedAt": "2026-05-18T21:30:00-06:00",
                    "researchOnly": True,
                    "promotable": True,
                    "scoredRows": 40,
                }
            )
        self.assertFalse(ok)
        self.assertIn("research-only=False", detail)


class InfernoDoctorInformationalSignalsTests(unittest.TestCase):
    """Verify the new informational doctor lines never bump warnings."""

    def test_block_reason_top_bucket_status_returns_top_label(self) -> None:
        performance = {
            "blockReasonCategories": {
                "approval-missing": {"count": 84, "examples": ["human approval missing"]},
                "size-cap-violation": {"count": 17, "examples": ["max loss exceeds cap"]},
            }
        }
        ok, detail = block_reason_top_bucket_status(performance)
        self.assertTrue(ok)
        self.assertIn("approval-missing", detail)
        self.assertIn("84", detail)

    def test_block_reason_top_bucket_status_handles_missing_categories(self) -> None:
        ok, detail = block_reason_top_bucket_status({})
        self.assertTrue(ok)
        self.assertEqual(detail, "no block reasons logged")

    def test_concentration_governor_status_includes_limit_and_counts(self) -> None:
        strike_plan = {
            "primaryCount": 4,
            "concentrationDemotedCount": 1,
            "concentrationGovernor": {"limit": 0.6, "demoted": [{"ticker": "VNET"}]},
        }
        ok, detail = concentration_governor_status(strike_plan)
        self.assertTrue(ok)
        self.assertIn("0.6", detail)
        self.assertIn("primary 4", detail)
        self.assertIn("demoted 1", detail)

    def test_concentration_governor_status_handles_missing_strike_plan(self) -> None:
        ok, detail = concentration_governor_status({})
        self.assertTrue(ok)
        self.assertEqual(detail, "no strike plan yet")

    def test_paper_test_director_status_accepts_shadow_fallback(self) -> None:
        now = datetime.fromisoformat("2026-05-19T09:00:00-06:00")
        director = {
            "generatedAt": "2026-05-19T08:55:00-06:00",
            "verdict": "no-viable-paper-tests",
            "counts": {"stageableNow": 0, "approvalOnly": 0, "hardBlocked": 7},
        }
        reducer = {
            "generatedAt": "2026-05-19T08:56:00-06:00",
            "verdict": "scenario-slate-ready",
            "counts": {"scenarios": 12, "shadowOnly": 12},
        }

        ok, detail = paper_test_director_status(director, reducer, now)

        self.assertTrue(ok)
        self.assertIn("no-viable-paper-tests", detail)
        self.assertIn("shadow-fallback=ready", detail)

    def test_paper_test_director_status_accepts_auto_paper_selection(self) -> None:
        now = datetime.fromisoformat("2026-05-19T09:00:00-06:00")
        director = {
            "generatedAt": "2026-05-19T08:55:00-06:00",
            "verdict": "auto-paper-selected",
            "counts": {"stageableNow": 0, "autoPaperSelected": 2, "approvalOnly": 0, "hardBlocked": 1},
        }

        ok, detail = paper_test_director_status(director, {}, now)

        self.assertTrue(ok)
        self.assertIn("auto-paper-selected", detail)
        self.assertIn("auto-paper=2", detail)

    def test_paper_test_director_status_warns_without_shadow_fallback(self) -> None:
        now = datetime.fromisoformat("2026-05-19T09:00:00-06:00")
        director = {
            "generatedAt": "2026-05-19T08:55:00-06:00",
            "verdict": "no-viable-paper-tests",
            "counts": {"stageableNow": 0, "approvalOnly": 0, "hardBlocked": 7},
        }
        reducer = {
            "generatedAt": "2026-05-19T08:56:00-06:00",
            "verdict": "scenario-slate-thin",
            "counts": {"scenarios": 0, "shadowOnly": 0},
        }

        ok, detail = paper_test_director_status(director, reducer, now)

        self.assertFalse(ok)
        self.assertIn("hard-blocked=7", detail)


if __name__ == "__main__":
    unittest.main()
