from __future__ import annotations

"""Regression tests for the brain cycle journal."""

import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import inferno_brain_cycle_journal as journal


class CycleJournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.source = self.root / "data"
        self.cycles_root = self.root / "data" / "cycles"
        self.source.mkdir()
        self._seed_artifacts()

    def _seed_artifacts(self) -> None:
        for source_name, _target in journal.SNAPSHOT_TARGETS:
            (self.source / source_name).write_text(
                json.dumps({"source": source_name}), encoding="utf-8"
            )

    def test_snapshot_copies_all_seeded_artifacts(self) -> None:
        result = journal.snapshot_cycle(
            now=datetime(2026, 5, 11, 6, 30, 0),
            cycles_root=self.cycles_root,
            source_dir=self.source,
            narrative="hello brain",
        )
        cycle_dir = self.cycles_root / "2026-05-11-0630"
        self.assertTrue(cycle_dir.exists())
        self.assertEqual(len(result["copied"]), len(journal.SNAPSHOT_TARGETS))
        self.assertEqual(result["missing"], [])
        self.assertTrue((cycle_dir / "narrative.txt").exists())
        self.assertTrue((cycle_dir / "manifest.json").exists())

    def test_snapshot_reports_missing_when_source_absent(self) -> None:
        # Remove one of the seed files.
        (self.source / "inferno_daily_loop.json").unlink()
        result = journal.snapshot_cycle(
            now=datetime(2026, 5, 11, 6, 30, 0),
            cycles_root=self.cycles_root,
            source_dir=self.source,
        )
        self.assertIn("inferno_daily_loop.json", result["missing"])

    def test_pruning_keeps_max_cycles_worth(self) -> None:
        for index in range(5):
            journal.snapshot_cycle(
                now=datetime(2026, 5, 1 + index, 6, 30, 0),
                cycles_root=self.cycles_root,
                source_dir=self.source,
                max_cycles=3,
            )
        cycles = journal.list_cycles(cycles_root=self.cycles_root)
        self.assertEqual(len(cycles), 3)
        # Should be the most recent three.
        self.assertEqual(cycles[-1], "2026-05-05-0630")

    def test_cycle_id_pattern_blocks_non_journal_directories(self) -> None:
        # A directory not matching the YYYY-MM-DD-HHMM pattern must not be
        # considered for pruning.
        (self.cycles_root / "not-a-cycle").mkdir(parents=True)
        journal.snapshot_cycle(
            now=datetime(2026, 5, 11, 6, 30, 0),
            cycles_root=self.cycles_root,
            source_dir=self.source,
        )
        self.assertTrue((self.cycles_root / "not-a-cycle").exists())

    def test_journal_text_renders_each_section(self) -> None:
        payload = journal.snapshot_cycle(
            now=datetime(2026, 5, 11, 6, 30, 0),
            cycles_root=self.cycles_root,
            source_dir=self.source,
            narrative="snapshot test",
        )
        rendered = journal.journal_text(payload)
        self.assertIn("Cycle Journal", rendered)
        self.assertIn("Cycle id", rendered)
        self.assertIn("Reminders:", rendered)


if __name__ == "__main__":
    unittest.main()
