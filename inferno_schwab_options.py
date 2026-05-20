from __future__ import annotations

"""Read-only Schwab option-chain adapter for the Inferno desk.

This module is intentionally narrow: it can normalize Schwab option-chain
payloads and, when locally configured, fetch market-data chains. It cannot read
accounts, build orders, preview orders, or submit trades. The first Schwab lane
is quote quality, strike selection, and evidence collection only.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from inferno_config import (
    SCHWAB_API_BASE_URL,
    SCHWAB_OPTIONS_ENABLED,
    SCHWAB_OPTIONS_SYMBOL_LIMIT,
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
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - configured Schwab HTTPS URL
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
        "liquidityScore": liquidity_score,
    }


def liquidity_score_for_contract(spread_pct: float | None, open_interest: int, volume: int) -> int:
    """Score contract tradability from spread, open interest, and volume.

    The score is deliberately conservative. Tight spreads matter most because
    bad entry/exit fills can destroy an otherwise correct earnings thesis.
    """
    score = 0
    if spread_pct is not None:
        if spread_pct <= 0.05:
            score += 45
        elif spread_pct <= 0.10:
            score += 35
        elif spread_pct <= 0.20:
            score += 20
        else:
            score += 5
    if open_interest >= 1000:
        score += 35
    elif open_interest >= 250:
        score += 25
    elif open_interest >= 50:
        score += 12
    if volume >= 500:
        score += 20
    elif volume >= 100:
        score += 14
    elif volume >= 10:
        score += 6
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


def summarize_chain(symbol: str, chain: dict[str, Any]) -> dict[str, Any]:
    """Create the compact option-chain summary consumed by the desk."""
    underlying_price = number(
        chain.get("underlyingPrice")
        or (chain.get("underlying") or {}).get("last")
        or (chain.get("underlying") or {}).get("mark")
    )
    contracts = [normalize_contract(raw) for raw in flatten_contracts(chain)]
    atm_pair = nearest_atm_pair(contracts, underlying_price)

    straddle_mid = None
    implied_move_pct = None
    atm_strike = None
    atm_expiration = None
    atm_liquidity = None
    if atm_pair:
        call = atm_pair["call"]
        put = atm_pair["put"]
        straddle_mid = round((call.get("mid") or 0) + (put.get("mid") or 0), 4)
        atm_strike = call.get("strikePrice")
        atm_expiration = call.get("expirationDate")
        atm_liquidity = min(call.get("liquidityScore") or 0, put.get("liquidityScore") or 0)
        if underlying_price:
            # Earnings expected move proxy: ATM straddle mid divided by spot.
            implied_move_pct = pct(straddle_mid / underlying_price)

    liquid_contracts = [c for c in contracts if (c.get("liquidityScore") or 0) >= 70]
    return {
        "symbol": symbol.upper().strip(),
        "status": "ok" if contracts else "empty-chain",
        "underlyingPrice": underlying_price,
        "contractCount": len(contracts),
        "liquidContractCount": len(liquid_contracts),
        "atmExpiration": atm_expiration,
        "atmStrike": atm_strike,
        "atmStraddleMid": straddle_mid,
        "atmImpliedMovePct": implied_move_pct,
        "atmLiquidityScore": atm_liquidity,
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
                payload = fetch_option_chain(symbol, access_token=token)
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
                f"move={move_text} liq={row.get('atmLiquidityScore')}"
            )
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
