from __future__ import annotations

"""Inferno Blow-Up Guardrails — pre-trade ruin-prevention checks.

What it does:
    Runs a small, named set of hard guardrails against the current
    operator briefing slate. Each guardrail is tied 1:1 to a documented
    historical blow-up in ``docs/BLOWUP_CASE_STUDIES.md``. If a guardrail
    fails, the artifact records *which* historical pattern the violation
    matches and which rule was breached.

    The module is research-only. It cannot reject a ticket, mutate the
    queue, change authority, or touch the broker. The operator briefing's
    own caps are the *enforcement* layer; this module is the *visibility*
    layer that makes the case-study reason audible.

What it does NOT do:
    - Approve, reject, or size any trade.
    - Mutate the authority manifest or the live book.
    - Touch any TOS, paper, or broker surface.

Strict contract: research-only, diagnostic-only, never promotable.

## The six guardrails

| # | Rule | Case study it prevents |
|---|---|---|
| 1 | Every position has a defined maximum loss known at trade open | Niederhoffer (1997), Cordier (2018) |
| 2 | Per-ticket dollar risk ≤ quarter-Kelly of bankroll | Kelly over-betting literature |
| 3 | Daily-total risk ≤ ``HARD_CAP_PER_DAY`` | Hwang (Archegos), Amaranth |
| 4 | Slate concentration caps on sector / setup / underlying | LTCM, Hwang |
| 5 | Daily-drawdown circuit breaker | Disposition-effect / revenge-trading |
| 6 | Consecutive-loss size tightening | Disposition effect (Shefrin-Statman 1985) |

Rules 1-4 are *hard*. Rules 5-6 are *operational* and require a
realised P/L stream the desk does not yet have at scale — so the
guardrails fail-soft (advisory) on them today and will fail-hard once
the closed-shadow ledger is populated.

CLI::

    python3 inferno_blowup_guardrails.py             # run + persist
    python3 inferno_blowup_guardrails.py status      # show last memo
"""

import argparse
from typing import Any, Iterable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


# ───────────────────────── file locations ──────────────────────────────

DECISION_BRIEFS_FILE = DATA_DIR / "inferno_decision_briefs.json"
SHADOW_LEDGER_FILE = DATA_DIR / "inferno_shadow_evidence.json"

GUARDRAILS_FILE = DATA_DIR / "inferno_blowup_guardrails.json"
GUARDRAILS_TEXT_FILE = REPORTS_DIR / "blowup_guardrails_latest.txt"

GUARDRAILS_STAGE = "blowup-guardrails-research-only"


# ───────────────────────── guardrail thresholds ────────────────────────

# These mirror inferno_operator_briefing constants so the visibility
# layer cannot drift from the enforcement layer. If you change one,
# change the other, and document the rationale in MATH.md §23.
HARD_CAP_PER_TICKET = 500.0           # max $ risk on one ticket (matches briefing)
HARD_CAP_PER_DAY = 1500.0             # max $ total daily risk (matches briefing)
QUARTER_KELLY_CAP_FRACTION = 0.25     # fraction of bankroll allowed per ticket
SECTOR_CONCENTRATION_LIMIT = 0.50     # max share of slate in one sector
SETUP_CONCENTRATION_LIMIT = 0.50      # max share of slate in one setup
UNDERLYING_DUPLICATE_LIMIT = 1        # max tickets sharing the same underlying
DAILY_DRAWDOWN_HALT_FRACTION = 0.05   # halt new tickets if -5% on the day
CONSECUTIVE_LOSS_TIGHTEN_AT = 3       # halve size after N consecutive losses

# Substrings that mark a structure as having undefined maximum loss.
# A trade-suffix that includes any of these is *banned*. These are not
# present in current snapshot output but are checked defensively because
# blow-ups happen when a future code path quietly admits a new structure.
UNDEFINED_LOSS_PATTERNS = (
    "NAKED CALL",
    "NAKED PUT",
    "SHORT STRADDLE",
    "SHORT STRANGLE",
    "SHORT CALL",   # unhedged short call
    "SHORT PUT",    # unhedged short put
    "UNCOVERED",
)


