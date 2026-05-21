from __future__ import annotations

"""Inferno Drawdown Protocol — rolling drawdown + Ulysses-contract sizing.

What it does:
    Builds a chronological equity curve from closed paper / shadow
    outcomes, computes the current drawdown depth, max drawdown,
    time-to-recovery on resolved drawdowns, Ulcer Index, and Calmar
    ratio. Maps the current depth onto the desk's pre-committed
    sizing-step-down table and emits a **research-only advisory**.

What it does NOT do:
    - Touch the broker, the live book, or any sizing surface that
      flows into authority or order entry.
    - Change risk-unit caps automatically.
    - Promote any strategy. Research-only, diagnostic-only.

Strict contract: research-only, diagnostic-only, promotable=False.

## The math (see docs/PORTFOLIO_CONSTRUCTION.md §5)

Let E_t be the equity (cumulative PnL) after the t-th closed outcome and
P_t = max_{s≤t} E_s the running peak. The drawdown at t is::

    DD_t = (E_t − P_t) / P_t        when P_t > 0, else 0

Max drawdown = min_t DD_t. Time-to-recovery for a resolved drawdown is
the number of closed outcomes between the peak that started it and the
first outcome that exceeded that peak again.

Ulcer Index (Martin 1989), squared drawdown average over the window::

    UI = √( (1/N) Σ_t (100·DD_t)² )

Calmar ratio (Young 1991)::

    Calmar = annualized_return / |max_drawdown|

For a fresh desk with <30 closed outcomes the Calmar number is noisy and
should be treated as "directionally correct" only.

## Sizing ladder (the Ulysses contract)

Drawdown depth ↦ recommended new-ticket size multiplier::

    0% to −5%   : 1.0   (full)
    −5% to −10% : 0.5
    −10% to −15%: 0.25
    −15% to −20%: 0.0   (no new positions; manage book only)
    < −20%      : 0.0   (full stop; review last 30 outcomes)

The advice is *strictly advisory*. The risk policy still owns the actual
gate. This module makes the operator's pre-committed protocol visible at
decision time so it cannot be quietly forgotten in a losing streak.

CLI::

    python3 inferno_drawdown_protocol.py             # run + persist
    python3 inferno_drawdown_protocol.py status      # show last memo
"""

import argparse
import math
from datetime import date, datetime
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


# ───────────────────────── file locations ──────────────────────────────

PAPER_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
SHADOW_LEDGER_FILE = DATA_DIR / "inferno_shadow_evidence.json"

DRAWDOWN_FILE = DATA_DIR / "inferno_drawdown_protocol.json"
DRAWDOWN_TEXT_FILE = REPORTS_DIR / "drawdown_protocol_latest.txt"

DRAWDOWN_STAGE = "drawdown-protocol-research-only"


# ───────────────────────── thresholds (Ulysses ladder) ──────────────────

SIZING_LADDER: tuple[tuple[float, float, str], ...] = (
    # (drawdown_depth_upper, size_multiplier, regime_label)
    # Tested in order; first match wins. depth is negative or zero.
    (0.0,  1.00, "normal"),
    (-0.05, 0.50, "first-cut"),
    (-0.10, 0.25, "deep-cut"),
    (-0.15, 0.00, "no-new-positions"),
    (-0.20, 0.00, "full-stop"),
)

MIN_OUTCOMES_FOR_CALMAR = 10
TRADING_DAYS_PER_YEAR = 252


# ───────────────────────── helpers (mirror Phase A) ─────────────────────


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


PNL_FIELDS = ("realizedPnl", "realised_pnl", "pnl", "outcomePnl", "outcome_pnl")
STATUS_CLOSED = {"closed", "exit", "exited", "outcome-closed", "shadow-closed"}


def _ticket_pnl(ticket: dict) -> float | None:
    for f in PNL_FIELDS:
        if f in ticket:
            v = _safe_float(ticket.get(f))
            if v is not None:
                return v
    return None


def _ticket_closed(ticket: dict) -> bool:
    if str(ticket.get("status", "")).lower() in STATUS_CLOSED:
        return True
    return _ticket_pnl(ticket) is not None


def _ticket_date(ticket: dict) -> str | None:
    """Best-effort close date for chronological ordering."""
    for key in ("closedAt", "exitAt", "reviewedAt", "tradeDate", "createdAt"):
        v = ticket.get(key)
        if v:
            return str(v)[:10]
    return None


# ───────────────────────── equity curve ─────────────────────────────────


