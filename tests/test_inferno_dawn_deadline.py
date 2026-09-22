from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_dawn_pipeline as dawn
import morning_inferno_pipeline as pipeline


class DawnDeadlineTests(unittest.TestCase):
    def test_contending_run_does_not_erase_owner_lock_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(pipeline, "LOCK_FILE", Path(tmp) / "job.lock"), \
             patch.object(pipeline, "ensure_dirs"):
            with pipeline.acquire_run_lock():
                before = pipeline.LOCK_FILE.read_text()
                with self.assertRaises(pipeline.PipelineLockActive):
                    with pipeline.acquire_run_lock():
                        self.fail("Contending run acquired the lock")
                self.assertEqual(pipeline.LOCK_FILE.read_text(), before)
            self.assertEqual(pipeline.LOCK_FILE.read_text(), "")

    def test_deadline_reaps_job_and_releases_file_lock(self) -> None:
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "job.lock"
            code = "import fcntl,time,sys; f=open(sys.argv[1],'w'); fcntl.flock(f,fcntl.LOCK_EX); f.write('locked'); f.flush(); time.sleep(60)"
            self.assertEqual(dawn.run_bounded([sys.executable, "-c", code, str(lock)], timeout_seconds=0.5), 124)
            self.assertEqual(lock.read_text(), "locked")
            with lock.open("a") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(handle, fcntl.LOCK_UN)

    def test_normal_exit_code_propagates(self) -> None:
        self.assertEqual(dawn.run_bounded([sys.executable, "-c", "raise SystemExit(3)"], timeout_seconds=2), 3)

    def test_skip_email_also_suppresses_failure_email(self) -> None:
        with patch.object(sys, "argv", ["pipeline", "--cloud-native", "--skip-updates", "--skip-email"]), \
             patch.object(pipeline, "load_env_file"), \
             patch.object(pipeline, "ensure_dirs"), \
             patch("inferno_cloud_state.restore_cloud_artifacts", return_value={}), \
             patch.object(pipeline, "acquire_run_lock", side_effect=RuntimeError("provider failed")), \
             patch.object(pipeline, "send_failure_email") as send, \
             patch.object(pipeline, "append_log"), \
             patch.object(pipeline, "atomic_write_json"), \
             patch.object(pipeline, "record_heartbeat"):
            self.assertEqual(pipeline.main(), 1)
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
