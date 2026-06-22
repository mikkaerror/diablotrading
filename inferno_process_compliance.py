from __future__ import annotations

"""Research-only process-breach circuit breaker for new paper entries."""

import argparse
from collections import defaultdict
from typing import Any

from inferno_config import MAX_SINGLE_TICKET_DOLLARS, local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_trade_evidence import decision_card, max_loss_dollars, parse_date
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


PAPER_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
PAPER_MTM_FILE = DATA_DIR / "inferno_paper_mark_to_market.json"
PROCESS_FILE = DATA_DIR / "inferno_process_compliance.json"
PROCESS_TEXT_FILE = REPORTS_DIR / "process_compliance_latest.txt"
STAGE = "process-compliance-research-only"


def build_process_compliance(
    *,
    ledger: dict[str, Any] | None = None,
    mtm: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ledger = ledger if ledger is not None else (load_json_file(PAPER_LEDGER_FILE) or {})
    mtm = mtm if mtm is not None else (load_json_file(PAPER_MTM_FILE) or {})
    marks = mtm.get("marksByTicketId") or {}
    hard_breaches = []
    advisories = []
    open_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for item in ledger.get("items") or []:
        outcome_status = str((item.get("outcome") or {}).get("status") or "").lower()
        status = str(item.get("status") or "").lower()
        if outcome_status == "open":
            open_by_ticker[str(item.get("ticker") or "").upper()].append(item)
        if status == "paper-staged" and outcome_status in {"open", "not-opened"}:
            card = item.get("decisionCard") or decision_card(item)
            if not card.get("complete"):
                hard_breaches.append(
                    {
                        "ticketId": item.get("ticketId"),
                        "ticker": item.get("ticker"),
                        "type": "unplanned-entry",
                        "detail": card.get("noTradeReason") or "decision card incomplete",
                    }
                )
            risk = max_loss_dollars(item)
            if risk > MAX_SINGLE_TICKET_DOLLARS:
                hard_breaches.append(
                    {
                        "ticketId": item.get("ticketId"),
                        "ticker": item.get("ticker"),
                        "type": "size-breach",
                        "detail": f"max loss ${risk:.2f} exceeds ${MAX_SINGLE_TICKET_DOLLARS:.2f}",
                    }
                )

        if outcome_status == "closed":
            expiration = parse_date(item.get("expiration"))
            reviewed = parse_date((item.get("outcome") or {}).get("reviewedAt"))
            if expiration and reviewed and reviewed > expiration:
                advisories.append(
                    {
                        "ticketId": item.get("ticketId"),
                        "ticker": item.get("ticker"),
                        "type": "late-reconciliation",
                        "detail": f"outcome recorded {(reviewed - expiration).days} day(s) after expiration",
                    }
                )

    for ticker, items in open_by_ticker.items():
        if len(items) < 2:
            continue
        losing = []
        for item in items:
            mark = marks.get(str(item.get("ticketId") or "")) or {}
            if (mark.get("unrealizedPnlDollars") or 0) < 0:
                losing.append(item)
        if losing:
            hard_breaches.append(
                {
                    "ticker": ticker,
                    "type": "potential-averaging-down",
                    "detail": f"{len(items)} overlapping open tickets while at least one is losing",
                }
            )

    allowed = not hard_breaches
    return {
        "generatedAt": local_now().isoformat(),
        "stage": STAGE,
        "verdict": "clear" if allowed else "stop-new-paper-entries",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "newPaperEntriesAllowed": allowed,
        "counts": {
            "hardBreaches": len(hard_breaches),
            "advisories": len(advisories),
            "openTickers": len(open_by_ticker),
        },
        "hardBreaches": hard_breaches,
        "advisories": advisories,
        "recovery": (
            ["Resolve each hard breach", "rebuild decision cards and risk", "rerun this audit"]
            if not allowed
            else []
        ),
    }


def render(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Process Compliance",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"New paper entries allowed: {payload.get('newPaperEntriesAllowed')}",
        f"Counts: {payload.get('counts')}",
        "",
        "Hard breaches:",
    ]
    for row in payload.get("hardBreaches") or []:
        lines.append(f"- {row.get('ticker')} | {row.get('type')} | {row.get('detail')}")
    if not payload.get("hardBreaches"):
        lines.append("- none")
    lines.extend(["", "Advisories:"])
    for row in payload.get("advisories") or []:
        lines.append(f"- {row.get('ticker')} | {row.get('type')} | {row.get('detail')}")
    if not payload.get("advisories"):
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def save(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(PROCESS_FILE, payload)
    atomic_write_text(PROCESS_TEXT_FILE, render(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Inferno process compliance.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    args = parser.parse_args()
    if args.command == "status" and PROCESS_TEXT_FILE.exists():
        print(PROCESS_TEXT_FILE.read_text(encoding="utf-8"), end="")
        return 0
    payload = build_process_compliance()
    save(payload)
    print(render(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
