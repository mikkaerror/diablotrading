from __future__ import annotations

import unittest
from unittest.mock import patch

import inferno_approval_dispatch as approval_dispatch
from inferno_approval_queue import ensure_queue_tokens


class InfernoApprovalDispatchTests(unittest.TestCase):
    """Verify one-word approval prompts are deduped and reply-friendly."""

    def test_build_prompt_subject_contains_ticker_and_token(self) -> None:
        subject = approval_dispatch.build_prompt_subject(
            {"ticker": "CEG", "approvalToken": "ABC12345"}
        )
        self.assertEqual(subject, "[Inferno Approval] CEG ABC12345")

    def test_dispatch_sends_only_unsent_tokens(self) -> None:
        queue = ensure_queue_tokens(
            {
                "generatedAt": "2026-05-10T06:00:00-06:00",
                "items": [
                    {"ticker": "CEG", "approvalStatus": "pending"},
                    {"ticker": "THR", "approvalStatus": "pending"},
                ],
            }
        )
        ceg_token = queue["items"][0]["approvalToken"]
        thr_token = queue["items"][1]["approvalToken"]
        briefs = {
            "briefs": [
                {"ticker": "CEG", "tracker": {"readiness": 99}, "considerations": ["hot"]},
                {"ticker": "THR", "tracker": {"readiness": 95}, "considerations": ["watch"]},
            ]
        }
        sent = []
        state = {
            "sentByToken": {
                ceg_token: {"ticker": "CEG", "sentAt": "2026-05-10T06:15:00-06:00"}
            }
        }
        saved_states = []
        saved_reports = []

        with (
            patch.object(approval_dispatch, "load_queue", return_value=queue),
            patch.object(approval_dispatch, "build_decision_briefs", return_value=briefs),
            patch.object(approval_dispatch, "load_state", return_value=state),
            patch.object(approval_dispatch, "save_state", side_effect=lambda payload: saved_states.append(payload)),
            patch.object(approval_dispatch, "save_report", side_effect=lambda payload: saved_reports.append(payload)),
            patch.object(approval_dispatch, "smtp_configured", return_value=True),
            patch.object(approval_dispatch, "send_operator_email", side_effect=lambda subject, text, html: sent.append(subject)),
        ):
            report = approval_dispatch.dispatch_pending_approval_prompts()

        self.assertTrue(report["ok"])
        self.assertEqual(report["sentCount"], 1)
        self.assertEqual(report["skippedCount"], 1)
        self.assertEqual(sent, [f"[Inferno Approval] THR {thr_token}"])
        self.assertTrue(saved_states)
        self.assertTrue(saved_reports)

    def test_dispatch_reports_missing_smtp(self) -> None:
        queue = {
            "generatedAt": "2026-05-10T06:00:00-06:00",
            "items": [{"ticker": "CEG", "approvalStatus": "pending", "approvalToken": "AAA11111"}],
        }
        saved_reports = []
        with (
            patch.object(approval_dispatch, "load_queue", return_value=queue),
            patch.object(approval_dispatch, "smtp_configured", return_value=False),
            patch.object(approval_dispatch, "save_report", side_effect=lambda payload: saved_reports.append(payload)),
        ):
            report = approval_dispatch.dispatch_pending_approval_prompts()

        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "smtp-not-configured")
        self.assertTrue(saved_reports)


if __name__ == "__main__":
    unittest.main()
