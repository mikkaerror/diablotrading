from __future__ import annotations

"""Data trust and next-week readiness audit for the Inferno desk.

This auditor answers one practical question every morning: which numbers are
solid enough to use for preparation, which are only good for research, and
which still need broker-grade confirmation before any real execution step.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from inferno_config import BROKER_API_TARGET, ROOT, local_now
from inferno_doctor import in_current_service_cycle
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
EXECUTION_QUEUE_FILE = DATA_DIR / "inferno_execution_queue.json"
STRIKE_PLAN_FILE = DATA_DIR / "inferno_strike_plan.json"
MARKET_CONTEXT_AUDIT_FILE = DATA_DIR / "inferno_market_context_audit.json"
TOS_EXPORT_VERIFIER_FILE = DATA_DIR / "inferno_tos_export_verifier.json"
TOS_SESSION_PROBE_FILE = DATA_DIR / "inferno_tos_session_probe.json"
DATA_READINESS_AUDIT_FILE = DATA_DIR / "inferno_data_readiness_audit.json"
DATA_READINESS_AUDIT_TEXT_FILE = REPORTS_DIR / "data_readiness_audit_latest.txt"


def text(value: Any) -> str:
    """Normalize arbitrary values into trimmed text."""
    return str(value or "").strip()


def number(value: Any) -> float | None:
    """Return a numeric value when parsing succeeds, else None."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def metric_record(
    *,
    key: str,
    label: str,
    source: str,
    trust_tier: str,
    status: str,
    correct_use: str,
    detail: str,
    broker_confirmation_required: bool = False,
) -> dict[str, Any]:
    """Build one portable readiness record."""
    return {
        "key": key,
        "label": label,
        "source": source,
        "trustTier": trust_tier,
        "status": status,
        "correctUse": correct_use,
        "detail": detail,
        "brokerConfirmationRequired": broker_confirmation_required,
    }


def summarize_status(items: list[dict[str, Any]], trust_tier: str) -> tuple[int, int]:
    """Count healthy metrics inside one trust tier."""
    tier_items = [item for item in items if item["trustTier"] == trust_tier]
    healthy = [item for item in tier_items if item["status"] == "healthy"]
    return len(healthy), len(tier_items)


