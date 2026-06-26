from __future__ import annotations

"""Research-only paper variant scanner for the stalled candidate funnel.

The funnel diagnostic shows the desk is dominated by premium-buy setup
recommendations, while the paper director receives no candidates. This module
does not change the live queue, risk constants, approval queue, paper ledger, or
broker authority. It only creates paper-only variant candidates that downstream
pricing and risk gates may reject.
"""

import argparse
import json
from collections import defaultdict
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
FUNNEL_DIAGNOSTIC_FILE = DATA_DIR / "inferno_funnel_diagnostic.json"
PAPER_VARIANT_SCANNER_FILE = DATA_DIR / "inferno_paper_variant_scanner.json"
PAPER_VARIANT_SCANNER_TEXT_FILE = REPORTS_DIR / "paper_variant_scanner_latest.txt"

STAGE = "paper-variant-scanner-research-only"

DEFAULT_LIMIT = 8
PRICE_CAP = 100.0
WHEEL_PROXY_PRICE_CAP = 30.0
MIN_CREDIT_IV_RANK = 50.0
MIN_WHEEL_IV_RANK = 30.0
MIN_READY = 72.0
MIN_SUPPORT_ATR = 1.0


def text(value: Any) -> str:
    return str(value or "").strip()


def norm(value: Any) -> str:
    return text(value).upper()


