from __future__ import annotations

"""Recurring deposit plan for the Inferno desk.

This lane keeps operator-planned deposits separate from broker-confirmed cash
and realized trading profit. It is a forecast and audit aid only; it never
creates deployable cash, never changes broker authority, and never submits
orders.
"""

import argparse
import os
from datetime import date, datetime, timedelta
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


DEPOSIT_PLAN_STAGE = "deposit-plan-research-only"
DEPOSIT_PLAN_CONFIG_FILE = DATA_DIR / "operator_deposit_plan.json"
DEPOSIT_PLAN_FILE = DATA_DIR / "inferno_deposit_plan.json"
DEPOSIT_PLAN_TEXT_FILE = REPORTS_DIR / "deposit_plan_latest.txt"
LIVE_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_live_account_sync.json"
SCHWAB_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_schwab_account_sync.json"

DEFAULT_AMOUNT_DOLLARS = float(os.environ.get("INFERNO_DEPOSIT_AMOUNT", "250"))
DEFAULT_INTERVAL_DAYS = int(os.environ.get("INFERNO_DEPOSIT_INTERVAL_DAYS", "14"))
DEFAULT_HORIZON_DAYS = 365


def text(value: Any, default: str = "") -> str:
    """Return a compact string for display."""
    if value is None:
        return default
    rendered = str(value).strip()
    return rendered or default


def number(value: Any, default: float = 0.0) -> float:
    """Parse broker/report numbers without throwing on blanks or symbols."""
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = text(value).replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(cleaned)
    except ValueError:
        return default


def parse_date(value: str | None, *, default: date) -> date:
    """Parse an ISO date with a safe default."""
    if not value:
        return default
    return date.fromisoformat(value)


def load_plan_config(now: datetime | None = None) -> tuple[dict[str, Any], bool]:
    """Load the saved operator deposit plan, or return a conservative default."""
    current = now or local_now()
    payload = load_json_file(DEPOSIT_PLAN_CONFIG_FILE) or {}
    if payload:
        return payload, True
    first_date = os.environ.get("INFERNO_DEPOSIT_FIRST_DATE") or current.date().isoformat()
    return {
        "amountDollars": DEFAULT_AMOUNT_DOLLARS,
        "intervalDays": DEFAULT_INTERVAL_DAYS,
        "firstDepositDate": first_date,
        "source": "default-assumption",
    }, False


def save_plan_config(
    *,
    amount_dollars: float,
    interval_days: int,
    first_deposit_date: str,
    source: str = "operator-assumption",
) -> dict[str, Any]:
    """Persist the operator's recurring deposit assumption."""
    ensure_dirs()
    payload = {
        "updatedAt": local_now().isoformat(),
        "amountDollars": round(float(amount_dollars), 2),
        "intervalDays": int(interval_days),
        "firstDepositDate": first_deposit_date,
        "source": source,
    }
    atomic_write_json(DEPOSIT_PLAN_CONFIG_FILE, payload)
    return payload


def next_deposit_date(first_date: date, interval_days: int, today: date) -> date:
    """Return the next scheduled deposit date on or after today."""
    if today <= first_date:
        return first_date
    elapsed_days = (today - first_date).days
    cycles = elapsed_days // interval_days
    candidate = first_date + timedelta(days=cycles * interval_days)
    if candidate < today:
        candidate += timedelta(days=interval_days)
    return candidate


def upcoming_deposits(first_date: date, interval_days: int, today: date, *, count: int = 8) -> list[str]:
    """Return upcoming deposit dates as ISO strings."""
    next_date = next_deposit_date(first_date, interval_days, today)
    return [(next_date + timedelta(days=interval_days * index)).isoformat() for index in range(count)]


def deposits_in_horizon(first_date: date, interval_days: int, today: date, horizon_days: int) -> int:
    """Count scheduled deposits from today through the horizon date inclusive."""
    horizon = today + timedelta(days=horizon_days)
    current = next_deposit_date(first_date, interval_days, today)
    deposits = 0
    while current <= horizon:
        deposits += 1
        current += timedelta(days=interval_days)
    return deposits


