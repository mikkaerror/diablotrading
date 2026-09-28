from __future__ import annotations

"""Delegated PAPER approvals under an explicit operator ack.

On 2026-09-27 the operator explicitly delegated paper-ticket approval to
Claude ("I want you to filter and approve the paper trades ... I give you
permission explicitly to approve the paper trades"). This module is the only
path that delegation may use. It is deliberately narrow:

- Paper only. It edits the local approval queue exactly the way
  `inferno_approval_queue.py approve|reject` does. Staging still happens in
  the normal strike cycle, which re-runs every risk gate with fresh chains.
  Nothing here touches liveTradingAllowed, brokerSubmitAllowed,
  BROKER_ADAPTER_MODE, risk constants, or the live broker book.
- Ack-gated. Without an active data/inferno_paper_delegation_ack.json it only
  prints what it would do. The operator revokes by setting "active": false
  (or deleting the file).
- Rule-based and audited. Every decision carries its rule and is appended to
  data/operator_decisions.csv with actor "claude-delegated".

Policy (paper evidence first; slots go to questions not yet answered):
  APPROVE  strike plan priced, fresh, event still ahead, and the paper risk
           verdict has no blocks other than "approval missing".
  REJECT   max loss is more than REJECT_CAP_MULTIPLE x the effective paper
           cap (no cap-fit variant is plausible), OR this ticker+strategy has
           already answered the question in shadow (>= SHADOW_ANSWERED_MIN
           closed with avg R <= SHADOW_ANSWERED_MAX_R).
  HOLD     anything else (wide spreads, stale price, open ticket, missing or
           stale plan, cap miss within reach of a cap-fit variant).
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from inferno_email_digest import normalize_block_reason

PAPER_DELEGATE_STAGE = "paper-delegate-ack-gated"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
ACK_FILE = DATA_DIR / "inferno_paper_delegation_ack.json"
DELEGATE_FILE = DATA_DIR / "inferno_paper_delegate.json"
DELEGATE_TEXT_FILE = REPORTS_DIR / "paper_delegate_latest.txt"
DECISIONS_LOG = DATA_DIR / "operator_decisions.csv"

ACTOR = "claude-delegated"
MAX_PLAN_AGE_HOURS = 96.0
REJECT_CAP_MULTIPLE = 3.0
SHADOW_ANSWERED_MIN = 15
SHADOW_ANSWERED_MAX_R = -0.5
MAX_APPROVALS_PER_RUN = 5
CAP_LABELS = {"over single-ticket cap", "over daily loss cap"}

CITATIONS = [
    "Operator delegation, 2026-09-27 (data/inferno_paper_delegation_ack.json)",
    "CLAUDE.md §8 autonomous-vs-ack boundary (paper approval now ack-delegated)",
    "inferno_risk_policy.evaluate_strike_item (re-run at staging)",
]


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _age_hours(stamp: Any, now: datetime) -> float | None:
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=now.tzinfo)
    return max(0.0, (now - when).total_seconds() / 3600.0)


def ack_status(ack: dict[str, Any]) -> tuple[bool, str]:
    if not ack:
        return False, "no delegation ack file"
    if not ack.get("active"):
        return False, "delegation ack is inactive"
    if ack.get("scope") != "paper-only":
        return False, "delegation ack scope is not paper-only"
    return True, f"active since {ack.get('grantedAt')}"


def shadow_history(shadow: dict[str, Any], ticker: str, strategy: str | None) -> dict[str, Any]:
    values = []
    for item in shadow.get("items") or []:
        if item.get("ticker") != ticker or (strategy and item.get("strategy") != strategy):
            continue
        outcome = item.get("outcome") or {}
        r_value = _num(outcome.get("estimatedReturnOnRisk"))
        if outcome.get("status") == "closed" and r_value is not None:
            values.append(r_value)
    if not values:
        return {"closed": 0, "avgR": None}
    return {"closed": len(values), "avgR": round(sum(values) / len(values), 3)}


def decide(
    queue_item: dict[str, Any],
    plan_item: dict[str, Any] | None,
    plan_age_hours: float | None,
    shadow: dict[str, Any],
) -> dict[str, Any]:
    """Pure policy: return {'action': approve|reject|hold, 'rule', 'reason'}."""
    ticker = queue_item.get("ticker")
    base = {"ticker": ticker, "token": queue_item.get("approvalToken")}

    def out(action: str, rule: str, reason: str, **extra: Any) -> dict[str, Any]:
        return {**base, "action": action, "rule": rule, "reason": reason, **extra}

    if not plan_item or not plan_item.get("ok"):
        return out("hold", "no-priced-plan", "no priced strike plan yet")
    strike = plan_item.get("strikePlan") or {}
    strategy = strike.get("strategy")
    verdict = plan_item.get("riskVerdict") or {}
    metrics = verdict.get("metrics") or {}
    max_loss = _num(metrics.get("maxLossDollars", strike.get("estimatedMaxLoss")))
    cap = _num(metrics.get("effectiveSingleTicketCap") or metrics.get("maxSingleTicketDollars"))
    blocks = []
    for reason in verdict.get("blocks") or []:
        label = normalize_block_reason(reason)
        if label and label not in blocks:
            blocks.append(label)
    history = shadow_history(shadow, ticker, strategy)
    extra = {"strategy": strategy, "maxLoss": max_loss, "cap": cap, "blocks": blocks, "shadow": history}

    if (
        history["closed"] >= SHADOW_ANSWERED_MIN
        and history["avgR"] is not None
        and history["avgR"] <= SHADOW_ANSWERED_MAX_R
    ):
        return out(
            "reject", "shadow-answered",
            f"{ticker} {strategy} already {history['closed']} shadow closes at avg {history['avgR']:+.2f}R",
            **extra,
        )
    if max_loss is not None and cap and max_loss > REJECT_CAP_MULTIPLE * cap:
        return out(
            "reject", "far-over-cap",
            f"max loss ${max_loss:,.0f} is more than {REJECT_CAP_MULTIPLE:g}x the ${cap:,.0f} paper cap",
            **extra,
        )
    days = _num(queue_item.get("daysUntilEarnings", plan_item.get("daysUntilEarnings")))
    if days is not None and days < 1:
        return out("hold", "event-passed", "earnings window has passed", **extra)
    if plan_age_hours is None or plan_age_hours > MAX_PLAN_AGE_HOURS:
        return out("hold", "stale-plan", "strike plan too old to judge", **extra)
    if blocks:
        return out("hold", "soft-blocks", "; ".join(blocks), **extra)
    return out("approve", "clean-paper", "priced, fresh, event ahead, paper risk clear", **extra)


def build_paper_delegate(
    data_dir: Path = DATA_DIR,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now().astimezone()
    queue = _load(data_dir / "inferno_approval_queue.json")
    plan = _load(data_dir / "inferno_strike_plan.json")
    shadow = _load(data_dir / "inferno_shadow_evidence.json")
    ack = _load(data_dir / ACK_FILE.name)
    ack_ok, ack_message = ack_status(ack)
    plan_age = _age_hours(plan.get("generatedAt"), now)
    by_ticker = {item.get("ticker"): item for item in plan.get("items") or []}
    decisions = []
    for item in queue.get("items") or []:
        if str(item.get("approvalStatus") or "").lower() != "pending":
            continue
        decisions.append(decide(item, by_ticker.get(item.get("ticker")), plan_age, shadow))
    approvals = [d for d in decisions if d["action"] == "approve"]
    for extra in approvals[MAX_APPROVALS_PER_RUN:]:
        extra.update(action="hold", rule="per-run-limit", reason=f"over {MAX_APPROVALS_PER_RUN} approvals this run")
    return {
        "generatedAt": now.isoformat(),
        "stage": PAPER_DELEGATE_STAGE,
        "researchOnly": False,
        "paperOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "ackActive": ack_ok,
        "ackMessage": ack_message,
        "planAgeHours": None if plan_age is None else round(plan_age, 1),
        "decisions": decisions,
        "applied": [],
        "citations": CITATIONS,
    }


def _log_decision(path: Path, decision: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(["timestamp", "ticker", "action", "note", "rationale", "confidence", "seconds_to_decide"])
        writer.writerow([
            datetime.now().isoformat(timespec="seconds"),
            decision["ticker"],
            "approve" if decision["action"] == "approve" else "reject",
            f"{ACTOR} paper-only ({decision['rule']})",
            decision["reason"],
            "",
            "",
        ])


def apply_decisions(payload: dict[str, Any], updater=None, log_path: Path = DECISIONS_LOG) -> dict[str, Any]:
    """Apply approve/reject decisions through the approval queue. Ack required."""
    if not payload["ackActive"]:
        return payload
    if updater is None:
        from inferno_approval_queue import load_queue, update_item

        def updater(identifier: str, status: str) -> int:
            return update_item(load_queue(), identifier, status)

    for decision in payload["decisions"]:
        if decision["action"] not in {"approve", "reject"}:
            continue
        status = "approved" if decision["action"] == "approve" else "rejected"
        identifier = decision.get("token") or decision["ticker"]
        if updater(identifier, status) == 0:
            _log_decision(log_path, decision)
            payload["applied"].append({"ticker": decision["ticker"], "status": status, "rule": decision["rule"]})
    return payload


def paper_delegate_text(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Paper Delegate (paper-only, ack-gated)",
        f"Generated: {payload['generatedAt']}",
        f"Ack: {'ACTIVE' if payload['ackActive'] else 'INACTIVE'} - {payload['ackMessage']}",
        f"Strike plan age: {payload['planAgeHours']}h",
        "",
    ]
    if not payload["decisions"]:
        lines.append("No pending paper candidates.")
    for d in payload["decisions"]:
        lines.append(f"- {d['action'].upper():7} {d['ticker']} ({d['rule']}): {d['reason']}")
    if payload["applied"]:
        lines.append("")
        lines.append("Applied: " + ", ".join(f"{a['ticker']} {a['status']}" for a in payload["applied"]))
    elif payload["ackActive"]:
        lines.append("")
        lines.append("Applied: nothing (dry run or no approve/reject decisions)")
    lines.append("")
    lines.append("Paper only. Staging re-runs every risk gate. Live submit stays False.")
    return "\n".join(lines) + "\n"


def save_paper_delegate(payload: dict[str, Any]) -> None:
    from inferno_io import atomic_write_json, atomic_write_text

    atomic_write_json(DELEGATE_FILE, payload)
    atomic_write_text(DELEGATE_TEXT_FILE, paper_delegate_text(payload))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ack-gated delegated paper approvals.")
    parser.add_argument("command", nargs="?", default="plan", choices=["plan", "run", "status"])
    args = parser.parse_args(argv)
    if args.command == "status":
        payload = _load(DELEGATE_FILE)
        if not payload:
            print("No delegate run yet.")
            return 1
        print(paper_delegate_text(payload))
        return 0
    payload = build_paper_delegate()
    if args.command == "run":
        payload = apply_decisions(payload)
    save_paper_delegate(payload)
    print(paper_delegate_text(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
