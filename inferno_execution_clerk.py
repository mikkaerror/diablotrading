from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

from inferno_config import (
    BROKER_API_TARGET,
    BROKER_EXECUTION_SURFACE,
    EXECUTION_ALLOWED_SETUPS,
    EXECUTION_MODE,
    EXECUTION_QUEUE_LIMIT,
    MAX_ACTIVE_EXECUTION_INTENTS,
    MAX_DAILY_RISK_UNITS,
    MAX_SINGLE_TRADE_RISK_UNITS,
)
from server import (
    APPROVAL_QUEUE_FILE,
    DATA_DIR,
    REPORTS_DIR,
    SNAPSHOT_FILE,
    ensure_dirs,
    load_json_file,
)


EXECUTION_QUEUE_FILE = DATA_DIR / "inferno_execution_queue.json"
EXECUTION_TEXT_FILE = REPORTS_DIR / "execution_desk_latest.txt"


def load_snapshot() -> dict[str, Any]:
    return load_json_file(SNAPSHOT_FILE) or {}


def load_approval_queue() -> dict[str, Any]:
    return load_json_file(APPROVAL_QUEUE_FILE) or {"generatedAt": None, "count": 0, "items": []}


def route_family(setup_rec: str) -> str:
    if setup_rec == "Vertical Call":
        return "defined-risk directional"
    if setup_rec == "Straddle":
        return "long-volatility event"
    if setup_rec == "Iron Condor":
        return "defined-risk premium"
    return "manual review"


def conviction_tier(row: dict[str, Any]) -> str:
    if row.get("readiness", 0) >= 86 and row.get("confidence", 0) >= 3:
        return "A"
    if row.get("readiness", 0) >= 76 and row.get("confidence", 0) >= 2:
        return "B"
    return "C"


def risk_units_for_row(row: dict[str, Any]) -> float:
    readiness = float(row.get("readiness", 0))
    confidence = float(row.get("confidence", 0))
    score = 0.45
    if readiness >= 86:
        score += 0.3
    elif readiness >= 76:
        score += 0.2
    if confidence >= 3:
        score += 0.2
    elif confidence >= 2:
        score += 0.1
    if row.get("signalTrigger"):
        score += 0.05
    if row.get("setupRec") == "Iron Condor":
        score -= 0.1
    return round(min(MAX_SINGLE_TRADE_RISK_UNITS, max(0.25, score)), 2)


def intent_blocks(row: dict[str, Any], approval_item: dict[str, Any] | None) -> list[str]:
    blocks: list[str] = []
    if row.get("setupRec") not in EXECUTION_ALLOWED_SETUPS:
        blocks.append("setup not approved for broker automation lane")
    if not row.get("signalTrigger"):
        blocks.append("trigger is not live")
    if approval_item and approval_item.get("approvalStatus") == "rejected":
        blocks.append("human reviewer rejected the name")
    if not approval_item or approval_item.get("approvalStatus") != "approved":
        blocks.append("human approval still required")
    return blocks


