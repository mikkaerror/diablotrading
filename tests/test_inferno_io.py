from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_io


class InfernoIoTests(unittest.TestCase):
    """Protect the retry/atomic write helper used by the desk hot path."""

    def test_atomic_write_text_retries_transient_deadlock_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "artifact.txt"
            calls = {"count": 0}
            real_write = inferno_io._atomic_write_once

            def flaky_write(target: Path, content: str, *, encoding: str) -> None:
                calls["count"] += 1
                if calls["count"] == 1:
                    raise OSError(11, "Resource deadlock avoided")
                real_write(target, content, encoding=encoding)

            with patch.object(inferno_io, "_atomic_write_once", side_effect=flaky_write):
                inferno_io.atomic_write_text(path, "hello inferno", retries=2, delay_seconds=0)

            self.assertEqual(path.read_text(encoding="utf-8"), "hello inferno")
            self.assertEqual(calls["count"], 2)

    def test_atomic_write_json_persists_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "artifact.json"
            inferno_io.atomic_write_json(path, {"ok": True, "count": 2})
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["count"], 2)


if __name__ == "__main__":
    unittest.main()
