from __future__ import annotations

import unittest

from inferno_approval_queue import (
    apply_reply_commands,
    ensure_queue_tokens,
    extract_authored_reply,
    find_item,
)


class InfernoApprovalQueueTests(unittest.TestCase):
    """Verify tokenized approvals stay safe and easy to operate."""

    def test_ensure_queue_tokens_stamps_reply_shortcuts(self) -> None:
        queue = ensure_queue_tokens(
            {
                "generatedAt": "2026-05-10T06:00:00-06:00",
                "items": [
                    {"ticker": "CEG", "approvalStatus": "pending"},
                ],
            }
        )
        item = queue["items"][0]
        self.assertEqual(item["ticker"], "CEG")
        self.assertEqual(len(item["approvalToken"]), 8)
        self.assertIn(item["approvalToken"], item["replyApprove"])
        self.assertIn(item["approvalToken"], item["replyDeny"])

    def test_apply_reply_commands_accepts_subject_context_for_simple_approve(self) -> None:
        queue = ensure_queue_tokens(
            {
                "generatedAt": "2026-05-10T06:00:00-06:00",
                "items": [
                    {"ticker": "CEG", "approvalStatus": "pending"},
                    {"ticker": "THR", "approvalStatus": "pending"},
                ],
            }
        )
        ceg = find_item(queue, "CEG")
        self.assertIsNotNone(ceg)

        result = apply_reply_commands(
            queue,
            "approve",
            subject=f"[Inferno Approval] {ceg['ticker']} {ceg['approvalToken']}",
        )

        self.assertTrue(result["changed"])
        self.assertEqual(result["matchedCount"], 1)
        self.assertEqual(find_item(queue, "CEG")["approvalStatus"], "approved")
        self.assertEqual(find_item(queue, "THR")["approvalStatus"], "pending")

    def test_apply_reply_commands_ignores_quoted_original_examples(self) -> None:
        queue = ensure_queue_tokens(
            {
                "generatedAt": "2026-05-10T06:00:00-06:00",
                "items": [
                    {"ticker": "CEG", "approvalStatus": "pending"},
                ],
            }
        )
        token = queue["items"][0]["approvalToken"]
        reply = "\n".join(
            [
                "deny",
                "",
                "On Sat, May 10, 2026 at 6:02 AM Inferno wrote:",
                f"> APPROVE CEG {token}",
            ]
        )

        result = apply_reply_commands(
            queue,
            reply,
            subject=f"[Inferno Approval] CEG {token}",
        )

        self.assertEqual(result["matchedCount"], 1)
        self.assertEqual(find_item(queue, "CEG")["approvalStatus"], "rejected")
        self.assertEqual(
            extract_authored_reply(reply),
            "deny",
        )

    def test_apply_reply_commands_rejects_conflicting_commands_for_same_subject(self) -> None:
        queue = ensure_queue_tokens(
            {
                "generatedAt": "2026-05-10T06:00:00-06:00",
                "items": [
                    {"ticker": "CEG", "approvalStatus": "pending"},
                ],
            }
        )
        token = queue["items"][0]["approvalToken"]
        result = apply_reply_commands(
            queue,
            "approve\n\ndeny",
            subject=f"[Inferno Approval] CEG {token}",
        )

        self.assertFalse(result["changed"])
        self.assertEqual(result["matchedCount"], 0)
        self.assertEqual(find_item(queue, "CEG")["approvalStatus"], "pending")
        self.assertTrue(any(entry.get("reason") == "conflicting-commands" for entry in result["commands"]))


if __name__ == "__main__":
    unittest.main()