def number(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    raw = text(value).replace("$", "").replace(",", "").replace("%", "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return text(value).lower() in {"1", "true", "yes", "y"}


def snapshot_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("rows", "scoredRows", "items", "tickers"):
        rows = snapshot.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def row_market_context(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "trend": text(row.get("trend")) or "Neutral",
        "rvol": number(row.get("rvol")),
        "support": number(row.get("support")),
        "resistance": number(row.get("resistance")),
        "distanceToSupportPct": number(row.get("distanceToSupportPct")),
        "distanceToResistancePct": number(row.get("distanceToResistancePct")),
        "atrPercent": number(row.get("atrPercent")),
        "ivRank": number(row.get("ivRank")),
    }


def support_atr(row: dict[str, Any]) -> float | None:
    distance = number(row.get("distanceToSupportPct"))
    atr = number(row.get("atrPercent"))
    if distance is None or atr is None or atr <= 0:
        return None
    return round(distance / atr, 4)


def base_candidate(row: dict[str, Any], *, family: str, reason: str, score: float) -> dict[str, Any]:
    ticker = norm(row.get("ticker"))
    warnings: list[str] = []
    cushion = support_atr(row)
    if cushion is None:
        warnings.append("missing support/ATR cushion")
    elif cushion < MIN_SUPPORT_ATR:
        warnings.append(f"support cushion {cushion:.2f} ATR is thin")
    rvol = number(row.get("rvol"))
    if rvol is not None and rvol > 1.5:
        warnings.append(f"rvol {rvol:.2f} is elevated for short-premium variants")
    if text(row.get("setupRec")) in {"Straddle", "Strangle", "Vertical Call", "Vertical Put"}:
        warnings.append(f"current setupRec remains premium-buy: {text(row.get('setupRec'))}")

    return {
        "ticker": ticker,
        "sourceFamily": family,
        "paperVariantOnly": True,
        "recommendedStrategy": "PUT_CREDIT_SPREAD",
        "sourceRecommendedStrategy": "PAPER_VARIANT_SCANNER",
        "recommendationVerdict": "paper-variant-research",
        "recommendationReason": reason,
        "candidateStrategyRank": 1,
        "fallbackVariant": False,
        "sourceAlternativeScore": round(score, 4),
        "sourceAlternativeRawScore": round(score, 4),
        "sourceAlternativeEdgeVsLongVol": None,
        "sourceAlternativeWarnings": warnings,
        "baselineUnderlyingPrice": number(row.get("price")),
        "price": number(row.get("price")),
        "daysUntilEarnings": number(row.get("daysUntilEarnings")),
        "readiness": number(row.get("readiness")),
        "confidence": number(row.get("confidence")),
        "signalTrigger": truthy(row.get("signalTrigger")),
        "currentSetupRec": text(row.get("setupRec")),
        "marketContextSummary": row_market_context(row),
        "trend": text(row.get("trend")) or "Neutral",
        "rvol": number(row.get("rvol")),
        "support": number(row.get("support")),
        "resistance": number(row.get("resistance")),
        "distanceToSupportPct": number(row.get("distanceToSupportPct")),
        "distanceToResistancePct": number(row.get("distanceToResistancePct")),
        "atrPercent": number(row.get("atrPercent")),
        "ivRank": number(row.get("ivRank")),
        "supportAtrMultiple": cushion,
    }


def variant_score(row: dict[str, Any], *, family_boost: float = 0.0) -> float:
    readiness = number(row.get("readiness"), 0.0) or 0.0
    iv_rank = number(row.get("ivRank"), 0.0) or 0.0
    cushion = support_atr(row) or 0.0
    rvol = number(row.get("rvol"), 1.0) or 1.0
    rvol_bonus = 8.0 if rvol <= 1.0 else 3.0 if rvol <= 1.25 else -4.0
    return min(100.0, readiness * 0.25 + iv_rank * 0.45 + min(cushion, 4.0) * 8.0 + rvol_bonus + family_boost)


def credit_spread_candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    price = number(row.get("price"))
    iv_rank = number(row.get("ivRank"))
    dte = number(row.get("daysUntilEarnings"))
    readiness = number(row.get("readiness"), 0.0) or 0.0
    if price is None or iv_rank is None:
        return None
    if price >= PRICE_CAP or iv_rank <= MIN_CREDIT_IV_RANK or readiness < MIN_READY:
        return None
    if dte is not None and dte <= 14:
        return None
    if not truthy(row.get("signalTrigger")):
        return None
    reason = "high-IV defined-risk credit candidate outside the near-earnings window"
    return base_candidate(
        row,
        family="credit-spread",
        reason=reason,
        score=variant_score(row, family_boost=6.0),
    )


def wheel_proxy_candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    price = number(row.get("price"))
    iv_rank = number(row.get("ivRank"))
    readiness = number(row.get("readiness"), 0.0) or 0.0
    if price is None or iv_rank is None:
        return None
    if price >= WHEEL_PROXY_PRICE_CAP or iv_rank <= MIN_WHEEL_IV_RANK or readiness < MIN_READY:
        return None
    if not truthy(row.get("signalTrigger")):
        return None
    reason = "cheap high-IV signal name for defined-risk wheel-proxy paper testing"
    return base_candidate(
        row,
        family="wheel-proxy",
        reason=reason,
        score=variant_score(row, family_boost=2.0),
    )


def sweet_spot_watch(row: dict[str, Any]) -> dict[str, Any] | None:
    dte = number(row.get("daysUntilEarnings"))
    atr = number(row.get("atrPercent"))
    if dte is None or atr is None:
        return None
    if not (7 <= dte <= 14 and atr > 2):
        return None
    return {
        "ticker": norm(row.get("ticker")),
        "sourceFamily": "sweet-spot-debit-watch",
        "paperVariantOnly": True,
        "currentSetupRec": text(row.get("setupRec")),
        "baselineUnderlyingPrice": number(row.get("price")),
        "daysUntilEarnings": dte,
        "atrPercent": atr,
        "ivRank": number(row.get("ivRank")),
        "readiness": number(row.get("readiness")),
        "reason": "7-14 DTE plus ATR expansion; watch only unless a supported priced debit variant clears risk",
    }


def dedupe_candidates(candidates: list[dict[str, Any]], *, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in candidates:
        key = (norm(candidate.get("ticker")), text(candidate.get("recommendedStrategy")))
        if not key[0] or not key[1]:
            continue
        existing = by_key.get(key)
        if existing is None or (number(candidate.get("sourceAlternativeScore"), 0.0) or 0.0) > (number(existing.get("sourceAlternativeScore"), 0.0) or 0.0):
            by_key[key] = candidate
    ranked = sorted(
        by_key.values(),
        key=lambda item: (
            -(number(item.get("sourceAlternativeScore"), 0.0) or 0.0),
            norm(item.get("ticker")),
        ),
    )
    for idx, candidate in enumerate(ranked[:limit], start=1):
        candidate["candidateStrategyRank"] = idx
    return ranked[:limit]


def build_paper_variant_scanner(
    *,
    snapshot: dict[str, Any] | None = None,
    funnel: dict[str, Any] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    snapshot = snapshot if snapshot is not None else (load_json_file(SNAPSHOT_FILE) or {})
    funnel = funnel if funnel is not None else (load_json_file(FUNNEL_DIAGNOSTIC_FILE) or {})
    rows = snapshot_rows(snapshot)
    raw_candidates: list[dict[str, Any]] = []
    watch: list[dict[str, Any]] = []
    family_counts: dict[str, int] = defaultdict(int)

    for row in rows:
        credit = credit_spread_candidate(row)
        if credit:
            raw_candidates.append(credit)
            family_counts["credit-spread"] += 1
        wheel = wheel_proxy_candidate(row)
        if wheel:
            raw_candidates.append(wheel)
            family_counts["wheel-proxy"] += 1
        sweet = sweet_spot_watch(row)
        if sweet:
            watch.append(sweet)
            family_counts["sweet-spot-debit-watch"] += 1

    pricing_candidates = dedupe_candidates(raw_candidates, limit=limit)
    verdict = "no-paper-variants"
    if pricing_candidates:
        verdict = "paper-variants-ready-for-pricing"
    elif watch:
        verdict = "watch-only-variants"

    next_actions = [
        "Price paper-only variants through existing strategy-alternative pricing; do not stage without normal risk gates.",
        "Treat wheel-proxy names as defined-risk put-credit research, not cash-secured put authorization.",
        "Keep live authority, approvals, risk constants, and universe membership unchanged.",
    ]
    if not pricing_candidates and not watch:
        next_actions.insert(0, "No safe paper variant patterns were found in the current snapshot.")

    return {
        "generatedAt": local_now().isoformat(),
        "stage": STAGE,
        "verdict": verdict,
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "sourceSnapshotGeneratedAt": snapshot.get("generatedAt"),
        "sourceFunnelGeneratedAt": funnel.get("generatedAt"),
        "sourceFunnelBiasVerdict": funnel.get("biasVerdict"),
        "counts": {
            "universeRows": len(rows),
            "rawCandidates": len(raw_candidates),
            "pricingCandidates": len(pricing_candidates),
            "watchOnly": len(watch),
            "families": dict(sorted(family_counts.items())),
        },
        "pricingCandidates": pricing_candidates,
        "watchOnlyCandidates": watch,
        "nextActions": next_actions,
        "rules": [
            "scanner output is paper-only and diagnostic-only",
            "pricing and paper-risk gates decide whether any variant survives",
            "no live orders, no approvals, no risk-constant changes, and no universe edits",
        ],
        "citations": [
            "inferno_funnel_diagnostic.py premium-buy-monoculture finding",
            "inferno_universe_cap_fit.py cap-fit audit",
            "inferno_strategy_alternative_pricing.py defined-risk pricing gates",
        ],
    }


def scanner_text(payload: dict[str, Any]) -> str:
    counts = payload.get("counts") or {}
    lines = [
        "Inferno Paper Variant Scanner",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Verdict: {payload.get('verdict')}",
        "Authority: research-only; broker submit OFF; live trading OFF",
        "",
        "Counts:",
        f"- universe rows: {counts.get('universeRows', 0)}",
        f"- raw candidates: {counts.get('rawCandidates', 0)}",
        f"- pricing candidates: {counts.get('pricingCandidates', 0)}",
        f"- watch-only candidates: {counts.get('watchOnly', 0)}",
        f"- families: {json.dumps(counts.get('families') or {})}",
        "",
        "Pricing candidates:",
    ]
    for item in payload.get("pricingCandidates") or []:
        lines.append(
            f"- {item.get('ticker')} | {item.get('sourceFamily')} | "
            f"{item.get('recommendedStrategy')} | score {number(item.get('sourceAlternativeScore'), 0.0):.2f} | "
            f"price ${number(item.get('price'), 0.0):.2f} | IVR {number(item.get('ivRank'), 0.0):.1f} | "
            f"support {number(item.get('supportAtrMultiple'), 0.0):.2f} ATR"
        )
        warnings = item.get("sourceAlternativeWarnings") or []
        if warnings:
            lines.append(f"  watch: {'; '.join(str(warning) for warning in warnings[:3])}")
    if not payload.get("pricingCandidates"):
        lines.append("- none")

    lines.extend(["", "Watch-only candidates:"])
    for item in payload.get("watchOnlyCandidates") or []:
        lines.append(
            f"- {item.get('ticker')} | {item.get('sourceFamily')} | "
            f"dte {item.get('daysUntilEarnings')} | ATR% {number(item.get('atrPercent'), 0.0):.2f}"
        )
    if not payload.get("watchOnlyCandidates"):
        lines.append("- none")

    lines.extend(["", "Next actions:"])
    for action in payload.get("nextActions") or []:
        lines.append(f"- {action}")
    lines.extend(["", "Rules:"])
    for rule in payload.get("rules") or []:
        lines.append(f"- {rule}")
    return "\n".join(lines).rstrip() + "\n"


def save_paper_variant_scanner(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or build_paper_variant_scanner()
    ensure_dirs()
    atomic_write_json(PAPER_VARIANT_SCANNER_FILE, payload)
    atomic_write_text(PAPER_VARIANT_SCANNER_TEXT_FILE, scanner_text(payload))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Inferno paper variant scanner report.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        if PAPER_VARIANT_SCANNER_TEXT_FILE.exists():
            print(PAPER_VARIANT_SCANNER_TEXT_FILE.read_text(encoding="utf-8"), end="")
            return 0
        print("(no cached paper variant scanner report)")
        return 1
    payload = save_paper_variant_scanner(build_paper_variant_scanner(limit=args.limit))
    print(scanner_text(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
