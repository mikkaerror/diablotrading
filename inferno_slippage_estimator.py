from __future__ import annotations

"""Inferno Slippage Estimator — execution-gap math for closed/staged tickets.

What it does:
    Reads the paper-execution and shadow-evidence ledgers, computes
    quoted-spread + effective-spread metrics per ticket and per strategy
    family, and produces a research-only slippage anchor table. The
    anchor table is what later modules (capital readiness, conviction
    audit, risk policy) can use to penalize a thesis whose advertised
    edge would not survive its own family's average fill friction.

What it does NOT do:
    - Touch the broker, the live book, or the approval queue.
    - Adjust any sizing rule, gate, or authority field.
    - Promote any strategy. Research-only, diagnostic-only.

Strict contract: research-only, diagnostic-only, promotable=False.

## The math (see docs/PERFORMANCE_ATTRIBUTION.md §3)

Per leg, with bid B, ask A, mid M = (A+B)/2, fill price F, instruction
direction d ∈ {+1 buy, −1 sell}:

    quoted_spread          = A − B
    quoted_spread_pct      = (A − B) / M               (Roll 1984 proxy)
    effective_half_spread  = d · (F − M)               (Hasbrouck 1991)
    effective_spread_pct   = 2 · |F − M| / M

For a multi-leg ticket with leg mids m_i and per-leg directions d_i and a
single net entryLimit L, we decompose:

    sum_leg_mid_net  = Σ d_i · m_i
    entry_slippage   = L − sum_leg_mid_net             (debit positive)
    entry_slip_pct   = entry_slippage / |sum_leg_mid_net|

When exit data is present (outcome.exitValue), the analogous exit
slippage uses the leg mids captured on the ticket at exit; v1 reuses
entry leg mids as the best available proxy and explicitly tags the
result so callers do not over-trust it.

Almgren-Chriss (2000) optimal-execution framing is the long-run anchor:
the *temporary* cost (eaten today) versus the *permanent* cost (price
impact). For a $500-ticket book this distinction collapses — we live
entirely in temporary cost territory.

CLI::

    python3 inferno_slippage_estimator.py             # run + persist
    python3 inferno_slippage_estimator.py status      # show last memo
"""

import argparse
import math
from collections import defaultdict
from statistics import median
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


# ───────────────────────── file locations ──────────────────────────────

PAPER_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
SHADOW_LEDGER_FILE = DATA_DIR / "inferno_shadow_evidence.json"

SLIPPAGE_FILE = DATA_DIR / "inferno_slippage_estimator.json"
SLIPPAGE_TEXT_FILE = REPORTS_DIR / "slippage_estimator_latest.txt"

SLIPPAGE_STAGE = "slippage-estimator-research-only"


# ───────────────────────── thresholds ──────────────────────────────────

MIN_TICKETS_PER_FAMILY = 10        # below this, anchor verdict is "thin"
WIDE_SPREAD_FLAG_PCT = 0.25        # quoted_spread_pct above this is flagged
HIGH_ENTRY_SLIP_FLAG_PCT = 0.10    # entry slippage above 10% of net is flagged


# ───────────────────────── helpers ──────────────────────────────────────


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _leg_direction(leg: dict[str, Any]) -> int | None:
    """+1 for BUY, −1 for SELL. Unknown instructions return None."""
    instr = str(leg.get("instruction") or "").upper()
    if instr.startswith("BUY"):
        return 1
    if instr.startswith("SELL"):
        return -1
    return None


def _leg_quoted_spread(leg: dict[str, Any]) -> dict[str, float | None]:
    bid = _safe_float(leg.get("bid"))
    ask = _safe_float(leg.get("ask"))
    mid = _safe_float(leg.get("mid"))
    if mid is None and bid is not None and ask is not None:
        mid = round((bid + ask) / 2.0, 4)
    if bid is None or ask is None or mid is None or mid <= 0:
        return {"spread": None, "spreadPct": None, "mid": mid}
    spread = round(ask - bid, 4)
    return {
        "spread": spread,
        "spreadPct": round(spread / mid, 6),
        "mid": mid,
    }


