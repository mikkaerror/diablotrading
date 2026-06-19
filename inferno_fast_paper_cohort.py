from __future__ import annotations

"""Accelerated option-paper simulations for rapid research feedback.

This lane scans the broader bootstrap-ranked universe, prices real option
structures, opens the largest cap-fitting daily cohort, and closes each
simulation at conservative bid/ask liquidation prices after the next market
session. It is deliberately isolated from the true paper execution ledger and
from every promotion calculation.

Strict contract:
  - research-only and non-promotable
  - no broker, TOS, approval, or live-book mutation
  - every outcome remains exploratory evidence
  - quote timestamps must prove a later market session before auto-close
"""

import argparse
import itertools
from collections import Counter
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
    nearest_workday,
)

from inferno_config import (
    MAX_DAILY_TICKET_DOLLARS,
    MAX_OPEN_PAPER_TICKETS,
    local_now,
)
from inferno_execution_clerk import build_execution_queue
from inferno_io import atomic_write_json, atomic_write_text
from inferno_outcome_reviewer import estimated_entry_cashflow
from inferno_paper_bootstrap import build_bootstrap
from inferno_paper_execution import strategy_cost, ticket_hash
from inferno_paper_mark_to_market import build_paper_mark_to_market
from inferno_strike_selector import (
    build_strike_plan_from_queue,
    effective_paper_rehearsal_item,
    effective_strategy_alternative_item,
)
from server import (
    APPROVAL_QUEUE_FILE,
    DATA_DIR,
    REPORTS_DIR,
    SNAPSHOT_FILE,
    ensure_dirs,
    load_json_file,
)


FAST_PAPER_FILE = DATA_DIR / "inferno_fast_paper_cohort.json"
FAST_PAPER_LEDGER_FILE = DATA_DIR / "inferno_fast_paper_ledger.json"
FAST_PAPER_TEXT_FILE = REPORTS_DIR / "fast_paper_cohort_latest.txt"
FAST_PAPER_STAGE = "fast-paper-cohort-research-only"

SCAN_LIMIT = 60
TARGET_DAILY_TRADES = 5
MAX_PER_STRATEGY = 3
CONTRACT_MULTIPLIER = 100
EASTERN = ZoneInfo("America/New_York")


class NyseHolidayCalendar(AbstractHolidayCalendar):
    """NYSE full-day holidays needed by the one-session holding clock."""

    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday(
            "Juneteenth",
            month=6,
            day=19,
            start_date="2022-06-19",
            observance=nearest_workday,
        ),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas Day", month=12, day=25, observance=nearest_workday),
    ]


@lru_cache(maxsize=8)
def market_holidays(year: int) -> frozenset[date]:
    """Return observed NYSE full-day holidays around one calendar year."""
    start = f"{year - 1}-12-20"
    end = f"{year + 1}-01-10"
    values = NyseHolidayCalendar().holidays(start=start, end=end)
    return frozenset(value.date() for value in values)


def is_market_session(value: date) -> bool:
    """Return whether a date is a regular U.S. equity market session."""
    return value.weekday() < 5 and value not in market_holidays(value.year)


def next_market_session(value: date) -> date:
    """Return the first regular market session after ``value``."""
    candidate = value + timedelta(days=1)
    while not is_market_session(candidate):
        candidate += timedelta(days=1)
    return candidate


def number(value: Any, default: float = 0.0) -> float:
    """Coerce a loose numeric field without throwing."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_fast_ledger(path: Path = FAST_PAPER_LEDGER_FILE) -> dict[str, Any]:
    """Load the isolated exploratory ledger."""
    payload = load_json_file(path) or {}
    if isinstance(payload.get("items"), list):
        return payload
    return {
        "version": 1,
        "generatedAt": None,
        "updatedAt": None,
        "count": 0,
        "items": [],
    }


def open_items(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Return currently open fast-paper simulations."""
    return [
        item
        for item in ledger.get("items") or []
        if (item.get("outcome") or {}).get("status") == "open"
    ]


