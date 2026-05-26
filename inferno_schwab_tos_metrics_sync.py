from __future__ import annotations

"""Recompute visible TOS custom metrics from Schwab price history.

This is the bridge the desk needs when TOS is useful for visualization but not
ideal as an automation source. It fetches Schwab daily candles, mirrors the
user's ThinkScript formulas in Python, and writes the canonical
`data/inferno_tos_custom_metrics.json` artifact consumed by the morning
pipeline.

Safety contract:
- read-only market data only
- no account, order, preview, cancel, replace, or staging endpoints
- does not click TOS, write Sheets, or mutate queues
"""

import argparse
import json
from pathlib import Path
from typing import Any

from inferno_io import atomic_write_json, atomic_write_text
from inferno_schwab_price_history import (
    SCHWAB_PRICE_HISTORY_FILE,
    build_report as build_price_history_report,
    load_fixture,
    refresh_access_token_if_possible,
    save_report as save_price_history_report,
    symbols_from_snapshot,
    unique_symbols,
)
from inferno_tos_custom_metrics import (
    build_custom_metrics_report,
    custom_metrics_text,
    save_custom_metrics,
)
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


SCHWAB_TOS_METRICS_SYNC_FILE = DATA_DIR / "inferno_schwab_tos_metrics_sync.json"
SCHWAB_TOS_METRICS_SYNC_TEXT_FILE = REPORTS_DIR / "schwab_tos_metrics_sync_latest.txt"
SCHWAB_TOS_METRICS_SYNC_STAGE = "schwab-tos-custom-metrics-sync"


def build_sync_report(
    *,
    price_history_report: dict[str, Any],
    custom_metrics_report: dict[str, Any],
    symbols: list[str],
    refresh_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact bridge report for command-center visibility."""
    values = custom_metrics_report.get("values") or {}
    return {
        "generatedAt": custom_metrics_report.get("generatedAt"),
        "stage": SCHWAB_TOS_METRICS_SYNC_STAGE,
        "researchOnly": True,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "sourceStatus": price_history_report.get("status"),
        "sourceConfigured": price_history_report.get("configured"),
        "sourceArtifact": str(SCHWAB_PRICE_HISTORY_FILE),
        "customMetricsVerdict": custom_metrics_report.get("verdict"),
        "customMetricsSourceProvider": values.get("sourceProvider"),
        "symbolCount": len(symbols),
        "symbols": symbols,
        "tickersWithMetrics": values.get("tickerCount", 0),
        "metricValueCount": values.get("metricValueCount", 0),
        "missingFormulaMetrics": custom_metrics_report.get("missingFormulaMetrics") or [],
        "historyErrors": price_history_report.get("errors") or [],
        "refreshStatus": refresh_status,
        "nextActions": custom_metrics_report.get("nextActions") or [],
    }


def render_sync_report(payload: dict[str, Any], custom_metrics_report: dict[str, Any]) -> str:
    """Render the Schwab-to-TOS metrics bridge memo."""
    lines = [
        "Inferno Schwab -> TOS Custom Metrics Sync",
        "=" * 42,
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Source status: {payload.get('sourceStatus')} | configured={payload.get('sourceConfigured')}",
        f"Custom metrics verdict: {payload.get('customMetricsVerdict')}",
        f"Symbols requested: {payload.get('symbolCount')} ({', '.join(payload.get('symbols') or [])})",
        f"Tickers with metrics: {payload.get('tickersWithMetrics')}",
        f"Metric values: {payload.get('metricValueCount')}",
        "",
        "Canonical custom-metrics artifact",
    ]
    lines.extend(custom_metrics_text(custom_metrics_report).splitlines())
    if payload.get("historyErrors"):
        lines.extend(["", "History errors"])
        lines.extend(f"- {item.get('symbol')}: {item.get('error')}" for item in payload.get("historyErrors") or [])
    return "\n".join(lines).rstrip() + "\n"


def save_sync_report(payload: dict[str, Any], custom_metrics_report: dict[str, Any]) -> None:
    """Persist the bridge report."""
    ensure_dirs()
    atomic_write_json(SCHWAB_TOS_METRICS_SYNC_FILE, payload)
    atomic_write_text(SCHWAB_TOS_METRICS_SYNC_TEXT_FILE, render_sync_report(payload, custom_metrics_report))


def parse_args() -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(description="Sync TOS-style custom metrics from Schwab price history.")
    parser.add_argument("symbols", nargs="*", help="Ticker symbols. Defaults to data/latest_snapshot.json.")
    parser.add_argument("--from-snapshot", action="store_true", help="Pull symbols from data/latest_snapshot.json")
    parser.add_argument("--limit", type=int, help="Symbol cap for this run")
    parser.add_argument("--fixture", type=Path, help="Use Schwab price-history fixture JSON instead of live API")
    parser.add_argument("--skip-refresh", action="store_true", help="Skip OAuth refresh before live fetch")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    parser.add_argument("--quiet", action="store_true", help="Persist artifacts without printing")
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    fixtures = load_fixture(args.fixture) if args.fixture else None
    if fixtures and not args.symbols:
        symbols = list(fixtures.keys())
    elif args.from_snapshot or not args.symbols:
        symbols = symbols_from_snapshot(limit=args.limit)
    else:
        symbols = unique_symbols(args.symbols, limit=args.limit)

    refresh_status = None
    if fixtures is None and not args.skip_refresh:
        refresh_status = refresh_access_token_if_possible()

    price_history_report = build_price_history_report(
        symbols,
        fixture_payloads=fixtures,
        symbol_limit=args.limit,
    )
    if refresh_status is not None:
        price_history_report["refreshStatus"] = refresh_status
    save_price_history_report(price_history_report)

    custom_metrics_report = build_custom_metrics_report(schwab_history_report=price_history_report)
    save_custom_metrics(custom_metrics_report)

    payload = build_sync_report(
        price_history_report=price_history_report,
        custom_metrics_report=custom_metrics_report,
        symbols=symbols,
        refresh_status=refresh_status,
    )
    save_sync_report(payload, custom_metrics_report)
    if not args.quiet:
        print(json.dumps(payload, indent=2) if args.json else render_sync_report(payload, custom_metrics_report))
    return 0 if payload.get("sourceStatus") in {"ok", "fixture", "partial-error"} and payload.get("metricValueCount", 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
