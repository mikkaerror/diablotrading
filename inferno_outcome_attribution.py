from __future__ import annotations

"""Inferno Outcome Attribution — Brinson-style decomposition of closed outcomes.

What it does:
    For each closed paper / shadow outcome, decompose realised PnL into
    allocation effect (did we pick the right strategy family?), selection
    effect (did we pick the right ticket inside the family?), and the
    Eckhardt comfortable-win flag (was the winner the "feels good" trade?).

What it does NOT do:
    - Approve, reject, or size any trade.
    - Mutate the live book, approval queue, or authority manifest.
    - Touch any TOS, paper, or broker write surface.
    - Promote any strategy. Research-only, diagnostic-only.

Strict contract: research-only, diagnostic-only, promotable=False.

## The math (see docs/PERFORMANCE_ATTRIBUTION.md §1)

Brinson-Hood-Beebower (1986) decomposition, adapted for a small options desk
where "sector" = strategy family and the "benchmark" = naive equal-weight
slate of all stageable tickets in the same cycle::

    allocation_j  = (wₚ,ⱼ − wᵦ,ⱼ) · Rᵦ,ⱼ
    selection_j   =  wᵦ,ⱼ · (Rₚ,ⱼ − Rᵦ,ⱼ)
    interaction_j = (wₚ,ⱼ − wᵦ,ⱼ) · (Rₚ,ⱼ − Rᵦ,ⱼ)

    active_return = Σⱼ (allocation_j + selection_j + interaction_j)

The Eckhardt-MW93 comfortable-win flag fires on a winner when the trade was
*consensus-aligned*: high readiness (≥80), high conviction tag, AND in the
dominant sector / setup of the slate. Comfortable wins are flagged because
the literature (Eckhardt) and the master traders (Druckenmiller, Marks)
both warn that the comfortable trade is usually the wrong lesson.

CLI::

    python3 inferno_outcome_attribution.py             # run + persist
    python3 inferno_outcome_attribution.py status      # print last artifact
"""

import argparse
from collections import Counter, defaultdict
from typing import Any, Iterable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


# ───────────────────────── file locations ──────────────────────────────

SHADOW_LEDGER_FILE = DATA_DIR / "inferno_shadow_evidence.json"
PAPER_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"

ATTRIBUTION_FILE = DATA_DIR / "inferno_outcome_attribution.json"
ATTRIBUTION_TEXT_FILE = REPORTS_DIR / "outcome_attribution_latest.txt"

ATTRIBUTION_STAGE = "outcome-attribution-research-only"


# ───────────────────────── thresholds + constants ──────────────────────

# When a ticket's readiness is at or above this floor AND it has a
# "supported" / "ready" conviction state AND it sits in the dominant
# slate family, a *winning* outcome is flagged as a comfortable win.
COMFORTABLE_READINESS_FLOOR = 80
COMFORTABLE_DOMINANT_SHARE_FLOOR = 0.50

# Per-ticket PnL fields we recognise (we read whichever is present).
PNL_FIELDS = ("realizedPnl", "realised_pnl", "pnl", "outcomePnl", "outcome_pnl")
STATUS_CLOSED = {"closed", "exit", "exited", "outcome-closed", "shadow-closed"}


# ───────────────────────── helpers ─────────────────────────────────────


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _ticket_pnl(ticket: dict) -> float | None:
    for field in PNL_FIELDS:
        if field in ticket:
            v = _safe_float(ticket.get(field))
            if v is not None:
                return v
    return None


def _ticket_closed(ticket: dict) -> bool:
    status = str(ticket.get("status", "")).lower()
    if status in STATUS_CLOSED:
        return True
    return _ticket_pnl(ticket) is not None


