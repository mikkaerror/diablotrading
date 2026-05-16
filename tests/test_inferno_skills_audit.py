from __future__ import annotations

"""Regression tests for the stale-skill auditor."""

import os
import time
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from inferno_skills_audit import (
    RETIRE_AFTER_DAYS,
    SKILLS_AUDIT_STAGE,
    STALE_AFTER_HOURS,
    build_skills_audit,
    skills_audit_text,
)


def _touch(path: Path, hours_ago: float) -> None:
    """Create ``path`` and set its mtime to ``hours_ago`` hours in the past."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    mtime = time.time() - (hours_ago * 3600.0)
    os.utime(path, (mtime, mtime))


class SkillsAuditTests(unittest.TestCase):
    """Audit results should classify modules by freshness correctly."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data_dir = self.root / "data"
        self.reports_dir = self.root / "reports"
        self.data_dir.mkdir()
        self.reports_dir.mkdir()
        # Fake modules: we only need real Path objects with the right names.
        self.modules = [
            self.root / "inferno_fresh.py",
            self.root / "inferno_stale.py",
            self.root / "inferno_silent.py",
            self.root / "inferno_unknown.py",
        ]
        for module in self.modules:
            module.write_text("")

    def _build(self, now: datetime | None = None) -> dict:
        return build_skills_audit(
            modules=self.modules,
            artifact_dirs=[self.data_dir, self.reports_dir],
            now=now,
        )

    def test_research_only_is_immutable(self) -> None:
        payload = self._build()
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertEqual(payload["stage"], SKILLS_AUDIT_STAGE)

    def test_fresh_artifact_classifies_as_fresh(self) -> None:
        _touch(self.data_dir / "inferno_fresh.json", hours_ago=2.0)
        payload = self._build()
        row = next(r for r in payload["rows"] if r["module"] == "inferno_fresh.py")
        self.assertEqual(row["freshness"], "fresh")

    def test_stale_artifact_classifies_as_stale(self) -> None:
        _touch(self.data_dir / "inferno_stale.json", hours_ago=STALE_AFTER_HOURS + 5)
        payload = self._build()
        row = next(r for r in payload["rows"] if r["module"] == "inferno_stale.py")
        self.assertEqual(row["freshness"], "stale")

    def test_silent_artifact_classifies_as_silent(self) -> None:
        _touch(self.data_dir / "inferno_silent.json", hours_ago=(RETIRE_AFTER_DAYS + 1) * 24)
        payload = self._build()
        row = next(r for r in payload["rows"] if r["module"] == "inferno_silent.py")
        self.assertEqual(row["freshness"], "silent")

    def test_missing_artifact_classifies_as_unknown(self) -> None:
        payload = self._build()
        row = next(r for r in payload["rows"] if r["module"] == "inferno_unknown.py")
        self.assertEqual(row["freshness"], "unknown")
        self.assertIsNone(row["latestArtifact"])

    def test_silent_drives_needs_attention_verdict(self) -> None:
        _touch(self.data_dir / "inferno_silent.json", hours_ago=(RETIRE_AFTER_DAYS + 1) * 24)
        _touch(self.data_dir / "inferno_fresh.json", hours_ago=1.0)
        payload = self._build()
        self.assertEqual(payload["verdict"], "needs-attention")

    def test_text_renderer_includes_each_section(self) -> None:
        _touch(self.data_dir / "inferno_fresh.json", hours_ago=1.0)
        payload = self._build()
        rendered = skills_audit_text(payload)
        self.assertIn("Skills Audit", rendered)
        self.assertIn("Verdict:", rendered)
        self.assertIn("Per-skill detail:", rendered)


class AliasTableTests(unittest.TestCase):
    """SPECIFIC_ALIASES should let the audit recognise artifact filenames
    that don't follow the default ``inferno_X`` / ``X_latest`` convention."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data_dir = self.root / "data"
        self.reports_dir = self.root / "reports"
        self.data_dir.mkdir()
        self.reports_dir.mkdir()

    def _module(self, name: str) -> Path:
        path = self.root / name
        path.write_text("")
        return path

    def test_specific_alias_resolves_to_fresh(self) -> None:
        # The TOS session probe writes ``tos_session_probe_latest.txt``,
        # which doesn't include the ``inferno_`` prefix. With the alias
        # table that should still match.
        _touch(self.reports_dir / "tos_session_probe_latest.txt", hours_ago=1.0)
        payload = build_skills_audit(
            modules=[self._module("inferno_tos_session_probe.py")],
            artifact_dirs=[self.data_dir, self.reports_dir],
        )
        row = next(r for r in payload["rows"] if r["module"] == "inferno_tos_session_probe.py")
        self.assertEqual(row["freshness"], "fresh")

    def test_module_with_no_alias_falls_back_to_default(self) -> None:
        _touch(self.data_dir / "inferno_only_default.json", hours_ago=1.0)
        payload = build_skills_audit(
            modules=[self._module("inferno_only_default.py")],
            artifact_dirs=[self.data_dir, self.reports_dir],
        )
        row = next(r for r in payload["rows"] if r["module"] == "inferno_only_default.py")
        self.assertEqual(row["freshness"], "fresh")


if __name__ == "__main__":
    unittest.main()
