from __future__ import annotations

"""Read-only drift audit for TOS-style tracker formulas.

This module compares the latest tracker/snapshot values for RVOL, trend,
support/resistance, and momentum against the local formula mirror. It is a
diagnostic lane only: no broker actions, no queue mutation, no staging.
"""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yfinance as yf

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_tos_formula_math import (
    FORMULA_VERSION,
    build_market_context_from_history,
    number,
    tracker_score_snapshot_from_row,
)
from server import DATA_DIR, REPORTS_DIR, SNAPSHOT_FILE, ensure_dirs, load_json_file


TOS_FORMULA_AUDIT_FILE = DATA_DIR / "inferno_tos_formula_audit.json"
TOS_FORMULA_AUDIT_TEXT_FILE = REPORTS_DIR / "tos_formula_audit_latest.txt"
AUDIT_STAGE = "tos-formula-audit-diagnostic-only"

RVOL_DRIFT_THRESHOLD = 0.35
LEVEL_DRIFT_THRESHOLD_PCT = 3.0
MOMENTUM_DRIFT_THRESHOLD = 0.45

HistoryLoader = Callable[[str], pd.DataFrame]


def norm(value: Any) -> str:
    """Normalize labels/symbols for comparison."""
    return str(value or "").strip().upper()


def text(value: Any) -> str:
    """Return stripped display text."""
    return str(value or "").strip()


def normalize_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Flatten yfinance output into the formula mirror's expected OHLCV shape."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    normalized = frame.copy()
    if isinstance(normalized.columns, pd.MultiIndex):
        normalized.columns = [column[0] if isinstance(column, tuple) else column for column in normalized.columns]
    return normalized


def download_history(symbol: str, *, period: str = "6mo") -> pd.DataFrame:
    """Load history for a symbol via yfinance."""
    try:
        return normalize_history_frame(
            yf.download(symbol, period=period, progress=False, auto_adjust=False, threads=False)
        )
    except Exception:  # noqa: BLE001 - network providers can fail in many ways
        return pd.DataFrame()


def snapshot_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the main tracker rows from a snapshot artifact."""
    rows = snapshot.get("rows")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    tickets = snapshot.get("tickets")
    if isinstance(tickets, list):
        return [row for row in tickets if isinstance(row, dict)]
    return []


def row_trend_label(row: dict[str, Any]) -> str | None:
    """Resolve trend label from row or embedded market context."""
    raw = row.get("trend")
    if text(raw):
        return text(raw)
    market_context = row.get("marketContext") if isinstance(row.get("marketContext"), dict) else {}
    trend = market_context.get("trend")
    if isinstance(trend, dict) and text(trend.get("label")):
        return text(trend.get("label"))
    if text(trend):
        return text(trend)
    return None


def level_delta_pct(observed: float | None, calculated: float | None) -> float | None:
    """Return absolute level drift as percent of observed level."""
    if observed is None or calculated is None:
        return None
    denominator = max(abs(observed), 1.0)
    return round(abs(calculated - observed) / denominator * 100.0, 4)


def compare_row_to_context(row: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Compare one tracker row to one formula context."""
    flags: list[str] = []
    deltas: dict[str, Any] = {}

    sheet_rvol = number(row.get("rvol"))
    calculated_rvol = number(context.get("rvol"))
    if sheet_rvol is not None and calculated_rvol is not None:
        deltas["rvol"] = round(calculated_rvol - sheet_rvol, 4)
        if abs(deltas["rvol"]) > RVOL_DRIFT_THRESHOLD:
            flags.append("rvol-drift")

    sheet_trend = row_trend_label(row)
    calculated_trend = text((context.get("trend") or {}).get("label")) if isinstance(context.get("trend"), dict) else None
    if sheet_trend and calculated_trend:
        deltas["trendMatch"] = sheet_trend.strip().lower() == calculated_trend.strip().lower()
        if not deltas["trendMatch"]:
            flags.append("trend-mismatch")

    for field, flag in (("support", "support-drift"), ("resistance", "resistance-drift")):
        observed = number(row.get(field))
        calculated = number(context.get(field))
        drift_pct = level_delta_pct(observed, calculated)
        if drift_pct is not None:
            deltas[f"{field}DriftPct"] = drift_pct
            if drift_pct > LEVEL_DRIFT_THRESHOLD_PCT:
                flags.append(flag)

    tracker_scores = tracker_score_snapshot_from_row(row)
    sheet_momentum = number(row.get("momentumScore"))
    formula_momentum = number(tracker_scores.get("momentumScore"))
    if sheet_momentum is not None and formula_momentum is not None:
        deltas["momentumScore"] = round(formula_momentum - sheet_momentum, 4)
        if abs(deltas["momentumScore"]) > MOMENTUM_DRIFT_THRESHOLD:
            flags.append("momentum-drift")

    return {
        "ticker": norm(row.get("ticker")),
        "status": "review" if flags else "clean",
        "flags": flags,
        "deltas": deltas,
        "tracker": {
            "rvol": sheet_rvol,
            "trend": sheet_trend,
            "support": number(row.get("support")),
            "resistance": number(row.get("resistance")),
            "momentumScore": sheet_momentum,
        },
        "calculated": {
            "rvol": calculated_rvol,
            "trend": calculated_trend,
            "support": number(context.get("support")),
            "resistance": number(context.get("resistance")),
            "momentumScore": formula_momentum,
            "momentumSemantics": "positive-iv-rank-change",
            "priceMomentumScore": number(context.get("priceMomentumScore") or context.get("momentumScore")),
            "strengthScore": number(context.get("strengthScore")),
            "strengthLabel": context.get("strengthLabel"),
            "alignmentScore": number(context.get("alignmentScore")),
            "alignmentLabel": context.get("alignmentLabel"),
            "trackerScoreFormula": tracker_scores,
        },
    }


