from __future__ import annotations

"""Inferno Slippage Estimator — quoted-spread math + limit-pricing cushion.

What it does:
    Reads the paper-execution and shadow-evidence ledgers and computes
    two distinct things per ticket and per strategy family:

      1. QUOTED LEG SPREADS (Roll 1984 effective-spread proxy). Real
         per-leg spread / mid measurements from the chain at strike-plan
         time. These reflect the option market itself.

      2. LIMIT-PRICING CUSHION. The gap between the strike selector's
         worst-case fill (entryLimit = sum of asks paid + bids received)
         and the theoretical mid-fill (sum of d_i · leg_mid_i). The
         strike selector deliberately quotes the limit at the worst-case
         fill so a limit order will cross the spread on every leg; the
         cushion is the conservatism baked into that policy. It is NOT
         realized slippage — that would require closed-outcome fill data,
         which doesn't exist on this desk yet.

What it does NOT do:
    - Touch the broker, the live book, or the approval queue.
    - Adjust any sizing rule, gate, or authority field.
    - Promote any strategy. Research-only, diagnostic-only.
    - Measure realized slippage (post-trade vs pre-trade marks). That
      requires outcome.exitValue + exit-side mids, neither of which is
      populated yet. The Hasbrouck (1991) decomposition lights up only
      when closed fills exist.

Strict contract: research-only, diagnostic-only, promotable=False.

## The math (see docs/PERFORMANCE_ATTRIBUTION.md §3)

Per leg, with bid B, ask A, mid M = (A+B)/2:

    quoted_spread          = A − B
    quoted_spread_pct      = (A − B) / M               (Roll 1984 proxy)

For a multi-leg ticket with leg mids m_i, per-leg directions d_i (+1 buy,
−1 sell), and the strike-selector-supplied net entryLimit L:

    sum_leg_mid_net  = Σ d_i · m_i             (theoretical mid-fill cost)
    limit_cushion    = L − sum_leg_mid_net     (worst-case − mid)
    limit_cushion_pct = limit_cushion / |sum_leg_mid_net|

A cushion of zero means the limit equals the mid (no spread crossed).
A cushion of 100% means the limit is 2× the mid (the strike selector
expects to pay through the spread on both legs).

NOTE: This v1 metric was originally labeled "entry slippage" — that name
was retired in the 2026-05 investigation that surfaced FTNT/ACMR-style
guaranteed-loss vertical-debit plans. The math is unchanged; the framing
is honest about what it actually measures.

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
HIGH_LIMIT_CUSHION_PCT = 0.10      # limit-pricing cushion above 10% of net is flagged


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
    limit_cushion = round(entry_limit - sum_signed_mid, 6)
    limit_cushion_pct = round(limit_cushion / denom, 6) if denom else None

    flags: list[str] = []
    if spread_pcts and max(spread_pcts) > WIDE_SPREAD_FLAG_PCT:
        flags.append("wide-leg-spread")
    if limit_cushion_pct is not None and abs(limit_cushion_pct) > HIGH_LIMIT_CUSHION_PCT:
        flags.append("high-limit-cushion")

    return {
        "usable": True,
        "legs": leg_reads,
        "sumLegMidNet": round(sum_signed_mid, 6),
        "entryLimit": entry_limit,
        # NOTE: limitCushion = entryLimit − Σ d_i · leg_mid_i. This is the
        # strike selector's worst-case-fill conservatism, NOT realized
        # slippage. Realized slippage would compare to actual fills, which
        # don't exist on this desk yet.
        "limitCushion": limit_cushion,
        "limitCushionPct": limit_cushion_pct,
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
    """Compute the anchor (quoted spread + limit cushion) for one family."""
    n = len(rows)
    spread_pcts = [r["avgLegSpreadPct"] for r in rows if r.get("avgLegSpreadPct") is not None]
    cushion_pcts = [
        abs(r["limitCushionPct"]) for r in rows if r.get("limitCushionPct") is not None
    ]
    verdict = "thin" if n < MIN_TICKETS_PER_FAMILY else "anchored"
    return {
        "ticketCount": n,
        "medianAvgLegSpreadPct": round(median(spread_pcts), 6) if spread_pcts else None,
        "medianLimitCushionPct": (
            round(median(cushion_pcts), 6) if cushion_pcts else None
        ),
        "maxLimitCushionPct": (
            round(max(cushion_pcts), 6) if cushion_pcts else None
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
            "highLimitCushionPct": HIGH_LIMIT_CUSHION_PCT,
        },
        "familyAnchors": table["familyAnchors"],
        "flaggedTickets": [
            {
                "ticketId": r["ticketId"],
                "ticker": r["ticker"],
                "family": r["family"],
                "limitCushionPct": r.get("limitCushionPct"),
                "maxLegSpreadPct": r.get("maxLegSpreadPct"),
                "flags": r.get("flags"),
            }
            for r in flagged[:20]
        ],
        "reminders": [
            "Anchors are research-only; broker submit stays OFF.",
            "Quoted leg spreads are Roll-1984 territory and real. The "
            "'limit cushion' is the strike selector's worst-case-fill "
            "conservatism — NOT realized slippage. Don't read it as a "
            "Hasbrouck adverse-selection cost.",
            "Realized slippage requires closed-outcome fills "
            "(outcome.exitValue). Until those exist, the Hasbrouck-1991 "
            "and Almgren-Chriss-2000 decompositions stay dormant.",
            "High limit-cushion on a family means the strike selector "
            "expects to cross the spread on every leg in that family. "
            "On wide-spread legs this can produce limits that exceed the "
            "spread's maximum payoff — see the FTNT/ACMR cases in the "
            "2026-05 investigation.",
        ],
        "citations": [
            "ROLL-1984",
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
        lines.append("STRATEGY-FAMILY ANCHORS (quoted spread + limit cushion)")
        lines.append("--------------------------------------------------------")
        lines.append(
            f"{'family':<22} {'n':>4} {'medSpread%':>11} "
            f"{'medCushion%':>12} {'maxCushion%':>12} {'flag':>5} {'verdict':<10}"
        )
        for fam in sorted(anchors.keys()):
            a = anchors[fam]
            def _pct(v):
                return f"{v * 100:.2f}" if isinstance(v, (int, float)) else "-"
            lines.append(
                f"{fam[:22]:<22} {a['ticketCount']:>4} "
                f"{_pct(a['medianAvgLegSpreadPct']):>11} "
                f"{_pct(a['medianLimitCushionPct']):>12} "
                f"{_pct(a['maxLimitCushionPct']):>12} "
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
                f"cushion={r.get('limitCushionPct')}  "
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
