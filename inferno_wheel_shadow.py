from __future__ import annotations

"""Capital-realistic wheel feasibility study with no staging authority."""

import argparse
from datetime import datetime
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


ACCOUNT_FILE = DATA_DIR / "inferno_schwab_account_sync.json"
OPTIONS_FILE = DATA_DIR / "inferno_schwab_options.json"
WHEEL_FILE = DATA_DIR / "inferno_wheel_shadow.json"
WHEEL_TEXT_FILE = REPORTS_DIR / "wheel_shadow_latest.txt"
STAGE = "wheel-shadow-research-only"
MIN_DTE = 30
MAX_DTE = 45
MIN_ABS_DELTA = 0.15
MAX_ABS_DELTA = 0.35
MIN_OPEN_INTEREST = 100
MAX_BID_ASK_SPREAD_PCT = 0.30
FRESH_OPTIONS_HOURS = 36.0


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _age_hours(value: Any) -> float | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    now = local_now()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    return max(0.0, (now - parsed.astimezone(now.tzinfo)).total_seconds() / 3600.0)


def _best_put(row: dict[str, Any], cash: float) -> dict[str, Any] | None:
    candidates = []
    for contract in row.get("contracts") or []:
        if str(contract.get("putCall") or "").upper() != "PUT":
            continue
        dte = int(_number(contract.get("daysToExpiration")))
        delta = abs(_number(contract.get("delta")))
        strike = _number(contract.get("strikePrice"))
        bid = _number(contract.get("bid"))
        ask = _number(contract.get("ask"))
        open_interest = _number(contract.get("openInterest"))
        mid = (bid + ask) / 2.0
        spread_pct = (ask - bid) / mid if mid > 0 else float("inf")
        if not (MIN_DTE <= dte <= MAX_DTE and MIN_ABS_DELTA <= delta <= MAX_ABS_DELTA):
            continue
        if (
            strike <= 0
            or bid <= 0
            or ask < bid
            or open_interest < MIN_OPEN_INTEREST
            or spread_pct > MAX_BID_ASK_SPREAD_PCT
        ):
            continue
        required_cash = strike * 100.0
        premium = bid * 100.0
        candidates.append(
            {
                "symbol": contract.get("symbol"),
                "expiration": contract.get("expirationDate"),
                "daysToExpiration": dte,
                "strike": strike,
                "delta": contract.get("delta"),
                "bid": bid,
                "ask": ask,
                "openInterest": contract.get("openInterest"),
                "volume": contract.get("volume"),
                "bidAskSpreadPct": round(spread_pct * 100.0, 2),
                "requiredCash": round(required_cash, 2),
                "cashFeasible": required_cash <= cash,
                "premiumAtBid": round(premium, 2),
                "premiumYieldOnCashPct": round(premium / required_cash * 100.0, 4),
                "breakeven": round(strike - bid, 4),
                "lossIfStockFalls25PctFromCurrent": round(
                    max(0.0, (strike - _number(row.get("underlyingPrice")) * 0.75 - bid) * 100.0),
                    2,
                ),
                "lossIfStockFalls50PctFromCurrent": round(
                    max(0.0, (strike - _number(row.get("underlyingPrice")) * 0.50 - bid) * 100.0),
                    2,
                ),
            }
        )
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            not item["cashFeasible"],
            abs(abs(_number(item["delta"])) - 0.25),
            -_number(item["openInterest"]),
        ),
    )[0]


def build_wheel_shadow(
    *,
    account: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    account = account if account is not None else (load_json_file(ACCOUNT_FILE) or {})
    options = options if options is not None else (load_json_file(OPTIONS_FILE) or {})
    cash = _number(account.get("totalCash"))
    options_age = _age_hours(options.get("generatedAt"))
    options_fresh = bool(
        options.get("status") == "ok"
        and options_age is not None
        and options_age <= FRESH_OPTIONS_HOURS
    )
    option_rows = {
        str(row.get("symbol") or "").upper(): row
        for row in options.get("rows") or []
    }
    rows = []
    for position in account.get("positions") or []:
        if str(position.get("assetType") or "EQUITY").upper() != "EQUITY":
            continue
        ticker = str(position.get("symbol") or "").upper()
        qty = _number(position.get("qty"))
        chain = option_rows.get(ticker)
        best_put = _best_put(chain, cash) if chain else None
        rows.append(
            {
                "ticker": ticker,
                "shares": qty,
                "coveredCallEligible": qty >= 100,
                "sharesMissingForCoveredCall": max(0, 100 - qty),
                "optionChainAvailable": chain is not None,
                "cashSecuredPutCandidate": best_put,
                "verdict": (
                    "stale-options-data"
                    if best_put and not options_fresh
                    else "shadow-candidate" if best_put and best_put["cashFeasible"]
                    else "capital-blocked"
                    if best_put
                    else "no-liquid-put-candidate"
                ),
            }
        )
    feasible = [row for row in rows if row["verdict"] == "shadow-candidate"]
    return {
        "generatedAt": local_now().isoformat(),
        "stage": STAGE,
        "verdict": (
            "stale-options-data"
            if not options_fresh
            else "shadow-candidates-found" if feasible
            else "no-capital-realistic-wheel"
        ),
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "paperStageAllowed": False,
        "cash": cash,
        "optionsDataAgeHours": round(options_age, 2) if options_age is not None else None,
        "optionsDataFresh": options_fresh,
        "filters": {
            "minDte": MIN_DTE,
            "maxDte": MAX_DTE,
            "absoluteDeltaRange": [MIN_ABS_DELTA, MAX_ABS_DELTA],
            "minimumOpenInterest": MIN_OPEN_INTEREST,
            "maximumBidAskSpreadPct": MAX_BID_ASK_SPREAD_PCT * 100.0,
        },
        "rows": rows,
        "reminders": [
            "Premium yield is not expected return and does not remove stock downside.",
            "Cash-secured puts require full assignment capital for 100 shares.",
            "Covered calls require 100 shares and cap upside if assigned.",
            "The wheel remains shadow-only while the equity sleeve is above target.",
        ],
    }


def render(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Wheel Feasibility Shadow",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Cash: ${payload.get('cash', 0):,.2f}",
        "",
    ]
    for row in payload.get("rows") or []:
        lines.append(
            f"- {row.get('ticker')} | shares {row.get('shares')} | "
            f"covered-call eligible {row.get('coveredCallEligible')} | {row.get('verdict')}"
        )
        candidate = row.get("cashSecuredPutCandidate")
        if candidate:
            lines.append(
                f"  put {candidate.get('strike')} exp {candidate.get('expiration')} | "
                f"cash ${candidate.get('requiredCash'):,.2f} | premium ${candidate.get('premiumAtBid'):,.2f} | "
                f"yield {candidate.get('premiumYieldOnCashPct')}% | "
                f"-25% stress ${candidate.get('lossIfStockFalls25PctFromCurrent'):,.2f}"
            )
    lines.extend(["", "Reminders:"])
    lines.extend(f"- {item}" for item in payload.get("reminders") or [])
    return "\n".join(lines).rstrip() + "\n"


def save(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(WHEEL_FILE, payload)
    atomic_write_text(WHEEL_TEXT_FILE, render(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Inferno wheel feasibility shadow.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    args = parser.parse_args()
    if args.command == "status" and WHEEL_TEXT_FILE.exists():
        print(WHEEL_TEXT_FILE.read_text(encoding="utf-8"), end="")
        return 0
    payload = build_wheel_shadow()
    save(payload)
    print(render(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
