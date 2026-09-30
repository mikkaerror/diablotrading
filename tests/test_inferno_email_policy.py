from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack
import cloud_strike_cycle as cloud

import inferno_email_policy as policy
import inferno_action_pulse as pulse
import inferno_strike_selector as strike
import inferno_ops_maintenance as maintenance
import morning_inferno_pipeline as morning
import server


class EmailPolicyTests(unittest.TestCase):
    def test_default_and_invalid_mode_preserve_delivery(self):
        for value in (None, "full", "typo"):
            with self.subTest(value=value), patch.dict(os.environ, {}, clear=True):
                if value is not None:
                    os.environ["INFERNO_EMAIL_MODE"] = value
                self.assertEqual(policy.email_mode(), "full")
                for kind in ("morning", "strike", "action-pulse"):
                    self.assertFalse(policy.suppress_routine_email(kind))

    @patch.dict(os.environ, {"INFERNO_EMAIL_MODE": "editor"})
    def test_editor_suppresses_only_routine_selected_mail(self):
        for kind in ("morning", "strike", "action-pulse"):
            self.assertTrue(policy.suppress_routine_email(kind, {"verdict": "blocked"}))
            for failure in ({"ok": False}, {"error": "timeout"}, {"verdict": "failed"},
                            {"maintenanceStatus": False}, {"dailyLoop": {"failedCount": 1}}):
                self.assertFalse(policy.suppress_routine_email(kind, failure))
        self.assertFalse(policy.suppress_routine_email("approval"))
        for subject in ("Inferno Runner Failure", "Inferno Watchdog Alert", "Cloud auditor failure"):
            self.assertFalse(policy.suppress_subject(subject, {}))

    @patch.dict(os.environ, {"INFERNO_EMAIL_MODE": "editor"})
    def test_shared_smtp_blocks_routine_but_sends_failure(self):
        settings = {"from_addr": "a@example.com", "to_addr": "b@example.com", "host": "test",
                    "port": 465, "username": "", "password": "", "use_ssl": True}
        with patch.object(server, "smtp_settings", return_value=settings), \
             patch.object(server, "smtp_configured", return_value=True), \
             patch.object(server, "html_from_payload", return_value="<p>test</p>"), \
             patch.object(server.smtplib, "SMTP_SSL") as smtp:
            self.assertFalse(server.send_email({"brief": "routine"}))
            smtp.assert_not_called()
            self.assertTrue(server.send_email({"brief": "failed"}, subject="Inferno Runner Failure"))
            smtp.return_value.__enter__.return_value.send_message.assert_called_once()

    @patch.dict(os.environ, {"INFERNO_EMAIL_MODE": "editor"})
    def test_resend_and_strike_do_not_bypass_mode(self):
        with patch.object(strike, "send_email") as send:
            self.assertFalse(strike.send_strike_plan_email({}, body="Claude digest"))
            send.assert_not_called()
        self.assertEqual(morning.send_morning_brief()["status"], "suppressed-editor-mode")
        self.assertEqual(maintenance.repair_morning_email(force=True)["status"], "suppressed-editor-mode")

    @patch.dict(os.environ, {"INFERNO_EMAIL_MODE": "full"})
    def test_full_mode_keeps_claude_digest(self):
        with patch.object(strike, "smtp_configured", return_value=True), \
             patch.object(strike, "send_email", return_value=True) as send:
            self.assertTrue(strike.send_strike_plan_email({}, body="Claude digest"))
        self.assertEqual(send.call_args.args[0]["brief"], "Claude digest")

    def test_morning_mode_records_skip_but_keeps_approval_dispatch(self):
        for mode in ("full", "editor"):
            with self.subTest(mode=mode), patch.dict(os.environ, {"INFERNO_EMAIL_MODE": mode}), \
                 patch.object(morning, "smtp_configured", return_value=True), \
                 patch.object(morning, "send_email", return_value=True) as send, \
                 patch("inferno_approval_dispatch.dispatch_pending_approval_prompts", return_value={"ok": True}) as approval:
                result = morning.deliver_morning_email({"brief": "complete report"})
                self.assertEqual(result["emailSent"], mode == "full")
                self.assertEqual(result["emailSkipped"], mode == "editor")
                self.assertEqual(send.call_count, int(mode == "full"))
                approval.assert_called_once()
                self.assertIsNone(result["emailError"])

    @patch.dict(os.environ, {"INFERNO_EMAIL_MODE": "editor"})
    def test_cloud_suppression_is_success_and_artifacts_still_saved(self):
        with ExitStack() as stack:
            for name in ("restore_cloud_artifacts", "persist_cloud_artifacts", "build_strike_plan",
                         "build_shadow_evidence", "build_performance_analytics", "build_strategy_lab",
                         "build_exposure_analytics", "build_broker_preview", "build_authority_manifest",
                         "build_capital_allocator", "build_tos_sandbox_session"):
                stack.enter_context(patch.object(cloud, name, return_value={}))
            saves = [stack.enter_context(patch.object(cloud, name)) for name in (
                "save_strike_plan", "save_shadow_evidence", "save_performance_analytics", "save_strategy_lab",
                "save_exposure_analytics", "save_broker_preview", "save_authority_manifest",
                "save_capital_allocator", "save_tos_sandbox_session")]
            for name in ("ledger_summary", "shadow_evidence_text", "analytics_text", "strategy_lab_text",
                         "exposure_text", "preview_text", "authority_text", "allocator_text",
                         "tos_sandbox_text", "build_text_report", "build_strike_digest"):
                stack.enter_context(patch.object(cloud, name, return_value="saved report"))
            stack.enter_context(patch.object(cloud, "load_ledger", return_value={"items": []}))
            stack.enter_context(patch.object(cloud, "run_morning_pipeline", return_value=0))
            send = stack.enter_context(patch.object(strike, "send_email"))
            stack.enter_context(patch("builtins.print"))
            self.assertEqual(cloud.main(), 0)
            send.assert_not_called()
            for save in saves:
                save.assert_called_once()

    @patch.dict(os.environ, {"INFERNO_EMAIL_MODE": "editor"})
    def test_action_pulse_still_writes_reports_without_mail(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(pulse, "ACTION_PULSE_FILE", Path(tmp)/"pulse.json"), \
             patch.object(pulse, "ACTION_PULSE_TEXT_FILE", Path(tmp)/"pulse.txt"), \
             patch.object(pulse, "load_env_file"), \
             patch.object(pulse, "smtp_settings") as settings:
            payload = {"verdict": "blocked", "generatedAt": "2026-09-27T12:00:00-06:00"}
            payload["delivery"] = pulse.send_action_pulse(payload, force=True)
            pulse.save_action_pulse(payload)
            self.assertEqual(payload["delivery"]["status"], "suppressed-editor-mode")
            self.assertTrue((Path(tmp)/"pulse.txt").read_text())
            settings.assert_not_called()

    @patch.dict(os.environ, {"INFERNO_EMAIL_MODE": "editor"})
    def test_action_failure_sends_after_routine_already_sent(self):
        with patch.object(pulse, "load_env_file"), \
             patch.object(pulse, "load_state", return_value={"sentByKey": {"day:open": {}}}), \
             patch.object(pulse, "sent_key", return_value="day:open"), \
             patch.object(pulse, "smtp_configured", return_value=True), \
             patch.object(pulse, "smtp_settings", return_value={"from_addr": "a@example.com", "to_addr": "b@example.com", "host": "test", "port": 465, "username": "", "use_ssl": True}), \
             patch.object(pulse.smtplib, "SMTP_SSL") as smtp, \
             patch.object(pulse, "save_state"):
            result = pulse.send_action_pulse({"phase": "open", "dailyLoop": {"failedCount": 1}})
            self.assertTrue(result["sent"])
            smtp.return_value.__enter__.return_value.send_message.assert_called_once()

if __name__ == "__main__":
    unittest.main()
