from __future__ import annotations

"""Lifecycle metadata for mutable Inferno research artifacts.

``generatedAt`` is retained for legacy readers, but it is a creation-time
compatibility field for append-only/mutable ledgers. Freshness decisions must
instead use ``lastSuccessfulAt`` and independently inspect
``sourceDataAsOf``. A failed refresh records its attempt without advancing the
last successful evidence timestamp.
"""

from datetime import datetime
from typing import Any

from inferno_config import local_now


LIFECYCLE_VERSION = 1


def text(value: Any) -> str:
    """Normalize an optional lifecycle value without inventing a timestamp."""
    return str(value or "").strip()


def timestamp(now: datetime | None = None) -> str:
    """Return the explicit lifecycle timestamp for one state transition."""
    return (now or local_now()).isoformat()


def successful_lifecycle(
    payload: dict[str, Any],
    *,
    producer: str,
    source_data_as_of: str | None = None,
    freshness_ttl_hours: float | None = None,
    schedule: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Attach a successful lifecycle transition while preserving creation time."""
    current = timestamp(now)
    created_at = text(payload.get("createdAt")) or text(payload.get("generatedAt")) or current
    source_at = text(source_data_as_of) or text(payload.get("sourceDataAsOf")) or None
    policy = dict(payload.get("freshnessPolicy") or {})
    if freshness_ttl_hours is not None:
        policy["ttlHours"] = freshness_ttl_hours
    if schedule:
        policy["schedule"] = schedule

    updated = {
        **payload,
        # Legacy consumers still read generatedAt. It stays creation-only.
        "generatedAt": text(payload.get("generatedAt")) or created_at,
        "createdAt": created_at,
        "updatedAt": current,
        "lastSuccessfulAt": current,
        "lastAttemptAt": current,
        "sourceDataAsOf": source_at,
        "producer": producer,
        "lifecycleVersion": LIFECYCLE_VERSION,
        "lifecycleStatus": "success",
        "lastFailure": None,
    }
    if policy:
        updated["freshnessPolicy"] = policy
    return updated


def failed_lifecycle(
    payload: dict[str, Any],
    *,
    producer: str,
    error: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record a failed attempt without changing successful/source freshness."""
    current = timestamp(now)
    created_at = text(payload.get("createdAt")) or text(payload.get("generatedAt")) or current
    last_success = text(payload.get("lastSuccessfulAt")) or text(payload.get("updatedAt")) or None
    return {
        **payload,
        "generatedAt": text(payload.get("generatedAt")) or created_at,
        "createdAt": created_at,
        "lastSuccessfulAt": last_success,
        "lastAttemptAt": current,
        "producer": producer,
        "lifecycleVersion": LIFECYCLE_VERSION,
        "lifecycleStatus": "failed",
        "lastFailure": {"at": current, "message": text(error) or "unknown failure"},
    }
