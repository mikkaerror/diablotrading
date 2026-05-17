from __future__ import annotations

"""Live account synchronization and audit for the Inferno desk.

This module turns the already-scraped thinkorswim Account Statement packet into
one durable artifact that the rest of the stack can trust. The goal is simple:
keep the live account read-only, keep the approved suffix guard in place, and
attach tracker context to every live holding so the desk can reason about
positions without hand-reading TOS every time.

The sync stays intentionally conservative:
1. read the latest account-statement artifact or refresh it from the open pane
2. prove the visible account belongs to the allowed live suffix set
3. enrich each holding with tracker/dash context from `latest_snapshot.json`
4. emit JSON + text artifacts that doctor/ops can verify independently
"""

import argparse
import json
from typing import Any

from inferno_config import TOS_ALLOWED_ACCOUNT_SUFFIXES, TOS_ALLOW_LIVE_READONLY, local_now
from inferno_tos_account_statement_scraper import ACCOUNT_STATEMENT_FILE, ACCOUNT_STATEMENT_LAST_GOOD_FILE, scrape_account_statement
from inferno_tos_session_probe import probe_tos_session
from server import DATA_DIR, REPORTS_DIR, SNAPSHOT_FILE, ensure_dirs, load_json_file


LIVE_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_live_account_sync.json"
LIVE_ACCOUNT_SYNC_TEXT_FILE = REPORTS_DIR / "live_account_sync_latest.txt"


def text(value: Any) -> str:
    """Normalize any value into trimmed display text."""
    return str(value or "").strip()


def numeric(value: Any) -> float | None:
    """Parse loose numeric values into floats when possible."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = text(value).replace("$", "").replace(",", "").replace("%", "")
    if not raw or raw in {"N/A", "--"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def suffix_match(candidates: list[str]) -> str | None:
    """Return the allowed live-account suffix that matches the current probe."""
    for allowed in TOS_ALLOWED_ACCOUNT_SUFFIXES:
        normalized_allowed = text(allowed)
        if not normalized_allowed:
            continue
        for candidate in candidates:
            normalized_candidate = text(candidate)
            if normalized_candidate.endswith(normalized_allowed):
                return normalized_allowed
    return None


def bucket_for_position(snapshot_row: dict[str, Any] | None) -> str:
    """Classify a live holding into the desk's current strategy sleeve."""
    if not snapshot_row:
        return "off-book"

    long_term_score = numeric(snapshot_row.get("longTermScore")) or 0.0
    accumulation_bias = text(snapshot_row.get("accumulationBias")).lower()
    ready_score = numeric(snapshot_row.get("readyScore")) or 0.0
    priority = numeric(snapshot_row.get("priority")) or 0.0

    if long_term_score >= 3 and accumulation_bias not in {"avoid", "none"}:
        return "long-term-core"
    if ready_score >= 2 or priority >= 5:
        return "catalyst-active"
    return "monitor"


def risk_flags(position: dict[str, Any], snapshot_row: dict[str, Any] | None, weight_pct: float | None) -> list[str]:
    """Return compact live-position risk flags for operator review."""
    flags: list[str] = []
    if weight_pct is not None and weight_pct >= 35:
        # Concentration above one-third of net-liq deserves an operator glance.
        flags.append("concentration")

    if not snapshot_row:
        flags.append("untracked")
        return flags

    days_until_earnings = numeric(snapshot_row.get("daysUntilEarnings"))
    if days_until_earnings is not None and 0 <= days_until_earnings <= 7:
        flags.append("earnings-soon")

    market_context = snapshot_row.get("marketContext") or {}
    alignment_label = text(market_context.get("alignmentLabel")).lower()
    if alignment_label in {"fragile", "unconfirmed"}:
        flags.append("fragile-alignment")

    urgency = text(snapshot_row.get("urgency")).lower()
    if "close" in urgency:
        flags.append("close-window")

    pl_percent = numeric(position.get("plPercent"))
    if pl_percent is not None and pl_percent <= -10:
        flags.append("drawdown")

    return flags


def build_position_packet(position: dict[str, Any], snapshot_row: dict[str, Any] | None, net_liq: float | None) -> dict[str, Any]:
    """Merge broker and tracker context into one live-position packet."""
    mark_value = numeric(position.get("markValue"))
    weight_pct = None
    if mark_value is not None and net_liq and net_liq > 0:
        weight_pct = round((mark_value / net_liq) * 100, 2)

    market_context = (snapshot_row or {}).get("marketContext") or {}
    trend = market_context.get("trend") or {}
    packet = {
        "symbol": text(position.get("symbol")),
        "description": text(position.get("description")),
        "qty": position.get("qty"),
        "mark": position.get("mark"),
        "markValue": position.get("markValue"),
        "derivedTradePrice": position.get("derivedTradePrice"),
        "plOpen": position.get("plOpen"),
        "plPercent": position.get("plPercent"),
        "weightPct": weight_pct,
        "trackerMatched": snapshot_row is not None,
        "bucket": bucket_for_position(snapshot_row),
        "riskFlags": [],
        "trackerContext": None,
    }

    packet["riskFlags"] = risk_flags(packet, snapshot_row, weight_pct)

    if snapshot_row is not None:
        packet["trackerContext"] = {
            "priority": snapshot_row.get("priority"),
            "readyScore": snapshot_row.get("readyScore"),
            "longTermScore": snapshot_row.get("longTermScore"),
            "setupRec": snapshot_row.get("setupRec"),
            "urgency": snapshot_row.get("urgency"),
            "nextEarnings": snapshot_row.get("nextEarnings"),
            "daysUntilEarnings": snapshot_row.get("daysUntilEarnings"),
            "accumulationBias": snapshot_row.get("accumulationBias"),
            "status": snapshot_row.get("status"),
            "alignmentLabel": market_context.get("alignmentLabel"),
            "alignmentScore": market_context.get("alignmentScore"),
            "trendLabel": trend.get("label"),
            "rvol": market_context.get("rvol"),
            "support": market_context.get("support"),
            "resistance": market_context.get("resistance"),
        }
    return packet


