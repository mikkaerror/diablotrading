from __future__ import annotations

"""Layer account truth, recurring deposits, and deterministic growth math.

This is deliberately a forecasting surface, not an allocation engine.  It
combines broker-read-only account value with the operator's deposit plan so the
desk can quantify how much of a projected balance comes from deposits versus a
range of explicitly labelled return assumptions.  It cannot make deposits
deployable, select a security, change a risk limit, or submit an order.
"""

import argparse
import csv
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


GROWTH_STACK_STAGE = "growth-stack-research-only"
GROWTH_STACK_FILE = DATA_DIR / "inferno_growth_stack.json"
GROWTH_STACK_TEXT_FILE = REPORTS_DIR / "growth_stack_latest.txt"
DEPOSIT_PLAN_FILE = DATA_DIR / "inferno_deposit_plan.json"
LIVE_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_live_account_sync.json"
SCHWAB_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_schwab_account_sync.json"
CASH_ATTRIBUTION_FILE = DATA_DIR / "inferno_cash_attribution.json"
NLV_HISTORY_FILE = DATA_DIR / "nlv_history.csv"

# These are mechanical scenarios for comparison, not return targets or advice.
ANNUAL_RETURN_SCENARIOS = (0.00, 0.04, 0.08)
MILESTONES = (1_000.0, 5_000.0, 10_000.0, 25_000.0)
FORECAST_DAYS = 365
MILESTONE_SEARCH_DAYS = 365 * 25
OBSERVED_NLV_WINDOWS_DAYS = (1, 7, 30)


def number(value: Any, default: float = 0.0) -> float:
    """Coerce an artifact value into a finite displayable number."""
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value or "").replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return default


def parse_date(value: Any) -> date | None:
    """Parse an ISO calendar date without inventing a deposit date."""
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def optional_number(value: Any) -> float | None:
    """Parse a historical number while preserving a missing value as missing."""
    if value is None:
        return None
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def load_nlv_history(path: Path | None = None) -> list[dict[str, Any]]:
    """Read valid NLV snapshots without changing the append-only history."""
    history_path = path or NLV_HISTORY_FILE
    if not history_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with history_path.open(newline="", encoding="utf-8") as handle:
            for raw in csv.DictReader(handle):
                nlv = optional_number(raw.get("nlv"))
                if nlv is None:
                    continue
                rows.append(
                    {
                        "source": "nlv-history",
                        "timestamp": raw.get("timestamp"),
                        "date": raw.get("date"),
                        "netLiquidatingValue": round(nlv, 2),
                    }
                )
    except OSError:
        return []
    return sorted(rows, key=lambda row: (str(row.get("date") or ""), str(row.get("timestamp") or "")))


def account_snapshot(live_account: dict[str, Any], schwab_account: dict[str, Any]) -> dict[str, Any]:
    """Prefer live Schwab-derived sync, with a direct Schwab fallback."""
    live_nlv = number(live_account.get("netLiquidatingValue"), -1.0)
    if live_nlv >= 0:
        return {
            "netLiquidatingValue": round(live_nlv, 2),
            "source": str(live_account.get("accountDataSource") or "live-account-sync"),
            "generatedAt": live_account.get("generatedAt"),
        }
    return {
        "netLiquidatingValue": round(max(0.0, number(schwab_account.get("netLiquidatingValue"))), 2),
        "source": "schwab-account-sync",
        "generatedAt": schwab_account.get("generatedAt"),
    }


def history_row_day(row: dict[str, Any]) -> date | None:
    """Return the recorded local day, with a timestamp fallback for old rows."""
    return parse_date(row.get("date")) or parse_date(str(row.get("timestamp") or "")[:10])


