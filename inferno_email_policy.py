"""Delivery-only controls. Reports and operator authority are unaffected."""
from __future__ import annotations

import os
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from inferno_away import is_away
from inferno_config import local_now


def suppress_away_email(kind: str, *, today: date | None = None) -> bool:
    """Read the operator window at delivery time, using the desk's calendar day.

    These senders stay quiet even for failures/forced sends. The Desk Editor's
    short away summary and independent watchdog alerts keep their own delivery.
    This check never changes the away window or any approval/delivery state.
    """
    return kind in {"approval", "desk-chief", "action-pulse"} and is_away(
        today or local_now().astimezone(ZoneInfo("America/Denver")).date()
    )


def email_mode() -> str:
    """Unknown or unset values preserve the existing full delivery mode."""
    value = os.environ.get("INFERNO_EMAIL_MODE", "full").strip().lower()
    return value if value in {"full", "editor"} else "full"


def is_failure_alert(payload: dict[str, Any]) -> bool:
    """Explicit operational failures are alerts; ordinary risk blocks are not."""
    if payload.get("ok") is False or payload.get("error") or payload.get("errors"):
        return True
    if payload.get("maintenanceStatus") is False:
        return True
    if str(payload.get("status") or payload.get("verdict") or "").lower() in {
        "failed", "failure", "error", "exception", "send-failed", "refresh-failed"
    }:
        return True
    daily = payload.get("dailyLoop") or {}
    if daily.get("failedCount"):
        return True
    return any(is_failure_alert(payload[key]) for key in ("capitalLaunch", "schwabDailyOps", "paperEvidence")
               if isinstance(payload.get(key), dict))


def suppress_routine_email(kind: str, payload: dict[str, Any] | None = None) -> bool:
    return (email_mode() == "editor" and kind in {"morning", "strike", "action-pulse"}
            and not is_failure_alert(payload or {}))


def suppress_subject(subject: str, payload: dict[str, Any]) -> bool:
    """Guard shared SMTP entry points, leaving other mail (especially alerts) alone."""
    # The Chief currently has no sender. Keep its named shared-SMTP route quiet
    # too, without adding a new delivery path or changing Chief authority.
    for prefix, kind in (("[Inferno Approval]", "approval"),
                         ("[Inferno Desk Chief]", "desk-chief")):
        if subject.startswith(prefix) and suppress_away_email(kind):
            return True
    if any(word in subject.lower() for word in ("failure", "exception", "alert")):
        return False
    if subject == "Morning Conviction Brief" or "Hell Market Morning Brief" in subject:
        return suppress_routine_email("morning", payload)
    if subject.startswith("[DIABLO TRADING] Strike Plan -"):
        return suppress_routine_email("strike", payload)
    return False
