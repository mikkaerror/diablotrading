from __future__ import annotations

"""Audit turnover, holding behavior, and re-entry patterns."""

import argparse
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_trade_evidence import (
    gross_pnl_dollars,
    holding_days,
    max_loss_dollars,
    normalized_outcome,
    parse_date,
    strategy_family,
)
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


PAPER_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
SHADOW_LEDGER_FILE = DATA_DIR / "inferno_shadow_evidence.json"
NLV_HISTORY_FILE = DATA_DIR / "nlv_history.csv"
DECISIONS_FILE = DATA_DIR / "operator_decisions.csv"
BEHAVIOR_FILE = DATA_DIR / "inferno_trading_behavior_audit.json"
BEHAVIOR_TEXT_FILE = REPORTS_DIR / "trading_behavior_audit_latest.txt"
STAGE = "trading-behavior-audit-research-only"


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _load_nlv_history(path: Path = NLV_HISTORY_FILE) -> dict[date, float]:
    if not path.exists():
        return {}
    rows: dict[date, float] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            day = parse_date(row.get("date"))
            try:
                nlv = float(row.get("nlv") or 0)
            except ValueError:
                continue
            if day and nlv > 0:
                rows[day] = nlv
    return rows


def _nlv_for(day: date | None, history: dict[date, float]) -> float | None:
    if day is None or not history:
        return None
    candidates = [key for key in history if key <= day]
    return history[max(candidates)] if candidates else None


