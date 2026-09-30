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
    ("paper ledger (staging)", "inferno_paper_execution_ledger.json", 48.0),
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

def _last_nlv_row(data_dir: Path) -> dict[str, Any] | None:
    path = data_dir / "nlv_history.csv"
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return None
    if len(lines) < 2:
        return None
    header = lines[0].split(",")
    for raw in reversed(lines[1:]):
        row = dict(zip(header, raw.split(",")))
        nlv = _num(row.get("nlv"))
        if nlv is not None:
            return {"nlv": nlv, "cash": _num(row.get("cash")), "timestamp": row.get("timestamp")}
    return None


def money_section(data_dir: Path, now: datetime) -> dict[str, Any]:
    sync = _load(data_dir / "inferno_live_account_sync.json")
    state = _load(data_dir / "inferno_capital_scaling_state.json")
    scaling = _load(data_dir / "inferno_capital_scaling.json")
    nlv = _num(sync.get("netLiquidatingValue"))
    cash = _num(sync.get("totalCash"))
    age = _age_hours(_stamp(sync), now)
    source = "broker sync"
    if nlv is None:
        # Sync can be "fresh" but empty (e.g. Schwab token rejected). Fall back
        # to the last recorded NLV and let the age say how old it is.
        last = _last_nlv_row(data_dir)
        if last:
            nlv, cash, age, source = last["nlv"], last["cash"], _age_hours(last["timestamp"], now), "nlv history"
    peak = _num(state.get("peakNlv"))
    drawdown = scaling.get("drawdownState") or {}
    return {
        "nlv": nlv,
        "cash": cash,
        "source": source,
        "peakNlv": peak,
        "fromPeakPct": round((nlv / peak - 1.0) * 100, 1) if nlv is not None and peak else None,
        "ageHours": None if age is None else round(age, 1),
        "fresh": age is not None and age <= 36.0,
        "performance": _performance(data_dir),
        "drawdownLevel": drawdown.get("level"),
        "newLiveEntriesAllowed": drawdown.get("newEntriesAllowed"),
    }


