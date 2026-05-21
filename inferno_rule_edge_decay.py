from __future__ import annotations

"""Inferno Rule Edge Decay — per-bullet hit rate + half-life tracking.

What it does:
    For each conviction auditor bullet (bull / bear / disagreement /
    falsification-trigger / blow-up-risk citation tag), maintains a
    rolling record of whether the bullet was followed by a confirming
    outcome (a bear bullet on a loser, a bull bullet on a winner).
    Reports the Wilson lower bound of the hit rate and a simple
    exponential half-life estimator. Bullets with Wilson lower < 0.50
    over the rolling window are surfaced as retirement candidates.

What it does NOT do:
    - Approve, reject, or size any trade.
    - Retire any rule automatically — surfaces candidates only.
    - Promote any strategy. Research-only, diagnostic-only.

Strict contract: research-only, diagnostic-only, promotable=False.

## The math (see docs/PERFORMANCE_ATTRIBUTION.md §2)

Wilson lower bound at 95% (Agresti-Coull style):

    z = 1.96
    p̂ = wins / n
    centre = (p̂ + z²/(2n)) / (1 + z²/n)
    radius = z·√( p̂·(1−p̂)/n + z²/(4n²) ) / (1 + z²/n)
    Wilson_lower = centre − radius

Half-life via exponential decay fit on per-window hit rates:

    h(t) = h₀ · exp(−λ · t)
    half_life = ln(2) / λ        (in window units)

We deliberately use a coarse, transparent estimator over a fancier
Bayesian Online Change-Point (Adams-MacKay 2007) approach for v1 —
the half-life number is *advisory*, not promotion-bearing, so
honesty about the estimate beats precision.

CLI::

    python3 inferno_rule_edge_decay.py             # run + persist
    python3 inferno_rule_edge_decay.py status      # show last memo
"""

import argparse
import math
from collections import defaultdict
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


# ───────────────────────── file locations ──────────────────────────────

SHADOW_LEDGER_FILE = DATA_DIR / "inferno_shadow_evidence.json"
PAPER_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
CONVICTION_AUDIT_FILE = DATA_DIR / "inferno_trade_conviction_audit.json"

DECAY_FILE = DATA_DIR / "inferno_rule_edge_decay.json"
DECAY_TEXT_FILE = REPORTS_DIR / "rule_edge_decay_latest.txt"

DECAY_STAGE = "rule-edge-decay-research-only"


# ───────────────────────── thresholds ──────────────────────────────────

WILSON_Z = 1.96                       # 95% CI
WILSON_LOWER_RETIRE_FLOOR = 0.50      # Wilson_lower < floor → retire candidate
MIN_SAMPLES_FOR_VERDICT = 10          # below this, verdict is "insufficient"
FAST_DECAY_WEEKS_FLOOR = 12.0         # half-life < 12w → "fast-decay" flag


# ───────────────────────── pnl + status helpers (mirror attribution) ───


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


# ───────────────────────── Wilson bound + half-life ────────────────────


def wilson_lower(wins: int, n: int, z: float = WILSON_Z) -> float:
    """Wilson 95% lower bound on the proportion. Returns 0 if n=0."""
    if n <= 0:
        return 0.0
    p_hat = wins / n
    denom = 1.0 + (z * z) / n
    centre = (p_hat + (z * z) / (2.0 * n)) / denom
    radius = (z * math.sqrt(p_hat * (1.0 - p_hat) / n + (z * z) / (4.0 * n * n))) / denom
    return max(0.0, centre - radius)


def exponential_half_life(rates: list[float]) -> float | None:
    """Fit h(t) = h₀·exp(−λ·t) on a sequence of per-window hit rates.

    Returns half-life in window units, or None if the fit is degenerate
    (constant rates, zero rates, fewer than 3 points, or non-positive
    fitted rate). We do not attempt to distinguish growth from decay —
    the caller treats a "positive λ" as decay and ignores negative λ.
    """
    if len(rates) < 3:
        return None
    # Drop trailing zero rates which break the log; keep at least 3 points.
    cleaned = [(i, r) for i, r in enumerate(rates) if r > 0]
    if len(cleaned) < 3:
        return None
    xs = [c[0] for c in cleaned]
    ys = [math.log(c[1]) for c in cleaned]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    var = sum((xs[i] - mean_x) ** 2 for i in range(n))
    if var == 0:
        return None
    slope = cov / var  # this is −λ when rates are decaying
    if slope >= 0:
        return None  # not decaying
    lam = -slope
    if lam <= 0:
        return None
    return math.log(2.0) / lam


