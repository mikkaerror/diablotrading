from __future__ import annotations

"""Inferno Paper Bootstrap — seed the paper ledger so the math earns Phase 2.

What it does:
    Phase 1 has a chicken-and-egg problem: the paper-evidence promotion
    gates in `docs/MATH.md` § 10 need ~30 closed paper outcomes per
    strategy before they produce trustworthy verdicts, but the live-gate
    filter (Ready≥72 AND Conf≥2 AND DTE≤21 AND not-Avoid AND Trigger)
    is too strict to clear on most days. Without paper data, the math
    cannot earn the right to promote to Phase 2. Forever.

    This module breaks the cycle. It scores every slate row by *how many*
    of the five conviction gates it clears (0..5) instead of demanding
    all five at once, then proposes paper trades at the top scores. The
    proposals are written to `data/inferno_paper_bootstrap_queue.json`
    for the paper test director to consume.

What it does NOT do:
    - Suggest a live trade. Touch the live authority. Modify the manifest.
    - Lower the five live gates — those stay exactly where they are.
      The relaxation here applies *only* to which trades get seeded
      into the paper ledger for the math to learn from.
    - Size positions out of the live bankroll. Bootstrap paper tickets
      are sized at a fixed, deliberately tiny notional so they're never
      confused with live conviction trades.

Strict contract: research-only, diagnostic-only, never promotable. The
proposals carry an explicit ``paperBootstrap: true`` flag the strategy
lab and authority controller respect — bootstrap outcomes go into the
shadow ledger but do not count toward live promotion math until the
operator manually marks them as live-quality.

## The math

For each slate row, the *gates cleared* score is:

```
score = sum([
    readyScore >= 72,
    confidence >= 2,
    daysUntilEarnings <= 21,
    setupRec not in {"Avoid"},
    bool(signalTrigger),
])
```

Each predicate evaluates to 0 or 1. The score is an integer in `[0, 5]`.

The bootstrap admit threshold is configurable (default ``3``), so by
default we admit rows that clear at least 3 of 5 gates. Verdict ladder:

| Condition                                    | Verdict                  |
|----------------------------------------------|--------------------------|
| no slate                                     | no-evidence              |
| no row scores at least the admit threshold   | insufficient-relaxation  |
| fewer than `MIN_BOOTSTRAP_TICKETS` admit     | slate-too-thin           |
| at least `MIN_BOOTSTRAP_TICKETS` admitted    | ready-to-seed            |

Sizing: every bootstrap paper ticket is ``BOOTSTRAP_TICKET_DOLLARS``
(default $50) of *paper* notional. Total open bootstrap tickets capped
at ``MAX_OPEN_BOOTSTRAP_TICKETS`` (default 10). These caps are
intentionally smaller than the live caps in `inferno_config.py`.

CLI::

    python3 inferno_paper_bootstrap.py             # generate today's seed queue
    python3 inferno_paper_bootstrap.py status      # show last memo
    python3 inferno_paper_bootstrap.py --threshold 4   # stricter relaxation
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


PAPER_BOOTSTRAP_FILE = DATA_DIR / "inferno_paper_bootstrap.json"
PAPER_BOOTSTRAP_QUEUE_FILE = DATA_DIR / "inferno_paper_bootstrap_queue.json"
PAPER_BOOTSTRAP_TEXT_FILE = REPORTS_DIR / "paper_bootstrap_latest.txt"
PAPER_BOOTSTRAP_STAGE = "paper-bootstrap-research-only"

DEFAULT_ADMIT_THRESHOLD = int(os.environ.get("INFERNO_PB_ADMIT_THRESHOLD", "3"))
MIN_BOOTSTRAP_TICKETS = int(os.environ.get("INFERNO_PB_MIN_TICKETS", "3"))
MAX_BOOTSTRAP_TICKETS_PER_RUN = int(os.environ.get("INFERNO_PB_MAX_PER_RUN", "5"))
MAX_OPEN_BOOTSTRAP_TICKETS = int(os.environ.get("INFERNO_PB_MAX_OPEN", "10"))
BOOTSTRAP_TICKET_DOLLARS = float(os.environ.get("INFERNO_PB_TICKET_DOLLARS", "50.0"))

# Live conviction gates — kept identical to inferno_operator_briefing so the
# scoring stays consistent. Loosening these here would only loosen *paper*
# seeding; live gating is unchanged.
MIN_READY_SCORE = 72
MIN_CONFIDENCE = 2
MAX_DAYS_UNTIL_EARNINGS = 21
BANNED_SETUPS = frozenset({"Avoid"})


# ---------------------------------------------------------------------------
# Slate ingestion.
# ---------------------------------------------------------------------------


def _coerce_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _load_snapshot() -> dict[str, Any]:
    path = DATA_DIR / "latest_snapshot.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _candidate_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("rows", "scoredRows", "items", "tickers"):
        value = snapshot.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


# ---------------------------------------------------------------------------
# Pure math: per-row gate score and ranking.
# ---------------------------------------------------------------------------


def score_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a dict with each gate evaluated and an integer ``score`` ∈ [0,5]."""
    ready = _coerce_int(row.get("readyScore") or row.get("Ready Score"))
    confidence = _coerce_int(row.get("confidence") or row.get("Confidence (3 MAX)"))
    dte = _coerce_int(row.get("daysUntilEarnings") or row.get("Days until earnings"))
    setup = _coerce_str(row.get("setupRec") or row.get("Setup Rec"))
    trigger = _coerce_str(row.get("signalTrigger") or row.get("Signal Trigger"))

    gates = {
        "readyOk": ready is not None and ready >= MIN_READY_SCORE,
        "confidenceOk": confidence is not None and confidence >= MIN_CONFIDENCE,
        "dteOk": dte is not None and dte <= MAX_DAYS_UNTIL_EARNINGS,
        "setupOk": bool(setup) and setup not in BANNED_SETUPS,
        "triggerOk": bool(trigger),
    }
    score = sum(1 for ok in gates.values() if ok)

    return {
        "ticker": _coerce_str(row.get("ticker") or row.get("Ticker")),
        "readyScore": ready,
        "confidence": confidence,
        "daysUntilEarnings": dte,
        "setupRec": setup,
        "signalTrigger": trigger,
        "gates": gates,
        "score": score,
        "failedGates": sorted(k for k, ok in gates.items() if not ok),
    }


