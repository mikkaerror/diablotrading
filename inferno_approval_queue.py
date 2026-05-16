from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from typing import Any

from inferno_execution_clerk import build_execution_queue, save_execution_queue
from inferno_io import atomic_write_json
from server import APPROVAL_QUEUE_FILE


# Stale-approval TTL: pending tickets that go this many *market days* without
# an approve/reject action are demoted to ``research-only`` so they can no
# longer reach the strike-cycle. The governor never approves anything; it can
# only demote, so this cannot create authority on its own.
DEFAULT_STALE_APPROVAL_TTL_MARKET_DAYS = int(
    os.environ.get("APPROVAL_STALE_TTL_MARKET_DAYS", "5") or "5"
)
STALE_APPROVAL_DEMOTED_STATUS = "research-only"
STALE_APPROVAL_REASON_PREFIX = "approval-stale"
APPROVAL_TOKEN_LENGTH = int(os.environ.get("APPROVAL_TOKEN_LENGTH", "8") or "8")

# Human-friendly aliases so an email reply can be short and natural. The map is
# intentionally one-way into the desk's canonical statuses.
APPROVAL_ACTION_TO_STATUS = {
    "approve": "approved",
    "approved": "approved",
    "yes": "approved",
    "go": "approved",
    "ship": "approved",
    "deny": "rejected",
    "denied": "rejected",
    "reject": "rejected",
    "rejected": "rejected",
    "no": "rejected",
    "pass": "rejected",
    "pending": "pending",
    "reset": "pending",
}
APPROVAL_REPLY_SPLIT_RE = re.compile(r"[^\w.-]+")
APPROVAL_REPLY_STOP_MARKERS = (
    "-----original message-----",
    "________________________________",
)


def build_approval_token(ticker: str, generated_at: str | None) -> str:
    """Build a deterministic short token for one queue item.

    The token is stable for the same ticker + queue generation time, which
    makes it safe to embed into reply emails and reports while still expiring
    naturally on the next queue rebuild.
    """
    digest = hashlib.sha1(
        f"inferno-approval|{(generated_at or '').strip()}|{ticker.strip().upper()}".encode("utf-8")
    ).hexdigest().upper()
    return digest[:APPROVAL_TOKEN_LENGTH]


def _reply_commands_for(item: dict[str, Any]) -> dict[str, str]:
    """Return the exact operator reply commands for one queue item."""
    ticker = str(item.get("ticker") or "").strip().upper()
    token = str(item.get("approvalToken") or "").strip().upper()
    return {
        "approve": f"APPROVE {ticker} {token}".strip(),
        "deny": f"DENY {ticker} {token}".strip(),
        "approveShort": f"APPROVE {token}".strip(),
        "denyShort": f"DENY {token}".strip(),
    }


def ensure_queue_tokens(queue: dict) -> dict:
    """Stamp every queue item with a deterministic approval token and shortcuts.

    This keeps the approval desk machine-readable across CLI, API, email, and
    future notification surfaces without changing the queue's authority model.
    """
    generated_at = str(queue.get("generatedAt") or "")
    for item in queue.get("items", []):
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        item["ticker"] = ticker
        item.setdefault("generatedAt", generated_at)
        item["approvalToken"] = build_approval_token(ticker, str(item.get("generatedAt") or generated_at))
        commands = _reply_commands_for(item)
        item["replyApprove"] = commands["approve"]
        item["replyDeny"] = commands["deny"]
        item["replyApproveShort"] = commands["approveShort"]
        item["replyDenyShort"] = commands["denyShort"]
    queue["count"] = len(queue.get("items", []))
    return queue


def load_queue() -> dict:
    if not APPROVAL_QUEUE_FILE.exists():
        return {"generatedAt": None, "count": 0, "items": []}
    return ensure_queue_tokens(json.loads(APPROVAL_QUEUE_FILE.read_text(encoding="utf-8")))


def save_queue(queue: dict) -> None:
    atomic_write_json(APPROVAL_QUEUE_FILE, ensure_queue_tokens(queue))


def refresh_execution_queue() -> None:
    save_execution_queue(build_execution_queue())


def _parse_iso_datetime(value) -> datetime | None:
    """Accept either an ISO datetime or an ISO date string."""
    if not value:
        return None
    text = str(value)
    try:
        if "T" in text:
            return datetime.fromisoformat(text)
        return datetime.fromisoformat(f"{text}T00:00:00")
    except ValueError:
        return None


