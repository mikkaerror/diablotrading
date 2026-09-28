from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_approval_dispatch as dispatch
import inferno_approval_queue as queue_module
import inferno_approval_inbox as inbox
import morning_inferno_pipeline as morning
from inferno_cloud_state import DEFAULT_ARTIFACT_PATHS


def queue(stamp="2026-09-24T07:00:00-06:00", event="2026-09-25"):
    return queue_module.ensure_queue_tokens({"generatedAt": stamp, "items": [{
        "ticker": "ACN", "approvalStatus": "pending", "nextEarnings": event,
        "primaryRoute": "Straddle", "secondaryRoute": "Watch", "setupRec": "Watch",
        "daysUntilEarnings": 1, "pendingSince": stamp}]})


class ApprovalEmailDedupeTests(unittest.TestCase):
    def test_rebuild_preserves_pending_token_and_reply_parser(self):
        original = queue()
        refreshed = queue_module.reuse_pending_tokens(queue("2026-09-24T13:00:00-06:00"), original)
        old = original["items"][0]
        self.assertEqual(refreshed["items"][0]["approvalToken"], old["approvalToken"])
        self.assertEqual(refreshed["items"][0]["pendingSince"], old["pendingSince"])
        subject = dispatch.build_prompt_subject(old)
        self.assertTrue(inbox.looks_like_approval_mail("Re: " + subject, "approve"))
        parsed = queue_module.apply_reply_commands(refreshed, "approve", subject="Re: " + subject)
        self.assertEqual(parsed["matchedCount"], 1)
        self.assertEqual(refreshed["items"][0]["approvalStatus"], "approved")
        self.assertEqual(original["items"][0]["approvalStatus"], "pending")

    def test_new_event_route_or_resolved_request_cannot_reuse_old_token(self):
        old = queue()
        for change in ({"nextEarnings": "2026-12-25"}, {"primaryRoute": "Call"}, {"approvalStatus": "approved"}):
            with self.subTest(change=change):
                previous = deepcopy(old)
                new = queue("2026-09-24T13:00:00-06:00")
                if "approvalStatus" in change:
                    previous["items"][0].update(change)
                else:
                    new["items"][0].update(change)
                refreshed = queue_module.reuse_pending_tokens(new, previous)
                self.assertNotEqual(refreshed["items"][0]["approvalToken"], old["items"][0]["approvalToken"])

    def test_legacy_countdown_identity_is_frozen_across_days(self):
        old = queue(); old["items"][0].pop("nextEarnings")
        new = queue("2026-09-25T07:00:00-06:00"); new["items"][0].pop("nextEarnings")
        new["items"][0]["daysUntilEarnings"] = 0
        result = queue_module.reuse_pending_tokens(new, old)
        self.assertEqual(result["items"][0]["approvalToken"], old["items"][0]["approvalToken"])
        self.assertEqual(queue_module.approval_event_key(result["items"][0]), "earnings:2026-09-25")

    def test_real_queue_writer_reuses_pending_request(self):
        row = dict(ticker="ACN", setupRec="Watch", readiness=95, daysUntilEarnings=1,
                   signalTrigger=True, rec1="Straddle", rec2="Watch", nextEarnings="2026-09-25")
        with tempfile.TemporaryDirectory() as tmp, patch.object(morning, "APPROVAL_QUEUE_FILE", Path(tmp)/"queue.json"):
            first = morning.write_approval_queue({"generatedAt": "2026-09-24T07:00:00-06:00", "rows": [row], "reviewQueueTickers": ["ACN"]})
            later = morning.write_approval_queue({"generatedAt": "2026-09-24T13:00:00-06:00", "rows": [row], "reviewQueueTickers": ["ACN"]})
        self.assertEqual(first["items"][0]["approvalToken"], later["items"][0]["approvalToken"])

    def test_daily_cap_survives_new_token_force_and_state_reload_both_modes(self):
        for mode in ("full", "editor"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp, \
                 patch.dict(os.environ, {"INFERNO_EMAIL_MODE": mode}), \
                 patch.object(dispatch, "APPROVAL_DISPATCH_STATE_FILE", Path(tmp)/"state.json"), \
                 patch.object(dispatch, "load_env_file"), patch.object(dispatch, "save_report"), \
                 patch.object(dispatch, "build_decision_briefs", return_value={}), \
                 patch.object(dispatch, "smtp_configured", return_value=True), \
                 patch.object(dispatch, "send_operator_email") as send, \
                 patch.object(dispatch, "local_now", return_value=datetime.fromisoformat("2026-09-24T13:00:00-06:00")) as now, \
                 patch.object(dispatch, "load_queue", return_value=queue()) as load:
                self.assertEqual(dispatch.dispatch_pending_approval_prompts()["sentCount"], 1)
                load.return_value = queue("2026-09-24T13:00:00-06:00")
                self.assertEqual(dispatch.dispatch_pending_approval_prompts(force=True)["sentCount"], 0)
                self.assertEqual(send.call_count, 1)
                load.return_value = queue("2026-09-24T14:00:00-06:00", "2026-12-25")
                self.assertEqual(dispatch.dispatch_pending_approval_prompts()["sentCount"], 1)
                now.return_value = datetime.fromisoformat("2026-09-25T07:00:00-06:00")
                self.assertEqual(dispatch.dispatch_pending_approval_prompts(force=True)["sentCount"], 1)

    def test_uncertain_smtp_send_is_not_retried_same_day(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(dispatch, "APPROVAL_DISPATCH_STATE_FILE", Path(tmp)/"state.json"), \
             patch.object(dispatch, "load_env_file"), patch.object(dispatch, "save_report"), \
             patch.object(dispatch, "build_decision_briefs", return_value={}), \
             patch.object(dispatch, "smtp_configured", return_value=True), \
             patch.object(dispatch, "load_queue", return_value=queue()), \
             patch.object(dispatch, "send_operator_email", side_effect=TimeoutError("uncertain")) as send:
            self.assertEqual(dispatch.dispatch_pending_approval_prompts()["status"], "send-failed")
            self.assertEqual(dispatch.dispatch_pending_approval_prompts(force=True)["sentCount"], 0)
            self.assertEqual(send.call_count, 1)

    def test_concurrent_dispatchers_share_one_reservation(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(dispatch, "APPROVAL_DISPATCH_STATE_FILE", Path(tmp)/"state.json"), \
             patch.object(dispatch, "load_env_file"), patch.object(dispatch, "save_report"), \
             patch.object(dispatch, "build_decision_briefs", return_value={}), \
             patch.object(dispatch, "smtp_configured", return_value=True), \
             patch.object(dispatch, "load_queue", side_effect=queue), \
             patch.object(dispatch, "send_operator_email") as send, ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: dispatch.dispatch_pending_approval_prompts(force=True), range(2)))
            self.assertEqual(sum(result["sentCount"] for result in results), 1)
            self.assertEqual(send.call_count, 1)

    def test_corrupt_state_blocks_delivery(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(dispatch, "APPROVAL_DISPATCH_STATE_FILE", Path(tmp)/"state.json"), \
             patch.object(dispatch, "load_env_file"), patch.object(dispatch, "save_report"), \
             patch.object(dispatch, "build_decision_briefs", return_value={}), \
             patch.object(dispatch, "smtp_configured", return_value=True), \
             patch.object(dispatch, "load_queue", return_value=queue()), \
             patch.object(dispatch, "send_operator_email") as send:
            (Path(tmp)/"state.json").write_text("broken JSON")
            self.assertEqual(dispatch.dispatch_pending_approval_prompts()["status"], "state-unreadable")
            send.assert_not_called()

    def test_legacy_sent_record_uses_denver_day_even_with_rotated_token(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(dispatch, "APPROVAL_DISPATCH_STATE_FILE", Path(tmp)/"state.json"), \
             patch.object(dispatch, "load_env_file"), patch.object(dispatch, "save_report"), \
             patch.object(dispatch, "build_decision_briefs", return_value={}), \
             patch.object(dispatch, "smtp_configured", return_value=True), \
             patch.object(dispatch, "load_queue", return_value=queue()), \
             patch.object(dispatch, "local_now", return_value=datetime.fromisoformat("2026-09-25T03:00:00+00:00")), \
             patch.object(dispatch, "load_state", return_value={"sentByToken": {"OLDTOKEN": {"ticker": "ACN", "sentAt": "2026-09-24T07:00:00-06:00"}}}), \
             patch.object(dispatch, "send_operator_email") as send:
            self.assertEqual(dispatch.dispatch_pending_approval_prompts(force=True)["sentCount"], 0)
            send.assert_not_called()

    def test_cloud_restarts_retain_queue_and_delivery_history(self):
        self.assertIn("data/inferno_approval_queue.json", DEFAULT_ARTIFACT_PATHS)
        self.assertIn("data/inferno_approval_dispatch_state.json", DEFAULT_ARTIFACT_PATHS)

if __name__ == "__main__":
    unittest.main()