def _strategy_family(ticket: dict) -> str:
    """Bucket the ticket's strategy into a family label."""
    raw = str(
        ticket.get("strategy")
        or ticket.get("setupRec")
        or ticket.get("structure")
        or "Unknown"
    ).upper()
    if "STRADDLE" in raw:
        return "Long Straddle"
    if "STRANGLE" in raw:
        return "Long Strangle"
    if "IRON_CONDOR" in raw or "IRON CONDOR" in raw:
        return "Iron Condor"
    if "BUTTERFLY" in raw:
        return "Butterfly"
    if "CALENDAR" in raw or "DIAGONAL" in raw:
        return "Calendar / Diagonal"
    if "CREDIT" in raw or "PUT_CREDIT" in raw or "CALL_CREDIT" in raw:
        return "Credit Spread"
    if "DEBIT" in raw or "CALL_DEBIT" in raw or "PUT_DEBIT" in raw:
        return "Vertical Debit"
    if "VERTICAL" in raw:
        return "Vertical"
    return raw.title() or "Unknown"


def _ticket_readiness(ticket: dict) -> float | None:
    for k in ("readinessScore", "readiness", "ready_score", "readyScore"):
        v = _safe_float(ticket.get(k))
        if v is not None:
            return v
    return None


def _ticket_confidence(ticket: dict) -> str | None:
    for k in ("convictionTag", "confidence", "convictionState", "conviction"):
        v = ticket.get(k)
        if v is not None:
            return str(v)
    return None


def _ticket_cycle_id(ticket: dict) -> str:
    return str(ticket.get("tradeDate") or ticket.get("cycleId") or "unknown-cycle")


# ───────────────────────── Brinson decomposition ───────────────────────


def _brinson_decompose(
    closed_tickets: list[dict],
    universe_tickets: list[dict],
) -> dict[str, Any]:
    """Return per-family allocation / selection / interaction.

    `closed_tickets` is the portfolio: tickets we actually took (paper) and
    that have closed. `universe_tickets` is the benchmark: every stageable
    ticket from the same cycles, equal-weighted by family.

    Returns a dict shaped:

        {
          "families": [
            {
              "family": "Long Straddle",
              "wPortfolio": ..., "wBenchmark": ...,
              "rPortfolio": ..., "rBenchmark": ...,
              "allocation": ..., "selection": ..., "interaction": ...,
            },
            ...
          ],
          "totals": {
            "allocation": ..., "selection": ..., "interaction": ...,
            "active_return": ...,
          },
        }

    R values are average PnL per ticket in that family; weights are share
    of family count over total. The decomposition identity always holds:
    Σ(allocation + selection + interaction) ≡ Σ(rPortfolio·wPortfolio) −
    Σ(rBenchmark·wBenchmark).
    """
    families = sorted({_strategy_family(t) for t in closed_tickets + universe_tickets})

    portfolio_by_family: dict[str, list[float]] = defaultdict(list)
    for t in closed_tickets:
        pnl = _ticket_pnl(t)
        if pnl is not None:
            portfolio_by_family[_strategy_family(t)].append(pnl)

    benchmark_by_family: dict[str, list[float]] = defaultdict(list)
    for t in universe_tickets:
        pnl = _ticket_pnl(t)
        if pnl is not None:
            benchmark_by_family[_strategy_family(t)].append(pnl)

    n_portfolio = sum(len(v) for v in portfolio_by_family.values())
    n_benchmark = sum(len(v) for v in benchmark_by_family.values())

    rows: list[dict[str, Any]] = []
    tot_alloc = tot_select = tot_inter = 0.0
    for fam in families:
        port = portfolio_by_family.get(fam, [])
        bench = benchmark_by_family.get(fam, [])
        w_port = (len(port) / n_portfolio) if n_portfolio else 0.0
        w_bench = (len(bench) / n_benchmark) if n_benchmark else 0.0
        r_port = (sum(port) / len(port)) if port else 0.0
        r_bench = (sum(bench) / len(bench)) if bench else 0.0
        allocation = (w_port - w_bench) * r_bench
        selection = w_bench * (r_port - r_bench)
        interaction = (w_port - w_bench) * (r_port - r_bench)
        tot_alloc += allocation
        tot_select += selection
        tot_inter += interaction
        rows.append(
            {
                "family": fam,
                "wPortfolio": round(w_port, 6),
                "wBenchmark": round(w_bench, 6),
                "rPortfolio": round(r_port, 6),
                "rBenchmark": round(r_bench, 6),
                "allocation": round(allocation, 6),
                "selection": round(selection, 6),
                "interaction": round(interaction, 6),
            }
        )

    return {
        "families": rows,
        "totals": {
            "allocation": round(tot_alloc, 6),
            "selection": round(tot_select, 6),
            "interaction": round(tot_inter, 6),
            "active_return": round(tot_alloc + tot_select + tot_inter, 6),
        },
    }


