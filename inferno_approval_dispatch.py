from __future__ import annotations

"""One-word approval prompt dispatcher for the Inferno desk.

This module sends one compact email per pending approval candidate so the
operator can simply reply ``approve`` or ``deny``. The subject carries the
queue token, which lets the inbox parser safely resolve a one-word reply
without copy/paste friction.

Safety contract:
- coordination only; cannot place trades or broaden broker authority
- sends only to the configured operator inbox
- deduplicates by queue token so maintenance sweeps stay quiet
"""

import argparse
import json
import smtplib
from email.message import EmailMessage
from typing import Any

from inferno_io import atomic_write_json, atomic_write_text
from inferno_approval_queue import ensure_queue_tokens, load_queue
from inferno_config import local_now
from inferno_decision_brief import build_decision_briefs
from server import DATA_DIR, REPORTS_DIR, SMTP_ENV_FILE, ensure_dirs, load_env_file, smtp_configured, smtp_settings


APPROVAL_DISPATCH_FILE = DATA_DIR / "inferno_approval_dispatch.json"
APPROVAL_DISPATCH_TEXT_FILE = REPORTS_DIR / "approval_dispatch_latest.txt"
APPROVAL_DISPATCH_STATE_FILE = DATA_DIR / "inferno_approval_dispatch_state.json"
APPROVAL_SUBJECT_PREFIX = "[Inferno Approval]"


def load_state() -> dict[str, Any]:
    """Load dispatch history keyed by approval token."""
    if not APPROVAL_DISPATCH_STATE_FILE.exists():
        return {"sentByToken": {}}
    try:
        payload = json.loads(APPROVAL_DISPATCH_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"sentByToken": {}}
    if not isinstance(payload, dict):
        return {"sentByToken": {}}
    payload.setdefault("sentByToken", {})
    return payload


def save_state(payload: dict[str, Any]) -> None:
    """Persist dispatch history."""
    ensure_dirs()
    atomic_write_json(APPROVAL_DISPATCH_STATE_FILE, payload)


def approval_dispatch_text(report: dict[str, Any]) -> str:
    """Render a human-readable dispatch summary."""
    lines = [
        "Inferno Approval Dispatch",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Status: {report.get('status')}",
        f"Pending count: {report.get('pendingCount', 0)}",
        f"Sent count: {report.get('sentCount', 0)}",
        f"Skipped count: {report.get('skippedCount', 0)}",
        "",
    ]
    for entry in report.get("sent") or []:
        lines.append(
            f"SENT {entry.get('ticker')} token={entry.get('approvalToken')} "
            f"subject={entry.get('subject')}"
        )
    for entry in report.get("skipped") or []:
        lines.append(
            f"SKIP {entry.get('ticker')} token={entry.get('approvalToken')} "
            f"reason={entry.get('reason')}"
        )
    if report.get("error"):
        lines.extend(["", f"Error: {report.get('error')}"])
    return "\n".join(lines).rstrip() + "\n"


def save_report(report: dict[str, Any]) -> None:
    """Persist dispatch artifacts."""
    ensure_dirs()
    atomic_write_json(APPROVAL_DISPATCH_FILE, report)
    atomic_write_text(APPROVAL_DISPATCH_TEXT_FILE, approval_dispatch_text(report))


def build_prompt_subject(item: dict[str, Any]) -> str:
    """Build the reply-friendly approval subject for one ticker."""
    ticker = str(item.get("ticker") or "").strip().upper()
    token = str(item.get("approvalToken") or "").strip().upper()
    return f"{APPROVAL_SUBJECT_PREFIX} {ticker} {token}".strip()


def build_prompt_text(item: dict[str, Any], brief: dict[str, Any] | None) -> str:
    """Build the plain-text version of one approval prompt."""
    tracker = (brief or {}).get("tracker") or {}
    edge = (brief or {}).get("edge") or {}
    live = (brief or {}).get("liveBook") or {}
    considerations = (brief or {}).get("considerations") or []
    lines = [
        f"Inferno approval request for {item.get('ticker')}",
        "",
        "Reply with one word only:",
        "approve",
        "or",
        "deny",
        "",
        "The subject already carries the exact queue token, so a one-word reply is enough.",
        "",
        f"Readiness: {tracker.get('readiness')}%",
        f"Confidence: {tracker.get('confidence')}",
        f"Days to earnings: {tracker.get('daysUntilEarnings')}",
        f"Primary route: {item.get('primaryRoute')}",
        f"Secondary route: {item.get('secondaryRoute')}",
        f"Trend: {tracker.get('trend')}",
        f"RVOL: {tracker.get('rvol')}",
        f"Edge bucket: {edge.get('category')} | lane: {edge.get('lane')} | score: {edge.get('edgeScore')}",
        f"Live posture: {live.get('posture') or '-'} | held: {live.get('held')}",
    ]
    if considerations:
        lines.extend(["", "Fast context:"])
        lines.extend(f"- {line}" for line in considerations[:3])
    return "\n".join(lines).rstrip() + "\n"