def rank_candidates(
    rows: list[dict[str, Any]],
    *,
    admit_threshold: int = DEFAULT_ADMIT_THRESHOLD,
) -> list[dict[str, Any]]:
    """Score every row and return only those scoring at or above the threshold,
    sorted by score desc, then readyScore desc, then DTE asc."""
    scored = [score_row(r) for r in rows if isinstance(r, dict)]
    admitted = [s for s in scored if s["score"] >= admit_threshold]
    admitted.sort(
        key=lambda s: (
            -s["score"],
            -(s["readyScore"] or 0),
            (s["daysUntilEarnings"] if s["daysUntilEarnings"] is not None else 99),
            s["ticker"],
        )
    )
    return admitted


# ---------------------------------------------------------------------------
# Queue building — proposed paper-bootstrap tickets.
# ---------------------------------------------------------------------------


def build_proposals(
    admitted: list[dict[str, Any]],
    *,
    max_tickets: int = MAX_BOOTSTRAP_TICKETS_PER_RUN,
    ticket_dollars: float = BOOTSTRAP_TICKET_DOLLARS,
) -> list[dict[str, Any]]:
    """Take the top admitted candidates and turn them into paper proposals.

    Each proposal carries enough metadata for the paper test director to
    stage it. The ``paperBootstrap`` flag tells downstream layers (lab,
    authority controller) that this outcome should *not* count toward live
    promotion math until manually re-classified.
    """
    proposals: list[dict[str, Any]] = []
    for candidate in admitted[:max_tickets]:
        # Suggested default strategy: a defined-risk vertical. Operator
        # may override at stage time.
        suggested_strategy = (
            "Vertical Call"
            if (candidate.get("setupRec") or "").lower().startswith("call")
            else "Vertical Put"
            if (candidate.get("setupRec") or "").lower().startswith("put")
            else "Vertical Call"
        )
        proposals.append({
            "ticker": candidate["ticker"],
            "score": candidate["score"],
            "failedGates": candidate["failedGates"],
            "suggestedStrategy": suggested_strategy,
            "paperBudgetDollars": round(ticket_dollars, 2),
            "readyScore": candidate["readyScore"],
            "confidence": candidate["confidence"],
            "daysUntilEarnings": candidate["daysUntilEarnings"],
            "signalTrigger": candidate["signalTrigger"],
            "paperBootstrap": True,
            "liveQualityYet": candidate["score"] == 5,
        })
    return proposals