def count_market_days_between(start: date, end: date) -> int:
    """Return weekdays between two dates (inclusive of start, exclusive of end).

    The desk runs Sun-Fri but trades only weekdays, so weekday count is the
    closest no-dependency proxy for market days. Holidays are not subtracted —
    that produces a slightly more lenient TTL, which is the safer side of the
    bias because we'd rather wait one extra day than auto-demote a real intent.
    """
    if end <= start:
        return 0
    days = 0
    cursor = start
    while cursor < end:
        if cursor.weekday() < 5:
            days += 1
        cursor += timedelta(days=1)
    return days


def ensure_pending_since(queue: dict, *, now: datetime | None = None) -> dict:
    """Stamp ``pendingSince`` on any pending item that lacks it.

    The stamp is what the staleness governor reads later. We never overwrite
    an existing stamp, so a ticker that has already been pending for three days
    keeps its original timestamp across rebuilds.
    """
    moment = (now or datetime.now().astimezone()).isoformat()
    for item in queue.get("items", []):
        if str(item.get("approvalStatus") or "").lower() != "pending":
            continue
        if not item.get("pendingSince"):
            item["pendingSince"] = moment
    return queue


def expire_stale_approvals(
    queue: dict,
    *,
    ttl_market_days: int = DEFAULT_STALE_APPROVAL_TTL_MARKET_DAYS,
    now: datetime | None = None,
) -> list[dict]:
    """Demote pending items older than ``ttl_market_days`` market days.

    Returns a list of summary dicts for the demoted items. The function only
    demotes — it never flips ``approved`` or ``rejected`` to anything else, and
    it never promotes a pending item to approved. ``ok`` and any other risk
    fields are untouched.
    """
    moment = now or datetime.now().astimezone()
    today = moment.date()
    decision_at = moment.isoformat()
    demoted: list[dict] = []

    for item in queue.get("items", []):
        status = str(item.get("approvalStatus") or "").lower()
        # Hard rule: only "pending" tickers are eligible for demotion. Approved,
        # rejected, or already-demoted statuses must be left alone.
        if status != "pending":
            continue
        pending_since = _parse_iso_datetime(item.get("pendingSince"))
        if pending_since is None:
            continue
        market_days = count_market_days_between(pending_since.date(), today)
        if market_days < ttl_market_days:
            continue
        item["approvalStatus"] = STALE_APPROVAL_DEMOTED_STATUS
        item["decisionAt"] = decision_at
        item["expirationReason"] = f"{STALE_APPROVAL_REASON_PREFIX}-{market_days}-market-days"
        demoted.append(
            {
                "ticker": item.get("ticker"),
                "marketDays": market_days,
                "previousStatus": "pending",
                "newStatus": STALE_APPROVAL_DEMOTED_STATUS,
            }
        )

    return demoted


def print_status(queue: dict) -> None:
    items = queue.get("items", [])
    status_counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("approvalStatus") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    print(f"Generated at: {queue.get('generatedAt') or 'never'}")
    print(f"Queue items: {len(items)}")
    print(
        "Status counts: "
        + ", ".join(f"{status}={count}" for status, count in sorted(status_counts.items()))
        if status_counts
        else "Status counts: none"
    )
    for item in items:
        print(
            f"- {item['ticker']}: {item['approvalStatus']} | token {item.get('approvalToken', '-')} | "
            f"{item['setupRec']} | {item['readiness']}% | {item['daysUntilEarnings']}d | {item['primaryRoute']}"
        )


def _normalize_identifier(value: str | None) -> str:
    """Normalize a ticker or token-like identifier for matching."""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def find_item(queue: dict, identifier: str) -> dict[str, Any] | None:
    """Resolve either a ticker or approval token to one queue item."""
    needle = _normalize_identifier(identifier)
    if not needle:
        return None
    for item in queue.get("items", []):
        if _normalize_identifier(item.get("approvalToken")) == needle:
            return item
    for item in queue.get("items", []):
        if _normalize_identifier(item.get("ticker")) == needle:
            return item
    return None


def update_item(queue: dict, identifier: str, status: str) -> int:
    target = _normalize_identifier(identifier)
    updated = False
    for item in queue.get("items", []):
        token_match = _normalize_identifier(item.get("approvalToken")) == target
        ticker_match = _normalize_identifier(item.get("ticker")) == target
        if not token_match and not ticker_match:
            continue
        item["approvalStatus"] = status
        item["decisionAt"] = datetime.now().astimezone().isoformat()
        # A manual decision releases the staleness clock for the next
        # pending cycle on this ticker.
        if status == "pending":
            item["pendingSince"] = item.get("pendingSince") or datetime.now().astimezone().isoformat()
            item.pop("decisionAt", None)
        else:
            item.pop("pendingSince", None)
        item.pop("expirationReason", None)
        updated = True
    if not updated:
        print(f"{identifier.strip().upper()} was not found in the current approval queue.")
        return 1
    save_queue(queue)
    refresh_execution_queue()
    print(f"{identifier.strip().upper()} marked {status}.")
    return 0


