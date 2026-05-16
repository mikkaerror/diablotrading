from __future__ import annotations

"""Regression tests for the daily success-criteria diagnostic.

Contract:
- safety-anchored criteria force a red verdict when they fail
- operational criteria force at most a yellow verdict
- the diagnostic never mutates an input
- the artifact path is distinct from any operational artifact
"""

import unittest

from inferno_daily_success import (
    DAILY_SUCCESS_FILE,
    DAILY_SUCCESS_STAGE,
    DAILY_SUCCESS_TEXT_FILE,
    build_daily_success,
    overall_verdict,
)


def healthy_inputs(today: str = "2026-05-10") -> dict:
    return {
        "ops_status": {
            "generatedAt": f"{today}T06:00:00-06:00",
            "emailSent": True,
        },
        "ops_maintenance": {
            "generatedAt": f"{today}T07:00:00-06:00",
            "ok": True,
        },
        "queue": {
            "items": [
                {"ticker": "CEG", "approvalStatus": "approved", "decisionAt": f"{today}T07:30:00-06:00"},
                {"ticker": "VNET", "approvalStatus": "pending"},
            ]
        },
        "authority": {
            "decision": {
                "authorityLevel": "paper-evidence-only",
                "brokerSubmitAllowed": False,
                "liveTradingAllowed": False,
            }
        },
        "live_review": {"counts": {"supported": 2, "review": 0, "fragile": 1}},
        "prior": {"liveReview": {"counts": {"fragile": 1}}},
        "today": today,
    }


class DailySuccessTests(unittest.TestCase):
    """Verify the green/yellow/red logic and fail-closed safety stance."""

    def test_artifact_paths_distinct_and_stage_committed(self) -> None:
        self.assertTrue(str(DAILY_SUCCESS_FILE).endswith("inferno_daily_success.json"))
        self.assertTrue(str(DAILY_SUCCESS_TEXT_FILE).endswith("daily_success_latest.txt"))
        self.assertEqual(DAILY_SUCCESS_STAGE, "daily-success-diagnostic-only")

    def test_healthy_inputs_produce_green_verdict(self) -> None:
        report = build_daily_success(**healthy_inputs())
        self.assertEqual(report["verdict"], "green")
        self.assertEqual(report["passCount"], report["totalCount"])
        self.assertTrue(report["diagnosticOnly"])

    def test_safety_failure_forces_red(self) -> None:
        inputs = healthy_inputs()
        # Authority manifest broker submit flipped to True — must force red.
        inputs["authority"]["decision"]["brokerSubmitAllowed"] = True
        report = build_daily_success(**inputs)
        self.assertEqual(report["verdict"], "red")

    def test_operational_failure_yields_yellow_not_red(self) -> None:
        inputs = healthy_inputs()
        # No decisions today is operational, not safety.
        inputs["queue"]["items"] = [{"ticker": "VNET", "approvalStatus": "pending"}]
        report = build_daily_success(**inputs)
        self.assertEqual(report["verdict"], "yellow")

    def test_new_fragile_holding_yields_yellow(self) -> None:
        inputs = healthy_inputs()
        inputs["live_review"]["counts"]["fragile"] = 2
        inputs["prior"] = {"liveReview": {"counts": {"fragile": 1}}}
        report = build_daily_success(**inputs)
        self.assertEqual(report["verdict"], "yellow")

    def test_missing_prior_treats_unchanged_as_pass(self) -> None:
        inputs = healthy_inputs()
        inputs["prior"] = {}
        report = build_daily_success(**inputs)
        # First run with no prior snapshot still passes the no-new-fragile check.
        new_fragile_check = next(c for c in report["criteria"] if c["name"] == "noNewFragileHoldings")
        self.assertTrue(new_fragile_check["pass"])

    def test_overall_verdict_red_overrides_yellow(self) -> None:
        criteria = [
            {"name": "safety-fail", "pass": False, "category": "safety", "detail": ""},
            {"name": "op-fail", "pass": False, "category": "operational", "detail": ""},
        ]
        self.assertEqual(overall_verdict(criteria), "red")

    def test_overall_verdict_green_only_when_all_pass(self) -> None:
        criteria = [
            {"name": "a", "pass": True, "category": "safety", "detail": ""},
            {"name": "b", "pass": True, "category": "operational", "detail": ""},
        ]
        self.assertEqual(overall_verdict(criteria), "green")

    def test_build_daily_success_does_not_mutate_inputs(self) -> None:
        import json as _json
        inputs = healthy_inputs()
        snapshot = _json.dumps(inputs, sort_keys=True, default=str)
        build_daily_success(**inputs)
        after = _json.dumps(inputs, sort_keys=True, default=str)
        self.assertEqual(snapshot, after)


if __name__ == "__main__":
    unittest.main()
