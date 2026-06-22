from __future__ import annotations

"""Observational DTE cohort analysis for closed paper and shadow outcomes."""

import argparse
from collections import defaultdict
from statistics import median
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_trade_evidence import (
    dte_bucket,
    entry_dte,
    exit_dte,
    holding_days,
    normalized_outcome,
    strategy_family,
)
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


PAPER_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
SHADOW_LEDGER_FILE = DATA_DIR / "inferno_shadow_evidence.json"
DTE_POLICY_FILE = DATA_DIR / "inferno_dte_policy_analysis.json"
DTE_POLICY_TEXT_FILE = REPORTS_DIR / "dte_policy_analysis_latest.txt"
STAGE = "dte-policy-analysis-research-only"


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [row["netREstimate"] for row in rows if row.get("netREstimate") is not None]
    holding_periods = [
        row["holdingDays"] for row in rows if row.get("holdingDays") is not None
    ]
    return {
        "count": len(rows),
        "scoredCount": len(values),
        "winRate": round(sum(value > 0 for value in values) / len(values), 4) if values else None,
        "meanNetREstimate": round(sum(values) / len(values), 6) if values else None,
        "medianNetREstimate": round(median(values), 6) if values else None,
        "meanHoldingDays": (
            round(sum(holding_periods) / len(holding_periods), 2)
            if holding_periods
            else None
        ),
    }


def build_dte_policy_analysis(
    *,
    paper: dict[str, Any] | None = None,
    shadow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sources = {
        "paper": paper if paper is not None else (load_json_file(PAPER_LEDGER_FILE) or {}),
        "shadow": shadow if shadow is not None else (load_json_file(SHADOW_LEDGER_FILE) or {}),
    }
    records = []
    for source, payload in sources.items():
        for item in payload.get("items") or []:
            if str((item.get("outcome") or {}).get("status") or "").lower() != "closed":
                continue
            outcome = normalized_outcome(item)
            if outcome.get("grossPnlDollars") is None:
                continue
            open_dte = entry_dte(item)
            close_dte = exit_dte(item)
            records.append(
                {
                    "source": source,
                    "ticketId": item.get("ticketId"),
                    "ticker": item.get("ticker"),
                    "family": strategy_family(item),
                    "admissibility": (
                        "risk-passed"
                        if (item.get("riskVerdict") or {}).get("passed") is True
                        else "risk-failed"
                    ),
                    "entryDte": open_dte,
                    "entryDteBucket": dte_bucket(open_dte),
                    "exitDte": close_dte,
                    "exitDteBucket": dte_bucket(close_dte),
                    "holdingDays": holding_days(item),
                    **outcome,
                }
            )

    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        grouped[(row["source"], row["family"], row["admissibility"], row["entryDteBucket"])].append(row)
    cohorts = [
        {
            "source": source,
            "family": family,
            "admissibility": admissibility,
            "entryDteBucket": bucket,
            **_stats(items),
        }
        for (source, family, admissibility, bucket), items in sorted(grouped.items())
    ]
    before_21 = [row for row in records if row.get("exitDte") is not None and row["exitDte"] >= 21]
    after_21 = [row for row in records if row.get("exitDte") is not None and row["exitDte"] < 21]
    return {
        "generatedAt": local_now().isoformat(),
        "stage": STAGE,
        "verdict": "cohorts-ready" if records else "awaiting-closed-outcomes",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "counts": {"records": len(records), "cohorts": len(cohorts)},
        "reviewAt21Dte": True,
        "observationalExitComparison": {
            "closedAtOrAbove21Dte": _stats(before_21),
            "closedBelow21Dte": _stats(after_21),
            "causalClaimAllowed": False,
        },
        "cohorts": cohorts,
        "records": records,
        "reminders": [
            "Twenty-one DTE is a review trigger, not a universal force-close.",
            "These cohorts are observational and mix regimes; do not infer causality from raw averages.",
            "Risk-failed shadow cohorts diagnose filters and must not be read as executable strategy evidence.",
            "Adopt an exit rule only after matched paper cohorts beat alternatives in net R and drawdown.",
        ],
    }


def render(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno DTE Policy Analysis",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Counts: {payload.get('counts')}",
        "",
        f"Observational 21-DTE comparison: {payload.get('observationalExitComparison')}",
        "",
        "Entry-DTE cohorts:",
    ]
    for row in payload.get("cohorts") or []:
        lines.append(
            f"- {row.get('source')} | {row.get('family')} | {row.get('admissibility')} | "
            f"{row.get('entryDteBucket')} DTE | "
            f"n={row.get('scoredCount')} | win={row.get('winRate')} | "
            f"netR={row.get('meanNetREstimate')} | hold={row.get('meanHoldingDays')}d"
        )
    if not payload.get("cohorts"):
        lines.append("- none")
    lines.extend(["", "Reminders:"])
    lines.extend(f"- {item}" for item in payload.get("reminders") or [])
    return "\n".join(lines).rstrip() + "\n"


def save(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(DTE_POLICY_FILE, payload)
    atomic_write_text(DTE_POLICY_TEXT_FILE, render(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Inferno DTE cohort analysis.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    args = parser.parse_args()
    if args.command == "status" and DTE_POLICY_TEXT_FILE.exists():
        print(DTE_POLICY_TEXT_FILE.read_text(encoding="utf-8"), end="")
        return 0
    payload = build_dte_policy_analysis()
    save(payload)
    print(render(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
