from __future__ import annotations

"""Regression tests for the non-destructive ops maintenance sweep."""

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import inferno_ops_maintenance as ops_maintenance


class InfernoOpsMaintenanceTests(unittest.TestCase):
    """Verify maintenance can recover a missed brief without lying about state."""

    def test_repair_morning_email_updates_ops_status_when_send_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            ops_status_file = temp_root / "inferno_ops_status.json"
            snapshot_file = temp_root / "latest_snapshot.json"
            log_file = temp_root / "inferno_dawn.log"
            ops_status_file.write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-05T06:00:00-10:00",
                        "ok": True,
                        "emailSent": False,
                    }
                ),
                encoding="utf-8",
            )
            snapshot_file.write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-05T06:00:00-10:00",
                        "brief": "Morning Brief",
                        "sourceLabel": "Inferno Runner",
                        "rows": [],
                    }
                ),
                encoding="utf-8",
            )

            def append_log_stub(entry):
                with log_file.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry) + "\n")

            with (
                patch.object(ops_maintenance, "OPS_STATUS_FILE", ops_status_file),
                patch.object(ops_maintenance, "SNAPSHOT_FILE", snapshot_file),
                patch.object(ops_maintenance, "append_log", append_log_stub),
                patch.object(ops_maintenance, "smtp_configured", return_value=True),
                patch.object(ops_maintenance, "send_email", return_value=True),
            ):
                result = ops_maintenance.repair_morning_email()

            repaired = json.loads(ops_status_file.read_text(encoding="utf-8"))
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "email-recovered")
            self.assertTrue(repaired["emailSent"])
            self.assertEqual(repaired["emailRecoverySource"], "inferno_ops_maintenance")
            self.assertIn("inferno_ops_maintenance_email_repair", log_file.read_text(encoding="utf-8"))

    def test_repair_morning_email_skips_when_snapshot_does_not_match_ops_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            ops_status_file = temp_root / "inferno_ops_status.json"
            snapshot_file = temp_root / "latest_snapshot.json"
            ops_status_file.write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-05T06:00:00-10:00",
                        "ok": True,
                        "emailSent": False,
                    }
                ),
                encoding="utf-8",
            )
            snapshot_file.write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-05T07:00:00-10:00",
                        "brief": "Morning Brief",
                        "sourceLabel": "Inferno Runner",
                        "rows": [],
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(ops_maintenance, "OPS_STATUS_FILE", ops_status_file),
                patch.object(ops_maintenance, "SNAPSHOT_FILE", snapshot_file),
                patch.object(ops_maintenance, "smtp_configured", return_value=True),
                patch.object(ops_maintenance, "send_email", return_value=True),
            ):
                result = ops_maintenance.repair_morning_email()

            repaired = json.loads(ops_status_file.read_text(encoding="utf-8"))
            self.assertFalse(result["attempted"])
            self.assertEqual(result["status"], "snapshot-mismatch")
            self.assertFalse(repaired["emailSent"])

    def test_run_maintenance_refreshes_cloud_artifacts_and_sets_ok(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            report_file = temp_root / "ops_maintenance.json"
            report_text_file = temp_root / "ops_maintenance.txt"

            with ExitStack() as stack:
                stack.enter_context(patch.object(ops_maintenance, "OPS_MAINTENANCE_FILE", report_file))
                stack.enter_context(patch.object(ops_maintenance, "OPS_MAINTENANCE_TEXT_FILE", report_text_file))
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "build_ticker_universe_audit_from_sheet",
                        return_value={"ok": True, "verdict": "healthy", "counts": {"criticalIssueCount": 0, "advisoryIssueCount": 0}},
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "run_audit",
                        return_value={"verdict": "ready-for-next-week-prep", "dailyPrepReady": True, "researchReady": False},
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "run_watch",
                        return_value={"generatedAt": "2026-05-06T07:00:00-10:00", "skipped": False, "downloadsManager": {"importedFiles": 0}, "fillIngest": {}},
                    )
                )
                repair_email = stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "repair_morning_email",
                        return_value={"attempted": False, "ok": True, "status": "already-sent"},
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "refresh_cloud_control_plane",
                        return_value={"ok": True, "status": "ready", "region": "us-central1", "projectId": "proj-123", "message": "good"},
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "refresh_cloud_execution_audit",
                        return_value={"ok": True, "status": "healthy", "region": "us-central1", "projectId": "proj-123"},
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "refresh_paper_test_director",
                        return_value={"ok": True, "status": "approval-bottleneck", "counts": {"stageableNow": 0, "approvalOnly": 1}},
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "refresh_paper_bottleneck_reducer",
                        return_value={
                            "ok": True,
                            "status": "scenario-slate-ready",
                            "counts": {"scenarios": 12, "executablePaper": 0, "shadowOnly": 12},
                            "topFocusTickers": ["MOD", "MRVL"],
                        },
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "refresh_paper_evidence_loop",
                        return_value={"ok": True, "status": "approval-bottleneck", "counts": {"plannedFillRows": 0, "openFillRows": 0, "remainingForPromotion": 30}},
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "refresh_paper_exit_audit",
                        return_value={"ok": True, "status": "clean", "counts": {"openLedgerTickets": 0, "closeNow": 0, "orphanOpenFillRows": 0}},
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "refresh_paper_mark_to_market",
                        return_value={"ok": True, "status": "disabled", "openPositionCount": 1, "markedTickets": 1},
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "refresh_broker_preview",
                        return_value={"ok": True, "status": "preview-built", "count": 0, "previewOnly": True, "generatedAt": "2026-05-10T07:05:00-10:00"},
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "refresh_stale_approval_governor",
                        return_value={"ok": True, "status": "no-action", "demoted": [], "ttlMarketDays": 5},
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "refresh_approval_inbox",
                        return_value={"ok": True, "status": "idle", "checkedCount": 2, "appliedCount": 1, "skippedCount": 1},
                    )
                )
                approval_dispatch = stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "refresh_approval_dispatch",
                        return_value={"ok": True, "status": "sent", "pendingCount": 2, "sentCount": 1, "skippedCount": 1},
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "refresh_schwab_account_sync",
                        return_value={
                            "ok": True,
                            "status": "healthy",
                            "matchedSuffix": "1234",
                            "counts": {"accounts": 1, "approvedAccounts": 1, "positions": 3},
                            "readOnly": True,
                        },
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "refresh_live_account_sync",
                        return_value={"ok": True, "status": "healthy", "matchedSuffix": "1234", "accountDataSource": "schwab-account-api", "counts": {"positions": 3, "matchedPositions": 3}},
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "refresh_live_position_review",
                        return_value={"ok": True, "status": "review", "counts": {"supported": 1, "review": 1, "fragile": 0}},
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "refresh_model_command_center",
                        return_value={
                            "ok": True,
                            "status": "ready",
                            "missionCount": 2,
                            "noteCount": 4,
                            "headlineMetrics": {"liveFragile": 1},
                        },
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "refresh_research_cycle",
                        return_value={
                            "ok": True,
                            "status": "research-refreshed",
                            "shadowTrackedCount": 39,
                            "shadowClosedCount": 10,
                            "strategyVerdict": "insufficient-data",
                            "strategyScoredCount": 0,
                            "scenarioCount": 12,
                            "scenarioClosedEvidenceCount": 2,
                            "scenarioVerdictCounts": {"insufficient-data": 12},
                            "scenarioTopFocusTickers": ["MOD", "THR"],
                        },
                    )
                )
                stack.enter_context(
                    patch.object(
                        ops_maintenance,
                        "run_watchdog_check",
                        return_value=({"ok": True, "reasons": [], "generatedAt": "2026-05-06T07:10:00-10:00"}, 0),
                    )
                )
                heartbeat = stack.enter_context(patch.object(ops_maintenance, "record_heartbeat", return_value={}))
                report = ops_maintenance.run_maintenance(
                    backtest_root=temp_root,
                    sheet_name="Earnings Tracker",
                    skip_outbound=True,
                    cloud_region="us-central1",
                )

            saved = json.loads(report_file.read_text(encoding="utf-8"))
            self.assertTrue(report["ok"])
            repair_email.assert_not_called()
            approval_dispatch.assert_not_called()
            self.assertEqual(saved["emailRepair"]["status"], "skipped")
            self.assertEqual(saved["cloudControlPlane"]["status"], "ready")
            self.assertEqual(saved["cloudExecutionAudit"]["status"], "healthy")
            self.assertEqual(saved["advisories"], [])
            self.assertEqual(saved["paperTestDirector"]["status"], "approval-bottleneck")
            self.assertEqual(saved["paperBottleneckReducer"]["status"], "scenario-slate-ready")
            self.assertEqual(saved["paperEvidenceLoop"]["status"], "approval-bottleneck")
            self.assertEqual(saved["paperMarkToMarket"]["status"], "disabled")
            self.assertEqual(saved["brokerPreview"]["status"], "preview-built")
            self.assertTrue(saved["brokerPreview"]["previewOnly"])
            self.assertEqual(saved["staleApprovalGovernor"]["status"], "no-action")
            self.assertEqual(saved["staleApprovalGovernor"]["ttlMarketDays"], 5)
            self.assertEqual(saved["approvalInbox"]["status"], "idle")
            self.assertEqual(saved["approvalDispatch"]["status"], "skipped")
            self.assertEqual(saved["schwabAccountSync"]["status"], "healthy")
            self.assertEqual(saved["liveAccountSync"]["status"], "healthy")
            self.assertEqual(saved["livePositionReview"]["status"], "review")
            self.assertEqual(saved["modelCommandCenter"]["status"], "ready")
            self.assertEqual(saved["researchCycle"]["status"], "research-refreshed")
            self.assertEqual(saved["researchCycle"]["scenarioCount"], 12)
            self.assertIn("Cloud control plane: ready", report_text_file.read_text(encoding="utf-8"))
            self.assertIn("Paper test director: approval-bottleneck", report_text_file.read_text(encoding="utf-8"))
            self.assertIn("Paper bottleneck reducer: scenario-slate-ready", report_text_file.read_text(encoding="utf-8"))
            self.assertIn("Paper mark-to-market: disabled", report_text_file.read_text(encoding="utf-8"))
            self.assertIn("Broker preview: preview-built", report_text_file.read_text(encoding="utf-8"))
            self.assertIn("Stale approval governor: no-action", report_text_file.read_text(encoding="utf-8"))
            self.assertIn("Approval inbox: idle", report_text_file.read_text(encoding="utf-8"))
            self.assertIn("Schwab account sync: healthy", report_text_file.read_text(encoding="utf-8"))
            self.assertIn("Live position review: review", report_text_file.read_text(encoding="utf-8"))
            self.assertIn("Model command center: ready", report_text_file.read_text(encoding="utf-8"))
            self.assertIn("Research cycle: research-refreshed", report_text_file.read_text(encoding="utf-8"))
            self.assertIn("scenarios 12", report_text_file.read_text(encoding="utf-8"))
            heartbeat.assert_called_once()
            self.assertEqual(heartbeat.call_args.args[0], "ops_maintenance")

    def test_advisory_failures_keep_cloud_noise_visible_without_blocking_core_desk(self) -> None:
        """Cloud refresh failures are advisory so local ops can still proceed."""
        advisories = ops_maintenance.advisory_failures(
            ("cloud-control-plane", {"ok": False, "status": "refresh-failed", "error": "timeout"}),
            ("cloud-execution-audit", {"ok": True, "status": "healthy"}),
        )

        self.assertEqual(advisories, ["cloud-control-plane"])

    def test_refresh_stale_approval_governor_demotes_only_pending(self) -> None:
        """The governor delegate must surface demotions and rebuild execution queue exactly once."""
        from datetime import datetime as _dt
        old = "2026-04-20T08:00:00-06:00"
        loaded_queue = {
            "items": [
                {"ticker": "STALE", "approvalStatus": "pending", "pendingSince": old},
                {"ticker": "FRESH", "approvalStatus": "approved"},
            ]
        }
        saved_queues = []
        rebuilds = []

        def fake_load():
            return loaded_queue

        def fake_save(queue):
            saved_queues.append(queue)

        def fake_rebuild():
            rebuilds.append(_dt.now().isoformat())

        with (
            patch.object(ops_maintenance, "load_approval_queue", side_effect=fake_load),
            patch.object(ops_maintenance, "save_approval_queue", side_effect=fake_save),
            patch.object(ops_maintenance, "refresh_execution_queue", side_effect=fake_rebuild),
        ):
            result = ops_maintenance.refresh_stale_approval_governor(ttl_market_days=5)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "demoted-1")
        # The pending ticker should be demoted; the approved ticker stays approved.
        self.assertEqual(loaded_queue["items"][0]["approvalStatus"], "research-only")
        self.assertEqual(loaded_queue["items"][1]["approvalStatus"], "approved")
        self.assertEqual(len(rebuilds), 1)
        self.assertEqual(len(saved_queues), 1)

    def test_refresh_stale_approval_governor_skips_rebuild_when_no_demotions(self) -> None:
        """A no-op pass must not rebuild the execution queue."""
        loaded_queue = {"items": [{"ticker": "FRESH", "approvalStatus": "approved"}]}
        rebuilds = []

        with (
            patch.object(ops_maintenance, "load_approval_queue", return_value=loaded_queue),
            patch.object(ops_maintenance, "save_approval_queue"),
            patch.object(ops_maintenance, "refresh_execution_queue", side_effect=lambda: rebuilds.append(1)),
        ):
            result = ops_maintenance.refresh_stale_approval_governor(ttl_market_days=5)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "no-action")
        self.assertEqual(rebuilds, [])

    def test_refresh_broker_preview_returns_safe_payload_when_build_fails(self) -> None:
        """A broker-preview build failure must surface as refresh-failed, not crash."""
        with patch.object(ops_maintenance, "build_broker_preview", side_effect=RuntimeError("preview boom")):
            result = ops_maintenance.refresh_broker_preview()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "refresh-failed")
        self.assertEqual(result["error"], "preview boom")


if __name__ == "__main__":
    unittest.main()
