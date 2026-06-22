from __future__ import annotations

"""Read-only Schwab price-history adapter for Inferno.

The option-chain adapter tells the desk what contracts look like. This module
pulls daily OHLCV candles so broker data can also drive the user's TOS-style
custom metrics:

- RVOL
- percent of 52-week high
- 10-day moving-average momentum
- ATR percent
- latest-bar strength
- 10-day support/resistance state

Safety contract:
- market-data endpoint only
- no account, order, preview, cancel, replace, or staging calls
- writes only clearly labeled local artifacts
- OAuth tokens stay in the ignored Schwab token vault
"""

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_schwab_oauth import (
    DEFAULT_API_BASE_URL,
    ENV_FILE,
    https_context,
    load_config,
    parse_env_file,
    refresh_access_token,
    token_status,
)
from inferno_tos_formula_math import tos_custom_quote_snapshot_from_history
from server import DATA_DIR, REPORTS_DIR, SNAPSHOT_FILE, ensure_dirs, load_json_file


SCHWAB_PRICE_HISTORY_FILE = DATA_DIR / "inferno_schwab_price_history.json"
SCHWAB_PRICE_HISTORY_TEXT_FILE = REPORTS_DIR / "schwab_price_history_latest.txt"
SCHWAB_PRICE_HISTORY_STAGE = "schwab-price-history-read-only"
PRICE_HISTORY_ENDPOINT = "/marketdata/v1/pricehistory"
DEFAULT_SYMBOL_LIMIT = 12
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_PRICE_HISTORY_PARAMS: dict[str, Any] = {
    "periodType": "year",
    "period": 1,
    "frequencyType": "daily",
    "frequency": 1,
    "needExtendedHoursData": "false",
    "needPreviousClose": "false",
}

SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-/]{0,14}$")


def text(value: Any) -> str:
    """Normalize loose display values."""
    return str(value or "").strip()


def number(value: Any, default: float | None = None) -> float | None:
    """Coerce API values into floats without raising on blanks."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = text(value).replace(",", "").replace("$", "")
    if not cleaned or cleaned.upper() in {"N/A", "NAN", "NONE", "--"}:
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default


def rounded(value: Any, digits: int = 4) -> float | None:
    """Round a loose number while preserving missing values."""
    parsed = number(value)
    if parsed is None:
        return None
    return round(parsed, digits)


def env_bool(name: str, fallback: bool = False) -> bool:
    """Read a boolean-like environment variable."""
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_float(name: str, fallback: float) -> float:
    """Read a float environment variable."""
    try:
        return float(os.environ.get(name, str(fallback)))
    except ValueError:
        return fallback


def env_int(name: str, fallback: int) -> int:
    """Read an int environment variable."""
    try:
        return int(os.environ.get(name, str(fallback)))
    except ValueError:
        return fallback


def load_schwab_env(path: Path = ENV_FILE) -> dict[str, str]:
    """Load `.env.schwab` values into this process without executing shell."""
    values = parse_env_file(path)
    for key, value in values.items():
        os.environ[key] = value
    return values


def schwab_price_history_settings(env_path: Path = ENV_FILE) -> dict[str, Any]:
    """Return dynamic Schwab settings after loading the local env file."""
    load_schwab_env(env_path)
    config = load_config(env_path)
    options_enabled = env_bool("SCHWAB_OPTIONS_ENABLED", False)
    return {
        "apiBaseUrl": config.get("api_base_url") or DEFAULT_API_BASE_URL,
        "tokenFile": Path(config.get("token_file")),
        "enabled": env_bool("SCHWAB_PRICE_HISTORY_ENABLED", options_enabled),
        "timeoutSeconds": env_float(
            "SCHWAB_PRICE_HISTORY_TIMEOUT_SECONDS",
            env_float("SCHWAB_OPTIONS_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
        ),
        "symbolLimit": env_int(
            "SCHWAB_PRICE_HISTORY_SYMBOL_LIMIT",
            env_int("SCHWAB_OPTIONS_SYMBOL_LIMIT", DEFAULT_SYMBOL_LIMIT),
        ),
    }


def load_access_token(token_file: Path | None) -> str | None:
    """Load the ignored Schwab OAuth access token."""
    if token_file is None or not token_file.exists():
        return None
    try:
        payload = json.loads(token_file.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    token = text(payload.get("access_token"))
    return token or None


def refresh_access_token_if_possible(env_path: Path = ENV_FILE) -> dict[str, Any]:
    """Refresh the local access token when a refresh token is available."""
    load_schwab_env(env_path)
    try:
        config = load_config(env_path)
        status = token_status(config)
        if not status.get("refreshTokenPresent"):
            return {"attempted": False, "refreshed": False, "reason": "missing-refresh-token"}
        if status.get("reauthorizationRequired"):
            return {"attempted": False, "refreshed": False, "reason": "reauthorization-required"}
        if not status.get("accessTokenNeedsRefresh"):
            return {"attempted": False, "refreshed": False, "reason": "access-token-fresh"}
        refresh_access_token(config)
        return {"attempted": True, "refreshed": True, "reason": None}
    except Exception as exc:  # noqa: BLE001
        return {"attempted": True, "refreshed": False, "reason": f"{type(exc).__name__}: {exc}"}


def normalize_symbol(value: Any) -> str:
    """Normalize a ticker for Schwab market-data calls."""
    candidate = text(value).upper().lstrip("$")
    return candidate if SYMBOL_PATTERN.match(candidate) else ""


def unique_symbols(symbols: list[Any], *, limit: int | None = None) -> list[str]:
    """Return ordered, deduplicated symbols with an optional cap."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        symbol = normalize_symbol(raw)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
        if limit is not None and len(out) >= limit:
            break
    return out


