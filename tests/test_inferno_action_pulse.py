from __future__ import annotations

"""Regression tests for the twice-daily action pulse."""

import unittest
from unittest.mock import patch

from inferno_action_pulse import (
    build_action_pulse,
    render_action_pulse,
    resolve_deployable_cash,
    sent_key,
    subject_for_pulse,
)


class InfernoActionPulseTests(unittest.TestCase):
    """Verify the action pulse is concise, deduped, and safety-forward."""

    def test_subject_includes_phase_and_verdict(self) -> None:
        subject = subject_for_pulse({"phaseLabel": "Open Watch", "verdict": "blocked"})

        self.assertEqual(subject, "[Inferno Action Pulse] OPEN WATCH: BLOCKED")

    def test_sent_key_is_phase_scoped(self) -> None:
        self.assertEqual(sent_key("open", "2026-05-15"), "2026-05-15:open")
        self.assertEqual(sent_key("preclose", "2026-05-15"), "2026-05-15:preclose")

    @patch("inferno_action_pulse.freshness_status", return_value="fresh")
    @patch("inferno_action_pulse.load_json_file")
    def test_resolve_deployable_cash_prefers_current_artifacts(
        self,
        load_json_mock,
        _freshness_mock,
    ) -> None:
        load_json_mock.side_effect = [
            {
                "generatedAt": "2026-06-13T09:00:00-06:00",
                "deployableCashSource": "live-account-sync",
                "guardrails": {"deployableCash": "$167.88"},
            },
        ]

        self.assertEqual(resolve_deployable_cash(), 167.88)

    @patch("inferno_action_pulse.freshness_status", side_effect=["stale", "fresh"])
    @patch("inferno_action_pulse.load_json_file")
    def test_resolve_deployable_cash_falls_back_to_fresh_live_cash(
        self,
        load_json_mock,
        _freshness_mock,
    ) -> None:
        load_json_mock.side_effect = [
            {
                "generatedAt": "2026-06-08T09:00:00-06:00",
                "deployableCashSource": "live-account-sync",
                "guardrails": {"deployableCash": "$500.00"},
            },
            {"generatedAt": "2026-06-13T09:00:00-06:00", "totalCash": "$42.50"},
        ]

        self.assertEqual(resolve_deployable_cash(), 42.50)

    @patch("inferno_action_pulse.freshness_status", return_value="fresh")
    @patch("inferno_action_pulse.load_json_file")
    def test_resolve_deployable_cash_preserves_fresh_zero(
        self,
        load_json_mock,
        _freshness_mock,
    ) -> None:
        load_json_mock.return_value = {
            "generatedAt": "2026-06-13T09:00:00-06:00",
            "deployableCashSource": "live-account-sync",
            "guardrails": {"deployableCash": 0.0},
        }

        self.assertEqual(resolve_deployable_cash(), 0.0)
        load_json_mock.assert_called_once()

    @patch("inferno_action_pulse.freshness_status", return_value="stale")
    @patch("inferno_action_pulse.load_json_file")
    def test_resolve_deployable_cash_uses_zero_when_all_sources_are_stale(
        self,
        load_json_mock,
        _freshness_mock,
    ) -> None:
        load_json_mock.side_effect = [
            {"generatedAt": "2026-06-08T09:00:00-06:00", "guardrails": {"deployableCash": 500.0}},
            {"generatedAt": "2026-06-08T09:00:00-06:00", "totalCash": 250.0},
        ]

        self.assertEqual(resolve_deployable_cash(), 0.0)

    @patch("inferno_action_pulse.freshness_status", return_value="fresh")
    @patch("inferno_action_pulse.load_json_file")
    def test_resolve_deployable_cash_does_not_promote_planning_scenario_cash(
        self,
        load_json_mock,
        _freshness_mock,
    ) -> None:
        load_json_mock.side_effect = [
            {
                "generatedAt": "2026-06-13T09:00:00-06:00",
                "deployableCashSource": "operator-argument",
                "guardrails": {"deployableCash": 5000.0},
            },
            {
                "generatedAt": "2026-06-13T09:01:00-06:00",
                "accountDataSource": "schwab-account-api",
                "schwabAccountGeneratedAt": "2026-06-13T09:00:00-06:00",
                "totalCash": 42.5,
            },
        ]

        self.assertEqual(resolve_deployable_cash(), 42.5)

    def test_render_action_pulse_surfaces_safety_locks(self) -> None:
        rendered = render_action_pulse(
            {
                "generatedAt": "2026-05-15T07:05:00-06:00",
                "phaseLabel": "Open Watch",
                "fastMode": True,
                "verdict": "blocked",
                "message": "Do not deploy fresh capital.",
                "manualDeploymentAllowed": False,
                "autoLiveAllowed": False,
                "deployableCash": 1000,
                "capitalLaunch": {
                    "capitalReadiness": {
                        "guardrails": {
                            "maxOptionsRisk": 250,
                            "maxStarterTicket": 125,
                            "maxLongTermBuy": 300,
                            "reserveCash": 450,
                        }
                    }
                },
                "dailyLoop": {
                    "decideTodayTickers": ["NVDA"],
                    "narrative": (
                        "TOS is intentionally closed for low-performance mode; open it only "
                        "for supervised export or manual order staging."
                    ),
                },
                "tosVisibility": {
                    "message": "TOS is running, but no main window is visible to the attach-only probe.",
                },
                "freshnessPanel": {
                    "rows": [
                        {
                            "label": "tracker snapshot",
                            "status": "fresh",
                            "generatedAt": "2026-05-15T06:00:00-06:00",
                            "ageHours": 1.0,
                        }
                    ]
                },
                "schwabDailyOps": {
                    "available": True,
                    "laneCounts": {"tradable-research": 1, "avoid-chain": 1},
                    "summaryLines": ["NVDA: tradable-research | Q 86/institutional | spread tight | liq 100 | move 5.90%"],
                },
                "paperEvidence": {
                    "available": True,
                    "brokerSubmitAllowed": False,
                    "counts": {
                        "scenarios": 12,
                        "executablePaper": 0,
                        "approvalNeeded": 0,
                        "shadowOnly": 12,
                    },
                    "summaryLines": [
                        "MOD: SHADOW | shadow-scenario | score 73.59 | Track MOD as shadow evidence only.",
                    ],
                },
                "decisionSummary": ["GDS hard-blocks-new-capital"],
                "warningSummary": ["Live position review has 1 fragile holding."],
                "operatorCommands": ["./inferno capital-check --deployable-cash 1000"],
                "operatorRule": "No broker submit.",
            }
        )

        self.assertIn("What changed", rendered)
        self.assertIn("Fast mode: True", rendered)
        self.assertIn("What matters today", rendered)
        self.assertIn("What action is allowed", rendered)
        self.assertIn("TOS is running, but no main window is visible", rendered)
        self.assertIn("tracker snapshot: fresh", rendered)
        self.assertIn("Auto live trading allowed: False", rendered)
        self.assertIn("Max options risk: $250.00", rendered)
        self.assertIn("Schwab options tape", rendered)
        self.assertIn("NVDA: tradable-research", rendered)
        self.assertIn("Paper evidence queue", rendered)
        self.assertIn("scenarios=12", rendered)
        self.assertIn("MOD: SHADOW", rendered)
        self.assertIn("./inferno capital-check --deployable-cash 1000", rendered)
        self.assertIn("executablePaper=true means operator-routable paper candidate", rendered)
        self.assertIn("GDS hard-blocks-new-capital", rendered)
        self.assertNotIn("TOS is intentionally closed", rendered)

    @patch("inferno_action_pulse.save_action_pulse")
    @patch("inferno_action_pulse.build_tos_visibility_summary", return_value={"message": "TOS visibility skipped in test."})
    @patch("inferno_action_pulse.build_freshness_panel", return_value={"rows": []})
    @patch("inferno_action_pulse.build_capital_launch_check")
    @patch("inferno_action_pulse.build_daily_loop")
    @patch("inferno_action_pulse.run_maintenance")
    @patch("inferno_action_pulse.load_json_file")
    def test_fast_mode_uses_saved_heavy_artifacts(
        self,
        load_json_mock,
        run_maintenance_mock,
        build_daily_loop_mock,
        build_launch_mock,
        _freshness_mock,
        _tos_mock,
        _save_mock,
    ) -> None:
        load_json_mock.side_effect = [
            {"deskVerdict": "saved", "decideTodayTickers": ["TE"], "narrative": "saved loop"},
            {"rows": [], "laneCounts": {}},
            {"counts": {"scenarios": 1, "executablePaper": 0, "approvalNeeded": 0, "shadowOnly": 1}},
        ]
        build_launch_mock.return_value = {
            "verdict": "blocked",
            "message": "blocked",
            "manualDeploymentAllowed": False,
            "capitalReadiness": {"guardrails": {}},
        }

        payload = build_action_pulse(phase="manual", deployable_cash=1050, fast=True)

        run_maintenance_mock.assert_not_called()
        build_daily_loop_mock.assert_not_called()
        self.assertTrue(payload["fastMode"])
        self.assertEqual(payload["dailyLoop"]["deskVerdict"], "saved")
        self.assertIn("--fast", payload["operatorCommands"][1])


if __name__ == "__main__":
    unittest.main()
