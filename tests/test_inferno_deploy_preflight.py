from __future__ import annotations

"""Regression tests for deployment-readiness profiles.

These checks keep the deploy gate honest across three different lanes:
CI, cloud, and desktop broker automation. The point is not to prove every
subprocess works here; it is to prove the profile logic itself does not
quietly mix those lanes together and give us a false green light.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from inferno_deploy_preflight import (
    determine_verdict,
    required_check_names,
    restore_artifact_state,
    run_check,
    snapshot_artifact_state,
    summarize_lane,
)


class DeployPreflightProfileTests(unittest.TestCase):
    """Verify profile-specific deploy gates stay truthful."""

    def test_ci_profile_does_not_require_desktop_or_cloud_checks(self) -> None:
        """CI should only require repo-safe checks that can run in GitHub Actions."""
        names = required_check_names("ci")
        self.assertIn("python-compile", names)
        self.assertIn("unit-tests", names)
        self.assertIn("deploy-assets", names)
        self.assertIn("research-cycle", names)
        self.assertNotIn("doctor", names)
        self.assertNotIn("cloud-smoke", names)
        self.assertNotIn("tos-session-probe", names)

    def test_cloud_profile_requires_cloud_smoke_but_not_desktop_lane(self) -> None:
        """Cloud preflight should validate cloud smoke without pretending the broker desktop exists."""
        names = required_check_names("cloud")
        self.assertIn("doctor", names)
        self.assertIn("cloud-smoke", names)
        self.assertNotIn("tos-ui-route-dry-run", names)
        self.assertNotIn("tos-export-verifier", names)

    def test_summarize_lane_requires_every_relevant_check(self) -> None:
        """A lane should only pass when all of its required checks are green."""
        checks = [
            {"name": "python-compile", "ok": True},
            {"name": "unit-tests", "ok": True},
            {"name": "deploy-assets", "ok": False},
        ]
        self.assertFalse(summarize_lane(checks, {"python-compile", "unit-tests", "deploy-assets"}))

    def test_determine_verdict_for_ci_profile(self) -> None:
        """The CI profile should report a repo-safe ready verdict when core checks are green."""
        verdict, message = determine_verdict(
            {
                "profile": "ci",
                "coreReady": True,
                "cloudReady": False,
                "brokerDesktopReady": False,
            }
        )
        self.assertEqual(verdict, "ready-for-ci")
        self.assertIn("CI-safe", message)

    def test_determine_verdict_for_desktop_profile(self) -> None:
        """Desktop preflight should call out the broker lane honestly when it is still blocked."""
        verdict, message = determine_verdict(
            {
                "profile": "desktop",
                "coreReady": True,
                "cloudReady": False,
                "brokerDesktopReady": False,
            }
        )
        self.assertEqual(verdict, "desktop-blocked")
        self.assertIn("desktop broker lane", message)

    @patch("inferno_deploy_preflight.run_command")
    def test_run_check_reports_silent_nonzero_return_codes_honestly(self, mock_run_command) -> None:
        """Silent failures should not be labeled as if the command returned 'ok'."""
        mock_run_command.return_value = {
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": "",
            "command": "python3 -m unittest",
        }

        check = run_check("unit-tests", ["python3", "-m", "unittest"])

        self.assertFalse(check["ok"])
        self.assertEqual(check["detail"], "command exited 1 with no output")

    def test_snapshot_and_restore_artifact_state_puts_files_back(self) -> None:
        """Isolated smoke runs should not leave desk artifacts in a mutated state."""
        with TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            reports_root = Path(tmp) / "reports"
            data_root.mkdir()
            reports_root.mkdir()
            (data_root / "alpha.json").write_text('{"ok": true}')
            (reports_root / "brief.txt").write_text("original")

            snapshot_dir, manifests = snapshot_artifact_state(data_root, reports_root)

            (data_root / "alpha.json").write_text('{"ok": false}')
            (data_root / "new.json").write_text("{}")
            (reports_root / "brief.txt").write_text("mutated")

            restore_artifact_state(snapshot_dir, manifests)

            self.assertEqual((data_root / "alpha.json").read_text(), '{"ok": true}')
            self.assertFalse((data_root / "new.json").exists())
            self.assertEqual((reports_root / "brief.txt").read_text(), "original")


if __name__ == "__main__":
    unittest.main()