def account_cash_snapshot() -> dict[str, Any]:
    """Summarize current broker cash without attributing its source."""
    live_sync = load_json_file(LIVE_ACCOUNT_SYNC_FILE) or {}
    schwab_sync = load_json_file(SCHWAB_ACCOUNT_SYNC_FILE) or {}
    cash = live_sync.get("totalCash")
    source = "live-account-sync"
    generated_at = live_sync.get("generatedAt")
    nlv = live_sync.get("netLiquidatingValue")
    if cash in (None, ""):
        cash = schwab_sync.get("totalCash")
        source = "schwab-account-sync"
        generated_at = schwab_sync.get("generatedAt")
        nlv = schwab_sync.get("netLiquidatingValue")
    return {
        "source": source,
        "generatedAt": generated_at,
        "cash": round(number(cash), 2),
        "netLiquidatingValue": round(number(nlv), 2),
        "cashAttribution": "unknown-without-transaction-ledger",
    }


def build_deposit_plan(now: datetime | None = None) -> dict[str, Any]:
    """Build and persist the recurring deposit forecast."""
    ensure_dirs()
    current = now or local_now()
    today = current.date()
    config, configured = load_plan_config(current)
    amount = number(config.get("amountDollars"), DEFAULT_AMOUNT_DOLLARS)
    interval_days = int(number(config.get("intervalDays"), DEFAULT_INTERVAL_DAYS))
    if interval_days <= 0:
        interval_days = DEFAULT_INTERVAL_DAYS
    first_date = parse_date(text(config.get("firstDepositDate")), default=today)
    next_date = next_deposit_date(first_date, interval_days, today)
    annual_deposit_count = 26 if interval_days == 14 else deposits_in_horizon(first_date, interval_days, today, DEFAULT_HORIZON_DAYS)
    annual_planned = round(amount * annual_deposit_count, 2)
    forecast_windows = {
        f"{days}Days": {
            "depositCount": deposits_in_horizon(first_date, interval_days, today, days),
            "grossDeposits": round(amount * deposits_in_horizon(first_date, interval_days, today, days), 2),
        }
        for days in (30, 90)
    }
    forecast_windows["planYear"] = {
        "depositCount": annual_deposit_count,
        "grossDeposits": annual_planned,
    }
    warnings = []
    if not configured:
        warnings.append("No saved operator deposit config was found; using default assumption values.")
    payload = {
        "generatedAt": current.isoformat(),
        "stage": DEPOSIT_PLAN_STAGE,
        "verdict": "configured" if configured else "default-assumption",
        "message": (
            f"${amount:,.2f} every {interval_days} days; planned deposits are forecast-only "
            "until broker cash confirms."
        ),
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "plan": {
            "amountDollars": round(amount, 2),
            "intervalDays": interval_days,
            "firstDepositDate": first_date.isoformat(),
            "source": text(config.get("source"), "operator-assumption"),
            "annualDepositCount": annual_deposit_count,
            "annualPlannedDollars": annual_planned,
            "monthlyEquivalentDollars": round(annual_planned / 12.0, 2),
        },
        "schedule": {
            "nextDepositDate": next_date.isoformat(),
            "daysUntilNextDeposit": (next_date - today).days,
            "upcomingDeposits": upcoming_deposits(first_date, interval_days, today),
        },
        "forecastWindows": forecast_windows,
        "brokerCashSnapshot": account_cash_snapshot(),
        "capitalTreatment": {
            "plannedDepositsAreDeployable": False,
            "deployableCashRequiresBrokerConfirmation": True,
            "realizedOptionsProfitSeparated": True,
            "cashIncreaseAttribution": "deposit/trading/transfer source remains unknown without transaction ledger",
        },
        "warnings": warnings,
        "nextActions": [
            "Keep planned deposits separate from realized options profit and paper/shadow P/L.",
            "After each deposit lands, rerun account sync and capital-check from broker-confirmed cash.",
            "Do not treat forecast deposits as deployable cash before Schwab cash confirms.",
        ],
        "citations": [
            "data/inferno_live_account_sync.json",
            "data/inferno_schwab_account_sync.json",
            "data/operator_deposit_plan.json",
        ],
    }
    save_deposit_plan(payload)
    return payload


