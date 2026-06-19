from __future__ import annotations

"""Regression tests for the night-prep diagnostic.

Contract:
- researchOnly / promotable hard-pinned
- ready verdict when every check passes
- blocked verdict when any check fails
- warming verdict when only warnings are present
- readyForMorning is False iff there's at least one FAIL
"""

import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import inferno_night_prep as np


def _seed_artifact(path: Path, age_hours: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    import os
    import time
    when = time.time() - age_hours * 3600
    os.utime(path, (when, when))


class NightPrepTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data_dir = self.root / "data"
        self.reports_dir = self.root / "reports"
        self.data_dir.mkdir()
        self.reports_dir.mkdir()
        (self.data_dir / "cycles").mkdir()
        # Point the module's expected artifact paths at the tmp data dir.
        patches = [
            mock.patch.object(np, "DATA_DIR", self.data_dir),
            mock.patch.object(np, "REPORTS_DIR", self.reports_dir),
            mock.patch.object(np, "NIGHT_PREP_ARTIFACT_FILE", self.data_dir / "inferno_night_prep.json"),
            mock.patch.object(np, "NIGHT_PREP_TEXT_FILE", self.reports_dir / "night_prep_latest.txt"),
            mock.patch.object(np, "WATCHLIST_INPUT_FILE", self.data_dir / "inferno_watchlist_input.json"),
            mock.patch.object(np, "SCHWAB_OPTIONS_FILE", self.data_dir / "inferno_schwab_options.json"),
            mock.patch.object(np, "TOS_STABILITY_FILE", self.data_dir / "inferno_tos_export_stability.json"),
            mock.patch.object(np, "EXPECTED_FRESH_ARTIFACTS", (
                ("recent_doctor", self.data_dir / "inferno_doctor.json"),
                ("recent_ops_maintenance", self.data_dir / "inferno_ops_maintenance.json"),
                ("recent_daily_loop", self.data_dir / "inferno_daily_loop.json"),
            )),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _all_agents_loaded(self, _label: str) -> tuple[bool, str]:
        return True, "agent loaded"

    def _no_agents_loaded(self, _label: str) -> tuple[bool, str]:
        return False, "agent not loaded"

    def _seed_happy_path(self) -> None:
        # Agents we stub via launchctl callback; artifacts we seed.
        for path in (
            self.data_dir / "inferno_doctor.json",
            self.data_dir / "inferno_ops_maintenance.json",
            self.data_dir / "inferno_daily_loop.json",
            self.data_dir / "inferno_tos_export_chain.json",
            self.data_dir / "inferno_brain_narrations.jsonl",
        ):
            _seed_artifact(path, age_hours=1.0)
        (self.data_dir / "cycles" / "2026-05-11-2300").mkdir()
        # Authority manifest with the canonical pinned posture.
        (self.data_dir / "inferno_authority_manifest.json").write_text(
            json.dumps({
                "decision": {
                    "authorityLevel": "paper-evidence-only",
                    "brokerSubmitAllowed": False,
                    "liveTradingAllowed": False,
                }
            }),
            encoding="utf-8",
        )
        # TOS chain artifact reports ready.
        (self.data_dir / "inferno_tos_export_chain.json").write_text(
            json.dumps({"verdict": "ready"}), encoding="utf-8"
        )
        # Schwab/TOS source posture artifacts are present and clean.
        (self.data_dir / "inferno_schwab_options.json").write_text(
            json.dumps({
                "status": "ok",
                "configured": True,
                "rows": [{"symbol": "NVDA", "quoteQualityScore": 88}],
                "errors": [],
            }),
            encoding="utf-8",
        )
        (self.data_dir / "inferno_tos_export_stability.json").write_text(
            json.dumps({
                "verdict": "stable-ready",
                "dominantFailMode": "ok-ready-live-readonly",
                "okCount": 3,
                "attempts": 3,
            }),
            encoding="utf-8",
        )
        # Narration log has one row.
        (self.data_dir / "inferno_brain_narrations.jsonl").write_text(
            '{"at":"2026-05-11T22:00:00","verdict":"green"}\n', encoding="utf-8"
        )
        # Operator has pre-populated the watchlist input slot.
        (self.data_dir / "inferno_watchlist_input.json").write_text(
            json.dumps({"tickers": []}), encoding="utf-8"
        )

    def test_research_only_contract(self) -> None:
        payload = np.build_night_prep(launchctl=self._all_agents_loaded)
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertEqual(payload["stage"], np.NIGHT_PREP_STAGE)

    def test_happy_path_reports_ready(self) -> None:
        self._seed_happy_path()
        payload = np.build_night_prep(launchctl=self._all_agents_loaded)
        self.assertEqual(payload["verdict"], "ready")
        self.assertTrue(payload["readyForMorning"])
        self.assertEqual(payload["failCount"], 0)
        self.assertIsNotNone(payload["nextMarketSession"])
        self.assertTrue(payload["dataSourcePosture"]["schwabOptionsReady"])
        self.assertTrue(payload["dataSourcePosture"]["tosCaptureReady"])

    def test_agent_not_loaded_yields_blocked(self) -> None:
        self._seed_happy_path()
        payload = np.build_night_prep(launchctl=self._no_agents_loaded)
        self.assertEqual(payload["verdict"], "blocked")
        self.assertFalse(payload["readyForMorning"])
        self.assertGreater(payload["failCount"], 0)

    def test_missing_artifact_yields_blocked(self) -> None:
        self._seed_happy_path()
        (self.data_dir / "inferno_doctor.json").unlink()
        payload = np.build_night_prep(launchctl=self._all_agents_loaded)
        self.assertFalse(payload["readyForMorning"])

    def test_stale_artifact_is_a_warn_not_a_fail(self) -> None:
        self._seed_happy_path()
        _seed_artifact(self.data_dir / "inferno_doctor.json", age_hours=48.0)
        payload = np.build_night_prep(launchctl=self._all_agents_loaded)
        # Should still be ready for morning; staleness only warns.
        self.assertTrue(payload["readyForMorning"])
        self.assertEqual(payload["verdict"], "warming")
        self.assertGreater(payload["warnCount"], 0)

    def test_authority_drift_yields_blocked(self) -> None:
        self._seed_happy_path()
        (self.data_dir / "inferno_authority_manifest.json").write_text(
            json.dumps({"decision": {
                "authorityLevel": "paper-evidence-only",
                "brokerSubmitAllowed": True,
                "liveTradingAllowed": False,
            }}),
            encoding="utf-8",
        )
        payload = np.build_night_prep(launchctl=self._all_agents_loaded)
        self.assertFalse(payload["readyForMorning"])
        authority = next(c for c in payload["checks"] if c["name"] == "authority_pinned")
        self.assertEqual(authority["status"], "fail")

    def test_watchlist_slot_missing_is_warn_not_fail(self) -> None:
        self._seed_happy_path()
        # Specifically remove the slot so we can verify the warn behaviour.
        (self.data_dir / "inferno_watchlist_input.json").unlink()
        payload = np.build_night_prep(launchctl=self._all_agents_loaded)
        slot = next(c for c in payload["checks"] if c["name"] == "watchlist_slot_ready")
        self.assertEqual(slot["status"], "warn")
        self.assertTrue(payload["readyForMorning"])

    def test_pending_schwab_is_warn_not_fail(self) -> None:
        self._seed_happy_path()
        (self.data_dir / "inferno_schwab_options.json").write_text(
            json.dumps({"status": "not-configured", "configured": False, "rows": []}),
            encoding="utf-8",
        )
        payload = np.build_night_prep(launchctl=self._all_agents_loaded)
        schwab = next(c for c in payload["checks"] if c["name"] == "schwab_options_source")
        self.assertEqual(schwab["status"], "warn")
        self.assertTrue(payload["readyForMorning"])
        self.assertFalse(payload["dataSourcePosture"]["schwabOptionsReady"])

    def test_tos_inactive_safe_keeps_overnight_math_ready(self) -> None:
        self._seed_happy_path()
        (self.data_dir / "inferno_tos_export_stability.json").write_text(
            json.dumps({
                "verdict": "inactive-safe",
                "dominantFailMode": "tos-closed-low-power",
                "okCount": 0,
                "attempts": 3,
            }),
            encoding="utf-8",
        )
        payload = np.build_night_prep(launchctl=self._all_agents_loaded)
        tos = next(c for c in payload["checks"] if c["name"] == "tos_capture_posture")
        self.assertEqual(tos["status"], "pass")
        self.assertTrue(payload["readyForMorning"])
        self.assertFalse(payload["dataSourcePosture"]["tosCaptureReady"])
        self.assertTrue(payload["dataSourcePosture"]["overnightMathReady"])

    def test_text_renderer_includes_each_section(self) -> None:
        self._seed_happy_path()
        payload = np.build_night_prep(launchctl=self._all_agents_loaded)
        rendered = np.night_prep_text(payload)
        self.assertIn("Night Prep", rendered)
        self.assertIn("Verdict:", rendered)
        self.assertIn("Next market session:", rendered)
        self.assertIn("Data source posture:", rendered)
        self.assertIn("Checks:", rendered)
        self.assertIn("Reminders:", rendered)


if __name__ == "__main__":
    unittest.main()
