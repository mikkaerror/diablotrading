from __future__ import annotations

"""Read-only Schwab option-chain adapter for the Inferno desk.

This module is intentionally narrow: it can normalize Schwab option-chain
payloads and, when locally configured, fetch market-data chains. It cannot read
accounts, build orders, preview orders, or submit trades. The first Schwab lane
is quote quality, strike selection, and evidence collection only.

Companion docs:
  * docs/SCHWAB_OPTIONS_API.md          — adapter plan, OAuth posture, fields.
  * docs/SCHWAB_EDGE_OPPORTUNITIES.md   — how the desk capitalizes on this
                                          data: four-tier edge framework,
                                          refresh cadence, anti-goals, and
                                          the Phase 2-4 build backlog.

Bridge module ``inferno_schwab_edge_signals.py`` converts the per-row chain
summary this adapter emits into operator-facing tier-classified signals.
"""

import argparse
import json
import ssl
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from inferno_config import (
    SCHWAB_API_BASE_URL,
    SCHWAB_OPTIONS_ENABLED,
    SCHWAB_OPTIONS_SYMBOL_LIMIT,
    SCHWAB_OPTIONS_STRIKE_COUNT,
    SCHWAB_OPTIONS_TIMEOUT_SECONDS,
    SCHWAB_TOKEN_FILE,
    local_now,
)
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


SCHWAB_OPTIONS_FILE = DATA_DIR / "inferno_schwab_options.json"
SCHWAB_OPTIONS_TEXT_FILE = REPORTS_DIR / "schwab_options_latest.txt"
SCHWAB_OPTIONS_STAGE = "schwab-options-read-only"
CHAIN_ENDPOINT = "/marketdata/v1/chains"
LIVE_MAX_SPREAD_PCT = 0.12
PAPER_MAX_SPREAD_PCT = 0.20
PAPER_MIN_WINDOW_OI = 250
HARD_WIDE_SPREAD_PCT = 0.25
DEFAULT_CHAIN_PARAMS = {"strikeCount": SCHWAB_OPTIONS_STRIKE_COUNT}


