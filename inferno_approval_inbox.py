from __future__ import annotations

"""Email-reply approval ingestor for the Inferno approval desk.

This adapter lets the operator approve or deny names by replying to a brief
email instead of dropping back into the terminal. It is intentionally narrow:

- reads only the inbox/mailbox configured by the existing SMTP app password
- accepts commands only from approved sender addresses
- can only mutate the approval queue + derived execution queue
- never touches broker authority or live order routing
"""

import argparse
import email
import imaplib
import json
import os
import re
from email.header import decode_header, make_header
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from inferno_io import atomic_write_json, atomic_write_text
from inferno_approval_queue import apply_reply_commands, load_queue, refresh_execution_queue, save_queue
from inferno_config import local_now
from server import DATA_DIR, REPORTS_DIR, SMTP_ENV_FILE, ensure_dirs, load_env_file, smtp_settings


APPROVAL_INBOX_FILE = DATA_DIR / "inferno_approval_inbox.json"
APPROVAL_INBOX_TEXT_FILE = REPORTS_DIR / "approval_inbox_latest.txt"
APPROVAL_INBOX_STATE_FILE = DATA_DIR / "inferno_approval_inbox_state.json"
APPROVAL_REPLY_PREFIX_RE = re.compile(r"^(approve|deny|reject|pending|reset|yes|no)\b", re.IGNORECASE)
APPROVAL_PROMPT_MARKERS = (
    "reply with one word only:",
    "the subject already carries the exact queue token",
)


def _imap_host_default(smtp_host: str) -> str:
    """Derive a safe IMAP host from the already-configured SMTP host."""
    host = (smtp_host or "").strip().lower()
    if not host:
        return ""
    if "gmail.com" in host:
        return "imap.gmail.com"
    if host.startswith("smtp."):
        return f"imap.{host[5:]}"
    return host


def imap_settings() -> dict[str, Any]:
    """Build inbound-mail settings from SMTP credentials plus optional overrides."""
    smtp = smtp_settings()
    username = os.getenv("IMAP_USERNAME", "").strip() or smtp.get("username") or smtp.get("from_addr")
    password = os.getenv("IMAP_PASSWORD", "").strip() or smtp.get("password")
    allowed_from = os.getenv("APPROVAL_INBOX_ALLOWED_FROM", "").strip()
    allowlist = []
    for raw in [allowed_from, smtp.get("from_addr", ""), smtp.get("to_addr", "")]:
        address = parseaddr(raw)[1].strip().lower()
        if address and address not in allowlist:
            allowlist.append(address)
    return {
        "host": os.getenv("IMAP_HOST", "").strip() or _imap_host_default(str(smtp.get("host") or "")),
        "port": int(os.getenv("IMAP_PORT", "993") or "993"),
        "username": username.strip(),
        "password": password.strip(),
        "mailbox": os.getenv("APPROVAL_INBOX_MAILBOX", "INBOX").strip() or "INBOX",
        "allowlist": allowlist,
        "search": os.getenv("APPROVAL_INBOX_SEARCH", "UNSEEN").strip() or "UNSEEN",
        "max_messages": int(os.getenv("APPROVAL_INBOX_MAX_MESSAGES", "25") or "25"),
    }


def imap_configured() -> bool:
    """Return True when inbound email can be checked safely."""
    settings = imap_settings()
    return all([settings["host"], settings["username"], settings["password"]])


def load_state() -> dict[str, Any]:
    """Load the inbox poller state ledger."""
    if not APPROVAL_INBOX_STATE_FILE.exists():
        return {"processedUids": {}}
    try:
        payload = json.loads(APPROVAL_INBOX_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"processedUids": {}}
    payload.setdefault("processedUids", {})
    return payload


def save_state(state: dict[str, Any]) -> None:
    """Persist the inbox poller state ledger."""
    atomic_write_json(APPROVAL_INBOX_STATE_FILE, state)


