from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
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
        "scenarioEvidence": {
            "generatedAt": generated,
            "counts": {"open": 2, "closed": 10},
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

    def test_goal_loop_labels_clean_unchanged_iteration_no_op(self) -> None:
        calls = []

        def runner(name, argv, *, timeout_seconds):
            calls.append((name, argv, timeout_seconds))
            return {"name": name, "ok": True, "returnCode": 0}

        payload = loop.build_goal_loop(
            max_iterations=3,
            timeout_seconds=10,
            command_runner=runner,
            artifact_loader=safe_artifacts,
            state_loader=lambda: {},
            now=NOW,
        )

        self.assertEqual(payload["verdict"], "no-op")
        self.assertEqual(payload["valueClass"], "no-op")
        self.assertEqual(payload["progressDelta"]["acceptedProgressPoints"], 0)
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
            state_loader=lambda: {},
            now=NOW,
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
            state_loader=lambda: {},
            now=NOW,
        )

        self.assertEqual(payload["stage"], loop.GOAL_LOOP_STAGE)
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["authorityChanged"])
        self.assertFalse(payload["liveTradingAllowed"])
        self.assertFalse(payload["brokerSubmitAllowed"])

    def test_goal_loop_marks_verified_evidence_gain_productive(self) -> None:
        baseline = safe_artifacts()
        improved = safe_artifacts()
        improved["performance"]["closedMetrics"]["scoredCount"] = 2
        improved["paperEvidenceLoop"]["counts"]["remainingForPromotion"] = 28
        loads = iter([baseline, improved])

        payload = loop.build_goal_loop(
            command_runner=lambda name, argv, timeout_seconds: {
                "name": name,
                "ok": True,
            },
            artifact_loader=lambda: next(loads),
            state_loader=lambda: {},
            now=NOW,
        )

        self.assertEqual(payload["verdict"], "productive")
        self.assertEqual(payload["valueClass"], "productive")
        self.assertEqual(payload["progressDelta"]["promotionEvidenceDelta"], 1)
        self.assertEqual(payload["progressDelta"]["acceptedProgressPoints"], 100)

    def test_goal_loop_skips_recent_duplicate_when_no_useful_work_is_ready(self) -> None:
        artifacts = safe_artifacts()
        snapshot = loop.progress_snapshot(artifacts, now=NOW)
        signature = loop.work_signature(snapshot, now=NOW)
        state = {
            "runs": [
                {
                    "generatedAt": "2026-06-22T12:30:00-06:00",
                    "workSignature": signature,
                    "verificationPassed": True,
                }
            ]
        }
        calls = []

        payload = loop.build_goal_loop(
            command_runner=lambda name, argv, timeout_seconds: (
                calls.append(name) or {"name": name, "ok": True}
            ),
            artifact_loader=lambda: artifacts,
            state_loader=lambda: state,
            now=NOW,
        )

        self.assertEqual(payload["verdict"], "skipped-duplicate-work")
        self.assertEqual(payload["iterationCount"], 0)
        self.assertEqual(len(calls), len(loop.PRECHECK_COMMANDS))

    def test_state_tracks_productive_rate_and_repeated_blocker(self) -> None:
        payload = loop.build_goal_loop(
            command_runner=lambda name, argv, timeout_seconds: {
                "name": name,
                "ok": True,
            },
            artifact_loader=safe_artifacts,
            state_loader=lambda: {},
            now=NOW,
        )
        prior = {
            "runs": [
                {
                    "generatedAt": "2026-06-22T11:00:00-06:00",
                    "valueClass": "no-op",
                    "progress": {"dominantBlocker": None},
                }
            ]
        }

        state = loop._update_state(payload, existing=prior)

        self.assertEqual(state["version"], 3)
        self.assertEqual(state["rolling10"]["productiveRunRate"], 0.0)
        self.assertEqual(state["rolling10"]["consecutiveNoProgressRuns"], 2)
        self.assertEqual(state["cadence"]["intervalMinutes"], 60)
        self.assertEqual(state["beliefs"][0]["status"], "active")

    def test_adaptive_cadence_exponentially_backs_off_no_progress(self) -> None:
        prior = {
            "runs": [
                {"valueClass": "no-op"},
                {"valueClass": "skipped"},
            ]
        }

        cadence = loop.adaptive_cadence(
            prior,
            value_class="no-op",
            progress={},
            generated_at=NOW,
            minimum_minutes=60,
        )

        self.assertEqual(cadence["noProgressStreak"], 3)
        self.assertEqual(cadence["intervalMinutes"], 240)

    def test_adaptive_gate_uses_state_next_check_and_does_not_extend_on_skip(self) -> None:
        artifacts = safe_artifacts()
        snapshot = loop.progress_snapshot(artifacts, now=NOW)
        signature = loop.work_signature(snapshot, now=NOW)
        next_check = "2026-06-22T17:00:00-06:00"
        state = {
            "cadence": {"nextCheckAt": next_check},
            "runs": [
                {
                    "generatedAt": "2026-06-22T11:00:00-06:00",
                    "workSignature": signature,
                    "verificationPassed": True,
                    "valueClass": "no-op",
                }
            ],
        }

        payload = loop.build_goal_loop(
            command_runner=lambda name, argv, timeout_seconds: {
                "name": name,
                "ok": True,
            },
            artifact_loader=lambda: artifacts,
            state_loader=lambda: state,
            now=NOW,
        )

        self.assertEqual(payload["verdict"], "skipped-duplicate-work")
        self.assertEqual(payload["cadence"]["nextCheckAt"], next_check)
        self.assertIn("do not extend", payload["cadence"]["reason"])

    def test_zero_cooldown_explicitly_bypasses_adaptive_gate(self) -> None:
        artifacts = safe_artifacts()
        snapshot = loop.progress_snapshot(artifacts, now=NOW)
        signature = loop.work_signature(snapshot, now=NOW)
        state = {
            "cadence": {"nextCheckAt": "2026-06-22T17:00:00-06:00"},
            "runs": [
                {
                    "generatedAt": "2026-06-22T12:00:00-06:00",
                    "workSignature": signature,
                    "verificationPassed": True,
                    "valueClass": "no-op",
                }
            ],
        }

        payload = loop.build_goal_loop(
            duplicate_cooldown_minutes=0,
            command_runner=lambda name, argv, timeout_seconds: {
                "name": name,
                "ok": True,
            },
            artifact_loader=lambda: artifacts,
            state_loader=lambda: state,
            now=NOW,
        )

        self.assertEqual(payload["verdict"], "no-op")
        self.assertEqual(payload["iterationCount"], 1)

    def test_belief_consolidation_is_falsifiable(self) -> None:
        runs = [
            {
                "valueClass": "no-op",
                "progressDelta": {"promotionEvidenceDelta": 0},
                "progress": {
                    "dominantBlocker": "approval-missing",
                    "dominantBlockerCount": 10,
                },
            },
            {
                "valueClass": "skipped",
                "progressDelta": {"promotionEvidenceDelta": 0},
                "progress": {
                    "dominantBlocker": "approval-missing",
                    "dominantBlockerCount": 10,
                },
            },
        ]

        beliefs = loop.consolidate_beliefs(runs)

        self.assertEqual(beliefs[0]["status"], "active")
        self.assertIn("falsifier", beliefs[0])
        self.assertEqual(beliefs[-1]["evidenceRuns"], 2)

    def test_knowledge_run_is_plain_markdown_with_structured_properties(self) -> None:
        payload = loop.build_goal_loop(
            command_runner=lambda name, argv, timeout_seconds: {
                "name": name,
                "ok": True,
            },
            artifact_loader=safe_artifacts,
            state_loader=lambda: {},
            now=NOW,
        )
        state = loop._update_state(payload, existing={})
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(loop, "KNOWLEDGE_RUNS_DIR", root / "runs"),
                patch.object(loop, "KNOWLEDGE_LESSONS_DIR", root / "lessons"),
                patch.object(loop, "KNOWLEDGE_CURRENT_FILE", root / "Current Loop State.md"),
                patch.object(loop, "KNOWLEDGE_BELIEFS_FILE", root / "Loop Beliefs.md"),
            ):
                loop._save_knowledge(payload, state)

            current = (root / "Current Loop State.md").read_text(encoding="utf-8")
            beliefs = (root / "Loop Beliefs.md").read_text(encoding="utf-8")
            self.assertIn("type: \"agent-loop-run\"", current)
            self.assertIn("[[Loop Optimization Principles]]", current)
            self.assertIn("live_trading_allowed: false", current)
            self.assertIn("# Loop Beliefs", beliefs)
            self.assertIn("Falsifier:", beliefs)


if __name__ == "__main__":
    unittest.main()
