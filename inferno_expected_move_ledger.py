from __future__ import annotations

"""Research-only expected-move ledger for long-vol option structures.

Long straddles and strangles do not merely need direction; they need realised
movement large enough to outrun premium, spread, and time decay. This module
audits closed long-vol records against the move implied by breakevens or, when
breakevens are absent, by the entry debit.

Strict contract:
- diagnostic-only and research-only
- no broker calls, approvals, order creation, or authority promotion
- the debit-implied move is a desk proxy, not an exchange or broker IV feed
"""

import argparse
import json
from collections import defaultdict
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


EXPECTED_MOVE_LEDGER_FILE = DATA_DIR / "inferno_expected_move_ledger.json"
EXPECTED_MOVE_LEDGER_TEXT_FILE = REPORTS_DIR / "expected_move_ledger_latest.txt"
EXPECTED_MOVE_LEDGER_STAGE = "expected-move-ledger-research-only"

PAPER_EXECUTION_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
SHADOW_EVIDENCE_FILE = DATA_DIR / "inferno_shadow_evidence.json"
PAPER_BOTTLENECK_REDUCER_FILE = DATA_DIR / "inferno_paper_bottleneck_reducer.json"

MIN_EXPECTED_MOVE_SAMPLE = 10
CONTRACT_MULTIPLIER = 100.0

HURDLE_REASONABLE_ATR_MULTIPLE = 1.25
HURDLE_STRETCH_ATR_MULTIPLE = 2.0
HURDLE_HARD_ATR_MULTIPLE = 3.0
HURDLE_PENALTIES = {
    "reasonable": 0.0,
    "stretch": 6.0,
    "hard": 12.0,
    "extreme": 20.0,
    "unknown": 0.0,
    "unpriced": 0.0,
}


def text(value: Any) -> str:
    """Normalize loose artifact values into stripped text."""
    return str(value or "").strip()


