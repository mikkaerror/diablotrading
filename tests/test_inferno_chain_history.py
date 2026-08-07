from __future__ import annotations

"""Regression tests for immutable local Schwab chain-history collection."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import inferno_chain_history as history


NOW = datetime.fromisoformat("2026-08-06T23:00:00-06:00")


def source_report(*, generated_at: str = "2026-08-06T16:20:00-06:00", **overrides: object) -> dict:
    report = {
        "stage": "schwab-options-read-only",
        "status": "ok",
        "generatedAt": generated_at,
        "researchOnly": True,
        "authorityChanged": False,
        "symbolCount": 1,
        "rows": [
            {
                "symbol": "ORCL",
                "status": "ok",
                "atmImpliedVolatility": 0.31,
                "atmImpliedMovePct": 0.04,
                "contracts": [{"symbol": "ORCL  260821C00100000", "mid": 1.25}],
            }
        ],
    }
    report.update(overrides)
    return report


class ChainHistoryTests(unittest.TestCase):
    """Pin the research-only and immutable daily snapshot contract."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.data_dir = root / "data"
        self.history_file = self.data_dir / "inferno_chain_history.json"
        self.manifest_file = self.data_dir / "inferno_chain_history_manifest.json"
        self.history_root = self.data_dir / "chain_history"
        self.hot_dir = self.history_root / "hot"
        self.archive_dir = self.history_root / "archive"
        self.text_file = root / "reports" / "chain_history_latest.txt"
        self.patches = [
            patch.object(history, "DATA_DIR", self.data_dir),
            patch.object(history, "CHAIN_HISTORY_FILE", self.history_file),
            patch.object(history, "CHAIN_HISTORY_MANIFEST_FILE", self.manifest_file),
            patch.object(history, "CHAIN_HISTORY_ROOT", self.history_root),
            patch.object(history, "CHAIN_HISTORY_HOT_DIR", self.hot_dir),
            patch.object(history, "CHAIN_HISTORY_ARCHIVE_DIR", self.archive_dir),
            patch.object(history, "CHAIN_HISTORY_TEXT_FILE", self.text_file),
            patch.object(history, "SCHWAB_OPTIONS_FILE", self.data_dir / "inferno_schwab_options.json"),
        ]
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self) -> None:
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.temp_dir.cleanup()

    def test_records_one_immutable_research_only_snapshot(self) -> None:
        payload, manifest = history.build_chain_history(source_report=source_report(), now=NOW)

        self.assertEqual(payload["capture"]["status"], "history-captured")
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["brokerSubmitAllowed"])
        self.assertFalse(payload["liveTradingAllowed"])
        self.assertEqual(payload["readiness"]["recordedDays"], 1)
        descriptor = manifest["hotSnapshots"][0]
        path = self.data_dir / descriptor["path"]
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["rows"][0]["symbol"], "ORCL")
        self.assertFalse(saved["authorityChanged"])

    def test_same_source_date_is_not_rewritten(self) -> None:
        first, manifest = history.build_chain_history(source_report=source_report(), now=NOW)
        self.assertEqual(first["capture"]["status"], "history-captured")
        second, updated = history.build_chain_history(
            source_report=source_report(),
            manifest=manifest,
            now=NOW.replace(hour=23, minute=30),
        )

        self.assertEqual(second["capture"]["status"], "history-unchanged")
        self.assertEqual(len(updated["hotSnapshots"]), 1)

    def test_recovers_intact_unindexed_snapshot_without_rewriting_it(self) -> None:
        first, _ = history.build_chain_history(source_report=source_report(), now=NOW)
        snapshot_path = self.hot_dir / "2026-08-06.json"
        original = snapshot_path.read_text(encoding="utf-8")

        recovered, manifest = history.build_chain_history(source_report=source_report(), now=NOW)

        self.assertEqual(first["capture"]["status"], "history-captured")
        self.assertEqual(recovered["capture"]["status"], "history-recovered")
        self.assertEqual(snapshot_path.read_text(encoding="utf-8"), original)
        self.assertEqual(len(manifest["hotSnapshots"]), 1)

    def test_rejects_partial_or_unsafe_source_without_snapshot(self) -> None:
        payload, manifest = history.build_chain_history(
            source_report=source_report(researchOnly=False, status="partial-error"),
            now=NOW,
        )

        self.assertEqual(payload["capture"]["status"], "source-rejected")
        self.assertIn("research-only", payload["capture"]["reason"])
        self.assertEqual(manifest["hotSnapshots"], [])
        self.assertEqual(manifest["archiveSnapshots"], [])

    def test_rejects_a_similarly_shaped_unexpected_source_stage(self) -> None:
        payload, manifest = history.build_chain_history(
            source_report=source_report(stage="unrelated-local-report"),
            now=NOW,
        )

        self.assertEqual(payload["capture"]["status"], "source-rejected")
        self.assertIn("normalized read-only Schwab chain artifact", payload["capture"]["reason"])
        self.assertEqual(manifest["hotSnapshots"], [])

    def test_old_hot_snapshot_moves_to_archive(self) -> None:
        old_day = "2026-01-01T16:20:00-06:00"
        payload, manifest = history.build_chain_history(
            source_report=source_report(generated_at=old_day),
            now=NOW,
        )

        self.assertEqual(payload["counts"]["movedToArchive"], 1)
        self.assertEqual(manifest["hotSnapshots"], [])
        self.assertEqual(len(manifest["archiveSnapshots"]), 1)
        archived_path = self.data_dir / manifest["archiveSnapshots"][0]["path"]
        self.assertTrue(archived_path.exists())

    def test_archive_retention_starts_after_hot_window(self) -> None:
        capture_day = NOW.date() - timedelta(
            days=history.HOT_RETENTION_DAYS + history.ARCHIVE_RETENTION_DAYS - 1
        )
        path = self.archive_dir / f"{capture_day.isoformat()}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        manifest = history.empty_manifest()
        manifest["archiveSnapshots"] = [
            {
                "captureDate": capture_day.isoformat(),
                "capturedAt": NOW.isoformat(),
                "path": f"chain_history/archive/{capture_day.isoformat()}.json",
            }
        ]

        retention = history.prune_history(manifest, now=NOW)

        self.assertEqual(retention["expiredFromArchive"], 0)
        self.assertTrue(path.exists())
        self.assertEqual(len(manifest["archiveSnapshots"]), 1)

    def test_render_makes_calibration_limit_explicit(self) -> None:
        payload, _ = history.build_chain_history(source_report=source_report(), now=NOW)

        rendered = history.render_chain_history(payload)

        self.assertIn("recorded dates: 1 / 60", rendered)
        self.assertIn("ready for calibration: False", rendered)
        self.assertIn("broker submit OFF", rendered)


if __name__ == "__main__":
    unittest.main()