def build_audit() -> dict[str, Any]:
    """Construct the current data-readiness audit from live artifacts."""
    now = local_now()
    snapshot = load_json_file(SNAPSHOT_FILE) or {}
    execution_queue = load_json_file(EXECUTION_QUEUE_FILE) or {}
    strike_plan = load_json_file(STRIKE_PLAN_FILE) or {}
    market_context_audit = load_json_file(MARKET_CONTEXT_AUDIT_FILE) or {}
    export_verifier = load_json_file(TOS_EXPORT_VERIFIER_FILE) or {}
    session_probe = load_json_file(TOS_SESSION_PROBE_FILE) or {}

    rows = snapshot.get("rows") or []
    negative_earnings = [
        row
        for row in rows
        if isinstance(row, dict) and int(row.get("daysUntilEarnings") or 0) < 0
    ]

    snapshot_fresh = in_current_service_cycle(text(snapshot.get("generatedAt")), now=now)
    queue_fresh = in_current_service_cycle(text(execution_queue.get("generatedAt")), now=now)
    strike_fresh = in_current_service_cycle(text(strike_plan.get("generatedAt")), now=now)
    market_context_fresh = in_current_service_cycle(text(market_context_audit.get("generatedAt")), now=now)

    atr_rows = [
        row for row in rows
        if isinstance(row, dict)
        and number(row.get("atrPercent")) is not None
        and number(row.get("atrZScore")) is not None
        and number(row.get("atr20Day")) is not None
    ]
    atr_missing = [
        row.get("ticker")
        for row in rows
        if isinstance(row, dict)
        and (
            number(row.get("atrPercent")) is None
            or number(row.get("atrZScore")) is None
            or number(row.get("atr20Day")) is None
        )
    ]
    iv_rows = [
        row for row in rows
        if isinstance(row, dict)
        and row.get("ivRank") not in {None, "", "N/A"}
        and row.get("ivRankChange") not in {None, "", "N/A"}
    ]

    metrics: list[dict[str, Any]] = []

    earnings_ok = snapshot_fresh and bool(rows) and not negative_earnings
    metrics.append(
        metric_record(
            key="earnings_calendar",
            label="Next Earnings / Days Until Earnings",
            source="Google Sheet plus yfinance earnings-date refresh",
            trust_tier="daily-safe",
            status="healthy" if earnings_ok else "attention",
            correct_use="Catalyst timing, watchlist ordering, and next-week prep.",
            detail=(
                f"{len(rows)} rows checked with no negative earnings windows."
                if earnings_ok
                else f"snapshot fresh={snapshot_fresh} | negative rows={len(negative_earnings)}"
            ),
        )
    )

    atr_coverage = (len(atr_rows) / len(rows)) if rows else 0.0
    atr_ok = snapshot_fresh and bool(rows) and atr_coverage >= 0.98
    metrics.append(
        metric_record(
            key="atr_family",
            label="ATR / ATR% / ATR Z / 20-Day ATR",
            source="yfinance daily OHLCV history",
            trust_tier="daily-safe",
            status="healthy" if atr_ok else "attention",
            correct_use="Daily volatility framing, timing pressure, and structure sizing.",
            detail=(
                f"{len(atr_rows)}/{len(rows)} rows populated from daily history."
                + (f" Missing: {', '.join(atr_missing[:4])}" if atr_missing else "")
                if rows
                else "snapshot rows missing"
            ),
        )
    )

    market_context_ok = (
        market_context_fresh
        and int(market_context_audit.get("totalRows") or 0) > 0
        and int(market_context_audit.get("populatedRows") or 0) == int(market_context_audit.get("totalRows") or 0)
    )
    metrics.append(
        metric_record(
            key="market_context",
            label="RVOL / Trend / Support / Resistance",
            source="yfinance daily OHLCV history over a 6-month lookback",
            trust_tier="daily-safe",
            status="healthy" if market_context_ok else "attention",
            correct_use="Premarket bias confirmation and same-day structure planning.",
            detail=(
                f"{market_context_audit.get('populatedRows', 0)}/{market_context_audit.get('totalRows', 0)} rows confirmed | avg RVOL {market_context_audit.get('averageRvol')}"
                if market_context_audit
                else "market-context audit missing"
            ),
            broker_confirmation_required=True,
        )
    )

    iv_ok = snapshot_fresh and bool(iv_rows)
    metrics.append(
        metric_record(
            key="iv_rank_family",
            label="IV Rank / IV Rank Change",
            source="current yfinance option-chain IV mix plus realized-vol proxy",
            trust_tier="research-grade",
            status="conditional" if iv_ok else "attention",
            correct_use="Idea ranking only; do not treat this as broker-grade implied-vol truth.",
            detail=(
                f"{len(iv_rows)}/{len(rows)} rows populated. Current implementation is not a full historical IV-rank surface."
                if rows
                else "snapshot rows missing"
            ),
            broker_confirmation_required=True,
        )
    )

    strike_ready = queue_fresh and strike_fresh and int(strike_plan.get("count") or 0) > 0
    metrics.append(
        metric_record(
            key="option_chain_quotes",
            label="Option Chain Quotes / Liquidity",
            source="yfinance option chains",
            trust_tier="research-grade",
            status="conditional" if strike_ready else "attention",
            correct_use="Pre-open idea generation, spread sketching, and research queue building.",
            detail=(
                f"{strike_plan.get('count', 0)} strike plans built | liveTradingAllowed={strike_plan.get('liveTradingAllowed')}"
                if strike_plan
                else "strike plan missing"
            ),
            broker_confirmation_required=True,
        )
    )

    export_verdict = text(export_verifier.get("verdict")) or "unknown"
    session_summary = text(session_probe.get("summary")) or text(session_probe.get("message")) or "no session proof"
    paper_safe = export_verdict == "ready" and bool(session_probe.get("ok"))
    metrics.append(
        metric_record(
            key="paper_sandbox",
            label="thinkorswim paperMoney Evidence Loop",
            source="thinkorswim desktop export and paper fill ingest",
            trust_tier="sandbox-only",
            status="healthy" if paper_safe else "conditional",
            correct_use="Sandbox staging, paper fills, and evidence gathering.",
            detail=f"{export_verdict} | {session_summary}",
        )
    )

    metrics.append(
        metric_record(
            key="broker_execution",
            label="Broker Confirmation / Execution Authority",
            source=f"Manual broker review today, future target {BROKER_API_TARGET}",
            trust_tier="broker-grade-needed",
            status="blocked",
            correct_use="Pre-trade confirmation, quote timestamp checks, and any future live authority.",
            detail="Broker API read-only and preview lanes are not integrated yet; live authority stays blocked.",
            broker_confirmation_required=True,
        )
    )

    daily_safe_healthy, daily_safe_total = summarize_status(metrics, "daily-safe")
    research_healthy, research_total = summarize_status(metrics, "research-grade")
    sandbox_healthy, sandbox_total = summarize_status(metrics, "sandbox-only")
    blocked_metrics = [item["label"] for item in metrics if item["status"] == "blocked"]
    broker_needed = [item["label"] for item in metrics if item["brokerConfirmationRequired"]]

    daily_prep_ready = daily_safe_total > 0 and daily_safe_healthy == daily_safe_total
    research_ready = research_total > 0 and research_healthy >= 1
    next_week_verdict = "ready-for-next-week-prep" if daily_prep_ready else "needs-refresh"

    return {
        "generatedAt": now.isoformat(),
        "verdict": next_week_verdict,
        "dailyPrepReady": daily_prep_ready,
        "researchReady": research_ready,
        "brokerExecutionReady": False,
        "manualExecutionRequired": True,
        "summary": {
            "dailySafeHealthy": daily_safe_healthy,
            "dailySafeTotal": daily_safe_total,
            "researchHealthy": research_healthy,
            "researchTotal": research_total,
            "sandboxHealthy": sandbox_healthy,
            "sandboxTotal": sandbox_total,
            "blockedCount": len(blocked_metrics),
        },
        "blockedMetrics": blocked_metrics,
        "brokerConfirmationNeeded": broker_needed,
        "metrics": metrics,
        "operatingRule": (
            "Use daily-safe metrics for prep and ranking. Use research-grade metrics for idea generation only. "
            "Confirm strikes, liquidity, quote freshness, and any execution-critical values at the broker before trading."
        ),
    }