# ───────────────────────── helpers ─────────────────────────────────────


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _structure_label(text: str) -> str:
    """Normalise a structure string for setup-share counting."""
    upper = text.upper()
    if "STRADDLE" in upper:
        return "Straddle"
    if "STRANGLE" in upper:
        return "Strangle"
    if "VERTICAL" in upper or ("CALL" in upper and "SHORT" not in upper):
        return "Vertical Call"
    if "PUT" in upper:
        return "Vertical Put"
    return text.title() or "Unknown"


def _structure_is_undefined_loss(text: str) -> bool:
    upper = (text or "").upper()
    return any(pattern in upper for pattern in UNDEFINED_LOSS_PATTERNS)


# ───────────────────────── individual guardrails ───────────────────────


def _g1_defined_loss(ticket: dict[str, Any]) -> dict[str, Any]:
    """Rule 1: every position must have a defined maximum loss."""
    structure = ticket.get("structure") or ""
    undefined = _structure_is_undefined_loss(structure)
    return {
        "rule": "defined-max-loss",
        "case": "Niederhoffer 1997 / Cordier 2018",
        "passed": not undefined,
        "detail": (
            f"structure '{structure}' has defined max loss"
            if not undefined
            else f"structure '{structure}' has *undefined* maximum loss — BLOCKED"
        ),
    }


def _g2_per_ticket_kelly(ticket: dict[str, Any], bankroll: float) -> dict[str, Any]:
    """Rule 2: per-ticket dollar risk ≤ quarter-Kelly of bankroll."""
    allocation = _safe_float(ticket.get("allocation")) or 0.0
    kelly_cap = QUARTER_KELLY_CAP_FRACTION * max(bankroll, 1e-6)
    passed = allocation <= kelly_cap and allocation <= HARD_CAP_PER_TICKET
    return {
        "rule": "per-ticket-quarter-kelly",
        "case": "Kelly over-betting literature (RT92, MTZ10)",
        "passed": passed,
        "detail": (
            f"allocation ${allocation:.2f} ≤ quarter-Kelly ${kelly_cap:.2f} "
            f"and ≤ hard-cap ${HARD_CAP_PER_TICKET:.2f}"
            if passed
            else f"allocation ${allocation:.2f} exceeds quarter-Kelly ${kelly_cap:.2f} "
                 f"or hard-cap ${HARD_CAP_PER_TICKET:.2f}"
        ),
    }


def _g3_daily_total(slate: list[dict[str, Any]]) -> dict[str, Any]:
    """Rule 3: daily-total risk ≤ HARD_CAP_PER_DAY."""
    total = sum((_safe_float(t.get("allocation")) or 0.0) for t in slate)
    passed = total <= HARD_CAP_PER_DAY
    return {
        "rule": "daily-total-cap",
        "case": "Hwang Archegos / Amaranth",
        "passed": passed,
        "detail": (
            f"slate total ${total:.2f} ≤ daily cap ${HARD_CAP_PER_DAY:.2f}"
            if passed
            else f"slate total ${total:.2f} would exceed daily cap ${HARD_CAP_PER_DAY:.2f}"
        ),
    }


