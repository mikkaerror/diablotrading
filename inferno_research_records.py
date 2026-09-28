"""Read saved evidence schemas for diagnostics; never grant sample admission."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def shadow_records(payload: Any) -> list[dict[str, Any]]:
    """Adapt the producer's items schema and retain legacy diagnostic inputs.

    An explicitly empty items list is authoritative. No fallback may resurrect
    an obsolete records list. Missing risk/P&L remains unscorable, never zero.
    All rows remain shadow proxies, including premature historical settlements.
    """
    rows = payload if isinstance(payload, list) else []
    if isinstance(payload, dict):
        for key in ("items", "records", "entries", "rows"):
            if key in payload:
                rows = payload[key]
                break
    if not isinstance(rows, list):
        return []
    result = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        outcome = item.get("outcome") or {}
        if not isinstance(outcome, dict):
            continue
        pnl = finite_number(item.get("estimatedPnl") if "estimatedPnl" in item else outcome.get("estimatedPnl"))
        verdict = item.get("riskVerdict")
        verdict = verdict if isinstance(verdict, dict) else {}
        metrics = verdict.get("metrics")
        metrics = metrics if isinstance(metrics, dict) else {}
        risk = None
        for value in (item.get("maxLossDollars"), item.get("estimatedMaxLoss"),
                      metrics.get("maxLossDollars"), outcome.get("maxLossDollars")):
            if value is not None:
                risk = finite_number(value)
                break
        row["outcome"] = {**outcome, "estimatedPnl": finite_number(outcome.get("estimatedPnl")),
                          "maxLossDollars": finite_number(outcome.get("maxLossDollars"))}
        row["estimatedPnl"] = pnl
        row["maxLossDollars"] = risk if risk is not None and risk > 0 else None
        row["outcomeStatus"] = str(outcome.get("status") or item.get("outcomeStatus") or "").lower()
        # Outcome observation time, never silently relabel it as broker execution.
        row["closedAt"] = outcome.get("closedAt") or outcome.get("settledAt") or outcome.get("reviewedAt") or item.get("closedAt")
        row["evidenceBasis"] = "unverified-shadow-proxy"
        result.append(row)
    return result


def load_shadow_records(path: Path) -> list[dict[str, Any]]:
    try:
        return shadow_records(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []
