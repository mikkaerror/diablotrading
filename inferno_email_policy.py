"""Delivery-only controls. Reports and operator authority are unaffected."""
from __future__ import annotations

import os
from typing import Any


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
    if any(word in subject.lower() for word in ("failure", "exception", "alert")):
        return False
    if subject == "Morning Conviction Brief" or "Hell Market Morning Brief" in subject:
        return suppress_routine_email("morning", payload)
    if subject.startswith("[DIABLO TRADING] Strike Plan -"):
        return suppress_routine_email("strike", payload)
    return False