def reset_queue(queue: dict) -> int:
    moment = datetime.now().astimezone().isoformat()
    for item in queue.get("items", []):
        item["approvalStatus"] = "pending"
        item.pop("decisionAt", None)
        item.pop("expirationReason", None)
        # A reset re-arms the staleness clock for every item.
        item["pendingSince"] = moment
    save_queue(queue)
    refresh_execution_queue()
    print("Approval queue reset to pending.")
    return 0


def expire_command(queue: dict, *, ttl_market_days: int) -> int:
    """CLI entry point for the staleness governor."""
    ensure_pending_since(queue)
    demoted = expire_stale_approvals(queue, ttl_market_days=ttl_market_days)
    save_queue(queue)
    if not demoted:
        print(f"No approvals older than {ttl_market_days} market days. Queue unchanged.")
        return 0
    refresh_execution_queue()
    print(f"Demoted {len(demoted)} stale approval(s):")
    for entry in demoted:
        print(
            f"- {entry['ticker']}: {entry['previousStatus']} -> "
            f"{entry['newStatus']} ({entry['marketDays']} market days)"
        )
    return 0


def extract_authored_reply(text: str) -> str:
    """Strip quoted reply history so we only parse the operator-authored text."""
    lines: list[str] = []
    seen_content = False
    for raw_line in str(text or "").splitlines():
        stripped = raw_line.strip()
        lower = stripped.lower()
        if any(marker in lower for marker in APPROVAL_REPLY_STOP_MARKERS):
            break
        if stripped.startswith(">"):
            break
        if lower.startswith("on ") and "wrote:" in lower:
            break
        if seen_content and lower.startswith(("from:", "sent:", "subject:", "to:", "cc:")):
            break
        if not stripped:
            if seen_content:
                lines.append("")
            continue
        lines.append(stripped)
        seen_content = True
    return "\n".join(lines).strip()


def _parse_action_line(
    line: str,
    queue: dict,
    *,
    default_identifier: str | None = None,
) -> dict[str, Any] | None:
    """Parse one authored line into a normalized approval decision."""
    pieces = [piece for piece in APPROVAL_REPLY_SPLIT_RE.split(line.strip()) if piece]
    if not pieces:
        return None
    action = pieces[0].strip().lower()
    status = APPROVAL_ACTION_TO_STATUS.get(action)
    if not status:
        return None

    identifier = ""
    for piece in pieces[1:]:
        if find_item(queue, piece):
            identifier = piece
            break
    if not identifier and default_identifier and find_item(queue, default_identifier):
        identifier = default_identifier
    if not identifier:
        return {
            "ok": False,
            "line": line.strip(),
            "status": status,
            "reason": "identifier-missing",
        }
    matched = find_item(queue, identifier)
    if not matched:
        return {
            "ok": False,
            "line": line.strip(),
            "status": status,
            "reason": "identifier-not-found",
        }
    return {
        "ok": True,
        "line": line.strip(),
        "status": status,
        "identifier": identifier,
        "ticker": matched.get("ticker"),
        "approvalToken": matched.get("approvalToken"),
    }


def _subject_context_identifier(subject: str, queue: dict) -> str | None:
    """Pull one valid queue identifier from an email subject, if present."""
    for piece in APPROVAL_REPLY_SPLIT_RE.split(str(subject or "")):
        if not piece:
            continue
        matched = find_item(queue, piece)
        if matched:
            return str(matched.get("approvalToken") or matched.get("ticker") or "")
    return None


