from __future__ import annotations

"""Broker-preview adapter for paper-approved Inferno tickets.

This module does not connect to Schwab, thinkorswim, or any live broker. It
translates clean paper-staged tickets into broker-neutral preview payloads so we
can harden order construction before adding OAuth, account selection, or submit
authority.
"""

import argparse
import json
from typing import Any

from inferno_config import BROKER_ADAPTER_MODE, BROKER_API_TARGET, BROKER_EXECUTION_SURFACE, local_now
from inferno_paper_execution import load_ledger
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


BROKER_PREVIEW_FILE = DATA_DIR / "inferno_broker_preview.json"
BROKER_PREVIEW_TEXT_FILE = REPORTS_DIR / "broker_preview_latest.txt"
SAFE_PREVIEW_MODES = {"OFF", "READ_ONLY", "PREVIEW_ONLY", "PAPER"}


def eligible_paper_tickets(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Return tickets clean enough for offline broker payload construction."""
    tickets: list[dict[str, Any]] = []
    for item in ledger.get("items", []):
        outcome = item.get("outcome") or {}
        verdict = item.get("riskVerdict") or {}
        if item.get("status") != "paper-staged":
            continue
        if item.get("paperVariantOnly"):
            continue
        if outcome.get("status") != "open":
            continue
        if not verdict.get("passed"):
            continue
        if item.get("liveTradingAllowed"):
            continue
        tickets.append(item)
    return tickets


def order_type_for_ticket(ticket: dict[str, Any]) -> str:
    """Map entry cost type to a broker-neutral order type."""
    if ticket.get("entryCostType") == "credit":
        return "NET_CREDIT_LIMIT"
    if ticket.get("entryCostType") == "debit":
        return "NET_DEBIT_LIMIT"
    return "LIMIT_REVIEW_REQUIRED"


def leg_payload(leg: dict[str, Any]) -> dict[str, Any]:
    """Convert one option leg to an order-leg preview shape."""
    return {
        "instruction": leg.get("instruction"),
        "assetType": "OPTION",
        "symbol": leg.get("symbol"),
        "putCall": leg.get("putCall"),
        "strike": leg.get("strike"),
        "expiration": leg.get("expiration"),
        "quantity": 1,
        "bid": leg.get("bid"),
        "ask": leg.get("ask"),
        "mid": leg.get("mid"),
    }


def build_preview_order(ticket: dict[str, Any]) -> dict[str, Any]:
    """Build a broker-neutral order preview from one paper-staged ticket."""
    return {
        "previewOnly": True,
        "liveTradingAllowed": False,
        "brokerSurface": BROKER_EXECUTION_SURFACE,
        "futureApiTarget": BROKER_API_TARGET,
        "ticketId": ticket.get("ticketId"),
        "ticker": ticket.get("ticker"),
        "strategy": ticket.get("strategy"),
        "orderType": order_type_for_ticket(ticket),
        "duration": "DAY",
        "session": "NORMAL",
        "limitPrice": ticket.get("entryLimit"),
        "estimatedMaxLoss": ticket.get("estimatedMaxLoss"),
        "estimatedMaxProfit": ticket.get("estimatedMaxProfit"),
        "breakEven": ticket.get("breakEven"),
        "lowerBreakEven": ticket.get("lowerBreakEven"),
        "upperBreakEven": ticket.get("upperBreakEven"),
        "legs": [leg_payload(leg) for leg in ticket.get("legs", [])],
        "requiredBeforeLive": [
            "fresh broker quote",
            "official broker preview accepted",
            "human final approval",
            "daily risk gate still clear",
            "kill switch healthy",
        ],
    }


def build_broker_preview() -> dict[str, Any]:
    """Build the current offline broker-preview artifact."""
    ledger = load_ledger()
    mode = BROKER_ADAPTER_MODE
    tickets = eligible_paper_tickets(ledger) if mode in SAFE_PREVIEW_MODES else []
    orders = [build_preview_order(ticket) for ticket in tickets]
    blocked_reason = None
    if mode not in SAFE_PREVIEW_MODES:
        blocked_reason = f"broker adapter mode {mode} is not allowed for offline preview"
    return {
        "generatedAt": local_now().isoformat(),
        "adapterMode": mode,
        "brokerSurface": BROKER_EXECUTION_SURFACE,
        "futureApiTarget": BROKER_API_TARGET,
        "previewOnly": True,
        "liveTradingAllowed": False,
        "blockedReason": blocked_reason,
        "count": len(orders),
        "orders": orders,
    }


def preview_text(preview: dict[str, Any]) -> str:
    """Render the broker preview artifact for operator review."""
    lines = [
        "Inferno Broker Preview",
        "",
        f"Generated: {preview.get('generatedAt')}",
        f"Adapter mode: {preview.get('adapterMode')}",
        f"Surface: {preview.get('brokerSurface')}",
        f"Future API target: {preview.get('futureApiTarget')}",
        f"Preview only: {preview.get('previewOnly')}",
        f"Live trading allowed: {preview.get('liveTradingAllowed')}",
        f"Orders: {preview.get('count', 0)}",
        "",
    ]
    if preview.get("blockedReason"):
        lines.append(f"Blocked: {preview['blockedReason']}")
        return "\n".join(lines).rstrip() + "\n"

    if not preview.get("orders"):
        lines.append("No paper-staged tickets are clean enough for broker preview.")
        return "\n".join(lines).rstrip() + "\n"

    for order in preview.get("orders", []):
        lines.append(
            f"{order.get('ticker')} | {order.get('strategy')} | {order.get('orderType')} | "
            f"limit {order.get('limitPrice')} | max loss {order.get('estimatedMaxLoss')}"
        )
        for leg in order.get("legs", []):
            lines.append(
                f"  {leg.get('instruction')} {leg.get('putCall')} {leg.get('strike')} "
                f"{leg.get('symbol')} bid/ask {leg.get('bid')}/{leg.get('ask')}"
            )
        lines.append("  Required: " + "; ".join(order.get("requiredBeforeLive", [])))
    return "\n".join(lines).rstrip() + "\n"


def save_broker_preview(preview: dict[str, Any]) -> None:
    """Persist JSON and text versions of the broker preview."""
    ensure_dirs()
    BROKER_PREVIEW_FILE.write_text(json.dumps(preview, indent=2), encoding="utf-8")
    BROKER_PREVIEW_TEXT_FILE.write_text(preview_text(preview), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build offline broker-preview payloads from clean paper tickets.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and BROKER_PREVIEW_TEXT_FILE.exists():
        print(BROKER_PREVIEW_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    preview = build_broker_preview()
    save_broker_preview(preview)
    print(preview_text(preview))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
