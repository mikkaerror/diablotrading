from __future__ import annotations

"""Inferno Operator Briefing — the daily "what do I trade today" memo.

What it does:
    Reads today's morning slate, applies the five conviction gates,
    sizes positions against the operator's deployable cash, and renders
    an email-ready text + HTML body that ends with the seven-step trade
    checklist. Designed so the operator can read one email and act
    without opening anything else.

What it does NOT do:
    - Place a trade. Connect to a broker. Touch the authority manifest.
    - Mutate the slate or the sheet.

CLI::

    python3 inferno_operator_briefing.py                # print to stdout
    python3 inferno_operator_briefing.py --email        # also send via SMTP
    python3 inferno_operator_briefing.py --cash 1050    # override cash
    python3 inferno_operator_briefing.py status         # show last memo

Environment variables consumed:

- ``INFERNO_OPERATOR_CASH``       — default deployable cash if --cash omitted
- ``INFERNO_OPERATOR_MAX_TICKETS``— target ticket count (default 5)
- ``SMTP_HOST`` / ``SMTP_PORT`` / ``SMTP_FROM`` / ``SMTP_TO`` etc. —
  the same SMTP envvars the morning brief already uses.

Strict contract: research-only, diagnostic-only, never promotable.
"""

import argparse
import json
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


OPERATOR_BRIEFING_TEXT_FILE = REPORTS_DIR / "operator_briefing_latest.txt"
OPERATOR_BRIEFING_HTML_FILE = REPORTS_DIR / "operator_briefing_latest.html"
OPERATOR_BRIEFING_STAGE = "operator-briefing-research-only"

# Conviction gates — must match frontend/modules/dataProcessor.js convictionConfig.
MIN_READY_SCORE = 72
MIN_CONFIDENCE = 2
MAX_DAYS_UNTIL_EARNINGS = 21
BANNED_SETUPS = frozenset({"Avoid"})

DEFAULT_CASH = float(os.environ.get("INFERNO_OPERATOR_CASH", "1050"))
DEFAULT_MAX_TICKETS = int(os.environ.get("INFERNO_OPERATOR_MAX_TICKETS", "5"))
HARD_CAP_PER_TICKET = 500.0
HARD_CAP_PER_DAY = 1500.0
QUARTER_KELLY_CAP_FRACTION = 0.25

LIVE_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_live_account_sync.json"
PAPER_BOOTSTRAP_FILE = DATA_DIR / "inferno_paper_bootstrap.json"
SLATE_NORMALIZED_FILE = DATA_DIR / "inferno_slate_normalized.json"

# Top-N by composite rank to surface in the email when the live filter
# blanks out. We pick the most-conviction names by *cross-sectional rank*,
# which works regardless of whether the absolute Ready Score scale is fixed.
RANKED_TIER_DEFAULT_TOP_N = int(os.environ.get("INFERNO_RANKED_TOP_N", "5"))


