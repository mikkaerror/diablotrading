from __future__ import annotations

import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import install_inferno_daily_model_refresh_service as service


class DailyModelRefreshServiceTests(unittest.TestCase):
    def test_plist_runs_full_refresh_twice_each_weekday(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(service, "LOG_DIR", Path(temp_dir)):
                payload = service.plist_payload(((6, 45), (16, 20)))

        self.assertEqual(payload["Label"], service.SERVICE_LABEL)
        self.assertFalse(payload["RunAtLoad"])
        self.assertEqual(len(payload["StartCalendarInterval"]), 10)
        self.assertEqual(
            {item["Weekday"] for item in payload["StartCalendarInterval"]},
            {1, 2, 3, 4, 5},
        )
        self.assertEqual(
            {(item["Hour"], item["Minute"]) for item in payload["StartCalendarInterval"]},
            {(6, 45), (16, 20)},
        )

    def test_wrapper_runs_deployed_daily_refresh_with_configured_python(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wrapper = root / "bin" / "daily_model_refresh_service.sh"
            entrypoint = root / "run_inferno_daily_model_refresh.sh"
            service_entrypoint = root / "bin" / "daily_model_refresh.sh"
            entrypoint.write_text("#!/usr/bin/env bash\necho refresh\n", encoding="utf-8")
            with (
                patch.object(service, "ROOT", root),
                patch.object(service, "SERVICE_BIN_DIR", wrapper.parent),
                patch.object(service, "SERVICE_WRAPPER", wrapper),
                patch.object(service, "SERVICE_ENTRYPOINT", service_entrypoint),
                patch.object(service, "ENTRYPOINT", entrypoint),
                patch.object(service, "backtest_python", return_value="/tmp/python"),
            ):
                service.ensure_wrapper()

            text = wrapper.read_text(encoding="utf-8")
            self.assertIn('export BACKTEST_PYTHON="/tmp/python"', text)
            self.assertIn('export INFERNO_PYTHON="/tmp/python"', text)
            self.assertIn(f'export INFERNO_ROOT="{root}"', text)
            self.assertIn(f'exec /bin/bash "{service_entrypoint}" "$@"', text)
            self.assertEqual(wrapper.stat().st_mode & 0o777, 0o755)
            self.assertEqual(service_entrypoint.read_text(encoding="utf-8"), entrypoint.read_text(encoding="utf-8"))
            self.assertEqual(service_entrypoint.stat().st_mode & 0o777, 0o755)

    def test_plist_payload_is_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(service, "LOG_DIR", Path(temp_dir)):
                payload = service.plist_payload(((6, 45), (16, 20)))
            encoded = plistlib.dumps(payload)
        self.assertIn(service.SERVICE_LABEL.encode(), encoded)


if __name__ == "__main__":
    unittest.main()