def _load_decisions(path: Path = DECISIONS_FILE) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_trading_behavior_audit(
    *,
    paper: dict[str, Any] | None = None,
    shadow: dict[str, Any] | None = None,
    nlv_history: dict[date, float] | None = None,
    decisions: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    sources = {
        "paper": paper if paper is not None else (load_json_file(PAPER_LEDGER_FILE) or {}),
        "shadow": shadow if shadow is not None else (load_json_file(SHADOW_LEDGER_FILE) or {}),
    }
    history = nlv_history if nlv_history is not None else _load_nlv_history()
    decision_rows = decisions if decisions is not None else _load_decisions()
    records = []
    all_entries: dict[tuple[str, str], list[date]] = defaultdict(list)
    daily_risk: dict[tuple[str, date], float] = defaultdict(float)

    for source, payload in sources.items():
        for item in payload.get("items") or []:
            ticker = str(item.get("ticker") or "").upper()
            opened = parse_date(item.get("tradeDate") or item.get("createdAt"))
            outcome_status = str((item.get("outcome") or {}).get("status") or "").lower()
            status = str(item.get("status") or "").lower()
            entered = (
                status == "paper-staged"
                if source == "paper"
                else status == "shadow-open" or outcome_status == "closed"
            )
            if ticker and opened and entered:
                all_entries[(source, ticker)].append(opened)
                daily_risk[(source, opened)] += max_loss_dollars(item)
            if outcome_status != "closed":
                continue
            pnl = gross_pnl_dollars(item)
            if pnl is None:
                continue
            records.append(
                {
                    "source": source,
                    "ticketId": item.get("ticketId"),
                    "ticker": ticker,
                    "family": strategy_family(item),
                    "tradeDate": opened.isoformat() if opened else None,
                    "holdingDays": holding_days(item),
                    "winner": pnl > 0,
                    **normalized_outcome(item),
                }
            )

    winners = [row["holdingDays"] for row in records if row["winner"] and row.get("holdingDays") is not None]
    losers = [row["holdingDays"] for row in records if not row["winner"] and row.get("holdingDays") is not None]
    reentries = []
    for (source, ticker), dates in sorted(all_entries.items()):
        ordered = sorted(set(dates))
        gaps = [(ordered[index] - ordered[index - 1]).days for index in range(1, len(ordered))]
        if gaps:
            reentries.append(
                {
                    "source": source,
                    "ticker": ticker,
                    "entryCount": len(ordered),
                    "minimumReentryDays": min(gaps),
                    "sameOrNextDayReentries": sum(gap <= 1 for gap in gaps),
                }
            )

    turnover_rows = []
    for (source, day), risk in sorted(daily_risk.items()):
        nlv = _nlv_for(day, history)
        turnover_rows.append(
            {
                "source": source,
                "date": day.isoformat(),
                "capitalAtRiskDollars": round(risk, 2),
                "nlv": nlv,
                "riskTurnoverPctOfNlv": round(risk / nlv * 100.0, 2) if nlv else None,
            }
        )

    approved = [row for row in decision_rows if str(row.get("action") or "").lower() == "approve"]
    approved_missing_journal = sum(
        not str(row.get("rationale") or "").strip() or not str(row.get("confidence") or "").strip()
        for row in approved
    )
    winner_mean = _mean([float(value) for value in winners])
    loser_mean = _mean([float(value) for value in losers])
    disposition_watch = bool(
        len(winners) >= 3
        and len(losers) >= 3
        and winner_mean is not None
        and loser_mean is not None
        and loser_mean > winner_mean * 1.25
    )
    high_turnover_days = [
        row for row in turnover_rows
        if row.get("riskTurnoverPctOfNlv") is not None and row["riskTurnoverPctOfNlv"] > 100.0
    ]
    verdict = (
        "disposition-watch" if disposition_watch
        else "activity-watch" if high_turnover_days
        else "behavior-baseline-ready" if records
        else "awaiting-closed-outcomes"
    )
    return {
        "generatedAt": local_now().isoformat(),
        "stage": STAGE,
        "verdict": verdict,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "counts": {
            "closedRecords": len(records),
            "winnerHoldSamples": len(winners),
            "loserHoldSamples": len(losers),
            "reentryTickers": len(reentries),
            "operatorApprovals": len(approved),
            "approvalsMissingJournal": approved_missing_journal,
        },
        "dispositionEffect": {
            "averageWinnerHoldingDays": winner_mean,
            "averageLoserHoldingDays": loser_mean,
            "watch": disposition_watch,
        },
        "turnover": {
            "method": "sum of ticket max loss divided by nearest prior NLV snapshot",
            "highTurnoverDayCount": len(high_turnover_days),
            "days": turnover_rows,
        },
        "reentries": reentries,
        "records": records,
        "reminders": [
            "High activity is not evidence of edge; compare net R after friction.",
            "Longer loser holding periods are a disposition-effect warning, not proof of irrationality.",
            "Paper and shadow behavior remain separate from live realized performance.",
        ],
    }


def render(payload: dict[str, Any]) -> str:
    disposition = payload.get("dispositionEffect") or {}
    lines = [
        "Inferno Trading Behavior Audit",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Counts: {payload.get('counts')}",
        "",
        "Disposition effect:",
        f"- winner hold days: {disposition.get('averageWinnerHoldingDays')}",
        f"- loser hold days: {disposition.get('averageLoserHoldingDays')}",
        f"- watch: {disposition.get('watch')}",
        "",
        "Highest turnover days:",
    ]
    days = sorted(
        payload.get("turnover", {}).get("days") or [],
        key=lambda row: row.get("riskTurnoverPctOfNlv") or -1,
        reverse=True,
    )
    for row in days[:10]:
        lines.append(
            f"- {row.get('source')} {row.get('date')} | risk ${row.get('capitalAtRiskDollars')} | "
            f"NLV {row.get('nlv')} | turnover {row.get('riskTurnoverPctOfNlv')}%"
        )
    if not days:
        lines.append("- none")
    lines.extend(["", "Re-entry watches:"])
    for row in payload.get("reentries") or []:
        if row.get("sameOrNextDayReentries"):
            lines.append(
                f"- {row.get('source')} {row.get('ticker')} | "
                f"same/next-day={row.get('sameOrNextDayReentries')} | min gap={row.get('minimumReentryDays')}d"
            )
    if not any(row.get("sameOrNextDayReentries") for row in payload.get("reentries") or []):
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def save(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(BEHAVIOR_FILE, payload)
    atomic_write_text(BEHAVIOR_TEXT_FILE, render(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Inferno trading behavior audit.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    args = parser.parse_args()
    if args.command == "status" and BEHAVIOR_TEXT_FILE.exists():
        print(BEHAVIOR_TEXT_FILE.read_text(encoding="utf-8"), end="")
        return 0
    payload = build_trading_behavior_audit()
    save(payload)
    print(render(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
