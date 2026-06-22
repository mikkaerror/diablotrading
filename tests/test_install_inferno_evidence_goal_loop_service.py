from __future__ import annotations

import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import install_inferno_evidence_goal_loop_service as service


class EvidenceGoalLoopServiceTests(unittest.TestCase):
    def test_plist_is_weekday_near_close_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(service, "LOG_DIR", Path(temp_dir)):
                payload = service.plist_payload(13, 40)

        self.assertEqual(payload["Label"], service.SERVICE_LABEL)
        self.assertFalse(payload["RunAtLoad"])
        self.assertEqual(len(payload["StartCalendarInterval"]), 5)
        self.assertEqual(
            {item["Weekday"] for item in payload["StartCalendarInterval"]},
            {1, 2, 3, 4, 5},
        )
        self.assertTrue(
            all(
                item["Hour"] == 13 and item["Minute"] == 40
                for item in payload["StartCalendarInterval"]
            )
        )

    def test_wrapper_runs_bounded_goal_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wrapper = root / "bin" / "goal-loop.sh"
            entrypoint = root / "inferno_evidence_goal_loop.py"
            with (
                patch.object(service, "ROOT", root),
                patch.object(service, "SERVICE_BIN_DIR", wrapper.parent),
                patch.object(service, "SERVICE_WRAPPER", wrapper),
                patch.object(service, "ENTRYPOINT", entrypoint),
                patch.object(service, "backtest_python", return_value="/tmp/python"),
            ):
                service.ensure_wrapper()

            text = wrapper.read_text(encoding="utf-8")
            self.assertIn(f'exec "/tmp/python" "{entrypoint}" run', text)
            self.assertIn("--max-iterations 2", text)
            self.assertEqual(wrapper.stat().st_mode & 0o777, 0o755)

    def test_plist_payload_is_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(service, "LOG_DIR", Path(temp_dir)):
                encoded = plistlib.dumps(service.plist_payload(13, 40))
        self.assertIn(service.SERVICE_LABEL.encode(), encoded)


if __name__ == "__main__":
    unittest.main()