def build_equity_curve(closed_tickets: list[dict]) -> list[dict[str, Any]]:
    """Return a chronological list of {date, ticker, pnl, equity, peak,
    drawdown}.

    Tickets without a usable date are placed at the end in stable order.
    """
    rows = []
    for t in closed_tickets:
        pnl = _ticket_pnl(t)
        if pnl is None:
            continue
        rows.append(
            {
                "date": _ticket_date(t),
                "ticker": t.get("ticker"),
                "ticketId": t.get("ticketId"),
                "pnl": pnl,
            }
        )
    # stable sort: dated first by date, undated kept at end in input order
    dated = [r for r in rows if r["date"]]
    undated = [r for r in rows if not r["date"]]
    dated.sort(key=lambda r: r["date"])
    ordered = dated + undated

    equity = 0.0
    peak = 0.0
    out: list[dict[str, Any]] = []
    for r in ordered:
        equity += float(r["pnl"])
        if equity > peak:
            peak = equity
        dd = (equity - peak) / peak if peak > 0 else 0.0
        out.append(
            {
                **r,
                "equity": round(equity, 6),
                "peak": round(peak, 6),
                "drawdown": round(dd, 6),
            }
        )
    return out


def max_drawdown(curve: list[dict[str, Any]]) -> float:
    if not curve:
        return 0.0
    return min((row["drawdown"] for row in curve), default=0.0)


def ulcer_index(curve: list[dict[str, Any]]) -> float:
    """Ulcer Index in percent-scaled units (Martin 1989)."""
    if not curve:
        return 0.0
    sq = sum((100.0 * row["drawdown"]) ** 2 for row in curve)
    return math.sqrt(sq / len(curve))


def time_to_recoveries(curve: list[dict[str, Any]]) -> list[int]:
    """For each resolved drawdown, return its length in outcomes.

    A "resolved drawdown" is a run of consecutive negative drawdowns
    starting from the moment a peak was made and ending at the next
    outcome whose equity strictly exceeds that peak. Tracks lengths only.
    """
    lengths: list[int] = []
    in_dd = False
    start_peak = 0.0
    run_len = 0
    for row in curve:
        if not in_dd and row["drawdown"] < 0:
            in_dd = True
            start_peak = row["peak"]
            run_len = 1
        elif in_dd:
            run_len += 1
            if row["equity"] > start_peak:
                lengths.append(run_len)
                in_dd = False
                start_peak = 0.0
                run_len = 0
    return lengths


def calmar_ratio(curve: list[dict[str, Any]]) -> float | None:
    """Annualized return / |max drawdown|. None if the window is too short
    or the drawdown is zero."""
    if len(curve) < MIN_OUTCOMES_FOR_CALMAR:
        return None
    dd = max_drawdown(curve)
    if dd >= 0:
        return None
    # Approximate annualization by treating the closed-outcome cadence
    # as roughly one trade per trading day. This is generous but honest;
    # the alternative (parse close dates) is sensitive to gaps.
    total_return = curve[-1]["equity"]
    days = len(curve)
    annualized = total_return * (TRADING_DAYS_PER_YEAR / days)
    return round(annualized / abs(dd), 4)


# ───────────────────────── sizing ladder ────────────────────────────────


def sizing_for_drawdown(depth: float) -> dict[str, Any]:
    """Return {multiplier, regime} for the given (signed, non-positive) depth.

    depth = 0 ↦ multiplier 1.0; depth ≤ −20% ↦ multiplier 0.0.
    """
    if depth >= 0:
        return {"multiplier": 1.0, "regime": "normal"}
    # Iterate downward through the ladder; pick the deepest matching bracket.
    multiplier = 1.0
    regime = "normal"
    for upper, mult, label in SIZING_LADDER:
        if depth <= upper:
            multiplier = mult
            regime = label
    return {"multiplier": multiplier, "regime": regime}


# ───────────────────────── ingestion ────────────────────────────────────


def _load_closed() -> list[dict]:
    closed: list[dict] = []
    for path in (PAPER_LEDGER_FILE, SHADOW_LEDGER_FILE):
        payload = load_json_file(path)
        if not isinstance(payload, dict):
            continue
        items = payload.get("items") or []
        if not isinstance(items, list):
            continue
        for it in items:
            if isinstance(it, dict) and _ticket_closed(it):
                closed.append(it)
    return closed


# ───────────────────────── builder ──────────────────────────────────────