def audit_text(report: dict[str, Any]) -> str:
    """Render the readiness audit into a concise operator-facing report."""
    lines = [
        "Inferno Data Readiness Audit",
        f"Generated at: {text(report.get('generatedAt'))}",
        f"Verdict: {text(report.get('verdict'))}",
        "",
        "Readiness:",
        f"- Daily prep: {'ready' if report.get('dailyPrepReady') else 'needs refresh'}",
        f"- Research queue: {'ready' if report.get('researchReady') else 'needs refresh'}",
        f"- Broker execution: {'ready' if report.get('brokerExecutionReady') else 'blocked'}",
        "",
        "Metric trust map:",
    ]
    for metric in report.get("metrics") or []:
        lines.append(
            f"- {metric['label']}: {metric['trustTier']} | {metric['status']} | {metric['detail']}"
        )
    lines.extend(
        [
            "",
            "Operating rule:",
            report.get("operatingRule") or "",
        ]
    )
    return "\n".join(lines)


def save_audit(report: dict[str, Any]) -> None:
    """Persist JSON and text artifacts for doctor and operators."""
    ensure_dirs()
    DATA_READINESS_AUDIT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    DATA_READINESS_AUDIT_TEXT_FILE.write_text(audit_text(report), encoding="utf-8")


def run_audit() -> dict[str, Any]:
    """Build and persist the latest readiness audit."""
    report = build_audit()
    save_audit(report)
    return report


def main() -> int:
    """Run or print the latest data-readiness audit."""
    parser = argparse.ArgumentParser(description="Audit data trust levels and next-week readiness for the Inferno desk.")
    parser.add_argument("--show-latest", action="store_true", help="Print the latest saved audit instead of rebuilding it.")
    args = parser.parse_args()

    if args.show_latest and DATA_READINESS_AUDIT_FILE.exists():
        latest = load_json_file(DATA_READINESS_AUDIT_FILE) or {}
        print(audit_text(latest))
        return 0 if text(latest.get("verdict")) == "ready-for-next-week-prep" else 1

    report = run_audit()
    print(audit_text(report))
    return 0 if text(report.get("verdict")) == "ready-for-next-week-prep" else 1


if __name__ == "__main__":
    raise SystemExit(main())
