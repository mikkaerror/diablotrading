from __future__ import annotations

"""Regression tests for the twice-daily action pulse."""

import unittest

from inferno_action_pulse import render_action_pulse, sent_key, subject_for_pulse


class InfernoActionPulseTests(unittest.TestCase):
    """Verify the action pulse is concise, deduped, and safety-forward."""

    def test_subject_includes_phase_and_verdict(self) -> None:
        subject = subject_for_pulse({"phaseLabel": "Open Watch", "verdict": "blocked"})

        self.assertEqual(subject, "[Inferno Action Pulse] OPEN WATCH: BLOCKED")

    def test_sent_key_is_phase_scoped(self) -> None:
        self.assertEqual(sent_key("open", "2026-05-15"), "2026-05-15:open")
        self.assertEqual(sent_key("preclose", "2026-05-15"), "2026-05-15:preclose")

    def test_render_action_pulse_surfaces_safety_locks(self) -> None:
        rendered = render_action_pulse(
            {
                "generatedAt": "2026-05-15T07:05:00-06:00",
                "phaseLabel": "Open Watch",
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
                "decisionSummary": ["GDS hard-blocks-new-capital"],
                "warningSummary": ["Live position review has 1 fragile holding."],
                "operatorCommands": ["./run_inferno_capital_launch_check.sh --deployable-cash 1000"],
                "operatorRule": "No broker submit.",
            }
        )

        self.assertIn("What changed", rendered)
        self.assertIn("What matters today", rendered)
        self.assertIn("What action is allowed", rendered)
        self.assertIn("TOS is running, but no main window is visible", rendered)
        self.assertIn("tracker snapshot: fresh", rendered)
        self.assertIn("Auto live trading allowed: False", rendered)
        self.assertIn("Max options risk: $250.00", rendered)
        self.assertIn("Schwab options tape", rendered)
        self.assertIn("NVDA: tradable-research", rendered)
        self.assertIn("GDS hard-blocks-new-capital", rendered)
        self.assertNotIn("TOS is intentionally closed", rendered)


if __name__ == "__main__":
    unittest.main()