def render_deposit_plan(payload: dict[str, Any]) -> str:
    """Render the deposit plan into a compact report."""
    plan = payload.get("plan") or {}
    schedule = payload.get("schedule") or {}
    broker = payload.get("brokerCashSnapshot") or {}
    forecast = payload.get("forecastWindows") or {}
    lines = [
        "Inferno Deposit Plan",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Message: {payload.get('message')}",
        "",
        "Recurring plan",
        f"- Amount: ${number(plan.get('amountDollars')):,.2f}",
        f"- Interval: every {int(number(plan.get('intervalDays')))} days",
        f"- First deposit date: {plan.get('firstDepositDate')}",
        f"- Next expected deposit: {schedule.get('nextDepositDate')} ({schedule.get('daysUntilNextDeposit')} day(s))",
        f"- Annual planned: ${number(plan.get('annualPlannedDollars')):,.2f}",
        f"- Monthly equivalent: ${number(plan.get('monthlyEquivalentDollars')):,.2f}",
        "",
        "Forecast deposits",
        f"- 30 days: {((forecast.get('30Days') or {}).get('depositCount', 0))} deposit(s) | ${number((forecast.get('30Days') or {}).get('grossDeposits')):,.2f}",
        f"- 90 days: {((forecast.get('90Days') or {}).get('depositCount', 0))} deposit(s) | ${number((forecast.get('90Days') or {}).get('grossDeposits')):,.2f}",
        f"- Plan year: {((forecast.get('planYear') or {}).get('depositCount', 0))} deposit(s) | ${number((forecast.get('planYear') or {}).get('grossDeposits')):,.2f}",
        "",
        "Broker cash snapshot",
        f"- Source: {broker.get('source')}",
        f"- Generated: {broker.get('generatedAt')}",
        f"- Cash: ${number(broker.get('cash')):,.2f}",
        f"- NLV: ${number(broker.get('netLiquidatingValue')):,.2f}",
        f"- Attribution: {broker.get('cashAttribution')}",
        "",
        "Capital treatment",
        "- Planned deposits are forecast-only.",
        "- Deployable cash requires broker-confirmed cash or explicit operator planning input.",
        "- Realized options profit remains separate until a transaction ledger is wired.",
        "",
        "Warnings",
    ]
    lines.extend(f"- {item}" for item in payload.get("warnings") or ["none"])
    lines.extend(["", "Next actions"])
    lines.extend(f"- {item}" for item in payload.get("nextActions") or [])
    return "\n".join(lines).rstrip() + "\n"


def save_deposit_plan(payload: dict[str, Any]) -> None:
    """Persist JSON and text copies of the deposit plan."""
    atomic_write_json(DEPOSIT_PLAN_FILE, payload)
    atomic_write_text(DEPOSIT_PLAN_TEXT_FILE, render_deposit_plan(payload))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Build or configure the Inferno recurring deposit plan.")
    parser.add_argument("action", nargs="?", choices=("run", "status", "configure"), default="run")
    parser.add_argument("--amount", type=float, default=DEFAULT_AMOUNT_DOLLARS)
    parser.add_argument("--interval-days", type=int, default=DEFAULT_INTERVAL_DAYS)
    parser.add_argument("--first-date", default=None)
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    if args.action == "configure":
        first_date = args.first_date or local_now().date().isoformat()
        save_plan_config(
            amount_dollars=args.amount,
            interval_days=args.interval_days,
            first_deposit_date=first_date,
        )
    payload = build_deposit_plan()
    print(render_deposit_plan(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
