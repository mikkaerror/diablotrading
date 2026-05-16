from __future__ import annotations

"""Regression tests for the brain console.

The console must:
- read existing artifacts and produce a structured snapshot
- never mutate desk state
- gracefully handle missing or unreadable artifact files
- emit the same shape under --json that the text renderer consumes
- flag stale or missing artifacts in the output
"""

import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import inferno_brain_console as console


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class BrainConsoleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data_dir = self.root / "data"
        self.reports_dir = self.root / "reports"
        self.data_dir.mkdir()
        self.reports_dir.mkdir()
        # Rewrite the module's ARTIFACT_PATHS map to point at the tmp dir.
        patcher = mock.patch.dict(
            console.ARTIFACT_PATHS,
            {name: self.data_dir / Path(path).name
             for name, path in console.ARTIFACT_PATHS.items()},
            clear=True,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_empty_state_does_not_crash(self) -> None:
        state = console.build_console_state(now=datetime(2026, 5, 11, 7, 0, 0))
        self.assertEqual(state["deskVerdict"], "unknown")
        self.assertEqual(state["decideToday"], [])
        # All artifacts should be flagged missing.
        for meta in state["artifactFreshness"].values():
            self.assertTrue(meta["missing"])

    def test_full_state_pulls_from_each_artifact(self) -> None:
        now = datetime(2026, 5, 11, 7, 0, 0)
        _write_json(self.data_dir / "inferno_daily_loop.json", {
            "deskVerdict": "green",
            "decideTodayTickers": ["CEG"],
            "narrative": "Desk verdict: GREEN.",
        })
        _write_json(self.data_dir / "inferno_approval_cadence.json", {
            "counts": {"pending": 5, "decideTodayQueue": 1},
        })
        _write_json(self.data_dir / "inferno_hypothesis_lab.json", {
            "totalHypotheses": 7,
            "edgeCount": 1,
            "antiEdgeCount": 0,
            "topHypotheses": [{
                "id": "dimension-edge:LONG_STRADDLE",
                "template": "dimension-edge",
                "claim": "edge",
                "testConfidence": 0.7,
                "stats": {"winRate": 0.86, "winRateLower": 0.49, "sampleSize": 7},
                "suggestedAction": "tighten-filter-to-cell",
            }],
        })
        _write_json(self.data_dir / "inferno_hypothesis_ledger.json", {
            "trajectoryCounts": {"strengthening": 2, "weakening": 1, "stable": 3},
        })
        _write_json(self.data_dir / "inferno_theme_synthesizer.json", {
            "totalCells": 12,
            "sufficientCells": 4,
            "edges": [{"key": "x"}],
            "antiEdges": [],
        })
        _write_json(self.data_dir / "inferno_heartbeat.json", {
            "verdict": "alive", "freshCount": 5, "totalSources": 5, "missingExpected": [],
        })
        _write_json(self.data_dir / "inferno_tos_export_stability.json", {
            "verdict": "stable-ready", "dominantFailMode": "ok-ready-live-readonly",
        })
        _write_json(self.data_dir / "inferno_skills_audit.json", {
            "verdict": "healthy", "counts": {"fresh": 30, "stale": 0, "silent": 0},
        })
        _write_json(self.data_dir / "inferno_daily_success.json", {
            "verdict": "green", "passCount": 5, "totalCount": 5,
        })

        state = console.build_console_state(now=now)
        self.assertEqual(state["deskVerdict"], "green")
        self.assertEqual(state["decideToday"], ["CEG"])
        self.assertEqual(state["hypothesisCounts"]["total"], 7)
        self.assertEqual(state["ledgerTrajectory"]["strengthening"], 2)
        self.assertEqual(state["themeCells"]["edges"], 1)
        self.assertEqual(state["breathing"]["heartbeatVerdict"], "alive")
        self.assertEqual(state["scorecard"]["verdict"], "green")
        self.assertEqual(len(state["topHypotheses"]), 1)

    def test_stale_artifact_is_flagged(self) -> None:
        _write_json(self.data_dir / "inferno_daily_loop.json", {"deskVerdict": "green"})
        # Manually set the file's mtime to 24 hours ago.
        import os, time
        old = time.time() - 24 * 3600
        os.utime(self.data_dir / "inferno_daily_loop.json", (old, old))

        state = console.build_console_state(now=datetime.now())
        self.assertTrue(state["artifactFreshness"]["dailyLoop"]["stale"])

    def test_authority_reads_from_nested_decision(self) -> None:
        _write_json(self.data_dir / "inferno_authority_manifest.json", {
            "generatedAt": "2026-05-10T22:06:58-06:00",
            "stage": "automation-authority-control",
            "decision": {
                "authorityLevel": "paper-evidence-only",
                "brokerSubmitAllowed": False,
                "liveTradingAllowed": False,
            },
        })
        state = console.build_console_state(now=datetime(2026, 5, 11, 22, 30, 0))
        self.assertEqual(state["authority"]["level"], "paper-evidence-only")
        self.assertEqual(state["authority"]["brokerSubmitAllowed"], False)
        self.assertEqual(state["authority"]["liveTradingAllowed"], False)

    def test_low_frequency_artifact_is_not_flagged_stale(self) -> None:
        # Write an authority manifest and age it well past the staleness
        # threshold. It should NOT show up as stale.
        path = self.data_dir / "inferno_authority_manifest.json"
        _write_json(path, {"decision": {"authorityLevel": "paper-evidence-only"}})
        import os, time
        ancient = time.time() - 48 * 3600
        os.utime(path, (ancient, ancient))

        state = console.build_console_state(now=datetime.now())
        self.assertFalse(state["artifactFreshness"]["authority"]["stale"])
        self.assertTrue(state["artifactFreshness"]["authority"]["lowFrequency"])

    def test_render_console_is_readable(self) -> None:
        state = console.build_console_state(now=datetime(2026, 5, 11, 7, 0, 0))
        text = console.render_console(state)
        self.assertIn("INFERNO BRAIN CONSOLE", text)
        self.assertIn("Desk verdict", text)
        self.assertIn("TOP HYPOTHESES", text)
        self.assertIn("BREATHING", text)


if __name__ == "__main__":
    unittest.main()