def build_execution_queue(
    snapshot: dict[str, Any] | None = None,
    approval_queue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = snapshot or load_snapshot()
    approval_queue = approval_queue or load_approval_queue()
    rows = snapshot.get("rows", [])
    rows_by_ticker = {row.get("ticker"): row for row in rows if row.get("ticker")}
    approvals_by_ticker = {item.get("ticker"): item for item in approval_queue.get("items", []) if item.get("ticker")}

    intents: list[dict[str, Any]] = []
    staged_risk = 0.0
    active_ready = 0

    for rank, ticker in enumerate(snapshot.get("reviewQueueTickers", [])[:EXECUTION_QUEUE_LIMIT], start=1):
        row = rows_by_ticker.get(ticker)
        if not row:
            continue

        approval_item = approvals_by_ticker.get(ticker)
        risk_units = risk_units_for_row(row)
        blocks = intent_blocks(row, approval_item)
        status = "blocked" if blocks else "approval-ready"

        if status == "approval-ready":
            if active_ready >= MAX_ACTIVE_EXECUTION_INTENTS:
                blocks.append("daily active intent cap reached")
                status = "blocked"
            elif staged_risk + risk_units > MAX_DAILY_RISK_UNITS:
                blocks.append("daily risk budget would be exceeded")
                status = "blocked"

        if status == "approval-ready":
            staged_risk += risk_units
            active_ready += 1

        intents.append(
            {
                "rank": rank,
                "ticker": ticker,
                "setupRec": row.get("setupRec"),
                "routeFamily": route_family(str(row.get("setupRec", ""))),
                "primaryRoute": row.get("rec1"),
                "secondaryRoute": row.get("rec2"),
                "readiness": row.get("readiness"),
                "confidence": row.get("confidence"),
                "daysUntilEarnings": row.get("daysUntilEarnings"),
                "signalTrigger": row.get("signalTrigger"),
                "price": row.get("price"),
                "priority": row.get("priority"),
                "convictionTier": conviction_tier(row),
                "riskUnits": risk_units,
                "approvalStatus": approval_item.get("approvalStatus", "pending") if approval_item else "pending",
                "intentStatus": status,
                "intentBlocks": blocks,
                "brokerSurface": BROKER_EXECUTION_SURFACE,
                "futureApiTarget": BROKER_API_TARGET,
                "executionMode": EXECUTION_MODE,
            }
        )

    queue = {
        "generatedAt": snapshot.get("generatedAt") or datetime.now().astimezone().isoformat(),
        "mode": EXECUTION_MODE,
        "brokerSurface": BROKER_EXECUTION_SURFACE,
        "futureApiTarget": BROKER_API_TARGET,
        "dailyRiskBudget": MAX_DAILY_RISK_UNITS,
        "stagedRiskUnits": round(staged_risk, 2),
        "activeIntentLimit": MAX_ACTIVE_EXECUTION_INTENTS,
        "activeReadyCount": active_ready,
        "count": len(intents),
        "items": intents,
    }
    return queue


def build_execution_text(queue: dict[str, Any]) -> str:
    lines = [
        "Execution Desk",
        "",
        f"Mode: {queue.get('mode')}",
        f"Broker surface: {queue.get('brokerSurface')}",
        f"Future API target: {queue.get('futureApiTarget')}",
        f"Risk staged: {queue.get('stagedRiskUnits')} / {queue.get('dailyRiskBudget')} units",
        f"Ready intents: {queue.get('activeReadyCount')} / {queue.get('activeIntentLimit')}",
        "",
    ]

    items = queue.get("items", [])
    if not items:
        lines.append("No execution intents are staged yet.")
        return "\n".join(lines)

    for item in items:
        block_text = "; ".join(item.get("intentBlocks", [])) or "all checks clear"
        lines.extend(
            [
                f"{item['rank']}. {item['ticker']} | {item['intentStatus']} | {item['setupRec']} | tier {item['convictionTier']} | risk {item['riskUnits']}",
                f"   Route: {item['primaryRoute']} / {item['secondaryRoute']}",
                f"   Approval: {item['approvalStatus']} | Trigger: {'LIVE' if item['signalTrigger'] else 'WAIT'} | {item['daysUntilEarnings']}d to earnings",
                f"   Notes: {block_text}",
            ]
        )
    return "\n".join(lines)


def save_execution_queue(queue: dict[str, Any]) -> dict[str, str]:
    ensure_dirs()
    EXECUTION_QUEUE_FILE.write_text(json.dumps(queue, indent=2), encoding="utf-8")
    EXECUTION_TEXT_FILE.write_text(build_execution_text(queue), encoding="utf-8")
    return {
        "json": str(EXECUTION_QUEUE_FILE),
        "text": str(EXECUTION_TEXT_FILE),
    }


def print_status(queue: dict[str, Any]) -> None:
    print(build_execution_text(queue))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage broker-safe execution intents from the latest inferno shortlist.")
    parser.add_argument("command", nargs="?", default="status", choices=["status", "build"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    queue = build_execution_queue()
    if args.command == "build":
        save_execution_queue(queue)
    print_status(queue)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
