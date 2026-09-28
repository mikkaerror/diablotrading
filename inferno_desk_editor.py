from __future__ import annotations

"""Desk Editor fact packet: one screen of what matters this morning.

The desk writes 60+ reports. The operator wants one email. This module is
the deterministic half of the "Desk Editor" agent: it reads artifacts that
already exist, pulls out only what changes a decision today, and saves a
packet (JSON + text). A scheduled Claude agent reads the packet and writes
the morning email in plain language; the text renderer here doubles as the
fallback email if that agent is unavailable.

Research/reporting only. Reads artifacts, never refreshes data, never
approves, rejects, stages, or closes a ticket, never touches risk constants
or broker authority. Every number the agent is allowed to quote comes from
this packet.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from inferno_email_digest import normalize_block_reason

DESK_EDITOR_STAGE = "desk-editor-research-only"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
DESK_EDITOR_FILE = DATA_DIR / "inferno_desk_editor.json"
DESK_EDITOR_TEXT_FILE = REPORTS_DIR / "desk_editor_latest.txt"

LOSS_RULE_PCT = -20.0
PROMOTION_SAMPLE = 30
LONG_TERM_LIMIT = 3

# (label, file, max age hours). Only stale/missing rows reach the email.
FRESHNESS_CHECKS: tuple[tuple[str, str, float], ...] = (
    ("broker account", "inferno_live_account_sync.json", 36.0),
    ("approval queue", "inferno_approval_queue.json", 36.0),
    ("strike plan", "inferno_strike_plan.json", 36.0),
    ("shadow evidence", "inferno_shadow_evidence.json", 48.0),
    ("action pulse", "inferno_action_pulse.json", 36.0),
)

CITATIONS = [
    "today.py (operator entry point: money header, candidates, loss rule)",
    "docs/TRADE_MANAGEMENT_PLAYBOOK.md §5.2 drawdown stepper, §5.4 never average down",
    "CLAUDE.md §8 autonomous-vs-ack boundary",
]


# ---------------------------------------------------------------- helpers

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


def _stamp(payload: dict[str, Any]) -> str | None:
    """Most recent successful write; ledgers keep an old generatedAt forever."""
    return payload.get("lastSuccessfulAt") or payload.get("updatedAt") or payload.get("generatedAt")


def _age_hours(stamp: str | None, now: datetime) -> float | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=now.tzinfo)
    return max(0.0, (now - when).total_seconds() / 3600.0)


def _money(value: Any) -> str:
    number = _num(value)
    return "n/a" if number is None else f"${number:,.2f}"


def _pretty(strategy: Any) -> str:
    return str(strategy or "?").replace("_", " ").title()


# ---------------------------------------------------------------- sections

def money_section(data_dir: Path, now: datetime) -> dict[str, Any]:
    sync = _load(data_dir / "inferno_live_account_sync.json")
    state = _load(data_dir / "inferno_capital_scaling_state.json")
    scaling = _load(data_dir / "inferno_capital_scaling.json")
    nlv = _num(sync.get("netLiquidatingValue"))
    peak = _num(state.get("peakNlv"))
    age = _age_hours(_stamp(sync), now)
    drawdown = scaling.get("drawdownState") or {}
    return {
        "nlv": nlv,
        "cash": _num(sync.get("totalCash")),
        "peakNlv": peak,
        "fromPeakPct": round((nlv / peak - 1.0) * 100, 1) if nlv is not None and peak else None,
        "ageHours": None if age is None else round(age, 1),
        "fresh": age is not None and age <= 36.0,
        "drawdownLevel": drawdown.get("level"),
        "newLiveEntriesAllowed": drawdown.get("newEntriesAllowed"),
    }


def _shadow_history(shadow: dict[str, Any], ticker: str, strategy: str | None) -> dict[str, Any]:
    closed = []
    for item in shadow.get("items") or []:
        if item.get("ticker") != ticker:
            continue
        if strategy and item.get("strategy") != strategy:
            continue
        outcome = item.get("outcome") or {}
        r_value = _num(outcome.get("estimatedReturnOnRisk"))
        if outcome.get("status") == "closed" and r_value is not None:
            closed.append(r_value)
    if not closed:
        return {"closed": 0}
    return {
        "closed": len(closed),
        "wins": sum(1 for r in closed if r > 0),
        "avgR": round(sum(closed) / len(closed), 3),
    }


def _strategy_stats(shadow: dict[str, Any], strategy: str | None) -> dict[str, Any] | None:
    for row in shadow.get("strategies") or []:
        if row.get("strategy") == strategy and (row.get("closedCount") or 0) > 0:
            return {
                "closed": row.get("closedCount"),
                "winRate": row.get("winRate"),
                "avgR": row.get("avgReturnOnRisk"),
            }
    return None


def decisions_section(data_dir: Path) -> list[dict[str, Any]]:
    queue = _load(data_dir / "inferno_approval_queue.json")
    plan = _load(data_dir / "inferno_strike_plan.json")
    shadow = _load(data_dir / "inferno_shadow_evidence.json")
    plan_by_ticker = {item.get("ticker"): item for item in plan.get("items") or [] if item.get("ok")}
    decisions = []
    for item in queue.get("items") or []:
        if str(item.get("approvalStatus") or "").lower() != "pending":
            continue
        ticker = item.get("ticker")
        planned = plan_by_ticker.get(ticker) or {}
        strike = planned.get("strikePlan") or {}
        verdict = planned.get("riskVerdict") or {}
        strategy = strike.get("strategy")
        blocks = []
        for reason in verdict.get("blocks") or []:
            label = normalize_block_reason(reason)
            if label and label not in blocks:
                blocks.append(label)
        decisions.append(
            {
                "ticker": ticker,
                "strategy": strategy or item.get("setupRec"),
                "expiration": strike.get("expiration"),
                "maxLoss": _num((verdict.get("metrics") or {}).get("maxLossDollars", strike.get("estimatedMaxLoss"))),
                "breakevens": [strike.get("lowerBreakEven"), strike.get("upperBreakEven")],
                "daysUntilEarnings": item.get("daysUntilEarnings"),
                "readiness": item.get("readiness"),
                "riskBlocks": blocks,
                "paperRiskPassed": bool(planned) and not blocks,
                "replyApprove": item.get("replyApprove"),
                "replyDeny": item.get("replyDeny"),
                "tickerShadow": _shadow_history(shadow, ticker, strategy),
                "strategyShadow": _strategy_stats(shadow, strategy),
            }
        )
    return decisions


def positions_section(data_dir: Path) -> dict[str, Any]:
    review = _load(data_dir / "inferno_live_position_review.json")
    management = _load(data_dir / "inferno_trade_management.json")
    holdings = []
    for pos in review.get("positions") or []:
        pct = _num(pos.get("plPercent"))
        holdings.append(
            {
                "symbol": pos.get("symbol"),
                "markValue": _num(pos.get("markValue")),
                "plOpen": _num(pos.get("plOpen")),
                "plPercent": None if pct is None else round(pct, 1),
                "lossRule": pct is not None and pct <= LOSS_RULE_PCT,
            }
        )
    paper_actions = [
        {
            "ticker": row.get("ticker"),
            "verdict": row.get("verdict"),
            "reason": row.get("reason") or row.get("message"),
        }
        for row in management.get("assessments") or []
        if row.get("verdict") not in (None, "hold", "awaiting-data")
    ]
    return {
        "live": holdings,
        "paperOpen": management.get("openPositionCount", 0),
        "paperActions": paper_actions,
    }


def evidence_section(data_dir: Path) -> dict[str, Any]:
    analytics = _load(data_dir / "inferno_performance_analytics.json")
    shadow = _load(data_dir / "inferno_shadow_evidence.json")
    closed = analytics.get("closedMetrics") or {}
    rows = [
        {
            "strategy": row.get("strategy"),
            "closed": row.get("closedCount"),
            "winRate": row.get("winRate"),
            "avgR": row.get("avgReturnOnRisk"),
        }
        for row in shadow.get("strategies") or []
        if (row.get("closedCount") or 0) > 0
    ]
    rows.sort(key=lambda row: -(row["closed"] or 0))
    return {
        "scoredPaper": closed.get("scoredCount", 0) or 0,
        "promotionSample": PROMOTION_SAMPLE,
        "paperExpectancyR": closed.get("expectancyPerDollarRisk"),
        "shadow": rows,
    }


def alerts_section(data_dir: Path, now: datetime) -> list[str]:
    alerts = []
    for label, name, max_age in FRESHNESS_CHECKS:
        path = data_dir / name
        if not path.exists():
            alerts.append(f"{label}: missing")
            continue
        age = _age_hours(_stamp(_load(path)), now)
        if age is None:
            alerts.append(f"{label}: unknown age")
        elif age > max_age:
            alerts.append(f"{label}: stale ({age:.0f}h old)")
    return alerts


_LONG_TERM_LINE = re.compile(r"^\s*\d+\.\s*([A-Z.\-]+)\s*\|\s*([^|]+)\|\s*score\s*([\d.]+)\s*\|\s*(.*)$")


def long_term_section(reports_dir: Path, limit: int = LONG_TERM_LIMIT) -> list[dict[str, Any]]:
    try:
        text = (reports_dir / "long_term_buys_latest.txt").read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        match = _LONG_TERM_LINE.match(line)
        if not match:
            continue
        reasons = [part.strip() for part in match.group(4).split(";") if part.strip()]
        rows.append(
            {
                "ticker": match.group(1),
                "action": match.group(2).strip(),
                "score": _num(match.group(3)),
                "why": reasons[0] if reasons else "",
            }
        )
        if len(rows) >= limit:
            break
    return rows


def headline(payload: dict[str, Any]) -> str:
    count = len(payload["decisions"])
    losers = [h for h in payload["positions"]["live"] if h["lossRule"]]
    parts = [f"{count} decision{'s' if count != 1 else ''} today" if count else "No decisions today"]
    if payload["positions"]["paperActions"]:
        parts.append(f"{len(payload['positions']['paperActions'])} paper position(s) need action")
    if losers:
        parts.append(f"{len(losers)} holding(s) past the -20% rule")
    if payload["alerts"]:
        parts.append("data needs a refresh")
    return " | ".join(parts)


# ---------------------------------------------------------------- payload

def build_desk_editor(
    data_dir: Path = DATA_DIR,
    reports_dir: Path = REPORTS_DIR,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now().astimezone()
    payload: dict[str, Any] = {
        "generatedAt": now.isoformat(),
        "stage": DESK_EDITOR_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "money": money_section(data_dir, now),
        "decisions": decisions_section(data_dir),
        "positions": positions_section(data_dir),
        "evidence": evidence_section(data_dir),
        "alerts": alerts_section(data_dir, now),
        "longTerm": long_term_section(reports_dir),
        "citations": CITATIONS,
    }
    payload["headline"] = headline(payload)
    return payload


def _r(value: Any) -> str:
    number = _num(value)
    return "-" if number is None else f"{number:+.2f}R"


def _pct(value: Any) -> str:
    number = _num(value)
    return "-" if number is None else f"{number * 100:.0f}%"


def desk_editor_text(payload: dict[str, Any]) -> str:
    """Plain-text fallback email. The agent may rewrite it, never re-number it."""
    money = payload["money"]
    lines = [f"Inferno Desk — {payload['headline']}", ""]

    stale = "" if money["fresh"] else f" (last known, {money['ageHours']}h old)"
    lines.append(f"MONEY{stale}")
    lines.append(
        f"NLV {_money(money['nlv'])} | cash {_money(money['cash'])}"
        + (f" | {money['fromPeakPct']:+.1f}% vs peak {_money(money['peakNlv'])}" if money["fromPeakPct"] is not None else "")
    )
    if money.get("newLiveEntriesAllowed") is False:
        lines.append(f"Drawdown protocol: {money.get('drawdownLevel')} — no new LIVE entries. Paper practice is fine.")
    lines.append("")

    lines.append("DECISIONS")
    if not payload["decisions"]:
        lines.append("Nothing waiting on you.")
    for d in payload["decisions"]:
        lines.append(
            f"- {d['ticker']} {_pretty(d['strategy'])} exp {d['expiration'] or '?'} | "
            f"max loss {_money(d['maxLoss'])} | earnings {d['daysUntilEarnings']}d | readiness {d['readiness']}%"
        )
        if d["riskBlocks"]:
            lines.append(f"  Blocked by: {', '.join(d['riskBlocks'])}")
        th, ss = d["tickerShadow"], d["strategyShadow"]
        against = []
        if th.get("closed"):
            against.append(f"{d['ticker']} shadow {th['wins']}/{th['closed']} wins, avg {_r(th['avgR'])}")
        if ss:
            against.append(f"strategy shadow win {_pct(ss['winRate'])}, avg {_r(ss['avgR'])} over {ss['closed']}")
        if against:
            lines.append(f"  Evidence: {'; '.join(against)}")
        lines.append(f"  Decide: ./inferno today, or reply to the {d['ticker']} [Inferno Approval] email")
    lines.append("")

    positions = payload["positions"]
    if positions["live"] or positions["paperActions"]:
        lines.append("POSITIONS")
        for h in positions["live"]:
            flag = "  <- past -20%: never add (playbook 5.4)" if h["lossRule"] else ""
            lines.append(f"- {h['symbol']} {_money(h['markValue'])} ({h['plPercent']:+.1f}%){flag}" if h["plPercent"] is not None else f"- {h['symbol']} {_money(h['markValue'])}")
        for a in positions["paperActions"]:
            lines.append(f"- paper {a['ticker']}: {a['verdict']} — {a['reason']}")
        lines.append("")

    evidence = payload["evidence"]
    lines.append("EVIDENCE")
    lines.append(f"Scored paper trades: {evidence['scoredPaper']}/{evidence['promotionSample']}")
    for row in evidence["shadow"]:
        lines.append(f"- shadow {_pretty(row['strategy'])}: {row['closed']} closed | win {_pct(row['winRate'])} | avg {_r(row['avgR'])}")
    lines.append("")

    if payload["longTerm"]:
        lines.append("LONG-TERM LANE")
        for row in payload["longTerm"]:
            lines.append(f"- {row['ticker']} {row['action']} ({row['score']}): {row['why']}")
        lines.append("")

    if payload["alerts"]:
        lines.append("HEADS UP")
        lines.extend(f"- {alert}" for alert in payload["alerts"])
        lines.append("")

    lines.append("Paper-only desk. Nothing in this email places or approves an order.")
    return "\n".join(lines).rstrip() + "\n"


def save_desk_editor(payload: dict[str, Any]) -> None:
    from inferno_io import atomic_write_json, atomic_write_text

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(DESK_EDITOR_FILE, payload)
    atomic_write_text(DESK_EDITOR_TEXT_FILE, desk_editor_text(payload))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Desk Editor fact packet (reporting only).")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--json", action="store_true", help="Print the JSON packet instead of text.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "status":
        payload = _load(DESK_EDITOR_FILE)
        if not payload:
            print("No desk editor packet yet. Run: python3 inferno_desk_editor.py run")
            return 1
    else:
        payload = build_desk_editor()
        save_desk_editor(payload)
    print(json.dumps(payload, indent=2) if args.json else desk_editor_text(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