def observed_nlv_windows(
    history: list[dict[str, Any]],
    *,
    current_nlv: float,
    today: date,
) -> list[dict[str, Any]]:
    """Compare current NLV to the nearest available historical window baseline.

    These are account-value movements, not investment-return calculations.
    The nearest snapshot on or before each cutoff makes sparse daily history
    explicit rather than pretending a missing day is a zero change.
    """
    dated_rows = [
        (row, row_day)
        for row in history
        if (row_day := history_row_day(row)) is not None and row_day <= today
    ]
    dated_rows.sort(key=lambda pair: (pair[1], str(pair[0].get("timestamp") or "")))
    layers: list[dict[str, Any]] = []
    for window_days in OBSERVED_NLV_WINDOWS_DAYS:
        cutoff = today - timedelta(days=window_days)
        eligible = [(row, row_day) for row, row_day in dated_rows if row_day <= cutoff]
        if current_nlv <= 0 or not eligible:
            layers.append(
                {
                    "windowDays": window_days,
                    "verdict": "awaiting-window-baseline",
                    "baseline": None,
                    "actualSpanDays": None,
                    "observedNlvDeltaDollars": None,
                    "observedNlvChangePct": None,
                    "returnAttribution": "withheld",
                    "safeForPerformanceClaim": False,
                    "availableToExecution": False,
                }
            )
            continue
        baseline, baseline_day = eligible[-1]
        baseline_nlv = number(baseline.get("netLiquidatingValue"))
        if baseline_nlv <= 0:
            layers.append(
                {
                    "windowDays": window_days,
                    "verdict": "missing-comparable-account-value",
                    "baseline": baseline,
                    "actualSpanDays": max(0, (today - baseline_day).days),
                    "observedNlvDeltaDollars": None,
                    "observedNlvChangePct": None,
                    "returnAttribution": "withheld",
                    "safeForPerformanceClaim": False,
                    "availableToExecution": False,
                }
            )
            continue
        delta = round(current_nlv - baseline_nlv, 2)
        layers.append(
            {
                "windowDays": window_days,
                "verdict": "observed-nlv-change-unattributed",
                "baseline": baseline,
                "actualSpanDays": max(0, (today - baseline_day).days),
                "observedNlvDeltaDollars": delta,
                "observedNlvChangePct": round(delta / baseline_nlv * 100.0, 2),
                "returnAttribution": "withheld",
                "safeForPerformanceClaim": False,
                "availableToExecution": False,
            }
        )
    return layers


def observed_progress(
    history: list[dict[str, Any]],
    account: dict[str, Any],
    cash_attribution: dict[str, Any],
    *,
    today: date,
) -> dict[str, Any]:
    """Show observed NLV movement without relabelling it as investment return.

    NLV changes may contain deposits, withdrawals, purchases, sales, and fees.
    Until the transaction ledger proves those flows, this is an account trend
    only. It is deliberately unavailable to any sizing or authority lane.
    """
    current_nlv = number(account.get("netLiquidatingValue"))
    short_horizon_windows = observed_nlv_windows(
        history, current_nlv=current_nlv, today=today
    )
    if not history:
        return {
            "verdict": "awaiting-history",
            "historyRows": 0,
            "observedNlvDeltaDollars": None,
            "observedNlvChangePct": None,
            "shortHorizonWindows": short_horizon_windows,
            "returnAttribution": "withheld",
            "safeForPerformanceClaim": False,
            "reason": "No valid historical NLV baseline is available yet.",
        }

    baseline = history[0]
    baseline_nlv = number(baseline.get("netLiquidatingValue"))
    baseline_day = parse_date(baseline.get("date"))
    elapsed_days = max(0, (today - baseline_day).days) if baseline_day else None
    if baseline_nlv <= 0 or current_nlv <= 0:
        return {
            "verdict": "missing-comparable-account-value",
            "historyRows": len(history),
            "baseline": baseline,
            "currentNlv": round(current_nlv, 2),
            "elapsedDays": elapsed_days,
            "observedNlvDeltaDollars": None,
            "observedNlvChangePct": None,
            "shortHorizonWindows": short_horizon_windows,
            "returnAttribution": "withheld",
            "safeForPerformanceClaim": False,
            "reason": "A positive historical baseline and current broker NLV are required for an observed change.",
        }

    delta = round(current_nlv - baseline_nlv, 2)
    change_pct = round(delta / baseline_nlv * 100.0, 2)
    cash_verdict = cash_attribution.get("verdict") or "missing"
    return {
        "verdict": "observed-nlv-change-unattributed",
        "historyRows": len(history),
        "baseline": baseline,
        "currentNlv": round(current_nlv, 2),
        "elapsedDays": elapsed_days,
        "observedNlvDeltaDollars": delta,
        "observedNlvChangePct": change_pct,
        "shortHorizonWindows": short_horizon_windows,
        "cashAttributionVerdict": cash_verdict,
        "returnAttribution": "withheld",
        "safeForPerformanceClaim": False,
        "reason": (
            "Observed NLV movement includes unknown cash-flow and transaction effects; "
            "it is not reported as market return or trading P/L."
        ),
    }