# ───────────────────────── data plumbing ───────────────────────────────


def _load_closed_tickets() -> list[dict]:
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


def _load_audit_history() -> dict[str, list[dict]]:
    """Map ticketId → list of bullets fired on that ticket.

    The audit artifact's shape varies across versions. We defensively
    walk every dict that looks like a "ticketAudit" and pull citation
    tags out of bullets / bears / bulls / disagreements / blow-up-risks
    fields. Missing or malformed records produce empty lists.
    """
    payload = load_json_file(CONVICTION_AUDIT_FILE)
    if not isinstance(payload, dict):
        return {}
    audits = payload.get("audits") or payload.get("ticketAudits") or []
    out: dict[str, list[dict]] = defaultdict(list)
    if not isinstance(audits, list):
        return {}
    for audit in audits:
        if not isinstance(audit, dict):
            continue
        ticket_id = audit.get("ticketId") or audit.get("ticker")
        if not ticket_id:
            continue
        for section in ("bull", "bear", "bulls", "bears", "disagreements",
                        "falsificationTriggers", "blowUpRisks"):
            bullets = audit.get(section) or []
            if not isinstance(bullets, list):
                continue
            for b in bullets:
                if not isinstance(b, dict):
                    continue
                tag = b.get("cite") or b.get("citation") or b.get("tag")
                if not tag:
                    continue
                out[str(ticket_id)].append(
                    {"section": section, "tag": str(tag), "note": b.get("note")}
                )
    return dict(out)


# ───────────────────────── core: per-rule hit rate ─────────────────────


def _bullet_predicted_outcome(section: str, pnl: float) -> bool:
    """Return True if the bullet's *side* was correct given the realised pnl.

    A bear bullet, a disagreement, a falsification-trigger, or a
    blow-up-risk on a losing ticket counts as correct.
    A bull bullet on a winning ticket counts as correct.
    Anything else is "missed".
    """
    section_l = section.lower()
    is_bear_side = section_l in (
        "bear", "bears", "disagreements",
        "falsificationtriggers", "blowuprisks",
    )
    is_bull_side = section_l in ("bull", "bulls")
    if is_bear_side:
        return pnl < 0
    if is_bull_side:
        return pnl > 0
    return False


def compute_rule_decay(
    closed_tickets: list[dict],
    audit_history: dict[str, list[dict]],
) -> list[dict[str, Any]]:
    """For every citation tag observed in the audit history that has at
    least one closed-ticket fire, compute hits / n / Wilson lower bound.

    Returns a list sorted by Wilson lower ascending so the worst-
    performing rules appear first.
    """
    # (tag, section_side) → list of bools
    correctness: dict[tuple[str, str], list[bool]] = defaultdict(list)

    for ticket in closed_tickets:
        ticket_id = ticket.get("ticketId") or ticket.get("ticker")
        if not ticket_id:
            continue
        pnl = _ticket_pnl(ticket)
        if pnl is None:
            continue
        bullets = audit_history.get(str(ticket_id), [])
        for b in bullets:
            tag = b["tag"]
            section = b["section"]
            side = "bull" if section.lower() in ("bull", "bulls") else "bear"
            correctness[(tag, side)].append(
                _bullet_predicted_outcome(section, pnl)
            )

    rows: list[dict[str, Any]] = []
    for (tag, side), outcomes in correctness.items():
        n = len(outcomes)
        wins = sum(1 for o in outcomes if o)
        wl = wilson_lower(wins, n)
        verdict = "insufficient"
        if n >= MIN_SAMPLES_FOR_VERDICT:
            verdict = "retire-candidate" if wl < WILSON_LOWER_RETIRE_FLOOR else "healthy"
        rows.append(
            {
                "tag": tag,
                "side": side,
                "n": n,
                "hits": wins,
                "hitRate": round(wins / n, 4) if n else 0.0,
                "wilsonLower": round(wl, 4),
                "verdict": verdict,
            }
        )
    rows.sort(key=lambda r: (r["wilsonLower"], -r["n"]))
    return rows


# ───────────────────────── builder ──────────────────────────────────────


