from __future__ import annotations

"""Regression tests for the Cloud Run execution auditor."""

import unittest
from unittest.mock import patch

from inferno_cloud_execution_auditor import (
    alert_throttle_key,
    audit_verdict,
    execution_completed,
    execution_name,
    latest_execution,
    logs_contain,
    maybe_send_failure_alert,
    normalize_gcs_artifact,
    safe_execution_summary,
    should_send_failure_alert,
)


def execution(name: str, created_at: str, *, succeeded: int = 1, failed: int = 0, completed: str = "True") -> dict:
    """Build a compact fake Cloud Run execution payload."""
    return {
        "metadata": {"name": name, "creationTimestamp": created_at},
        "status": {
            "startTime": created_at,
            "completionTime": created_at,
            "succeededCount": succeeded,
            "failedCount": failed,
            "conditions": [{"type": "Completed", "status": completed}],
        },
    }


def execution_v2(
    name: str,
    created_at: str,
    *,
    succeeded: int = 1,
    failed: int = 0,
    completed: str = "CONDITION_SUCCEEDED",
) -> dict:
    """Build a compact Cloud Run v2 execution payload."""
    return {
        "name": f"projects/ohsheetohsheet/locations/us-central1/jobs/diablotrading-dawn/executions/{name}",
        "createTime": created_at,
        "startTime": created_at,
        "completionTime": created_at,
        "succeededCount": succeeded,
        "failedCount": failed,
        "conditions": [{"type": "Completed", "state": completed}],
    }


class CloudExecutionAuditorTests(unittest.TestCase):
    """Verify the execution audit parser stays safe and deterministic."""

    def test_latest_execution_uses_creation_timestamp(self) -> None:
        older = execution("dawn-old", "2026-04-27T12:00:00Z")
        newer = execution("dawn-new", "2026-04-28T12:00:00Z")
        self.assertEqual(latest_execution([older, newer])["metadata"]["name"], "dawn-new")

    def test_execution_completed_requires_success_without_failures(self) -> None:
        self.assertTrue(execution_completed(execution("ok", "2026-04-28T12:00:00Z")))
        self.assertFalse(execution_completed(execution("failed", "2026-04-28T12:00:00Z", failed=1)))
        self.assertFalse(execution_completed(execution("pending", "2026-04-28T12:00:00Z", completed="False")))
        self.assertTrue(execution_completed(execution_v2("ok-v2", "2026-04-28T12:00:00Z")))
        self.assertFalse(
            execution_completed(
                execution_v2("pending-v2", "2026-04-28T12:00:00Z", completed="CONDITION_PENDING")
            )
        )

    def test_safe_execution_summary_does_not_include_spec_or_env(self) -> None:
        payload = execution("dawn", "2026-04-28T12:00:00Z")
        payload["spec"] = {"template": {"template": {"containers": [{"env": [{"name": "SMTP_PASSWORD"}]}]}}}
        summary = safe_execution_summary(payload)
        self.assertEqual(summary["name"], "dawn")
        self.assertNotIn("spec", summary)
        self.assertNotIn("env", str(summary))

    def test_v2_execution_summary_uses_short_name_and_flat_fields(self) -> None:
        payload = execution_v2("dawn-fjzzk", "2026-04-28T12:00:00Z")
        summary = safe_execution_summary(payload)
        self.assertEqual(execution_name(payload), "dawn-fjzzk")
        self.assertEqual(summary["name"], "dawn-fjzzk")
        self.assertEqual(summary["createdAt"], "2026-04-28T12:00:00Z")
        self.assertTrue(summary["completed"])

    def test_log_and_artifact_helpers(self) -> None:
        self.assertTrue(logs_contain("Email sent: yes\nCloud state persist: 16 persisted", "Email sent: yes"))
        self.assertEqual(
            normalize_gcs_artifact(
                "gs://example/diablotrading-state/reports/shadow_evidence_latest.txt",
                "example",
                "diablotrading-state",
            ),
            "reports/shadow_evidence_latest.txt",
        )

    def test_audit_verdict_requires_all_checks(self) -> None:
        self.assertEqual(audit_verdict([{"ok": True}, {"ok": True}]), "healthy")
        self.assertEqual(audit_verdict([{"ok": True}, {"ok": False}]), "needs-attention")

    def test_failure_alert_is_throttled_by_daily_key(self) -> None:
        report = {
            "generatedAt": "2026-04-28T06:00:00-06:00",
            "projectId": "ohsheetohsheet",
            "region": "us-central1",
            "verdict": "needs-attention",
            "checks": [{"name": "dawn-success-log", "ok": False, "detail": "missing"}],
        }
        key = alert_throttle_key(report)
        self.assertTrue(should_send_failure_alert(report, {"lastAlertKey": "older-key"}))
        self.assertFalse(should_send_failure_alert(report, {"lastAlertKey": key}))
        self.assertTrue(should_send_failure_alert(report, {"lastAlertKey": key}, force=True))

    @patch("inferno_cloud_execution_auditor.save_alert_state")
    @patch("inferno_cloud_execution_auditor.smtp_configured", return_value=True)
    @patch("inferno_cloud_execution_auditor.send_email", return_value=True)
    @patch("inferno_cloud_execution_auditor.load_alert_state", return_value={})
    @patch("inferno_cloud_execution_auditor.load_env_file")
    def test_maybe_send_failure_alert_sends_once_for_unhealthy_report(
        self,
        _load_env_file: object,
        _load_alert_state: object,
        send_email_mock: object,
        _smtp_configured: object,
        save_alert_state_mock: object,
    ) -> None:
        report = {
            "generatedAt": "2026-04-28T06:00:00-06:00",
            "projectId": "ohsheetohsheet",
            "region": "us-central1",
            "verdict": "needs-attention",
            "checks": [{"name": "dawn-success-log", "ok": False, "detail": "missing"}],
            "jobs": [],
            "stateArtifacts": {},
        }
        result = maybe_send_failure_alert(report)
        self.assertTrue(result["alertSentThisRun"])
        self.assertFalse(result["alertSuppressed"])
        self.assertIsNone(result["alertError"])
        self.assertTrue(send_email_mock.called)
        self.assertTrue(save_alert_state_mock.called)

    @patch("inferno_cloud_execution_auditor.save_alert_state")
    @patch("inferno_cloud_execution_auditor.load_alert_state", return_value={"lastAlertKey": "keep"})
    @patch("inferno_cloud_execution_auditor.load_env_file")
    def test_maybe_send_failure_alert_stays_quiet_when_healthy(
        self,
        _load_env_file: object,
        _load_alert_state: object,
        save_alert_state_mock: object,
    ) -> None:
        report = {
            "generatedAt": "2026-04-28T06:00:00-06:00",
            "projectId": "ohsheetohsheet",
            "region": "us-central1",
            "verdict": "healthy",
            "checks": [{"name": "dawn-success-log", "ok": True, "detail": "ok"}],
            "jobs": [],
            "stateArtifacts": {},
        }
        result = maybe_send_failure_alert(report)
        self.assertFalse(result["alertNeeded"])
        self.assertFalse(result["alertSentThisRun"])
        self.assertFalse(result["alertSuppressed"])
        self.assertEqual(result["lastAlertKey"], "keep")
        self.assertTrue(save_alert_state_mock.called)


if __name__ == "__main__":
    unittest.main()
