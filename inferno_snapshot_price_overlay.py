from __future__ import annotations

"""Overlay fresh broker underlyings onto the local tracker snapshot.

The Google Sheet remains operator-owned. This module updates the local
snapshot and execution queue with broker-read market data provenance so
paper/strike gates do not treat old-but-valid sheet prices as current quotes.
"""

import argparse
from datetime import datetime
from typing import Any

from inferno_execution_clerk import build_execution_queue, save_execution_queue
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, SNAPSHOT_FILE, ensure_dirs, load_json_file


SCHWAB_OPTIONS_FILE = DATA_DIR / "inferno_schwab_options.json"
SNAPSHOT_PRICE_OVERLAY_FILE = DATA_DIR / "inferno_snapshot_price_overlay.json"
SNAPSHOT_PRICE_OVERLAY_TEXT_FILE = REPORTS_DIR / "snapshot_price_overlay_latest.txt"


def number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    cleaned = str(value or "").replace("$", "").replace(",", "").strip()
    if not cleaned:
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default


def schwab_underlying_index(options_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = options_report.get("rows") if isinstance(options_report, dict) else []
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        price = number(row.get("underlyingPrice"))
        if symbol and price > 0:
            indexed[symbol] = row
    return indexed


def refresh_market_context_distances(row: dict[str, Any], price: float) -> None:
    context = dict(row.get("marketContext") or {})
    support = number(context.get("support"))
    resistance = number(context.get("resistance"))
    if price > 0 and support > 0:
        context["distanceToSupportPct"] = round((price - support) / price * 100.0, 4)
    if price > 0 and resistance > 0:
        context["distanceToResistancePct"] = round((resistance - price) / price * 100.0, 4)
    context["price"] = price
    context["priceSource"] = row.get("priceSource")
    context["priceAsOf"] = row.get("priceAsOf")
    row["marketContext"] = context


def apply_schwab_price_overlay(
    snapshot: dict[str, Any],
    options_report: dict[str, Any],
    *,
    generated_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    generated_at = generated_at or datetime.now().astimezone().isoformat()
    options_generated_at = str(options_report.get("generatedAt") or "")
    option_index = schwab_underlying_index(options_report)
    rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []

    updated: list[dict[str, Any]] = []
    missing: list[str] = []
    unchanged = 0

    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper().strip()
        sheet_price = number(row.get("sheetPrice"), number(row.get("price")))
        row["sheetPrice"] = sheet_price or None
        option_row = option_index.get(ticker)
        broker_price = number((option_row or {}).get("underlyingPrice"))
        if ticker and broker_price > 0:
            old_price = number(row.get("price"))
            row["price"] = round(broker_price, 4)
            row["priceSource"] = "schwab-options-underlying"
            row["priceAsOf"] = options_generated_at
            row["priceOverlay"] = {
                "source": "schwab-options-underlying",
                "appliedAt": generated_at,
                "sourceGeneratedAt": options_generated_at,
                "sheetPrice": sheet_price or None,
                "brokerUnderlyingPrice": round(broker_price, 4),
                "driftPct": round((broker_price - sheet_price) / sheet_price * 100.0, 4)
                if sheet_price > 0
                else None,
                "previousSnapshotPrice": old_price or None,
            }
            refresh_market_context_distances(row, broker_price)
            updated.append(
                {
                    "ticker": ticker,
                    "sheetPrice": sheet_price or None,
                    "brokerUnderlyingPrice": round(broker_price, 4),
                    "driftPct": row["priceOverlay"]["driftPct"],
                }
            )
        else:
            row.setdefault("priceSource", "google-sheet-price")
            row.setdefault("priceAsOf", snapshot.get("generatedAt"))
            if ticker:
                missing.append(ticker)
            unchanged += 1

    summary = {
        "generatedAt": generated_at,
        "stage": "snapshot-price-overlay",
        "source": "schwab-options-underlying",
        "sourceGeneratedAt": options_generated_at or None,
        "status": "ok" if updated else "no-overlays-applied",
        "researchOnly": True,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "counts": {
            "snapshotRows": len(rows),
            "optionRows": len(option_index),
            "updated": len(updated),
            "unchanged": unchanged,
            "missingOptionRows": len(missing),
        },
        "updated": updated,
        "missing": missing[:50],
    }
    snapshot["priceOverlaySummary"] = summary
    return snapshot, summary


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "Inferno Snapshot Price Overlay",
        "",
        f"Generated: {summary.get('generatedAt')}",
        f"Stage: {summary.get('stage')}",
        f"Status: {summary.get('status')}",
        f"Source: {summary.get('source')} | sourceGeneratedAt={summary.get('sourceGeneratedAt')}",
        "Authority: research-only; brokerSubmitAllowed=False; liveTradingAllowed=False",
        "",
        "Counts:",
    ]
    counts = summary.get("counts") or {}
    lines.extend(
        [
            f"- snapshot rows: {counts.get('snapshotRows', 0)}",
            f"- option rows: {counts.get('optionRows', 0)}",
            f"- updated: {counts.get('updated', 0)}",
            f"- unchanged: {counts.get('unchanged', 0)}",
            f"- missing option rows: {counts.get('missingOptionRows', 0)}",
        ]
    )
    updated = summary.get("updated") or []
    if updated:
        lines.extend(["", "Updated prices:"])
        for item in updated[:30]:
            drift = item.get("driftPct")
            drift_text = "n/a" if drift is None else f"{drift:.2f}%"
            sheet_price = item.get("sheetPrice")
            sheet_text = "n/a" if sheet_price is None else f"${sheet_price:.2f}"
            lines.append(
                f"- {item.get('ticker')}: sheet {sheet_text} -> "
                f"broker ${item.get('brokerUnderlyingPrice'):.2f} | drift {drift_text}"
            )
    if summary.get("missing"):
        lines.extend(["", "Missing broker underlyings:"])
        lines.append("- " + ", ".join(summary.get("missing") or []))
    lines.extend(
        [
            "",
            "Next actions:",
            "- Use this local overlay before paper/strike gates compare tracker prices to Schwab chains.",
            "- Keep the Google Sheet operator-owned; do not infer live trading authority from this overlay.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_overlay(*, quiet: bool = False) -> dict[str, Any]:
    ensure_dirs()
    snapshot = load_json_file(SNAPSHOT_FILE) or {}
    options_report = load_json_file(SCHWAB_OPTIONS_FILE) or {}
    snapshot, summary = apply_schwab_price_overlay(snapshot, options_report)
    approval_queue = snapshot.get("approvalQueue") if isinstance(snapshot.get("approvalQueue"), dict) else None
    execution_queue = build_execution_queue(snapshot, approval_queue)
    snapshot["executionQueue"] = execution_queue
    atomic_write_json(SNAPSHOT_FILE, snapshot)
    save_execution_queue(execution_queue)
    atomic_write_json(SNAPSHOT_PRICE_OVERLAY_FILE, summary)
    text = render_report(summary)
    atomic_write_text(SNAPSHOT_PRICE_OVERLAY_TEXT_FILE, text)
    if not quiet:
        print(text, end="")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Overlay fresh Schwab underlyings onto the local tracker snapshot.")
    parser.add_argument("--quiet", action="store_true", help="Write artifacts without printing the text report.")
    args = parser.parse_args()
    run_overlay(quiet=args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