# ---------------------------------------------------------------------------
# Pure builder.
# ---------------------------------------------------------------------------


def build_bootstrap(
    *,
    snapshot_loader: Callable[[], dict[str, Any]] | None = None,
    admit_threshold: int = DEFAULT_ADMIT_THRESHOLD,
    max_tickets: int = MAX_BOOTSTRAP_TICKETS_PER_RUN,
    ticket_dollars: float = BOOTSTRAP_TICKET_DOLLARS,
) -> dict[str, Any]:
    """Generate today's paper-bootstrap proposal set."""
    snapshot = (snapshot_loader or _load_snapshot)()
    rows = _candidate_rows(snapshot)
    admitted = rank_candidates(rows, admit_threshold=admit_threshold)
    proposals = build_proposals(
        admitted, max_tickets=max_tickets, ticket_dollars=ticket_dollars,
    )

    # Score histogram for operator situational awareness.
    score_histogram = {i: 0 for i in range(6)}
    for r in rows:
        s = score_row(r)
        score_histogram[s["score"]] = score_histogram.get(s["score"], 0) + 1

    live_quality_count = sum(1 for p in proposals if p.get("liveQualityYet"))
    paper_only_count = len(proposals) - live_quality_count

    if not rows:
        verdict = "no-evidence"
        narrative = (
            "No slate snapshot found. Run the dawn pipeline before bootstrapping."
        )
    elif not admitted:
        verdict = "insufficient-relaxation"
        narrative = (
            f"Scanned {len(rows)} ticker(s); none cleared at least "
            f"{admit_threshold} of 5 gates. Either raise volatility-rich names "
            "into the tracker or lower the admit threshold (paper-only) to harvest "
            "more seed data."
        )
    elif len(proposals) < MIN_BOOTSTRAP_TICKETS:
        verdict = "slate-too-thin"
        narrative = (
            f"Only {len(proposals)} candidate(s) cleared the relaxed threshold "
            f"(min {MIN_BOOTSTRAP_TICKETS}). The bootstrapper will not flood the "
            "paper queue with low-conviction noise."
        )
    elif live_quality_count == len(proposals):
        verdict = "live-quality-found"
        narrative = (
            f"All {len(proposals)} proposal(s) cleared every live gate (5/5). "
            "These are not bootstrap-only — review them as live candidates."
        )
    else:
        verdict = "ready-to-seed"
        narrative = (
            f"{len(proposals)} paper-bootstrap proposal(s) at relaxed gating: "
            f"{live_quality_count} live-quality (5/5), {paper_only_count} paper-only "
            f"(<5/5). All sized at ${ticket_dollars:.0f} paper notional. "
            "Their outcomes feed shadow evidence, not live authority."
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": PAPER_BOOTSTRAP_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "method": "gates-cleared-scoring-with-paper-seeding",
        "admitThreshold": admit_threshold,
        "maxTicketsPerRun": max_tickets,
        "maxOpenTickets": MAX_OPEN_BOOTSTRAP_TICKETS,
        "ticketDollars": ticket_dollars,
        "minBootstrapTickets": MIN_BOOTSTRAP_TICKETS,
        "slateSize": len(rows),
        "admittedCount": len(admitted),
        "proposalCount": len(proposals),
        "liveQualityCount": live_quality_count,
        "paperOnlyCount": paper_only_count,
        "scoreHistogram": score_histogram,
        "proposals": proposals,
        "reminders": [
            "every proposal carries paperBootstrap=true; never counts toward live promotion math",
            "loosening the admit threshold loosens paper seeding only — live gates are unchanged",
            "bootstrap tickets are $50 paper notional, not live capital",
        ],
    }