def _performance(data_dir: Path) -> dict[str, Any] | None:
    perf = _load(data_dir / "inferno_account_performance.json")
    if perf.get("verdict") != "measured":
        return None
    bench = perf.get("benchmark") or {}
    return {
        "twr": perf.get("twrSinceStart"),
        "twrDrawdownCurrent": perf.get("twrDrawdownCurrent"),
        "spy": bench.get("return"),
        "accountSameWindow": bench.get("accountTwrSameWindow"),
        "window": perf.get("window"),
        "peakSupported": (perf.get("peakIntegrity") or {}).get("supported"),
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


def order_cards_section(data_dir: Path) -> dict[str, Any]:
    cards = _load(data_dir / "inferno_paper_order_cards.json").get("cards") or []
    return {
        "actionable": [c for c in cards if c.get("kind") in {"enter", "exit"}],
        "expired": sum(1 for c in cards if c.get("kind") == "expired"),
    }


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


def earnings_section(data_dir: Path) -> dict[str, Any] | None:
    ledger = _load(data_dir / "inferno_earnings_runner.json")
    if not ledger.get("scoreboard"):
        return None
    records = ledger.get("records") or []
    today = datetime.now().astimezone().date().isoformat()
    return {
        "scoreboard": ledger["scoreboard"],
        "upcoming": ledger.get("upcoming") or [],
        "newToday": [r for r in records if r.get("enteredOn") == today],
        "closedToday": [r for r in records if r.get("exitOn") == today and r.get("status") == "closed"],
    }


def live_book_section(data_dir: Path) -> dict[str, Any] | None:
    officer = _load(data_dir / "inferno_live_book_officer.json")
    if not officer.get("book"):
        return None
    holdings = officer.get("holdings") or []
    return {
        "planStatus": officer.get("planStatus"),
        "holdsWeight": officer["book"].get("holdsWeight"),
        "neverAdd": [h["symbol"] for h in holdings if h.get("plPercent") is not None and h["plPercent"] < 0],
        "nextThesisCheck": officer.get("nextThesisCheck"),
        "depositRouting": officer.get("depositRouting"),
        "nextDeposit": officer["book"].get("nextDeposit"),
    }


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


def delegated_section(data_dir: Path, now: datetime) -> list[dict[str, Any]]:
    """Paper approvals/rejections Claude applied under the operator's ack (last 24h)."""
    payload = _load(data_dir / "inferno_paper_delegate.json")
    age = _age_hours(payload.get("generatedAt"), now)
    if not payload or age is None or age > 24:
        return []
    reasons = {d.get("ticker"): d for d in payload.get("decisions") or []}
    return [
        {
            "ticker": row.get("ticker"),
            "status": row.get("status"),
            "rule": row.get("rule"),
            "reason": (reasons.get(row.get("ticker")) or {}).get("reason"),
        }
        for row in payload.get("applied") or []
    ]


def second_opinions(data_dir: Path, now: datetime) -> dict[str, str]:
    """ChatGPT devil's-advocate lines (advisory) from the last 24h, by ticker."""
    payload = _load(data_dir / "inferno_second_opinion.json")
    age = _age_hours(payload.get("generatedAt"), now)
    if not payload or age is None or age > 24:
        return {}
    return {row.get("ticker"): row.get("challenge") for row in payload.get("items") or [] if row.get("challenge")}


def capex_flow_section(data_dir: Path) -> dict[str, Any] | None:
    flow = _load(data_dir / "inferno_capex_flow.json")
    if not flow.get("regime"):
        return None
    r = flow["regime"]
    top = [n for n in flow.get("names") or [] if n.get("action") == "BUY"][:3]
    sizing = {r["ticker"]: r for r in flow.get("sizing") or []}
    return {
        "regime": r.get("regime"),
        "growth": r.get("growth"),
        "fcfPositive": r.get("fcfPositive"),
        "spenders": r.get("spenders"),
        "tapeStale": r.get("tapeStale"),
        "top": [{"ticker": n["ticker"], "layer": n["layer"], "instrument": n["instrument"],
                 **({"targetWeight": sizing[n["ticker"]]["targetWeight"],
                     "deployNowWeight": sizing[n["ticker"]]["deployNowWeight"]}
                    if n["ticker"] in sizing else {})} for n in top],
    }


def _paper_funnel(data_dir: Path, days: int = 30) -> dict[str, Any] | None:
    ledger = _load(data_dir / "inferno_paper_execution_ledger.json")
    items = [i for i in ledger.get("items") or [] if isinstance(i, dict)]
    if not items:
        return None
    cutoff = datetime.now().astimezone().timestamp() - days * 86400
    recent = []
    for item in items:
        try:
            when = datetime.fromisoformat(str(item.get("createdAt")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.astimezone()
        if when.timestamp() >= cutoff:
            recent.append(item)
    status = [str(i.get("status") or "") for i in recent]
    return {
        "days": days,
        "proposed": len(recent),
        "blocked": sum(s == "paper-blocked" for s in status),
        "rejected": sum(s == "paper-rejected" for s in status),
        "staged": sum(s == "paper-staged" for s in status),
        "closed": sum((i.get("outcome") or {}).get("status") == "closed" for i in recent),
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
    lineage = (_load(data_dir / "inferno_promotion_evidence_lineage.json").get("promotion") or {})
    qualified = lineage.get("qualifiedPaperOutcomes")
    reported = closed.get("scoredCount", 0) or 0
    return {
        # Lineage (source-reconciled fills) is the promotion truth; analytics
        # also counts intrinsic-value estimates, which earn no credit.
        "scoredPaper": qualified if qualified is not None else reported,
        "scoredSource": "lineage" if qualified is not None else "analytics",
        "estimatesWithoutCredit": max(0, reported - qualified) if qualified is not None else None,
        "funnel": _paper_funnel(data_dir),
        "promotionSample": PROMOTION_SAMPLE,
        "paperExpectancyR": closed.get("expectancyPerDollarRisk"),
        "shadow": rows,
        "shortPremium": _short_premium_forward(data_dir),
        "fillQuality": _fill_quality(data_dir),
    }


def _fill_quality(data_dir: Path) -> dict[str, Any] | None:
    payload = _load(data_dir / "inferno_fill_quality.json")
    summary = payload.get("summary") or {}
    if not summary:
        return None
    under = [row for row in payload.get("modelCheck") or [] if row.get("read") == "model under-charges"]
    return {
        "fills": summary.get("fills", 0),
        "clean": summary.get("cleanFills", 0),
        "medianHalfSpreads": summary.get("medianHalfSpreadsVsStagedMid"),
        "verdict": summary.get("verdict"),
        "underCharged": [(row["strategy"], row["medianHalfSpreadToModeled"]) for row in under],
    }


def _short_premium_forward(data_dir: Path) -> dict[str, Any] | None:
    ledger = _load(data_dir / "inferno_short_premium_shadow.json")
    summary = ledger.get("summary") or {}
    if not summary:
        return None
    return {
        "verdict": summary.get("verdict"),
        "events": summary.get("distinctEvents", 0),
        "names": summary.get("distinctNames", 0),
        "open": summary.get("openEvents", 0),
        "meanR": summary.get("meanNetR"),
        "exBestR": summary.get("meanNetR_exTwoBest"),
        "frictionDollars": summary.get("meanEntryFrictionDollars"),
        "timeboxEnd": summary.get("timeboxEnd"),
    }


SCHWAB_REFRESH_DAYS = 7
SCHWAB_WARN_DAYS = 2.0


def schwab_login_days_left(token_file: Path, now: datetime) -> float | None:
    """Days until the 7-day Schwab refresh window closes. Reads timestamps only."""
    token = _load(token_file)
    issued = token.get("refresh_token_issued_at") or token.get("token_obtained_at")
    age = _age_hours(issued, now)
    return None if age is None else round(SCHWAB_REFRESH_DAYS - age / 24.0, 1)


def alerts_section(data_dir: Path, now: datetime) -> list[str]:
    alerts = []
    alerts.extend(_load(data_dir / "inferno_prereg_integrity.json").get("alerts") or [])
    days_left = schwab_login_days_left(data_dir.parent / ".secrets" / "schwab_token.json", now)
    if days_left is not None and 0 < days_left <= SCHWAB_WARN_DAYS:
        alerts.append(f"Schwab login runs out in {days_left:.1f} days - re-sign in on the Mac: "
                      "python3 inferno_schwab_oauth.py restart")
    sync = _load(data_dir / "inferno_live_account_sync.json")
    if sync and sync.get("ok") is False:
        if str(sync.get("schwabAccountVerdict") or "").startswith("reauth"):
            alerts.append("Schwab login expired - re-sign in on the Mac: python3 inferno_schwab_oauth.py restart")
        else:
            alerts.append(f"broker account sync blocked: {sync.get('message') or 'no detail'}")
    for label, name, max_age in FRESHNESS_CHECKS:
        path = data_dir / name
        if not path.exists():
            alerts.append(f"{label}: missing")
            continue
        age = _age_hours(_stamp(_load(path)), now)
        if age is None:
            alerts.append(f"{label}: unknown age")
        elif age > max_age:
            alerts.append(f"{label}: stale ({age:.0f}h old)" if age < 72 else f"{label}: stale ({age / 24:.0f} days old)")
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
    keyable = len((payload.get("orderCards") or {}).get("actionable") or [])
    deposit_today = bool((payload.get("depositCard") or {}).get("show"))
    losers = [h for h in payload["positions"]["live"] if h["lossRule"]]
    parts = [f"{count} decision{'s' if count != 1 else ''} today" if count else "No decisions today"]
    if keyable:
        parts.insert(0, f"{keyable} paper order{'s' if keyable != 1 else ''} to key")
    if deposit_today:
        parts.insert(0, "deposit day: your buys are ready")
    if payload.get("delegated"):
        approved = sum(1 for row in payload["delegated"] if row["status"] == "approved")
        made = len(payload["delegated"])
        parts.append(f"{made} paper call{'s' if made != 1 else ''} made for you ({approved} approved)")
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
        "orderCards": order_cards_section(data_dir),
        "decisions": decisions_section(data_dir),
        "delegated": delegated_section(data_dir, now),
        "positions": positions_section(data_dir),
        "liveBook": live_book_section(data_dir),
        "earnings": earnings_section(data_dir),
        "depositCard": _load(data_dir / "inferno_deposit_card.json") or None,
        "lifecycle": _load(data_dir / "inferno_lifecycle_board.json") or None,
        "evidence": evidence_section(data_dir),
        "capexFlow": capex_flow_section(data_dir),
        "alerts": alerts_section(data_dir, now),
        "longTerm": long_term_section(reports_dir),
        "citations": CITATIONS,
    }
    opinions = second_opinions(data_dir, now)
    for row in payload["decisions"] + payload["delegated"]:
        if row.get("ticker") in opinions:
            row["secondOpinion"] = opinions[row["ticker"]]
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
        + (f" | {money['fromPeakPct']:+.1f}% vs peak {_money(money['peakNlv'])}"
           if money["fromPeakPct"] is not None and (money.get("performance") or {}).get("peakSupported") is not False
           else "")
    )
    perf = money.get("performance")
    if perf:
        spy = "" if perf["spy"] is None else f" vs SPY {perf['spy'] * 100:+.1f}%"
        lines.append(
            f"Flow-adjusted return since {perf['window'][0]}: {perf['twr'] * 100:+.1f}%{spy} | "
            f"drawdown from high-water {perf['twrDrawdownCurrent'] * 100:+.1f}%"
        )
        if perf["peakSupported"] is False:
            lines.append("Note: the drawdown stepper's stored peak is not supported by NLV history (under review).")
    if money.get("newLiveEntriesAllowed") is False:
        lines.append(f"Drawdown protocol: {money.get('drawdownLevel')} — no new LIVE entries. Paper practice is fine.")
    lines.append("")

    cards = (payload.get("orderCards") or {}).get("actionable") or []
    if cards:
        lines.append("KEY THESE IN PAPERMONEY (full cards: reports/paper_order_cards_latest.txt)")
        for c in cards:
            if c["kind"] == "enter":
                lines.append(f"- ENTER {c['ticker']} {_pretty(c['strategy'])} exp {c['expiration']}: "
                             f"{c['orderType']} @ {c['limit']} (don't chase past {c['dontChasePast']})")
            else:
                lines.append(f"- CLOSE {c['ticker']} {_pretty(c['strategy'])}: {c['exitRule']}")
            lines.append(f"  then: {c['recordCommand']}")
        lines.append("")

    dep = payload.get("depositCard") or {}
    if dep.get("show"):
        from inferno_deposit_card import card_text
        lines.extend(card_text(dep).rstrip().splitlines())
        lines.append("")

    if payload.get("delegated"):
        lines.append("PAPER DECISIONS CLAUDE MADE (your delegation; paper only)")
        for row in payload["delegated"]:
            lines.append(f"- {row['ticker']} {row['status']}: {row['reason']}")
            if row.get("secondOpinion"):
                lines.append(f"  ChatGPT's case against: {row['secondOpinion']}")
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
        if d.get("secondOpinion"):
            lines.append(f"  ChatGPT's case against: {d['secondOpinion']}")
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

    earn = payload.get("earnings")
    if earn:
        lines.append("EARNINGS RUNNER CAMPAIGN (paper/shadow; reports/earnings_runner_latest.txt)")
        for arm, sb in earn["scoreboard"].items():
            res = "" if sb["mean"] is None else f", win {sb['winRate'] * 100:.0f}%, mean {sb['mean'] * 100:+.0f}%"
            lines.append(f"- {arm} {sb['label']}: {sb['closed']} closed, {sb['open']} open{res}")
        for r in earn["newToday"]:
            lines.append(f"  new: {r['arm']} {r['ticker']} {_pretty(r['structure'])} exp {r['expiration']} @ {r['entry']}")
        for r in earn["closedToday"]:
            lines.append(f"  closed: {r['arm']} {r['ticker']} {r['returnOnDebit'] * 100:+.0f}% ({r['exitHow']})")
        if earn["upcoming"]:
            lines.append("Reporting within 14 days: " + ", ".join(f"{u['ticker']} {u['earnings'][5:]}" for u in earn["upcoming"][:6]))
        lines.append('Make a call: python3 inferno_earnings_runner.py call TICKER up|down "why"')
        lines.append("")

    book = payload.get("liveBook")
    if book:
        lines.append("LIVE BOOK (report only; details: reports/live_book_officer_latest.txt)")
        if book.get("holdsWeight") is not None:
            lines.append(f"Operator holds are {book['holdsWeight'] * 100:.0f}% of the account.")
        if book["neverAdd"]:
            lines.append(f"Never add while under water: {', '.join(book['neverAdd'])} (playbook 5.4).")
        if book.get("nextThesisCheck"):
            lines.append(f"Next thesis check: {book['nextThesisCheck']['symbol']} on {book['nextThesisCheck']['on']}.")
        r = book.get("depositRouting")
        if r:
            prefix = "Plan: " if book["planStatus"] == "signed" else "If you sign the Conviction Plan, "
            tranche = "" if r.get("convictionTranche") in (None, "full") else " (1/3 now, rest on a pullback)"
            lines.append(f"{prefix}the {book['nextDeposit']} deposit goes ${r['core']:.0f} {r['coreVehicle']} / "
                         f"${r['conviction']:.0f} {r['convictionName']}{tranche}.")
        lines.append("")

    life = payload.get("lifecycle") or {}
    if life.get("lanes"):
        tag = "" if life.get("rulesStatus") == "signed" else "; draft rules"
        lines.append(f"LIFECYCLE (reports/lifecycle_board_latest.txt{tag})")
        for r in life["lanes"]:
            if r["stage"] == "decommission":
                continue
            lines.append(f"- [{r['stage']}] {r['label']}: {r['evidence']}")
        for f in life.get("flags") or []:
            lines.append(f"  REVIEW: {f}")
        lines.append("")

    evidence = payload["evidence"]
    lines.append("EVIDENCE")
    extra = ""
    if evidence.get("estimatesWithoutCredit"):
        extra = f" (+{evidence['estimatesWithoutCredit']} intrinsic estimate(s), no credit)"
    lines.append(f"Promotion evidence: {evidence['scoredPaper']}/{evidence['promotionSample']} qualified paper fills{extra}")
    f = evidence.get("funnel")
    if f:
        lines.append(
            f"Paper funnel, last {f['days']}d: {f['proposed']} proposed -> {f['blocked']} blocked, "
            f"{f['rejected']} rejected -> {f['staged']} staged -> {f['closed']} closed"
        )
    for row in evidence["shadow"]:
        lines.append(f"- shadow {_pretty(row['strategy'])}: {row['closed']} closed | win {_pct(row['winRate'])} | avg {_r(row['avgR'])}")
    sp = evidence.get("shortPremium")
    if sp:
        result = "" if sp["meanR"] is None else f" | mean {_r(sp['meanR'])}, ex-two-best {_r(sp['exBestR'])}"
        friction = "" if sp["frictionDollars"] is None else f" | entry friction ${sp['frictionDollars']:.0f}/fly"
        lines.append(
            f"- short-premium forward (iron fly shadow): {sp['events']}/60 events, {sp['names']}/40 names, "
            f"{sp['open']} open{result}{friction} | time-box {sp['timeboxEnd']}"
        )
    fq = evidence.get("fillQuality")
    if fq:
        median = "" if fq["medianHalfSpreads"] is None else f" | median {fq['medianHalfSpreads']:+.2f} half-spreads vs staged mid"
        lines.append(f"- fill quality: {fq['fills']} fill(s), {fq['clean']} with a fill-time mid{median} | {fq['verdict']}")
        if fq["underCharged"]:
            worst = ", ".join(f"{_pretty(name)} x{ratio}" for name, ratio in fq["underCharged"])
            lines.append(f"  model friction under-charges: {worst} (reports/fill_quality_latest.txt)")
    lines.append("")

    flow = payload.get("capexFlow")
    if flow:
        growth = "n/a" if flow["growth"] is None else f"{flow['growth'] * 100:+.0f}%"
        lines.append("CAPEX FLOW")
        lines.append(
            f"Tap: {flow['regime']} (spender capex {growth} guided; FCF-positive {flow['fcfPositive']}/{flow['spenders']})"
            + (" - tape needs an earnings-season update" if flow["tapeStale"] else "")
        )
        for row in flow["top"]:
            size = ""
            if row.get("targetWeight") is not None:
                size = f" (sleeve target {row['targetWeight'] * 100:.0f}%, now {row['deployNowWeight'] * 100:.0f}%)"
            lines.append(f"- {row['ticker']} [{row['layer']}]{size}: {row['instrument']}")
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
