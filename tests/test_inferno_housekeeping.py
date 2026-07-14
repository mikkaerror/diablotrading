from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from inferno_housekeeping import iter_cache_dirs, prune_cache_dirs, run_git_gc, trim_log


class HousekeepingTests(unittest.TestCase):
    """Keep cleanup tooling boring, predictable, and non-destructive."""

    def test_trim_log_keeps_tail_lines(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "desk.log"
            path.write_text("one\ntwo\nthree\n", encoding="utf-8")

            original_count, final_count, error = trim_log(path, keep_lines=2, dry_run=False)

            self.assertIsNone(error)
            self.assertEqual(original_count, 3)
            self.assertEqual(final_count, 2)
            self.assertEqual(path.read_text(encoding="utf-8"), "two\nthree\n")

    def test_trim_log_reports_read_errors_without_crashing(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "desk.log"
            path.write_text("one\n", encoding="utf-8")

            with patch.object(Path, "read_text", side_effect=TimeoutError("slow filesystem")):
                original_count, final_count, error = trim_log(path, keep_lines=2, dry_run=True)

            self.assertEqual((original_count, final_count), (0, 0))
            self.assertIn("TimeoutError", error or "")

    def test_trim_log_can_remove_all_lines(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "desk.log"
            path.write_text("one\ntwo\n", encoding="utf-8")

            original_count, final_count, error = trim_log(path, keep_lines=0, dry_run=False)

            self.assertIsNone(error)
            self.assertEqual((original_count, final_count), (2, 0))
            self.assertEqual(path.read_text(encoding="utf-8"), "")

    def test_cache_scan_excludes_dependencies_and_git(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            wanted = root / "src" / "__pycache__"
            ignored = root / ".venv" / "lib" / "__pycache__"
            git_cache = root / ".git" / "__pycache__"
            for path in (wanted, ignored, git_cache):
                path.mkdir(parents=True)
                (path / "cache.pyc").write_bytes(b"cache")

            self.assertEqual(iter_cache_dirs(root), [wanted])
            removed, reclaimed, errors = prune_cache_dirs([wanted], dry_run=False)

            self.assertEqual((removed, reclaimed, errors), (1, 5, []))
            self.assertFalse(wanted.exists())
            self.assertTrue(ignored.exists())

    @patch("inferno_housekeeping.subprocess.run")
    def test_git_gc_uses_normal_safe_mode(self, run_mock) -> None:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stderr = ""
        run_mock.return_value.stdout = ""

        ok, detail = run_git_gc(Path("/tmp/project"), dry_run=False)

        self.assertTrue(ok)
        self.assertEqual(detail, "complete")
        self.assertEqual(run_mock.call_args.args[0], ["git", "gc"])


if __name__ == "__main__":
    unittest.main()
