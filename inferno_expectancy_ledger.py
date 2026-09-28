from __future__ import annotations

"""Net-R expectancy ledger by strategy family and evidence source."""

import argparse
import random
from collections import defaultdict
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_trade_evidence import normalized_outcome, strategy_family
from inferno_strategy_lab import closed_trade_records
from inferno_paper_execution import paper_event_id
from inferno_paper_provenance import finite, parse_execution_timestamp
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


PAPER_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
SHADOW_LEDGER_FILE = DATA_DIR / "inferno_shadow_evidence.json"
EXPECTANCY_LEDGER_FILE = DATA_DIR / "inferno_expectancy_ledger.json"
EXPECTANCY_LEDGER_TEXT_FILE = REPORTS_DIR / "expectancy_ledger_latest.txt"
STAGE = "expectancy-ledger-research-only"
BOOTSTRAP_SAMPLES = 2000


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return round(ordered[index], 6)


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
    dated = [(parse_execution_timestamp(row.get("reviewedAt")), row) for row in records]
    chronology_known = all(stamp is not None for stamp, _ in dated)
    if chronology_known:
        records = [row for _, row in sorted(dated, key=lambda pair: pair[0])]
    net_r = [finite(row.get("netREstimate")) for row in records if finite(row.get("netREstimate")) is not None]
    gross_r = [finite(row.get("grossR")) for row in records if finite(row.get("grossR")) is not None]
    wins = [value for value in net_r if value > 0]
    losses = [value for value in net_r if value < 0]
    clusters = defaultdict(list)
    for row in records:
        value = finite(row.get("netREstimate"))
        if value is not None:
            clusters[row.get("eventId") or "unknown-event"].append(value)
    ci = {"lower": None, "upper": None}
    if len(clusters) >= 2:
        groups = list(clusters.values())
        rng = random.Random(17)
        means = []
        for _ in range(BOOTSTRAP_SAMPLES):
            sample = [value for _ in groups for value in groups[rng.randrange(len(groups))]]
            means.append(sum(sample) / len(sample))
        ci = {"lower": _percentile(means, .025), "upper": _percentile(means, .975)}
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
        "maxDrawdownNetR": _max_drawdown(net_r) if chronology_known else None,
        "drawdownBasis": "chronological-summed-trade-R" if chronology_known else "unavailable-missing-outcome-time",
        "estimatedFrictionDollars": round(
            sum(row.get("estimatedFrictionDollars") or 0.0 for row in records), 2
        ),
    }


def build_expectancy_ledger(
    *,
    paper: dict[str, Any] | None = None,
    shadow: dict[str, Any] | None = None,
    fill_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sources = {
        "paper": paper if paper is not None else (load_json_file(PAPER_LEDGER_FILE) or {}),
        "shadow": shadow if shadow is not None else (load_json_file(SHADOW_LEDGER_FILE) or {}),
    }
    if paper is not None and fill_source is None:
        fill_source = {"status": "not-supplied", "rows": []}
    # Use the existing qualifier; this report neither changes nor replaces it.
    admitted = {row["ticketId"]: row for row in closed_trade_records(sources["paper"].get("items") or [], fill_source)}
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
            qualified = admitted.get(ticket_id) if source == "paper" else None
            evidence_class = "source-reconciled-paper-fill" if qualified else ("unverified-paper-estimate" if source == "paper" else "shadow-proxy")
            if qualified:
                # The qualifier supplies fill-adjusted risk and fee semantics.
                provenance = qualified["provenance"]
                basis = provenance["pnlBasis"]
                economics = provenance["pnlReconciliation"]
                net_known = economics.get("netPnl") is not None
                outcome.update({
                    "maxLossDollars": qualified["maxLoss"],
                    "grossPnlDollars": economics["grossPnl"],
                    "grossR": round(economics["grossPnl"] / qualified["maxLoss"], 6),
                    "netREstimate": qualified["returnOnRisk"] if net_known else None,
                    "netPnlEstimateDollars": qualified["estimatedPnl"] if net_known else None,
                    "frictionSource": basis,
                    "estimatedFrictionDollars": economics.get("totalFees"),
                    "frictionRealized": net_known,
                })
            else:
                basis = "modeled-net" if outcome.get("frictionSource") != "unavailable" else "gross-costs-unknown"
                if basis == "gross-costs-unknown":
                    outcome["netREstimate"] = None
                    outcome["netPnlEstimateDollars"] = None
            records.append(
                {
                    "source": source,
                    "evidenceClass": evidence_class,
                    "returnBasis": basis,
                    "eventId": paper_event_id(item),
                    "ticketId": ticket_id,
                    "ticker": item.get("ticker"),
                    "family": strategy_family(item),
                    "admissibility": (
                        "risk-passed"
                        if (item.get("riskVerdict") or {}).get("passed") is True
                        else "risk-failed"
                    ),
                    "reviewedAt": qualified["reviewedAt"] if qualified else (item.get("outcome") or {}).get("reviewedAt"),
                    **outcome,
                }
            )

    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(record["source"], record["family"], record["admissibility"], record["evidenceClass"], record["returnBasis"])].append(record)
    rows = []
    for (source, family, admissibility, evidence_class, basis), items in sorted(grouped.items()):
        stats = _stats(items)
        rows.append(
            {
                "source": source,
                "family": family,
                "admissibility": admissibility,
                **stats,
                "evidenceClass": evidence_class,
                "returnBasis": basis,
                "distinctEvents": len({row["eventId"] for row in items}),
                "sourceReconciledCount": len(items) if evidence_class == "source-reconciled-paper-fill" else 0,
                # Only the strategy lab / authority controller evaluates promotion.
                "promotionEvidenceEligible": False,
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
            "sourceReconciledPaper": sum(row["evidenceClass"] == "source-reconciled-paper-fill" for row in records),
            "unverifiedPaper": sum(row["evidenceClass"] == "unverified-paper-estimate" for row in records),
            "reportedNetPaperFills": sum(row["evidenceClass"] == "source-reconciled-paper-fill" and row.get("netREstimate") is not None for row in records),
            "netEstimatesAvailable": sum(row.get("netREstimate") is not None for row in records),
            "paper": sum(1 for row in records if row["source"] == "paper"),
            "shadow": sum(1 for row in records if row["source"] == "shadow"),
        },
        "families": rows,
        "records": records,
        "reminders": [
            "Source-reconciled fills, unverified paper estimates and shadow proxies are separate populations.",
            "Unknown costs leave net return unavailable; modeled friction is not realized net performance.",
            "Confidence intervals are event-clustered descriptive intervals, not selection-adjusted evidence of edge.",
            "Drawdown is the ordered sum of trade R, not account drawdown or a capital-weighted portfolio return.",
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
            f"{row.get('evidenceClass')} | {row.get('returnBasis')} | "
            f"records={row.get('count')} | net-scored={row.get('scoredCount')} | events={row.get('distinctEvents')} | "
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