def effective_candidate(item: dict[str, Any]) -> dict[str, Any]:
    """Prefer a clean capped rehearsal or Greek-supported alternative."""
    return (
        effective_paper_rehearsal_item(item)
        or effective_strategy_alternative_item(item)
        or item
    )


def candidate_pool(
    strike_plan: dict[str, Any],
    proposals: list[dict[str, Any]],
    *,
    excluded_tickers: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return clean, priceable exploratory candidates with bootstrap metadata."""
    proposal_by_ticker = {
        str(item.get("ticker") or "").upper(): item for item in proposals
    }
    excluded = {ticker.upper() for ticker in (excluded_tickers or set())}
    candidates: list[dict[str, Any]] = []
    for raw_item in strike_plan.get("items") or []:
        ticker = str(raw_item.get("ticker") or "").upper()
        proposal = proposal_by_ticker.get(ticker)
        if not ticker or not proposal or ticker in excluded:
            continue
        if raw_item.get("approvalStatus") == "rejected":
            continue
        item = effective_candidate(raw_item)
        verdict = item.get("riskVerdict") or {}
        plan = item.get("strikePlan") or {}
        max_loss = number(plan.get("estimatedMaxLoss"), -1.0)
        if not item.get("ok") or not verdict.get("passed") or max_loss <= 0:
            continue
        candidates.append(
            {
                "ticker": ticker,
                "bootstrapScore": int(proposal.get("score") or 0),
                "failedGates": list(proposal.get("failedGates") or []),
                "readiness": number(proposal.get("readiness")),
                "liveQualityYet": bool(proposal.get("liveQualityYet")),
                "strategy": plan.get("strategy"),
                "maxLoss": round(max_loss, 2),
                "item": {
                    **item,
                    "paperBootstrap": True,
                    "promotionEligible": False,
                    "evidenceCohort": "exploratory-fast",
                    "bootstrapScore": int(proposal.get("score") or 0),
                    "bootstrapFailedGates": list(proposal.get("failedGates") or []),
                },
            }
        )
    return candidates


def choose_daily_slate(
    candidates: list[dict[str, Any]],
    *,
    capacity: int = TARGET_DAILY_TRADES,
    daily_risk_cap: float = MAX_DAILY_TICKET_DOLLARS,
) -> list[dict[str, Any]]:
    """Maximize trade count first, then diversity and bootstrap quality."""
    if capacity <= 0 or not candidates:
        return []
    best: tuple[tuple[Any, ...], tuple[dict[str, Any], ...]] | None = None
    upper = min(capacity, len(candidates))
    for size in range(1, upper + 1):
        for combo in itertools.combinations(candidates, size):
            total_risk = sum(number(item.get("maxLoss")) for item in combo)
            if total_risk > daily_risk_cap:
                continue
            strategy_counts = Counter(str(item.get("strategy") or "UNKNOWN") for item in combo)
            if strategy_counts and max(strategy_counts.values()) > MAX_PER_STRATEGY:
                continue
            objective = (
                len(combo),
                len(strategy_counts),
                sum(int(item.get("bootstrapScore") or 0) for item in combo),
                sum(number(item.get("readiness")) for item in combo),
                -round(total_risk, 2),
            )
            if best is None or objective > best[0]:
                best = (objective, combo)
    if best is None:
        return []
    return sorted(
        best[1],
        key=lambda item: (
            -int(item.get("bootstrapScore") or 0),
            -number(item.get("readiness")),
            number(item.get("maxLoss")),
            str(item.get("ticker") or ""),
        ),
    )


def build_fast_entry(candidate: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Convert one selected candidate into an isolated simulation record."""
    item = candidate.get("item") or {}
    plan = item.get("strikePlan") or {}
    legs = list(plan.get("legs") or [])
    cost_type, cost = strategy_cost(plan)
    trade_date = now.date()
    ticket_id = ticket_hash(
        [
            "fast-paper",
            trade_date.isoformat(),
            item.get("ticker"),
            plan.get("strategy"),
            plan.get("expiration"),
            ",".join(str(leg.get("symbol") or "") for leg in legs),
        ]
    )
    return {
        "ticketId": ticket_id,
        "createdAt": now.isoformat(),
        "tradeDate": trade_date.isoformat(),
        "exitEligibleDate": next_market_session(trade_date).isoformat(),
        "ticker": item.get("ticker"),
        "setupRec": item.get("setupRec"),
        "strategy": plan.get("strategy"),
        "status": "sim-open",
        "paperOnly": True,
        "paperBootstrap": True,
        "autoSimulation": True,
        "evidenceCohort": "exploratory-fast",
        "promotionEligible": False,
        "promotable": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "bootstrapScore": candidate.get("bootstrapScore"),
        "bootstrapFailedGates": candidate.get("failedGates") or [],
        "sourceStrikePlanGeneratedAt": item.get("generatedAt"),
        "underlyingPrice": item.get("price"),
        "daysUntilEarnings": item.get("daysUntilEarnings"),
        "expiration": plan.get("expiration"),
        "entryCostType": cost_type,
        "entryLimit": round(cost, 4),
        "estimatedMaxLoss": plan.get("estimatedMaxLoss"),
        "estimatedMaxProfit": plan.get("estimatedMaxProfit"),
        "riskVerdict": item.get("riskVerdict") or {},
        "legs": legs,
        "outcome": {
            "status": "open",
            "reviewedAt": None,
            "exitValue": None,
            "estimatedPnl": None,
            "notes": "one-session exploratory option simulation",
        },
    }


def epoch_date(value: Any) -> date | None:
    """Convert Schwab epoch milliseconds into an Eastern market date."""
    raw = number(value)
    if raw <= 0:
        return None
    seconds = raw / 1000.0 if raw > 10_000_000_000 else raw
    try:
        return datetime.fromtimestamp(seconds, tz=EASTERN).date()
    except (OverflowError, OSError, ValueError):
        return None


def quotes_cover_exit_session(mark: dict[str, Any], eligible: date) -> bool:
    """Require every leg quote to come from the eligible session or later."""
    legs = mark.get("perLeg") or []
    if not legs:
        return False
    quote_dates = [epoch_date(leg.get("quoteTimeInLong")) for leg in legs]
    return all(value is not None and value >= eligible for value in quote_dates)


def conservative_exit_value(mark: dict[str, Any]) -> float | None:
    """Liquidate buy legs at bid and sell legs at ask."""
    net_per_share = 0.0
    for leg in mark.get("perLeg") or []:
        instruction = str(leg.get("instruction") or "").upper()
        if instruction.startswith("BUY"):
            price = leg.get("currentBid")
            sign = 1.0
        elif instruction.startswith("SELL"):
            price = leg.get("currentAsk")
            sign = -1.0
        else:
            return None
        if price is None:
            return None
        net_per_share += sign * number(price)
    return round(net_per_share * CONTRACT_MULTIPLIER, 2)


def close_due_entries(
    ledger: dict[str, Any],
    mtm: dict[str, Any],
    *,
    now: datetime,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Close due simulations only when later-session Schwab quotes are proven."""
    marks = mtm.get("marksByTicketId") or {}
    closed_ids: list[str] = []
    pending: list[str] = []
    updated_items: list[dict[str, Any]] = []
    for item in ledger.get("items") or []:
        outcome = item.get("outcome") or {}
        eligible_raw = str(item.get("exitEligibleDate") or "")
        try:
            eligible = date.fromisoformat(eligible_raw)
        except ValueError:
            eligible = None
        if outcome.get("status") != "open" or eligible is None or now.date() < eligible:
            updated_items.append(item)
            continue

        mark = marks.get(str(item.get("ticketId") or "")) or {}
        if mark.get("fetchStatus") != "ok":
            pending.append(f"{item.get('ticker')}: current option quotes unavailable")
            updated_items.append(item)
            continue
        if not quotes_cover_exit_session(mark, eligible):
            pending.append(f"{item.get('ticker')}: waiting for a later market-session quote")
            updated_items.append(item)
            continue
        exit_value = conservative_exit_value(mark)
        if exit_value is None:
            pending.append(f"{item.get('ticker')}: conservative bid/ask exit is incomplete")
            updated_items.append(item)
            continue

        pnl = round(estimated_entry_cashflow(item) + exit_value, 2)
        updated_items.append(
            {
                **item,
                "status": "sim-closed",
                "outcome": {
                    **outcome,
                    "status": "closed",
                    "reviewedAt": now.isoformat(),
                    "exitValue": exit_value,
                    "estimatedPnl": pnl,
                    "notes": "closed at next-session conservative bid/ask liquidation",
                    "exitMethod": "schwab-next-session-bid-ask",
                },
            }
        )
        closed_ids.append(str(item.get("ticketId") or ""))
    return {
        **ledger,
        "updatedAt": now.isoformat(),
        "count": len(updated_items),
        "items": updated_items,
    }, closed_ids, pending


def build_priceable_slate(
    snapshot: dict[str, Any],
    approval_queue: dict[str, Any],
    *,
    scan_limit: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build bootstrap proposals and price the broader ranked universe."""
    bootstrap = build_bootstrap(
        snapshot_loader=lambda: snapshot,
        max_tickets=scan_limit,
    )
    tickers = [
        str(item.get("ticker") or "").upper()
        for item in bootstrap.get("proposals") or []
        if str(item.get("ticker") or "").strip()
    ]
    expanded_snapshot = {**snapshot, "reviewQueueTickers": tickers}
    queue = build_execution_queue(
        expanded_snapshot,
        approval_queue,
        limit_override=len(tickers),
        enforce_capacity_limits=False,
    )
    strike_plan = build_strike_plan_from_queue(queue, limit=len(tickers))
    return bootstrap, strike_plan


def build_fast_paper_cohort(
    *,
    now: datetime | None = None,
    ledger_override: dict[str, Any] | None = None,
    snapshot_override: dict[str, Any] | None = None,
    approval_queue_override: dict[str, Any] | None = None,
    bootstrap_override: dict[str, Any] | None = None,
    strike_plan_override: dict[str, Any] | None = None,
    mtm_override: dict[str, Any] | None = None,
    scan_limit: int = SCAN_LIMIT,
    target_trades: int = TARGET_DAILY_TRADES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one close-then-open accelerated simulation cycle."""
    now = now or local_now()
    ledger = ledger_override if ledger_override is not None else load_fast_ledger()
    due = [
        item for item in open_items(ledger)
        if str(item.get("exitEligibleDate") or "") <= now.date().isoformat()
    ]
    if mtm_override is not None:
        mtm = mtm_override
    elif due:
        mtm = build_paper_mark_to_market(now=now, ledger_override=ledger)
    else:
        mtm = {"fetchStatus": "no-due-positions", "marksByTicketId": {}}
    ledger, closed_ids, close_pending = close_due_entries(ledger, mtm, now=now)

    existing_open = open_items(ledger)
    opened_today = [
        item for item in ledger.get("items") or []
        if item.get("tradeDate") == now.date().isoformat()
    ]
    capacity = max(0, min(target_trades, MAX_OPEN_PAPER_TICKETS - len(existing_open)))
    selected: list[dict[str, Any]] = []
    pool: list[dict[str, Any]] = []
    bootstrap: dict[str, Any] = bootstrap_override or {}
    strike_plan: dict[str, Any] = strike_plan_override or {}

    if is_market_session(now.date()) and capacity > 0 and not opened_today:
        snapshot = snapshot_override if snapshot_override is not None else (
            load_json_file(SNAPSHOT_FILE) or {}
        )
        approval_queue = (
            approval_queue_override
            if approval_queue_override is not None
            else (load_json_file(APPROVAL_QUEUE_FILE) or {"items": []})
        )
        if not bootstrap or not strike_plan:
            bootstrap, strike_plan = build_priceable_slate(
                snapshot,
                approval_queue,
                scan_limit=scan_limit,
            )
        excluded = {str(item.get("ticker") or "").upper() for item in existing_open}
        pool = candidate_pool(
            strike_plan,
            bootstrap.get("proposals") or [],
            excluded_tickers=excluded,
        )
        selected = choose_daily_slate(pool, capacity=capacity)
        new_entries = [build_fast_entry(item, now=now) for item in selected]
        existing_ids = {str(item.get("ticketId") or "") for item in ledger.get("items") or []}
        inserted = [item for item in new_entries if str(item.get("ticketId") or "") not in existing_ids]
        ledger = {
            **ledger,
            "version": 1,
            "generatedAt": ledger.get("generatedAt") or now.isoformat(),
            "updatedAt": now.isoformat(),
            "items": list(ledger.get("items") or []) + inserted,
        }
        ledger["count"] = len(ledger["items"])

    all_items = ledger.get("items") or []
    closed = [
        item for item in all_items
        if (item.get("outcome") or {}).get("status") == "closed"
    ]
    closed_pnls = [
        number((item.get("outcome") or {}).get("estimatedPnl"))
        for item in closed
        if (item.get("outcome") or {}).get("estimatedPnl") is not None
    ]
    current_open = open_items(ledger)
    opened_ids = {
        build_fast_entry(item, now=now).get("ticketId") for item in selected
    } if selected else set()

    if closed_ids and opened_ids:
        verdict = "cycled-and-seeded"
    elif opened_ids:
        verdict = "seeded"
    elif not is_market_session(now.date()):
        verdict = "market-closed"
    elif current_open:
        verdict = "awaiting-next-session"
    elif pool:
        verdict = "daily-risk-cap-limited"
    else:
        verdict = "no-priceable-candidates"

    open_slate = [
        {
            "ticker": item.get("ticker"),
            "strategy": item.get("strategy"),
            "bootstrapScore": item.get("bootstrapScore"),
            "failedGates": item.get("bootstrapFailedGates") or [],
            "maxLoss": item.get("estimatedMaxLoss"),
            "exitEligibleDate": item.get("exitEligibleDate"),
            "promotionEligible": False,
        }
        for item in current_open
    ]
    payload = {
        "generatedAt": now.isoformat(),
        "stage": FAST_PAPER_STAGE,
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "verdict": verdict,
        "scanLimit": scan_limit,
        "targetDailyTrades": target_trades,
        "marketSession": is_market_session(now.date()),
        "scanPerformed": bool(bootstrap or strike_plan),
        "counts": {
            "bootstrapProposals": len(bootstrap.get("proposals") or []),
            "priceableCandidates": len(pool),
            "selectedToday": len(opened_ids),
            "closedToday": len(closed_ids),
            "closePending": len(close_pending),
            "open": len(current_open),
            "closedLifetime": len(closed),
        },
        "riskBudget": {
            "dailyMaxLossCap": MAX_DAILY_TICKET_DOLLARS,
            "openTicketCap": MAX_OPEN_PAPER_TICKETS,
            "selectedMaxLoss": round(sum(number(item.get("maxLoss")) for item in selected), 2),
            "openMaxLoss": round(
                sum(number(item.get("estimatedMaxLoss")) for item in current_open),
                2,
            ),
        },
        "selectedSlate": [
            {
                "ticker": item.get("ticker"),
                "strategy": item.get("strategy"),
                "bootstrapScore": item.get("bootstrapScore"),
                "failedGates": item.get("failedGates") or [],
                "maxLoss": item.get("maxLoss"),
                "promotionEligible": False,
            }
            for item in selected
        ],
        "openSlate": open_slate,
        "closedTicketIds": closed_ids,
        "closePendingReasons": close_pending,
        "performance": {
            "scoredCount": len(closed_pnls),
            "totalPnl": round(sum(closed_pnls), 2),
            "averagePnl": round(sum(closed_pnls) / len(closed_pnls), 2) if closed_pnls else None,
            "winRate": (
                round(sum(1 for pnl in closed_pnls if pnl > 0) / len(closed_pnls), 4)
                if closed_pnls else None
            ),
        },
        "reminders": [
            "exploratory simulations do not count toward the 30-trade promotion gate",
            "entries use priced option structures; exits use later-session Schwab bid/ask quotes",
            "no approval, broker, TOS, live-book, or authority mutation occurs",
        ],
        "citations": [
            "data/latest_snapshot.json",
            "data/inferno_paper_bootstrap.json",
            "Schwab market-data option chains",
        ],
    }
    return payload, ledger


def fast_paper_text(payload: dict[str, Any]) -> str:
    """Render the accelerated cohort as a compact operator report."""
    counts = payload.get("counts") or {}
    risk = payload.get("riskBudget") or {}
    performance = payload.get("performance") or {}
    lines = [
        "Inferno Fast Paper Cohort",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        "Authority: research-only; promotion credit OFF; broker submit OFF",
        "",
        "Cycle:",
        f"- scanned bootstrap proposals: {counts.get('bootstrapProposals', 0)}",
        f"- scan performed this run: {'yes' if payload.get('scanPerformed') else 'no'}",
        f"- priceable candidates: {counts.get('priceableCandidates', 0)}",
        f"- selected today: {counts.get('selectedToday', 0)} / {payload.get('targetDailyTrades')}",
        f"- closed today: {counts.get('closedToday', 0)}",
        f"- open now: {counts.get('open', 0)}",
        f"- close pending: {counts.get('closePending', 0)}",
        f"- selected max loss: ${number(risk.get('selectedMaxLoss')):,.2f} / "
        f"${number(risk.get('dailyMaxLossCap')):,.2f}",
        f"- open max loss: ${number(risk.get('openMaxLoss')):,.2f}",
        "",
        "Open slate:",
    ]
    slate = payload.get("openSlate") or []
    if not slate:
        lines.append("- none")
    for item in slate:
        failed = ", ".join(item.get("failedGates") or []) or "none"
        lines.append(
            f"- {item.get('ticker')} | {item.get('strategy')} | "
            f"score {item.get('bootstrapScore')}/5 | max loss ${number(item.get('maxLoss')):,.2f} | "
            f"exit eligible {item.get('exitEligibleDate')} | failed bootstrap gates: {failed}"
        )
    lines.extend(
        [
            "",
            "Exploratory performance:",
            f"- scored: {performance.get('scoredCount', 0)}",
            f"- total P/L: {performance.get('totalPnl')}",
            f"- average P/L: {performance.get('averagePnl')}",
            f"- win rate: {performance.get('winRate')}",
        ]
    )
    pending = payload.get("closePendingReasons") or []
    if pending:
        lines.extend(["", "Pending exits:"])
        lines.extend(f"- {reason}" for reason in pending)
    lines.extend(["", "Reminders:"])
    lines.extend(f"- {item}" for item in payload.get("reminders") or [])
    return "\n".join(lines).rstrip() + "\n"


def save_fast_paper(payload: dict[str, Any], ledger: dict[str, Any]) -> None:
    """Persist the isolated cohort, ledger, and text report."""
    ensure_dirs()
    atomic_write_json(FAST_PAPER_FILE, payload)
    atomic_write_json(FAST_PAPER_LEDGER_FILE, ledger)
    atomic_write_text(FAST_PAPER_TEXT_FILE, fast_paper_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the isolated accelerated option-paper simulation cohort."
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--scan-limit", type=int, default=SCAN_LIMIT)
    parser.add_argument("--target", type=int, default=TARGET_DAILY_TRADES)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        if FAST_PAPER_TEXT_FILE.exists():
            print(FAST_PAPER_TEXT_FILE.read_text(encoding="utf-8"))
        else:
            print("(no cached fast-paper cohort report)")
        return 0
    payload, ledger = build_fast_paper_cohort(
        scan_limit=max(1, args.scan_limit),
        target_trades=max(1, args.target),
    )
    save_fast_paper(payload, ledger)
    print(fast_paper_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