# ───────────────────────── Eckhardt comfortable-win flag ───────────────


def _eckhardt_flags(
    closed_tickets: list[dict],
    universe_tickets: list[dict],
) -> list[dict[str, Any]]:
    """Flag each *winning* closed ticket that matches the comfortable-win
    profile.

    A comfortable win has all of:
      - PnL > 0
      - readiness >= COMFORTABLE_READINESS_FLOOR
      - dominant family in its cycle's slate (share ≥ COMFORTABLE_DOMINANT_SHARE_FLOOR)
    """
    by_cycle = defaultdict(list)
    for t in universe_tickets:
        by_cycle[_ticket_cycle_id(t)].append(t)

    flags: list[dict[str, Any]] = []
    for t in closed_tickets:
        pnl = _ticket_pnl(t)
        if pnl is None or pnl <= 0:
            continue
        readiness = _ticket_readiness(t)
        if readiness is None or readiness < COMFORTABLE_READINESS_FLOOR:
            continue
        cycle = _ticket_cycle_id(t)
        slate = by_cycle.get(cycle, [])
        if not slate:
            continue
        fams = Counter(_strategy_family(s) for s in slate)
        total = sum(fams.values())
        if total == 0:
            continue
        my_family = _strategy_family(t)
        dominant_share = fams.most_common(1)[0][1] / total
        my_share = fams.get(my_family, 0) / total
        if my_family != fams.most_common(1)[0][0]:
            continue
        if dominant_share < COMFORTABLE_DOMINANT_SHARE_FLOOR:
            continue
        flags.append(
            {
                "ticker": t.get("ticker"),
                "ticketId": t.get("ticketId"),
                "family": my_family,
                "pnl": round(pnl, 4),
                "readiness": readiness,
                "dominantShare": round(dominant_share, 3),
                "ownFamilyShare": round(my_share, 3),
                "citation": "ECKHARDT-MW93",
                "note": (
                    "comfortable win — high readiness, in slate's dominant "
                    "family; check whether the bull case was selection or "
                    "just allocation drift before reusing the rule"
                ),
            }
        )
    return flags


# ───────────────────────── ingestion ────────────────────────────────────


def _load_universe(now: Any | None = None) -> tuple[list[dict], list[dict]]:
    """Load (closed_outcomes, universe) tickets from the shadow + paper
    ledgers."""
    universe: list[dict] = []
    closed: list[dict] = []
    for path in (PAPER_LEDGER_FILE, SHADOW_LEDGER_FILE):
        payload = load_json_file(path)
        if not isinstance(payload, dict):
            continue
        items = payload.get("items") or []
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            universe.append(it)
            if _ticket_closed(it):
                closed.append(it)
    return closed, universe


# ───────────────────────── builder ──────────────────────────────────────


def build_outcome_attribution(now: Any | None = None) -> dict[str, Any]:
    """Build the attribution report (research-only, diagnostic-only)."""
    closed, universe = _load_universe(now=now)

    decomposition = _brinson_decompose(closed, universe)
    comfortable_wins = _eckhardt_flags(closed, universe)

    summary_verdict = (
        "attribution-ready"
        if closed
        else "awaiting-closed-outcomes"
    )

    payload = {
        "version": 1,
        "stage": ATTRIBUTION_STAGE,
        "promotable": False,
        "generatedAt": str(now or local_now()),
        "verdict": summary_verdict,
        "counts": {
            "closedOutcomes": len(closed),
            "universeTickets": len(universe),
            "comfortableWins": len(comfortable_wins),
        },
        "brinson": decomposition,
        "comfortableWins": comfortable_wins,
        "reminders": [
            "Decomposition is research-only; broker submit is OFF.",
            "Allocation effect tells you whether you picked the right "
            "strategy family; selection effect tells you whether you "
            "picked the right ticket inside it. Both must be honest.",
            "Eckhardt-MW93: comfortable wins are the dangerous ones. "
            "Confirm the bull case stands without the consensus tailwind.",
        ],
        "citations": ["BHB-1986", "SHARPE-1966", "SORTINO-1980", "ECKHARDT-MW93"],
    }
    return payload