def build_drawdown_protocol(now: Any | None = None) -> dict[str, Any]:
    closed = _load_closed()
    curve = build_equity_curve(closed)
    current_depth = curve[-1]["drawdown"] if curve else 0.0
    max_dd = max_drawdown(curve)
    ulcer = ulcer_index(curve)
    recoveries = time_to_recoveries(curve)
    calmar = calmar_ratio(curve)
    sizing = sizing_for_drawdown(current_depth)

    if not curve:
        verdict = "awaiting-closed-outcomes"
    elif current_depth <= -0.20:
        verdict = "full-stop-advised"
    elif current_depth <= -0.15:
        verdict = "no-new-positions-advised"
    elif current_depth <= -0.10:
        verdict = "deep-cut-advised"
    elif current_depth <= -0.05:
        verdict = "first-cut-advised"
    else:
        verdict = "normal-sizing"

    payload = {
        "version": 1,
        "stage": DRAWDOWN_STAGE,
        "promotable": False,
        "researchOnly": True,
        "authorityChanged": False,
        "generatedAt": str(now or local_now()),
        "verdict": verdict,
        "counts": {
            "closedOutcomes": len(curve),
            "resolvedDrawdowns": len(recoveries),
        },
        "metrics": {
            "currentDrawdown": round(current_depth, 6),
            "maxDrawdown": round(max_dd, 6),
            "ulcerIndex": round(ulcer, 4),
            "calmar": calmar,
            "currentEquity": round(curve[-1]["equity"], 6) if curve else 0.0,
            "peakEquity": round(curve[-1]["peak"], 6) if curve else 0.0,
            "medianRecoveryOutcomes": (
                sorted(recoveries)[len(recoveries) // 2] if recoveries else None
            ),
            "longestRecoveryOutcomes": max(recoveries) if recoveries else None,
        },
        "sizingAdvisory": sizing,
        "sizingLadder": [
            {"upperDepth": upper, "multiplier": mult, "regime": label}
            for upper, mult, label in SIZING_LADDER
        ],
        "thresholds": {
            "minOutcomesForCalmar": MIN_OUTCOMES_FOR_CALMAR,
            "tradingDaysPerYear": TRADING_DAYS_PER_YEAR,
        },
        "equityCurveTail": curve[-15:],
        "reminders": [
            "Sizing advisory is research-only. The risk policy still owns "
            "the actual gate on any ticket.",
            "Calmar is suppressed below 10 closed outcomes — the noise "
            "dominates the signal at this scale.",
            "Ulcer Index captures depth × duration. Two equal-depth "
            "drawdowns with different time-under-water will read differently.",
        ],
        "citations": [
            "YOUNG-1991",
            "MARTIN-1989",
            "SCHWAGER-MARKET-WIZARDS",
            "KELLY-1956",
            "CONSTANTINIDES-1986",
        ],
    }
    return payload


def save_drawdown_protocol(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(DRAWDOWN_FILE, payload)
    atomic_write_text(DRAWDOWN_TEXT_FILE, drawdown_protocol_text(payload))


# ───────────────────────── rendering ────────────────────────────────────


def drawdown_protocol_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Inferno Drawdown Protocol (research-only)")
    lines.append("")
    lines.append(f"Generated: {payload.get('generatedAt')}")
    lines.append(f"Stage:     {payload.get('stage')}")
    lines.append(f"Verdict:   {payload.get('verdict')}")
    counts = payload.get("counts") or {}
    metrics = payload.get("metrics") or {}
    sizing = payload.get("sizingAdvisory") or {}
    lines.append(
        f"Closed outcomes: {counts.get('closedOutcomes', 0)}  "
        f"resolved DDs: {counts.get('resolvedDrawdowns', 0)}"
    )
    lines.append("")
    def _pct(v):
        return f"{v * 100:.2f}%" if isinstance(v, (int, float)) else "-"
    lines.append("METRICS")
    lines.append("-------")
    lines.append(f"  Current drawdown: {_pct(metrics.get('currentDrawdown'))}")
    lines.append(f"  Max drawdown:     {_pct(metrics.get('maxDrawdown'))}")
    lines.append(f"  Ulcer Index:      {metrics.get('ulcerIndex')}")
    lines.append(f"  Calmar:           {metrics.get('calmar')}")
    lines.append(f"  Current equity:   {metrics.get('currentEquity')}")
    lines.append(f"  Peak equity:      {metrics.get('peakEquity')}")
    lines.append(
        f"  Median recovery:  {metrics.get('medianRecoveryOutcomes')} outcomes"
    )
    lines.append(
        f"  Longest recovery: {metrics.get('longestRecoveryOutcomes')} outcomes"
    )
    lines.append("")
    lines.append("SIZING ADVISORY (research-only)")
    lines.append("-------------------------------")
    lines.append(f"  Regime:     {sizing.get('regime')}")
    lines.append(f"  Multiplier: {sizing.get('multiplier')}")
    lines.append("")
    lines.append("Reminders:")
    for item in payload.get("reminders") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


# ───────────────────────── CLI ──────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Research-only drawdown protocol + Ulysses-contract sizing ladder. "
            "See docs/PORTFOLIO_CONSTRUCTION.md §5."
        )
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=("run", "status"),
        help="run = build + persist; status = print last artifact.",
    )
    args = parser.parse_args(argv)

    if args.command == "status":
        existing = load_json_file(DRAWDOWN_FILE) or {}
        print(drawdown_protocol_text(existing))
        return 0

    payload = build_drawdown_protocol()
    save_drawdown_protocol(payload)
    print(drawdown_protocol_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
