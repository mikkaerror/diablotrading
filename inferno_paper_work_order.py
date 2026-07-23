from __future__ import annotations

"""Paper work-order renderer (research-only).

The desk's single binding constraint is closed, scored paper outcomes.
The engine already scores candidates and the strike selector already
resolves each one into a concrete, ready-to-key multi-leg order --
specific option symbols, strikes, an estimated net debit, and the exact
max loss. But nothing surfaces that order to the operator. The
operator-facing reports (fast-paper cohort, evidence loop, ``./inferno
today``) show only ``ticker + strategy + maxLoss``. So the person who has
to actually stage the paper trade in thinkorswim paperMoney is handed an
abstraction and left to reverse-engineer the legs by hand -- and that
friction is a large part of why the promotion gate has sat near zero
scored outcomes for weeks.

This module removes that friction and nothing more. It reads the strike
selector's already-computed plan (``inferno_strike_plan.json``) and
renders, per operator-routable candidate, a clean order ticket the
operator can read straight into paperMoney: each leg as
``BUY_TO_OPEN +1 CHKP 2026-08-21 130 CALL``, the net debit limit, the
resulting max loss / max profit / break-even, and a plain instruction.

It is deliberately inert on authority:

- It stages nothing. The operator keys every order in manually and
  confirms it. Unattended agents must never stage, approve, close, or
  promote a paper ticket -- this module respects that rail and only
  renders what already exists.
- It computes no new strikes and fetches no market data. It is a pure
  join-and-render over the strike plan, so it cannot invent an order.
- It changes no risk constant, eligibility, or broker/authority state.

Citations (light): The bottleneck framing is Goldratt's Theory of
Constraints (THEORY-CONSTRAINTS-GOLDRATT-1984) -- lift the constraint
(operator staging throughput), not the non-constraints. The 30-outcome
promotion floor is the desk's own decision-rule, not a published
threshold.
"""

import argparse
import json
from typing import Any

from inferno_config import MAX_SINGLE_TICKET_DOLLARS, local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


STRIKE_PLAN_FILE = DATA_DIR / "inferno_strike_plan.json"
PAPER_EVIDENCE_LOOP_FILE = DATA_DIR / "inferno_paper_evidence_loop.json"
WORK_ORDER_FILE = DATA_DIR / "inferno_paper_work_order.json"
WORK_ORDER_TEXT_FILE = REPORTS_DIR / "paper_work_order_latest.txt"

WORK_ORDER_STAGE = "paper-work-order-research-only"

# thinkorswim keys spread legs as a single order; render buy/sell as the
# signed quantity the operator types on each leg row.
_INSTRUCTION_SIGN = {
    "BUY_TO_OPEN": "+",
    "BUY_TO_CLOSE": "+",
    "SELL_TO_OPEN": "-",
    "SELL_TO_CLOSE": "-",
}


def text(value: Any) -> str:
    """Normalize arbitrary values into trimmed text."""
    return str(value or "").strip()


def _money(value: Any) -> str:
    """Render a dollar figure, or a placeholder when it is missing."""
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _operator_routable_tickers(evidence_loop: dict[str, Any] | None) -> list[str]:
    """Tickers the evidence loop flagged to route to the operator now."""
    if not isinstance(evidence_loop, dict):
        return []
    # The evidence loop publishes the route-now set as ``stageableTickers``.
    routable = (
        evidence_loop.get("stageableTickers")
        or evidence_loop.get("operatorRoutableTickers")
        or evidence_loop.get("operatorRoutable")
    )
    if isinstance(routable, list):
        return [text(t).upper() for t in routable if text(t)]
    return []


def _leg_line(leg: dict[str, Any]) -> dict[str, Any]:
    """Render one option leg into an operator-readable row and keep raw facts."""
    instruction = text(leg.get("instruction")).upper()
    sign = _INSTRUCTION_SIGN.get(instruction, "")
    put_call = text(leg.get("putCall")).upper() or "?"
    strike = leg.get("strike")
    expiration = text(leg.get("expiration"))
    mid = leg.get("mid")
    strike_text = f"{float(strike):g}" if isinstance(strike, (int, float)) else "?"
    mid_text = f" (mid {float(mid):.2f})" if isinstance(mid, (int, float)) else ""
    return {
        "instruction": instruction or "?",
        "quantitySigned": f"{sign}1" if sign else "1",
        "symbol": text(leg.get("symbol")),
        "expiration": expiration,
        "strike": strike,
        "putCall": put_call,
        "mid": mid,
        "line": (
            f"{(instruction or '?'):<13} {sign or ' '}1  "
            f"{text(leg.get('symbol')) or '?'}  "
            f"{expiration} {strike_text} {put_call}{mid_text}"
        ),
    }