def apply_reply_commands(
    queue: dict,
    text: str,
    *,
    subject: str = "",
) -> dict[str, Any]:
    """Apply one or more approve/deny lines from an email or notification reply.

    The parser only considers the operator-authored reply text and ignores the
    quoted body below it. Subject tokens provide context, so a reply body that
    only says ``approve`` can still be resolved safely when the subject names a
    single ticket token.
    """
    ensure_queue_tokens(queue)
    authored = extract_authored_reply(text)
    default_identifier = _subject_context_identifier(subject, queue)
    attempted: list[dict[str, Any]] = []
    changed = False

    candidate_lines = [line for line in authored.splitlines() if line.strip()]
    if not candidate_lines and subject:
        candidate_lines = [subject]

    for line in candidate_lines:
        parsed = _parse_action_line(line, queue, default_identifier=default_identifier)
        if not parsed:
            continue
        attempted.append(parsed)
    conflicts: set[str] = set()
    statuses_by_identifier: dict[str, set[str]] = {}
    for parsed in attempted:
        if not parsed.get("ok"):
            continue
        identifier = str(parsed.get("identifier") or "")
        statuses_by_identifier.setdefault(identifier, set()).add(str(parsed.get("status") or ""))
    for identifier, statuses in statuses_by_identifier.items():
        if len(statuses) > 1:
            conflicts.add(identifier)

    for parsed in attempted:
        if not parsed.get("ok"):
            continue
        if str(parsed.get("identifier") or "") in conflicts:
            parsed["ok"] = False
            parsed["reason"] = "conflicting-commands"
            continue
        item = find_item(queue, parsed["identifier"])
        if not item:
            continue
        item["approvalStatus"] = parsed["status"]
        if parsed["status"] == "pending":
            item["pendingSince"] = datetime.now().astimezone().isoformat()
            item.pop("decisionAt", None)
        else:
            item["decisionAt"] = datetime.now().astimezone().isoformat()
            item.pop("pendingSince", None)
        item.pop("expirationReason", None)
        changed = True

    return {
        "authoredText": authored,
        "defaultIdentifier": default_identifier,
        "matchedCount": sum(1 for entry in attempted if entry.get("ok")),
        "changed": changed,
        "commands": attempted,
    }


def approval_reply_section(queue: dict) -> str:
    """Render a copy/paste-ready approval section for briefs and reports."""
    ensure_queue_tokens(queue)
    pending_items = [
        item for item in queue.get("items", [])
        if str(item.get("approvalStatus") or "").lower() == "pending"
    ]
    if not pending_items:
        return ""
    lines = [
        "",
        "Approval Desk Quick Reply:",
        "Reply to this email with one or more of the lines below.",
        "The desk will only accept commands that match a live queue token.",
        "",
    ]
    for item in pending_items:
        lines.append(
            f"- {item['ticker']} ({item.get('readiness')}% | {item.get('daysUntilEarnings')}d): "
            f"{item.get('replyApprove')}  |  {item.get('replyDeny')}"
        )
    return "\n".join(lines).rstrip() + "\n"


def ingest_command_text(queue: dict, text: str, *, subject: str = "") -> int:
    """CLI entry point for email-style approval replies."""
    result = apply_reply_commands(queue, text, subject=subject)
    if result["matchedCount"] == 0:
        print("No approval commands were recognized.")
        return 1
    save_queue(queue)
    refresh_execution_queue()
    for command in result.get("commands", []):
        if command.get("ok"):
            print(
                f"{command.get('ticker')} marked {command.get('status')} "
                f"via {command.get('approvalToken') or command.get('identifier')}"
            )
        else:
            print(f"Skipped line '{command.get('line')}' ({command.get('reason')})")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect and manage the local inferno approval queue.")
    parser.add_argument(
        "command",
        nargs="?",
        default="status",
        choices=["status", "approve", "reject", "reset", "expire", "ingest"],
    )
    parser.add_argument("target", nargs="?", default="")
    parser.add_argument(
        "--ttl-market-days",
        type=int,
        default=DEFAULT_STALE_APPROVAL_TTL_MARKET_DAYS,
        help="Market-day TTL before pending approvals are demoted to research-only.",
    )
    parser.add_argument(
        "--text",
        default="",
        help="Email-style approval text to ingest (for example: 'APPROVE CEG ABC12345').",
    )
    parser.add_argument(
        "--subject",
        default="",
        help="Optional subject line context for approve/deny replies.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    queue = load_queue()

    if args.command == "status":
        ensure_pending_since(queue)
        save_queue(queue)
        print_status(queue)
        return 0
    if args.command == "reset":
        return reset_queue(queue)
    if args.command == "expire":
        return expire_command(queue, ttl_market_days=args.ttl_market_days)
    if args.command == "ingest":
        text = args.text
        if not text and not sys.stdin.isatty():
            text = sys.stdin.read()
        if not text.strip():
            print("Approval ingest needs text from --text or stdin.")
            return 1
        return ingest_command_text(queue, text, subject=args.subject)
    if not args.target:
        print("A ticker or token is required for approve/reject.")
        return 1
    if args.command == "approve":
        return update_item(queue, args.target, "approved")
    return update_item(queue, args.target, "rejected")


if __name__ == "__main__":
    raise SystemExit(main())