def save_outcome_attribution(payload: dict) -> None:
    ensure_dirs()
    atomic_write_json(ATTRIBUTION_FILE, payload)
    atomic_write_text(ATTRIBUTION_TEXT_FILE, outcome_attribution_text(payload))


# ───────────────────────── rendering ────────────────────────────────────


def outcome_attribution_text(payload: dict) -> str:
    lines: list[str] = []
    lines.append("Inferno Outcome Attribution (research-only)")
    lines.append("")
    lines.append(f"Generated: {payload.get('generatedAt')}")
    lines.append(f"Stage:     {payload.get('stage')}")
    lines.append(f"Verdict:   {payload.get('verdict')}")
    counts = payload.get("counts") or {}
    lines.append(
        f"Closed outcomes: {counts.get('closedOutcomes', 0)}  "
        f"universe: {counts.get('universeTickets', 0)}  "
        f"comfortable wins: {counts.get('comfortableWins', 0)}"
    )
    lines.append("")
    if counts.get("closedOutcomes", 0) == 0:
        lines.append("No closed outcomes yet — this is expected at the desk's")
        lines.append("current stage. Once paper outcomes start closing, the")
        lines.append("Brinson decomposition below will populate.")
        lines.append("")
    else:
        brinson = payload.get("brinson") or {}
        totals = brinson.get("totals") or {}
        lines.append("BRINSON DECOMPOSITION (BHB-1986)")
        lines.append("--------------------------------")
        lines.append(
            f"Active return: {totals.get('active_return', 0):.4f}  "
            f"= alloc {totals.get('allocation', 0):.4f}  "
            f"+ selection {totals.get('selection', 0):.4f}  "
            f"+ interaction {totals.get('interaction', 0):.4f}"
        )
        lines.append("")
        lines.append(
            f"{'family':<22} {'wP':>6} {'wB':>6} {'rP':>9} {'rB':>9} "
            f"{'alloc':>9} {'sel':>9} {'inter':>9}"
        )
        for row in brinson.get("families", []):
            lines.append(
                f"{row['family'][:22]:<22} "
                f"{row['wPortfolio']:>6.2f} {row['wBenchmark']:>6.2f} "
                f"{row['rPortfolio']:>9.2f} {row['rBenchmark']:>9.2f} "
                f"{row['allocation']:>9.4f} {row['selection']:>9.4f} "
                f"{row['interaction']:>9.4f}"
            )
        lines.append("")
        flags = payload.get("comfortableWins") or []
        if flags:
            lines.append("COMFORTABLE WINS (ECKHARDT-MW93)")
            lines.append("--------------------------------")
            for f in flags:
                lines.append(
                    f"  {f.get('ticker')} ({f.get('family')}) "
                    f"PnL {f.get('pnl')}  readiness {f.get('readiness')}  "
                    f"dom share {f.get('dominantShare')}"
                )
                lines.append(f"    {f.get('note')}")
            lines.append("")
    lines.append("Reminders:")
    for r in payload.get("reminders", []):
        lines.append(f"- {r}")
    lines.append("")
    return "\n".join(lines)


# ───────────────────────── CLI ──────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inferno Outcome Attribution — research-only Brinson "
                    "decomposition of closed paper outcomes."
    )
    parser.add_argument(
        "mode",
        nargs="?",
        default="run",
        choices=("run", "status"),
        help="run: rebuild artifact. status: print last text artifact.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode == "status":
        if ATTRIBUTION_TEXT_FILE.exists():
            print(ATTRIBUTION_TEXT_FILE.read_text())
            return 0
        print("no outcome_attribution artifact yet — run without args first")
        return 1
    payload = build_outcome_attribution()
    save_outcome_attribution(payload)
    print(outcome_attribution_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
