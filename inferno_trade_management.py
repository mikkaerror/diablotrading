from __future__ import annotations

"""Trade-management auditor for open paper tickets (research-only).

Walks every OPEN paper position in the ledger, joins it to the latest
mark-to-market snapshot, applies the rules from
``docs/TRADE_MANAGEMENT_PLAYBOOK.md``, and emits a per-position recommended
action with a short rationale. Output is the daily report card the operator
reads each morning -- nothing in this module closes, approves, or routes a
trade. The operator clicks the buttons.

Strategy taxonomy (mirrors the playbook):

  Lane A -- long-vol, capped loss, large/uncapped upside.
    LONG_STRADDLE, LONG_STRANGLE, LONG_CALL, LONG_PUT
    Rules: +50% / +100% / +200% scale-out, -50% stop, time-stops, pre-event
    exit by default until 30 closed outcomes accrue.

  Lane B credit -- defined-risk, high win-rate, capped profit.
    PUT_CREDIT_SPREAD, CALL_CREDIT_SPREAD, IRON_CONDOR
    Rules: close at +50% of max profit, accelerated trim in last 7 days,
    stop at -100% of credit collected.

  Lane B debit -- defined-risk, asymmetric.
    CALL_DEBIT_SPREAD, PUT_DEBIT_SPREAD
    Rules: half off at +50% of max profit, close the rest at +80%, hard
    stop at -50% of debit.

  Unknown -- not classifiable; emits ``hold`` plus a warning.

Strict invariants: research-only, promotable=False, authorityChanged=False,
liveTradingAllowed False, brokerSubmitAllowed False. Never mutates the
ledger or the MTM artifact.
"""

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


# ─────────────────────────── files / constants ───────────────────────

PAPER_EXECUTION_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
PAPER_MTM_FILE = DATA_DIR / "inferno_paper_mark_to_market.json"
TRADE_MANAGEMENT_FILE = DATA_DIR / "inferno_trade_management.json"
TRADE_MANAGEMENT_TEXT_FILE = REPORTS_DIR / "trade_management_latest.txt"

TRADE_MANAGEMENT_STAGE = "trade-management-research-only"

# Playbook trigger thresholds. These match docs/TRADE_MANAGEMENT_PLAYBOOK.md
# §3 (Lane A) and §4 (Lane B). Pinned here so tests catch any drift.
LANE_A_TAKE_PROFIT_1_PCT_OF_DEBIT = 0.50
LANE_A_TAKE_PROFIT_2_PCT_OF_DEBIT = 1.00
LANE_A_TAKE_PROFIT_3_PCT_OF_DEBIT = 2.00
LANE_A_STOP_LOSS_PCT_OF_DEBIT = -0.50
LANE_A_TIME_STOP_HARD_DAYS = 2     # close all by T-2 days regardless
LANE_A_TIME_STOP_FLAT_DAYS = 3     # close at T-3 if position is flat
LANE_A_FLAT_BAND = 0.10            # +/-10% of debit counts as flat

LANE_B_CREDIT_TAKE_PROFIT_1_PCT_OF_MAX = 0.50
LANE_B_CREDIT_TAKE_PROFIT_2_PCT_OF_MAX = 0.25  # only if T-7 or sooner
LANE_B_CREDIT_LATE_DAYS = 7
LANE_B_CREDIT_FORCE_CLOSE_DAYS = 3
LANE_B_CREDIT_STOP_PCT_OF_CREDIT = -1.0  # loss = 2x the credit collected

LANE_B_DEBIT_TAKE_PROFIT_1_PCT_OF_MAX = 0.50
LANE_B_DEBIT_TAKE_PROFIT_2_PCT_OF_MAX = 0.80
LANE_B_DEBIT_TIME_STOP_DAYS = 2
LANE_B_DEBIT_STOP_PCT_OF_DEBIT = -0.50

PRE_EVENT_EXIT_DAYS = 1            # close before earnings if <= this many days out
DTE_POLICY_REVIEW_DAYS = 21        # review trigger, never an automatic close

# Set of verdicts the doctor + tests consume.
VERDICTS = (
    "hold",
    "take-profit-1",
    "take-profit-2",
    "take-profit-3",
    "stop-loss",
    "time-stop",
    "pre-event-exit",
    "awaiting-data",
)