def _load_ranked_slate() -> dict[str, Any]:
    """Best-effort read of the latest normalized slate (percentile ranks).

    Returns an empty-shaped dict when the file is missing so the briefing
    can always render the email without crashing. The renderer simply
    skips the ranked block when ``available`` is False.
    """
    info: dict[str, Any] = {
        "available": False,
        "verdict": None,
        "slateSize": 0,
        "gatePercentile": None,
        "passingCount": 0,
        "topByComposite": [],
    }
    if not SLATE_NORMALIZED_FILE.exists():
        return info
    try:
        payload = json.loads(SLATE_NORMALIZED_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return info
    info["available"] = True
    info["verdict"] = payload.get("verdict")
    info["slateSize"] = payload.get("slateSize") or 0
    info["gatePercentile"] = payload.get("gatePercentile")
    info["passingCount"] = payload.get("passingCount") or 0
    rows = payload.get("rows") or []
    info["topByComposite"] = [
        {
            "ticker": r.get("ticker"),
            "compositeRank": r.get("compositeRank"),
            "readyRank": r.get("readyRank"),
            "ivPercentileRank": r.get("ivPercentileRank"),
            "readyScoreRaw": r.get("readyScoreRaw"),
            "passesReadyPercentileGate": r.get("passesReadyPercentileGate"),
        }
        for r in rows[:RANKED_TIER_DEFAULT_TOP_N]
    ]
    return info


# Age beyond which the live cash readout is stale and we won't trust it.
LIVE_CASH_STALE_HOURS = float(os.environ.get("INFERNO_LIVE_CASH_STALE_HOURS", "8"))


def _load_paper_bootstrap() -> dict[str, Any]:
    """Best-effort read of the latest paper-bootstrap proposals.

    Returns a stripped-down dict that's safe to include in the email
    even when the file is missing or unreadable. The briefing uses these
    proposals as a *fallback*: when the live filter produces no
    candidates, the email surfaces the bootstrap proposals so the
    operator still has actionable paper work to seed shadow evidence.
    """
    info: dict[str, Any] = {
        "available": False,
        "verdict": None,
        "proposalCount": 0,
        "liveQualityCount": 0,
        "paperOnlyCount": 0,
        "proposals": [],
        "ticketDollars": None,
    }
    if not PAPER_BOOTSTRAP_FILE.exists():
        return info
    try:
        payload = json.loads(PAPER_BOOTSTRAP_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return info
    info["available"] = True
    info["verdict"] = payload.get("verdict")
    info["proposalCount"] = payload.get("proposalCount") or 0
    info["liveQualityCount"] = payload.get("liveQualityCount") or 0
    info["paperOnlyCount"] = payload.get("paperOnlyCount") or 0
    info["ticketDollars"] = payload.get("ticketDollars")
    proposals = payload.get("proposals") or []
    info["proposals"] = [
        {
            "ticker": p.get("ticker"),
            "score": p.get("score"),
            "readyScore": p.get("readyScore"),
            "confidence": p.get("confidence"),
            "daysUntilEarnings": p.get("daysUntilEarnings"),
            "suggestedStrategy": p.get("suggestedStrategy"),
            "paperBudgetDollars": p.get("paperBudgetDollars"),
            "failedGates": p.get("failedGates") or [],
            "liveQualityYet": p.get("liveQualityYet"),
        }
        for p in proposals[:5]
    ]
    return info


def _coerce_float(value: Any) -> float | None:
    """Try to turn any JSON value (incl. ``$1,050.00`` strings) into a float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    # Strip $ and commas the TOS statement scraper sometimes leaves in.
    cleaned = text.replace("$", "").replace(",", "").replace("USD", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def load_live_cash() -> dict[str, Any]:
    """Read the latest TOS-sourced cash balance from the live account sync.

    Returns a dict describing what we found, including:
    - ``cash``               — float or ``None``
    - ``netLiquidatingValue``— float or ``None``
    - ``source``             — 'live' / 'missing' / 'unreadable' / 'blocked' /
                               'stale' / 'no-cash-field'
    - ``ageHours``           — how stale the artifact is
    - ``matchedSuffix``      — the approved account suffix it matched, if any
    - ``verdict``            — sync module's own verdict
    - ``message``            — human-readable status

    The briefing will only *use* the live cash when ``source == 'live'``.
    Every other branch falls back to the operator-supplied/env-default.
    """
    info: dict[str, Any] = {
        "cash": None,
        "netLiquidatingValue": None,
        "source": "missing",
        "ageHours": None,
        "matchedSuffix": None,
        "verdict": None,
        "message": "",
    }
    if not LIVE_ACCOUNT_SYNC_FILE.exists():
        info["message"] = "data/inferno_live_account_sync.json not found"
        return info
    try:
        payload = json.loads(LIVE_ACCOUNT_SYNC_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        info["source"] = "unreadable"
        info["message"] = f"{type(exc).__name__}: {exc}"
        return info

    try:
        import os as _os
        from datetime import datetime as _datetime, timezone as _timezone

        mtime = LIVE_ACCOUNT_SYNC_FILE.stat().st_mtime
        age_hours = (
            _datetime.now(tz=_timezone.utc).timestamp() - mtime
        ) / 3600.0
        info["ageHours"] = round(age_hours, 2)
    except OSError:
        info["ageHours"] = None
        age_hours = float("inf")

    info["verdict"] = payload.get("verdict")
    info["matchedSuffix"] = payload.get("matchedSuffix")
    info["netLiquidatingValue"] = _coerce_float(payload.get("netLiquidatingValue"))
    cash = _coerce_float(payload.get("totalCash"))

    if not payload.get("ok"):
        info["source"] = "blocked"
        info["message"] = (
            payload.get("message")
            or "live account sync did not produce a healthy snapshot"
        )
        return info
    if cash is None:
        info["source"] = "no-cash-field"
        info["message"] = "live sync ran but did not include totalCash"
        return info
    if info["ageHours"] is not None and info["ageHours"] > LIVE_CASH_STALE_HOURS:
        info["source"] = "stale"
        info["message"] = (
            f"live cash readout is {info['ageHours']:.1f}h old "
            f"(threshold {LIVE_CASH_STALE_HOURS}h); not trusting it"
        )
        info["cash"] = cash  # we record it but don't use it
        return info

    info["cash"] = cash
    info["source"] = "live"
    info["message"] = (
        f"live cash ${cash:,.2f} pulled from account suffix "
        f"{info['matchedSuffix']} ({info['ageHours']:.1f}h old)"
    )
    return info


def _load_snapshot() -> dict[str, Any]:
    """Read the canonical dashboard snapshot. Returns ``{}`` when missing."""
    path = DATA_DIR / "latest_snapshot.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _candidate_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Find the slate rows in whichever shape the snapshot stores them."""
    for key in ("rows", "scoredRows", "items", "tickers"):
        value = snapshot.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _coerce_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def evaluate_gates(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return ``(passes_all_gates, failed_gate_labels)``."""
    failures: list[str] = []

    ready = _coerce_int(row.get("readyScore") or row.get("Ready Score"))
    if ready is None or ready < MIN_READY_SCORE:
        failures.append(f"readyScore={ready} < {MIN_READY_SCORE}")

    confidence = _coerce_int(row.get("confidence") or row.get("Confidence (3 MAX)"))
    if confidence is None or confidence < MIN_CONFIDENCE:
        failures.append(f"confidence={confidence} < {MIN_CONFIDENCE}")

    dte = _coerce_int(row.get("daysUntilEarnings") or row.get("Days until earnings"))
    if dte is None or dte > MAX_DAYS_UNTIL_EARNINGS:
        failures.append(f"DTE={dte} > {MAX_DAYS_UNTIL_EARNINGS}")

    setup = _coerce_str(row.get("setupRec") or row.get("Setup Rec"))
    if setup in BANNED_SETUPS or not setup:
        failures.append(f"setup={setup!r} is banned or missing")

    trigger = _coerce_str(row.get("signalTrigger") or row.get("Signal Trigger"))
    if not trigger:
        failures.append("signalTrigger missing")

    return len(failures) == 0, failures


def filter_qualified(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the slate rows that clear every gate, sorted by ready score desc."""
    qualified: list[dict[str, Any]] = []
    for row in rows:
        passes, _ = evaluate_gates(row)
        if not passes:
            continue
        qualified.append(row)
    qualified.sort(
        key=lambda r: (
            -(_coerce_int(r.get("readyScore") or r.get("Ready Score")) or 0),
            (_coerce_int(r.get("daysUntilEarnings") or r.get("Days until earnings")) or 99),
        )
    )
    return qualified


def size_tickets(
    qualified: list[dict[str, Any]],
    *,
    cash: float = DEFAULT_CASH,
    max_tickets: int = DEFAULT_MAX_TICKETS,
) -> dict[str, Any]:
    """Allocate cash across the top-N qualified tickets.

    Even split, then capped at quarter-Kelly per ticket and at the
    desk's ``HARD_CAP_PER_TICKET``. The daily total is then capped at
    ``HARD_CAP_PER_DAY``.
    """
    if cash <= 0 or max_tickets <= 0 or not qualified:
        return {
            "cash": cash,
            "targetTickets": max_tickets,
            "actualTickets": 0,
            "perTicket": 0.0,
            "totalDeployed": 0.0,
            "tickets": [],
            "binding": "no-candidates" if not qualified else "no-cash",
        }

    n = min(len(qualified), max_tickets)
    even = cash / n
    quarter_kelly = QUARTER_KELLY_CAP_FRACTION * cash
    per_ticket = min(even, quarter_kelly, HARD_CAP_PER_TICKET)
    per_ticket = round(per_ticket, 2)

    tickets: list[dict[str, Any]] = []
    total = 0.0
    for row in qualified[:n]:
        if total + per_ticket > HARD_CAP_PER_DAY:
            break
        ticker = _coerce_str(row.get("ticker") or row.get("Ticker"))
        tickets.append({
            "ticker": ticker,
            "readyScore": _coerce_int(row.get("readyScore") or row.get("Ready Score")),
            "confidence": _coerce_int(row.get("confidence") or row.get("Confidence (3 MAX)")),
            "daysUntilEarnings": _coerce_int(row.get("daysUntilEarnings") or row.get("Days until earnings")),
            "setupRec": _coerce_str(row.get("setupRec") or row.get("Setup Rec")),
            "signalTrigger": _coerce_str(row.get("signalTrigger") or row.get("Signal Trigger")),
            "dollarAllocation": per_ticket,
        })
        total += per_ticket

    binding = "even-split"
    if abs(per_ticket - quarter_kelly) < 1e-6:
        binding = "quarter-kelly-cap"
    elif abs(per_ticket - HARD_CAP_PER_TICKET) < 1e-6:
        binding = "hard-cap-per-ticket"
    if total >= HARD_CAP_PER_DAY - 1e-6:
        binding = "hard-cap-per-day"

    return {
        "cash": cash,
        "targetTickets": max_tickets,
        "actualTickets": len(tickets),
        "perTicket": per_ticket,
        "totalDeployed": round(total, 2),
        "tickets": tickets,
        "binding": binding,
    }


def resolve_cash(
    *,
    cli_cash: float | None = None,
    env_cash: float | None = None,
) -> tuple[float, dict[str, Any]]:
    """Decide which cash number to use today.

    Precedence (highest first):
    1. Live TOS readout from ``inferno_live_account_sync.json`` when fresh and healthy.
    2. Explicit ``cli_cash`` override (``--cash`` on the CLI).
    3. ``INFERNO_OPERATOR_CASH`` env var.
    4. ``DEFAULT_CASH`` baked-in fallback.

    Returns ``(cash, source_info)`` so the briefing can show the operator
    *why* it chose this number.
    """
    live = load_live_cash()
    if live["source"] == "live" and isinstance(live["cash"], (int, float)):
        return float(live["cash"]), {
            "chosenSource": "live-tos",
            "live": live,
            "cliCash": cli_cash,
            "envCash": env_cash,
        }
    if cli_cash is not None:
        return float(cli_cash), {
            "chosenSource": "cli-override",
            "live": live,
            "cliCash": cli_cash,
            "envCash": env_cash,
        }
    if env_cash is not None:
        return float(env_cash), {
            "chosenSource": "env-override",
            "live": live,
            "cliCash": cli_cash,
            "envCash": env_cash,
        }
    return DEFAULT_CASH, {
        "chosenSource": "default",
        "live": live,
        "cliCash": cli_cash,
        "envCash": env_cash,
    }


def build_briefing(
    *,
    cash: float | None = None,
    max_tickets: int = DEFAULT_MAX_TICKETS,
    cli_cash: float | None = None,
) -> dict[str, Any]:
    snapshot = _load_snapshot()
    rows = _candidate_rows(snapshot)
    qualified = filter_qualified(rows)

    if cash is not None:
        resolved_cash, cash_source = float(cash), {
            "chosenSource": "explicit",
            "live": load_live_cash(),
            "cliCash": cli_cash,
            "envCash": None,
        }
    else:
        env_cash = (
            float(os.environ["INFERNO_OPERATOR_CASH"])
            if os.environ.get("INFERNO_OPERATOR_CASH")
            else None
        )
        resolved_cash, cash_source = resolve_cash(
            cli_cash=cli_cash, env_cash=env_cash,
        )

    sizing = size_tickets(qualified, cash=resolved_cash, max_tickets=max_tickets)
    sizing["cashSource"] = cash_source

    # Pull paper-bootstrap proposals so the email can pivot to research
    # work when the live filter blanks out.
    bootstrap_info = _load_paper_bootstrap()
    # Pull the percentile-ranked slate so the email can surface
    # rank-based candidates regardless of the absolute-threshold gate.
    ranked_info = _load_ranked_slate()
    ranked_info = _load_ranked_slate()

    if not rows:
        verdict = "no-slate"
        narrative = (
            "No slate snapshot found at data/latest_snapshot.json. "
            "Run the dawn pipeline before relying on this briefing."
        )
    elif not qualified:
        verdict = "no-candidates"
        bs_count = bootstrap_info.get("proposalCount") or 0
        if bs_count > 0:
            narrative = (
                f"Scanned {len(rows)} ticker(s); none cleared all five live "
                f"conviction gates. Sit on live cash — but {bs_count} paper-bootstrap "
                "proposal(s) are queued below for shadow-evidence work. "
                "Their outcomes feed the Phase-2 promotion math, not live authority."
            )
        else:
            narrative = (
                f"Scanned {len(rows)} ticker(s) on the slate; none cleared all five "
                "conviction gates today and no paper-bootstrap proposals queued. Sit on cash."
            )
    elif sizing["actualTickets"] == 0:
        verdict = "no-cash"
        narrative = "Candidates exist but cash sizing produced zero tickets — check INFERNO_OPERATOR_CASH."
    else:
        verdict = "ready-to-execute"
        narrative = (
            f"{sizing['actualTickets']} ticket(s) ready at ${sizing['perTicket']:.2f} "
            f"each (${sizing['totalDeployed']:.2f} total). Binding constraint: {sizing['binding']}."
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": OPERATOR_BRIEFING_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "slateSize": len(rows),
        "qualifiedCount": len(qualified),
        "sizing": sizing,
        "gates": {
            "minReadyScore": MIN_READY_SCORE,
            "minConfidence": MIN_CONFIDENCE,
            "maxDaysUntilEarnings": MAX_DAYS_UNTIL_EARNINGS,
            "bannedSetups": sorted(BANNED_SETUPS),
        },
        "caps": {
            "hardCapPerTicket": HARD_CAP_PER_TICKET,
            "hardCapPerDay": HARD_CAP_PER_DAY,
            "quarterKellyFraction": QUARTER_KELLY_CAP_FRACTION,
        },
        "paperBootstrap": bootstrap_info,
        "rankedSlate": ranked_info,
    }


def render_text(payload: dict[str, Any]) -> str:
    """Plain-text email body."""
    sizing = payload.get("sizing") or {}
    tickets = sizing.get("tickets") or []
    cash_source = sizing.get("cashSource") or {}
    live = cash_source.get("live") or {}
    chosen = cash_source.get("chosenSource") or "unknown"
    cash_line = f"Deployable cash: ${sizing.get('cash', 0):,.2f}  (source: {chosen})"
    if chosen == "live-tos" and live.get("matchedSuffix"):
        cash_line += f" — TOS suffix {live['matchedSuffix']}, {live.get('ageHours')}h old"
    elif chosen != "live-tos" and live.get("source"):
        cash_line += f" — live readout: {live.get('source')} ({live.get('message')})"

    lines = [
        "INFERNO OPERATOR BRIEFING",
        "=" * 60,
        "",
        f"Date: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        "",
        payload.get("narrative") or "",
        "",
        "TODAY'S PLAN",
        "-" * 60,
        cash_line,
        f"Target tickets:  {sizing.get('targetTickets')}",
        f"Actual tickets:  {sizing.get('actualTickets')}",
        f"Per ticket:      ${sizing.get('perTicket', 0):,.2f}",
        f"Total deployed:  ${sizing.get('totalDeployed', 0):,.2f}",
        f"Binding cap:     {sizing.get('binding')}",
        "",
    ]

    if tickets:
        lines.append("CANDIDATES (in order of conviction)")
        lines.append("-" * 60)
        lines.append(f"{'#':>2} {'Ticker':<8} {'Ready':>6} {'Conf':>5} {'DTE':>4} {'Setup':<14} ${'Alloc':<8}")
        for i, t in enumerate(tickets, 1):
            lines.append(
                f"{i:>2} {str(t['ticker'])[:8]:<8} "
                f"{t.get('readyScore', 0):>6} "
                f"{t.get('confidence', 0):>5} "
                f"{t.get('daysUntilEarnings', 0):>4} "
                f"{str(t.get('setupRec'))[:14]:<14} "
                f"${t.get('dollarAllocation', 0):,.2f}"
            )
            trigger = t.get("signalTrigger")
            if trigger:
                lines.append(f"   trigger: {trigger}")
        lines.append("")

    ranked = payload.get("rankedSlate") or {}
    ranked_rows = ranked.get("topByComposite") or []
    if not tickets and ranked_rows:
        lines.append("RANKED SLATE FALLBACK (relative strength; not live authority)")
        lines.append("-" * 60)
        lines.append(
            f"Verdict: {ranked.get('verdict')}  "
            f"passing ready-rank gate: {ranked.get('passingCount')} / {ranked.get('slateSize')}  "
            f"gate percentile: {ranked.get('gatePercentile')}"
        )
        lines.append(f"{'#':>2} {'Ticker':<8} {'CompR':>6} {'ReadyR':>7} {'IVR':>6} {'RawReady':>8} {'Gate'}")
        for i, row in enumerate(ranked_rows, 1):
            gate = "PASS" if row.get("passesReadyPercentileGate") else "-"
            lines.append(
                f"{i:>2} {str(row.get('ticker'))[:8]:<8} "
                f"{row.get('compositeRank') if row.get('compositeRank') is not None else '-':>6} "
                f"{row.get('readyRank') if row.get('readyRank') is not None else '-':>7} "
                f"{row.get('ivPercentileRank') if row.get('ivPercentileRank') is not None else '-':>6} "
                f"{row.get('readyScoreRaw') if row.get('readyScoreRaw') is not None else '-':>8} "
                f"{gate}"
            )
        lines.append("")
        lines.append("Use this as review context only. It does not override the five live gates.")
        lines.append("")

    ranked = payload.get("rankedSlate") or {}
    ranked_rows = ranked.get("topByComposite") or []
    if ranked_rows:
        gate_pct = ranked.get("gatePercentile")
        passing_n = ranked.get("passingCount") or 0
        slate_n = ranked.get("slateSize") or 0
        top_n = int(100 - gate_pct) if isinstance(gate_pct, (int, float)) else None
        lines.append("RANKED-BY-PERCENTILE CANDIDATES (scale-invariant; cross-sectional)")
        lines.append("-" * 60)
        if top_n is not None:
            lines.append(
                f"Top {top_n}% gate (readyRank >= {gate_pct}): "
                f"{passing_n} of {slate_n} pass."
            )
        lines.append(
            f"{'#':>2} {'Ticker':<8} {'Comp':>6} {'ReadyR':>7} {'IV%R':>6} "
            f"{'Ready':>8} {'Gate'}"
        )
        for i, r in enumerate(ranked_rows, 1):
            comp = r.get("compositeRank")
            ready_r = r.get("readyRank")
            iv_r = r.get("ivPercentileRank")
            raw = r.get("readyScoreRaw")
            gate = "PASS" if r.get("passesReadyPercentileGate") else "-"
            lines.append(
                f"{i:>2} {str(r.get('ticker'))[:8]:<8} "
                f"{comp if comp is not None else '-':>6} "
                f"{ready_r if ready_r is not None else '-':>7} "
                f"{iv_r if iv_r is not None else '-':>6} "
                f"{raw if raw is not None else '-':>8} "
                f"{gate}"
            )
        lines.append("")
        lines.append(
            "Composite is the geometric mean of Ready/Value/Momentum/Squeeze ranks."
        )
        lines.append(
            "These rank highest on this slate — they're not auto-approved trades."
        )
        lines.append("")

    bootstrap = payload.get("paperBootstrap") or {}
    bootstrap_proposals = bootstrap.get("proposals") or []
    if bootstrap_proposals:
        lines.append("PAPER-BOOTSTRAP PROPOSALS (shadow-evidence seed; not live)")
        lines.append("-" * 60)
        budget = bootstrap.get("ticketDollars")
        lines.append(
            f"Verdict: {bootstrap.get('verdict')}  "
            f"proposals: {bootstrap.get('proposalCount')}  "
            f"live-quality: {bootstrap.get('liveQualityCount')}  "
            f"paper-only: {bootstrap.get('paperOnlyCount')}  "
            f"@ ${budget}/ticket paper"
        )
        lines.append(
            f"{'#':>2} {'Ticker':<8} {'Score':>5} {'Ready':>6} {'Conf':>5} "
            f"{'DTE':>4} {'Strategy':<14} {'Missing gates'}"
        )
        for i, p in enumerate(bootstrap_proposals, 1):
            failed = ", ".join(p.get("failedGates") or []) or "(none)"
            lines.append(
                f"{i:>2} {str(p.get('ticker'))[:8]:<8} "
                f"{p.get('score'):>5} "
                f"{p.get('readyScore') or 0:>6} "
                f"{p.get('confidence') or 0:>5} "
                f"{p.get('daysUntilEarnings') or 0:>4} "
                f"{str(p.get('suggestedStrategy'))[:14]:<14} "
                f"{failed}"
            )
        lines.append("")
        lines.append("These are PAPER seeds — they do NOT count toward live promotion math.")
        lines.append("Stage via: ./run_inferno_paper_test_director.sh")
        lines.append("")

    gates = payload.get("gates") or {}
    lines.extend([
        "CONVICTION GATES",
        "-" * 60,
        f"  - Ready Score >= {gates.get('minReadyScore')}",
        f"  - Confidence >= {gates.get('minConfidence')}",
        f"  - Days until earnings <= {gates.get('maxDaysUntilEarnings')}",
        f"  - Setup Rec not in {gates.get('bannedSetups')}",
        f"  - Signal Trigger must be present",
        "",
    ])

    lines.extend([
        "NEXT STEPS (the seven-step checklist)",
        "-" * 60,
        "  1. python3 inferno_doctor.py            (confirm desk healthy)",
        "  2. python3 inferno_brain_console.py     (one-screen state)",
        "  3. Apply the five gates above to today's slate",
        "  4. ./run_inferno_strike_cycle.sh        (paper-stage strikes)",
        "  5. ./run_inferno_broker_preview.sh      (read the order ticket)",
        "  6. Place the trade yourself in the already-open TOS window",
        "  7. ./run_inferno_tos_fill_ingest.sh     (log fills for feedback loop)",
        "",
        "  Full checklist: docs/TRADING_DAY_CHECKLIST.md",
        "",
        "WHAT THE DESK WILL NOT DO",
        "-" * 60,
        "  - Click submit. The desk's authority is paper-evidence-only.",
        "  - Pick tickets you didn't explicitly want.",
        "  - Override the conviction gates because a chart looks good.",
        "",
        "If fewer than 3 tickets clear the gates, cash is a valid position.",
        "There is no penalty for sitting out a day. The market opens again tomorrow.",
        "",
    ])
    return "\n".join(lines).rstrip() + "\n"


def render_html(payload: dict[str, Any]) -> str:
    """Email-friendly HTML body."""
    sizing = payload.get("sizing") or {}
    tickets = sizing.get("tickets") or []
    gates = payload.get("gates") or {}

    rows_html = ""
    for i, t in enumerate(tickets, 1):
        trigger = t.get("signalTrigger") or ""
        rows_html += f"""
        <tr>
          <td>{i}</td>
          <td><strong>{t.get('ticker')}</strong></td>
          <td style="text-align:right">{t.get('readyScore', 0)}</td>
          <td style="text-align:right">{t.get('confidence', 0)}</td>
          <td style="text-align:right">{t.get('daysUntilEarnings', 0)}</td>
          <td>{t.get('setupRec', '')}</td>
          <td style="text-align:right">${t.get('dollarAllocation', 0):,.2f}</td>
          <td>{trigger}</td>
        </tr>"""

    verdict = payload.get("verdict") or "unknown"
    verdict_color = {
        "ready-to-execute": "#0a7f2e",
        "no-candidates": "#a86a00",
        "no-slate": "#a02020",
        "no-cash": "#a02020",
    }.get(verdict, "#444444")

    return f"""<!DOCTYPE html>
<html><body style="font-family: -apple-system, system-ui, sans-serif; max-width: 720px; margin: auto; color: #222;">
  <h1 style="border-bottom: 2px solid #b22222; padding-bottom: 8px;">Inferno Operator Briefing</h1>
  <p style="color:#666;">{payload.get('generatedAt')}</p>
  <p><strong>Verdict:</strong> <span style="color:{verdict_color}; font-weight:bold;">{verdict}</span></p>
  <p>{payload.get('narrative', '')}</p>

  <h2>Today's Plan</h2>
  {(lambda cs: f'''<p style="color:#666; font-size:12px; margin:0 0 8px 0;">Cash source: <strong>{cs.get('chosenSource')}</strong>{(' — TOS suffix ' + str((cs.get('live') or {}).get('matchedSuffix')) + ', ' + str((cs.get('live') or {}).get('ageHours')) + 'h old') if cs.get('chosenSource') == 'live-tos' else ''}</p>''')(sizing.get('cashSource') or {})}
  <table style="border-collapse:collapse; width:100%;">
    <tr><td><strong>Deployable cash</strong></td><td style="text-align:right">${sizing.get('cash', 0):,.2f}</td></tr>
    <tr><td><strong>Tickets to place</strong></td><td style="text-align:right">{sizing.get('actualTickets')} of {sizing.get('targetTickets')} target</td></tr>
    <tr><td><strong>Per ticket</strong></td><td style="text-align:right">${sizing.get('perTicket', 0):,.2f}</td></tr>
    <tr><td><strong>Total deployed</strong></td><td style="text-align:right">${sizing.get('totalDeployed', 0):,.2f}</td></tr>
    <tr><td><strong>Binding cap</strong></td><td style="text-align:right">{sizing.get('binding')}</td></tr>
  </table>

  <h2>Candidates</h2>
  <table style="border-collapse:collapse; width:100%; font-size: 13px;">
    <thead><tr style="background:#f0f0f0;">
      <th style="text-align:left; padding:6px;">#</th>
      <th style="text-align:left; padding:6px;">Ticker</th>
      <th style="text-align:right; padding:6px;">Ready</th>
      <th style="text-align:right; padding:6px;">Conf</th>
      <th style="text-align:right; padding:6px;">DTE</th>
      <th style="text-align:left; padding:6px;">Setup</th>
      <th style="text-align:right; padding:6px;">Allocation</th>
      <th style="text-align:left; padding:6px;">Trigger</th>
    </tr></thead>
    <tbody>{rows_html if rows_html else '<tr><td colspan="8" style="padding:12px; color:#888;">No candidates cleared the gates today.</td></tr>'}</tbody>
  </table>

  <h2>Conviction Gates</h2>
  <ul>
    <li>Ready Score &ge; {gates.get('minReadyScore')}</li>
    <li>Confidence &ge; {gates.get('minConfidence')}</li>
    <li>Days until earnings &le; {gates.get('maxDaysUntilEarnings')}</li>
    <li>Setup Rec not in {gates.get('bannedSetups')}</li>
    <li>Signal Trigger must be present</li>
  </ul>

  <h2>Next Steps</h2>
  <ol>
    <li><code>python3 inferno_doctor.py</code> &mdash; confirm desk healthy</li>
    <li><code>python3 inferno_brain_console.py</code> &mdash; one-screen state</li>
    <li>Apply the five gates above to today&rsquo;s slate</li>
    <li><code>./run_inferno_strike_cycle.sh</code> &mdash; paper-stage strikes</li>
    <li><code>./run_inferno_broker_preview.sh</code> &mdash; read the order ticket</li>
    <li>Place the trade yourself in the already-open TOS window</li>
    <li><code>./run_inferno_tos_fill_ingest.sh</code> &mdash; log fills for feedback loop</li>
  </ol>

  <p style="color:#666; font-size:12px; margin-top: 24px; border-top:1px solid #ddd; padding-top:12px;">
    The desk's authority is paper-evidence-only. The math filters and sizes; the operator clicks submit.
    Full checklist: <code>docs/TRADING_DAY_CHECKLIST.md</code>.
  </p>
</body></html>"""


def save_briefing(payload: dict[str, Any]) -> tuple[Path, Path]:
    ensure_dirs()
    text_body = render_text(payload)
    html_body = render_html(payload)
    atomic_write_text(OPERATOR_BRIEFING_TEXT_FILE, text_body)
    atomic_write_text(OPERATOR_BRIEFING_HTML_FILE, html_body)
    return OPERATOR_BRIEFING_TEXT_FILE, OPERATOR_BRIEFING_HTML_FILE


def send_email(payload: dict[str, Any]) -> dict[str, Any]:
    """Send the briefing via the same SMTP envvars the morning brief uses."""
    host = os.environ.get("SMTP_HOST", "").strip()
    port = int(os.environ.get("SMTP_PORT", "587") or 587)
    sender = os.environ.get("SMTP_FROM", "").strip()
    recipient = os.environ.get("SMTP_TO", "").strip()
    username = os.environ.get("SMTP_USERNAME", "").strip() or sender
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    use_ssl = str(os.environ.get("SMTP_USE_SSL", "false")).lower() in {"1", "true", "yes"}

    if not (host and sender and recipient):
        return {"ok": False, "reason": "SMTP_HOST / SMTP_FROM / SMTP_TO not all set"}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Inferno Operator Briefing — {payload.get('verdict', 'unknown')}"
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(render_text(payload), "plain", "utf-8"))
    msg.attach(MIMEText(render_html(payload), "html", "utf-8"))

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls()
        if password:
            server.login(username, password)
        server.sendmail(sender, [recipient], msg.as_string())
        server.quit()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

    return {"ok": True, "recipient": recipient}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Produce the daily operator briefing — slate filtered, cash sized, "
            "checklist included. Research-only; never places a trade."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--cash", type=float, default=None,
                        help=(
                            "Override deployable cash. Default behaviour reads "
                            "the live TOS readout from data/inferno_live_account_sync.json "
                            "when it's fresh; falls back to INFERNO_OPERATOR_CASH env "
                            "var, then to the baked-in default."
                        ))
    parser.add_argument("--tickets", type=int, default=DEFAULT_MAX_TICKETS,
                        help=f"Target ticket count (default {DEFAULT_MAX_TICKETS}).")
    parser.add_argument("--email", action="store_true",
                        help="Send the briefing via SMTP after generating it.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and OPERATOR_BRIEFING_TEXT_FILE.exists():
        print(OPERATOR_BRIEFING_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_briefing(max_tickets=args.tickets, cli_cash=args.cash)
    text_path, html_path = save_briefing(payload)
    print(render_text(payload))
    print(f"\nSaved: {text_path}\nSaved: {html_path}")
    if args.email:
        result = send_email(payload)
        if result.get("ok"):
            print(f"\nEmail sent to {result.get('recipient')}.")
        else:
            print(f"\nEmail not sent: {result.get('reason')}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