def selected_rows(rows: list[dict[str, Any]], *, symbols: set[str] | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Filter and cap rows for an audit run."""
    filtered = []
    for row in rows:
        ticker = norm(row.get("ticker"))
        if not ticker:
            continue
        if symbols and ticker not in symbols:
            continue
        filtered.append(row)
        if len(filtered) >= max(0, limit):
            break
    return filtered


def build_formula_audit(
    snapshot: dict[str, Any],
    *,
    limit: int = 20,
    symbols: set[str] | None = None,
    benchmark: str | None = "QQQ",
    history_loader: HistoryLoader = download_history,
) -> dict[str, Any]:
    """Build a read-only drift audit from a snapshot artifact."""
    all_rows = snapshot_rows(snapshot)
    rows = selected_rows(all_rows, symbols=symbols, limit=limit)
    benchmark_symbol = norm(benchmark) if benchmark else None
    benchmark_history = history_loader(benchmark_symbol) if benchmark_symbol else None
    if benchmark_history is not None:
        benchmark_history = normalize_history_frame(benchmark_history)
        if benchmark_history.empty:
            benchmark_history = None

    checked: list[dict[str, Any]] = []
    load_errors: list[dict[str, str]] = []
    flag_counts: Counter[str] = Counter()
    for row in rows:
        ticker = norm(row.get("ticker"))
        history = normalize_history_frame(history_loader(ticker))
        if history.empty:
            load_errors.append({"ticker": ticker, "reason": "missing-history"})
            continue
        try:
            context = build_market_context_from_history(
                history,
                price=number(row.get("price")),
                atr_z_score=number(row.get("atrZScore")),
                iv_rank_change=number(row.get("ivRankChange")),
                benchmark_history=benchmark_history,
            )
        except Exception as exc:  # noqa: BLE001 - diagnostic lane should keep reporting
            load_errors.append({"ticker": ticker, "reason": f"formula-error: {exc}"})
            continue
        comparison = compare_row_to_context(row, context)
        checked.append(comparison)
        flag_counts.update(comparison["flags"])

    if not rows:
        verdict = "insufficient-data"
    elif load_errors and not checked:
        verdict = "insufficient-history"
    elif flag_counts:
        verdict = "formula-drift-review"
    else:
        verdict = "formula-sync-clean"

    return {
        "generatedAt": local_now().isoformat(),
        "stage": AUDIT_STAGE,
        "formulaVersion": FORMULA_VERSION,
        "authority": {
            "readOnly": True,
            "stagesTrades": False,
            "touchesBroker": False,
            "touchesSheets": False,
        },
        "snapshotGeneratedAt": snapshot.get("generatedAt"),
        "benchmark": benchmark_symbol,
        "limit": limit,
        "requestedSymbols": sorted(symbols) if symbols else [],
        "universeRows": len(all_rows),
        "selectedRows": len(rows),
        "checked": len(checked),
        "loadErrors": load_errors,
        "flagCounts": dict(sorted(flag_counts.items())),
        "verdict": verdict,
        "rows": checked,
        "thresholds": {
            "rvolDrift": RVOL_DRIFT_THRESHOLD,
            "levelDriftPct": LEVEL_DRIFT_THRESHOLD_PCT,
            "momentumDrift": MOMENTUM_DRIFT_THRESHOLD,
        },
    }


def formula_audit_text(payload: dict[str, Any]) -> str:
    """Render a compact operator memo."""
    lines = [
        "# TOS Formula Audit",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Formula version: {payload.get('formulaVersion')}",
        f"Benchmark: {payload.get('benchmark') or 'none'}",
        f"Rows checked: {payload.get('checked')} / selected {payload.get('selectedRows')}",
        "",
        "Authority: read-only diagnostic; no broker, sheet, queue, or staging writes.",
    ]
    flag_counts = payload.get("flagCounts") or {}
    if flag_counts:
        lines.append("")
        lines.append("Flag counts:")
        for flag, count in flag_counts.items():
            lines.append(f"- {flag}: {count}")

    load_errors = payload.get("loadErrors") or []
    if load_errors:
        lines.append("")
        lines.append("History gaps:")
        for item in load_errors[:10]:
            lines.append(f"- {item.get('ticker')}: {item.get('reason')}")

    review_rows = [row for row in payload.get("rows") or [] if row.get("flags")]
    clean_rows = [row for row in payload.get("rows") or [] if not row.get("flags")]
    if review_rows:
        lines.append("")
        lines.append("Rows needing formula review:")
        for row in review_rows[:12]:
            calc = row.get("calculated") or {}
            tracker = row.get("tracker") or {}
            deltas = row.get("deltas") or {}
            lines.append(
                "- "
                f"{row.get('ticker')}: {', '.join(row.get('flags') or [])}; "
                f"RVOL {tracker.get('rvol')} -> {calc.get('rvol')}, "
                f"trend {tracker.get('trend')} -> {calc.get('trend')}, "
                f"tracker momentum {tracker.get('momentumScore')} -> {calc.get('momentumScore')}, "
                f"price momentum {calc.get('priceMomentumScore')}, "
                f"deltas {deltas}"
            )
    elif clean_rows:
        lines.append("")
        lines.append("No drift flags on checked rows.")

    lines.append("")
    lines.append("Next action: copy any exact TOS custom-column formulas into docs/TOS_FORMULA_MIRROR.md, then tune thresholds here.")
    return "\n".join(lines) + "\n"


def parse_symbols(raw: str | None) -> set[str] | None:
    """Parse comma-separated symbols from CLI input."""
    if not raw:
        return None
    symbols = {norm(part) for part in raw.split(",") if norm(part)}
    return symbols or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default=str(SNAPSHOT_FILE), help="Snapshot JSON path")
    parser.add_argument("--limit", type=int, default=20, help="Maximum rows to audit")
    parser.add_argument("--symbols", help="Comma-separated symbols to audit")
    parser.add_argument("--benchmark", default="QQQ", help="Benchmark symbol for relative strength")
    parser.add_argument("--skip-benchmark", action="store_true", help="Do not load benchmark history")
    parser.add_argument("--json", action="store_true", help="Print JSON payload path/status")
    args = parser.parse_args(argv)

    ensure_dirs()
    snapshot = load_json_file(Path(args.snapshot))
    if snapshot is None:
        snapshot = {}

    payload = build_formula_audit(
        snapshot,
        limit=max(0, args.limit),
        symbols=parse_symbols(args.symbols),
        benchmark=None if args.skip_benchmark else args.benchmark,
    )
    atomic_write_json(TOS_FORMULA_AUDIT_FILE, payload)
    atomic_write_text(TOS_FORMULA_AUDIT_TEXT_FILE, formula_audit_text(payload))
    if args.json:
        print(
            json.dumps(
                {
                    "verdict": payload.get("verdict"),
                    "checked": payload.get("checked"),
                    "flagCounts": payload.get("flagCounts"),
                    "artifact": str(TOS_FORMULA_AUDIT_FILE),
                    "report": str(TOS_FORMULA_AUDIT_TEXT_FILE),
                },
                indent=2,
            )
        )
    else:
        print(formula_audit_text(payload), end="")
    return 0 if payload.get("verdict") in {"formula-sync-clean", "insufficient-data"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
