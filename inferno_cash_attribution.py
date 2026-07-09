from __future__ import annotations

"""Cash attribution ledger for the Inferno desk.

This lane reconciles broker-confirmed cash, the recurring deposit forecast, and
cash history without pretending to know transaction-level P/L. It is
research-only: it never creates deployable cash, never infers realized options
profit from balance changes, and never changes broker authority.
"""

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


CASH_ATTRIBUTION_STAGE = "cash-attribution-research-only"
CASH_ATTRIBUTION_FILE = DATA_DIR / "inferno_cash_attribution.json"
CASH_ATTRIBUTION_TEXT_FILE = REPORTS_DIR / "cash_attribution_latest.txt"
LIVE_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_live_account_sync.json"
SCHWAB_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_schwab_account_sync.json"
DEPOSIT_PLAN_FILE = DATA_DIR / "inferno_deposit_plan.json"
NLV_HISTORY_FILE = DATA_DIR / "nlv_history.csv"
SCHWAB_TRANSACTION_LEDGER_FILE = DATA_DIR / "schwab_transactions.csv"
OPERATOR_CASH_EVENTS_FILE = DATA_DIR / "operator_cash_events.csv"
DEFAULT_DEPOSIT_MATCH_DAYS = 3


def text(value: Any, default: str = "") -> str:
    """Return a compact string for display."""
    if value is None:
        return default
    rendered = str(value).strip()
    return rendered or default


def number(value: Any, default: float | None = 0.0) -> float | None:
    """Parse broker/report numbers without throwing on blanks or symbols."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = text(value).replace("$", "").replace(",", "").replace("%", "")
    if not cleaned:
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default


def money(value: Any) -> str:
    """Render optional money values."""
    parsed = number(value, None)
    if parsed is None:
        return "-"
    prefix = "-$" if parsed < 0 else "$"
    return f"{prefix}{abs(parsed):,.2f}"


def parse_dt(value: Any) -> datetime | None:
    """Parse common ISO timestamps."""
    raw = text(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_day(value: Any) -> date | None:
    """Parse an ISO date or timestamp into a date."""
    raw = text(value)
    if not raw:
        return None
    parsed_dt = parse_dt(raw)
    if parsed_dt is not None:
        return parsed_dt.date()
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def schwab_account_cash_available(payload: dict[str, Any]) -> bool:
    """Return whether Schwab has usable read-only cash/account truth."""
    return (
        text(payload.get("verdict")).lower() == "healthy"
        and bool(payload.get("brokerReadOnly"))
        and (
            payload.get("totalCash") not in (None, "")
            or payload.get("netLiquidatingValue") not in (None, "")
        )
    )


def broker_cash_payload(
    live_sync: dict[str, Any],
    schwab_sync: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Choose the current broker-cash source using Schwab before stale TOS statements."""
    if text(live_sync.get("accountDataSource")) == "schwab-account-api":
        return "live-account-sync", live_sync
    if schwab_account_cash_available(schwab_sync):
        return "schwab-account-sync", schwab_sync
    if live_sync.get("totalCash") not in (None, ""):
        return "live-account-sync", live_sync
    if schwab_sync:
        return "schwab-account-sync", schwab_sync
    return "live-account-sync", live_sync


def broker_cash_snapshot() -> dict[str, Any]:
    """Return the latest approved broker cash snapshot."""
    live_sync = load_json_file(LIVE_ACCOUNT_SYNC_FILE) or {}
    schwab_sync = load_json_file(SCHWAB_ACCOUNT_SYNC_FILE) or {}
    source, payload = broker_cash_payload(live_sync, schwab_sync)
    account_data_source = payload.get("accountDataSource")
    if not account_data_source and source == "schwab-account-sync":
        account_data_source = "schwab-account-api"
    return {
        "source": source,
        "generatedAt": payload.get("generatedAt"),
        "ok": bool(payload.get("ok")),
        "verdict": payload.get("verdict"),
        "accountDataSource": account_data_source or source,
        "matchedSuffix": payload.get("matchedSuffix"),
        "cash": round(float(number(payload.get("totalCash"), 0.0) or 0.0), 2),
        "netLiquidatingValue": round(float(number(payload.get("netLiquidatingValue"), 0.0) or 0.0), 2),
    }


