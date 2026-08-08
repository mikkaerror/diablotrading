from __future__ import annotations

"""Join current quote-quality and premium-hurdle evidence, research-only.

The pricing lane can create multiple structures for one underlying.  The
paper-blocker swarm diagnoses the source candidate, while the expected-move
ledger records the source long-vol premium hurdle.  This report makes those
relationships explicit without treating each priced variant as an independent
market observation.

It reads local artifacts only.  It cannot change a gate, ticket, cap, eligible
universe, approval, paper stage, or broker authority.
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


STRATEGY_PRICING_FILE = DATA_DIR / "inferno_strategy_alternative_pricing.json"
PAPER_BLOCKER_SWARM_FILE = DATA_DIR / "inferno_paper_blocker_swarm.json"
EXPECTED_MOVE_FILE = DATA_DIR / "inferno_expected_move_ledger.json"

LIQUIDITY_PREMIUM_MATRIX_FILE = DATA_DIR / "inferno_liquidity_premium_matrix.json"
LIQUIDITY_PREMIUM_MATRIX_TEXT_FILE = REPORTS_DIR / "liquidity_premium_matrix_latest.txt"
STAGE = "liquidity-premium-matrix-research-only"

def text(value: Any) -> str:
    """Return a compact display string without trusting source formatting."""
    return str(value or "").strip()


def norm(value: Any) -> str:
    """Normalize a ticker or label for deterministic joins."""
    return text(value).upper()


def number(value: Any) -> float | None:
    """Coerce a source numeric value, returning ``None`` when it is absent."""
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def dedupe(values: list[Any]) -> list[str]:
    """Keep first-seen, non-empty display values once."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = text(value)
        if not item or item.lower() in seen:
            continue
        seen.add(item.lower())
        result.append(item)
    return result


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an artifact timestamp without substituting the current time."""
    raw = text(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def quote_time_label(value: Any) -> str | None:
    """Render the quote snapshot clock time, not an inferred market-session label."""
    parsed = parse_timestamp(value)
    if not parsed:
        return None
    return parsed.strftime("%H:%M %z")


def liquidity_reason(reason: Any) -> bool:
    """Classify existing quote/liquidity evidence without introducing a threshold."""
    raw = text(reason).lower()
    return any(
        token in raw
        for token in (
            "liquidity",
            "quote quality",
            "atm spread",
            "wide-atm-spread",
            "no-liquid",
            "spread is wide",
            "untradeable",
            "open interest",
        )
    )


def premium_reason(reason: Any) -> bool:
    """Classify existing premium-hurdle evidence without creating a new gate."""
    raw = text(reason).lower()
    return any(token in raw for token in ("premium", "expected move", "long-vol"))


def blocker_index(blocker_swarm: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Aggregate source-candidate blocker lanes by ticker, preserving provenance."""
    indexed: dict[str, dict[str, Any]] = {}
    for finding in blocker_swarm.get("candidateFindings") or []:
        if not isinstance(finding, dict):
            continue
        ticker = norm(finding.get("ticker"))
        if not ticker:
            continue
        row = indexed.setdefault(
            ticker,
            {"lanes": [], "reasons": [], "sourceSlates": [], "strategies": []},
        )
        row["lanes"] = dedupe(row["lanes"] + list(finding.get("activeLanes") or []))
        row["reasons"] = dedupe(row["reasons"] + list(finding.get("reasons") or []) + list(finding.get("warnings") or []))
        row["sourceSlates"] = dedupe(row["sourceSlates"] + [finding.get("sourceSlate")])
        row["strategies"] = dedupe(row["strategies"] + [finding.get("strategy")])
    return indexed