def symbols_from_snapshot(path: Path = SNAPSHOT_FILE, *, limit: int | None = None) -> list[str]:
    """Extract a focused Schwab pull universe from the current tracker snapshot."""
    payload = load_json_file(path) or {}
    symbols: list[Any] = []
    for key in ("eligibleTickers", "reviewQueueTickers", "longTermTickers"):
        value = payload.get(key)
        if isinstance(value, list):
            symbols.extend(value)
    for key in ("rows", "longTermRows"):
        for row in payload.get(key) or []:
            if isinstance(row, dict):
                symbols.append(row.get("ticker") or row.get("symbol") or row.get("underlying"))
    return unique_symbols(symbols, limit=limit)


def build_price_history_url(
    symbol: str,
    params: dict[str, Any] | None = None,
    *,
    base_url: str | None = None,
) -> str:
    """Build a Schwab price-history URL without performing network IO."""
    query = dict(DEFAULT_PRICE_HISTORY_PARAMS)
    query["symbol"] = normalize_symbol(symbol)
    for key, value in (params or {}).items():
        if value is not None and value != "":
            query[key] = value
    resolved_base = (base_url or DEFAULT_API_BASE_URL).strip().rstrip("/")
    return f"{resolved_base}{PRICE_HISTORY_ENDPOINT}?{urlencode(query)}"


