from __future__ import annotations

"""Research-only, common-risk comparison of tech equity and option arms."""

import argparse
from collections import defaultdict
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_paper_execution import paper_event_id
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


STAGE = "tech-cohort-evaluator-research-only"
OUTPUT_FILE = DATA_DIR / "inferno_tech_cohort_evaluator.json"
REPORT_FILE = REPORTS_DIR / "tech_cohort_evaluator_latest.txt"
PRICING_FILE = DATA_DIR / "inferno_strategy_alternative_pricing.json"
BASKET_FILE = DATA_DIR / "ai_basket_snapshot.json"
BASKET_CONTRACT_FILE = DATA_DIR / "inferno_ai_basket_data_contract.json"
SUPPORTED = {"CALL_DEBIT_SPREAD", "PUT_DEBIT_SPREAD"}
DEFAULT_RISK = 500.0
MOVE_GRID = (-0.10, -0.05, 0.0, 0.05, 0.10)


def number(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def norm(value: Any) -> str:
    return str(value or "").strip().upper()


def option_pnl(plan: dict[str, Any], terminal: float) -> float:
    strategy = norm(plan.get("strategy"))
    debit = number(plan.get("estimatedDebit"), 0.0) or 0.0
    legs = plan.get("legs") or []
    long_strikes = [number(x.get("strike")) for x in legs if norm(x.get("instruction")) == "BUY"]
    short_strikes = [number(x.get("strike")) for x in legs if norm(x.get("instruction")) == "SELL"]
    long_strikes = [x for x in long_strikes if x is not None]
    short_strikes = [x for x in short_strikes if x is not None]
    if not long_strikes or not short_strikes:
        return -debit * 100.0
    long_k, short_k = long_strikes[0], short_strikes[0]
    if strategy == "CALL_DEBIT_SPREAD":
        intrinsic = max(terminal - long_k, 0.0) - max(terminal - short_k, 0.0)
    else:
        intrinsic = max(long_k - terminal, 0.0) - max(short_k - terminal, 0.0)
    return round((intrinsic - debit) * 100.0, 2)


def trend_state(row: dict[str, Any]) -> str:
    price, avg50, avg200 = number(row.get("price")), number(row.get("priceAvg50")), number(row.get("priceAvg200"))
    if None in (price, avg50, avg200):
        return "unknown"
    if price > avg50 > avg200:
        return "leader-trend"
    if price > avg200:
        return "above-200-mixed"
    return "below-200-defensive"


def build_cohort(pricing: dict[str, Any], *, basket: Any = None, basket_contract: dict[str, Any] | None = None, risk_budget: float = DEFAULT_RISK) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in pricing.get("items") or []:
        if not isinstance(item, dict) or item.get("status") != "priced":
            continue
        strategy = norm((item.get("strikePlan") or {}).get("strategy") or item.get("recommendedStrategy"))
        if strategy in SUPPORTED:
            grouped[norm(item.get("ticker"))].append(item)

    basket_rows = basket if isinstance(basket, list) else (basket or {}).get("records") or [] if isinstance(basket, dict) else []
    basket_index = {norm(row.get("symbol")): row for row in basket_rows if isinstance(row, dict)}
    tickers = sorted(set(grouped) | set(basket_index))
    cohorts = []
    for ticker in tickers:
        items = grouped.get(ticker, [])
        first = items[0] if items else {}
        basket_row = basket_index.get(ticker, {})
        price = number(first.get("price") or first.get("sourcePrice") or (first.get("intent") or {}).get("price") or basket_row.get("price"))
        if not price or price <= 0:
            continue
        event_id = paper_event_id({"ticker": ticker, **(first.get("intent") or {})}) if items else None
        terminals = {f"{move:+.0%}": round(price * (1 + move), 4) for move in MOVE_GRID}
        share_qty = risk_budget / price
        arms = [{
            "arm": "SHARES",
            "comparisonIncluded": True,
            "gateEligible": None,
            "benchmarkOnly": True,
            "units": round(share_qty, 6),
            "capitalAtRisk": round(risk_budget, 2),
            "projectedPnl": {label: round((terminal - price) * share_qty, 2) for label, terminal in terminals.items()},
        }]
        seen: set[str] = set()
        for item in sorted(items, key=lambda x: (not bool(x.get("combinedPassed")), -(number(x.get("sourceAlternativeScore"), 0) or 0))):
            plan = item.get("strikePlan") or {}
            strategy = norm(plan.get("strategy") or item.get("recommendedStrategy"))
            if strategy in seen:
                continue
            seen.add(strategy)
            max_loss = number(plan.get("estimatedMaxLoss"))
            contracts = int(risk_budget // max_loss) if max_loss and max_loss > 0 else 0
            eligible = bool(item.get("combinedPassed")) and contracts >= 1
            arms.append({
                "arm": strategy,
                "comparisonIncluded": eligible,
                "gateEligible": eligible,
                "benchmarkOnly": False,
                "contracts": contracts if eligible else 0,
                "capitalAtRisk": round(max_loss * contracts, 2) if eligible else None,
                "expiration": plan.get("expiration"),
                "maxLossPerContract": max_loss,
                "exclusionReasons": ([] if item.get("combinedPassed") else (item.get("riskVerdict") or {}).get("blocks") or ["combined pricing/risk gate failed"]) + (["one contract exceeds common-risk budget"] if contracts < 1 else []),
                "projectedPnl": {label: round(option_pnl(plan, terminal) * contracts, 2) for label, terminal in terminals.items()} if eligible else {},
            })
        signals_trusted = bool((basket_contract or {}).get("signalsTrusted"))
        cohorts.append({"ticker": ticker, "category": basket_row.get("cat"), "trendState": trend_state(basket_row) if signals_trusted else "untrusted-source", "eventId": event_id, "entryPrice": price, "riskBudget": risk_budget, "terminalPrices": terminals, "arms": arms})

    option_eligible = sum(sum(1 for arm in row["arms"] if arm["arm"] != "SHARES" and arm["gateEligible"]) for row in cohorts)
    return {
        "generatedAt": local_now().isoformat(), "stage": STAGE, "researchOnly": True,
        "promotable": False, "authorityChanged": False, "brokerSubmitAllowed": False,
        "liveTradingAllowed": False, "sourceGeneratedAt": pricing.get("generatedAt"),
        "method": {"commonRiskBudget": risk_budget, "moveGrid": list(MOVE_GRID), "shareSizing": "fractional shares; full notional treated as maximum loss", "optionValuation": "expiration intrinsic value less entry debit"},
        "basketDataContract": {"generatedAt": (basket_contract or {}).get("generatedAt"), "verdict": (basket_contract or {}).get("verdict") or "missing", "signalsTrusted": bool((basket_contract or {}).get("signalsTrusted"))},
        "counts": {"distinctEvents": len({x["eventId"] for x in cohorts if x.get("eventId")}), "cohorts": len(cohorts), "basketNames": len(basket_index), "eligibleOptionArms": option_eligible},
        "cohorts": cohorts,
        "rules": ["One cohort per ticker earnings event.", "Excluded arms remain visible and cannot win the comparison.", "No ticket is staged, approved, closed, scored, promoted, or submitted."],
    }


def render(payload: dict[str, Any]) -> str:
    counts = payload["counts"]
    contract = payload.get("basketDataContract") or {}
    lines = ["Inferno Tech/Semiconductor Common-Risk Cohorts", "", f"Generated: {payload['generatedAt']}", f"Stage: {payload['stage']}", "Authority: research-only; broker submit OFF; live trading OFF", f"Basket signals trusted: {contract.get('signalsTrusted', False)} | contract {contract.get('verdict', 'missing')}", "", f"Cohorts / distinct events: {counts['cohorts']} / {counts['distinctEvents']}", f"Eligible option arms: {counts['eligibleOptionArms']}", f"Common maximum-loss budget: ${payload['method']['commonRiskBudget']:.2f}", "", "Cohorts:"]
    for row in payload["cohorts"]:
        eligible = [x["arm"] for x in row["arms"] if x.get("gateEligible")]
        event = row.get("eventId") or "no priced earnings overlay"
        overlay = ", ".join(eligible) if eligible else "none"
        lines.append(f"- {row['ticker']} | {row.get('category') or 'uncategorized'} | {row.get('trendState')} | {event} | share benchmark only | gate-eligible option overlay {overlay}")
    lines += ["", "Interpretation:", "- Compare arms only inside the same event row and terminal-price column.", "- Share rows are analytical benchmarks, not buy eligibility or portfolio-fit decisions.", "- Option arms must first clear construction and paper-risk gates.", "- This artifact creates observations only and never mutates a paper or broker ledger."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=("run", "status"), default="run")
    parser.add_argument("--risk-budget", type=float, default=DEFAULT_RISK)
    args = parser.parse_args()
    ensure_dirs()
    if args.command == "status":
        print(REPORT_FILE.read_text() if REPORT_FILE.exists() else "No cohort report yet.")
        return 0
    basket = load_json_file(BASKET_FILE) if BASKET_FILE.exists() else []
    contract = load_json_file(BASKET_CONTRACT_FILE) if BASKET_CONTRACT_FILE.exists() else {}
    payload = build_cohort(load_json_file(PRICING_FILE), basket=basket, basket_contract=contract, risk_budget=args.risk_budget)
    atomic_write_json(OUTPUT_FILE, payload)
    atomic_write_text(REPORT_FILE, render(payload))
    print(render(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