def expected_move_index(expected_move: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index source long-vol hurdle evidence by ticker without extrapolation."""
    indexed: dict[str, dict[str, Any]] = {}
    for candidate in expected_move.get("currentCandidates") or []:
        if not isinstance(candidate, dict):
            continue
        ticker = norm(candidate.get("ticker"))
        if ticker and ticker not in indexed:
            indexed[ticker] = candidate
    return indexed


def risk_quote_evidence(item: dict[str, Any]) -> dict[str, Any]:
    """Return the pricing pass's existing normalized quote-quality evidence."""
    risk = item.get("riskVerdict") or {}
    metrics = risk.get("metrics") or {}
    source = metrics.get("schwabOptions") or item.get("schwabOptions") or {}
    return source if isinstance(source, dict) else {}


def source_row(
    item: dict[str, Any],
    *,
    blockers: dict[str, dict[str, Any]],
    expected: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build one priced-variant row while retaining source-candidate distinctions."""
    plan = item.get("strikePlan") or {}
    risk = item.get("riskVerdict") or {}
    ticker = norm(item.get("ticker"))
    quote = risk_quote_evidence(item)
    blocker = blockers.get(ticker) or {}
    expected_candidate = expected.get(ticker) or {}
    risk_blocks = dedupe(
        list(risk.get("blocks") or [])
        + list((plan.get("optimizerBlocks") or []))
        + list(plan.get("liquidityNotes") or [])
    )
    source_lanes = list(blocker.get("lanes") or [])
    quote_snapshot_at = text(quote.get("sourceGeneratedAt")) or None
    priced_structure_liquidity_blocked = (
        quote.get("paperLiquidityPass") is False
        or any(liquidity_reason(reason) for reason in risk_blocks)
    )
    source_candidate_liquidity_blocked = "liquidity" in source_lanes
    priced_structure_premium_blocked = any(premium_reason(reason) for reason in risk_blocks)
    source_candidate_premium_blocked = "premium_hurdle" in source_lanes
    premium_label = text(expected_candidate.get("premiumHurdleLabel")) or None
    quote_evidence_available = bool(quote_snapshot_at)
    liquidity_blocked = bool(priced_structure_liquidity_blocked or source_candidate_liquidity_blocked)
    source_premium_evidence_available = bool(expected_candidate) or source_candidate_premium_blocked
    return {
        "ticker": ticker,
        "pricingStatus": text(item.get("status")) or "unknown",
        "recommendedStrategy": text(item.get("recommendedStrategy") or plan.get("strategy")) or None,
        "expiration": text(item.get("expiration") or plan.get("expiration")) or None,
        "chainSource": text(item.get("chainSource")) or None,
        "capFitFallback": bool(item.get("capFitFallback")),
        "capFitFallbackOfStrategy": text(item.get("capFitFallbackOfStrategy")) or None,
        "capFitFallbackStructure": text(item.get("capFitFallbackStructure")) or None,
        "quoteSnapshotAt": quote_snapshot_at,
        "quoteSnapshotTimeLocal": quote_time_label(quote_snapshot_at),
        "quoteQualityScore": number(quote.get("quoteQualityScore")),
        "quoteQualityLabel": text(quote.get("quoteQualityLabel")) or None,
        "atmSpreadPct": number(quote.get("atmSpreadPct")),
        "atmSpreadQuality": text(quote.get("atmSpreadQuality")) or None,
        "atmWindowOpenInterest": number(quote.get("atmWindowOpenInterest")),
        "atmLiquidityScore": number(quote.get("atmLiquidityScore")),
        "paperLiquidityPass": quote.get("paperLiquidityPass"),
        "qualityFlags": dedupe(list(quote.get("qualityFlags") or [])),
        "quoteEvidenceAvailable": quote_evidence_available,
        "pricedStructureLiquidityBlocked": priced_structure_liquidity_blocked,
        "sourceCandidateLiquidityBlocked": source_candidate_liquidity_blocked,
        "liquidityBlocked": liquidity_blocked,
        "liquidityEvidenceStatus": (
            "blocked" if liquidity_blocked else "observed-no-block" if quote_evidence_available else "unobserved"
        ),
        "liquidityReasons": [reason for reason in risk_blocks if liquidity_reason(reason)],
        "sourceCandidateLanes": source_lanes,
        "sourceCandidateReasons": list(blocker.get("reasons") or []),
        "sourceCandidateStrategies": list(blocker.get("strategies") or []),
        "sourceLongVolHurdleLabel": premium_label,
        "sourceLongVolRequiredMoveAtrMultiple": number(expected_candidate.get("requiredMoveAtrMultiple")),
        "sourceLongVolImpliedMovePct": number(expected_candidate.get("impliedMovePct")),
        "sourceLongVolHurdleAction": text(expected_candidate.get("hurdleAction")) or None,
        "sourceCandidatePremiumHurdleBlocked": source_candidate_premium_blocked,
        "sourcePremiumPressure": source_candidate_premium_blocked,
        "sourcePremiumEvidenceAvailable": source_premium_evidence_available,
        "sourcePremiumEvidenceStatus": (
            "source-pressure"
            if source_candidate_premium_blocked
            else "observed-no-pressure"
            if source_premium_evidence_available
            else "unobserved"
        ),
        "pricedStructurePremiumEvidenceBlocked": priced_structure_premium_blocked,
        "pricedStructurePremiumReasons": [reason for reason in risk_blocks if premium_reason(reason)],
        "combinedPassed": bool(item.get("combinedPassed", risk.get("passed"))),
        "riskBlocks": risk_blocks,
    }


def aggregate_rows(rows: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    """Summarize variant rows by one observation dimension with explicit counts."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = text(row.get(key)) or "missing"
        groups[value].append(row)

    summary: list[dict[str, Any]] = []
    for value, group in groups.items():
        tickers = sorted({row.get("ticker") for row in group if row.get("ticker")})
        snapshots = {
            f"{row.get('ticker')}|{row.get('quoteSnapshotAt')}"
            for row in group
            if row.get("ticker") and row.get("quoteSnapshotAt")
        }
        summary.append(
            {
                key: None if value == "missing" else value,
                "pricingRows": len(group),
                "tickerExposures": len(tickers),
                "tickers": tickers,
                "quoteObservations": len(snapshots),
                "liquidityBlockedRows": sum(bool(row.get("liquidityBlocked")) for row in group),
                "sourcePremiumPressureRows": sum(bool(row.get("sourcePremiumPressure")) for row in group),
                "pricedStructurePremiumEvidenceBlockedRows": sum(
                    bool(row.get("pricedStructurePremiumEvidenceBlocked")) for row in group
                ),
                "liquidityAndSourcePremiumPressureRows": sum(
                    bool(row.get("liquidityBlocked")) and bool(row.get("sourcePremiumPressure"))
                    for row in group
                ),
                "liquidityAndPricedStructurePremiumBlockedRows": sum(
                    bool(row.get("liquidityBlocked")) and bool(row.get("pricedStructurePremiumEvidenceBlocked"))
                    for row in group
                ),
            }
        )
    return sorted(summary, key=lambda row: (-row["tickerExposures"], text(row.get(key))))


def ticker_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse variants to one ticker exposure for non-duplicative headlines."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("ticker"):
            grouped[row["ticker"]].append(row)
    summaries: list[dict[str, Any]] = []
    for ticker, group in grouped.items():
        snapshots = {
            f"{ticker}|{row.get('quoteSnapshotAt')}"
            for row in group
            if row.get("quoteSnapshotAt")
        }
        summaries.append(
            {
                "ticker": ticker,
                "pricingRows": len(group),
                "pricedRows": sum(row.get("pricingStatus") == "priced" for row in group),
                "expirations": sorted({row["expiration"] for row in group if row.get("expiration")}),
                "strategies": sorted({row["recommendedStrategy"] for row in group if row.get("recommendedStrategy")}),
                "quoteObservations": len(snapshots),
                "quoteSnapshotTimesLocal": sorted({row["quoteSnapshotTimeLocal"] for row in group if row.get("quoteSnapshotTimeLocal")}),
                "liquidityBlocked": any(row.get("liquidityBlocked") for row in group),
                "sourcePremiumPressure": any(row.get("sourcePremiumPressure") for row in group),
                "sourcePremiumEvidenceStatus": (
                    "source-pressure"
                    if any(row.get("sourcePremiumPressure") for row in group)
                    else "observed-no-pressure"
                    if any(row.get("sourcePremiumEvidenceAvailable") for row in group)
                    else "unobserved"
                ),
                "pricedStructurePremiumEvidenceBlocked": any(
                    row.get("pricedStructurePremiumEvidenceBlocked") for row in group
                ),
                "quoteEvidenceAvailable": any(row.get("quoteEvidenceAvailable") for row in group),
                "sourcePremiumEvidenceAvailable": any(row.get("sourcePremiumEvidenceAvailable") for row in group),
                "sourceLongVolHurdleLabels": sorted({row["sourceLongVolHurdleLabel"] for row in group if row.get("sourceLongVolHurdleLabel")}),
                "capFitFallbackRows": sum(bool(row.get("capFitFallback")) for row in group),
                "combinedPassedRows": sum(bool(row.get("combinedPassed")) for row in group),
            }
        )
    return sorted(summaries, key=lambda row: row["ticker"])


def matrix_verdict(ticker_rows: list[dict[str, Any]]) -> str:
    """Return a descriptive research verdict, never an eligibility decision."""
    if not ticker_rows:
        return "no-pricing-candidates"
    liquidity = any(row.get("liquidityBlocked") for row in ticker_rows)
    source_premium_pressure = any(row.get("sourcePremiumPressure") for row in ticker_rows)
    if liquidity and source_premium_pressure:
        return "mixed-market-quality-and-premium-pressure"
    if liquidity:
        return "market-quality-blocked"
    if source_premium_pressure:
        return "premium-pressure-observed"
    return "no-current-market-quality-or-premium-pressure"


def build_liquidity_premium_matrix(
    *,
    strategy_pricing: dict[str, Any] | None = None,
    paper_blocker_swarm: dict[str, Any] | None = None,
    expected_move: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the local, read-only liquidity/premium reconciliation artifact."""
    pricing = strategy_pricing if strategy_pricing is not None else (load_json_file(STRATEGY_PRICING_FILE) or {})
    swarm = paper_blocker_swarm if paper_blocker_swarm is not None else (load_json_file(PAPER_BLOCKER_SWARM_FILE) or {})
    expected = expected_move if expected_move is not None else (load_json_file(EXPECTED_MOVE_FILE) or {})
    blockers = blocker_index(swarm)
    expected_by_ticker = expected_move_index(expected)
    rows = [
        source_row(item, blockers=blockers, expected=expected_by_ticker)
        for item in pricing.get("items") or []
        if isinstance(item, dict) and norm(item.get("ticker"))
    ]
    ticker_rows = ticker_summaries(rows)
    verdict = matrix_verdict(ticker_rows)
    quote_observations = {
        f"{row.get('ticker')}|{row.get('quoteSnapshotAt')}"
        for row in rows
        if row.get("ticker") and row.get("quoteSnapshotAt")
    }
    counts = {
        "pricingRows": len(rows),
        "pricedRows": sum(row.get("pricingStatus") == "priced" for row in rows),
        "unpricedOrFailedRows": sum(row.get("pricingStatus") != "priced" for row in rows),
        "tickerExposures": len(ticker_rows),
        "quoteObservations": len(quote_observations),
        "rowsWithQuoteEvidence": sum(row.get("quoteSnapshotAt") is not None for row in rows),
        "rowsWithoutQuoteEvidence": sum(row.get("quoteSnapshotAt") is None for row in rows),
        "liquidityBlockedRows": sum(bool(row.get("liquidityBlocked")) for row in rows),
        "sourcePremiumPressureRows": sum(bool(row.get("sourcePremiumPressure")) for row in rows),
        "pricedStructurePremiumEvidenceBlockedRows": sum(
            bool(row.get("pricedStructurePremiumEvidenceBlocked")) for row in rows
        ),
        "liquidityAndSourcePremiumPressureRows": sum(
            bool(row.get("liquidityBlocked")) and bool(row.get("sourcePremiumPressure")) for row in rows
        ),
        "liquidityAndPricedStructurePremiumBlockedRows": sum(
            bool(row.get("liquidityBlocked")) and bool(row.get("pricedStructurePremiumEvidenceBlocked"))
            for row in rows
        ),
        "liquidityBlockedTickers": sum(bool(row.get("liquidityBlocked")) for row in ticker_rows),
        "tickerExposuresWithoutQuoteEvidence": sum(not bool(row.get("quoteEvidenceAvailable")) for row in ticker_rows),
        "sourcePremiumPressureTickers": sum(bool(row.get("sourcePremiumPressure")) for row in ticker_rows),
        "pricedStructurePremiumEvidenceBlockedTickers": sum(
            bool(row.get("pricedStructurePremiumEvidenceBlocked")) for row in ticker_rows
        ),
        "liquidityAndSourcePremiumPressureTickers": sum(
            bool(row.get("liquidityBlocked")) and bool(row.get("sourcePremiumPressure"))
            for row in ticker_rows
        ),
        "liquidityAndPricedStructurePremiumBlockedTickers": sum(
            bool(row.get("liquidityBlocked")) and bool(row.get("pricedStructurePremiumEvidenceBlocked"))
            for row in ticker_rows
        ),
        "capFitFallbackRows": sum(bool(row.get("capFitFallback")) for row in rows),
        "capFitFallbackTickers": sum(bool(row.get("capFitFallbackRows")) for row in ticker_rows),
        "combinedPassedRows": sum(bool(row.get("combinedPassed")) for row in rows),
    }
    generated = now or local_now()
    return {
        "generatedAt": generated.isoformat(),
        "stage": STAGE,
        "verdict": verdict,
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "sources": {
            "strategyPricingGeneratedAt": pricing.get("generatedAt"),
            "paperBlockerSwarmGeneratedAt": swarm.get("generatedAt"),
            "expectedMoveLedgerGeneratedAt": expected.get("generatedAt"),
        },
        "counts": counts,
        "tickerExposures": ticker_rows,
        "byExpiry": aggregate_rows(rows, key="expiration"),
        "byQuoteSnapshotTimeLocal": aggregate_rows(rows, key="quoteSnapshotTimeLocal"),
        "byQuoteQualityLabel": aggregate_rows(rows, key="quoteQualityLabel"),
        "bySourceLongVolHurdle": aggregate_rows(rows, key="sourceLongVolHurdleLabel"),
        "rows": sorted(
            rows,
            key=lambda row: (
                not bool(row.get("liquidityBlocked")),
                not bool(row.get("sourcePremiumPressure")),
                not bool(row.get("pricedStructurePremiumEvidenceBlocked")),
                row.get("ticker") or "",
                row.get("recommendedStrategy") or "",
            ),
        ),
        "countSemantics": [
            "pricingRows counts each priced-structure request; one ticker can have several variants.",
            "tickerExposures deduplicates underlying symbols for market-observation headlines.",
            "quoteObservations deduplicates ticker plus source snapshot timestamp; variants sharing a quote are not independent quotes.",
            "Source-premium pressure records the original long-vol candidate only; it is not an alternative-structure gate failure.",
            "Structure-specific premium blocks come only from the alternative pricing risk record; do not add source-pressure and structure-block counts to estimate unique failures.",
            "A missing quote or source premium record is unobserved, not clear; it is excluded from blocker and pressure counts rather than inferred to pass.",
        ],
        "limitations": [
            "Quote snapshot time is the source artifact clock time, not an intraday time-of-day study or proof of a recurring session effect.",
            "Expected-move labels and source premium pressure describe the source long-vol candidate; they do not by themselves fail or pass an alternative structure.",
            "This matrix records existing gate evidence only and creates no new threshold, recommendation, or promotion path.",
        ],
        "reminders": [
            "research-only; no paper ticket is approved, staged, closed, or promoted",
            "broker submit remains OFF and live trading remains OFF",
            "do not change risk constants, eligible universe, or quality/promotion gates from this report",
        ],
    }


def fmt(value: Any, *, suffix: str = "") -> str:
    """Format an optional diagnostic scalar for the text memo."""
    parsed = number(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:.4g}{suffix}"


def pct(value: Any) -> str:
    """Render the normalized quote ratio as a human percentage."""
    parsed = number(value)
    if parsed is None:
        return "n/a"
    return f"{parsed * 100:.4g}%"


def render_text(payload: dict[str, Any]) -> str:
    """Render a concise, operator-readable matrix with its count semantics."""
    counts = payload.get("counts") or {}
    lines = [
        "Inferno Liquidity / Premium Blocker Matrix",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Verdict: {payload.get('verdict')}",
        "Contract: research-only; broker submit OFF; live trading OFF; no gate changes",
        "",
        "Counts:",
        f"- pricing rows / priced / unpriced-or-failed: {counts.get('pricingRows', 0)} / {counts.get('pricedRows', 0)} / {counts.get('unpricedOrFailedRows', 0)}",
        f"- ticker exposures / quote observations: {counts.get('tickerExposures', 0)} / {counts.get('quoteObservations', 0)}",
        f"- rows / ticker exposures without quote evidence: {counts.get('rowsWithoutQuoteEvidence', 0)} / {counts.get('tickerExposuresWithoutQuoteEvidence', 0)}",
        f"- liquidity blocked rows / tickers: {counts.get('liquidityBlockedRows', 0)} / {counts.get('liquidityBlockedTickers', 0)}",
        f"- source premium-pressure rows / tickers: {counts.get('sourcePremiumPressureRows', 0)} / {counts.get('sourcePremiumPressureTickers', 0)}",
        f"- structure-specific premium-block rows / tickers: {counts.get('pricedStructurePremiumEvidenceBlockedRows', 0)} / {counts.get('pricedStructurePremiumEvidenceBlockedTickers', 0)}",
        f"- liquidity plus source-premium-pressure rows / tickers: {counts.get('liquidityAndSourcePremiumPressureRows', 0)} / {counts.get('liquidityAndSourcePremiumPressureTickers', 0)}",
        f"- cap-fit fallback rows / tickers: {counts.get('capFitFallbackRows', 0)} / {counts.get('capFitFallbackTickers', 0)}",
        f"- combined-passed rows: {counts.get('combinedPassedRows', 0)}",
        "",
        "Count semantics:",
    ]
    lines.extend(f"- {item}" for item in payload.get("countSemantics") or [])
    lines.extend(["", "Ticker exposures:"])
    if not payload.get("tickerExposures"):
        lines.append("- none")
    for row in payload.get("tickerExposures") or []:
        lines.append(
            f"- {row.get('ticker')} | variants {row.get('pricingRows')} | exp {', '.join(row.get('expirations') or []) or 'n/a'} | "
            f"liq {'block' if row.get('liquidityBlocked') else 'observed-clear' if row.get('quoteEvidenceAvailable') else 'unobserved'} | "
            f"source premium {row.get('sourcePremiumEvidenceStatus')} | "
            f"structure premium {'block' if row.get('pricedStructurePremiumEvidenceBlocked') else 'not-flagged'} | "
            f"source hurdle {', '.join(row.get('sourceLongVolHurdleLabels') or []) or 'n/a'}"
        )
    lines.extend(["", "Pricing-row matrix:"])
    if not payload.get("rows"):
        lines.append("- none")
    for row in payload.get("rows") or []:
        lines.append(
            f"- {row.get('ticker')} | {row.get('recommendedStrategy') or 'n/a'} | {row.get('pricingStatus')} | "
            f"exp {row.get('expiration') or 'n/a'} | quote {row.get('quoteSnapshotTimeLocal') or 'n/a'} | "
            f"spread {pct(row.get('atmSpreadPct'))} | OI {fmt(row.get('atmWindowOpenInterest'))} | "
            f"quote {row.get('quoteQualityLabel') or 'n/a'} | source hurdle {row.get('sourceLongVolHurdleLabel') or 'n/a'} | "
            f"ATRx {fmt(row.get('sourceLongVolRequiredMoveAtrMultiple'))} | "
            f"liq {row.get('liquidityEvidenceStatus')} | source premium {row.get('sourcePremiumEvidenceStatus')} | "
            f"structure premium {'blocked' if row.get('pricedStructurePremiumEvidenceBlocked') else 'not-flagged'}"
        )
        if row.get("capFitFallback"):
            lines.append(
                f"  cap-fit route: {row.get('capFitFallbackOfStrategy') or 'n/a'} -> {row.get('capFitFallbackStructure') or 'n/a'}"
            )
    lines.extend(["", "Limits:"])
    lines.extend(f"- {item}" for item in payload.get("limitations") or [])
    lines.extend(["", "Reminders:"])
    lines.extend(f"- {item}" for item in payload.get("reminders") or [])
    return "\n".join(lines).rstrip() + "\n"


def save_liquidity_premium_matrix(payload: dict[str, Any]) -> None:
    """Persist the data and text artifacts atomically."""
    ensure_dirs()
    atomic_write_json(LIQUIDITY_PREMIUM_MATRIX_FILE, payload)
    atomic_write_text(LIQUIDITY_PREMIUM_MATRIX_TEXT_FILE, render_text(payload))


def parse_args() -> argparse.Namespace:
    """Parse the small read-only command surface."""
    parser = argparse.ArgumentParser(description="Build the research-only liquidity/premium matrix.")
    parser.add_argument("command", nargs="?", choices=("run", "status"), default="run")
    return parser.parse_args()


def main() -> None:
    """Build or display the latest matrix without contacting external services."""
    args = parse_args()
    if args.command == "status":
        print(render_text(load_json_file(LIQUIDITY_PREMIUM_MATRIX_FILE) or {}))
        return
    payload = build_liquidity_premium_matrix()
    save_liquidity_premium_matrix(payload)
    print(render_text(payload))


if __name__ == "__main__":
    main()