# ─────────────────────────── helpers ──────────────────────────────────


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _parse_iso_date(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _strategy_lane(strategy: str | None) -> str:
    """Classify a strategy string into ``lane-a`` / ``lane-b-credit`` /
    ``lane-b-debit`` / ``unknown``.
    """
    name = str(strategy or "").upper().strip()
    if not name:
        return "unknown"
    if name in {"LONG_STRADDLE", "LONG_STRANGLE", "LONG_CALL", "LONG_PUT"}:
        return "lane-a"
    if name in {"PUT_CREDIT_SPREAD", "CALL_CREDIT_SPREAD", "IRON_CONDOR"}:
        return "lane-b-credit"
    if name in {"CALL_DEBIT_SPREAD", "PUT_DEBIT_SPREAD", "VERTICAL_DEBIT_SPREAD"}:
        return "lane-b-debit"
    return "unknown"


def _days_to_expiration(ticket: dict[str, Any], today: date) -> int | None:
    exp = _parse_iso_date(ticket.get("expiration"))
    if exp is None:
        return None
    return (exp - today).days


def _days_until_earnings(ticket: dict[str, Any]) -> int | None:
    """Read frozen daysUntilEarnings from the ledger entry.

    Note: this is the count captured at strike-plan time, not a live count.
    The playbook treats it as a directional signal rather than a real-time
    metric; the operator should refresh the strike plan to recompute.
    """
    raw = ticket.get("daysUntilEarnings")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _open_paper_tickets(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    items = ledger.get("items") or []
    return [
        it for it in items
        if ((it.get("outcome") or {}).get("status")) == "open"
    ]


# ─────────────────────────── per-lane verdict rules ──────────────────


def _verdict_lane_a(
    *,
    mark: dict[str, Any] | None,
    dte: int | None,
    dte_earnings: int | None,
) -> tuple[str, list[str]]:
    """Long-vol playbook rules (Lane A).

    Returns (verdict, rationale_lines).
    """
    rationale: list[str] = []
    if mark is None or mark.get("playbookPctOfDebit") is None:
        if dte is not None and dte <= LANE_A_TIME_STOP_HARD_DAYS:
            rationale.append(
                f"hard time stop: {dte}d to expiry (≤ {LANE_A_TIME_STOP_HARD_DAYS}d)"
            )
            return "time-stop", rationale
        rationale.append("mark-to-market unavailable; price-triggered rules blocked")
        return "awaiting-data", rationale

    pct = float(mark.get("playbookPctOfDebit") or 0.0)
    rationale.append(f"playbook %-of-debit = {pct:+.4f}")

    # Pre-event exit: close before earnings unless desk has explicit
    # post-event-edge evidence (we don't until 30 outcomes accrue).
    if dte_earnings is not None and dte_earnings <= PRE_EVENT_EXIT_DAYS and dte_earnings >= 0:
        rationale.append(
            f"pre-event exit: daysUntilEarnings = {dte_earnings} ≤ {PRE_EVENT_EXIT_DAYS}"
        )
        return "pre-event-exit", rationale

    # Hard time stop -- close everything by T-2.
    if dte is not None and dte <= LANE_A_TIME_STOP_HARD_DAYS:
        rationale.append(
            f"hard time stop: {dte}d to expiry (≤ {LANE_A_TIME_STOP_HARD_DAYS}d)"
        )
        return "time-stop", rationale

    # Stop loss -- close immediately, no exception.
    if pct <= LANE_A_STOP_LOSS_PCT_OF_DEBIT:
        rationale.append(
            f"stop loss: {pct:+.2f} ≤ {LANE_A_STOP_LOSS_PCT_OF_DEBIT:+.2f} (per playbook §3.3)"
        )
        return "stop-loss", rationale

    # Profit ladder (highest tier first so the verdict reflects the deepest
    # target hit so far).
    if pct >= LANE_A_TAKE_PROFIT_3_PCT_OF_DEBIT:
        rationale.append(
            f"runner final: {pct:+.2f} ≥ {LANE_A_TAKE_PROFIT_3_PCT_OF_DEBIT:+.2f} -- close last 25%"
        )
        return "take-profit-3", rationale
    if pct >= LANE_A_TAKE_PROFIT_2_PCT_OF_DEBIT:
        rationale.append(
            f"take-profit tier 2: {pct:+.2f} ≥ {LANE_A_TAKE_PROFIT_2_PCT_OF_DEBIT:+.2f} -- trim 25%"
        )
        return "take-profit-2", rationale
    if pct >= LANE_A_TAKE_PROFIT_1_PCT_OF_DEBIT:
        rationale.append(
            f"take-profit tier 1: {pct:+.2f} ≥ {LANE_A_TAKE_PROFIT_1_PCT_OF_DEBIT:+.2f} -- trim 50%"
        )
        return "take-profit-1", rationale

    # Time stop on flat positions.
    is_flat = abs(pct) <= LANE_A_FLAT_BAND
    if dte is not None and dte <= LANE_A_TIME_STOP_FLAT_DAYS and is_flat:
        rationale.append(
            f"flat time stop: position within ±{LANE_A_FLAT_BAND:.0%} of entry "
            f"and {dte}d to expiry (≤ {LANE_A_TIME_STOP_FLAT_DAYS}d)"
        )
        return "time-stop", rationale

    rationale.append("no rule fired")
    return "hold", rationale


def _verdict_lane_b_credit(
    *,
    mark: dict[str, Any] | None,
    dte: int | None,
    estimated_credit: float | None,
) -> tuple[str, list[str]]:
    """Defined-risk premium-selling rules (Lane B credit)."""
    rationale: list[str] = []
    pnl_dollars = _safe_float(mark.get("unrealizedPnlDollars")) if mark else None
    pct_max = _safe_float(mark.get("unrealizedPnlPctOfMaxProfit")) if mark else None
    price_data_available = pnl_dollars is not None or pct_max is not None

    if not price_data_available:
        # Time-based rules still apply even with no live prices.
        if dte is not None and dte <= LANE_B_CREDIT_FORCE_CLOSE_DAYS:
            rationale.append(
                f"force close (T-{LANE_B_CREDIT_FORCE_CLOSE_DAYS}): {dte}d to expiry"
            )
            return "time-stop", rationale
        rationale.append("mark-to-market unavailable; price-triggered rules blocked")
        return "awaiting-data", rationale

    if pct_max is not None:
        rationale.append(f"unrealized %-of-max-profit = {pct_max:+.4f}")

    # Stop loss: per playbook §4.3, close credit spread when loss is 2x credit
    # collected (≈ -100% of credit). Credit-collected = estimated_credit * 100.
    if pnl_dollars is not None and estimated_credit and estimated_credit > 0:
        credit_dollars = estimated_credit * 100
        stop_loss_dollars = LANE_B_CREDIT_STOP_PCT_OF_CREDIT * credit_dollars
        if pnl_dollars <= stop_loss_dollars + 0.005:
            rationale.append(
                f"stop loss: PnL ${pnl_dollars:+.0f} ≤ "
                f"{LANE_B_CREDIT_STOP_PCT_OF_CREDIT:+.0%} × ${credit_dollars:.0f} credit"
            )
            return "stop-loss", rationale

    # Force-close in the last few days regardless of profit/loss.
    if dte is not None and dte <= LANE_B_CREDIT_FORCE_CLOSE_DAYS:
        if pct_max is not None and pct_max > 0:
            rationale.append(
                f"force close at any profit: {dte}d to expiry ≤ "
                f"{LANE_B_CREDIT_FORCE_CLOSE_DAYS}d"
            )
            return "take-profit-3", rationale
        rationale.append(
            f"time stop: {dte}d to expiry ≤ {LANE_B_CREDIT_FORCE_CLOSE_DAYS}d, not profitable"
        )
        return "time-stop", rationale

    # Standard 50% rule.
    if pct_max is not None and pct_max >= LANE_B_CREDIT_TAKE_PROFIT_1_PCT_OF_MAX:
        rationale.append(
            f"take-profit at 50% of max profit: "
            f"{pct_max:+.2f} ≥ {LANE_B_CREDIT_TAKE_PROFIT_1_PCT_OF_MAX:+.2f}"
        )
        return "take-profit-1", rationale

    # Accelerated trim in the danger week.
    if (
        dte is not None
        and dte <= LANE_B_CREDIT_LATE_DAYS
        and pct_max is not None
        and pct_max >= LANE_B_CREDIT_TAKE_PROFIT_2_PCT_OF_MAX
    ):
        rationale.append(
            f"late-cycle trim: {dte}d to expiry and "
            f"{pct_max:+.2f} ≥ {LANE_B_CREDIT_TAKE_PROFIT_2_PCT_OF_MAX:+.2f} of max"
        )
        return "take-profit-2", rationale

    rationale.append("no rule fired")
    return "hold", rationale


def _verdict_lane_b_debit(
    *,
    mark: dict[str, Any] | None,
    dte: int | None,
) -> tuple[str, list[str]]:
    """Defined-risk debit-spread rules (Lane B debit)."""
    rationale: list[str] = []
    pct_max = _safe_float(mark.get("unrealizedPnlPctOfMaxProfit")) if mark else None
    pct_debit = _safe_float(mark.get("playbookPctOfDebit")) if mark else None
    price_data_available = pct_max is not None or pct_debit is not None

    if not price_data_available:
        if dte is not None and dte <= LANE_B_DEBIT_TIME_STOP_DAYS:
            rationale.append(
                f"hard time stop: {dte}d to expiry ≤ {LANE_B_DEBIT_TIME_STOP_DAYS}d"
            )
            return "time-stop", rationale
        rationale.append("mark-to-market unavailable; price-triggered rules blocked")
        return "awaiting-data", rationale

    if pct_max is not None:
        rationale.append(f"unrealized %-of-max-profit = {pct_max:+.4f}")
    if pct_debit is not None:
        rationale.append(f"playbook %-of-debit = {pct_debit:+.4f}")

    # Hard stop loss on debit at -50%.
    if pct_debit is not None and pct_debit <= LANE_B_DEBIT_STOP_PCT_OF_DEBIT:
        rationale.append(
            f"stop loss: {pct_debit:+.2f} ≤ {LANE_B_DEBIT_STOP_PCT_OF_DEBIT:+.2f}"
        )
        return "stop-loss", rationale

    # Hard time stop at T-2.
    if dte is not None and dte <= LANE_B_DEBIT_TIME_STOP_DAYS:
        rationale.append(
            f"hard time stop: {dte}d to expiry ≤ {LANE_B_DEBIT_TIME_STOP_DAYS}d"
        )
        return "time-stop", rationale

    # Profit ladder.
    if pct_max is not None and pct_max >= LANE_B_DEBIT_TAKE_PROFIT_2_PCT_OF_MAX:
        rationale.append(
            f"close remaining at +80%: {pct_max:+.2f} ≥ "
            f"{LANE_B_DEBIT_TAKE_PROFIT_2_PCT_OF_MAX:+.2f}"
        )
        return "take-profit-2", rationale
    if pct_max is not None and pct_max >= LANE_B_DEBIT_TAKE_PROFIT_1_PCT_OF_MAX:
        rationale.append(
            f"trim half at +50% of max: {pct_max:+.2f} ≥ "
            f"{LANE_B_DEBIT_TAKE_PROFIT_1_PCT_OF_MAX:+.2f}"
        )
        return "take-profit-1", rationale

    rationale.append("no rule fired")
    return "hold", rationale


def _strategy_plan(ticket: dict[str, Any]) -> dict[str, Any]:
    """Return the strike-plan sub-dict so we can read estimatedCredit."""
    plan = ticket.get("strikePlan")
    return plan if isinstance(plan, dict) else {}


# ─────────────────────────── per-position assessment ─────────────────


def assess_ticket(
    ticket: dict[str, Any],
    *,
    mark: dict[str, Any] | None,
    today: date,
) -> dict[str, Any]:
    """Return the verdict and rationale for one open ticket."""
    lane = _strategy_lane(ticket.get("strategy"))
    dte = _days_to_expiration(ticket, today)
    dte_earnings = _days_until_earnings(ticket)
    plan = _strategy_plan(ticket)
    estimated_credit = _safe_float(
        plan.get("estimatedCredit") if plan else ticket.get("estimatedCredit")
    )

    if lane == "lane-a":
        verdict, rationale = _verdict_lane_a(
            mark=mark, dte=dte, dte_earnings=dte_earnings
        )
    elif lane == "lane-b-credit":
        verdict, rationale = _verdict_lane_b_credit(
            mark=mark, dte=dte, estimated_credit=estimated_credit
        )
    elif lane == "lane-b-debit":
        verdict, rationale = _verdict_lane_b_debit(mark=mark, dte=dte)
    else:
        verdict, rationale = (
            "hold",
            [f"unknown strategy family '{ticket.get('strategy')}'; no rules applied"],
        )

    return {
        "ticketId": ticket.get("ticketId"),
        "ticker": ticket.get("ticker"),
        "strategy": ticket.get("strategy"),
        "lane": lane,
        "expiration": ticket.get("expiration"),
        "daysToExpiration": dte,
        "dtePolicyReview": bool(
            dte is not None
            and LANE_B_CREDIT_FORCE_CLOSE_DAYS < dte <= DTE_POLICY_REVIEW_DAYS
        ),
        "daysUntilEarnings": dte_earnings,
        "entryLimit": _safe_float(ticket.get("entryLimit")),
        "estimatedMaxLoss": _safe_float(ticket.get("estimatedMaxLoss")),
        "estimatedMaxProfit": ticket.get("estimatedMaxProfit"),
        "verdict": verdict,
        "rationale": rationale,
        "markFetchStatus": (mark or {}).get("fetchStatus"),
        "unrealizedPnlDollars": _safe_float((mark or {}).get("unrealizedPnlDollars")),
        "playbookPctOfDebit": _safe_float((mark or {}).get("playbookPctOfDebit")),
        "unrealizedPnlPctOfMaxProfit": _safe_float(
            (mark or {}).get("unrealizedPnlPctOfMaxProfit")
        ),
    }


# ─────────────────────────── build + render ───────────────────────────


def build_trade_management(
    *,
    now: datetime | None = None,
    ledger_override: dict[str, Any] | None = None,
    mtm_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or local_now()
    today = now.date() if isinstance(now, datetime) else now

    ledger = (
        ledger_override if ledger_override is not None
        else load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {"items": []}
    )
    mtm = mtm_override if mtm_override is not None else (
        load_json_file(PAPER_MTM_FILE) or {}
    )
    marks_by_ticket = (mtm.get("marksByTicketId") or {}) if isinstance(mtm, dict) else {}
    mtm_fetch_status = mtm.get("fetchStatus") if isinstance(mtm, dict) else None

    open_tickets = _open_paper_tickets(ledger)
    assessments: list[dict[str, Any]] = []
    verdict_counts: dict[str, int] = {v: 0 for v in VERDICTS}

    for ticket in open_tickets:
        ticket_id = str(ticket.get("ticketId") or "")
        mark = marks_by_ticket.get(ticket_id) if ticket_id else None
        result = assess_ticket(ticket, mark=mark, today=today)
        assessments.append(result)
        verdict = result["verdict"]
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1

    actionable_count = sum(
        c for v, c in verdict_counts.items() if v not in {"hold", "awaiting-data"}
    )
    dte_policy_review_count = sum(
        1 for assessment in assessments if assessment.get("dtePolicyReview")
    )

    awaiting_data_count = verdict_counts.get("awaiting-data", 0)
    overall_verdict = (
        "no-open-positions" if not open_tickets
        else "actions-recommended" if actionable_count > 0
        else "awaiting-data" if awaiting_data_count > 0
        else "all-hold"
    )

    return {
        "generatedAt": now.isoformat() if isinstance(now, datetime) else None,
        "stage": TRADE_MANAGEMENT_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "verdict": overall_verdict,
        "openPositionCount": len(open_tickets),
        "actionableCount": actionable_count,
        "dtePolicyReviewCount": dte_policy_review_count,
        "verdictCounts": verdict_counts,
        "mtmFetchStatus": mtm_fetch_status,
        "assessments": assessments,
        "thresholds": {
            "laneA": {
                "takeProfit1PctOfDebit": LANE_A_TAKE_PROFIT_1_PCT_OF_DEBIT,
                "takeProfit2PctOfDebit": LANE_A_TAKE_PROFIT_2_PCT_OF_DEBIT,
                "takeProfit3PctOfDebit": LANE_A_TAKE_PROFIT_3_PCT_OF_DEBIT,
                "stopLossPctOfDebit": LANE_A_STOP_LOSS_PCT_OF_DEBIT,
                "hardTimeStopDays": LANE_A_TIME_STOP_HARD_DAYS,
                "flatTimeStopDays": LANE_A_TIME_STOP_FLAT_DAYS,
            },
            "laneBCredit": {
                "takeProfit1PctOfMax": LANE_B_CREDIT_TAKE_PROFIT_1_PCT_OF_MAX,
                "takeProfit2PctOfMax": LANE_B_CREDIT_TAKE_PROFIT_2_PCT_OF_MAX,
                "lateDays": LANE_B_CREDIT_LATE_DAYS,
                "forceCloseDays": LANE_B_CREDIT_FORCE_CLOSE_DAYS,
                "stopPctOfCredit": LANE_B_CREDIT_STOP_PCT_OF_CREDIT,
            },
            "laneBDebit": {
                "takeProfit1PctOfMax": LANE_B_DEBIT_TAKE_PROFIT_1_PCT_OF_MAX,
                "takeProfit2PctOfMax": LANE_B_DEBIT_TAKE_PROFIT_2_PCT_OF_MAX,
                "timeStopDays": LANE_B_DEBIT_TIME_STOP_DAYS,
                "stopPctOfDebit": LANE_B_DEBIT_STOP_PCT_OF_DEBIT,
            },
            "preEventExitDays": PRE_EVENT_EXIT_DAYS,
            "dtePolicyReviewDays": DTE_POLICY_REVIEW_DAYS,
        },
        "citations": ["TRADE_MANAGEMENT_PLAYBOOK.md", "TASTYTRADE-50PCT-RULE"],
        "reminders": [
            "research-only: never closes, approves, or routes a trade",
            "broker submit OFF; liveTradingAllowed False; no authority change",
            "21 DTE is a review trigger; cohort evidence decides whether a family should close there",
            "verdicts are recommendations -- the operator clicks the buttons",
        ],
    }


def trade_management_text(payload: dict[str, Any]) -> str:
    """Render the phone-readable daily report card."""
    assessments = payload.get("assessments") or []
    counts = payload.get("verdictCounts") or {}
    lines = [
        "Inferno Trade Management",
        "",
        f"Generated:       {payload.get('generatedAt')}",
        f"Overall verdict: {payload.get('verdict')}",
        f"Open positions:  {payload.get('openPositionCount')}",
        f"Actionable:      {payload.get('actionableCount')}",
        f"DTE reviews:     {payload.get('dtePolicyReviewCount')}",
        f"MTM fetch:       {payload.get('mtmFetchStatus')}",
        "",
    ]
    if any(counts.values()):
        lines.append("Verdict counts:")
        for v in VERDICTS:
            c = counts.get(v, 0)
            if c:
                lines.append(f"  {v}: {c}")
        lines.append("")
    if not assessments:
        lines.append("(no open paper positions)")
    else:
        lines.append("Per-position recommendations:")
        for a in assessments:
            lines.append("")
            tid = str(a.get("ticketId") or "")
            lines.append(
                f"  {a.get('ticker'):>6} {a.get('strategy'):>22}  "
                f"DTE={a.get('daysToExpiration')}  "
                f"earnings={a.get('daysUntilEarnings')}  "
                f"(ticketId {tid[:8]}…)"
            )
            lines.append(f"    -> verdict: {a.get('verdict')}")
            if a.get("dtePolicyReview"):
                lines.append(
                    "       - review-dte-policy: compare with the 21-DTE cohort; no automatic close"
                )
            pnl = a.get("unrealizedPnlDollars")
            if pnl is not None:
                lines.append(f"       unrealized PnL: ${pnl:+.2f}")
            for r in a.get("rationale") or []:
                lines.append(f"       - {r}")
    lines.append("")
    lines.append("Reminders:")
    for r in payload.get("reminders") or []:
        lines.append(f"  - {r}")
    return "\n".join(lines).rstrip() + "\n"


def save_trade_management(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(TRADE_MANAGEMENT_FILE, payload)
    atomic_write_text(TRADE_MANAGEMENT_TEXT_FILE, trade_management_text(payload))


# ─────────────────────────── CLI ──────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inferno trade-management auditor (research-only)"
    )
    parser.add_argument(
        "command", nargs="?", default="run", choices=["run", "status"],
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        if TRADE_MANAGEMENT_TEXT_FILE.exists():
            print(TRADE_MANAGEMENT_TEXT_FILE.read_text(encoding="utf-8"))
            return 0
        print("(no cached trade_management report)")
        return 0
    payload = build_trade_management()
    save_trade_management(payload)
    print(trade_management_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