def _decoded_header(value: str | None) -> str:
    """Decode an RFC 2047 header into plain text."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001
        return str(value)


def extract_plain_text(message: email.message.Message) -> str:
    """Extract the first plain-text body from an email message."""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_type() != "text/plain":
                continue
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            try:
                return payload.decode(charset, errors="replace")
            except Exception:  # noqa: BLE001
                return payload.decode("utf-8", errors="replace")
        return ""
    payload = message.get_payload(decode=True) or b""
    charset = message.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except Exception:  # noqa: BLE001
        return payload.decode("utf-8", errors="replace")


def looks_like_approval_mail(subject: str, body: str) -> bool:
    """Return True when a message plausibly belongs to the approval loop."""
    subject_lower = str(subject or "").strip().lower()
    if subject_lower.startswith("re:") or "[inferno approval]" in subject_lower:
        return True
    for line in str(body or "").splitlines():
        stripped = line.strip().lower()
        if not stripped:
            continue
        if APPROVAL_REPLY_PREFIX_RE.match(stripped):
            return True
    return False


def is_self_prompt_mail(subject: str, body: str) -> bool:
    """Return true when the message is one of our own prompt emails."""
    lowered_subject = str(subject or "").strip().lower()
    lowered_body = str(body or "").strip().lower()
    if not lowered_subject.startswith("[inferno approval]"):
        return False
    return any(marker in lowered_body for marker in APPROVAL_PROMPT_MARKERS)


def approval_inbox_text(report: dict[str, Any]) -> str:
    """Render a short operator-facing poll report."""
    lines = [
        "Inferno Approval Inbox",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Status: {report.get('status')}",
        f"Checked: {report.get('checkedCount', 0)}",
        f"Applied: {report.get('appliedCount', 0)}",
        f"Skipped: {report.get('skippedCount', 0)}",
    ]
    if report.get("error"):
        lines.append(f"Error: {report.get('error')}")
    if report.get("messages"):
        lines.extend(["", "Messages:"])
        for message in report.get("messages") or []:
            lines.append(
                f"- uid {message.get('uid')}: {message.get('status')} | "
                f"from {message.get('from')} | subject {message.get('subject')}"
            )
            for command in message.get("commands") or []:
                lines.append(
                    f"    {command.get('line')} -> "
                    f"{command.get('status')} ({command.get('ticker') or command.get('reason')})"
                )
    return "\n".join(lines).rstrip() + "\n"


def save_report(report: dict[str, Any]) -> None:
    """Persist inbox polling artifacts."""
    ensure_dirs()
    atomic_write_json(APPROVAL_INBOX_FILE, report)
    atomic_write_text(APPROVAL_INBOX_TEXT_FILE, approval_inbox_text(report))


def poll_approval_inbox(*, mark_seen: bool = True) -> dict[str, Any]:
    """Poll the inbox for approve/deny replies and apply them safely."""
    load_env_file(SMTP_ENV_FILE)
    ensure_dirs()
    settings = imap_settings()
    if not imap_configured():
        report = {
            "generatedAt": local_now().isoformat(),
            "status": "not-configured",
            "checkedCount": 0,
            "appliedCount": 0,
            "skippedCount": 0,
            "messages": [],
            "ok": True,
        }
        save_report(report)
        return report

    queue = load_queue()
    state = load_state()
    processed_uids = state.setdefault("processedUids", {})
    checked_count = 0
    applied_count = 0
    skipped_count = 0
    message_reports: list[dict[str, Any]] = []
    queue_changed = False

    try:
        with imaplib.IMAP4_SSL(settings["host"], settings["port"]) as client:
            client.login(settings["username"], settings["password"])
            client.select(settings["mailbox"])
            status, response = client.uid("search", None, settings["search"])
            if status != "OK":
                raise RuntimeError(f"IMAP search failed: {status}")
            uids = [uid for uid in (response[0] or b"").split() if uid]
            # Work newest-first so the desk sees the latest reply first.
            for uid in reversed(uids[-settings["max_messages"] :]):
                uid_text = uid.decode("utf-8", errors="ignore")
                if uid_text in processed_uids:
                    continue
                checked_count += 1
                fetch_status, fetched = client.uid("fetch", uid, "(RFC822)")
                if fetch_status != "OK" or not fetched:
                    skipped_count += 1
                    processed_uids[uid_text] = {
                        "status": "fetch-failed",
                        "processedAt": local_now().isoformat(),
                    }
                    continue
                raw_message = b""
                for part in fetched:
                    if isinstance(part, tuple) and len(part) >= 2:
                        raw_message = part[1]
                        break
                if not raw_message:
                    skipped_count += 1
                    processed_uids[uid_text] = {
                        "status": "empty-message",
                        "processedAt": local_now().isoformat(),
                    }
                    continue
                message = email.message_from_bytes(raw_message)
                subject = _decoded_header(message.get("Subject"))
                sender = parseaddr(message.get("From") or "")[1].strip().lower()
                body = extract_plain_text(message)
                report_row = {
                    "uid": uid_text,
                    "from": sender,
                    "subject": subject,
                    "status": "ignored",
                    "commands": [],
                }
                if settings["allowlist"] and sender not in settings["allowlist"]:
                    skipped_count += 1
                    report_row["status"] = "sender-not-allowed"
                    processed_uids[uid_text] = {
                        "status": report_row["status"],
                        "processedAt": local_now().isoformat(),
                    }
                    message_reports.append(report_row)
                    continue
                if is_self_prompt_mail(subject, body):
                    skipped_count += 1
                    report_row["status"] = "self-prompt"
                    processed_uids[uid_text] = {
                        "status": report_row["status"],
                        "processedAt": local_now().isoformat(),
                    }
                    if mark_seen:
                        client.uid("store", uid, "+FLAGS", "(\\Seen)")
                    message_reports.append(report_row)
                    continue
                if not looks_like_approval_mail(subject, body):
                    skipped_count += 1
                    report_row["status"] = "not-approval-mail"
                    processed_uids[uid_text] = {
                        "status": report_row["status"],
                        "processedAt": local_now().isoformat(),
                    }
                    message_reports.append(report_row)
                    continue

                ingest = apply_reply_commands(queue, body, subject=subject)
                report_row["commands"] = ingest.get("commands") or []
                if ingest.get("matchedCount", 0) <= 0:
                    skipped_count += 1
                    report_row["status"] = "no-command-found"
                    processed_uids[uid_text] = {
                        "status": report_row["status"],
                        "processedAt": local_now().isoformat(),
                    }
                    message_reports.append(report_row)
                    continue

                queue_changed = bool(ingest.get("changed")) or queue_changed
                if ingest.get("changed"):
                    applied_count += len([entry for entry in ingest.get("commands") or [] if entry.get("ok")])
                    report_row["status"] = "applied"
                    if mark_seen:
                        client.uid("store", uid, "+FLAGS", "(\\Seen)")
                else:
                    skipped_count += 1
                    report_row["status"] = "parsed-no-change"
                processed_uids[uid_text] = {
                    "status": report_row["status"],
                    "processedAt": local_now().isoformat(),
                }
                message_reports.append(report_row)
    except Exception as exc:  # noqa: BLE001
        report = {
            "generatedAt": local_now().isoformat(),
            "status": "poll-failed",
            "error": str(exc),
            "checkedCount": checked_count,
            "appliedCount": applied_count,
            "skippedCount": skipped_count,
            "messages": message_reports,
            "ok": False,
        }
        save_report(report)
        save_state(state)
        return report

    if queue_changed:
        save_queue(queue)
        refresh_execution_queue()
    state["lastCheckedAt"] = local_now().isoformat()
    save_state(state)
    report = {
        "generatedAt": local_now().isoformat(),
        "status": "applied" if applied_count else "idle",
        "checkedCount": checked_count,
        "appliedCount": applied_count,
        "skippedCount": skipped_count,
        "messages": message_reports,
        "ok": True,
    }
    save_report(report)
    return report


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the inbox poller."""
    parser = argparse.ArgumentParser(
        description="Poll the approval inbox for approve/deny replies and update the queue safely."
    )
    parser.add_argument("command", nargs="?", default="poll", choices=("poll", "status"))
    parser.add_argument("--leave-unread", action="store_true", help="Do not mark successfully-applied emails as read.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and APPROVAL_INBOX_TEXT_FILE.exists():
        print(APPROVAL_INBOX_TEXT_FILE.read_text(encoding="utf-8"))
        latest = json.loads(APPROVAL_INBOX_FILE.read_text(encoding="utf-8")) if APPROVAL_INBOX_FILE.exists() else {}
        return 0 if latest.get("ok", True) else 1
    report = poll_approval_inbox(mark_seen=not args.leave_unread)
    print(approval_inbox_text(report))
    return 0 if report.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