def load_cash_history(path: Path | None = None) -> list[dict[str, Any]]:
    """Load cash rows from the append-only NLV history."""
    path = path or NLV_HISTORY_FILE
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            for raw in csv.DictReader(handle):
                cash = number(raw.get("cash"), None)
                nlv = number(raw.get("nlv"), None)
                if cash is None and nlv is None:
                    continue
                rows.append(
                    {
                        "source": "nlv_history",
                        "timestamp": text(raw.get("timestamp")),
                        "date": text(raw.get("date")),
                        "cash": round(cash, 2) if cash is not None else None,
                        "netLiquidatingValue": round(nlv, 2) if nlv is not None else None,
                    }
                )
    except OSError:
        return []
    return sorted(rows, key=history_sort_key)


def history_sort_key(row: dict[str, Any]) -> tuple[int, datetime, str, str]:
    """Return a stable chronological key for history rows."""
    parsed = parse_dt(row.get("timestamp"))
    if parsed is not None:
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return (0, parsed, text(row.get("date")), text(row.get("timestamp")))
    parsed_day = parse_day(row.get("date"))
    if parsed_day is not None:
        return (1, datetime.combine(parsed_day, datetime.min.time()), text(row.get("date")), text(row.get("timestamp")))
    return (2, datetime.min, text(row.get("date")), text(row.get("timestamp")))


