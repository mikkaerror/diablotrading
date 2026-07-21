from __future__ import annotations

"""Regression tests for the central heartbeat ledger."""

import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import inferno_heartbeat


class HeartbeatRecordTests(unittest.TestCase):
    """``record_heartbeat`` should append, prune, and stay atomic."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._data_dir = Path(self._tmp.name) / "data"
        self._reports_dir = Path(self._tmp.name) / "reports"
        self._data_dir.mkdir()
        self._reports_dir.mkdir()
        self._artifact = self._data_dir / "inferno_heartbeat.json"
        self._text = self._reports_dir / "heartbeat_latest.txt"

        patcher = mock.patch.multiple(
            inferno_heartbeat,
            HEARTBEAT_ARTIFACT_FILE=self._artifact,
            HEARTBEAT_TEXT_FILE=self._text,
            ensure_dirs=lambda: None,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_record_persists_a_row_with_normalized_status(self) -> None:
        record = inferno_heartbeat.record_heartbeat(
            "dawn_cycle", status="OK", summary="morning brief sent"
        )
        self.assertEqual(record["status"], "ok")
        on_disk = json.loads(self._artifact.read_text())
        self.assertEqual(len(on_disk["records"]), 1)
        self.assertEqual(on_disk["records"][0]["source"], "dawn_cycle")

    def test_record_rejects_empty_source(self) -> None:
        with self.assertRaises(ValueError):
            inferno_heartbeat.record_heartbeat("")

    def test_record_prunes_per_source(self) -> None:
        with mock.patch.object(inferno_heartbeat, "MAX_RECORDS_PER_SOURCE", 3):
            for index in range(6):
                inferno_heartbeat.record_heartbeat(
                    "ops_maintenance",
                    status="ok",
                    summary=f"sweep #{index}",
                )
        on_disk = json.loads(self._artifact.read_text())
        rows = [r for r in on_disk["records"] if r["source"] == "ops_maintenance"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]["summary"], "sweep #5")


class HeartbeatBuildReportTests(unittest.TestCase):
    """``build_heartbeat_report`` should classify by age + missing expected."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._data_dir = Path(self._tmp.name) / "data"
        self._data_dir.mkdir()
        self._artifact = self._data_dir / "inferno_heartbeat.json"

        patcher = mock.patch.object(inferno_heartbeat, "HEARTBEAT_ARTIFACT_FILE", self._artifact)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _seed(self, records: list[dict]) -> None:
        self._artifact.write_text(json.dumps({"records": records}))

    def test_empty_ledger_with_expected_yields_silent_verdict(self) -> None:
        self._seed([])
        report = inferno_heartbeat.build_heartbeat_report(
            expected_sources=["dawn_cycle"],
            now=datetime(2026, 5, 10, 12, 0, 0),
        )
        self.assertEqual(report["verdict"], "silent")
        self.assertEqual(report["missingExpected"], ["dawn_cycle"])

    def test_fresh_record_yields_alive_verdict(self) -> None:
        now = datetime(2026, 5, 10, 12, 0, 0)
        self._seed([
            {
                "source": "dawn_cycle",
                "status": "ok",
                "summary": "fresh",
                "at": (now - timedelta(hours=1)).isoformat(),
            }
        ])
        report = inferno_heartbeat.build_heartbeat_report(
            expected_sources=["dawn_cycle"], now=now
        )
        self.assertEqual(report["verdict"], "alive")
        self.assertEqual(report["freshCount"], 1)

    def test_stale_record_yields_stale_verdict(self) -> None:
        now = datetime(2026, 5, 10, 12, 0, 0)
        stale_at = now - timedelta(hours=inferno_heartbeat.STALE_AFTER_HOURS + 1)
        self._seed([
            {
                "source": "dawn_cycle",
                "status": "ok",
                "summary": "stale",
                "at": stale_at.isoformat(),
            }
        ])
        report = inferno_heartbeat.build_heartbeat_report(
            expected_sources=["dawn_cycle"], now=now
        )
        self.assertEqual(report["verdict"], "stale")
        self.assertEqual(report["staleCount"], 1)

    def test_silent_record_overrides_stale(self) -> None:
        now = datetime(2026, 5, 10, 12, 0, 0)
        silent_at = now - timedelta(hours=inferno_heartbeat.SILENT_AFTER_HOURS + 1)
        stale_at = now - timedelta(hours=inferno_heartbeat.STALE_AFTER_HOURS + 1)
        self._seed([
            {"source": "a", "status": "ok", "summary": "", "at": silent_at.isoformat()},
            {"source": "b", "status": "ok", "summary": "", "at": stale_at.isoformat()},
        ])
        report = inferno_heartbeat.build_heartbeat_report(now=now)
        self.assertEqual(report["verdict"], "silent")
        self.assertEqual(report["silentCount"], 1)
        self.assertEqual(report["staleCount"], 1)

    def test_inactive_record_is_separated_from_silent(self) -> None:
        now = datetime(2026, 5, 10, 12, 0, 0)
        old = now - timedelta(hours=100)
        self._seed([
            {"source": "weekend", "status": "inactive", "summary": "", "at": old.isoformat()},
        ])
        report = inferno_heartbeat.build_heartbeat_report(now=now)
        self.assertEqual(report["inactiveCount"], 1)
        self.assertEqual(report["silentCount"], 0)

    def test_optional_stale_source_does_not_override_scheduled_liveness(self) -> None:
        now = datetime(2026, 5, 10, 12, 0, 0)
        self._seed([
            {
                "source": "daily_loop",
                "status": "ok",
                "summary": "fresh",
                "at": (now - timedelta(hours=1)).isoformat(),
            },
            {
                "source": "tos_session_probe",
                "status": "warn",
                "summary": "manual attach-only probe",
                "at": (now - timedelta(hours=100)).isoformat(),
            },
        ])

        report = inferno_heartbeat.build_heartbeat_report(
            expected_sources=["daily_loop"], now=now
        )

        self.assertEqual(report["verdict"], "alive")
        self.assertEqual(report["silentCount"], 1)
        self.assertEqual(report["expectedSilentSources"], [])

    def test_expected_stale_source_sets_stale_verdict(self) -> None:
        now = datetime(2026, 5, 10, 12, 0, 0)
        self._seed([
            {
                "source": "daily_loop",
                "status": "ok",
                "summary": "stale",
                "at": (now - timedelta(hours=48)).isoformat(),
            },
        ])

        report = inferno_heartbeat.build_heartbeat_report(
            expected_sources=["daily_loop"], now=now
        )

        self.assertEqual(report["verdict"], "stale")
        self.assertEqual(report["expectedStaleSources"], ["daily_loop"])

    def test_default_schedule_excludes_manual_tos_probe(self) -> None:
        self.assertNotIn("tos_session_probe", inferno_heartbeat.default_expected_sources())

    def test_empty_schedule_keeps_whole_ledger_diagnostic_behavior(self) -> None:
        now = datetime(2026, 5, 10, 12, 0, 0)
        self._seed([
            {
                "source": "manual_probe",
                "status": "warn",
                "summary": "stale",
                "at": (now - timedelta(hours=100)).isoformat(),
            },
        ])

        report = inferno_heartbeat.build_heartbeat_report(
            expected_sources=[], now=now
        )

        self.assertEqual(report["verdict"], "silent")

    def test_text_explains_scheduled_verdict_scope(self) -> None:
        payload = {
            "generatedAt": "2026-05-10T12:00:00",
            "verdict": "alive",
            "totalSources": 2,
            "freshCount": 1,
            "staleCount": 0,
            "silentCount": 1,
            "inactiveCount": 0,
            "staleAfterHours": 36,
            "silentAfterHours": 96,
            "expectedSources": ["daily_loop"],
            "expectedStaleSources": [],
            "expectedSilentSources": [],
            "missingExpected": [],
        }

        rendered = inferno_heartbeat.heartbeat_text(payload)

        self.assertIn("Scheduled verdict scope: daily_loop", rendered)
        self.assertIn("Scheduled issues: stale 0 | silent 0 | missing 0", rendered)


if __name__ == "__main__":
    unittest.main()