def fetch_price_history(
    symbol: str,
    *,
    access_token: str,
    params: dict[str, Any] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Fetch one Schwab price-history payload using a caller-supplied token."""
    request = Request(
        build_price_history_url(symbol, params, base_url=base_url),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=timeout_seconds, context=https_context()) as response:  # noqa: S310 - configured Schwab HTTPS URL
        return json.loads(response.read().decode("utf-8"))


def candle_timestamp(value: Any) -> pd.Timestamp | pd.NaT:
    """Normalize Schwab candle datetime values into UTC timestamps."""
    parsed = number(value)
    if parsed is not None:
        return pd.to_datetime(int(parsed), unit="ms", utc=True, errors="coerce")
    return pd.to_datetime(value, utc=True, errors="coerce")


def normalize_candles(payload: dict[str, Any]) -> pd.DataFrame:
    """Convert Schwab candles into the OHLCV frame used by formula mirrors."""
    rows: list[dict[str, Any]] = []
    for candle in payload.get("candles") or []:
        if not isinstance(candle, dict):
            continue
        row = {
            "Datetime": candle_timestamp(candle.get("datetime")),
            "Open": number(candle.get("open")),
            "High": number(candle.get("high")),
            "Low": number(candle.get("low")),
            "Close": number(candle.get("close")),
            "Volume": number(candle.get("volume")),
        }
        if all(row.get(column) is not None for column in ("Open", "High", "Low", "Close")):
            rows.append(row)
    if not rows:
        return pd.DataFrame(columns=["Datetime", "Open", "High", "Low", "Close", "Volume"])
    frame = pd.DataFrame(rows)
    frame = frame.sort_values("Datetime").reset_index(drop=True)
    return frame


def history_records(history: pd.DataFrame, *, limit: int = 260) -> list[dict[str, Any]]:
    """Serialize the tail of a history frame for audit artifacts."""
    if history.empty:
        return []
    records: list[dict[str, Any]] = []
    for row in history.tail(limit).to_dict(orient="records"):
        timestamp = row.get("Datetime")
        records.append(
            {
                "datetime": timestamp.isoformat() if hasattr(timestamp, "isoformat") and not pd.isna(timestamp) else None,
                "open": rounded(row.get("Open")),
                "high": rounded(row.get("High")),
                "low": rounded(row.get("Low")),
                "close": rounded(row.get("Close")),
                "volume": int(number(row.get("Volume"), 0) or 0),
            }
        )
    return records


def metric_missing_keys(mirror: dict[str, Any]) -> list[str]:
    """Return mirrored metric keys whose value could not be computed."""
    missing: list[str] = []
    for key, cell in mirror.items():
        if not isinstance(cell, dict) or key in {"source", "formulaStatus"}:
            continue
        if key == "tos_support_resistance_state":
            if cell.get("label") is None:
                missing.append(key)
        elif cell.get("value") is None:
            missing.append(key)
    return missing


def summarize_price_history(symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Summarize one Schwab price-history payload for downstream joins."""
    history = normalize_candles(payload)
    mirror = tos_custom_quote_snapshot_from_history(history) if not history.empty else {}
    latest = history.iloc[-1] if not history.empty else {}
    earliest = history.iloc[0] if not history.empty else {}
    latest_date = latest.get("Datetime") if isinstance(latest, pd.Series) else None
    earliest_date = earliest.get("Datetime") if isinstance(earliest, pd.Series) else None
    missing = metric_missing_keys(mirror)
    return {
        "symbol": normalize_symbol(symbol),
        "status": "ok" if not history.empty else "empty-history",
        "candleCount": int(len(history)),
        "earliestDate": earliest_date.isoformat() if hasattr(earliest_date, "isoformat") and not pd.isna(earliest_date) else None,
        "latestDate": latest_date.isoformat() if hasattr(latest_date, "isoformat") and not pd.isna(latest_date) else None,
        "latestClose": rounded(latest.get("Close") if isinstance(latest, pd.Series) else None, 4),
        "latestVolume": int(number(latest.get("Volume") if isinstance(latest, pd.Series) else None, 0) or 0),
        "tosCustomFormulaMirror": mirror,
        "missingFormulaValues": missing,
        "formulaReady": bool(mirror) and not missing,
        "candles": history_records(history),
    }


def build_report(
    symbols: list[str],
    *,
    token_file: Path | None = None,
    fixture_payloads: dict[str, dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    symbol_limit: int | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only Schwab price-history report."""
    ensure_dirs()
    resolved_settings = settings or schwab_price_history_settings()
    clean_symbols = unique_symbols(symbols, limit=symbol_limit if symbol_limit is not None else resolved_settings["symbolLimit"])
    token_path = token_file or resolved_settings.get("tokenFile")
    token = load_access_token(Path(token_path) if token_path else None)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    if not clean_symbols:
        status = "no-symbols"
    elif fixture_payloads is not None:
        status = "fixture"
    elif not resolved_settings.get("enabled"):
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
                payload = fetch_price_history(
                    symbol,
                    access_token=token,
                    params=params,
                    timeout_seconds=float(resolved_settings["timeoutSeconds"]),
                    base_url=str(resolved_settings["apiBaseUrl"]),
                )
            else:
                continue
            rows.append(summarize_price_history(symbol, payload))
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})

    return {
        "generatedAt": local_now().isoformat(),
        "stage": SCHWAB_PRICE_HISTORY_STAGE,
        "researchOnly": True,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "status": "partial-error" if errors and rows else ("error" if errors else status),
        "configured": bool(resolved_settings.get("enabled") and token),
        "endpoint": PRICE_HISTORY_ENDPOINT,
        "params": {**DEFAULT_PRICE_HISTORY_PARAMS, **(params or {})},
        "symbolCount": len(clean_symbols),
        "rows": rows,
        "errors": errors,
        "reminders": [
            "market-data only; no account/order endpoints",
            "daily candles can reproduce the visible OHLCV-derived TOS custom columns",
            "refresh before the desk cycle when these numbers will influence model context",
        ],
    }


def metric_preview(row: dict[str, Any]) -> str:
    """Render the six visible TOS metrics from a history row."""
    mirror = row.get("tosCustomFormulaMirror") or {}

    def cell_value(key: str, field: str = "value") -> Any:
        cell = mirror.get(key) if isinstance(mirror, dict) else None
        return cell.get(field) if isinstance(cell, dict) else None

    return (
        f"rvol={cell_value('tos_rvol')} "
        f"pv52h={cell_value('tos_pv52h')} "
        f"mom={cell_value('tos_momentum')} "
        f"atr%={cell_value('tos_atr_percent')} "
        f"str={cell_value('tos_strength')} "
        f"supres={cell_value('tos_support_resistance_state', 'label')}"
    )


def render_report(payload: dict[str, Any]) -> str:
    """Render a compact Schwab price-history memo."""
    lines = [
        "Inferno Schwab Price History",
        "=" * 29,
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Status: {payload.get('status')} | configured={payload.get('configured')}",
        f"Endpoint: {payload.get('endpoint')}",
        f"Symbols: {payload.get('symbolCount')}",
        "",
        "History rows",
    ]
    rows = payload.get("rows") or []
    if rows:
        for row in rows:
            lines.append(
                f"- {row.get('symbol')}: candles={row.get('candleCount')} "
                f"latest={row.get('latestDate')} close={row.get('latestClose')} "
                f"{metric_preview(row)}"
            )
            if row.get("missingFormulaValues"):
                lines.append(f"  missing formulas: {', '.join(row.get('missingFormulaValues') or [])}")
    else:
        lines.append("- No Schwab price-history rows captured.")
    if payload.get("errors"):
        lines.extend(["", "Errors"])
        lines.extend(f"- {item.get('symbol')}: {item.get('error')}" for item in payload.get("errors") or [])
    lines.extend(["", "Reminders"])
    lines.extend(f"- {item}" for item in payload.get("reminders") or [])
    return "\n".join(lines).rstrip() + "\n"


def save_report(payload: dict[str, Any]) -> None:
    """Persist Schwab price-history artifacts."""
    ensure_dirs()
    atomic_write_json(SCHWAB_PRICE_HISTORY_FILE, payload)
    atomic_write_text(SCHWAB_PRICE_HISTORY_TEXT_FILE, render_report(payload))


def load_fixture(path: Path) -> dict[str, dict[str, Any]]:
    """Load a single Schwab history fixture or a symbol-keyed fixture bundle."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "candles" in payload:
        symbol = normalize_symbol(payload.get("symbol") or "FIXTURE") or "FIXTURE"
        return {symbol: payload}
    return {normalize_symbol(key): value for key, value in payload.items() if normalize_symbol(key)}


def parse_args() -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(description="Read-only Schwab price-history adapter.")
    parser.add_argument("symbols", nargs="*", help="Ticker symbols. Defaults to the latest tracker snapshot.")
    parser.add_argument("--from-snapshot", action="store_true", help="Pull symbols from data/latest_snapshot.json")
    parser.add_argument("--limit", type=int, help="Symbol cap for this run")
    parser.add_argument("--fixture", type=Path, help="Normalize fixture JSON instead of calling Schwab")
    parser.add_argument("--skip-refresh", action="store_true", help="Skip OAuth refresh before live fetch")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    parser.add_argument("--quiet", action="store_true", help="Persist artifacts without printing")
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    fixtures = load_fixture(args.fixture) if args.fixture else None
    if fixtures and not args.symbols:
        symbols = list(fixtures.keys())
    elif args.from_snapshot or not args.symbols:
        symbols = symbols_from_snapshot(limit=args.limit)
    else:
        symbols = unique_symbols(args.symbols, limit=args.limit)

    refresh_status = None
    if fixtures is None and not args.skip_refresh:
        refresh_status = refresh_access_token_if_possible()
        if refresh_status.get("reason") == "reauthorization-required":
            if not args.quiet:
                print(
                    "Schwab reauthorization is required. Run "
                    "`python3 inferno_schwab_oauth.py restart` once."
                )
            return 1
    report = build_report(symbols, fixture_payloads=fixtures, symbol_limit=args.limit)
    if refresh_status is not None:
        report["refreshStatus"] = refresh_status
    save_report(report)
    if not args.quiet:
        print(json.dumps(report, indent=2) if args.json else render_report(report))
    return 0 if report.get("status") in {"ok", "fixture", "partial-error"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
