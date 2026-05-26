from __future__ import annotations

"""Research-only register for comparing passing condors against alternatives.

The strategy alternative pricing pass can find a clean structure without
meaning that the desk should stage anything. This module snapshots those
passing structures into a separate comparison register so the desk can watch
PL/MRVL/ORCL-style condors against the long-vol pressure and put-credit ideas
that led to the test.

Strict contract:
- read-only with respect to execution, approval, paper, broker, and shadow
  evidence ledgers
- diagnostic-only and non-promotable
- never creates, stages, or queues an order
"""

import argparse
from collections import defaultdict
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


STRATEGY_SHADOW_COMPARISON_FILE = DATA_DIR / "inferno_strategy_shadow_comparison.json"
STRATEGY_SHADOW_COMPARISON_TEXT_FILE = REPORTS_DIR / "strategy_shadow_comparison_latest.txt"
STRATEGY_SHADOW_COMPARISON_STAGE = "strategy-shadow-comparison-research-only"

STRATEGY_ALTERNATIVE_PRICING_FILE = DATA_DIR / "inferno_strategy_alternative_pricing.json"
EXPECTED_MOVE_LEDGER_FILE = DATA_DIR / "inferno_expected_move_ledger.json"


def text(value: Any) -> str:
    """Normalize loose values into stripped display text."""
    return str(value or "").strip()


def norm(value: Any) -> str:
    """Normalize ticker/strategy labels."""
    return text(value).upper()


