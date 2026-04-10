from __future__ import annotations

import argparse
import json
from datetime import datetime

from inferno_execution_clerk import build_execution_queue, save_execution_queue
from server import APPROVAL_QUEUE_FILE


def load_queue() -> dict:
    if not APPROVAL_QUEUE_FILE.exists():
        return {"generatedAt": None, "count": 0, "items": []}
    return json.loads(APPROVAL_QUEUE_FILE.read_text(encoding="utf-8"))


def save_queue(queue: dict) -> None:
    APPROVAL_QUEUE_FILE.write_text(json.dumps(queue, indent=2), encoding="utf-8")


def refresh_execution_queue() -> None:
    save_execution_queue(build_execution_queue())


def print_status(queue: dict) -> None:
    print(f"Generated at: {queue.get('generatedAt') or 'never'}")
    print(f"Pending count: {queue.get('count', 0)}")
    for item in queue.get("items", []):
        print(
            f"- {item['ticker']}: {item['approvalStatus']} | {item['setupRec']} | "
            f"{item['readiness']}% | {item['daysUntilEarnings']}d | {item['primaryRoute']}"
        )


def update_item(queue: dict, ticker: str, status: str) -> int:
    target = ticker.strip().upper()
    updated = False
    for item in queue.get("items", []):
        if item["ticker"] == target:
            item["approvalStatus"] = status
            item["decisionAt"] = datetime.now().astimezone().isoformat()
            updated = True
    if not updated:
        print(f"{target} was not found in the current approval queue.")
        return 1
    save_queue(queue)
    refresh_execution_queue()
    print(f"{target} marked {status}.")
    return 0


def reset_queue(queue: dict) -> int:
    for item in queue.get("items", []):
        item["approvalStatus"] = "pending"
        item.pop("decisionAt", None)
    save_queue(queue)
    refresh_execution_queue()
    print("Approval queue reset to pending.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect and manage the local inferno approval queue.")
    parser.add_argument("command", nargs="?", default="status", choices=["status", "approve", "reject", "reset"])
    parser.add_argument("ticker", nargs="?", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    queue = load_queue()

    if args.command == "status":
        print_status(queue)
        return 0
    if args.command == "reset":
        return reset_queue(queue)
    if not args.ticker:
        print("A ticker is required for approve/reject.")
        return 1
    if args.command == "approve":
        return update_item(queue, args.ticker, "approved")
    return update_item(queue, args.ticker, "rejected")


if __name__ == "__main__":
    raise SystemExit(main())