def https_context() -> ssl.SSLContext:
    """Return a certificate-validating HTTPS context for Schwab API calls."""
    try:
        import certifi  # type: ignore[import-not-found]

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def number(value: Any, default: float | None = None) -> float | None:
    """Coerce API values into floats without throwing on missing fields."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def int_number(value: Any, default: int = 0) -> int:
    """Coerce API values into ints for volume/open-interest fields."""
    parsed = number(value)
    return default if parsed is None else int(parsed)


def pct(value: float | None) -> float | None:
    """Round a decimal percentage for stable JSON/text reports."""
    if value is None:
        return None
    return round(value, 4)


def rounded(value: float | None, digits: int = 4) -> float | None:
    """Round optional floats while preserving missing API values."""
    if value is None:
        return None
    return round(value, digits)


def mean_number(values: list[float | int | None]) -> float | None:
    """Return the mean of present numeric values or ``None`` when empty."""
    present = [float(value) for value in values if value is not None]
    if not present:
        return None
    return round(sum(present) / len(present), 4)


def median_number(values: list[float | int | None]) -> float | None:
    """Return the median of present numeric values or ``None`` when empty."""
    present = sorted(float(value) for value in values if value is not None)
    if not present:
        return None
    midpoint = len(present) // 2
    if len(present) % 2:
        return round(present[midpoint], 4)
    return round((present[midpoint - 1] + present[midpoint]) / 2.0, 4)


def normalized_iv(value: float | None) -> float | None:
    """Normalize Schwab IV/volatility into decimal form.

    Schwab-style option payloads commonly express volatility as ``35.0`` for
    35%. Some fixtures/vendors may already use ``0.35``. Keeping one decimal
    convention avoids accidental 100x blowups in expected-move math.
    """
    if value is None:
        return None
    return round(value / 100.0, 6) if value > 3 else round(value, 6)


def liquidity_bucket(score: int | float | None) -> str:
    """Classify a contract or ATM pair into a trading-quality liquidity bucket."""
    value = number(score, 0) or 0
    if value >= 85:
        return "elite"
    if value >= 70:
        return "tradable"
    if value >= 50:
        return "watch"
    if value > 0:
        return "thin"
    return "missing"


def spread_quality(spread_pct: float | None) -> str:
    """Classify bid/ask spread friction in plain desk language."""
    if spread_pct is None:
        return "unknown"
    if spread_pct <= 0.05:
        return "tight"
    if spread_pct <= 0.10:
        return "acceptable"
    if spread_pct <= 0.20:
        return "workable"
    if spread_pct <= 0.35:
        return "wide"
    return "untradeable"


def expected_move_bucket(implied_move_pct: float | None) -> str:
    """Classify how aggressive the ATM straddle-implied move is."""
    if implied_move_pct is None:
        return "unknown"
    if implied_move_pct < 0.03:
        return "quiet"
    if implied_move_pct < 0.06:
        return "normal"
    if implied_move_pct < 0.10:
        return "hot"
    return "inferno"


def contract_has_greeks(contract: dict[str, Any]) -> bool:
    """Return whether a normalized contract has enough Greeks for analysis."""
    return all(contract.get(field) is not None for field in ("delta", "gamma", "theta", "vega"))


def contract_quality_flags(contract: dict[str, Any]) -> list[str]:
    """Return conservative per-contract warnings used by chain summaries."""
    flags: list[str] = []
    if not contract.get("mid"):
        flags.append("missing-mid")
    if contract.get("spreadPct") is None:
        flags.append("missing-spread")
    elif (contract.get("spreadPct") or 0) > 0.35:
        flags.append("wide-spread")
    if (contract.get("openInterest") or 0) <= 0 and (contract.get("volume") or 0) <= 0:
        flags.append("no-visible-interest")
    if not contract_has_greeks(contract):
        flags.append("missing-greeks")
    return flags


def load_schwab_access_token(token_file: Path | None = None) -> str | None:
    """Load a local Schwab access token from the ignored token vault.

    Expected token file shape is compatible with common OAuth helpers:
    ``{"access_token": "..."}``. The file lives outside git via
    ``SCHWAB_TOKEN_FILE`` / ``.secrets/``.
    """
    path = token_file or SCHWAB_TOKEN_FILE
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    token = str(payload.get("access_token") or "").strip()
    return token or None


def schwab_options_configured(token_file: Path | None = None) -> bool:
    """Return True only when the read-only Schwab data lane is explicitly on."""
    return SCHWAB_OPTIONS_ENABLED and bool(load_schwab_access_token(token_file))


def build_chain_url(symbol: str, params: dict[str, Any] | None = None) -> str:
    """Build the Schwab option-chain URL without performing a network call."""
    query = {
        "symbol": symbol.upper().strip(),
        "strategy": "SINGLE",
        "includeUnderlyingQuote": "true",
    }
    for key, value in (params or {}).items():
        if value is not None and value != "":
            query[key] = value
    return f"{SCHWAB_API_BASE_URL}{CHAIN_ENDPOINT}?{urlencode(query)}"


def fetch_option_chain(
    symbol: str,
    *,
    access_token: str,
    params: dict[str, Any] | None = None,
    timeout_seconds: float = SCHWAB_OPTIONS_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Fetch one Schwab option chain using a caller-supplied bearer token.

    This function reads market data only. Callers are responsible for obtaining
    and refreshing OAuth tokens outside this module.
    """
    request = Request(
        build_chain_url(symbol, params),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=timeout_seconds, context=https_context()) as response:  # noqa: S310 - configured Schwab HTTPS URL
        return json.loads(response.read().decode("utf-8"))


