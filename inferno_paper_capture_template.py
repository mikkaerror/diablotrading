from __future__ import annotations

"""Paper capture-template emitter (research-only).

Proven barrier this removes: a closed paper fill only scores toward the
30-outcome promotion gate when its CSV row carries (1) Inferno's internal
``ticketId`` -- which no thinkorswim export contains -- and (2)
timezone-aware ISO 8601 ``openedAt`` / ``closedAt`` timestamps, which TOS
does not emit either (see ``inferno_tos_fill_ingest.closed_fill_evidence_gaps``
and ``parse_execution_timestamp``). A human cannot realistically hand-build
that row from a raw export, which is why the closed-outcome count has sat
near zero for weeks even though the rest of the pipeline works.

This module closes that gap without crossing any safety line. For each
``paper-staged`` ticket in the execution ledger it emits one canonical
fill-log row, pre-filled with the immutable facts the operator cannot be
expected to know or retype -- the internal ticketId, ticker, strategy,
expiration, paperMoney environment, and contract count -- and leaves exactly
the fields that are genuine execution evidence blank: ``entryPrice``,
``exitPrice``, ``openedAt``, ``closedAt``, ``status``, ``realizedPnl``. The
companion instruction sheet spells out the required tz-aware ISO timestamp
format so a filled row imports and scores on the first try.

Safety:

- It reads the execution ledger read-only and writes only a *template* file
  in the reports area. It never writes the live fill log or the ledger, and
  it records no execution facts -- the operator supplies those by hand.
- It stages, approves, closes, and promotes nothing. Emitting a worksheet is
  not staging, exactly as the blank role-policy packet is not a policy.
- No risk constant, eligibility, broker, or authority state is touched.

Citations (light): Theory of Constraints (THEORY-CONSTRAINTS-GOLDRATT-1984)
-- lift the binding constraint (turning a real fill into a scorable outcome),
not the non-constraints.
"""

import argparse
import csv
import io
from datetime import date
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file

try:  # canonical schema + the exact environment token the scorer accepts
    from inferno_tos_sandbox import FILL_LOG_COLUMNS
except Exception:  # pragma: no cover - defensive fallback if sandbox import shifts
    FILL_LOG_COLUMNS = [
        "sessionDate", "ticketId", "ticker", "strategy", "expiration", "environment",
        "paperAccount", "routeFamily", "orderType", "contracts", "entryPrice", "exitPrice",
        "realizedPnl", "status", "openedAt", "closedAt", "notes",
    ]

EXECUTION_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
CAPTURE_TEMPLATE_FILE = DATA_DIR / "inferno_paper_capture_template.json"
CAPTURE_TEMPLATE_CSV = REPORTS_DIR / "paper_capture_template_latest.csv"
CAPTURE_TEMPLATE_TEXT_FILE = REPORTS_DIR / "paper_capture_template_latest.txt"

CAPTURE_TEMPLATE_STAGE = "paper-capture-template-research-only"

# The scorer lowercases and compares against this exact token.
PAPER_MONEY_ENVIRONMENT = "thinkorswim-paperMoney"

# Fields the operator must supply from their actual paperMoney fills. Left
# blank on purpose so the template can never masquerade as an executed order.
OPERATOR_SUPPLIED_FIELDS = ("entryPrice", "exitPrice", "realizedPnl", "status", "openedAt", "closedAt")


def text(value: Any) -> str:
    """Normalize arbitrary values into trimmed text."""
    return str(value or "").strip()


def _is_expired(expiration: str, today: date) -> bool:
    """True only when the expiration is a real date strictly before today.

    Fails open: an empty or unparseable expiration is NOT treated as expired,
    so a staged ticket is never silently dropped on a formatting quirk.
    """
    raw = text(expiration)
    if not raw:
        return False
    try:
        return date.fromisoformat(raw[:10]) < today
    except ValueError:
        return False


def _contracts_for(ticket: dict[str, Any]) -> str:
    """Best-effort contract count; defaults to 1 for a single defined-risk spread."""
    contracts = ticket.get("contracts")
    try:
        value = int(contracts)
        if value > 0:
            return str(value)
    except (TypeError, ValueError):
        pass
    return "1"


def _template_row(ticket: dict[str, Any], session_date: str) -> dict[str, str]:
    """Build one canonical fill-log row with immutable facts filled, evidence blank."""
    row = {column: "" for column in FILL_LOG_COLUMNS}
    row["sessionDate"] = session_date
    row["ticketId"] = text(ticket.get("ticketId"))
    row["ticker"] = text(ticket.get("ticker")).upper()
    row["strategy"] = text(ticket.get("strategy"))
    row["expiration"] = text(ticket.get("expiration"))
    row["environment"] = PAPER_MONEY_ENVIRONMENT
    row["paperAccount"] = "paperMoney"
    row["routeFamily"] = text(ticket.get("setupRec") or ticket.get("routeFamily"))
    row["orderType"] = text(ticket.get("entryCostType") or "NET_DEBIT_LIMIT")
    row["contracts"] = _contracts_for(ticket)
    row["notes"] = "fill entry/exit prices, status, and tz-aware ISO timestamps before import"
    # OPERATOR_SUPPLIED_FIELDS deliberately left blank.
    return row


