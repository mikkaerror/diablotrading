from __future__ import annotations

"""Validate provenance, freshness, and coverage for AI-basket research inputs."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


STAGE = "ai-basket-data-contract-research-only"
OUTPUT_FILE = DATA_DIR / "inferno_ai_basket_data_contract.json"
REPORT_FILE = REPORTS_DIR / "ai_basket_data_contract_latest.txt"
SNAPSHOT_FILE = DATA_DIR / "ai_basket_snapshot.json"
MOMENTUM_FILE = DATA_DIR / "ai_basket_momentum.json"
MAX_AGE_HOURS = 36.0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _symbols(rows: list[dict[str, Any]], field: str) -> list[str]:
    return [_text(row.get(field)).upper() for row in rows if isinstance(row, dict) and _text(row.get(field))]


def _timestamp(payload: Any, path: Path) -> tuple[str, str]:
    if isinstance(payload, dict) and _text(payload.get("generatedAt")):
        return _text(payload.get("generatedAt")), "embedded-generatedAt"
    if path.exists():
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone().isoformat(), "file-mtime-inferred"
    return "", "missing"


def _age_hours(timestamp: str, now: datetime) -> float | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return round(max(0.0, (now.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600.0), 4)
    except ValueError:
        return None


def assess_source(name: str, payload: Any, path: Path, *, expected: set[str], symbol_field: str, now: datetime) -> dict[str, Any]:
    rows = payload if isinstance(payload, list) else ((payload or {}).get("ranking") or (payload or {}).get("records") or []) if isinstance(payload, dict) else []
    symbols = _symbols(rows, symbol_field)
    unique = set(symbols)
    timestamp, timestamp_type = _timestamp(payload, path)
    age = _age_hours(timestamp, now)
    missing = sorted(expected - unique)
    extras = sorted(unique - expected)
    duplicates = sorted({symbol for symbol in symbols if symbols.count(symbol) > 1})
    complete = bool(expected) and not missing and not duplicates
    fresh = age is not None and age <= MAX_AGE_HOURS
    provenance_explicit = timestamp_type == "embedded-generatedAt"
    trusted = complete and fresh and provenance_explicit
    reasons = []
    if not complete:
        reasons.append("coverage-incomplete")
    if not fresh:
        reasons.append("source-stale-or-undated")
    if not provenance_explicit:
        reasons.append("timestamp-inferred-not-embedded")
    return {
        "name": name, "path": str(path), "rowCount": len(rows), "uniqueSymbols": len(unique),
        "expectedSymbols": len(expected), "coveragePct": round(len(unique & expected) / len(expected), 4) if expected else 0.0,
        "missingSymbols": missing, "extraSymbols": extras, "duplicateSymbols": duplicates,
        "sourceTimestamp": timestamp, "timestampType": timestamp_type, "ageHours": age,
        "complete": complete, "fresh": fresh, "provenanceExplicit": provenance_explicit,
        "trustedForSignals": trusted, "reasons": reasons,
    }


def build_contract(snapshot: Any, momentum: Any, *, snapshot_path: Path = SNAPSHOT_FILE, momentum_path: Path = MOMENTUM_FILE, now: datetime | None = None) -> dict[str, Any]:
    now = now or local_now()
    snapshot_rows = snapshot if isinstance(snapshot, list) else (snapshot or {}).get("records") or []
    declared = (snapshot or {}).get("expectedUniverse") if isinstance(snapshot, dict) else None
    expected = set(_text(symbol).upper() for symbol in declared if _text(symbol)) if isinstance(declared, list) and declared else set(_symbols(snapshot_rows, "symbol"))
    snapshot_check = assess_source("basket-snapshot", snapshot, snapshot_path, expected=expected, symbol_field="symbol", now=now)
    momentum_check = assess_source("basket-momentum", momentum, momentum_path, expected=expected, symbol_field="symbol", now=now)
    all_trusted = snapshot_check["trustedForSignals"] and momentum_check["trustedForSignals"]
    return {
        "generatedAt": now.isoformat(), "stage": STAGE, "verdict": "trusted" if all_trusted else "fail-closed",
        "researchOnly": True, "promotable": False, "authorityChanged": False,
        "brokerSubmitAllowed": False, "liveTradingAllowed": False,
        "expectedUniverse": sorted(expected), "expectedCount": len(expected),
        "signalsTrusted": all_trusted, "sources": {"snapshot": snapshot_check, "momentum": momentum_check},
        "rules": [
            f"Every signal source must cover the full snapshot universe and be no older than {MAX_AGE_HOURS:.0f} hours.",
            "Signal timestamps must be embedded by the producer; filesystem modification time is diagnostic only.",
            "Partial, stale, duplicated, or inferred-timestamp inputs fail closed and cannot rank candidates.",
        ],
    }


def render(payload: dict[str, Any]) -> str:
    lines = ["Inferno AI Basket Data Contract", "", f"Generated: {payload['generatedAt']}", f"Verdict: {payload['verdict']}", f"Signals trusted: {payload['signalsTrusted']}", f"Expected universe: {payload['expectedCount']} names", ""]
    for source in payload["sources"].values():
        lines.append(f"- {source['name']}: {source['uniqueSymbols']}/{source['expectedSymbols']} | age {source['ageHours']}h | timestamp {source['timestampType']} | trusted {source['trustedForSignals']}")
        if source["missingSymbols"]:
            lines.append(f"  missing: {', '.join(source['missingSymbols'])}")
        if source["reasons"]:
            lines.append(f"  blocks: {', '.join(source['reasons'])}")
    lines += ["", "Contract:"] + [f"- {rule}" for rule in payload["rules"]]
    return "\n".join(lines) + "\n"


def save_contract(
    payload: dict[str, Any],
    *,
    output_file: Path | None = None,
    report_file: Path | None = None,
) -> None:
    """Persist a derived trust verdict without changing basket membership or signals."""
    ensure_dirs()
    atomic_write_json(output_file or OUTPUT_FILE, payload)
    atomic_write_text(report_file or REPORT_FILE, render(payload))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=("run", "status"), default="run")
    args = parser.parse_args()
    if args.command == "status":
        print(REPORT_FILE.read_text() if REPORT_FILE.exists() else "No basket data-contract report yet.")
        return 0
    payload = build_contract(load_json_file(SNAPSHOT_FILE) if SNAPSHOT_FILE.exists() else [], load_json_file(MOMENTUM_FILE) if MOMENTUM_FILE.exists() else {})
    save_contract(payload)
    print(render(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
