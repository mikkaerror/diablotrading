from __future__ import annotations

"""Regression tests for the operator daily-loop runner.

Contract:
- the loop is read-only and diagnostic-only
- one failing diagnostic does not abort the loop
- the combined digest tracks step ok/fail counts honestly
- artifact paths are distinct from any operational artifact
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_daily_loop as daily_loop


HEALTHY_CADENCE = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "counts": {"pending": 5, "decideTodayQueue": 1},
    "decideTodayTickers": ["CEG"],
    "oldestPendingSince": "2026-05-10T08:00:00-06:00",
}
HEALTHY_BRIEFS = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "pendingCount": 5,
    "briefs": [{"ticker": "CEG"}, {"ticker": "VNET"}],
}
HEALTHY_GAP = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "overall": {"promotable": False, "gatesOpen": 2, "gatesTotal": 6, "tradesToWinRateFloor": 15},
}
HEALTHY_SENS = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "tightestPromotingProfile": "exploratory",
    "promotedAnyUnder": ["exploratory", "permissive"],
}
HEALTHY_REPLAY = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "closedShadowCount": 10,
    "deskVerdictReplay": {"level": "evidence-building"},
    "promotionCandidatesReplay": [],
}
HEALTHY_SUCCESS = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "verdict": "green",
    "passCount": 5,
    "totalCount": 5,
}
HEALTHY_COMMAND = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "headlineMetrics": {"liveSupported": 2, "liveFragile": 1},
    "activeMissions": [],
    "recentNotes": [],
}
HEALTHY_STABILITY = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "stage": "tos-export-stability-observation-only",
    "verdict": "stable-ready",
    "okCount": 2,
    "attempts": 2,
    "dominantFailMode": "ok-ready-live-readonly",
    "classificationCounts": {},
    "attemptRecords": [],
}
HEALTHY_SKILLS = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "stage": "skills-audit-research-only",
    "verdict": "healthy",
    "totalSkills": 30,
    "counts": {"fresh": 30, "stale": 0, "silent": 0, "unknown": 0},
    "rows": [],
}
HEALTHY_HEARTBEAT = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "stage": "heartbeat-liveness-ledger",
    "verdict": "alive",
    "totalSources": 5,
    "freshCount": 5,
    "staleCount": 0,
    "silentCount": 0,
    "inactiveCount": 0,
    "missingExpected": [],
}
HEALTHY_THEME = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "stage": "theme-synthesizer-research-only",
    "totalCells": 12,
    "sufficientCells": 4,
    "edges": [{"key": "LONG_STRADDLE|bullish-normal|Technology|mid|near"}],
    "antiEdges": [],
}
HEALTHY_HYPOTHESES = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "stage": "hypothesis-lab-research-only",
    "shadowRecordCount": 10,
    "pendingRecordCount": 5,
    "totalHypotheses": 4,
    "edgeCount": 1,
    "antiEdgeCount": 0,
    "templateCounts": {"dimension-edge": 1, "pending-match-edge": 1, "insufficient-but-trending": 2},
    "topHypotheses": [
        {
            "id": "dimension-edge:LONG_STRADDLE|bullish-normal|Technology|mid|near",
            "template": "dimension-edge",
            "claim": "Cell LONG_STRADDLE|bullish-normal shows a positive edge.",
            "testConfidence": 0.74,
        }
    ],
    "allHypotheses": [
        {
            "id": "dimension-edge:LONG_STRADDLE|bullish-normal|Technology|mid|near",
            "template": "dimension-edge",
            "stats": {"winRateLower": 0.48},
            "testConfidence": 0.74,
        }
    ],
}
HEALTHY_LEDGER = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "stage": "hypothesis-ledger-research-only",
    "totalHypotheses": 7,
    "trajectoryCounts": {"strengthening": 2, "weakening": 1, "stable": 3, "new": 1, "abandoned": 0},
}
HEALTHY_COUNTERFACTUAL = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "stage": "counterfactual-replay-research-only",
    "verdict": "ranked",
    "closedRecordCount": 7,
    "rankings": {
        "bestByMeanR": "edge-only",
        "bestByWilsonLower": "edge-only",
        "bestByProfitFactor": "iv-cheap",
        "bestByDrawdown": "conservative",
    },
    "policies": [],
}
HEALTHY_CONVICTION_RESEARCH = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "stage": "conviction-research-only",
    "researchOnly": True,
    "promotable": False,
    "behemoths": [{"ticker": "NVDA"}, {"ticker": "AVGO"}],
    "sleepers": [{"ticker": "MOD"}],
    "nearTermWinners": [{"ticker": "MRVL"}],
    "bestBalanced": [{"ticker": "NVDA"}, {"ticker": "MOD"}],
}
HEALTHY_FALSIFICATION = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "stage": "devils-advocate-falsification",
    "verdict": "watch",
    "signFlipRisk": "normal",
}
HEALTHY_EVIDENCE_STRENGTH = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "stage": "evidence-strength-scalar",
    "verdict": "evidence-building",
    "compositeStrength": 0.42,
}
HEALTHY_CYCLE_JOURNAL = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "stage": "brain-cycle-journal-research-only",
    "cycleId": "2026-05-10-0800",
    "cycleDirectory": "/tmp/cycles/2026-05-10-0800",
    "copied": ["daily_loop.json"],
    "missing": [],
    "pruned": [],
    "totalCyclesOnDisk": 1,
    "maxCycles": 90,
}


def patch_all_builders(*, fail: str | None = None):
    """Patch the daily-loop module's chained builders with healthy stubs.

    Pass ``fail`` to make one builder raise, simulating an isolated failure.
    """
    payloads = {
        "build_cadence": HEALTHY_CADENCE,
        "build_decision_briefs": HEALTHY_BRIEFS,
        "build_promotion_gap": HEALTHY_GAP,
        "build_sensitivity": HEALTHY_SENS,
        "build_replay": HEALTHY_REPLAY,
        "build_daily_success": HEALTHY_SUCCESS,
        "build_command_center": HEALTHY_COMMAND,
        "build_stability_report": HEALTHY_STABILITY,
        "build_skills_audit": HEALTHY_SKILLS,
        "build_heartbeat_report": HEALTHY_HEARTBEAT,
        "build_theme_report": HEALTHY_THEME,
        "build_hypothesis_lab": HEALTHY_HYPOTHESES,
        "build_ledger_report": HEALTHY_LEDGER,
        "build_counterfactual": HEALTHY_COUNTERFACTUAL,
        "build_conviction_research": HEALTHY_CONVICTION_RESEARCH,
        "build_falsification": HEALTHY_FALSIFICATION,
        "build_evidence_strength": HEALTHY_EVIDENCE_STRENGTH,
        "snapshot_cycle": HEALTHY_CYCLE_JOURNAL,
    }
    savers = ["save_cadence", "save_decision_briefs", "save_promotion_gap",
              "save_sensitivity", "save_replay", "save_daily_success",
              "save_stability_report", "save_skills_audit", "save_heartbeat_report",
              "save_theme_report", "save_hypothesis_lab", "save_ledger_report",
              "save_counterfactual", "save_conviction_research",
              "save_falsification", "save_evidence_strength",
              "save_journal_memo"]
    patches = []
    for name, payload in payloads.items():
        if name == fail:
            patches.append(patch.object(daily_loop, name, side_effect=RuntimeError("boom")))
        else:
            patches.append(patch.object(daily_loop, name, return_value=payload))
    for saver in savers:
        patches.append(patch.object(daily_loop, saver))
    # Heartbeat recording and the ledger update are side-effects, not builders.
    patches.append(patch.object(daily_loop, "record_heartbeat"))
    patches.append(patch.object(daily_loop, "update_ledger"))
    # Narration log is a side-effect at the end of the digest assembly;
    # stub it so tests don't touch the real data/ directory.
    patches.append(patch.object(daily_loop, "_append_narration_row"))
    return patches


class DailyLoopTests(unittest.TestCase):
    """Verify the loop chains diagnostics with failure isolation."""

    def test_artifact_paths_are_distinct(self) -> None:
        self.assertTrue(str(daily_loop.DAILY_LOOP_FILE).endswith("inferno_daily_loop.json"))
        self.assertTrue(str(daily_loop.DAILY_LOOP_TEXT_FILE).endswith("daily_loop_latest.txt"))
        self.assertEqual(daily_loop.DAILY_LOOP_STAGE, "daily-loop-operator-routine")

    def test_healthy_loop_reports_all_ok(self) -> None:
        patches = patch_all_builders()
        for p in patches:
            p.start()
        try:
            payload = daily_loop.build_daily_loop()
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(payload["okCount"], len(payload["steps"]))
        self.assertEqual(payload["failedCount"], 0)
        self.assertEqual(payload["deskVerdict"], "green")
        self.assertEqual(payload["decideTodayTickers"], ["CEG"])
        self.assertTrue(payload["diagnosticOnly"])
        # Narrative must reflect the thinking + breathing layers.
        self.assertIn("narrative", payload)
        self.assertIn("Desk verdict: GREEN", payload["narrative"])
        self.assertIn("CEG", payload["narrative"])
        self.assertIn("hypotheses", payload["narrative"].lower())

    def test_one_failing_step_does_not_abort_loop(self) -> None:
        patches = patch_all_builders(fail="build_promotion_gap")
        for p in patches:
            p.start()
        try:
            payload = daily_loop.build_daily_loop()
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(payload["failedCount"], 1)
        self.assertEqual(payload["okCount"], len(payload["steps"]) - 1)
        failed = next(step for step in payload["steps"] if step["name"] == "promotionGap")
        self.assertFalse(failed["ok"])
        self.assertIn("RuntimeError: boom", failed["error"])

    def test_loop_payload_is_diagnostic_only(self) -> None:
        patches = patch_all_builders()
        for p in patches:
            p.start()
        try:
            payload = daily_loop.build_daily_loop()
        finally:
            for p in patches:
                p.stop()
        self.assertTrue(payload["diagnosticOnly"])

    def test_text_render_lists_each_step(self) -> None:
        patches = patch_all_builders()
        for p in patches:
            p.start()
        try:
            payload = daily_loop.build_daily_loop()
        finally:
            for p in patches:
                p.stop()
        text = daily_loop.daily_loop_text(payload)
        for step_name in ("approvalCadence", "decisionBriefs", "promotionGap",
                          "thresholdSensitivity", "strategyReplay", "dailySuccess",
                          "tosExportStability", "skillsAudit", "heartbeat",
                          "themeSynthesizer", "hypothesisLab", "hypothesisLedger",
                          "counterfactual", "devilsAdvocate", "evidenceStrength",
                          "convictionResearch", "commandCenter", "cycleJournal"):
            self.assertIn(step_name, text)
        self.assertIn("Narrative:", text)
        self.assertIn("Watch the brain operate", text)

    def test_save_writes_both_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            json_path = tmp_root / "loop.json"
            text_path = tmp_root / "loop.txt"
            with (
                patch.object(daily_loop, "DAILY_LOOP_FILE", json_path),
                patch.object(daily_loop, "DAILY_LOOP_TEXT_FILE", text_path),
                patch.object(daily_loop, "ensure_dirs"),
            ):
                daily_loop.save_daily_loop({
                    "generatedAt": "2026-05-10T08:00:00-06:00",
                    "stage": daily_loop.DAILY_LOOP_STAGE,
                    "diagnosticOnly": True,
                    "deskVerdict": "green",
                    "decideTodayTickers": [],
                    "steps": [],
                    "stepCount": 0,
                    "okCount": 0,
                    "failedCount": 0,
                })
            self.assertTrue(json_path.exists())
            self.assertTrue(text_path.exists())
            written = json.loads(json_path.read_text())
            self.assertTrue(written["diagnosticOnly"])


class ComposeNarrativeTests(unittest.TestCase):
    """The narrative paragraphs should read what the diagnostics show."""

    def test_healthy_narrative_mentions_decide_today(self) -> None:
        narrative = daily_loop.compose_narrative(
            success_payload=HEALTHY_SUCCESS,
            cadence_payload=HEALTHY_CADENCE,
            gap_payload=HEALTHY_GAP,
            replay_payload=HEALTHY_REPLAY,
            stability_payload=HEALTHY_STABILITY,
            skills_payload=HEALTHY_SKILLS,
            heartbeat_payload=HEALTHY_HEARTBEAT,
            theme_payload=HEALTHY_THEME,
            hypothesis_payload=HEALTHY_HYPOTHESES,
            ledger_payload=HEALTHY_LEDGER,
            counterfactual_payload=HEALTHY_COUNTERFACTUAL,
        )
        self.assertIn("CEG", narrative)
        self.assertIn("stable", narrative.lower())
        self.assertIn("fresh artifacts", narrative.lower())

    def test_silent_subsystem_surfaces_in_narrative(self) -> None:
        heartbeat = {**HEALTHY_HEARTBEAT, "verdict": "silent", "silentCount": 2,
                     "missingExpected": ["dawn_cycle"]}
        narrative = daily_loop.compose_narrative(
            success_payload=HEALTHY_SUCCESS,
            cadence_payload=HEALTHY_CADENCE,
            gap_payload=HEALTHY_GAP,
            replay_payload=HEALTHY_REPLAY,
            stability_payload=HEALTHY_STABILITY,
            skills_payload=HEALTHY_SKILLS,
            heartbeat_payload=heartbeat,
        )
        self.assertIn("dawn_cycle", narrative)

    def test_blocked_tos_surfaces_in_narrative(self) -> None:
        stability = {**HEALTHY_STABILITY, "verdict": "blocked",
                     "dominantFailMode": "tos-not-running"}
        narrative = daily_loop.compose_narrative(
            success_payload=HEALTHY_SUCCESS,
            cadence_payload=HEALTHY_CADENCE,
            gap_payload=HEALTHY_GAP,
            replay_payload=HEALTHY_REPLAY,
            stability_payload=stability,
            skills_payload=HEALTHY_SKILLS,
            heartbeat_payload=HEALTHY_HEARTBEAT,
        )
        self.assertIn("tos-not-running", narrative)
        self.assertIn("blocked", narrative.lower())


if __name__ == "__main__":
    unittest.main()