def load_statement(*, refresh: bool) -> dict[str, Any]:
    """Load the latest account statement packet, optionally re-scraping it."""
    existing = load_json_file(ACCOUNT_STATEMENT_FILE)
    last_good = load_json_file(ACCOUNT_STATEMENT_LAST_GOOD_FILE)
    if refresh:
        refreshed = scrape_account_statement()
        if refreshed.get("ok"):
            return refreshed
        fallback_source = None
        if existing and existing.get("ok"):
            fallback_source = existing
        elif last_good and last_good.get("ok"):
            fallback_source = last_good
        if fallback_source:
            fallback = dict(fallback_source)
            fallback["_refreshFallback"] = text(refreshed.get("message")) or "fresh scrape unavailable"
            return fallback
        return refreshed
    if existing and existing.get("ok"):
        return existing
    if last_good and last_good.get("ok"):
        return last_good
    if existing:
        return existing
    if last_good:
        return last_good
    return scrape_account_statement()


def build_live_account_sync(*, refresh_statement: bool = False) -> dict[str, Any]:
    """Build the live-account sync artifact from the approved read-only account."""
    ensure_dirs()

    statement = load_statement(refresh=refresh_statement)
    session_probe = probe_tos_session()
    raw_statement_mode = text(statement.get("accountMode")).lower()
    raw_session_mode = text(session_probe.get("accountMode")).lower()
    statement_mode = raw_statement_mode if raw_statement_mode not in {"", "unknown"} else raw_session_mode
    suffixes = [text(item) for item in (statement.get("accountSuffixCandidates") or []) if text(item)]
    if not suffixes:
        suffixes = [text(item) for item in (session_probe.get("accountSuffixCandidates") or []) if text(item)]
    matched_suffix = suffix_match(suffixes)
    snapshot = load_json_file(SNAPSHOT_FILE) or {}
    snapshot_rows = snapshot.get("rows") or []
    snapshot_by_ticker = {text(row.get("ticker")).upper(): row for row in snapshot_rows if text(row.get("ticker"))}
    net_liq = numeric(statement.get("netLiquidatingValue"))

    report: dict[str, Any] = {
        "generatedAt": local_now().isoformat(),
        "ok": False,
        "verdict": "blocked",
        "message": "",
        "statementGeneratedAt": statement.get("generatedAt"),
        "statementOk": statement.get("ok"),
        "statementRefreshFallback": statement.get("_refreshFallback"),
        "accountMode": statement_mode or statement.get("accountMode"),
        "allowedLiveReadonly": TOS_ALLOW_LIVE_READONLY,
        "allowedSuffixes": list(TOS_ALLOWED_ACCOUNT_SUFFIXES),
        "matchedSuffix": matched_suffix,
        "accountSuffixCandidates": suffixes,
        "sessionSummary": session_probe.get("summary"),
        "netLiquidatingValue": statement.get("netLiquidatingValue"),
        "totalCash": statement.get("totalCash"),
        "positions": [],
        "counts": {
            "positions": 0,
            "matchedPositions": 0,
            "unmatchedPositions": 0,
            "concentrationFlags": 0,
            "earningsSoonFlags": 0,
            "fragileAlignmentFlags": 0,
        },
        "nextActions": [],
    }

    if not statement.get("ok"):
        report["message"] = text(statement.get("message")) or "account statement scrape unavailable"
        save_live_account_sync(report)
        return report

    if statement_mode != "live":
        report["message"] = "account statement is not scoped to a live account"
        save_live_account_sync(report)
        return report

    if not TOS_ALLOW_LIVE_READONLY or not matched_suffix:
        report["message"] = "visible live account is not approved for read-only automation"
        save_live_account_sync(report)
        return report

    positions: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for position in statement.get("positions") or []:
        ticker = text(position.get("symbol")).upper()
        snapshot_row = snapshot_by_ticker.get(ticker)
        packet = build_position_packet(position, snapshot_row, net_liq)
        positions.append(packet)
        if not packet.get("trackerMatched"):
            unmatched.append(ticker)

    concentration_flags = sum(1 for item in positions if "concentration" in (item.get("riskFlags") or []))
    earnings_flags = sum(1 for item in positions if "earnings-soon" in (item.get("riskFlags") or []))
    fragile_flags = sum(1 for item in positions if "fragile-alignment" in (item.get("riskFlags") or []))

    report["positions"] = sorted(
        positions,
        key=lambda item: (numeric(item.get("weightPct")) or 0.0, numeric(item.get("markValue")) or 0.0),
        reverse=True,
    )
    report["counts"] = {
        "positions": len(positions),
        "matchedPositions": len(positions) - len(unmatched),
        "unmatchedPositions": len(unmatched),
        "concentrationFlags": concentration_flags,
        "earningsSoonFlags": earnings_flags,
        "fragileAlignmentFlags": fragile_flags,
    }

    next_actions: list[str] = []
    if unmatched:
        next_actions.append(f"Add or intentionally exclude: {', '.join(sorted(set(unmatched)))}.")
    if concentration_flags:
        next_actions.append("Review concentrated live holdings before layering new risk.")
    if earnings_flags:
        next_actions.append("Review earnings-near positions before the next catalyst window.")
    if fragile_flags:
        next_actions.append("Re-check weak alignment names against support/resistance before adding exposure.")
    if not next_actions:
        next_actions.append("Live holdings are synced and tracker-aligned.")
    report["nextActions"] = next_actions

    if unmatched or concentration_flags:
        report["verdict"] = "attention"
        report["ok"] = True
        report["message"] = "live holdings synced, but operator review is needed"
    else:
        report["verdict"] = "healthy"
        report["ok"] = True
        report["message"] = f"live holdings synced for approved account suffix {matched_suffix}"

    if report.get("statementRefreshFallback"):
        report["nextActions"].append(f"Fresh scrape fallback used: {report.get('statementRefreshFallback')}.")

    save_live_account_sync(report)
    return report