def number(value: Any, default: float | None = None) -> float | None:
    """Coerce artifact numbers while tolerating display strings."""
    if isinstance(value, (int, float)):
        return float(value)
    raw = text(value).replace("$", "").replace(",", "").replace("%", "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def fmt_money(value: Any) -> str:
    amount = number(value)
    if amount is None:
        return "n/a"
    return f"${amount:.2f}"


def fmt_num(value: Any) -> str:
    amount = number(value)
    if amount is None:
        return "n/a"
    return f"{amount:.4g}"


def strategy_from_item(item: dict[str, Any]) -> str:
    plan = item.get("strikePlan") or {}
    return norm(plan.get("strategy") or item.get("recommendedStrategy"))


def combined_passed(item: dict[str, Any]) -> bool:
    return item.get("status") == "priced" and bool(item.get("combinedPassed"))


def plan_summary(item: dict[str, Any]) -> dict[str, Any]:
    """Return the compact option-plan fields needed for comparison."""
    plan = item.get("strikePlan") or {}
    risk = item.get("riskVerdict") or {}
    return {
        "strategy": strategy_from_item(item),
        "expiration": plan.get("expiration") or item.get("expiration"),
        "estimatedCredit": plan.get("estimatedCredit"),
        "estimatedDebit": plan.get("estimatedDebit"),
        "estimatedMaxLoss": plan.get("estimatedMaxLoss"),
        "estimatedMaxProfit": plan.get("estimatedMaxProfit"),
        "creditRisk": plan.get("creditRisk"),
        "breakEven": plan.get("breakEven"),
        "breakEvenLower": plan.get("breakEvenLower"),
        "breakEvenUpper": plan.get("breakEvenUpper"),
        "shortPutStrike": plan.get("shortPutStrike"),
        "longPutStrike": plan.get("longPutStrike"),
        "shortCallStrike": plan.get("shortCallStrike"),
        "longCallStrike": plan.get("longCallStrike"),
        "supportReference": plan.get("supportReference"),
        "resistanceReference": plan.get("resistanceReference"),
        "supportCushionToShortPct": plan.get("supportCushionToShortPct"),
        "supportCushionToShortPutPct": plan.get("supportCushionToShortPutPct"),
        "resistanceCushionToShortCallPct": plan.get("resistanceCushionToShortCallPct"),
        "rangeSafe": plan.get("rangeSafe"),
        "greekSummary": plan.get("greekSummary") or {},
        "optimizerPassed": bool(item.get("optimizerPassed")),
        "paperRiskPassed": bool(item.get("paperRiskPassed", risk.get("passed"))),
        "combinedPassed": bool(item.get("combinedPassed")),
        "optimizerBlocks": plan.get("optimizerBlocks") or item.get("optimizerBlocks") or [],
        "riskBlocks": risk.get("blocks") or [],
        "warnings": (plan.get("optimizerWarnings") or []) + (risk.get("warnings") or []),
    }


def market_reference(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Return shared underlying/ATR/support context for one ticker."""
    first = items[0] if items else {}
    intent = first.get("intent") or {}
    market = first.get("marketContextSummary") or {}
    price = number(first.get("price") or first.get("sourcePrice") or intent.get("price"))
    atr_points = number(intent.get("atr20Day"))
    atr_percent = number(intent.get("atrPercent"))
    if atr_points is None and price is not None and atr_percent is not None:
        atr_points = round(price * atr_percent / 100.0, 6)
    return {
        "underlyingPrice": price,
        "atrPoints": atr_points,
        "atrPercent": atr_percent,
        "support": number(market.get("support")),
        "resistance": number(market.get("resistance")),
        "trend": market.get("trend"),
        "rvol": market.get("rvol"),
    }


def credit_structure_expiration_pnl(plan: dict[str, Any], underlying_price: Any) -> float | None:
    """Estimate expiration P/L for supported defined-risk structures."""
    price = number(underlying_price)
    strategy = norm(plan.get("strategy"))
    credit = number(plan.get("estimatedCredit"), 0.0) or 0.0
    debit = number(plan.get("estimatedDebit"), 0.0) or 0.0
    if price is None:
        return None

    pnl = credit * 100.0 - debit * 100.0
    if strategy in {"PUT_CREDIT_SPREAD", "PUT_DEBIT_SPREAD", "IRON_CONDOR"}:
        short_put = number(plan.get("shortPutStrike"))
        long_put = number(plan.get("longPutStrike"))
        if short_put is not None:
            pnl -= max(0.0, short_put - price) * 100.0
        if long_put is not None:
            pnl += max(0.0, long_put - price) * 100.0
    if strategy == "IRON_CONDOR":
        short_call = number(plan.get("shortCallStrike"))
        long_call = number(plan.get("longCallStrike"))
        if short_call is not None:
            pnl -= max(0.0, price - short_call) * 100.0
        if long_call is not None:
            pnl += max(0.0, price - long_call) * 100.0
    return round(pnl, 2)


def scenario_points(market: dict[str, Any], primary_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Create key underlying prices for expiration payoff comparison."""
    price = number(market.get("underlyingPrice"))
    atr = number(market.get("atrPoints"))
    raw: list[tuple[str, float | None]] = [
        ("support", number(market.get("support"))),
        ("minus_1_atr", price - atr if price is not None and atr is not None else None),
        ("current", price),
        ("plus_1_atr", price + atr if price is not None and atr is not None else None),
        ("resistance", number(market.get("resistance"))),
        ("condor_lower_breakeven", number(primary_plan.get("breakEvenLower"))),
        ("condor_upper_breakeven", number(primary_plan.get("breakEvenUpper"))),
    ]
    seen: set[float] = set()
    points: list[dict[str, Any]] = []
    for label, value in raw:
        if value is None:
            continue
        rounded = round(value, 4)
        if rounded in seen:
            continue
        seen.add(rounded)
        move_pct = None
        move_atr = None
        if price:
            move_pct = round((rounded - price) / price * 100.0, 4)
        if price is not None and atr:
            move_atr = round((rounded - price) / atr, 4)
        points.append(
            {
                "label": label,
                "underlyingPrice": rounded,
                "movePct": move_pct,
                "moveAtrMultiple": move_atr,
            }
        )
    return sorted(points, key=lambda item: item["underlyingPrice"])


def payoff_grid(comparisons: list[dict[str, Any]], market: dict[str, Any], primary_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Build expiration payoff rows for priced alternatives in the register."""
    priced = [row for row in comparisons if row.get("type") == "priced-alternative"]
    grid: list[dict[str, Any]] = []
    for point in scenario_points(market, primary_plan):
        payoffs: dict[str, dict[str, Any]] = {}
        for row in priced:
            strategy = str(row.get("strategy") or "UNKNOWN")
            plan = row.get("plan") or {}
            pnl = credit_structure_expiration_pnl(plan, point.get("underlyingPrice"))
            max_loss = number(plan.get("estimatedMaxLoss"))
            payoffs[strategy] = {
                "pnl": pnl,
                "rMultiple": round(pnl / max_loss, 4) if pnl is not None and max_loss else None,
                "combinedPassed": bool(row.get("combinedPassed")),
            }
        ranked = sorted(
            ((strategy, values.get("pnl")) for strategy, values in payoffs.items() if values.get("pnl") is not None),
            key=lambda item: item[1],
            reverse=True,
        )
        grid.append(
            {
                **point,
                "payoffs": payoffs,
                "bestStrategyByPnl": ranked[0][0] if ranked else None,
            }
        )
    return grid


def comparison_row(item: dict[str, Any]) -> dict[str, Any]:
    """Convert one priced alternative into a shadow-comparison row."""
    plan = plan_summary(item)
    blocks = list(plan.get("optimizerBlocks") or []) + list(plan.get("riskBlocks") or [])
    return {
        "type": "priced-alternative",
        "ticker": norm(item.get("ticker")),
        "strategy": plan.get("strategy"),
        "status": item.get("status"),
        "combinedPassed": bool(item.get("combinedPassed")),
        "optimizerPassed": bool(item.get("optimizerPassed")),
        "paperRiskPassed": bool(item.get("paperRiskPassed")),
        "fallbackVariant": bool(item.get("fallbackVariant")),
        "candidateStrategyRank": item.get("candidateStrategyRank"),
        "sourceRecommendedStrategy": item.get("sourceRecommendedStrategy"),
        "recommendationVerdict": item.get("recommendationVerdict"),
        "sourceAlternativeScore": item.get("sourceAlternativeScore"),
        "sourceAlternativeEdgeVsLongVol": item.get("sourceAlternativeEdgeVsLongVol"),
        "longVolHurdle": item.get("longVolHurdle"),
        "longVolAtrMultiple": item.get("longVolAtrMultiple"),
        "longVolPressureScore": item.get("longVolPressureScore"),
        "blockReasons": blocks,
        "plan": plan,
    }


def expected_move_lookup(expected_move: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index current long-vol pressure records by ticker."""
    lookup: dict[str, dict[str, Any]] = {}
    for key in ("currentPressureCandidates", "currentCandidates"):
        for item in expected_move.get(key) or []:
            if not isinstance(item, dict):
                continue
            ticker = norm(item.get("ticker"))
            if ticker and ticker not in lookup:
                lookup[ticker] = item
    return lookup


def long_vol_baseline(ticker: str, items: list[dict[str, Any]], expected: dict[str, Any] | None) -> dict[str, Any]:
    """Build the long-vol comparison baseline from pricing and expected-move context."""
    first = items[0] if items else {}
    expected = expected or {}
    hurdle = expected.get("premiumHurdleLabel") or first.get("longVolHurdle")
    atr_multiple = expected.get("requiredMoveAtrMultiple") or first.get("longVolAtrMultiple")
    pressure = expected.get("rankPressureScore") or first.get("longVolPressureScore")
    strategy = expected.get("strategy") or "LONG_VOL"
    return {
        "type": "long-vol-baseline",
        "ticker": ticker,
        "strategy": strategy,
        "status": expected.get("status") or "current-context",
        "premiumHurdleLabel": hurdle,
        "requiredMoveAtrMultiple": atr_multiple,
        "rankPressureScore": pressure,
        "entryDebit": expected.get("entryDebit") or expected.get("estimatedDebit"),
        "requiredMovePct": expected.get("requiredMovePct") or expected.get("breakEvenMovePercent"),
        "source": "expected-move-ledger" if expected else "strategy-alternative-pricing",
        "comparisonUse": "pressure baseline; not a staged long-vol ticket",
    }


def best_passing_variant(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Select the passing structure to track as the primary shadow comparison."""
    passed = [item for item in items if combined_passed(item)]
    passed.sort(
        key=lambda item: (
            strategy_from_item(item) != "IRON_CONDOR",
            -(number((item.get("strikePlan") or {}).get("creditRisk"), 0.0) or 0.0),
            number((item.get("strikePlan") or {}).get("estimatedMaxLoss"), 999999.0) or 999999.0,
            number(item.get("candidateStrategyRank"), 99.0) or 99.0,
        )
    )
    return passed[0]


def build_register_entry(
    ticker: str,
    items: list[dict[str, Any]],
    expected: dict[str, Any] | None,
    *,
    generated_at: str,
) -> dict[str, Any]:
    """Build one ticker's non-executable comparison register row."""
    primary = best_passing_variant(items)
    primary_plan = plan_summary(primary)
    market = market_reference(items)
    comparisons = [long_vol_baseline(ticker, items, expected)]
    comparisons.extend(
        comparison_row(item)
        for item in sorted(
            items,
            key=lambda row: (
                strategy_from_item(row) != "PUT_CREDIT_SPREAD",
                strategy_from_item(row) != "IRON_CONDOR",
                number(row.get("candidateStrategyRank"), 99.0) or 99.0,
            ),
        )
    )
    put_credit_blocks = [
        reason
        for row in comparisons
        if row.get("strategy") == "PUT_CREDIT_SPREAD"
        for reason in row.get("blockReasons") or []
    ]
    return {
        "registerId": f"shadow-compare-{ticker.lower()}-{primary_plan.get('expiration') or 'no-exp'}",
        "createdAt": generated_at,
        "sourcePricingGeneratedAt": primary.get("generatedAt"),
        "ticker": ticker,
        "registerStatus": "shadow-compare-open",
        "action": "track-shadow-comparison",
        "bestPassingVariant": comparison_row(primary),
        "comparisons": comparisons,
        "marketReference": market,
        "expirationPayoffGrid": payoff_grid(comparisons, market, primary_plan),
        "trackingPlan": {
            "reviewTrigger": "manual expiration/outcome review before any promotion decision",
            "expiration": primary_plan.get("expiration"),
            "compareAgainst": [
                "same-underlying move",
                "long-vol required-move hurdle",
                "put-credit spread optimizer/risk blocks",
                "defined-risk expiration payoff",
            ],
        },
        "putCreditBlockSummary": put_credit_blocks,
        "shadowOnly": True,
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
        "paperStageAllowed": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "mutatesShadowLedger": False,
    }


def build_strategy_shadow_comparison(
    pricing: dict[str, Any] | None = None,
    expected_move: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the research-only comparison register from existing artifacts."""
    ensure_dirs()
    pricing = pricing if pricing is not None else load_json_file(STRATEGY_ALTERNATIVE_PRICING_FILE) or {}
    expected_move = expected_move if expected_move is not None else load_json_file(EXPECTED_MOVE_LEDGER_FILE) or {}
    generated_at = local_now().isoformat()
    items = [item for item in pricing.get("items") or [] if isinstance(item, dict)]

    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        ticker = norm(item.get("ticker"))
        if ticker:
            by_ticker[ticker].append(item)

    expected_by_ticker = expected_move_lookup(expected_move)
    register: list[dict[str, Any]] = []
    for ticker in sorted(by_ticker):
        ticker_items = by_ticker[ticker]
        if not any(combined_passed(item) for item in ticker_items):
            continue
        register.append(
            build_register_entry(
                ticker,
                ticker_items,
                expected_by_ticker.get(ticker),
                generated_at=generated_at,
            )
        )

    counts = {
        "pricingItems": len(items),
        "groups": len(register),
        "passingVariants": sum(1 for item in items if combined_passed(item)),
        "trackedCondors": sum(
            1
            for entry in register
            if (entry.get("bestPassingVariant") or {}).get("strategy") == "IRON_CONDOR"
        ),
        "blockedPutCreditComparisons": sum(
            1
            for entry in register
            for row in entry.get("comparisons") or []
            if row.get("strategy") == "PUT_CREDIT_SPREAD" and not row.get("combinedPassed")
        ),
        "longVolBaselines": sum(
            1
            for entry in register
            for row in entry.get("comparisons") or []
            if row.get("type") == "long-vol-baseline"
        ),
        "payoffGridRows": sum(len(entry.get("expirationPayoffGrid") or []) for entry in register),
        "paperStageAllowed": 0,
        "brokerSubmitAllowed": 0,
        "liveTradingAllowed": 0,
    }
    return {
        "generatedAt": generated_at,
        "stage": STRATEGY_SHADOW_COMPARISON_STAGE,
        "verdict": "shadow-comparison-ready" if register else "no-passing-alternatives",
        "researchOnly": True,
        "diagnosticOnly": True,
        "shadowOnly": True,
        "promotable": False,
        "paperStageAllowed": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "mutatesShadowLedger": False,
        "sourcePricing": {
            "generatedAt": pricing.get("generatedAt"),
            "verdict": pricing.get("verdict"),
            "counts": pricing.get("counts") or {},
        },
        "sourceExpectedMove": {
            "generatedAt": expected_move.get("generatedAt"),
            "verdict": expected_move.get("verdict"),
        },
        "counts": counts,
        "register": register,
        "rules": [
            "Register rows are shadow comparison only and cannot stage paper or live orders.",
            "Passing condors remain research context until separate human review and normal desk gates approve any future action.",
            "Put-credit and long-vol alternatives are retained as baselines so the desk can compare theory against realized outcomes.",
        ],
    }


def render_strategy_shadow_comparison(payload: dict[str, Any]) -> str:
    """Render the comparison register for quick operator review."""
    counts = payload.get("counts") or {}
    lines = [
        "Inferno Strategy Shadow Comparison Register",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Verdict: {payload.get('verdict')}",
        f"Research only: {payload.get('researchOnly')} | promotable: {payload.get('promotable')}",
        f"Paper stage allowed: {payload.get('paperStageAllowed')} | broker submit allowed: {payload.get('brokerSubmitAllowed')} | live allowed: {payload.get('liveTradingAllowed')}",
        f"Mutates shadow ledger: {payload.get('mutatesShadowLedger')}",
        "",
        "Counts:",
        f"- groups: {counts.get('groups', 0)}",
        f"- passing variants: {counts.get('passingVariants', 0)}",
        f"- tracked condors: {counts.get('trackedCondors', 0)}",
        f"- blocked put-credit comparisons: {counts.get('blockedPutCreditComparisons', 0)}",
        f"- long-vol baselines: {counts.get('longVolBaselines', 0)}",
        f"- payoff grid rows: {counts.get('payoffGridRows', 0)}",
        "",
        "Register:",
    ]
    register = payload.get("register") or []
    if not register:
        lines.append("- none")
    for entry in register:
        best = entry.get("bestPassingVariant") or {}
        plan = best.get("plan") or {}
        long_vol = next(
            (row for row in entry.get("comparisons") or [] if row.get("type") == "long-vol-baseline"),
            {},
        )
        put_credit = next(
            (row for row in entry.get("comparisons") or [] if row.get("strategy") == "PUT_CREDIT_SPREAD"),
            {},
        )
        lines.append(
            "- "
            f"{entry.get('ticker')} | best {best.get('strategy')} | exp {plan.get('expiration')} | "
            f"credit {fmt_money(plan.get('estimatedCredit'))} | max loss {fmt_money(plan.get('estimatedMaxLoss'))} | "
            f"credit/risk {fmt_num(plan.get('creditRisk'))} | "
            f"wings P {fmt_num(plan.get('shortPutStrike'))}/{fmt_num(plan.get('longPutStrike'))} "
            f"C {fmt_num(plan.get('shortCallStrike'))}/{fmt_num(plan.get('longCallStrike'))}"
        )
        lines.append(
            "  "
            f"long-vol baseline: {long_vol.get('strategy')} | hurdle {long_vol.get('premiumHurdleLabel') or 'n/a'} | "
            f"ATR multiple {fmt_num(long_vol.get('requiredMoveAtrMultiple'))} | "
            f"pressure {fmt_num(long_vol.get('rankPressureScore'))}"
        )
        blocks = put_credit.get("blockReasons") or []
        lines.append(
            "  "
            f"put-credit comparison: {'pass' if put_credit.get('combinedPassed') else 'block'} | "
            f"blocks: {'; '.join(blocks) if blocks else 'none'}"
        )
        grid_by_label = {row.get("label"): row for row in entry.get("expirationPayoffGrid") or []}
        checkpoints = []
        for label in ("support", "current", "resistance"):
            row = grid_by_label.get(label)
            if not row:
                continue
            payoffs = row.get("payoffs") or {}
            condor = payoffs.get("IRON_CONDOR") or {}
            put_credit_payoff = payoffs.get("PUT_CREDIT_SPREAD") or {}
            checkpoints.append(
                f"{label} {fmt_num(row.get('underlyingPrice'))}: "
                f"condor {fmt_money(condor.get('pnl'))} / put-credit {fmt_money(put_credit_payoff.get('pnl'))}"
            )
        if checkpoints:
            lines.append(f"  payoff checkpoints: {' | '.join(checkpoints)}")

    lines.extend(["", "Rules:"])
    for rule in payload.get("rules") or []:
        lines.append(f"- {rule}")
    return "\n".join(lines).rstrip() + "\n"


def save_strategy_shadow_comparison(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(STRATEGY_SHADOW_COMPARISON_FILE, payload)
    atomic_write_text(STRATEGY_SHADOW_COMPARISON_TEXT_FILE, render_strategy_shadow_comparison(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the strategy shadow comparison register.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and STRATEGY_SHADOW_COMPARISON_TEXT_FILE.exists():
        print(STRATEGY_SHADOW_COMPARISON_TEXT_FILE.read_text(encoding="utf-8"))
        latest = load_json_file(STRATEGY_SHADOW_COMPARISON_FILE) or {}
        return 0 if latest.get("verdict") in {"shadow-comparison-ready", "no-passing-alternatives"} else 1
    payload = build_strategy_shadow_comparison()
    save_strategy_shadow_comparison(payload)
    print(render_strategy_shadow_comparison(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
