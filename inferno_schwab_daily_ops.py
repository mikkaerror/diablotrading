from __future__ import annotations

"""Daily Schwab option-chain operations layer.

The raw Schwab chain adapter answers "what did the API return?" This module
answers the operator question: "which symbols are clean enough to care about
today, and which fields should influence strike selection, sizing, and risk?"

Safety contract:
- read-only market-data endpoints only
- no account, order, preview, cancel, or replace endpoints
- no authority promotion
- missing/failed Schwab refresh produces a warning report, not broker action
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from inferno_config import CANDIDATE_BANNED_SETUPS, CANDIDATE_MAX_DAYS_UNTIL_EARNINGS
from inferno_io import atomic_write_json, atomic_write_text
from inferno_schwab_oauth import (
    ENV_FILE,
    SchwabOAuthError,
    load_config,
    parse_env_file,
    refresh_access_token,
    token_status,
)
from server import (
    APPROVAL_QUEUE_FILE,
    DATA_DIR,
    LIVE_ACCOUNT_SYNC_FILE,
    REPORTS_DIR,
    SNAPSHOT_FILE,
    ensure_dirs,
    load_json_file,
)


EXECUTION_QUEUE_FILE = DATA_DIR / "inferno_execution_queue.json"
WATCHLIST_INPUT_FILE = DATA_DIR / "inferno_watchlist_input.json"
SCHWAB_DAILY_OPS_FILE = DATA_DIR / "inferno_schwab_daily_ops.json"
SCHWAB_DAILY_OPS_TEXT_FILE = REPORTS_DIR / "schwab_daily_ops_latest.txt"
SCHWAB_DAILY_OPS_STAGE = "schwab-daily-ops-read-only"
DEFAULT_SYMBOL_LIMIT = 12
DEFAULT_PRIORITY_SLATE_LIMIT = 8

HARD_QUALITY_FLAGS = {
    "empty-chain",
    "missing-underlying-price",
    "missing-atm-pair",
    "no-liquid-contracts",
    "wide-atm-spread",
}

FIELD_CATALOG = [
    {
        "field": "quoteQualityScore / quoteQualityLabel",
        "dailyUse": "Primary chain-quality gate before a ticker reaches strike selection.",
    },
    {
        "field": "atmSpreadPct / atmSpreadQuality",
        "dailyUse": "Execution-friction gate; wide/untradeable spreads block paper tickets.",
    },
    {
        "field": "atmLiquidityScore / liquidContractCount",
        "dailyUse": "Fillability/depth proxy; thin chains stay paper-only or avoided.",
    },
    {
        "field": "atmImpliedMovePct / atmExpectedMoveDollar",
        "dailyUse": "Expected-move benchmark versus ATR, support/resistance, and earnings window.",
    },
    {
        "field": "atmStraddleMid / break-even band",
        "dailyUse": "Premium paid and the price range the market is implying.",
    },
    {
        "field": "atmImpliedVolatility / Greeks completeness",
        "dailyUse": "Volatility regime and whether Greeks are trustworthy enough to size.",
    },
    {
        "field": "topLiquidContracts",
        "dailyUse": "Contract shortlist for later strike selector and broker-preview work.",
    },
]


def number(value: Any, default: float = 0.0) -> float:
    """Coerce loose artifact values into floats for stable gating."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed


def percent_text(value: Any) -> str:
    """Render a decimal percentage from Schwab summaries."""
    parsed = number(value, -1)
    if parsed < 0:
        return "-"
    return f"{parsed * 100:.2f}%"


def money_text(value: Any) -> str:
    """Render optional dollar values without implying trade authority."""
    parsed = number(value, -1)
    if parsed < 0:
        return "-"
    return f"${parsed:,.2f}"


def local_now() -> datetime:
    """Return local wall-clock time without importing config before `.env.schwab`."""
    return datetime.now().astimezone()


def schwab_symbol_limit() -> int:
    """Read the Schwab symbol cap dynamically after `.env.schwab` is loaded."""
    try:
        return int(os.environ.get("SCHWAB_OPTIONS_SYMBOL_LIMIT", str(DEFAULT_SYMBOL_LIMIT)))
    except ValueError:
        return DEFAULT_SYMBOL_LIMIT


def clean_symbol(value: Any) -> str:
    """Normalize a ticker symbol for API calls and artifact joins."""
    return str(value or "").upper().strip().replace("$", "")


def unique_symbols(symbols: list[Any], *, limit: int | None = None) -> list[str]:
    """Return ordered, deduplicated symbols capped to the API-safe limit."""
    out: list[str] = []
    seen: set[str] = set()
    symbol_limit = limit if limit is not None else schwab_symbol_limit()
    for raw in symbols:
        symbol = clean_symbol(raw)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
        if len(out) >= symbol_limit:
            break
    return out


