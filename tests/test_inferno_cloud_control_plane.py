from __future__ import annotations

"""Regression tests for the cloud control-plane verifier.

These tests keep the verdict logic honest so we do not confuse "repo is ready"
with "this machine can actually deploy the cloud jobs right now."
"""

import unittest

from inferno_cloud_control_plane import determine_verdict


def check(name: str, ok: bool) -> dict[str, object]:
    """Build a compact fake check record for verdict tests."""
    return {"name": name, "ok": ok, "detail": "ok" if ok else "warn"}


class CloudControlPlaneVerdictTests(unittest.TestCase):
    """Verify the cloud control-plane verdict ladder stays stable."""

    def test_repo_ready_when_gcloud_missing(self) -> None:
        """Missing gcloud should still distinguish code-readiness from operator-readiness."""
        verdict, message = determine_verdict(
            [
                check("assets", True),
                check("local-credentials", True),
                check("gcloud", False),
            ]
        )
        self.assertEqual(verdict, "repo-ready")
        self.assertIn("gcloud", message)

    def test_deployable_when_jobs_not_provisioned_yet(self) -> None:
        """A prepared machine should report deployable before jobs are created."""
        verdict, message = determine_verdict(
            [
                check("assets", True),
                check("local-credentials", True),
                check("gcloud", True),
                check("project", True),
                check("auth", True),
                check("adc", True),
                check("apis", True),
                check("jobs", False),
                check("schedulers", False),
            ]
        )
        self.assertEqual(verdict, "deployable")
        self.assertIn("not fully provisioned", message)

    def test_ready_when_all_checks_pass(self) -> None:
        """A fully provisioned machine should report ready."""
        verdict, message = determine_verdict(
            [
                check("assets", True),
                check("local-credentials", True),
                check("gcloud", True),
                check("project", True),
                check("auth", True),
                check("adc", True),
                check("apis", True),
                check("jobs", True),
                check("schedulers", True),
            ]
        )
        self.assertEqual(verdict, "ready")
        self.assertIn("ready to operate", message)


if __name__ == "__main__":
    unittest.main()