def scheduled_deposit_dates(first_deposit: date, interval_days: int, *, start: date, days: int) -> set[date]:
    """Return scheduled dates in a bounded horizon, including a deposit due today."""
    if interval_days <= 0 or days < 0:
        return set()
    end = start + timedelta(days=days)
    current = first_deposit
    while current < start:
        current += timedelta(days=interval_days)
    dates: set[date] = set()
    while current <= end:
        dates.add(current)
        current += timedelta(days=interval_days)
    return dates


def simulate_balance(
    *,
    starting_balance: float,
    annual_return: float,
    deposit_amount: float,
    deposit_dates: set[date],
    start: date,
    days: int,
    target: float | None = None,
) -> dict[str, Any]:
    """Compound daily with scheduled end-of-day deposits under one assumption."""
    balance = max(0.0, starting_balance)
    contributions = 0.0
    daily_rate = (1.0 + annual_return) ** (1.0 / 365.0) - 1.0
    reached_on = start if target is not None and balance >= target else None
    for offset in range(days + 1):
        current = start + timedelta(days=offset)
        if offset:
            balance *= 1.0 + daily_rate
        if current in deposit_dates:
            balance += deposit_amount
            contributions += deposit_amount
        if reached_on is None and target is not None and balance >= target:
            reached_on = current
    return {
        "endingBalance": round(balance, 2),
        "grossContributions": round(contributions, 2),
        "marketGrowthDollars": round(balance - max(0.0, starting_balance) - contributions, 2),
        "reachedOn": reached_on.isoformat() if reached_on else None,
    }


def source_inputs() -> dict[str, Any]:
    """Load only the canonical read-only artifacts used by this forecast."""
    return {
        "depositPlan": load_json_file(DEPOSIT_PLAN_FILE) or {},
        "liveAccount": load_json_file(LIVE_ACCOUNT_SYNC_FILE) or {},
        "schwabAccount": load_json_file(SCHWAB_ACCOUNT_SYNC_FILE) or {},
        "cashAttribution": load_json_file(CASH_ATTRIBUTION_FILE) or {},
        "nlvHistory": load_nlv_history(),
    }


