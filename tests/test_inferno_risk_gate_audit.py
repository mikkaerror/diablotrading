import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import inferno_risk_gate_audit as audit
from inferno_io import atomic_write_json, atomic_write_text


class RiskGateAuditTests(unittest.TestCase):
    """Verify the consolidated gate audit fails closed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.reports = self.root / "reports"
        self.data.mkdir()
        self.reports.mkdir()
        self.files = {
            "RISK_GATE_AUDIT_FILE": self.data / "inferno_risk_gate_audit.json",
            "RISK_GATE_AUDIT_TEXT_FILE": self.reports / "risk_gate_audit_latest.txt",
            "AUTHORITY_MANIFEST_FILE": self.data / "inferno_authority_manifest.json",
            "CAPITAL_DEPLOYMENT_READINESS_FILE": self.data / "inferno_capital_deployment_readiness.json",
            "LIVE_ACCOUNT_SYNC_FILE": self.data / "inferno_live_account_sync.json",
            "LIVE_POSITION_REVIEW_FILE": self.data / "inferno_live_position_review.json",
            "PAPER_EVIDENCE_LOOP_FILE": self.data / "inferno_paper_evidence_loop.json",
            "PAPER_TEST_DIRECTOR_FILE": self.data / "inferno_paper_test_director.json",
            "STRATEGY_LAB_FILE": self.data / "inferno_strategy_lab.json",
            "BROKER_PREVIEW_FILE": self.data / "inferno_broker_preview.json",
            "APPROVAL_DISPATCH_FILE": self.data / "inferno_approval_dispatch.json",
            "APPROVAL_INBOX_FILE": self.data / "inferno_approval_inbox.json",
            "DAILY_SUCCESS_FILE": self.data / "inferno_daily_success.json",
            "OPS_MAINTENANCE_FILE": self.data / "inferno_ops_maintenance.json",
            "DOWNLOADS_WATCH_FILE": self.data / "inferno_downloads_watch.json",
            "DOWNLOADS_MANAGER_FILE": self.data / "inferno_downloads_manager.json",
            "TOS_FILL_INGEST_FILE": self.data / "inferno_tos_fill_ingest.json",
            "DESKTOP_AUTOMATION_FILE": self.data / "inferno_desktop_automation.json",
            "TOS_EXPORT_VERIFIER_FILE": self.data / "inferno_tos_export_verifier.json",
            "PAPER_EXIT_AUDIT_FILE": self.data / "inferno_paper_exit_audit.json",
            "DOCTOR_TEXT_FILE": self.reports / "doctor_latest.txt",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def patch_paths(self):
        stack = ExitStack()
        for name, path in self.files.items():
            stack.enter_context(patch.object(audit, name, path))
        stack.enter_context(patch.object(audit, "ensure_dirs", return_value=None))
        stack.enter_context(patch.object(audit, "local_today", return_value="2026-05-14"))
        stack.enter_context(patch.object(audit, "account_suffix_allowed", return_value=True))
        stack.enter_context(patch.object(audit, "approved_account_scope", return_value="account ending 1234"))
        return stack

    def write_base_artifacts(self, *, fragile=0, broker_submit=False, capital_verdict="manual-ready"):
        atomic_write_json(
            self.files["AUTHORITY_MANIFEST_FILE"],
            {
                "decision": {
                    "authorityLevel": "paper-evidence-only",
                    "brokerSubmitAllowed": broker_submit,
                    "liveTradingAllowed": False,
                }
            },
        )
        atomic_write_json(
            self.files["CAPITAL_DEPLOYMENT_READINESS_FILE"],
            {
                "generatedAt": "2026-05-14T08:00:00-06:00",
                "verdict": capital_verdict,
                "manualDeploymentAllowed": capital_verdict != "not-ready",
                "autoLiveAllowed": False,
            },
        )
        atomic_write_json(
            self.files["LIVE_ACCOUNT_SYNC_FILE"],
            {"generatedAt": "2026-05-14T08:00:00-06:00", "ok": True, "verdict": "healthy", "matchedSuffix": "1234"},
        )
        atomic_write_json(
            self.files["LIVE_POSITION_REVIEW_FILE"],
            {"generatedAt": "2026-05-14T08:00:00-06:00", "counts": {"supported": 2, "review": 0, "fragile": fragile}},
        )
        atomic_write_json(
            self.files["PAPER_EVIDENCE_LOOP_FILE"],
            {"generatedAt": "2026-05-14T08:00:00-06:00", "counts": {"scoredTickets": 30, "remainingForPromotion": 0}},
        )
        atomic_write_json(
            self.files["PAPER_TEST_DIRECTOR_FILE"],
            {"generatedAt": "2026-05-14T08:00:00-06:00", "counts": {"stageableNow": 1, "approvalOnly": 0, "hardBlocked": 0}},
        )
        atomic_write_json(self.files["STRATEGY_LAB_FILE"], {"generatedAt": "2026-05-14T08:00:00-06:00", "verdict": "promotable"})
        atomic_write_json(
            self.files["BROKER_PREVIEW_FILE"],
            {"generatedAt": "2026-05-14T08:00:00-06:00", "adapterMode": "PREVIEW_ONLY", "previewOnly": True, "liveTradingAllowed": False, "count": 1},
        )
        atomic_write_json(self.files["APPROVAL_DISPATCH_FILE"], {"generatedAt": "2026-05-14T08:00:00-06:00", "ok": True, "status": "idle"})
        atomic_write_json(self.files["APPROVAL_INBOX_FILE"], {"generatedAt": "2026-05-14T08:00:00-06:00", "ok": True, "status": "idle"})
        atomic_write_json(
            self.files["DAILY_SUCCESS_FILE"],
            {
                "generatedAt": "2026-05-14T08:00:00-06:00",
                "criteria": [
                    {"name": "morningBriefDelivered", "pass": True},
                    {"name": "doctorHealthy", "pass": True},
                ],
            },
        )
        atomic_write_json(self.files["OPS_MAINTENANCE_FILE"], {"generatedAt": "2026-05-14T08:00:00-06:00", "ok": True})
        atomic_write_json(self.files["DOWNLOADS_WATCH_FILE"], {"generatedAt": "2026-05-14T08:00:00-06:00", "exportFirst": True, "skipped": False})
        atomic_write_json(self.files["DOWNLOADS_MANAGER_FILE"], {"generatedAt": "2026-05-14T08:00:00-06:00", "importedRows": 1})
        atomic_write_json(self.files["TOS_FILL_INGEST_FILE"], {"generatedAt": "2026-05-14T08:00:00-06:00", "unmatchedRows": 0})
        atomic_write_json(self.files["DESKTOP_AUTOMATION_FILE"], {"generatedAt": "2026-05-14T08:00:00-06:00", "verdict": "ready"})
        atomic_write_json(
            self.files["TOS_EXPORT_VERIFIER_FILE"],
            {"generatedAt": "2026-05-14T08:00:00-06:00", "verdict": "ready-live-readonly", "appRunning": True, "allowedLiveReadonly": True},
        )
        atomic_write_json(self.files["PAPER_EXIT_AUDIT_FILE"], {"generatedAt": "2026-05-14T08:00:00-06:00", "verdict": "clean", "counts": {"closeNow": 0, "review": 0}})
        atomic_write_text(self.files["DOCTOR_TEXT_FILE"], "")

    def test_clear_when_all_gates_pass(self):
        self.write_base_artifacts()
        with self.patch_paths():
            payload = audit.build_risk_gate_audit()

        self.assertEqual(payload["verdict"], "clear")
        self.assertEqual(payload["summary"]["hardFails"], 0)
        self.assertTrue(self.files["RISK_GATE_AUDIT_TEXT_FILE"].exists())

    def test_live_fragile_holding_blocks_deployment(self):
        self.write_base_artifacts(fragile=1, capital_verdict="not-ready")
        with self.patch_paths():
            payload = audit.build_risk_gate_audit()

        self.assertEqual(payload["verdict"], "blocked")
        self.assertIn("live-position-fragility", payload["summary"]["blockedGateIds"])
        self.assertFalse(payload["liveTradingAllowed"])

    def test_paper_exit_gate_reads_review_today_count(self):
        row = audit.evaluate_paper_exit_gate(
            {
                "verdict": "review-open-exits",
                "counts": {"closeNow": 0, "reviewToday": 1},
            }
        )

        self.assertEqual(row["status"], "warn")
        self.assertIn("review=1", row["detail"])

    def test_authority_submit_flag_fails_hard(self):
        self.write_base_artifacts(broker_submit=True)
        with self.patch_paths():
            payload = audit.build_risk_gate_audit()

        self.assertEqual(payload["verdict"], "blocked")
        self.assertIn("authority-live-submit-lock", payload["summary"]["blockedGateIds"])


if __name__ == "__main__":
    unittest.main()