def _strategy_family(ticket: dict[str, Any]) -> str:
    """Bucket per the same taxonomy used by outcome attribution.

    Kept duplicated here so the slippage module can stand alone in tests
    without importing from attribution; centralizing it is a refactor for
    a future sweep. Accepts both ``strategy`` (snake_case ledger field) and
    ``setupRec`` (display string) and normalizes underscores so patterns
    like ``call_debit_spread`` and ``credit spread`` both classify.
    """
    raw = str(ticket.get("strategy") or ticket.get("setupRec") or "").strip().lower()
    if not raw:
        return "Unknown"
    name = raw.replace("_", " ")
    if "straddle" in name:
        return "Long Straddle"
    if "strangle" in name:
        return "Long Strangle"
    if "iron condor" in name:
        return "Iron Condor"
    if "butterfly" in name:
        return "Butterfly"
    if "calendar" in name or "diagonal" in name:
        return "Calendar / Diagonal"
    if "credit" in name:
        return "Credit Spread"
    if "debit" in name or ("vertical" in name and "call" in name) or ("vertical" in name and "put" in name):
        return "Vertical Debit"
    if "vertical" in name:
        return "Vertical"
    return "Unknown"


def _ticket_entry_slippage(ticket: dict[str, Any]) -> dict[str, Any]:
    """Compute the per-ticket entry-slippage decomposition.

    Returns a dict with:
        legs: list of per-leg quoted-spread reads
        sumLegMidNet: signed sum (debit positive) of d_i · m_i
        entryLimit: the desk's intended fill price
        entrySlippage: entryLimit − sumLegMidNet
        entrySlipPct: entrySlippage / |sumLegMidNet|
        flags: list of per-ticket flags
        usable: True only when every leg had bid/ask/mid AND a direction
    """
    legs = ticket.get("legs") or []
    if not isinstance(legs, list) or not legs:
        return {"usable": False, "reason": "no-legs"}

    leg_reads: list[dict[str, Any]] = []
    sum_signed_mid = 0.0
    spread_pcts: list[float] = []
    any_missing = False
    for leg in legs:
        spread = _leg_quoted_spread(leg)
        direction = _leg_direction(leg)
        usable = (
            spread["mid"] is not None
            and spread["spread"] is not None
            and direction is not None
        )
        if not usable:
            any_missing = True
        if usable:
            sum_signed_mid += direction * spread["mid"]
            spread_pcts.append(spread["spreadPct"])
        leg_reads.append(
            {
                "instruction": leg.get("instruction"),
                "putCall": leg.get("putCall"),
                "strike": leg.get("strike"),
                "expiration": leg.get("expiration"),
                "direction": direction,
                "bid": _safe_float(leg.get("bid")),
                "ask": _safe_float(leg.get("ask")),
                "mid": spread["mid"],
                "spread": spread["spread"],
                "spreadPct": spread["spreadPct"],
            }
        )

    entry_limit = _safe_float(ticket.get("entryLimit"))
    if any_missing or entry_limit is None:
        return {
            "usable": False,
            "reason": "missing-leg-data" if any_missing else "missing-entry-limit",
            "legs": leg_reads,
        }

    # entryLimit on a debit ticket is positive; on a credit ticket the
    # convention varies. We treat |sum_signed_mid| as the denominator so
    # the percentage stays interpretable in both directions.
    denom = abs(sum_signed_mid) if sum_signed_mid != 0 else None
    entry_slip = round(entry_limit - sum_signed_mid, 6)
    entry_slip_pct = round(entry_slip / denom, 6) if denom else None

    flags: list[str] = []
    if spread_pcts and max(spread_pcts) > WIDE_SPREAD_FLAG_PCT:
        flags.append("wide-leg-spread")
    if entry_slip_pct is not None and abs(entry_slip_pct) > HIGH_ENTRY_SLIP_FLAG_PCT:
        flags.append("high-entry-slippage")

    return {
        "usable": True,
        "legs": leg_reads,
        "sumLegMidNet": round(sum_signed_mid, 6),
        "entryLimit": entry_limit,
        "entrySlippage": entry_slip,
        "entrySlipPct": entry_slip_pct,
        "maxLegSpreadPct": round(max(spread_pcts), 6) if spread_pcts else None,
        "avgLegSpreadPct": (
            round(sum(spread_pcts) / len(spread_pcts), 6) if spread_pcts else None
        ),
        "flags": flags,
    }


