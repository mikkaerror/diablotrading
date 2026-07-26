from __future__ import annotations

import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import install_inferno_daily_loop_service as service


class DailyLoopServiceTests(unittest.TestCase):
    def test_plist_runs_the_daily_digest_twice_each_weekday(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(service, "LOG_DIR", Path(temp_dir)):
                payload = service.plist_payload(((6, 30), (16, 30)))

        self.assertEqual(payload["Label"], service.SERVICE_LABEL)
        self.assertFalse(payload["RunAtLoad"])
        self.assertEqual(len(payload["StartCalendarInterval"]), 10)
        self.assertEqual(
            {(item["Hour"], item["Minute"]) for item in payload["StartCalendarInterval"]},
            {(6, 30), (16, 30)},
        )

    def test_wrapper_runs_deployed_daily_loop_with_configured_python(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wrapper = root / "bin" / "daily_loop_service.sh"
            entrypoint = root / "inferno_daily_loop.py"
            service_entrypoint = root / "bin" / "inferno_daily_loop.py"
            entrypoint.write_text("print('digest')\n", encoding="utf-8")
            with (
                patch.object(service, "ROOT", root),
                patch.object(service, "SERVICE_BIN_DIR", wrapper.parent),
                patch.object(service, "SERVICE_WRAPPER", wrapper),
                patch.object(service, "SERVICE_ENTRYPOINT", service_entrypoint),
                patch.object(service, "ENTRYPOINT", entrypoint),
                patch.object(service, "backtest_python", return_value="/tmp/python"),
            ):
                service.ensure_wrapper()
                sync_status = service.script_sync_status()

            text = wrapper.read_text(encoding="utf-8")
            self.assertIn('export BACKTEST_PYTHON="/tmp/python"', text)
            self.assertIn(f'export PYTHONPATH="{root}${{PYTHONPATH:+:${{PYTHONPATH}}}}"', text)
            self.assertIn(f'exec "/tmp/python" "{service_entrypoint}" run "$@"', text)
            self.assertEqual(service_entrypoint.read_text(encoding="utf-8"), entrypoint.read_text(encoding="utf-8"))
            self.assertEqual(service_entrypoint.stat().st_mode & 0o777, 0o755)
            self.assertEqual(sync_status["status"], "synced")

    def test_script_sync_status_detects_deployed_copy_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entrypoint = root / "inferno_daily_loop.py"
            deployed = root / "bin" / "inferno_daily_loop.py"
            entrypoint.write_text("current\n", encoding="utf-8")
            deployed.parent.mkdir()
            deployed.write_text("stale\n", encoding="utf-8")
            with (
                patch.object(service, "ENTRYPOINT", entrypoint),
                patch.object(service, "SERVICE_ENTRYPOINT", deployed),
            ):
                self.assertEqual(service.script_sync_status()["status"], "drift")

    def test_plist_payload_is_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(service, "LOG_DIR", Path(temp_dir)):
                payload = service.plist_payload(((6, 30), (16, 30)))
            encoded = plistlib.dumps(payload)
        self.assertIn(service.SERVICE_LABEL.encode(), encoded)


if __name__ == "__main__":
    unittest.main()