def live_account_sync_text(report: dict[str, Any]) -> str:
    """Render the latest live-account sync into an operator-friendly report."""
    counts = report.get("counts") or {}
    lines = [
        "Inferno Live Account Sync",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Verdict: {report.get('verdict')}",
        f"Message: {report.get('message')}",
        f"Account mode: {report.get('accountMode')}",
        f"Allowed live readonly: {report.get('allowedLiveReadonly')}",
        f"Matched suffix: {report.get('matchedSuffix') or '-'}",
        f"Visible suffixes: {', '.join(report.get('accountSuffixCandidates') or []) or '-'}",
        f"Net liq: {report.get('netLiquidatingValue') or '-'}",
        f"Total cash: {report.get('totalCash') or '-'}",
        f"Refresh fallback: {report.get('statementRefreshFallback') or '-'}",
        f"Positions: {counts.get('positions', 0)}",
        f"Tracker matched: {counts.get('matchedPositions', 0)}",
        f"Unmatched: {counts.get('unmatchedPositions', 0)}",
        f"Concentration flags: {counts.get('concentrationFlags', 0)}",
        f"Earnings soon flags: {counts.get('earningsSoonFlags', 0)}",
        f"Fragile alignment flags: {counts.get('fragileAlignmentFlags', 0)}",
        "",
        "Next actions:",
    ]
    for action in report.get("nextActions") or []:
        lines.append(f"- {action}")
    lines.append("")
    lines.append("Positions:")
    for item in report.get("positions") or []:
        tracker = item.get("trackerContext") or {}
        lines.append(
            "- "
            + f"{item.get('symbol')} qty={item.get('qty')} mv={item.get('markValue')} "
            + f"w={item.get('weightPct') or '-'}% "
            + f"bucket={item.get('bucket')} "
            + f"priority={tracker.get('priority') or '-'} "
            + f"ready={tracker.get('readyScore') or '-'} "
            + f"align={tracker.get('alignmentLabel') or '-'} "
            + f"flags={', '.join(item.get('riskFlags') or []) or '-'}"
        )
    return "\n".join(lines).rstrip() + "\n"


def save_live_account_sync(report: dict[str, Any]) -> None:
    """Persist the live-account sync JSON and text artifacts."""
    ensure_dirs()
    LIVE_ACCOUNT_SYNC_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    LIVE_ACCOUNT_SYNC_TEXT_FILE.write_text(live_account_sync_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse the tiny CLI surface for build/status usage."""
    parser = argparse.ArgumentParser(description="Sync the approved live thinkorswim account into Inferno artifacts.")
    parser.add_argument("command", nargs="?", choices=("build", "status"), default="build")
    parser.add_argument(
        "--refresh-statement",
        action="store_true",
        help="Re-scrape the already-open Account Statement pane before building the sync.",
    )
    return parser.parse_args()


def main() -> int:
    """Build or print the live-account sync report."""
    args = parse_args()
    if args.command == "status" and LIVE_ACCOUNT_SYNC_TEXT_FILE.exists():
        print(LIVE_ACCOUNT_SYNC_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = build_live_account_sync(refresh_statement=args.refresh_statement)
    print(live_account_sync_text(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
