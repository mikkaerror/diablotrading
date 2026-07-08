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
PAPER_TEST_DIRECTOR_FILE = DATA_DIR / "inferno_paper_test_director.json"
STRATEGY_ALTERNATIVE_SCORER_FILE = DATA_DIR / "inferno_strategy_alternative_scorer.json"
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
        "dailyUse": "Secondary depth context; paper pass/fail is spread-primary with an OI floor.",
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
    sync_schwab_market_data_config(values)
    return values


def _truthy_env(value: str | None) -> bool:
    """Return the boolean convention used by `inferno_config` env flags."""
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def sync_schwab_market_data_config(values: dict[str, str]) -> None:
    """Mirror `.env.schwab` into already-imported read-only Schwab constants."""
    import inferno_config as config

    updates: dict[str, Any] = {}
    if "SCHWAB_OPTIONS_ENABLED" in values:
        updates["SCHWAB_OPTIONS_ENABLED"] = _truthy_env(values.get("SCHWAB_OPTIONS_ENABLED"))
    if "SCHWAB_TOKEN_FILE" in values:
        updates["SCHWAB_TOKEN_FILE"] = Path(values["SCHWAB_TOKEN_FILE"]).expanduser()
    if "SCHWAB_API_BASE_URL" in values:
        updates["SCHWAB_API_BASE_URL"] = values["SCHWAB_API_BASE_URL"].strip().rstrip("/")
    if "SCHWAB_OPTIONS_TIMEOUT_SECONDS" in values:
        updates["SCHWAB_OPTIONS_TIMEOUT_SECONDS"] = float(values["SCHWAB_OPTIONS_TIMEOUT_SECONDS"])
    if "SCHWAB_OPTIONS_SYMBOL_LIMIT" in values:
        updates["SCHWAB_OPTIONS_SYMBOL_LIMIT"] = int(values["SCHWAB_OPTIONS_SYMBOL_LIMIT"])
    if "SCHWAB_OPTIONS_STRIKE_COUNT" in values:
        updates["SCHWAB_OPTIONS_STRIKE_COUNT"] = int(values["SCHWAB_OPTIONS_STRIKE_COUNT"])

    for key, value in updates.items():
        setattr(config, key, value)

    options_module = sys.modules.get("inferno_schwab_options")
    if options_module is not None:
        for key, value in updates.items():
            setattr(options_module, key, value)
        if "SCHWAB_OPTIONS_STRIKE_COUNT" in updates:
            options_module.DEFAULT_CHAIN_PARAMS = {
                "strikeCount": updates["SCHWAB_OPTIONS_STRIKE_COUNT"],
            }


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

    Order matters: held names stay monitored first, then current paper and
    strategy-research rows get chain coverage before execution, approval,
    tracker-priority, and watchlist backfill. This changes market-data coverage
    only; it does not change eligible tickers, risk gates, authority, or broker
    permissions.
    """
    live_sync = load_json_file(LIVE_ACCOUNT_SYNC_FILE) or {}
    snapshot = load_json_file(SNAPSHOT_FILE) or {}
    paper_director = load_json_file(PAPER_TEST_DIRECTOR_FILE) or {}
    alternative_scorer = load_json_file(STRATEGY_ALTERNATIVE_SCORER_FILE) or {}
    execution = load_json_file(EXECUTION_QUEUE_FILE) or {}
    approval = load_json_file(APPROVAL_QUEUE_FILE) or {}
    watchlist = load_json_file(WATCHLIST_INPUT_FILE) or {}
    symbols = (
        symbols_from_positions(live_sync)
        + symbols_from_payload(
            paper_director,
            (
                "stageableSlate",
                "autoPaperSlate",
                "researchWatchlist",
                "pricedPaperVariantWatchlist",
                "constructionWatchlist",
            ),
        )
        + symbols_from_payload(alternative_scorer, ("scorecards",))
        + symbols_from_payload(execution, ("items", "readyTickers"))
        + symbols_from_payload(approval, ("items",))
        + top_priority_slate(snapshot)
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
    paper_pass = bool(row.get("paperLiquidityPass"))
    live_pass = bool(row.get("liveLiquidityPass"))
    paper_block = str(row.get("paperLiquidityBlockReason") or "")

    reasons: list[str] = []
    if hard_flags:
        reasons.append("hard quote flags: " + ", ".join(hard_flags))
    if not paper_pass:
        reasons.append(f"paper spread/OI gate failed: {paper_block or 'spread/OI gate failed'}")
    if score < 50:
        reasons.append(f"quote quality below paper threshold ({score:.0f}/{label})")
    elif score < 70:
        reasons.append(f"fragile quote quality ({score:.0f}/{label})")
    if spread_quality == "untradeable":
        reasons.append(f"ATM spread is {spread_quality}")
    elif spread_quality == "wide" and not paper_pass:
        reasons.append(f"ATM spread is {spread_quality}")
    if liquidity < 70:
        reasons.append(f"ATM liquidity score is secondary ({liquidity:.0f})")
    if "incomplete-greeks" in flags:
        reasons.append("Greeks incomplete")

    if live_pass and not hard_flags and score >= 70:
        lane = "tradable-research"
        action = "Allow into strike research; still require risk gates and human confirmation."
    elif paper_pass and not hard_flags:
        lane = "paper-ready"
        action = "Paper-admissible by spread/OI; charge full ATM spread as modeled friction."
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
        "atmWindowMedianSpreadPct": row.get("atmWindowMedianSpreadPct"),
        "atmWindowOpenInterest": row.get("atmWindowOpenInterest"),
        "paperLiquidityPass": paper_pass,
        "paperLiquidityBlockReason": row.get("paperLiquidityBlockReason"),
        "liveLiquidityPass": live_pass,
        "liveLiquidityBlockReason": row.get("liveLiquidityBlockReason"),
        "paperFillFrictionPct": row.get("paperFillFrictionPct"),
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
            f"win spr {percent_text(row.get('atmWindowMedianSpreadPct'))} | "
            f"win OI {int(number(row.get('atmWindowOpenInterest'), 0))} | "
            f"paper {'pass' if row.get('paperLiquidityPass') else 'fail'} | "
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