def number(value: Any, default: float | None = None) -> float | None:
    """Coerce artifact values to floats while tolerating display strings."""
    if isinstance(value, (int, float)):
        return float(value)
    raw = text(value).replace("$", "").replace(",", "").replace("%", "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def norm(value: Any) -> str:
    """Uppercase normalization for strategy/ticker matching."""
    return text(value).upper()


def is_long_vol_strategy(value: Any) -> bool:
    """Return True for long-vol structures where movement is the main hurdle."""
    raw = norm(value).replace("_", " ")
    return "STRADDLE" in raw or "STRANGLE" in raw


def long_vol_family(value: Any) -> str:
    """Collapse strategy names into expected-move families."""
    raw = norm(value).replace("_", " ")
    if "STRANGLE" in raw:
        return "LONG_STRANGLE"
    if "STRADDLE" in raw:
        return "LONG_STRADDLE"
    return "OTHER"


def first_number(*values: Any) -> float | None:
    """Return the first parseable numeric value from a candidate list."""
    for value in values:
        parsed = number(value)
        if parsed is not None:
            return parsed
    return None


def underlying_entry_price(entry: dict[str, Any]) -> float | None:
    """Return the best available underlying price at trade/scenario entry."""
    market = entry.get("marketContextSummary") or {}
    return first_number(
        entry.get("underlyingPrice"),
        entry.get("entryUnderlyingPrice"),
        entry.get("baselineUnderlyingPrice"),
        entry.get("currentUnderlyingPrice"),
        entry.get("price"),
        market.get("underlyingPrice"),
        market.get("price"),
    )


def underlying_exit_price(entry: dict[str, Any]) -> float | None:
    """Return the best available underlying exit/review price."""
    outcome = entry.get("outcome") or {}
    return first_number(
        outcome.get("exitUnderlyingPrice"),
        outcome.get("currentUnderlyingPrice"),
        entry.get("exitUnderlyingPrice"),
    )


def entry_debit(entry: dict[str, Any]) -> float | None:
    """Return the per-share debit proxy for one long-vol structure."""
    direct = first_number(entry.get("entryLimit"), entry.get("debit"), entry.get("entryDebit"))
    if direct and direct > 0:
        return direct
    max_loss = first_number(entry.get("estimatedMaxLoss"), entry.get("maxLossDollars"))
    if max_loss and max_loss > 0:
        multiplier = first_number(entry.get("contractMultiplier")) or CONTRACT_MULTIPLIER
        return max_loss / multiplier
    return None


def implied_move_pct(entry: dict[str, Any], baseline: float) -> tuple[float | None, str]:
    """Return the minimum breakeven move or a debit proxy as percent of price."""
    lower = number(entry.get("lowerBreakEven"))
    upper = number(entry.get("upperBreakEven"))
    candidates: list[float] = []
    if lower is not None and lower < baseline:
        candidates.append(((baseline - lower) / baseline) * 100.0)
    if upper is not None and upper > baseline:
        candidates.append(((upper - baseline) / baseline) * 100.0)
    positive = [value for value in candidates if value > 0]
    if positive:
        return round(min(positive), 4), "breakeven-min"
    debit = entry_debit(entry)
    if debit and debit > 0:
        return round((debit / baseline) * 100.0, 4), "debit-proxy"
    return None, "missing-premium"


def atr_percent(entry: dict[str, Any], baseline: float | None = None) -> float | None:
    """Return ATR percent from reducer context, or derive it from ATR dollars."""
    market = entry.get("marketContextSummary") or {}
    direct = first_number(entry.get("atrPercent"), market.get("atrPercent"))
    if direct and direct > 0:
        return direct
    atr = first_number(entry.get("atr20Day"), market.get("atr20Day"))
    if atr and baseline and baseline > 0:
        return round((atr / baseline) * 100.0, 4)
    return None


def premium_hurdle(
    *,
    entry: dict[str, Any],
    implied_pct: float | None,
    baseline: float | None,
) -> dict[str, Any]:
    """Classify the premium hurdle relative to ATR for diagnostic ranking pressure."""
    scenario_score = number(entry.get("scenarioScore"))
    if implied_pct is None:
        label = "unpriced"
        penalty = HURDLE_PENALTIES[label]
        return {
            "label": label,
            "atrPercent": atr_percent(entry, baseline),
            "requiredMoveAtrMultiple": None,
            "rankPenalty": penalty,
            "rankPressureScore": scenario_score,
            "action": "cannot evaluate premium hurdle until the candidate has a priced move",
        }

    atr = atr_percent(entry, baseline)
    if atr is None or atr <= 0:
        label = "unknown"
        penalty = HURDLE_PENALTIES[label]
        return {
            "label": label,
            "atrPercent": atr,
            "requiredMoveAtrMultiple": None,
            "rankPenalty": penalty,
            "rankPressureScore": scenario_score,
            "action": "missing ATR context; do not reward the long-vol structure for price alone",
        }

    multiple = round(implied_pct / atr, 4)
    if multiple <= HURDLE_REASONABLE_ATR_MULTIPLE:
        label = "reasonable"
        action = "no premium demotion from ATR hurdle"
    elif multiple <= HURDLE_STRETCH_ATR_MULTIPLE:
        label = "stretch"
        action = "require catalyst and IV-expansion confirmation before favoring long vol"
    elif multiple <= HURDLE_HARD_ATR_MULTIPLE:
        label = "hard"
        action = "demote long vol unless alternatives have worse defined-risk math"
    else:
        label = "extreme"
        action = "prefer a defined-risk alternative unless the catalyst is exceptional"
    penalty = HURDLE_PENALTIES[label]
    adjusted = round(max(0.0, scenario_score - penalty), 4) if scenario_score is not None else None
    return {
        "label": label,
        "atrPercent": round(atr, 4),
        "requiredMoveAtrMultiple": multiple,
        "rankPenalty": penalty,
        "rankPressureScore": adjusted,
        "action": action,
    }


def max_loss(entry: dict[str, Any]) -> float:
    """Return the best available max-loss estimate for R-unit math."""
    metrics = ((entry.get("riskVerdict") or {}).get("metrics") or {})
    for candidate in (
        metrics.get("maxLossDollars"),
        entry.get("estimatedMaxLoss"),
        entry.get("maxLossDollars"),
    ):
        value = number(candidate)
        if value and value > 0:
            return value
    return 0.0


def outcome_r(entry: dict[str, Any]) -> float | None:
    """Return closed outcome return in R units if enough data exists."""
    outcome = entry.get("outcome") or {}
    direct = number(outcome.get("estimatedReturnOnRisk"))
    if direct is not None:
        return round(direct, 6)
    pnl = number(outcome.get("estimatedPnl"))
    risk = max_loss(entry)
    if pnl is None or risk <= 0:
        return None
    return round(pnl / risk, 6)


def closed_expected_move_record(entry: dict[str, Any], source: str) -> dict[str, Any] | None:
    """Normalize one closed long-vol record into expected-move evidence."""
    strategy = entry.get("strategy") or entry.get("setupRec")
    if not is_long_vol_strategy(strategy):
        return None
    outcome = entry.get("outcome") or {}
    if text(outcome.get("status")).lower() != "closed":
        return None
    baseline = underlying_entry_price(entry)
    exit_price = underlying_exit_price(entry)
    if baseline is None or baseline <= 0 or exit_price is None:
        return None
    implied, implied_source = implied_move_pct(entry, baseline)
    if implied is None:
        return None
    realized = round(abs(exit_price - baseline) / baseline * 100.0, 4)
    edge = round(realized - implied, 4)
    return {
        "source": source,
        "ticketId": entry.get("ticketId") or entry.get("scenarioId"),
        "ticker": norm(entry.get("ticker")),
        "strategy": text(strategy),
        "family": long_vol_family(strategy),
        "baselineUnderlyingPrice": round(baseline, 4),
        "exitUnderlyingPrice": round(exit_price, 4),
        "impliedMovePct": implied,
        "impliedMoveSource": implied_source,
        "realizedAbsMovePct": realized,
        "moveEdgePct": edge,
        "moveRatio": round(realized / implied, 4) if implied > 0 else None,
        "beatImpliedMove": realized >= implied,
        "entryDebit": entry_debit(entry),
        "outcomeR": outcome_r(entry),
        "reviewedAt": outcome.get("reviewedAt"),
    }


def closed_expected_move_records(
    *,
    paper_ledger: dict[str, Any] | None = None,
    shadow_ledger: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return closed paper/shadow long-vol records with move evidence."""
    paper = paper_ledger if paper_ledger is not None else (load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {})
    shadow = shadow_ledger if shadow_ledger is not None else (load_json_file(SHADOW_EVIDENCE_FILE) or {})
    records: list[dict[str, Any]] = []
    for source, payload in (("paper", paper), ("shadow", shadow)):
        for item in payload.get("items") or []:
            record = closed_expected_move_record(item, source)
            if record:
                records.append(record)
    return records


def current_long_vol_candidate(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Summarize a current slate long-vol candidate without pretending it is evidence."""
    strategy = entry.get("strategy") or entry.get("setupRec")
    if not is_long_vol_strategy(strategy):
        return None
    baseline = underlying_entry_price(entry)
    candidate = {
        "ticker": norm(entry.get("ticker")),
        "rank": entry.get("rank"),
        "strategy": text(strategy),
        "family": long_vol_family(strategy),
        "readiness": number(entry.get("readiness")),
        "scenarioScore": number(entry.get("scenarioScore")),
        "estimatedMaxLoss": number(entry.get("estimatedMaxLoss")),
        "baselineUnderlyingPrice": baseline,
        "paperAutoSelected": bool(entry.get("paperAutoSelected")),
        "shadowOnly": bool(entry.get("shadowOnly")),
        "brokerSubmitAllowed": bool(entry.get("brokerSubmitAllowed")),
        "liveTradingAllowed": bool(entry.get("liveTradingAllowed")),
    }
    if baseline is None or baseline <= 0:
        candidate["status"] = "missing-underlying-price"
        candidate["impliedMovePct"] = None
        candidate["impliedMoveSource"] = None
        hurdle = premium_hurdle(entry=entry, implied_pct=None, baseline=baseline)
        candidate.update(
            {
                "atrPercent": hurdle["atrPercent"],
                "requiredMoveAtrMultiple": hurdle["requiredMoveAtrMultiple"],
                "premiumHurdleLabel": hurdle["label"],
                "rankPenalty": hurdle["rankPenalty"],
                "rankPressureScore": hurdle["rankPressureScore"],
                "hurdleAction": hurdle["action"],
            }
        )
        return candidate
    implied, implied_source = implied_move_pct(entry, baseline)
    candidate["impliedMovePct"] = implied
    candidate["impliedMoveSource"] = implied_source
    candidate["status"] = "priced" if implied is not None else implied_source
    hurdle = premium_hurdle(entry=entry, implied_pct=implied, baseline=baseline)
    candidate.update(
        {
            "atrPercent": hurdle["atrPercent"],
            "requiredMoveAtrMultiple": hurdle["requiredMoveAtrMultiple"],
            "premiumHurdleLabel": hurdle["label"],
            "rankPenalty": hurdle["rankPenalty"],
            "rankPressureScore": hurdle["rankPressureScore"],
            "hurdleAction": hurdle["action"],
        }
    )
    return candidate


def current_long_vol_candidates(
    paper_reducer: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return current reducer long-vol candidates for operator visibility."""
    reducer = paper_reducer if paper_reducer is not None else (load_json_file(PAPER_BOTTLENECK_REDUCER_FILE) or {})
    rows: list[dict[str, Any]] = []
    for item in reducer.get("scenarioSlate") or []:
        candidate = current_long_vol_candidate(item)
        if candidate:
            rows.append(candidate)
    return rows


def mean(values: list[float]) -> float | None:
    """Return a rounded arithmetic mean for non-empty samples."""
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def rate(count: int, total: int) -> float | None:
    """Return a rounded count/total rate."""
    if total <= 0:
        return None
    return round(count / total, 4)


def move_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute expected-move summary stats for a record set."""
    beat_count = sum(1 for record in records if record.get("beatImpliedMove"))
    r_values = [number(record.get("outcomeR")) for record in records if number(record.get("outcomeR")) is not None]
    implied = [number(record.get("impliedMovePct")) for record in records if number(record.get("impliedMovePct")) is not None]
    realized = [
        number(record.get("realizedAbsMovePct"))
        for record in records
        if number(record.get("realizedAbsMovePct")) is not None
    ]
    edges = [number(record.get("moveEdgePct")) for record in records if number(record.get("moveEdgePct")) is not None]
    ratios = [number(record.get("moveRatio")) for record in records if number(record.get("moveRatio")) is not None]
    return {
        "sampleCount": len(records),
        "beatCount": beat_count,
        "missCount": len(records) - beat_count,
        "beatRate": rate(beat_count, len(records)),
        "meanImpliedMovePct": mean([value for value in implied if value is not None]),
        "meanRealizedAbsMovePct": mean([value for value in realized if value is not None]),
        "meanMoveEdgePct": mean([value for value in edges if value is not None]),
        "meanMoveRatio": mean([value for value in ratios if value is not None]),
        "meanOutcomeR": mean([value for value in r_values if value is not None]),
    }


def group_stats(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Compute move stats grouped by a record key."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[text(record.get(key)) or "unknown"].append(record)
    rows: list[dict[str, Any]] = []
    for label, group in groups.items():
        row = {"group": label, **move_stats(group)}
        rows.append(row)
    return sorted(rows, key=lambda row: (-row["sampleCount"], row["group"]))


def hurdle_counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    """Count current candidates by premium-hurdle label."""
    counts: dict[str, int] = {}
    for item in candidates:
        label = text(item.get("premiumHurdleLabel")) or "unknown"
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def top_pressure_candidates(candidates: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    """Return candidates most pressured by the premium hurdle."""
    pressured = [
        item
        for item in candidates
        if number(item.get("rankPenalty"), 0.0)
    ]
    pressured.sort(
        key=lambda item: (
            -(number(item.get("rankPenalty"), 0.0) or 0.0),
            -(number(item.get("requiredMoveAtrMultiple"), 0.0) or 0.0),
            text(item.get("ticker")),
        )
    )
    return pressured[:limit]


def ledger_verdict(stats: dict[str, Any]) -> str:
    """Return a conservative expected-move verdict."""
    sample_count = int(stats.get("sampleCount") or 0)
    if sample_count < MIN_EXPECTED_MOVE_SAMPLE:
        return "insufficient-data"
    mean_edge = number(stats.get("meanMoveEdgePct"), 0.0) or 0.0
    beat_rate = number(stats.get("beatRate"), 0.0) or 0.0
    if mean_edge > 0 and beat_rate >= 0.55:
        return "move-edge-positive"
    if mean_edge < 0 or beat_rate < 0.45:
        return "move-edge-negative"
    return "move-edge-watch"


def build_expected_move_ledger(
    *,
    paper_ledger: dict[str, Any] | None = None,
    shadow_ledger: dict[str, Any] | None = None,
    paper_reducer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the research-only expected-move ledger."""
    ensure_dirs()
    closed_records = closed_expected_move_records(
        paper_ledger=paper_ledger,
        shadow_ledger=shadow_ledger,
    )
    current_candidates = current_long_vol_candidates(paper_reducer)
    stats = move_stats(closed_records)
    priced_current = [
        item
        for item in current_candidates
        if item.get("status") == "priced"
    ]
    missing_current = [
        item
        for item in current_candidates
        if item.get("status") != "priced"
    ]
    pressure_candidates = top_pressure_candidates(current_candidates)
    return {
        "generatedAt": local_now().isoformat(),
        "stage": EXPECTED_MOVE_LEDGER_STAGE,
        "verdict": ledger_verdict(stats),
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "counts": {
            "closedLongVolRecords": len(closed_records),
            "withExpectedMove": len(closed_records),
            "currentLongVolCandidates": len(current_candidates),
            "currentPricedCandidates": len(priced_current),
            "currentMissingPriceOrPremium": len(missing_current),
            "currentPremiumPressured": len(pressure_candidates),
        },
        "overall": stats,
        "byFamily": group_stats(closed_records, "family"),
        "bySource": group_stats(closed_records, "source"),
        "currentHurdleCounts": hurdle_counts(current_candidates),
        "currentPressureCandidates": pressure_candidates,
        "closedRecords": closed_records,
        "currentCandidates": current_candidates,
        "reminders": [
            "A long-vol ticket needs realised move to clear premium, spread, and decay; direction alone is not enough.",
            "Breakeven distance is preferred; debit/underlying is used only when breakevens are absent.",
            "This artifact is diagnostic only and cannot promote live or paper authority.",
        ],
    }


def pct(value: Any) -> str:
    """Render a decimal rate as a compact percentage."""
    parsed = number(value)
    if parsed is None:
        return "n/a"
    return f"{parsed * 100:.1f}%"


def fmt(value: Any, *, suffix: str = "") -> str:
    """Render optional numeric values compactly."""
    parsed = number(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:.4g}{suffix}"


def expected_move_ledger_text(payload: dict[str, Any]) -> str:
    """Render the expected-move ledger memo."""
    counts = payload.get("counts") or {}
    overall = payload.get("overall") or {}
    lines = [
        "Inferno Expected Move Ledger",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Verdict: {payload.get('verdict')}",
        "Authority: research-only; promotable=False; liveTradingAllowed=False",
        "",
        "Counts:",
        f"- closed long-vol records: {counts.get('closedLongVolRecords', 0)}",
        f"- current long-vol candidates: {counts.get('currentLongVolCandidates', 0)}",
        f"- current priced candidates: {counts.get('currentPricedCandidates', 0)}",
        f"- current missing price/premium: {counts.get('currentMissingPriceOrPremium', 0)}",
        f"- current premium-pressured: {counts.get('currentPremiumPressured', 0)}",
        "",
        "Closed long-vol expected-move summary:",
        f"- beat rate: {pct(overall.get('beatRate'))} "
        f"({overall.get('beatCount', 0)}/{overall.get('sampleCount', 0)})",
        f"- mean implied move: {fmt(overall.get('meanImpliedMovePct'), suffix='%')}",
        f"- mean realised abs move: {fmt(overall.get('meanRealizedAbsMovePct'), suffix='%')}",
        f"- mean move edge: {fmt(overall.get('meanMoveEdgePct'), suffix='%')}",
        f"- mean outcome R: {fmt(overall.get('meanOutcomeR'))}",
        "",
        f"Current premium hurdle counts: {json.dumps(payload.get('currentHurdleCounts') or {})}",
        "",
        "By family:",
    ]
    if not payload.get("byFamily"):
        lines.append("- no closed long-vol records with expected-move math yet")
    for row in payload.get("byFamily") or []:
        lines.append(
            f"- {row.get('group')}: n={row.get('sampleCount')} | "
            f"beat={pct(row.get('beatRate'))} | "
            f"edge={fmt(row.get('meanMoveEdgePct'), suffix='%')} | "
            f"mean R={fmt(row.get('meanOutcomeR'))}"
        )
    lines.extend(["", "Current long-vol candidates:"])
    if not payload.get("currentCandidates"):
        lines.append("- none")
    for item in payload.get("currentCandidates") or []:
        lines.append(
            f"- {item.get('ticker')}: {item.get('strategy')} | "
            f"status={item.get('status')} | "
            f"score={fmt(item.get('scenarioScore'))} | "
            f"implied={fmt(item.get('impliedMovePct'), suffix='%')} | "
            f"ATRx={fmt(item.get('requiredMoveAtrMultiple'))} | "
            f"hurdle={item.get('premiumHurdleLabel')} | "
            f"pressureScore={fmt(item.get('rankPressureScore'))} | "
            f"paperAutoSelected={item.get('paperAutoSelected')}"
        )
        action = text(item.get("hurdleAction"))
        if action:
            lines.append(f"  hurdle action: {action}")
    lines.extend(["", "Recent closed records:"])
    if not payload.get("closedRecords"):
        lines.append("- none")
    for record in (payload.get("closedRecords") or [])[-8:]:
        lines.append(
            f"- {record.get('ticker')} {record.get('family')}: "
            f"realised={fmt(record.get('realizedAbsMovePct'), suffix='%')} | "
            f"required={fmt(record.get('impliedMovePct'), suffix='%')} "
            f"({record.get('impliedMoveSource')}) | "
            f"edge={fmt(record.get('moveEdgePct'), suffix='%')} | "
            f"beat={record.get('beatImpliedMove')} | R={fmt(record.get('outcomeR'))}"
        )
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_expected_move_ledger(payload: dict[str, Any]) -> None:
    """Persist expected-move JSON and text artifacts."""
    ensure_dirs()
    atomic_write_json(EXPECTED_MOVE_LEDGER_FILE, payload)
    atomic_write_text(EXPECTED_MOVE_LEDGER_TEXT_FILE, expected_move_ledger_text(payload))


def parse_args() -> argparse.Namespace:
    """Parse the expected-move CLI."""
    parser = argparse.ArgumentParser(description="Build Inferno long-vol expected-move diagnostics.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    """Run the expected-move ledger CLI."""
    args = parse_args()
    if args.command == "status" and EXPECTED_MOVE_LEDGER_TEXT_FILE.exists():
        print(EXPECTED_MOVE_LEDGER_TEXT_FILE.read_text(encoding="utf-8"))
        latest = json.loads(EXPECTED_MOVE_LEDGER_FILE.read_text(encoding="utf-8")) if EXPECTED_MOVE_LEDGER_FILE.exists() else {}
        return 0 if latest.get("promotable") is False else 1
    payload = build_expected_move_ledger()
    save_expected_move_ledger(payload)
    print(expected_move_ledger_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
