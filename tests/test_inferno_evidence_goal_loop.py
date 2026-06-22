from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import inferno_evidence_goal_loop as loop


NOW = datetime(2026, 6, 22, 13, 0, tzinfo=ZoneInfo("America/Denver"))


def safe_artifacts() -> dict:
    generated = NOW.isoformat()
    return {
        "authority": {
            "generatedAt": generated,
            "decision": {
                "authorityLevel": "paper-evidence-only",
                "liveTradingAllowed": False,
                "brokerSubmitAllowed": False,
                "allowedActions": ["record_paper_ledger"],
            },
        },
        "processCompliance": {
            "generatedAt": generated,
            "newPaperEntriesAllowed": True,
            "counts": {"hardBreaches": 0},
        },
        "paperEvidenceLoop": {
            "generatedAt": generated,
            "verdict": "evidence-building",
            "counts": {"remainingForPromotion": 29},
        },
        "fastPaper": {
            "generatedAt": generated,
            "verdict": "cycled-and-seeded",
            "counts": {"open": 4, "lifetimeClosed": 4},
            "researchOnly": True,
            "promotable": False,
            "liveTradingAllowed": False,
            "brokerSubmitAllowed": False,
        },
        "performance": {
            "generatedAt": generated,
            "closedMetrics": {"scoredCount": 1},
        },
        "strategyLab": {
            "generatedAt": generated,
            "deskVerdict": {"level": "evidence-building"},
        },
        "paperVelocity": {
            "generatedAt": generated,
            "velocity": {"weeklyRate30dWindow": 1.0},
        },
    }


class EvidenceGoalLoopTests(unittest.TestCase):
    def test_verifier_accepts_fresh_safe_research_cycle(self) -> None:
        commands = [{"name": "step", "ok": True}]
        result = loop.verify_cycle(safe_artifacts(), commands, now=NOW)

        self.assertTrue(result["passed"])
        self.assertTrue(result["authorityIntact"])
        self.assertTrue(result["paperEntryGateOpen"])

    def test_verifier_rejects_live_authority_drift(self) -> None:
        artifacts = safe_artifacts()
        artifacts["authority"]["decision"]["liveTradingAllowed"] = True

        result = loop.verify_cycle(artifacts, [], now=NOW)

        self.assertFalse(result["passed"])
        self.assertIn("liveTradingAllowed is not hard-false", result["errors"])

    def test_precheck_requires_paper_evidence_authority(self) -> None:
        artifacts = safe_artifacts()
        artifacts["authority"]["decision"]["authorityLevel"] = "halted"

        result = loop.verify_precheck(artifacts)

        self.assertFalse(result["passed"])
        self.assertIn(
            "authority level halted is not unattended paper scope",
            result["errors"],
        )

    def test_precheck_rejects_process_breach(self) -> None:
        artifacts = safe_artifacts()
        artifacts["processCompliance"]["newPaperEntriesAllowed"] = False
        artifacts["processCompliance"]["counts"]["hardBreaches"] = 1

        result = loop.verify_precheck(artifacts)

        self.assertFalse(result["passed"])
        self.assertFalse(result["paperEntryGateOpen"])

    def test_goal_loop_stops_after_successful_verified_iteration(self) -> None:
        calls = []

        def runner(name, argv, *, timeout_seconds):
            calls.append((name, argv, timeout_seconds))
            return {"name": name, "ok": True, "returnCode": 0}

        payload = loop.build_goal_loop(
            max_iterations=3,
            timeout_seconds=10,
            command_runner=runner,
            artifact_loader=safe_artifacts,
        )

        self.assertEqual(payload["verdict"], "cycle-complete")
        self.assertEqual(payload["iterationCount"], 1)
        self.assertTrue(payload["verification"]["passed"])
        self.assertFalse(payload["brokerSubmitAllowed"])
        self.assertEqual(
            len(calls),
            len(loop.PRECHECK_COMMANDS) + len(loop.CYCLE_COMMANDS),
        )

    def test_goal_loop_never_runs_cycle_when_precheck_is_unsafe(self) -> None:
        artifacts = safe_artifacts()
        artifacts["authority"]["decision"]["brokerSubmitAllowed"] = True
        calls = []

        def runner(name, argv, *, timeout_seconds):
            calls.append(name)
            return {"name": name, "ok": True, "returnCode": 0}

        payload = loop.build_goal_loop(
            command_runner=runner,
            artifact_loader=lambda: artifacts,
        )

        self.assertEqual(payload["verdict"], "blocked-safety")
        self.assertEqual(payload["iterationCount"], 0)
        self.assertEqual(len(calls), len(loop.PRECHECK_COMMANDS))

    def test_contract_is_pinned_research_only(self) -> None:
        payload = loop.build_goal_loop(
            command_runner=lambda name, argv, timeout_seconds: {
                "name": name,
                "ok": True,
            },
            artifact_loader=safe_artifacts,
        )

        self.assertEqual(payload["stage"], loop.GOAL_LOOP_STAGE)
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["authorityChanged"])
        self.assertFalse(payload["liveTradingAllowed"])
        self.assertFalse(payload["brokerSubmitAllowed"])


if __name__ == "__main__":
    unittest.main()
