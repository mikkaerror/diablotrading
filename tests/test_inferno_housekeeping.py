from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from inferno_housekeeping import trim_log


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


if __name__ == "__main__":
    unittest.main()