def load_schwab_env(path: Path = ENV_FILE) -> dict[str, str]:
    """Load `.env.schwab` into this process before importing API constants."""
    values = parse_env_file(path)
    for key, value in values.items():
        # The local env file is the source of truth for scheduled runs; setting
        # it here means LaunchAgents do not have to manually `source` secrets.
        os.environ[key] = value
    return values


def symbols_from_payload(payload: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    """Extract ticker-like values from common desk artifact shapes."""
    symbols: list[str] = []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    symbols.append(clean_symbol(item.get("ticker") or item.get("symbol")))
                else:
                    symbols.append(clean_symbol(item))
    return symbols


def symbols_from_positions(payload: dict[str, Any]) -> list[str]:
    """Extract held symbols from the approved read-only live account sync."""
    symbols: list[str] = []
    for item in payload.get("positions") or []:
        if isinstance(item, dict):
            symbols.append(clean_symbol(item.get("symbol") or item.get("ticker")))
        else:
            symbols.append(clean_symbol(item))
    return symbols


def top_priority_slate(payload: dict[str, Any], *, n: int = DEFAULT_PRIORITY_SLATE_LIMIT) -> list[str]:
    """Return top tracker candidates that deserve Schwab chain coverage.

    This is a coverage helper, not an eligibility or authority change. It keeps
    the same catalyst-window and banned-setup filters already used elsewhere,
    then sorts by tracker priority so daily option chains cover the desk's own
    highest-ranked candidates.
    """
    rows: list[dict[str, Any]] = []
    for row in payload.get("rows") or []:
        if not isinstance(row, dict):
            continue
        symbol = clean_symbol(row.get("ticker") or row.get("symbol"))
        if not symbol:
            continue
        setup = str(row.get("setupRec") or "").strip()
        if setup in CANDIDATE_BANNED_SETUPS:
            continue
        if number(row.get("daysUntilEarnings"), 999) > CANDIDATE_MAX_DAYS_UNTIL_EARNINGS:
            continue
        rows.append(row)

    rows.sort(
        key=lambda row: (
            -number(row.get("priority")),
            -number(row.get("readiness")),
            number(row.get("daysUntilEarnings"), 999),
            clean_symbol(row.get("ticker") or row.get("symbol")),
        )
    )
    return unique_symbols([row.get("ticker") or row.get("symbol") for row in rows], limit=n)


def default_symbol_universe(limit: int | None = None) -> list[str]:
    """Choose the daily Schwab pull universe from the current decision slate.

    Order matters: held names stay monitored first, then the priority slate gets
    chain coverage before execution/approval/watchlist backfill. This changes
    market-data coverage only; it does not change eligible tickers, risk gates,
    authority, or broker permissions.
    """
    live_sync = load_json_file(LIVE_ACCOUNT_SYNC_FILE) or {}
    snapshot = load_json_file(SNAPSHOT_FILE) or {}
    execution = load_json_file(EXECUTION_QUEUE_FILE) or {}
    approval = load_json_file(APPROVAL_QUEUE_FILE) or {}
    watchlist = load_json_file(WATCHLIST_INPUT_FILE) or {}
    symbols = (
        symbols_from_positions(live_sync)
        + top_priority_slate(snapshot)
        + symbols_from_payload(execution, ("items", "readyTickers"))
        + symbols_from_payload(approval, ("items",))
        + symbols_from_payload(watchlist, ("tickers", "symbols", "watchlist"))
    )
    return unique_symbols(symbols, limit=limit)


def classify_chain_row(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a Schwab chain summary into an operational lane.

    The thresholds mirror `inferno_risk_policy` but remain advisory here. This
    report tells the operator what to inspect; the risk policy remains the hard
    paper-ticket gate.
    """
    score = number(row.get("quoteQualityScore"), 0)
    liquidity = number(row.get("atmLiquidityScore"), 0)
    spread_quality = str(row.get("atmSpreadQuality") or "unknown")
    label = str(row.get("quoteQualityLabel") or "unknown")
    flags = [str(flag) for flag in row.get("qualityFlags") or []]
    hard_flags = [flag for flag in flags if flag in HARD_QUALITY_FLAGS]

    reasons: list[str] = []
    if hard_flags:
        reasons.append("hard quote flags: " + ", ".join(hard_flags))
    if score < 50:
        reasons.append(f"quote quality below paper threshold ({score:.0f}/{label})")
    elif score < 70:
        reasons.append(f"fragile quote quality ({score:.0f}/{label})")
    if spread_quality in {"wide", "untradeable"}:
        reasons.append(f"ATM spread is {spread_quality}")
    if liquidity < 50:
        reasons.append(f"ATM liquidity too thin ({liquidity:.0f})")
    elif liquidity < 70:
        reasons.append(f"ATM liquidity needs review ({liquidity:.0f})")
    if "incomplete-greeks" in flags:
        reasons.append("Greeks incomplete")

    if not hard_flags and score >= 80 and liquidity >= 70 and spread_quality in {"tight", "acceptable"}:
        lane = "tradable-research"
        action = "Allow into strike research; still require risk gates and human confirmation."
    elif not hard_flags and score >= 70 and liquidity >= 50 and spread_quality in {"tight", "acceptable", "workable"}:
        lane = "paper-ready"
        action = "Good enough for paper staging; inspect contract legs before sizing."
    elif score >= 50 and spread_quality not in {"untradeable"}:
        lane = "manual-review"
        action = "Manual quote review only; do not size up."
    else:
        lane = "avoid-chain"
        action = "Skip for contract work until spreads/liquidity improve."

    return {
        "symbol": row.get("symbol"),
        "lane": lane,
        "action": action,
        "reasons": reasons or ["clean Schwab chain posture"],
        "quoteQualityScore": score,
        "quoteQualityLabel": label,
        "atmSpreadPct": row.get("atmSpreadPct"),
        "atmSpreadQuality": spread_quality,
        "atmLiquidityScore": liquidity,
        "atmLiquidityBucket": row.get("atmLiquidityBucket"),
        "atmImpliedMovePct": row.get("atmImpliedMovePct"),
        "atmExpectedMoveDollar": row.get("atmExpectedMoveDollar"),
        "atmExpectedMoveBucket": row.get("atmExpectedMoveBucket"),
        "atmStraddleMid": row.get("atmStraddleMid"),
        "atmBreakEvenLower": row.get("atmBreakEvenLower"),
        "atmBreakEvenUpper": row.get("atmBreakEvenUpper"),
        "atmImpliedVolatility": row.get("atmImpliedVolatility"),
        "greeksCompletenessPct": row.get("greeksCompletenessPct"),
        "liquidContractCount": row.get("liquidContractCount"),
        "liquidContractRatio": row.get("liquidContractRatio"),
        "underlyingPrice": row.get("underlyingPrice"),
        "topLiquidContracts": (row.get("topLiquidContracts") or [])[:5],
    }


def lane_sort_key(row: dict[str, Any]) -> tuple[int, float, float]:
    """Sort cleanest chains first for the operator memo."""
    lane_rank = {
        "tradable-research": 0,
        "paper-ready": 1,
        "manual-review": 2,
        "avoid-chain": 3,
    }.get(str(row.get("lane")), 9)
    return (lane_rank, -number(row.get("quoteQualityScore")), -number(row.get("atmLiquidityScore")))


def summarize_lanes(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Count rows by operational lane."""
    counts = {"tradable-research": 0, "paper-ready": 0, "manual-review": 0, "avoid-chain": 0}
    for row in rows:
        lane = str(row.get("lane") or "")
        counts[lane] = counts.get(lane, 0) + 1
    return counts


def build_ops_report(chain_report: dict[str, Any], *, symbols: list[str]) -> dict[str, Any]:
    """Build the daily Schwab operations payload from a chain report."""
    rows = [classify_chain_row(row) for row in chain_report.get("rows") or []]
    rows.sort(key=lane_sort_key)
    return {
        "generatedAt": local_now().isoformat(),
        "stage": SCHWAB_DAILY_OPS_STAGE,
        "researchOnly": True,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "sourceStatus": chain_report.get("status"),
        "sourceGeneratedAt": chain_report.get("generatedAt"),
        "configured": chain_report.get("configured"),
        "symbolsRequested": symbols,
        "symbolCount": len(symbols),
        "rows": rows,
        "laneCounts": summarize_lanes(rows),
        "fieldCatalog": FIELD_CATALOG,
        "errors": chain_report.get("errors") or [],
        "operatorRule": "Use Schwab chains as a quote-quality gate only; never as live-submit authority.",
    }


def contract_preview(contracts: list[dict[str, Any]]) -> str:
    """Render compact top-contract candidates for the text memo."""
    if not contracts:
        return "none"
    parts = []
    for contract in contracts[:3]:
        parts.append(
            f"{contract.get('putCall')} {contract.get('strikePrice')} "
            f"{contract.get('expirationDate')} mid {money_text(contract.get('mid'))} "
            f"spr {percent_text(contract.get('spreadPct'))} OI {contract.get('openInterest')}"
        )
    return "; ".join(parts)


def render_ops_report(payload: dict[str, Any]) -> str:
    """Render an operator-facing Schwab daily ops memo."""
    counts = payload.get("laneCounts") or {}
    lines = [
        "Inferno Schwab Daily Ops",
        "=" * 24,
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Source status: {payload.get('sourceStatus')} | configured={payload.get('configured')}",
        f"Symbols requested: {payload.get('symbolCount')} ({', '.join(payload.get('symbolsRequested') or [])})",
        "",
        "Operational lanes",
        f"- tradable-research: {counts.get('tradable-research', 0)}",
        f"- paper-ready: {counts.get('paper-ready', 0)}",
        f"- manual-review: {counts.get('manual-review', 0)}",
        f"- avoid-chain: {counts.get('avoid-chain', 0)}",
        "",
        "Daily Schwab values to use",
    ]
    for item in FIELD_CATALOG:
        lines.append(f"- {item['field']}: {item['dailyUse']}")

    lines.extend(["", "Ticker lanes"])
    for row in payload.get("rows") or []:
        lines.append(
            f"- {row.get('symbol')}: {row.get('lane')} | "
            f"Q {row.get('quoteQualityScore'):.0f}/{row.get('quoteQualityLabel')} | "
            f"spread {row.get('atmSpreadQuality')} {percent_text(row.get('atmSpreadPct'))} | "
            f"liq {row.get('atmLiquidityScore'):.0f} | "
            f"move {percent_text(row.get('atmImpliedMovePct'))} / {money_text(row.get('atmExpectedMoveDollar'))} | "
            f"straddle {money_text(row.get('atmStraddleMid'))}"
        )
        lines.append(
            f"  BE {money_text(row.get('atmBreakEvenLower'))} - "
            f"{money_text(row.get('atmBreakEvenUpper'))}; "
            f"top: {contract_preview(row.get('topLiquidContracts') or [])}"
        )
        lines.append(f"  Action: {row.get('action')}")
        lines.append(f"  Reasons: {'; '.join(row.get('reasons') or [])}")
    if not payload.get("rows"):
        lines.append("- No Schwab rows available.")
    if payload.get("errors"):
        lines.extend(["", "Errors"])
        lines.extend(f"- {item.get('symbol')}: {item.get('error')}" for item in payload.get("errors") or [])
    lines.extend(["", f"Rule: {payload.get('operatorRule')}"])
    return "\n".join(lines).rstrip() + "\n"


def save_ops_report(payload: dict[str, Any]) -> None:
    """Persist daily Schwab ops JSON + text artifacts."""
    ensure_dirs()
    atomic_write_json(SCHWAB_DAILY_OPS_FILE, payload)
    atomic_write_text(SCHWAB_DAILY_OPS_TEXT_FILE, render_ops_report(payload))


def live_chain_report(symbols: list[str], *, fixture: Path | None = None, skip_refresh: bool = False) -> dict[str, Any]:
    """Refresh OAuth if possible, then build the latest Schwab chain report."""
    load_schwab_env()
    from inferno_schwab_options import build_report, load_fixture, save_report

    if fixture:
        fixtures = load_fixture(fixture)
        report = build_report(symbols or list(fixtures.keys()), fixture_payloads=fixtures)
        save_report(report)
        return report

    if not skip_refresh:
        try:
            config = load_config()
            status = token_status(config)
            if status.get("reauthorizationRequired"):
                raise SchwabOAuthError(
                    "Schwab reauthorization is required. Run "
                    "`python3 inferno_schwab_oauth.py restart` once."
                )
            if (
                status.get("refreshTokenPresent")
                and status.get("accessTokenNeedsRefresh")
                and not status.get("reauthorizationRequired")
            ):
                refresh_access_token(config)
        except SchwabOAuthError:
            raise
        except Exception:  # noqa: BLE001 - chain fetch still reports if token is stale.
            pass

    report = build_report(symbols)
    save_report(report)
    return report


def parse_args() -> argparse.Namespace:
    """Parse CLI args for daily Schwab operations."""
    parser = argparse.ArgumentParser(description="Build the read-only Schwab daily ops report.")
    parser.add_argument("symbols", nargs="*", help="Optional symbols. Defaults to execution/approval/watchlist slate.")
    parser.add_argument("--fixture", type=Path, help="Use a Schwab chain fixture instead of the live API.")
    parser.add_argument("--skip-refresh", action="store_true", help="Skip OAuth token refresh before fetching chains.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    parser.add_argument("--quiet", action="store_true", help="Persist artifacts without printing the memo.")
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    load_schwab_env()
    symbols = unique_symbols(args.symbols) if args.symbols else default_symbol_universe()
    try:
        chain_report = live_chain_report(
            symbols,
            fixture=args.fixture,
            skip_refresh=args.skip_refresh,
        )
    except SchwabOAuthError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    payload = build_ops_report(chain_report, symbols=symbols)
    save_ops_report(payload)
    if not args.quiet:
        print(json.dumps(payload, indent=2) if args.json else render_ops_report(payload))
    return 0 if payload.get("sourceStatus") in {"ok", "fixture", "partial-error"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