def bootstrap_text(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Paper Bootstrap (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Method: {payload.get('method')}",
        f"Verdict: {payload.get('verdict')}",
        f"Slate size: {payload.get('slateSize')}  "
        f"admitted: {payload.get('admittedCount')}  "
        f"proposed: {payload.get('proposalCount')}  "
        f"(live-quality: {payload.get('liveQualityCount')}, "
        f"paper-only: {payload.get('paperOnlyCount')})",
        "",
        f"Narrative: {payload.get('narrative')}",
        "",
    ]
    hist = payload.get("scoreHistogram") or {}
    if hist:
        lines.append("Gate-score histogram across the full slate:")
        for score in sorted(hist.keys(), reverse=True):
            count = hist[score]
            bar = "█" * min(count, 60)
            lines.append(f"  {score}/5 gates : {count:>4}  {bar}")
        lines.append("")
    proposals = payload.get("proposals") or []
    if proposals:
        lines.append("Proposals (top by score):")
        lines.append(
            f"  {'Ticker':<8} {'Score':>5} {'Ready':>6} {'Conf':>5} {'DTE':>4} "
            f"{'Setup':<14} {'Strategy':<14} ${'Paper':<7}"
        )
        for p in proposals:
            ready = p.get('readyScore') if p.get('readyScore') is not None else 0
            conf = p.get('confidence') if p.get('confidence') is not None else 0
            dte = p.get('daysUntilEarnings') if p.get('daysUntilEarnings') is not None else 0
            lines.append(
                f"  {str(p.get('ticker'))[:8]:<8} "
                f"{p.get('score'):>5} "
                f"{ready:>6} "
                f"{conf:>5} "
                f"{dte:>4} "
                f"{'-':<14} "
                f"{str(p.get('suggestedStrategy'))[:14]:<14} "
                f"${p.get('paperBudgetDollars', 0):,.2f}"
            )
            failed = p.get("failedGates") or []
            if failed:
                lines.append(f"     failed gates: {', '.join(failed)}")
        lines.append("")
    lines.extend([
        "Thresholds:",
        f"  - admit if score >= {payload.get('admitThreshold')}/5",
        f"  - min proposals to emit a queue: {payload.get('minBootstrapTickets')}",
        f"  - max paper tickets per run: {payload.get('maxTicketsPerRun')}",
        f"  - max open paper-bootstrap tickets: {payload.get('maxOpenTickets')}",
        f"  - paper notional per ticket: ${payload.get('ticketDollars')}",
        "",
        "Reminders:",
    ])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_bootstrap(payload: dict[str, Any]) -> None:
    """Persist the diagnostic artifact, the operator memo, and the proposal queue.

    The queue file is the structured input the paper test director can
    consume. Empty proposal lists still write the queue with an empty
    ``proposals`` array so consumers see a definitive "no seed today."
    """
    ensure_dirs()
    atomic_write_json(PAPER_BOOTSTRAP_FILE, payload)
    atomic_write_text(PAPER_BOOTSTRAP_TEXT_FILE, bootstrap_text(payload))
    atomic_write_json(PAPER_BOOTSTRAP_QUEUE_FILE, {
        "generatedAt": payload.get("generatedAt"),
        "verdict": payload.get("verdict"),
        "ticketDollars": payload.get("ticketDollars"),
        "paperBootstrap": True,
        "proposals": payload.get("proposals") or [],
    })


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Seed the paper ledger with relaxed-gate candidates so the math "
            "earns its way to Phase 2. Never proposes a live trade."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument(
        "--threshold", type=int, default=DEFAULT_ADMIT_THRESHOLD,
        help=f"Min gates cleared to admit (default {DEFAULT_ADMIT_THRESHOLD}, range 1..5).",
    )
    parser.add_argument(
        "--max-tickets", type=int, default=MAX_BOOTSTRAP_TICKETS_PER_RUN,
        help=f"Max bootstrap proposals per run (default {MAX_BOOTSTRAP_TICKETS_PER_RUN}).",
    )
    parser.add_argument(
        "--ticket-dollars", type=float, default=BOOTSTRAP_TICKET_DOLLARS,
        help=f"Paper notional per bootstrap ticket (default ${BOOTSTRAP_TICKET_DOLLARS}).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and PAPER_BOOTSTRAP_TEXT_FILE.exists():
        print(PAPER_BOOTSTRAP_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    if not (1 <= args.threshold <= 5):
        print(f"--threshold must be in [1, 5], got {args.threshold}")
        return 2
    payload = build_bootstrap(
        admit_threshold=args.threshold,
        max_tickets=args.max_tickets,
        ticket_dollars=args.ticket_dollars,
    )
    save_bootstrap(payload)
    print(bootstrap_text(payload))
    if payload.get("verdict") == "insufficient-relaxation":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