def append_current_snapshot(history: list[dict[str, Any]], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Append the current broker snapshot as the latest comparable row."""
    if snapshot.get("cash") is None:
        return history
    row = {
        "source": snapshot.get("source") or "broker-snapshot",
        "timestamp": snapshot.get("generatedAt"),
        "date": (parse_day(snapshot.get("generatedAt")) or local_now().date()).isoformat(),
        "cash": round(float(number(snapshot.get("cash"), 0.0) or 0.0), 2),
        "netLiquidatingValue": round(float(number(snapshot.get("netLiquidatingValue"), 0.0) or 0.0), 2),
    }
    combined = list(history)
    if not combined or any(
        text(row.get(key)) != text(combined[-1].get(key))
        for key in ("timestamp", "cash", "netLiquidatingValue")
    ):
        combined.append(row)
    return sorted(combined, key=history_sort_key)


def cash_changes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return non-zero cash changes between valid cash snapshots."""
    changes: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for row in rows:
        if row.get("cash") is None:
            continue
        if previous is not None:
            delta = round(float(row["cash"]) - float(previous["cash"]), 2)
            if delta:
                changes.append(
                    {
                        "from": previous,
                        "to": row,
                        "deltaCash": delta,
                        "direction": "increase" if delta > 0 else "decrease",
                    }
                )
        previous = row
    return changes


def is_near_planned_deposit(change_date: date, plan: dict[str, Any]) -> dict[str, Any]:
    """Check whether a date is close to the configured recurring deposit schedule."""
    plan_body = plan.get("plan") or {}
    first = parse_day(plan_body.get("firstDepositDate"))
    interval = int(number(plan_body.get("intervalDays"), 0) or 0)
    if first is None or interval <= 0:
        return {"matches": False}
    cycles = round((change_date - first).days / interval)
    scheduled = first + timedelta(days=cycles * interval)
    days_from_schedule = abs((change_date - scheduled).days)
    return {
        "matches": days_from_schedule <= DEFAULT_DEPOSIT_MATCH_DAYS,
        "nearestScheduledDeposit": scheduled.isoformat(),
        "daysFromSchedule": days_from_schedule,
    }


def classify_cash_change(change: dict[str, Any] | None, deposit_plan: dict[str, Any]) -> dict[str, Any]:
    """Classify a cash movement without inferring trading profit."""
    if not change:
        return {
            "classification": "no-cash-change-observed",
            "confidence": "none",
            "reason": "No non-zero broker cash movement is visible in the cash history.",
            "knownCashSource": False,
        }
    delta = float(change.get("deltaCash") or 0.0)
    plan_body = deposit_plan.get("plan") or {}
    planned_amount = float(number(plan_body.get("amountDollars"), 0.0) or 0.0)
    change_day = parse_day((change.get("to") or {}).get("date") or (change.get("to") or {}).get("timestamp"))
    amount_tolerance = max(5.0, planned_amount * 0.05) if planned_amount > 0 else 0.0
    amount_matches = delta > 0 and planned_amount > 0 and abs(delta - planned_amount) <= amount_tolerance
    schedule_match = is_near_planned_deposit(change_day, deposit_plan) if change_day else {"matches": False}
    if amount_matches and schedule_match.get("matches"):
        return {
            "classification": "likely-planned-deposit-confirmed-in-broker-cash",
            "confidence": "medium",
            "reason": "Cash increased by approximately the planned deposit amount near the recurring deposit schedule.",
            "knownCashSource": False,
            "nearestScheduledDeposit": schedule_match.get("nearestScheduledDeposit"),
            "daysFromSchedule": schedule_match.get("daysFromSchedule"),
        }
    if delta > 0:
        return {
            "classification": "cash-increase-unattributed-without-transaction-ledger",
            "confidence": "none",
            "reason": "Broker cash increased, but no transaction ledger proves whether it was deposit, sale proceeds, transfer, or trading P/L.",
            "knownCashSource": False,
        }
    return {
        "classification": "cash-decrease-unattributed-without-transaction-ledger",
        "confidence": "none",
        "reason": "Broker cash decreased, but no transaction ledger identifies withdrawal, buy, fee, transfer, or trading activity.",
        "knownCashSource": False,
    }


def source_coverage() -> dict[str, Any]:
    """Describe which cash attribution inputs are wired."""
    return {
        "brokerTransactionLedgerPresent": SCHWAB_TRANSACTION_LEDGER_FILE.exists(),
        "brokerTransactionLedgerPath": str(SCHWAB_TRANSACTION_LEDGER_FILE),
        "operatorCashEventsPresent": OPERATOR_CASH_EVENTS_FILE.exists(),
        "operatorCashEventsPath": str(OPERATOR_CASH_EVENTS_FILE),
        "nlvHistoryPresent": NLV_HISTORY_FILE.exists(),
        "nlvHistoryPath": str(NLV_HISTORY_FILE),
    }


def build_cash_attribution(now: datetime | None = None) -> dict[str, Any]:
    """Build and persist the cash attribution ledger."""
    ensure_dirs()
    current = now or local_now()
    deposit_plan = load_json_file(DEPOSIT_PLAN_FILE) or {}
    broker = broker_cash_snapshot()
    history = append_current_snapshot(load_cash_history(), broker)
    valid_cash_rows = [row for row in history if row.get("cash") is not None]
    changes = cash_changes(history)
    latest_change = changes[-1] if changes else None
    latest_classification = classify_cash_change(latest_change, deposit_plan)
    coverage = source_coverage()
    transaction_ledger_present = bool(coverage.get("brokerTransactionLedgerPresent"))
    realized_status = "requires-broker-transaction-ledger"
    warnings: list[str] = []
    if not transaction_ledger_present:
        warnings.append("No broker transaction ledger is wired; realized options profit remains unknown.")
    if not valid_cash_rows:
        warnings.append("No valid cash rows were found in broker cash history.")

    payload = {
        "generatedAt": current.isoformat(),
        "stage": CASH_ATTRIBUTION_STAGE,
        "verdict": "attribution-incomplete" if not transaction_ledger_present else "transaction-ledger-present-review-required",
        "message": "Broker cash is reconciled, but cash source attribution requires transaction history.",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "brokerCash": broker,
        "plannedDeposit": {
            "verdict": deposit_plan.get("verdict"),
            "amountDollars": (deposit_plan.get("plan") or {}).get("amountDollars"),
            "intervalDays": (deposit_plan.get("plan") or {}).get("intervalDays"),
            "nextDepositDate": (deposit_plan.get("schedule") or {}).get("nextDepositDate"),
            "daysUntilNextDeposit": (deposit_plan.get("schedule") or {}).get("daysUntilNextDeposit"),
            "forecast30Days": ((deposit_plan.get("forecastWindows") or {}).get("30Days") or {}).get("grossDeposits"),
            "plannedDepositsAreDeployable": False,
        },
        "history": {
            "rowCount": len(history),
            "validCashRows": len(valid_cash_rows),
            "changeCount": len(changes),
            "latestCashRow": valid_cash_rows[-1] if valid_cash_rows else None,
            "latestDistinctCashChange": latest_change,
        },
        "latestCashChange": latest_change,
        "latestCashClassification": latest_classification,
        "realizedOptionsProfit": {
            "status": realized_status,
            "known": False,
            "closedLiveOptionPnlDollars": None,
            "sweepableOptionsProfitDollars": None,
            "neverInferFromCashChange": True,
        },
        "capitalTreatment": {
            "brokerConfirmedCashDollars": broker.get("cash"),
            "plannedDepositsAreDeployableBeforeBrokerConfirmation": False,
            "realizedOptionsProfitIsKnown": False,
            "cashChangesCreateLiveAuthority": False,
            "deployableCashStillRequiresCapitalCheck": True,
        },
        "sourceCoverage": coverage,
        "warnings": warnings,
        "nextActions": [
            "Wire Schwab transaction history or reviewed broker exports before labeling any cash movement as realized options profit.",
            "After a deposit lands, rerun account sync, cash-ledger, and capital-check from broker-confirmed cash.",
            "Keep planned deposits, broker cash, realized options P/L, and paper/shadow P/L in separate buckets.",
        ],
        "citations": [
            "data/inferno_live_account_sync.json",
            "data/inferno_schwab_account_sync.json",
            "data/inferno_deposit_plan.json",
            "data/nlv_history.csv",
        ],
    }
    save_cash_attribution(payload)
    return payload


def render_cash_attribution(payload: dict[str, Any]) -> str:
    """Render the cash attribution ledger into a compact report."""
    broker = payload.get("brokerCash") or {}
    planned = payload.get("plannedDeposit") or {}
    history = payload.get("history") or {}
    latest_change = payload.get("latestCashChange") or {}
    latest_class = payload.get("latestCashClassification") or {}
    realized = payload.get("realizedOptionsProfit") or {}
    capital = payload.get("capitalTreatment") or {}
    coverage = payload.get("sourceCoverage") or {}
    lines = [
        "Inferno Cash Attribution",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Message: {payload.get('message')}",
        "",
        "Broker cash",
        f"- Source: {broker.get('source')}",
        f"- Generated: {broker.get('generatedAt')}",
        f"- Cash: {money(broker.get('cash'))}",
        f"- NLV: {money(broker.get('netLiquidatingValue'))}",
        f"- Matched suffix: {broker.get('matchedSuffix') or '-'}",
        "",
        "Planned deposits",
        f"- Plan: {money(planned.get('amountDollars'))} every {planned.get('intervalDays') or '-'} day(s)",
        f"- Next expected: {planned.get('nextDepositDate') or '-'} ({planned.get('daysUntilNextDeposit')} day(s))",
        f"- 30-day forecast: {money(planned.get('forecast30Days'))}",
        "- Planned deposits are not deployable before broker cash confirms.",
        "",
        "Latest cash movement",
        f"- Change count: {history.get('changeCount', 0)}",
        f"- Delta: {money(latest_change.get('deltaCash'))}",
        f"- Direction: {latest_change.get('direction') or '-'}",
        f"- Classification: {latest_class.get('classification')}",
        f"- Confidence: {latest_class.get('confidence')}",
        f"- Reason: {latest_class.get('reason')}",
        "",
        "Realized options profit",
        f"- Status: {realized.get('status')}",
        f"- Closed live option P/L: {money(realized.get('closedLiveOptionPnlDollars'))}",
        f"- Sweepable options profit: {money(realized.get('sweepableOptionsProfitDollars'))}",
        "- Never infer realized options profit from cash changes, deposits, paper P/L, or NLV movement.",
        "",
        "Capital treatment",
        f"- Broker-confirmed cash: {money(capital.get('brokerConfirmedCashDollars'))}",
        f"- Realized options profit known: {capital.get('realizedOptionsProfitIsKnown')}",
        f"- Cash changes create live authority: {capital.get('cashChangesCreateLiveAuthority')}",
        f"- Deployable cash still requires capital-check: {capital.get('deployableCashStillRequiresCapitalCheck')}",
        "",
        "Source coverage",
        f"- Broker transaction ledger present: {coverage.get('brokerTransactionLedgerPresent')}",
        f"- Operator cash events present: {coverage.get('operatorCashEventsPresent')}",
        f"- NLV history present: {coverage.get('nlvHistoryPresent')}",
        "",
        "Warnings",
    ]
    lines.extend(f"- {item}" for item in payload.get("warnings") or ["none"])
    lines.extend(["", "Next actions"])
    lines.extend(f"- {item}" for item in payload.get("nextActions") or [])
    return "\n".join(lines).rstrip() + "\n"


def save_cash_attribution(payload: dict[str, Any]) -> None:
    """Persist JSON and text copies of the cash attribution report."""
    atomic_write_json(CASH_ATTRIBUTION_FILE, payload)
    atomic_write_text(CASH_ATTRIBUTION_TEXT_FILE, render_cash_attribution(payload))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Build the Inferno cash attribution ledger.")
    parser.add_argument("action", nargs="?", choices=("run", "status"), default="run")
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    parse_args()
    payload = build_cash_attribution()
    print(render_cash_attribution(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
