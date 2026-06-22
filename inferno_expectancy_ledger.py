from __future__ import annotations

"""Net-R expectancy ledger by strategy family and evidence source."""

import argparse
import random
from collections import defaultdict
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_trade_evidence import normalized_outcome, strategy_family
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


PAPER_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
SHADOW_LEDGER_FILE = DATA_DIR / "inferno_shadow_evidence.json"
EXPECTANCY_LEDGER_FILE = DATA_DIR / "inferno_expectancy_ledger.json"
EXPECTANCY_LEDGER_TEXT_FILE = REPORTS_DIR / "expectancy_ledger_latest.txt"
STAGE = "expectancy-ledger-research-only"
BOOTSTRAP_SAMPLES = 2000
MIN_PROMOTION_SAMPLE = 30


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return round(ordered[index], 6)


def _bootstrap_mean_ci(values: list[float], seed: int = 17) -> dict[str, float | None]:
    if not values:
        return {"lower": None, "upper": None}
    rng = random.Random(seed)
    means = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = [values[rng.randrange(len(values))] for _ in values]
        means.append(sum(sample) / len(sample))
    return {"lower": _percentile(means, 0.025), "upper": _percentile(means, 0.975)}


def _max_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    equity = peak = worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return round(worst, 6)


def _stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    net_r = [row["netREstimate"] for row in records if row.get("netREstimate") is not None]
    gross_r = [row["grossR"] for row in records if row.get("grossR") is not None]
    wins = [value for value in net_r if value > 0]
    losses = [value for value in net_r if value < 0]
    ci = _bootstrap_mean_ci(net_r)
    return {
        "count": len(records),
        "scoredCount": len(net_r),
        "wins": len(wins),
        "losses": len(losses),
        "winRate": round(len(wins) / len(net_r), 4) if net_r else None,
        "averageGrossR": round(sum(gross_r) / len(gross_r), 6) if gross_r else None,
        "averageNetREstimate": round(sum(net_r) / len(net_r), 6) if net_r else None,
        "averageWinNetR": round(sum(wins) / len(wins), 6) if wins else None,
        "averageLossNetR": round(sum(losses) / len(losses), 6) if losses else None,
        "expectancyNetR": round(sum(net_r) / len(net_r), 6) if net_r else None,
        "expectancyNetR95": ci,
        "maxDrawdownNetR": _max_drawdown(net_r),
        "estimatedFrictionDollars": round(
            sum(row.get("estimatedFrictionDollars") or 0.0 for row in records), 2
        ),
    }


def build_expectancy_ledger(
    *,
    paper: dict[str, Any] | None = None,
    shadow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sources = {
        "paper": paper if paper is not None else (load_json_file(PAPER_LEDGER_FILE) or {}),
        "shadow": shadow if shadow is not None else (load_json_file(SHADOW_LEDGER_FILE) or {}),
    }
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source, payload in sources.items():
        for item in payload.get("items") or []:
            if str((item.get("outcome") or {}).get("status") or "").lower() != "closed":
                continue
            ticket_id = str(item.get("ticketId") or "")
            key = (source, ticket_id)
            if ticket_id and key in seen:
                continue
            seen.add(key)
            outcome = normalized_outcome(item)
            if outcome.get("grossPnlDollars") is None:
                continue
            records.append(
                {
                    "source": source,
                    "ticketId": ticket_id,
                    "ticker": item.get("ticker"),
                    "family": strategy_family(item),
                    "admissibility": (
                        "risk-passed"
                        if (item.get("riskVerdict") or {}).get("passed") is True
                        else "risk-failed"
                    ),
                    "reviewedAt": (item.get("outcome") or {}).get("reviewedAt"),
                    **outcome,
                }
            )

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(record["source"], record["family"], record["admissibility"])].append(record)
    rows = []
    for (source, family, admissibility), items in sorted(grouped.items()):
        stats = _stats(items)
        lower = (stats.get("expectancyNetR95") or {}).get("lower")
        rows.append(
            {
                "source": source,
                "family": family,
                "admissibility": admissibility,
                **stats,
                "promotionEvidenceEligible": bool(
                    source == "paper"
                    and admissibility == "risk-passed"
                    and stats["scoredCount"] >= MIN_PROMOTION_SAMPLE
                    and lower is not None
                    and lower > 0
                ),
            }
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": STAGE,
        "verdict": "evidence-building" if records else "awaiting-closed-outcomes",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "counts": {
            "records": len(records),
            "paper": sum(1 for row in records if row["source"] == "paper"),
            "shadow": sum(1 for row in records if row["source"] == "shadow"),
        },
        "families": rows,
        "records": records,
        "reminders": [
            "Net R subtracts modeled friction when realized fills are unavailable.",
            "Shadow outcomes never count toward promotion.",
            "Risk-failed shadow structures are diagnostics, not tradable expectancy.",
            "Kelly sizing remains disabled until credible paper-family evidence exists.",
        ],
    }


def render(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Net-R Expectancy Ledger",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Counts: {payload.get('counts')}",
        "",
        "Strategy families:",
    ]
    for row in payload.get("families") or []:
        ci = row.get("expectancyNetR95") or {}
        lines.append(
            f"- {row.get('source')} | {row.get('family')} | {row.get('admissibility')} | "
            f"n={row.get('scoredCount')} | "
            f"win={row.get('winRate')} | grossR={row.get('averageGrossR')} | "
            f"netR={row.get('expectancyNetR')} | 95% [{ci.get('lower')}, {ci.get('upper')}] | "
            f"DD={row.get('maxDrawdownNetR')} | promotion={row.get('promotionEvidenceEligible')}"
        )
    if not payload.get("families"):
        lines.append("- none")
    lines.extend(["", "Reminders:"])
    lines.extend(f"- {item}" for item in payload.get("reminders") or [])
    return "\n".join(lines).rstrip() + "\n"


def save(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(EXPECTANCY_LEDGER_FILE, payload)
    atomic_write_text(EXPECTANCY_LEDGER_TEXT_FILE, render(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Inferno net-R expectancy ledger.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    args = parser.parse_args()
    if args.command == "status" and EXPECTANCY_LEDGER_TEXT_FILE.exists():
        print(EXPECTANCY_LEDGER_TEXT_FILE.read_text(encoding="utf-8"), end="")
        return 0
    payload = build_expectancy_ledger()
    save(payload)
    print(render(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