def cash_attribution_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Expose cash provenance without inventing realized P/L or deposits."""
    latest = payload.get("latestCashChange") or {}
    classification = payload.get("latestCashClassification") or {}
    realized = payload.get("realizedOptionsProfit") or {}
    broker_cash = payload.get("brokerCash") or {}
    return {
        "verdict": payload.get("verdict") or "missing",
        "generatedAt": payload.get("generatedAt"),
        "brokerCash": number(broker_cash.get("cash")),
        "latestDeltaCash": number(latest.get("deltaCash")),
        "latestClassification": classification.get("classification") or "unknown",
        "realizedOptionsProfitKnown": bool(realized.get("known")),
        "plannedDepositsAreDeployable": False,
    }


def build_growth_stack(
    inputs: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a safe, source-labelled contribution-and-compounding forecast."""
    ensure_dirs()
    supplied = inputs or source_inputs()
    current = now or local_now()
    today = current.date()
    plan_artifact = supplied.get("depositPlan") or {}
    cash_attribution_artifact = supplied.get("cashAttribution") or {}
    plan = plan_artifact.get("plan") or {}
    schedule = plan_artifact.get("schedule") or {}
    account = account_snapshot(
        supplied.get("liveAccount") or {}, supplied.get("schwabAccount") or {}
    )
    history = supplied.get("nlvHistory") or []
    progress = observed_progress(history, account, cash_attribution_artifact, today=today)
    starting_balance = number(account.get("netLiquidatingValue"))
    deposit_amount = max(0.0, number(plan.get("amountDollars")))
    interval_days = int(number(plan.get("intervalDays")))
    next_deposit = parse_date(schedule.get("nextDepositDate"))

    warnings: list[str] = []
    if not plan_artifact:
        warnings.append("Deposit-plan artifact is missing; no contribution forecast was computed.")
    if plan_artifact.get("verdict") == "default-assumption":
        warnings.append("Deposit plan is a default assumption, not a saved operator commitment.")
    if starting_balance <= 0:
        warnings.append("No positive broker NLV was available; projections start at $0.00.")
    if deposit_amount <= 0 or interval_days <= 0 or next_deposit is None:
        warnings.append("Deposit amount, interval, or next scheduled date is missing; no deposit schedule was assumed.")
    if not cash_attribution_artifact:
        warnings.append("Cash-attribution artifact is missing; cash source and realized options P/L remain unknown.")

    deposit_dates = (
        scheduled_deposit_dates(next_deposit, interval_days, start=today, days=MILESTONE_SEARCH_DAYS)
        if deposit_amount > 0 and interval_days > 0 and next_deposit is not None
        else set()
    )
    projections: list[dict[str, Any]] = []
    milestones: list[dict[str, Any]] = []
    for annual_return in ANNUAL_RETURN_SCENARIOS:
        projection = simulate_balance(
            starting_balance=starting_balance,
            annual_return=annual_return,
            deposit_amount=deposit_amount,
            deposit_dates=deposit_dates,
            start=today,
            days=FORECAST_DAYS,
        )
        projection["annualReturnPct"] = round(annual_return * 100.0, 2)
        projection["label"] = f"{annual_return * 100:.0f}% annual illustrative return"
        projections.append(projection)
    for target in MILESTONES:
        row: dict[str, Any] = {"targetBalance": target, "scenarios": []}
        for annual_return in ANNUAL_RETURN_SCENARIOS:
            forecast = simulate_balance(
                starting_balance=starting_balance,
                annual_return=annual_return,
                deposit_amount=deposit_amount,
                deposit_dates=deposit_dates,
                start=today,
                days=MILESTONE_SEARCH_DAYS,
                target=target,
            )
            reached_on = parse_date(forecast.get("reachedOn"))
            row["scenarios"].append(
                {
                    "annualReturnPct": round(annual_return * 100.0, 2),
                    "reachedOn": forecast.get("reachedOn"),
                    "monthsFromNow": (
                        round((reached_on - today).days / 30.44, 1) if reached_on else None
                    ),
                }
            )
        milestones.append(row)

    flat = projections[0]
    illustrative = projections[-1]
    annual_planned = deposit_amount * len(
        scheduled_deposit_dates(next_deposit, interval_days, start=today, days=FORECAST_DAYS)
    ) if deposit_dates else 0.0
    base_eight_percent = starting_balance * ANNUAL_RETURN_SCENARIOS[-1]
    contribution_to_starting_return = (
        round(annual_planned / base_eight_percent, 2) if base_eight_percent > 0 else None
    )
    if not plan_artifact:
        verdict = "missing-deposit-plan"
    elif deposit_amount <= 0 or interval_days <= 0 or next_deposit is None:
        verdict = "incomplete-deposit-plan"
    elif starting_balance <= 0:
        verdict = "missing-account-balance"
    elif plan_artifact.get("verdict") == "default-assumption":
        verdict = "assumption-review"
    else:
        verdict = "forecast-ready"
    payload = {
        "generatedAt": current.isoformat(),
        "stage": GROWTH_STACK_STAGE,
        "verdict": verdict,
        "message": "Forecast-only layering of broker NLV, scheduled contributions, and explicit return assumptions.",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "account": account,
        "cashAttribution": cash_attribution_snapshot(cash_attribution_artifact),
        "observedProgress": progress,
        "depositPlan": {
            "amountDollars": round(deposit_amount, 2),
            "intervalDays": interval_days if interval_days > 0 else None,
            "nextDepositDate": next_deposit.isoformat() if next_deposit else None,
            "forecastYearDepositCount": int(annual_planned / deposit_amount) if deposit_amount else 0,
            "forecastYearContributions": round(annual_planned, 2),
            "monthlyEquivalentDollars": round(annual_planned / 12.0, 2),
            "source": plan.get("source"),
            "configuredVerdict": plan_artifact.get("verdict"),
        },
        "projections": projections,
        "milestones": milestones,
        "layeredMath": {
            "baseEightPctOneYearDollars": round(base_eight_percent, 2),
            "forecastYearContributionsDollars": round(annual_planned, 2),
            "contributionToBaseEightPctReturnRatio": contribution_to_starting_return,
            "flatProjectionEndingBalance": flat["endingBalance"],
            "illustrativeEightPctEndingBalance": illustrative["endingBalance"],
            "illustrativeEightPctMarketGrowthDollars": illustrative["marketGrowthDollars"],
            "plannedDepositsAreDeployable": False,
        },
        "warnings": warnings,
        "nextActions": [
            "Keep scheduled deposits forecast-only until broker cash confirms them.",
            "Use this as a contribution and compounding comparison; it does not select securities or authorize orders.",
            "Rerun account sync and capital readiness after a confirmed deposit before considering any sizing decision.",
        ],
        "citations": [
            "data/inferno_live_account_sync.json",
            "data/inferno_schwab_account_sync.json",
            "data/inferno_deposit_plan.json",
            "data/inferno_cash_attribution.json",
            "data/nlv_history.csv",
        ],
    }
    return payload