def build_capture_template(ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    """Emit a canonical capture template for every paper-staged ticket.

    Reads the execution ledger only. Never mutates the ledger or the live
    fill log.
    """
    if ledger is None:
        ledger = load_json_file(EXECUTION_LEDGER_FILE)

    now = local_now()
    generated_at = now.isoformat()
    session_date = generated_at[:10]
    today = now.date()
    items = (ledger or {}).get("items") or []
    staged = [item for item in items if text(item.get("status")) == "paper-staged"]

    # A staged ticket whose option has already expired cannot be traded, so it
    # must never appear as a fillable row -- filling it would fabricate a scored
    # outcome on a dead contract. Surface it separately as cleanup instead.
    live = [t for t in staged if not _is_expired(t.get("expiration"), today)]
    expired = [t for t in staged if _is_expired(t.get("expiration"), today)]

    rows = [_template_row(ticket, session_date) for ticket in live]
    stale = [
        {
            "ticker": text(t.get("ticker")).upper(),
            "strategy": text(t.get("strategy")),
            "ticketId": text(t.get("ticketId")),
            "expiration": text(t.get("expiration")),
        }
        for t in expired
    ]
    return {
        "generatedAt": generated_at,
        "stage": CAPTURE_TEMPLATE_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "verdict": "templates-ready" if rows else "no-fillable-staged-tickets",
        "stagedTicketCount": len(staged),
        "fillableTicketCount": len(rows),
        "expiredTicketCount": len(stale),
        "columns": list(FILL_LOG_COLUMNS),
        "rows": rows,
        "expiredStagedTickets": stale,
        "operatorSuppliedFields": list(OPERATOR_SUPPLIED_FIELDS),
        "citations": ["THEORY-CONSTRAINTS-GOLDRATT-1984"],
    }


def template_csv_text(payload: dict[str, Any]) -> str:
    """Render the template rows as a canonical fill-log CSV string."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=payload.get("columns") or list(FILL_LOG_COLUMNS))
    writer.writeheader()
    for row in payload.get("rows") or []:
        writer.writerow(row)
    return buffer.getvalue()


def template_text(payload: dict[str, Any]) -> str:
    """Render operator instructions for filling and importing the template."""
    lines = [
        "Inferno Paper Capture Template (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Paper-staged tickets: {payload.get('stagedTicketCount', 0)}",
        "",
        "This is a worksheet. It stages and scores nothing. Fill the blank",
        "execution fields from your actual paperMoney fills, then import the CSV",
        "so the fill can score toward the 30-outcome promotion gate.",
        "",
        f"Template CSV: {CAPTURE_TEMPLATE_CSV}",
        "",
    ]

    stale = payload.get("expiredStagedTickets") or []

    rows = payload.get("rows") or []
    if not rows:
        lines.append("(no fillable paper-staged tickets; approve a candidate via ./inferno today first)")
        if stale:
            lines.append("")
            lines.append("Stale staged tickets (expired, NOT fillable -- consider cleaning up):")
            for t in stale:
                lines.append(f"  {t['ticker']:6} {t['strategy']:18} exp={t['expiration']} ticketId={t['ticketId']}")
        return "\n".join(lines).rstrip() + "\n"

    lines.append("Pre-filled per staged ticket (do not change these):")
    for row in rows:
        lines.append(
            f"  {row['ticker']:6} {row['strategy']:18} ticketId={row['ticketId']} "
            f"exp={row['expiration']} contracts={row['contracts']}"
        )
    lines.extend([
        "",
        "You fill only these fields, from your paperMoney fills:",
        "  entryPrice   net debit/credit you were filled at on entry (e.g. 2.30)",
        "  exitPrice    net price you were filled at on exit         (e.g. 4.10)",
        "  realizedPnl  realized dollar P/L for the closed spread    (e.g. 180)",
        "  status       closed-win  or  closed-loss",
        "  openedAt     entry fill time, timezone-aware ISO 8601",
        "  closedAt     exit fill time, timezone-aware ISO 8601 (>= openedAt)",
        "",
        "Timestamp format MUST be tz-aware ISO 8601 or the fill is rejected:",
        "  2026-07-23T10:05:00-06:00      (correct)",
        "  2026-07-23 10:05:00            (rejected: no timezone offset)",
        "  7/23/26 10:05 AM              (rejected: not ISO 8601)",
        "",
        "When done: save the CSV, drop it in ~/Downloads, and run",
        "  python3 inferno_downloads_manager.py",
        "then confirm it scored with",
        "  python3 inferno_tos_fill_ingest.py",
    ])
    if stale:
        lines.extend([
            "",
            "Stale staged tickets (expired, NOT fillable -- consider cleaning up):",
        ])
        for t in stale:
            lines.append(f"  {t['ticker']:6} {t['strategy']:18} exp={t['expiration']} ticketId={t['ticketId']}")
    return "\n".join(lines).rstrip() + "\n"


def save_capture_template(payload: dict[str, Any]) -> None:
    """Persist template artifacts only; never the ledger or live fill log."""
    ensure_dirs()
    atomic_write_json(CAPTURE_TEMPLATE_FILE, payload)
    atomic_write_text(CAPTURE_TEMPLATE_CSV, template_csv_text(payload))
    atomic_write_text(CAPTURE_TEMPLATE_TEXT_FILE, template_text(payload))


def parse_args() -> argparse.Namespace:
    """Parse CLI args for the capture-template emitter."""
    parser = argparse.ArgumentParser(
        description="Inferno paper capture-template emitter (research-only)"
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    """Build and emit the capture template, or print the last cached instructions."""
    args = parse_args()
    if args.command == "status" and CAPTURE_TEMPLATE_TEXT_FILE.exists():
        print(CAPTURE_TEMPLATE_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_capture_template()
    save_capture_template(payload)
    print(template_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