# ───────────────────────── ingestion ────────────────────────────────────


def _load_tickets() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in (PAPER_LEDGER_FILE, SHADOW_LEDGER_FILE):
        payload = load_json_file(path)
        if not isinstance(payload, dict):
            continue
        items = payload.get("items") or []
        if not isinstance(items, list):
            continue
        for it in items:
            if isinstance(it, dict):
                out.append(it)
    return out


# ───────────────────────── aggregation ──────────────────────────────────


def _family_anchor(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the slippage anchor for one strategy family."""
    n = len(rows)
    spread_pcts = [r["avgLegSpreadPct"] for r in rows if r.get("avgLegSpreadPct") is not None]
    entry_slip_pcts = [
        abs(r["entrySlipPct"]) for r in rows if r.get("entrySlipPct") is not None
    ]
    verdict = "thin" if n < MIN_TICKETS_PER_FAMILY else "anchored"
    return {
        "ticketCount": n,
        "medianAvgLegSpreadPct": round(median(spread_pcts), 6) if spread_pcts else None,
        "medianEntrySlipPct": (
            round(median(entry_slip_pcts), 6) if entry_slip_pcts else None
        ),
        "maxEntrySlipPct": (
            round(max(entry_slip_pcts), 6) if entry_slip_pcts else None
        ),
        "flaggedCount": sum(1 for r in rows if r.get("flags")),
        "verdict": verdict,
    }


def compute_slippage_table(tickets: list[dict[str, Any]]) -> dict[str, Any]:
    """Return per-ticket reads + per-family anchors."""
    per_ticket: list[dict[str, Any]] = []
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in tickets:
        ticket_id = t.get("ticketId") or t.get("ticker")
        family = _strategy_family(t)
        slip = _ticket_entry_slippage(t)
        row = {
            "ticketId": ticket_id,
            "ticker": t.get("ticker"),
            "strategy": t.get("strategy"),
            "family": family,
            "status": t.get("status"),
            **slip,
        }
        per_ticket.append(row)
        if slip.get("usable"):
            by_family[family].append(slip)

    family_anchors = {fam: _family_anchor(rows) for fam, rows in by_family.items()}
    return {"perTicket": per_ticket, "familyAnchors": family_anchors}


# ───────────────────────── builder ──────────────────────────────────────


def build_slippage_estimator(now: Any | None = None) -> dict[str, Any]:
    tickets = _load_tickets()
    table = compute_slippage_table(tickets)

    usable_rows = [r for r in table["perTicket"] if r.get("usable")]
    anchored_families = [
        fam for fam, anchor in table["familyAnchors"].items()
        if anchor["verdict"] == "anchored"
    ]
    flagged = [r for r in usable_rows if r.get("flags")]

    if not usable_rows:
        verdict = "no-usable-tickets"
    elif anchored_families:
        verdict = "anchors-ready"
    else:
        verdict = "thin-anchors"

    payload = {
        "version": 1,
        "stage": SLIPPAGE_STAGE,
        "promotable": False,
        "researchOnly": True,
        "authorityChanged": False,
        "generatedAt": str(now or local_now()),
        "verdict": verdict,
        "counts": {
            "tickets": len(table["perTicket"]),
            "usableTickets": len(usable_rows),
            "anchoredFamilies": len(anchored_families),
            "flaggedTickets": len(flagged),
        },
        "thresholds": {
            "minTicketsPerFamily": MIN_TICKETS_PER_FAMILY,
            "wideSpreadFlagPct": WIDE_SPREAD_FLAG_PCT,
            "highEntrySlipFlagPct": HIGH_ENTRY_SLIP_FLAG_PCT,
        },
        "familyAnchors": table["familyAnchors"],
        "flaggedTickets": [
            {
                "ticketId": r["ticketId"],
                "ticker": r["ticker"],
                "family": r["family"],
                "entrySlipPct": r.get("entrySlipPct"),
                "maxLegSpreadPct": r.get("maxLegSpreadPct"),
                "flags": r.get("flags"),
            }
            for r in flagged[:20]
        ],
        "reminders": [
            "Slippage anchors are research-only; broker submit stays OFF.",
            "Wide quoted spreads + high entry slippage are warnings, not "
            "blocks. The risk policy still owns the go/no-go on any ticket.",
            "v1 uses entry leg mids only; exit-side decomposition lights "
            "up when outcome.exitValue and exit-side mids are recorded.",
        ],
        "citations": [
            "ROLL-1984",
            "HASBROUCK-1991",
            "ALMGREN-CHRISS-2000",
            "KYLE-1985",
        ],
    }
    return payload


def save_slippage_estimator(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(SLIPPAGE_FILE, payload)
    atomic_write_text(SLIPPAGE_TEXT_FILE, slippage_estimator_text(payload))


# ───────────────────────── rendering ────────────────────────────────────


def slippage_estimator_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Inferno Slippage Estimator (research-only)")
    lines.append("")
    lines.append(f"Generated: {payload.get('generatedAt')}")
    lines.append(f"Stage:     {payload.get('stage')}")
    lines.append(f"Verdict:   {payload.get('verdict')}")
    counts = payload.get("counts") or {}
    lines.append(
        f"Tickets: {counts.get('tickets', 0)}  "
        f"usable: {counts.get('usableTickets', 0)}  "
        f"anchored families: {counts.get('anchoredFamilies', 0)}  "
        f"flagged: {counts.get('flaggedTickets', 0)}"
    )
    lines.append("")
    anchors = payload.get("familyAnchors") or {}
    if anchors:
        lines.append("STRATEGY-FAMILY SLIPPAGE ANCHORS")
        lines.append("---------------------------------")
        lines.append(
            f"{'family':<22} {'n':>4} {'medSpread%':>11} "
            f"{'medSlip%':>10} {'maxSlip%':>10} {'flag':>5} {'verdict':<10}"
        )
        for fam in sorted(anchors.keys()):
            a = anchors[fam]
            def _pct(v):
                return f"{v * 100:.2f}" if isinstance(v, (int, float)) else "-"
            lines.append(
                f"{fam[:22]:<22} {a['ticketCount']:>4} "
                f"{_pct(a['medianAvgLegSpreadPct']):>11} "
                f"{_pct(a['medianEntrySlipPct']):>10} "
                f"{_pct(a['maxEntrySlipPct']):>10} "
                f"{a['flaggedCount']:>5} "
                f"{a['verdict']:<10}"
            )
        lines.append("")
    flagged = payload.get("flaggedTickets") or []
    if flagged:
        lines.append("FLAGGED TICKETS (first 20)")
        lines.append("--------------------------")
        for r in flagged:
            lines.append(
                f"- {r.get('ticker')} ({r.get('family')}): "
                f"slip={r.get('entrySlipPct')}  "
                f"maxLegSpread={r.get('maxLegSpreadPct')}  "
                f"flags={','.join(r.get('flags') or [])}"
            )
        lines.append("")
    lines.append("Reminders:")
    for item in payload.get("reminders") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


# ───────────────────────── CLI ──────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Research-only slippage estimator. "
            "See docs/PERFORMANCE_ATTRIBUTION.md §3."
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
        existing = load_json_file(SLIPPAGE_FILE) or {}
        print(slippage_estimator_text(existing))
        return 0

    payload = build_slippage_estimator()
    save_slippage_estimator(payload)
    print(slippage_estimator_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