def _g4_concentration(slate: list[dict[str, Any]], briefs_by_ticker: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Rule 4: sector / setup / underlying concentration caps.

    A slate of fewer than 3 tickets cannot exceed concentration even if all
    are the same — concentration ratios are noisy at very small n. We still
    flag duplicate underlyings at any slate size because that is a different
    failure mode (same name × different structures = same risk).
    """
    n = max(1, len(slate))

    # Sector shares
    sectors: dict[str, int] = {}
    setups: dict[str, int] = {}
    underlyings: dict[str, int] = {}
    for t in slate:
        ticker = (t.get("ticker") or "").upper()
        if not ticker:
            continue
        underlyings[ticker] = underlyings.get(ticker, 0) + 1
        brief = briefs_by_ticker.get(ticker) or {}
        sector = ((brief.get("edge") or {}).get("sector")) or "Unknown"
        sectors[sector] = sectors.get(sector, 0) + 1
        setup_label = _structure_label(t.get("structure") or "")
        setups[setup_label] = setups.get(setup_label, 0) + 1

    max_sector_share = (max(sectors.values()) / n) if sectors else 0
    max_setup_share = (max(setups.values()) / n) if setups else 0
    duplicate_underlyings = [tk for tk, c in underlyings.items() if c > UNDERLYING_DUPLICATE_LIMIT]

    failures = []
    if n >= 3 and max_sector_share > SECTOR_CONCENTRATION_LIMIT:
        dominant = max(sectors, key=sectors.get)
        failures.append(f"sector '{dominant}' is {max_sector_share*100:.0f}% of slate (cap {SECTOR_CONCENTRATION_LIMIT*100:.0f}%)")
    if n >= 3 and max_setup_share > SETUP_CONCENTRATION_LIMIT:
        dominant = max(setups, key=setups.get)
        failures.append(f"setup '{dominant}' is {max_setup_share*100:.0f}% of slate (cap {SETUP_CONCENTRATION_LIMIT*100:.0f}%)")
    if duplicate_underlyings:
        failures.append(f"duplicate underlying(s): {', '.join(duplicate_underlyings)}")

    return {
        "rule": "concentration-caps",
        "case": "LTCM 1998 / Hwang Archegos",
        "passed": not failures,
        "detail": (
            f"sector max {max_sector_share*100:.0f}% / setup max {max_setup_share*100:.0f}% / "
            f"no duplicate underlyings"
            if not failures
            else "; ".join(failures)
        ),
        "metrics": {
            "sectorShares": {k: v / n for k, v in sectors.items()},
            "setupShares": {k: v / n for k, v in setups.items()},
            "underlyingCounts": underlyings,
        },
    }


def _g5_daily_drawdown(closed_today_pnl: float, bankroll: float) -> dict[str, Any]:
    """Rule 5: halt new tickets if today's realised loss > X% of bankroll.

    Until the desk has a reliable realised-P/L feed for today's closed
    tickets, this rule is advisory (passed=True) but the artifact records
    the threshold so the operator can act manually.
    """
    threshold = DAILY_DRAWDOWN_HALT_FRACTION * max(bankroll, 1e-6)
    breached = closed_today_pnl < -threshold
    return {
        "rule": "daily-drawdown-halt",
        "case": "Disposition effect / revenge trading (SS85)",
        "passed": not breached,
        "advisory": True,  # until realised P/L is wired in
        "detail": (
            f"closed-today P/L ${closed_today_pnl:.2f} is within "
            f"-${threshold:.2f} drawdown threshold"
            if not breached
            else f"closed-today P/L ${closed_today_pnl:.2f} breached "
                 f"-${threshold:.2f} threshold — HALT new tickets"
        ),
    }


def _g6_loss_streak(loss_streak: int) -> dict[str, Any]:
    """Rule 6: halve sizing after N consecutive losses."""
    breached = loss_streak >= CONSECUTIVE_LOSS_TIGHTEN_AT
    return {
        "rule": "loss-streak-tightening",
        "case": "Disposition effect (SS85)",
        "passed": not breached,
        "advisory": True,  # until streak is computed from real history
        "detail": (
            f"current loss streak {loss_streak} < tighten threshold {CONSECUTIVE_LOSS_TIGHTEN_AT}"
            if not breached
            else f"loss streak {loss_streak} ≥ {CONSECUTIVE_LOSS_TIGHTEN_AT} — halve per-ticket size"
        ),
    }


# ───────────────────────── orchestration ───────────────────────────────


def _slate_from_briefing(briefing: dict[str, Any]) -> list[dict[str, Any]]:
    tickets = ((briefing.get("sizing") or {}).get("tickets") or []) or (briefing.get("candidates") or [])
    out = []
    for t in tickets:
        if not t:
            continue
        ticker = (t.get("ticker") or "").upper()
        if not ticker:
            continue
        out.append({
            "ticker": ticker,
            "structure": t.get("structure") or t.get("setupRec") or t.get("setup") or "",
            "allocation": (_safe_float(t.get("allocation"))
                           or _safe_float(t.get("dollarAllocation"))
                           or 0.0),
        })
    return out


def _briefs_by_ticker(briefs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        (b.get("ticker") or "").upper(): b
        for b in (briefs.get("briefs") or [])
        if b.get("ticker")
    }


def build_guardrails(
    *,
    briefing: dict[str, Any] | None = None,
    decision_briefs: dict[str, Any] | None = None,
    bankroll: float | None = None,
    closed_today_pnl: float | None = None,
    loss_streak: int | None = None,
) -> dict[str, Any]:
    """Build the blow-up guardrails artifact."""
    if briefing is None:
        try:
            from inferno_operator_briefing import build_briefing
            briefing = build_briefing()
        except Exception:
            briefing = {}
    if decision_briefs is None:
        decision_briefs = load_json_file(DECISION_BRIEFS_FILE) or {}

    slate = _slate_from_briefing(briefing)
    briefs_by_ticker = _briefs_by_ticker(decision_briefs)

    # Bankroll default: derive from the briefing's deployable cash if available
    if bankroll is None:
        cash = (briefing.get("sizing") or {}).get("cash")
        bankroll = _safe_float(cash) or 1000.0  # conservative default

    closed_today_pnl = closed_today_pnl if closed_today_pnl is not None else 0.0
    loss_streak = loss_streak if loss_streak is not None else 0

    # Global slate checks
    g3 = _g3_daily_total(slate)
    g4 = _g4_concentration(slate, briefs_by_ticker)
    g5 = _g5_daily_drawdown(closed_today_pnl, bankroll)
    g6 = _g6_loss_streak(loss_streak)

    # Per-ticket checks
    ticket_results = []
    for ticket in slate:
        g1 = _g1_defined_loss(ticket)
        g2 = _g2_per_ticket_kelly(ticket, bankroll)
        ticket_passed = g1["passed"] and g2["passed"]
        ticket_results.append({
            "ticker": ticket["ticker"],
            "structure": ticket["structure"],
            "allocation": ticket["allocation"],
            "passed": ticket_passed,
            "checks": [g1, g2],
        })

    global_results = [g3, g4, g5, g6]
    any_global_fail = any(not g["passed"] and not g.get("advisory") for g in global_results)
    any_global_advisory_fail = any(not g["passed"] and g.get("advisory") for g in global_results)
    any_ticket_fail = any(not r["passed"] for r in ticket_results)

    if any_global_fail or any_ticket_fail:
        verdict = "blocked"
        narrative = (
            "At least one hard guardrail failed. The operator briefing's own caps "
            "should have prevented this; if a violation is showing here, the "
            "enforcement layer has drifted from the visibility layer and needs "
            "reconciliation."
        )
    elif any_global_advisory_fail:
        verdict = "advisory-warn"
        narrative = (
            "Hard guardrails passed. Advisory rules (drawdown halt / loss-streak "
            "tightening) flag operator attention. Review before sizing."
        )
    else:
        verdict = "clear"
        narrative = (
            "All hard guardrails passed. Advisory rules within tolerance. The "
            "case-study reasons next to each rule are listed below."
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": GUARDRAILS_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "bankroll": bankroll,
        "closedTodayPnl": closed_today_pnl,
        "lossStreak": loss_streak,
        "slateSize": len(slate),
        "globalChecks": global_results,
        "tickets": ticket_results,
        "constants": {
            "hardCapPerTicket": HARD_CAP_PER_TICKET,
            "hardCapPerDay": HARD_CAP_PER_DAY,
            "quarterKellyCapFraction": QUARTER_KELLY_CAP_FRACTION,
            "sectorConcentrationLimit": SECTOR_CONCENTRATION_LIMIT,
            "setupConcentrationLimit": SETUP_CONCENTRATION_LIMIT,
            "underlyingDuplicateLimit": UNDERLYING_DUPLICATE_LIMIT,
            "dailyDrawdownHaltFraction": DAILY_DRAWDOWN_HALT_FRACTION,
            "consecutiveLossTightenAt": CONSECUTIVE_LOSS_TIGHTEN_AT,
        },
        "reminders": [
            "diagnostic only; does not block anything — the briefing's caps are the enforcement layer",
            "see docs/BLOWUP_CASE_STUDIES.md for the historical reason behind each rule",
            "see docs/MATH.md §23 for the position-sizing math",
            "advisory rules (G5, G6) become hard once a realised P/L feed is wired in",
        ],
    }


# ───────────────────────── rendering ───────────────────────────────────


def _check_line(check: dict[str, Any]) -> str:
    mark = "PASS" if check["passed"] else ("ADVISORY" if check.get("advisory") else "FAIL")
    advisory_tag = " (advisory)" if check.get("advisory") else ""
    return (
        f"  [{mark}]{advisory_tag} {check['rule']:<28} — {check['detail']}\n"
        f"            case: {check['case']}"
    )


def guardrails_text(report: dict[str, Any]) -> str:
    lines = [
        "Inferno Blow-Up Guardrails (diagnostic-only)",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Stage: {report.get('stage')}",
        f"Verdict: {report.get('verdict')}",
        f"Narrative: {report.get('narrative')}",
        f"Bankroll: ${report.get('bankroll', 0):.2f}",
        f"Closed-today P/L: ${report.get('closedTodayPnl', 0):.2f}",
        f"Loss streak: {report.get('lossStreak', 0)}",
        f"Slate size: {report.get('slateSize', 0)}",
        "",
        "GLOBAL CHECKS:",
    ]
    for check in report.get("globalChecks") or []:
        lines.append(_check_line(check))
    lines.append("")
    lines.append("PER-TICKET CHECKS:")
    for ticket in report.get("tickets") or []:
        mark = "PASS" if ticket["passed"] else "FAIL"
        lines.append(
            f"  [{mark}] {ticket['ticker']:<6} {ticket['structure']:<18} "
            f"${ticket['allocation']:.2f}"
        )
        for check in ticket["checks"]:
            lines.append(_check_line(check))
        lines.append("")
    lines.append("CONSTANTS:")
    for key, value in (report.get("constants") or {}).items():
        lines.append(f"  - {key}: {value}")
    lines.append("")
    lines.append("REMINDERS:")
    for reminder in report.get("reminders") or []:
        lines.append(f"  - {reminder}")
    return "\n".join(lines).rstrip() + "\n"


# ───────────────────────── persistence ─────────────────────────────────


def save_guardrails(report: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(GUARDRAILS_FILE, report)
    atomic_write_text(GUARDRAILS_TEXT_FILE, guardrails_text(report))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Pre-trade blow-up guardrails. Runs six named rules against "
            "today's slate, each tied to a documented historical blow-up. "
            "Research-only; does not block or mutate anything."
        )
    )
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    parser.add_argument("--bankroll", type=float, default=None,
                        help="Override bankroll (default: briefing's deployable cash)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and GUARDRAILS_TEXT_FILE.exists():
        print(GUARDRAILS_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = build_guardrails(bankroll=args.bankroll)
    save_guardrails(report)
    print(guardrails_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