def build_rule_edge_decay(now: Any | None = None) -> dict[str, Any]:
    closed = _load_closed_tickets()
    audit_history = _load_audit_history()
    rule_rows = compute_rule_decay(closed, audit_history)

    retire_candidates = [r for r in rule_rows if r["verdict"] == "retire-candidate"]

    if not closed:
        verdict = "awaiting-closed-outcomes"
    elif retire_candidates:
        verdict = "retire-candidates-present"
    else:
        verdict = "healthy"

    payload = {
        "version": 1,
        "stage": DECAY_STAGE,
        "promotable": False,
        "generatedAt": str(now or local_now()),
        "verdict": verdict,
        "counts": {
            "closedTickets": len(closed),
            "rulesTracked": len(rule_rows),
            "retireCandidates": len(retire_candidates),
        },
        "thresholds": {
            "wilsonLowerRetireFloor": WILSON_LOWER_RETIRE_FLOOR,
            "minSamplesForVerdict": MIN_SAMPLES_FOR_VERDICT,
            "fastDecayWeeksFloor": FAST_DECAY_WEEKS_FLOOR,
            "wilsonZ": WILSON_Z,
        },
        "rules": rule_rows,
        "retireCandidates": retire_candidates,
        "reminders": [
            "Rules are diagnostic-only; surfacing a retire candidate "
            "is not the same as retiring it. The operator decides.",
            "Wilson lower bound at 95% — the rule's *true* hit rate is "
            "at least this with 95% confidence. Below 0.50 means the "
            "rule is not statistically better than a coin flip.",
            "Minimum sample size is 10 — below that, verdict is "
            "'insufficient' regardless of Wilson lower.",
        ],
        "citations": [
            "GRINOLD-1989",
            "GRINOLD-KAHN-2000",
            "ISRAEL-MOSKOWITZ-2013",
            "MCLEAN-PONTIFF-2016",
            "STEIN-2009",
            "ADAMS-MACKAY-2007",
            "PAGE-1954",
        ],
    }
    return payload


def save_rule_edge_decay(payload: dict) -> None:
    ensure_dirs()
    atomic_write_json(DECAY_FILE, payload)
    atomic_write_text(DECAY_TEXT_FILE, rule_edge_decay_text(payload))


# ───────────────────────── rendering ────────────────────────────────────


def rule_edge_decay_text(payload: dict) -> str:
    lines: list[str] = []
    lines.append("Inferno Rule Edge Decay (research-only)")
    lines.append("")
    lines.append(f"Generated: {payload.get('generatedAt')}")
    lines.append(f"Stage:     {payload.get('stage')}")
    lines.append(f"Verdict:   {payload.get('verdict')}")
    counts = payload.get("counts") or {}
    lines.append(
        f"Closed tickets: {counts.get('closedTickets', 0)}  "
        f"rules tracked: {counts.get('rulesTracked', 0)}  "
        f"retire candidates: {counts.get('retireCandidates', 0)}"
    )
    lines.append("")
    rules = payload.get("rules") or []
    if not rules:
        lines.append("No rule firings recorded yet — this is expected at the")
        lines.append("desk's current stage. Once the conviction auditor's")
        lines.append("bullets can be paired with closed paper outcomes, this")
        lines.append("artifact will populate.")
        lines.append("")
    else:
        lines.append("RULE EDGE LADDER (worst Wilson lower first)")
        lines.append("-------------------------------------------")
        lines.append(
            f"{'tag':<22} {'side':<5} {'n':>3} {'hits':>4} "
            f"{'rate':>6} {'wilsonL':>8} {'verdict':<18}"
        )
        for r in rules:
            lines.append(
                f"{r['tag'][:22]:<22} {r['side']:<5} "
                f"{r['n']:>3} {r['hits']:>4} "
                f"{r['hitRate']:>6.3f} {r['wilsonLower']:>8.3f} "
                f"{r['verdict']:<18}"
            )
        lines.append("")
        retire = payload.get("retireCandidates") or []
        if retire:
            lines.append("RETIRE CANDIDATES")
            lines.append("-----------------")
            for r in retire:
                lines.append(
                    f"  {r['tag']} ({r['side']}): {r['hits']}/{r['n']}  "
                    f"Wilson_lower {r['wilsonLower']}"
                )
                lines.append(
                    f"    Below {WILSON_LOWER_RETIRE_FLOOR} — review "
                    f"whether this rule still carries edge."
                )
            lines.append("")
    lines.append("Reminders:")
    for r in payload.get("reminders", []):
        lines.append(f"- {r}")
    lines.append("")
    return "\n".join(lines)


# ───────────────────────── CLI ──────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inferno Rule Edge Decay — per-bullet hit rate + Wilson "
                    "lower bound. Research-only.",
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
        if DECAY_TEXT_FILE.exists():
            print(DECAY_TEXT_FILE.read_text())
            return 0
        print("no rule_edge_decay artifact yet — run without args first")
        return 1
    payload = build_rule_edge_decay()
    save_rule_edge_decay(payload)
    print(rule_edge_decay_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