def _stageable_reason(item: dict[str, Any], strike_plan: dict[str, Any] | None) -> str:
    """Explain why a candidate is not yet a keyable order, if so."""
    if not isinstance(strike_plan, dict):
        return "no resolved strike plan for this candidate yet"
    legs = strike_plan.get("legs")
    if not isinstance(legs, list) or not legs:
        return "strike plan has no legs"
    missing = [
        i + 1
        for i, leg in enumerate(legs)
        if not text(leg.get("symbol")) or leg.get("strike") is None
    ]
    if missing:
        return f"leg(s) {missing} missing symbol or strike"
    if strike_plan.get("estimatedDebit") is None and strike_plan.get("estimatedCredit") is None:
        return "no estimated net price"
    return ""


def build_work_order(
    strike_plan_report: dict[str, Any] | None = None,
    evidence_loop: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Join operator-routable candidates with their resolved legs.

    Reads only already-computed artifacts. Every order rendered here was
    priced by the strike selector; this function never selects a strike or
    fetches a quote.
    """
    if strike_plan_report is None:
        strike_plan_report = load_json_file(STRIKE_PLAN_FILE)
    if evidence_loop is None:
        evidence_loop = load_json_file(PAPER_EVIDENCE_LOOP_FILE)

    generated_at = local_now().isoformat()
    routable = set(_operator_routable_tickers(evidence_loop))

    if not isinstance(strike_plan_report, dict) or not strike_plan_report.get("items"):
        return {
            "generatedAt": generated_at,
            "stage": WORK_ORDER_STAGE,
            "researchOnly": True,
            "promotable": False,
            "authorityChanged": False,
            "verdict": "awaiting-strike-plan",
            "message": (
                "No strike plan available yet. Run the strike cycle so candidates "
                "resolve into concrete legs, then rebuild the work order."
            ),
            "sourceStrikePlanGeneratedAt": None,
            "orderCount": 0,
            "stageableCount": 0,
            "orders": [],
            "citations": ["THEORY-CONSTRAINTS-GOLDRATT-1984"],
        }

    orders: list[dict[str, Any]] = []
    for item in strike_plan_report.get("items") or []:
        ticker = text(item.get("ticker") or item.get("symbol")).upper()
        strike_plan = item.get("strikePlan") if isinstance(item.get("strikePlan"), dict) else None
        reason = _stageable_reason(item, strike_plan)
        stageable = reason == ""
        legs = [_leg_line(leg) for leg in (strike_plan or {}).get("legs", [])] if strike_plan else []

        max_loss = (strike_plan or {}).get("estimatedMaxLoss")
        # Read the operator-set single-ticket cap and flag violations. This
        # only *reads* MAX_SINGLE_TICKET_DOLLARS; it never changes it. A cap
        # breach does not block keying the order mechanically, but it does
        # mean the order is not sized for this account, so it is reported and
        # de-prioritised rather than silently listed alongside safe orders.
        within_cap = (
            isinstance(max_loss, (int, float)) and float(max_loss) <= MAX_SINGLE_TICKET_DOLLARS
        )

        orders.append(
            {
                "ticker": ticker,
                "strategy": text((strike_plan or {}).get("strategy") or item.get("setupRec")),
                "direction": text((strike_plan or {}).get("direction")),
                "expiration": text((strike_plan or {}).get("expiration") or item.get("expiration")),
                "legs": legs,
                "estimatedDebit": (strike_plan or {}).get("estimatedDebit"),
                "estimatedCredit": (strike_plan or {}).get("estimatedCredit"),
                "estimatedMaxLoss": max_loss,
                "estimatedMaxProfit": (strike_plan or {}).get("estimatedMaxProfit"),
                "breakEven": (strike_plan or {}).get("breakEven"),
                "width": (strike_plan or {}).get("width"),
                "underlyingPrice": item.get("price") or item.get("sourcePrice"),
                "routeNow": ticker in routable,
                "approvalStatus": text(item.get("approvalStatus")) or "pending",
                "intentStatus": text(item.get("intentStatus")),
                "stageable": stageable,
                "notStageableReason": reason,
                "singleTicketCap": MAX_SINGLE_TICKET_DOLLARS,
                "withinSingleTicketCap": within_cap,
            }
        )

    # Order: route-now + within-cap + keyable first; oversized and blocked last.
    orders.sort(
        key=lambda o: (
            not (o["routeNow"] and o["withinSingleTicketCap"]),
            not o["withinSingleTicketCap"],
            not o["stageable"],
            o["ticker"],
        )
    )
    stageable_count = sum(1 for o in orders if o["stageable"])
    ready_count = sum(1 for o in orders if o["stageable"] and o["withinSingleTicketCap"])
    oversized_count = sum(1 for o in orders if o["stageable"] and not o["withinSingleTicketCap"])

    if ready_count:
        verdict = "orders-ready"
    elif stageable_count:
        verdict = "orders-oversized"
    else:
        verdict = "no-stageable-orders"
    return {
        "generatedAt": generated_at,
        "stage": WORK_ORDER_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "verdict": verdict,
        "message": (
            f"{ready_count} of {len(orders)} candidate(s) are keyable and within your "
            f"{_money(MAX_SINGLE_TICKET_DOLLARS)} single-ticket cap"
            + (
                f"; {oversized_count} keyable order(s) exceed the cap and are not sized "
                "for this account."
                if oversized_count
                else "."
            )
            + " Operator stages and confirms each manually; nothing is staged, "
            "approved, or promoted here."
        ),
        "sourceStrikePlanGeneratedAt": text(strike_plan_report.get("generatedAt")) or None,
        "orderCount": len(orders),
        "stageableCount": stageable_count,
        "readyCount": ready_count,
        "oversizedCount": oversized_count,
        "singleTicketCap": MAX_SINGLE_TICKET_DOLLARS,
        "orders": orders,
        "citations": ["THEORY-CONSTRAINTS-GOLDRATT-1984"],
    }


def _order_block(order: dict[str, Any]) -> list[str]:
    """Render one order ticket into operator-readable lines."""
    header_bits = [order["ticker"], order.get("strategy") or "?"]
    if order.get("direction"):
        header_bits.append(f"({order['direction']})")
    if order.get("expiration"):
        header_bits.append(f"exp {order['expiration']}")
    flags = []
    if order.get("routeNow"):
        flags.append("ROUTE NOW")
    if order.get("stageable") and not order.get("withinSingleTicketCap"):
        flags.append(f"OVER {_money(order.get('singleTicketCap'))} CAP")
    flag = f"  <-- {' / '.join(flags)}" if flags else ""
    lines = [f"{' | '.join(b for b in header_bits if b)}{flag}"]

    if not order["stageable"]:
        lines.append(f"    not keyable yet: {order['notStageableReason']}")
        return lines

    for leg in order["legs"]:
        lines.append(f"    {leg['line']}")

    if order.get("estimatedDebit") is not None:
        net = f"net debit ~{_money(order['estimatedDebit'])}"
    elif order.get("estimatedCredit") is not None:
        net = f"net credit ~{_money(order['estimatedCredit'])}"
    else:
        net = "net price n/a"
    econ = (
        f"    {net}  |  max loss {_money(order.get('estimatedMaxLoss'))}"
        f"  |  max profit {_money(order.get('estimatedMaxProfit'))}"
    )
    if isinstance(order.get("breakEven"), (int, float)):
        econ += f"  |  break-even {float(order['breakEven']):g}"
    lines.append(econ)

    if order.get("stageable") and not order.get("withinSingleTicketCap"):
        lines.append(
            f"    NOT SIZED FOR THIS ACCOUNT: max loss exceeds the "
            f"{_money(order.get('singleTicketCap'))} single-ticket cap."
        )

    debit = order.get("estimatedDebit")
    limit_hint = f" limit @ net debit {_money(debit)}," if debit is not None else ""
    lines.append(
        f"    -> in paperMoney: key as one spread order,{limit_hint} DAY; "
        f"approval status: {order.get('approvalStatus')}"
    )
    return lines


def work_order_text(payload: dict[str, Any]) -> str:
    """Render the work-order payload into a plain-text operator sheet."""
    lines = [
        "Inferno Paper Work Order (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Source strike plan: {payload.get('sourceStrikePlanGeneratedAt') or 'none'}",
        "",
        "Safety: this sheet stages nothing. You key each order into thinkorswim",
        "paperMoney yourself and confirm it. No authority, risk, or broker state",
        "changes here; broker submit and live trading remain OFF.",
        "",
        payload.get("message", ""),
        "",
    ]

    orders = payload.get("orders") or []
    if not orders:
        lines.append("(no candidates with resolved legs; run the strike cycle first)")
        return "\n".join(lines).rstrip() + "\n"

    lines.append(
        f"Orders ({payload.get('readyCount', 0)} ready within cap / "
        f"{payload.get('stageableCount', 0)} keyable / {payload.get('orderCount', 0)} total):"
    )
    lines.append("")
    for order in orders:
        lines.extend(_order_block(order))
        lines.append("")

    lines.append("After you fill an order in paperMoney, record the execution fact so the")
    lines.append("evidence loop can score it toward the 30-outcome promotion gate.")
    return "\n".join(lines).rstrip() + "\n"


def save_work_order(payload: dict[str, Any]) -> None:
    """Persist the work-order artifact and its text rendering."""
    ensure_dirs()
    atomic_write_json(WORK_ORDER_FILE, payload)
    atomic_write_text(WORK_ORDER_TEXT_FILE, work_order_text(payload))


def parse_args() -> argparse.Namespace:
    """Parse CLI args for the work-order renderer."""
    parser = argparse.ArgumentParser(
        description="Inferno paper work-order renderer (research-only)"
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    """Build and emit the work order, or print the last cached one."""
    args = parse_args()
    if args.command == "status" and WORK_ORDER_TEXT_FILE.exists():
        print(WORK_ORDER_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_work_order()
    save_work_order(payload)
    print(work_order_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