def build_prompt_html(item: dict[str, Any], brief: dict[str, Any] | None) -> str:
    """Build the HTML version of one approval prompt."""
    tracker = (brief or {}).get("tracker") or {}
    edge = (brief or {}).get("edge") or {}
    live = (brief or {}).get("liveBook") or {}
    considerations = "".join(f"<li>{line}</li>" for line in ((brief or {}).get("considerations") or [])[:3])
    return f"""<!DOCTYPE html>
<html lang="en">
  <body style="background:#120707;color:#f6e5d1;font-family:Georgia,serif;padding:24px;">
    <h1 style="color:#ffb074;margin:0 0 12px;">Inferno Approval Request: {item.get('ticker')}</h1>
    <p style="color:#b49a86;">Reply with exactly <strong>approve</strong> or <strong>deny</strong>. The subject already carries the token.</p>
    <table style="border-collapse:collapse;width:100%;max-width:720px;">
      <tr><td><strong>Readiness</strong></td><td>{tracker.get('readiness')}%</td></tr>
      <tr><td><strong>Confidence</strong></td><td>{tracker.get('confidence')}</td></tr>
      <tr><td><strong>Days to earnings</strong></td><td>{tracker.get('daysUntilEarnings')}</td></tr>
      <tr><td><strong>Primary route</strong></td><td>{item.get('primaryRoute')}</td></tr>
      <tr><td><strong>Trend</strong></td><td>{tracker.get('trend')}</td></tr>
      <tr><td><strong>RVOL</strong></td><td>{tracker.get('rvol')}</td></tr>
      <tr><td><strong>Edge</strong></td><td>{edge.get('category')} / {edge.get('lane')} / {edge.get('edgeScore')}</td></tr>
      <tr><td><strong>Live posture</strong></td><td>{live.get('posture') or '-'} | held={live.get('held')}</td></tr>
    </table>
    <p style="margin-top:16px;color:#ffb074;"><strong>One-word reply:</strong> approve or deny</p>
    <ul>{considerations}</ul>
  </body>
</html>"""


def send_operator_email(subject: str, text: str, html: str) -> None:
    """Send one operator-facing email using the existing SMTP config."""
    settings = smtp_settings()
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings["from_addr"]
    message["To"] = settings["to_addr"]
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    if settings["use_ssl"]:
        with smtplib.SMTP_SSL(settings["host"], settings["port"]) as smtp:
            if settings["username"]:
                smtp.login(settings["username"], settings["password"])
            smtp.send_message(message)
        return

    with smtplib.SMTP(settings["host"], settings["port"]) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        if settings["username"]:
            smtp.login(settings["username"], settings["password"])
        smtp.send_message(message)


def dispatch_pending_approval_prompts(*, force: bool = False) -> dict[str, Any]:
    """Send unsent approval prompts for the current queue."""
    load_env_file(SMTP_ENV_FILE)
    queue = ensure_queue_tokens(load_queue())
    pending = [
        item for item in queue.get("items", [])
        if str(item.get("approvalStatus") or "").lower() == "pending"
    ]
    report: dict[str, Any] = {
        "generatedAt": local_now().isoformat(),
        "status": "idle",
        "ok": True,
        "pendingCount": len(pending),
        "sentCount": 0,
        "skippedCount": 0,
        "force": force,
        "sent": [],
        "skipped": [],
    }
    if not pending:
        save_report(report)
        return report
    if not smtp_configured():
        report.update({"ok": False, "status": "smtp-not-configured"})
        save_report(report)
        return report

    briefs_payload = build_decision_briefs(queue=queue)
    brief_map = {
        str(brief.get("ticker") or "").upper(): brief
        for brief in briefs_payload.get("briefs") or []
        if brief.get("ticker")
    }
    state = load_state()
    sent_by_token = state.setdefault("sentByToken", {})
    current_tokens = {str(item.get("approvalToken") or "") for item in pending}
    state["sentByToken"] = {
        token: payload
        for token, payload in sent_by_token.items()
        if token in current_tokens
    }
    sent_by_token = state["sentByToken"]

    try:
        for item in pending:
            token = str(item.get("approvalToken") or "")
            ticker = str(item.get("ticker") or "").upper()
            if not token:
                report["skipped"].append({"ticker": ticker, "approvalToken": token, "reason": "missing-token"})
                continue
            if not force and token in sent_by_token:
                report["skipped"].append({"ticker": ticker, "approvalToken": token, "reason": "already-sent"})
                continue
            brief = brief_map.get(ticker)
            subject = build_prompt_subject(item)
            send_operator_email(
                subject,
                build_prompt_text(item, brief),
                build_prompt_html(item, brief),
            )
            entry = {
                "ticker": ticker,
                "approvalToken": token,
                "subject": subject,
                "sentAt": local_now().isoformat(),
                "queueGeneratedAt": queue.get("generatedAt"),
            }
            sent_by_token[token] = entry
            report["sent"].append(entry)
    except Exception as exc:  # noqa: BLE001
        report.update({"ok": False, "status": "send-failed", "error": str(exc)})
        report["sentCount"] = len(report["sent"])
        report["skippedCount"] = len(report["skipped"])
        save_state(state)
        save_report(report)
        return report

    report["sentCount"] = len(report["sent"])
    report["skippedCount"] = len(report["skipped"])
    report["status"] = "sent" if report["sentCount"] else "idle"
    save_state(state)
    save_report(report)
    return report


def parse_args() -> argparse.Namespace:
    """Parse CLI args for approval dispatch."""
    parser = argparse.ArgumentParser(description="Send one reply-friendly approval email per pending ticker.")
    parser.add_argument("command", nargs="?", default="dispatch", choices=["dispatch", "status"])
    parser.add_argument("--force", action="store_true", help="Resend prompts even if the token already dispatched.")
    return parser.parse_args()


def main() -> int:
    """Run the approval-dispatch CLI."""
    args = parse_args()
    if args.command == "status" and APPROVAL_DISPATCH_TEXT_FILE.exists():
        print(APPROVAL_DISPATCH_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = dispatch_pending_approval_prompts(force=args.force)
    print(approval_dispatch_text(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