def flatten_contracts(chain: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten Schwab call/put expiration maps into one contract list."""
    contracts: list[dict[str, Any]] = []
    for map_name, side in (("callExpDateMap", "CALL"), ("putExpDateMap", "PUT")):
        exp_map = chain.get(map_name) or {}
        for exp_key, strike_map in exp_map.items():
            expiration = str(exp_key).split(":", 1)[0]
            dte_from_key = str(exp_key).split(":", 1)[1] if ":" in str(exp_key) else None
            for strike_key, rows in (strike_map or {}).items():
                for raw in rows or []:
                    enriched = dict(raw)
                    enriched.setdefault("putCall", side)
                    enriched.setdefault("expirationDate", expiration)
                    enriched.setdefault("daysToExpiration", dte_from_key)
                    enriched.setdefault("strikePrice", strike_key)
                    contracts.append(enriched)
    return contracts


def normalize_contract(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize one option contract into the fields the model needs."""
    bid = number(raw.get("bid"))
    ask = number(raw.get("ask"))
    mark = number(raw.get("mark"))
    last = number(raw.get("last"))
    mid = None
    if bid is not None and ask is not None and bid >= 0 and ask >= bid:
        mid = round((bid + ask) / 2, 4)
    elif mark is not None:
        mid = mark

    spread = None
    spread_pct = None
    if bid is not None and ask is not None and ask >= bid:
        spread = round(ask - bid, 4)
        # Wide option markets are dangerous; spread percent penalizes slippage.
        spread_pct = pct(spread / mid) if mid and mid > 0 else None

    open_interest = int_number(raw.get("openInterest"))
    volume = int_number(raw.get("totalVolume") if raw.get("totalVolume") is not None else raw.get("volume"))
    liquidity_score = liquidity_score_for_contract(spread_pct, open_interest, volume)

    return {
        "symbol": str(raw.get("symbol") or raw.get("optionSymbol") or "").strip(),
        "description": str(raw.get("description") or "").strip(),
        "putCall": str(raw.get("putCall") or "").upper(),
        "expirationDate": str(raw.get("expirationDate") or "").split("T", 1)[0],
        "daysToExpiration": int_number(raw.get("daysToExpiration")),
        "strikePrice": number(raw.get("strikePrice")),
        "bid": bid,
        "ask": ask,
        "mark": mark,
        "last": last,
        "mid": mid,
        "spread": spread,
        "spreadPct": spread_pct,
        "delta": number(raw.get("delta")),
        "gamma": number(raw.get("gamma")),
        "theta": number(raw.get("theta")),
        "vega": number(raw.get("vega")),
        "volatility": number(raw.get("volatility")),
        "openInterest": open_interest,
        "volume": volume,
        "inTheMoney": bool(raw.get("inTheMoney")),
        "intrinsicValue": number(raw.get("intrinsicValue")),
        "timeValue": number(raw.get("timeValue")),
        "theoreticalOptionValue": number(raw.get("theoreticalOptionValue")),
        "quoteTimeInLong": int_number(raw.get("quoteTimeInLong")) or None,
        "tradeTimeInLong": int_number(raw.get("tradeTimeInLong")) or None,
        "liquidityScore": liquidity_score,
    }


def liquidity_score_for_contract(spread_pct: float | None, open_interest: int, volume: int) -> int:
    """Score contract tradability from spread, open interest, and volume.

    The score is deliberately conservative and spread-primary. Volume is only a
    tiny confirmation bonus once spread and open interest are already usable; it
    must not rescue a wide-spread contract.
    """
    score = 0
    if spread_pct is not None:
        if spread_pct <= 0.05:
            score += 60
        elif spread_pct <= 0.10:
            score += 55
        elif spread_pct <= LIVE_MAX_SPREAD_PCT:
            score += 50
        elif spread_pct <= 0.20:
            score += 45
        elif spread_pct <= HARD_WIDE_SPREAD_PCT:
            score += 20
    if open_interest >= 1000:
        score += 40
    elif open_interest >= PAPER_MIN_WINDOW_OI:
        score += 30
    elif open_interest >= 50:
        score += 10
    if spread_pct is not None and spread_pct <= PAPER_MAX_SPREAD_PCT and open_interest >= PAPER_MIN_WINDOW_OI:
        if volume >= 500:
            score += 5
        elif volume >= 100:
            score += 3
    return min(100, score)


def nearest_atm_pair(contracts: list[dict[str, Any]], underlying_price: float | None) -> dict[str, Any] | None:
    """Return the nearest same-expiration ATM call/put pair."""
    if underlying_price is None:
        return None
    calls = [c for c in contracts if c.get("putCall") == "CALL" and c.get("mid")]
    puts = [c for c in contracts if c.get("putCall") == "PUT" and c.get("mid")]
    if not calls or not puts:
        return None

    expirations = sorted({c["expirationDate"] for c in calls if c.get("expirationDate")})
    for expiration in expirations:
        exp_calls = [c for c in calls if c.get("expirationDate") == expiration]
        exp_puts = [p for p in puts if p.get("expirationDate") == expiration]
        best_call = min(exp_calls, key=lambda c: abs((c.get("strikePrice") or 0) - underlying_price), default=None)
        if not best_call:
            continue
        best_put = min(
            exp_puts,
            key=lambda p: (
                abs((p.get("strikePrice") or 0) - (best_call.get("strikePrice") or underlying_price)),
                abs((p.get("strikePrice") or 0) - underlying_price),
            ),
            default=None,
        )
        if best_put:
            return {"call": best_call, "put": best_put}
    return None


def spread_primary_liquidity_score(spread_pct: float | None, open_interest: int) -> int:
    """Score ATM-window fillability with spread first and OI as confirmation."""
    if spread_pct is None:
        return 0
    if spread_pct <= 0.05:
        score = 80
    elif spread_pct <= 0.10:
        score = 75
    elif spread_pct <= LIVE_MAX_SPREAD_PCT:
        score = 70
    elif spread_pct <= PAPER_MAX_SPREAD_PCT:
        score = 55
    elif spread_pct <= HARD_WIDE_SPREAD_PCT:
        score = 35
    else:
        score = 5

    if open_interest >= 2000:
        score += 20
    elif open_interest >= 500:
        score += 15
    elif open_interest >= PAPER_MIN_WINDOW_OI:
        score += 10
    return min(100, score)


def spread_for_liquidity_gate(row: dict[str, Any]) -> float | None:
    """Return the robust spread used for paper/live liquidity gates."""
    spread = row.get("atmWindowMedianSpreadPct")
    if spread is None:
        spread = row.get("atmSpreadPct")
    return number(spread, None)


def liquidity_gate(
    row: dict[str, Any],
    *,
    max_spread_pct: float,
    min_window_oi: int = PAPER_MIN_WINDOW_OI,
) -> dict[str, Any]:
    """Evaluate a spread-primary liquidity gate for a Schwab chain summary."""
    spread = spread_for_liquidity_gate(row)
    window_oi = int_number(row.get("atmWindowOpenInterest"))
    if spread is None:
        return {
            "passed": False,
            "spreadPct": None,
            "windowOpenInterest": window_oi,
            "reason": "missing-atm-window-spread",
        }
    if spread > HARD_WIDE_SPREAD_PCT:
        return {
            "passed": False,
            "spreadPct": spread,
            "windowOpenInterest": window_oi,
            "reason": f"atm-window-spread {spread:.2%} exceeds hard-wide ceiling {HARD_WIDE_SPREAD_PCT:.0%}",
        }
    if spread > max_spread_pct:
        return {
            "passed": False,
            "spreadPct": spread,
            "windowOpenInterest": window_oi,
            "reason": f"atm-window-spread {spread:.2%} exceeds gate {max_spread_pct:.0%}",
        }
    if window_oi < min_window_oi:
        return {
            "passed": False,
            "spreadPct": spread,
            "windowOpenInterest": window_oi,
            "reason": f"atm-window-open-interest {window_oi} below floor {min_window_oi}",
        }
    return {
        "passed": True,
        "spreadPct": spread,
        "windowOpenInterest": window_oi,
        "reason": "spread-primary-liquidity-pass",
    }


def paper_liquidity_gate(row: dict[str, Any]) -> dict[str, Any]:
    """Return whether a chain is paper-admissible after spread/OI checks."""
    return liquidity_gate(row, max_spread_pct=PAPER_MAX_SPREAD_PCT)


def live_liquidity_gate(row: dict[str, Any]) -> dict[str, Any]:
    """Return whether a chain clears the tighter future live-liquidity check."""
    return liquidity_gate(row, max_spread_pct=LIVE_MAX_SPREAD_PCT)


def atm_window_metrics(
    contracts: list[dict[str, Any]],
    atm_pair: dict[str, Any] | None,
    underlying_price: float | None,
    *,
    window_per_side: int = 3,
) -> dict[str, Any]:
    """Summarize nearest ATM contracts so one odd strike cannot dominate."""
    if not atm_pair or underlying_price is None:
        return {
            "atmWindowMedianSpreadPct": None,
            "atmWindowOpenInterest": 0,
            "atmWindowVolume": 0,
            "atmWindowContractCount": 0,
        }

    expiration = (atm_pair.get("call") or {}).get("expirationDate")
    considered: list[dict[str, Any]] = []
    for side in ("CALL", "PUT"):
        side_contracts = [
            contract
            for contract in contracts
            if contract.get("putCall") == side
            and contract.get("expirationDate") == expiration
            and contract.get("mid")
        ]
        considered.extend(
            sorted(
                side_contracts,
                key=lambda contract: abs((contract.get("strikePrice") or 0) - underlying_price),
            )[:window_per_side]
        )

    spread = median_number([contract.get("spreadPct") for contract in considered])
    open_interest = sum(int(contract.get("openInterest") or 0) for contract in considered)
    volume = sum(int(contract.get("volume") or 0) for contract in considered)
    return {
        "atmWindowMedianSpreadPct": spread,
        "atmWindowOpenInterest": open_interest,
        "atmWindowVolume": volume,
        "atmWindowContractCount": len(considered),
    }


def contract_digest(contract: dict[str, Any]) -> dict[str, Any]:
    """Return a compact contract shape for ranking cards and reports."""
    return {
        "symbol": contract.get("symbol"),
        "putCall": contract.get("putCall"),
        "expirationDate": contract.get("expirationDate"),
        "daysToExpiration": contract.get("daysToExpiration"),
        "strikePrice": contract.get("strikePrice"),
        "mid": contract.get("mid"),
        "spreadPct": contract.get("spreadPct"),
        "liquidityScore": contract.get("liquidityScore"),
        "liquidityBucket": liquidity_bucket(contract.get("liquidityScore")),
        "delta": contract.get("delta"),
        "volatility": contract.get("volatility"),
        "openInterest": contract.get("openInterest"),
        "volume": contract.get("volume"),
        "qualityFlags": contract_quality_flags(contract),
    }


def top_liquid_contracts(contracts: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    """Rank the most usable contracts without flooding downstream artifacts.

    This intentionally favors liquidity first, then real activity. It is not a
    trade selector; it is a quote-quality shortlist for future strike logic.
    """
    ranked = sorted(
        contracts,
        key=lambda contract: (
            contract.get("liquidityScore") or 0,
            contract.get("volume") or 0,
            contract.get("openInterest") or 0,
            -(contract.get("spreadPct") or 9),
        ),
        reverse=True,
    )
    return [contract_digest(contract) for contract in ranked[:limit]]


def side_stats(contracts: list[dict[str, Any]], side: str) -> dict[str, Any]:
    """Summarize one side of the chain so call/put quality can diverge."""
    side_contracts = [contract for contract in contracts if contract.get("putCall") == side]
    liquid = [contract for contract in side_contracts if (contract.get("liquidityScore") or 0) >= 70]
    return {
        "count": len(side_contracts),
        "liquidCount": len(liquid),
        "avgSpreadPct": mean_number([contract.get("spreadPct") for contract in side_contracts]),
        "avgLiquidityScore": mean_number([contract.get("liquidityScore") for contract in side_contracts]),
        "avgImpliedVolatility": mean_number(
            [normalized_iv(contract.get("volatility")) for contract in side_contracts]
        ),
        "greeksCompletenessPct": pct(
            len([contract for contract in side_contracts if contract_has_greeks(contract)]) / len(side_contracts)
        )
        if side_contracts
        else None,
    }


def atm_metrics(
    atm_pair: dict[str, Any] | None,
    underlying_price: float | None,
    contracts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute the ATM straddle quality and expected-move fields.

    The ATM straddle is the cleanest first-pass proxy for what the option market
    is charging for an earnings move. We keep it descriptive here; strategy
    modules can later decide whether that premium is worth buying or selling.
    """
    if not atm_pair:
        return {
            "atmStrike": None,
            "atmExpiration": None,
            "atmStraddleMid": None,
            "atmExpectedMoveDollar": None,
            "atmImpliedMovePct": None,
            "atmExpectedMoveBucket": "unknown",
            "atmBreakEvenLower": None,
            "atmBreakEvenUpper": None,
            "atmSpreadPct": None,
            "atmSpreadQuality": "unknown",
            "atmLiquidityScore": None,
            "atmLiquidityBucket": "missing",
            "atmWindowMedianSpreadPct": None,
            "atmWindowOpenInterest": 0,
            "atmWindowVolume": 0,
            "atmWindowContractCount": 0,
            "atmLiquidityGateSpreadPct": None,
            "paperLiquidityPass": False,
            "paperLiquidityBlockReason": "missing-atm-window-spread",
            "liveLiquidityPass": False,
            "liveLiquidityBlockReason": "missing-atm-window-spread",
            "paperFillFrictionPct": None,
            "paperFillFrictionModel": "full-atm-window-spread-per-crossing",
            "paperLiquidityPolicy": {
                "spreadPrimary": True,
                "paperMaxSpreadPct": PAPER_MAX_SPREAD_PCT,
                "liveMaxSpreadPct": LIVE_MAX_SPREAD_PCT,
                "paperMinWindowOpenInterest": PAPER_MIN_WINDOW_OI,
                "hardWideSpreadPct": HARD_WIDE_SPREAD_PCT,
                "volumeCanRescueWideSpread": False,
            },
            "atmImpliedVolatility": None,
            "atmNetDelta": None,
            "atmNetTheta": None,
            "atmNetVega": None,
        }

    call = atm_pair["call"]
    put = atm_pair["put"]
    straddle_mid = round((call.get("mid") or 0) + (put.get("mid") or 0), 4)
    implied_move_pct = pct(straddle_mid / underlying_price) if underlying_price else None
    strike = call.get("strikePrice")
    window = atm_window_metrics(contracts or [], atm_pair, underlying_price)
    atm_spread_pct = window.get("atmWindowMedianSpreadPct") or mean_number([call.get("spreadPct"), put.get("spreadPct")])
    liquidity_score = spread_primary_liquidity_score(
        atm_spread_pct,
        int(window.get("atmWindowOpenInterest") or 0),
    )
    gate_row = {**window, "atmSpreadPct": atm_spread_pct}
    paper_gate = paper_liquidity_gate(gate_row)
    live_gate = live_liquidity_gate(gate_row)

    return {
        "atmStrike": strike,
        "atmExpiration": call.get("expirationDate"),
        "atmStraddleMid": straddle_mid,
        "atmExpectedMoveDollar": straddle_mid,
        "atmImpliedMovePct": implied_move_pct,
        "atmExpectedMoveBucket": expected_move_bucket(implied_move_pct),
        "atmBreakEvenLower": rounded((underlying_price - straddle_mid) if underlying_price else None),
        "atmBreakEvenUpper": rounded((underlying_price + straddle_mid) if underlying_price else None),
        "atmSpreadPct": atm_spread_pct,
        "atmSpreadQuality": spread_quality(atm_spread_pct),
        "atmLiquidityScore": liquidity_score,
        "atmLiquidityBucket": liquidity_bucket(liquidity_score),
        **window,
        "atmLiquidityGateSpreadPct": atm_spread_pct,
        "paperLiquidityPass": paper_gate["passed"],
        "paperLiquidityBlockReason": None if paper_gate["passed"] else paper_gate["reason"],
        "liveLiquidityPass": live_gate["passed"],
        "liveLiquidityBlockReason": None if live_gate["passed"] else live_gate["reason"],
        "paperFillFrictionPct": atm_spread_pct,
        "paperFillFrictionModel": "full-atm-window-spread-per-crossing",
        "paperLiquidityPolicy": {
            "spreadPrimary": True,
            "paperMaxSpreadPct": PAPER_MAX_SPREAD_PCT,
            "liveMaxSpreadPct": LIVE_MAX_SPREAD_PCT,
            "paperMinWindowOpenInterest": PAPER_MIN_WINDOW_OI,
            "hardWideSpreadPct": HARD_WIDE_SPREAD_PCT,
            "volumeCanRescueWideSpread": False,
        },
        "atmImpliedVolatility": mean_number(
            [normalized_iv(call.get("volatility")), normalized_iv(put.get("volatility"))]
        ),
        # Long straddles are roughly delta-neutral at entry; drift here warns us
        # when the "ATM" pair is not actually centered.
        "atmNetDelta": mean_number([call.get("delta"), put.get("delta")]),
        "atmNetTheta": mean_number([call.get("theta"), put.get("theta")]),
        "atmNetVega": mean_number([call.get("vega"), put.get("vega")]),
    }


def chain_quality_score(
    *,
    contract_count: int,
    liquid_count: int,
    atm_liquidity_score: int | None,
    atm_spread_pct: float | None,
    greeks_completeness_pct: float | None,
) -> int:
    """Score the chain's usefulness for the desk from 0 to 100.

    This is deliberately not a bullish/bearish score. It only asks whether the
    options market is clean enough to rely on for strike selection.
    """
    if contract_count <= 0:
        return 0

    liquid_ratio = liquid_count / contract_count
    depth_score = min(contract_count / 120.0, 1.0) * 15
    liquid_score = min(liquid_ratio, 1.0) * 25
    atm_score = ((atm_liquidity_score or 0) / 100.0) * 35
    greek_score = (greeks_completeness_pct or 0) * 10
    if atm_spread_pct is None:
        spread_score = 0
    else:
        # The spread score fades linearly to zero at 35% spread; beyond that,
        # slippage is too ugly for an options desk to trust.
        spread_score = max(0.0, 1.0 - min(atm_spread_pct, 0.35) / 0.35) * 15
    return int(round(depth_score + liquid_score + atm_score + greek_score + spread_score))


def quote_quality_label(score: int) -> str:
    """Convert a numeric chain-quality score into an operator label."""
    if score >= 85:
        return "institutional"
    if score >= 70:
        return "usable"
    if score >= 50:
        return "fragile"
    if score > 0:
        return "poor"
    return "unusable"


def chain_quality_flags(
    *,
    underlying_price: float | None,
    contract_count: int,
    liquid_count: int,
    atm: dict[str, Any],
    greeks_completeness_pct: float | None,
) -> list[str]:
    """Build fail-closed warnings for Schwab option-chain consumers."""
    flags: list[str] = []
    if underlying_price is None:
        flags.append("missing-underlying-price")
    if contract_count <= 0:
        flags.append("empty-chain")
    if liquid_count <= 0:
        flags.append("no-liquid-contracts")
    if not atm.get("atmStrike"):
        flags.append("missing-atm-pair")
    atm_spread = spread_for_liquidity_gate(atm)
    paper_gate = paper_liquidity_gate(atm)
    if atm_spread is not None and atm_spread > HARD_WIDE_SPREAD_PCT:
        flags.append("wide-atm-spread")
    if not paper_gate["passed"]:
        flags.append("thin-atm-liquidity")
    if greeks_completeness_pct is not None and greeks_completeness_pct < 0.80:
        flags.append("incomplete-greeks")
    return flags


def summarize_chain(symbol: str, chain: dict[str, Any]) -> dict[str, Any]:
    """Create the compact option-chain summary consumed by the desk."""
    underlying_price = number(
        chain.get("underlyingPrice")
        or (chain.get("underlying") or {}).get("last")
        or (chain.get("underlying") or {}).get("mark")
    )
    contracts = [normalize_contract(raw) for raw in flatten_contracts(chain)]
    atm_pair = nearest_atm_pair(contracts, underlying_price)
    liquid_contracts = [c for c in contracts if (c.get("liquidityScore") or 0) >= 70]
    liquid_ratio = pct(len(liquid_contracts) / len(contracts)) if contracts else None
    greek_complete = [contract for contract in contracts if contract_has_greeks(contract)]
    greeks_completeness_pct = pct(len(greek_complete) / len(contracts)) if contracts else None
    avg_spread_pct = mean_number([contract.get("spreadPct") for contract in contracts])
    liquid_avg_spread_pct = mean_number([contract.get("spreadPct") for contract in liquid_contracts])
    atm = atm_metrics(atm_pair, underlying_price, contracts)
    quality_score = chain_quality_score(
        contract_count=len(contracts),
        liquid_count=len(liquid_contracts),
        atm_liquidity_score=atm.get("atmLiquidityScore"),
        atm_spread_pct=atm.get("atmSpreadPct"),
        greeks_completeness_pct=greeks_completeness_pct,
    )
    quality_flags = chain_quality_flags(
        underlying_price=underlying_price,
        contract_count=len(contracts),
        liquid_count=len(liquid_contracts),
        atm=atm,
        greeks_completeness_pct=greeks_completeness_pct,
    )
    return {
        "symbol": symbol.upper().strip(),
        "status": "ok" if contracts else "empty-chain",
        "underlyingPrice": underlying_price,
        "contractCount": len(contracts),
        "liquidContractCount": len(liquid_contracts),
        "liquidContractRatio": liquid_ratio,
        "avgSpreadPct": avg_spread_pct,
        "liquidAvgSpreadPct": liquid_avg_spread_pct,
        "greeksCompletenessPct": greeks_completeness_pct,
        "quoteQualityScore": quality_score,
        "quoteQualityLabel": quote_quality_label(quality_score),
        "qualityFlags": quality_flags,
        "sideStats": {
            "CALL": side_stats(contracts, "CALL"),
            "PUT": side_stats(contracts, "PUT"),
        },
        "topLiquidContracts": top_liquid_contracts(contracts),
        **atm,
        "contracts": contracts,
    }


def build_report(
    symbols: list[str],
    *,
    token_file: Path | None = None,
    fixture_payloads: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a read-only Schwab option-chain report.

    ``fixture_payloads`` lets tests and offline research exercise the full
    normalizer without network or credentials.
    """
    ensure_dirs()
    clean_symbols = [s.upper().strip() for s in symbols if s.strip()]
    clean_symbols = list(dict.fromkeys(clean_symbols))[:SCHWAB_OPTIONS_SYMBOL_LIMIT]
    token = load_schwab_access_token(token_file)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    if not clean_symbols:
        status = "no-symbols"
    elif fixture_payloads is not None:
        status = "fixture"
    elif not SCHWAB_OPTIONS_ENABLED:
        status = "disabled"
    elif not token:
        status = "not-configured"
    else:
        status = "ok"

    for symbol in clean_symbols:
        try:
            if fixture_payloads is not None:
                payload = fixture_payloads[symbol]
            elif status == "ok" and token:
                payload = fetch_option_chain(symbol, access_token=token, params=DEFAULT_CHAIN_PARAMS)
            else:
                continue
            rows.append(summarize_chain(symbol, payload))
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})

    return {
        "generatedAt": local_now().isoformat(),
        "stage": SCHWAB_OPTIONS_STAGE,
        "researchOnly": True,
        "authorityChanged": False,
        "status": "partial-error" if errors and rows else ("error" if errors else status),
        "configured": bool(SCHWAB_OPTIONS_ENABLED and token),
        "symbolCount": len(clean_symbols),
        "rows": rows,
        "errors": errors,
        "reminders": [
            "market-data only; no account/order endpoints",
            "quotes support strike selection and risk checks, not live authority",
            "OAuth tokens must stay outside git",
        ],
    }


def render_report(report: dict[str, Any]) -> str:
    """Render a compact operator memo for the Schwab options lane."""
    lines = [
        "Inferno Schwab Options Adapter",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Stage: {report.get('stage')}",
        f"Status: {report.get('status')}",
        f"Configured: {report.get('configured')}",
        f"Symbols: {report.get('symbolCount')}",
        "",
    ]
    rows = report.get("rows") or []
    if rows:
        lines.append("Chain summaries:")
        for row in rows:
            move = row.get("atmImpliedMovePct")
            move_text = f"{round(move * 100, 2)}%" if isinstance(move, (int, float)) else "-"
            lines.append(
                f"- {row.get('symbol')}: contracts={row.get('contractCount')} "
                f"liquid={row.get('liquidContractCount')} ATM={row.get('atmStrike')} "
                f"exp={row.get('atmExpiration')} straddle={row.get('atmStraddleMid')} "
                f"move={move_text} liq={row.get('atmLiquidityScore')} "
                f"quality={row.get('quoteQualityScore')}/{row.get('quoteQualityLabel')} "
                f"spread={row.get('atmSpreadQuality')}"
            )
            if row.get("qualityFlags"):
                lines.append(f"  flags: {', '.join(row.get('qualityFlags') or [])}")
            top_contracts = row.get("topLiquidContracts") or []
            if top_contracts:
                preview = ", ".join(
                    f"{item.get('putCall')} {item.get('strikePrice')} "
                    f"L{item.get('liquidityScore')}"
                    for item in top_contracts[:3]
                )
                lines.append(f"  top contracts: {preview}")
    else:
        lines.append("No chain rows captured.")
    if report.get("errors"):
        lines.extend(["", "Errors:"])
        lines.extend(f"- {err.get('symbol')}: {err.get('error')}" for err in report["errors"])
    lines.extend(["", "Reminders:"])
    lines.extend(f"- {item}" for item in report.get("reminders") or [])
    return "\n".join(lines) + "\n"


def save_report(report: dict[str, Any]) -> None:
    """Persist JSON + text reports for command-center consumption."""
    ensure_dirs()
    atomic_write_json(SCHWAB_OPTIONS_FILE, report)
    atomic_write_text(SCHWAB_OPTIONS_TEXT_FILE, render_report(report))


def load_fixture(path: Path) -> dict[str, dict[str, Any]]:
    """Load either a single-chain fixture or a symbol-keyed fixture bundle."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "callExpDateMap" in payload or "putExpDateMap" in payload:
        symbol = str(payload.get("symbol") or payload.get("underlyingSymbol") or "FIXTURE").upper()
        return {symbol: payload}
    return {str(key).upper(): value for key, value in payload.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Schwab option-chain adapter.")
    parser.add_argument("symbols", nargs="*", help="Ticker symbols to fetch or normalize.")
    parser.add_argument("--fixture", type=Path, help="Normalize fixture JSON instead of calling Schwab.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    args = parser.parse_args()

    fixtures = load_fixture(args.fixture) if args.fixture else None
    symbols = args.symbols or (list(fixtures.keys()) if fixtures else [])
    report = build_report(symbols, fixture_payloads=fixtures)
    save_report(report)
    print(json.dumps(report, indent=2) if args.json else render_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