def render_growth_stack(payload: dict[str, Any]) -> str:
    """Render the stacked numbers into an operator-readable research report."""
    account = payload.get("account") or {}
    cash = payload.get("cashAttribution") or {}
    progress = payload.get("observedProgress") or {}
    plan = payload.get("depositPlan") or {}
    layered = payload.get("layeredMath") or {}
    observed_delta = progress.get("observedNlvDeltaDollars")
    observed_change_pct = progress.get("observedNlvChangePct")
    observed_delta_text = (
        "n/a" if observed_delta is None else f"${number(observed_delta):+,.2f}"
    )
    observed_change_pct_text = (
        "n/a" if observed_change_pct is None else f"{number(observed_change_pct):+.2f}%"
    )
    short_horizon_lines: list[str] = []
    for window in progress.get("shortHorizonWindows") or []:
        delta = window.get("observedNlvDeltaDollars")
        change_pct = window.get("observedNlvChangePct")
        delta_text = "n/a" if delta is None else f"${number(delta):+,.2f}"
        change_pct_text = "n/a" if change_pct is None else f"{number(change_pct):+.2f}%"
        short_horizon_lines.append(
            f"- {window.get('windowDays')}d target / {window.get('actualSpanDays') or '-'}d actual: "
            f"{delta_text} | {change_pct_text} | {window.get('verdict') or '-'}"
        )
    lines = [
        "Inferno Growth Stack",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Message: {payload.get('message')}",
        "",
        "Inputs",
        f"- Broker NLV: ${number(account.get('netLiquidatingValue')):,.2f} | source {account.get('source')}",
        f"- Deposit plan: ${number(plan.get('amountDollars')):,.2f} every {plan.get('intervalDays') or '-'} day(s) | next {plan.get('nextDepositDate') or '-'}",
        f"- One-year scheduled contributions: ${number(plan.get('forecastYearContributions')):,.2f} ({plan.get('forecastYearDepositCount', 0)} deposit(s))",
        f"- Monthly equivalent: ${number(plan.get('monthlyEquivalentDollars')):,.2f}",
        f"- Cash attribution: {cash.get('verdict') or '-'} | broker cash ${number(cash.get('brokerCash')):,.2f}",
        "",
        "Twelve-month layered projections",
    ]
    for row in payload.get("projections") or []:
        lines.append(
            f"- {row.get('label')}: ${number(row.get('endingBalance')):,.2f} ending | "
            f"${number(row.get('grossContributions')):,.2f} deposits | "
            f"${number(row.get('marketGrowthDollars')):,.2f} market component"
        )
    ratio = layered.get("contributionToBaseEightPctReturnRatio")
    ratio_text = f"{number(ratio):.2f}x" if ratio is not None else "n/a"
    lines.extend(
        [
            "",
            "Contribution versus return layer",
            f"- 8% of starting NLV for one year: ${number(layered.get('baseEightPctOneYearDollars')):,.2f}",
            f"- Scheduled one-year contributions: ${number(layered.get('forecastYearContributionsDollars')):,.2f} ({ratio_text} that starting-balance return)",
            f"- 8% scenario market component after deposits: ${number(layered.get('illustrativeEightPctMarketGrowthDollars')):,.2f}",
            "- Planned deposits remain forecast-only and are never deployable cash.",
            "",
            "Cash attribution boundary",
            f"- Latest broker-cash movement: ${number(cash.get('latestDeltaCash')):,.2f} | {cash.get('latestClassification') or '-'}",
            f"- Realized options profit known: {cash.get('realizedOptionsProfitKnown')}",
            "- This forecast never converts an unexplained cash movement into a deposit, profit, or deployable cash.",
            "",
            "Observed account progress (not a return calculation)",
            f"- Baseline NLV: ${number((progress.get('baseline') or {}).get('netLiquidatingValue')):,.2f} | "
            f"current broker NLV: ${number(progress.get('currentNlv')):,.2f}",
            f"- Observed NLV change: {observed_delta_text} | {observed_change_pct_text} | "
            f"{progress.get('elapsedDays') if progress.get('elapsedDays') is not None else '-'} day(s)",
            f"- Attribution: {progress.get('returnAttribution') or '-'} | {progress.get('reason') or '-'}",
            "- An observed NLV change is never labelled market return, trading P/L, a confirmed deposit, or deployable cash.",
        ]
    )
    lines.extend(["", "Short-horizon observed NLV layers (not return calculations)"])
    lines.extend(short_horizon_lines or ["- No comparable NLV history yet."])
    lines.extend(["", "Milestone timing (mechanical scenarios)"])
    for row in payload.get("milestones") or []:
        timing = []
        for scenario in row.get("scenarios") or []:
            months = scenario.get("monthsFromNow")
            rendered = f"{months:.1f} mo" if months is not None else "not within 25y"
            timing.append(f"{scenario.get('annualReturnPct', 0):.0f}%: {rendered}")
        lines.append(f"- ${number(row.get('targetBalance')):,.0f}: " + " | ".join(timing))
    lines.extend(["", "Warnings"])
    lines.extend(f"- {warning}" for warning in payload.get("warnings") or ["none"])
    lines.extend(["", "Safety boundary"])
    lines.extend(
        [
            "- Research-only forecast; not a deposit instruction, security recommendation, or order.",
            "- Broker submission and live trading remain disabled.",
            "- No risk constant, eligible universe, ticket, or authority state was changed.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def save_growth_stack(payload: dict[str, Any]) -> None:
    """Persist the canonical JSON and compact text report atomically."""
    ensure_dirs()
    atomic_write_json(GROWTH_STACK_FILE, payload)
    atomic_write_text(GROWTH_STACK_TEXT_FILE, render_growth_stack(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the research-only Inferno contribution growth stack.")
    parser.add_argument("command", nargs="?", choices=("run", "status"), default="run")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and GROWTH_STACK_TEXT_FILE.exists():
        print(GROWTH_STACK_TEXT_FILE.read_text(encoding="utf-8"), end="")
        return 0
    payload = build_growth_stack()
    save_growth_stack(payload)
    print(render_growth_stack(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
