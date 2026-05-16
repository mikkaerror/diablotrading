from __future__ import annotations

import unittest
from email.message import EmailMessage
from unittest.mock import patch

import inferno_approval_inbox as approval_inbox
from inferno_approval_queue import ensure_queue_tokens


class FakeImapClient:
    """Small IMAP test double for one-message polling flows."""

    def __init__(self, host: str, port: int, *, raw_message: bytes) -> None:
        self.host = host
        self.port = port
        self.raw_message = raw_message
        self.marked_seen = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def login(self, username: str, password: str) -> tuple[str, list[bytes]]:
        self.username = username
        self.password = password
        return ("OK", [b"logged-in"])

    def select(self, mailbox: str) -> tuple[str, list[bytes]]:
        self.mailbox = mailbox
        return ("OK", [b"1"])

    def uid(self, command: str, *args):
        if command == "search":
            return ("OK", [b"101"])
        if command == "fetch":
            return ("OK", [(b"101 (RFC822 {123})", self.raw_message)])
        if command == "store":
            self.marked_seen = True
            return ("OK", [b"stored"])
        raise AssertionError(f"unexpected command {command}")


class InfernoApprovalInboxTests(unittest.TestCase):
    """Verify inbox replies can drive the approval desk safely."""

    def test_imap_settings_derives_gmail_defaults_from_smtp(self) -> None:
        with patch.object(
            approval_inbox,
            "smtp_settings",
            return_value={
                "host": "smtp.gmail.com",
                "username": "operator@example.com",
                "password": "app-password",
                "from_addr": "operator@example.com",
                "to_addr": "operator@example.com",
            },
        ):
            settings = approval_inbox.imap_settings()

        self.assertEqual(settings["host"], "imap.gmail.com")
        self.assertEqual(settings["username"], "operator@example.com")
        self.assertIn("operator@example.com", settings["allowlist"])

    def test_poll_approval_inbox_applies_simple_approve_reply(self) -> None:
        queue = ensure_queue_tokens(
            {
                "generatedAt": "2026-05-10T06:00:00-06:00",
                "items": [{"ticker": "CEG", "approvalStatus": "pending"}],
            }
        )
        token = queue["items"][0]["approvalToken"]
        message = EmailMessage()
        message["Subject"] = f"[Inferno Approval] CEG {token}"
        message["From"] = "operator@example.com"
        message["To"] = "operator@example.com"
        message.set_content("approve")
        raw = message.as_bytes()

        def fake_imap(host: str, port: int):
            return FakeImapClient(host, port, raw_message=raw)

        saved_queues = []
        refreshed = []
        saved_reports = []
        saved_states = []
        state = {"processedUids": {}}

        with (
            patch.object(approval_inbox, "load_env_file"),
            patch.object(
                approval_inbox,
                "imap_settings",
                return_value={
                    "host": "imap.gmail.com",
                    "port": 993,
                    "username": "operator@example.com",
                    "password": "app-password",
                    "mailbox": "INBOX",
                    "allowlist": ["operator@example.com"],
                    "search": "UNSEEN",
                    "max_messages": 10,
                },
            ),
            patch.object(approval_inbox, "imap_configured", return_value=True),
            patch.object(approval_inbox, "load_queue", return_value=queue),
            patch.object(approval_inbox, "save_queue", side_effect=lambda payload: saved_queues.append(payload)),
            patch.object(approval_inbox, "refresh_execution_queue", side_effect=lambda: refreshed.append(True)),
            patch.object(approval_inbox, "load_state", return_value=state),
            patch.object(approval_inbox, "save_state", side_effect=lambda payload: saved_states.append(payload)),
            patch.object(approval_inbox, "save_report", side_effect=lambda payload: saved_reports.append(payload)),
            patch.object(approval_inbox.imaplib, "IMAP4_SSL", side_effect=fake_imap),
        ):
            report = approval_inbox.poll_approval_inbox()

        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "applied")
        self.assertEqual(report["appliedCount"], 1)
        self.assertEqual(queue["items"][0]["approvalStatus"], "approved")
        self.assertEqual(len(saved_queues), 1)
        self.assertEqual(len(refreshed), 1)
        self.assertTrue(saved_reports)
        self.assertTrue(saved_states)

    def test_looks_like_approval_mail_requires_reply_or_command_prefix(self) -> None:
        self.assertTrue(
            approval_inbox.looks_like_approval_mail(
                "Re: Morning Conviction Brief",
                "sounds good",
            )
        )
        self.assertTrue(
            approval_inbox.looks_like_approval_mail(
                "Random note",
                "APPROVE CEG 11111234",
            )
        )
        self.assertFalse(
            approval_inbox.looks_like_approval_mail(
                "[DIABLO TRADING] Strike Plan - 2026-05-10",
                "Rejected: 43 -> rejected",
            )
        )

    def test_is_self_prompt_mail_detects_outbound_prompt_template(self) -> None:
        self.assertTrue(
            approval_inbox.is_self_prompt_mail(
                "[Inferno Approval] CEG 11111234",
                "Reply with one word only:\napprove\nor\ndeny\n\nThe subject already carries the exact queue token.",
            )
        )
        self.assertFalse(
            approval_inbox.is_self_prompt_mail(
                "Re: [Inferno Approval] CEG 11111234",
                "approve",
            )
        )


if __name__ == "__main__":
    unittest.main()
