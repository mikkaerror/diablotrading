from __future__ import annotations

"""Read-only Schwab account and position sync for the Inferno desk.

This module moves broker truth out of the fragile desktop-capture lane. It
reads Schwab account balances and positions, normalizes them into the same
shape the live-book review already understands, and writes local artifacts.

Safety contract:
- read-only account endpoints only
- no order, preview, replace, cancel, or submit endpoints
- no raw account numbers in saved artifacts
- no authority promotion
"""

import argparse
import json
import os
import ssl
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from inferno_config import TOS_ALLOWED_ACCOUNT_SUFFIXES, TOS_ALLOW_LIVE_READONLY, local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_schwab_oauth import ENV_FILE, load_config, parse_env_file, read_token_file, refresh_access_token, token_status
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


SCHWAB_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_schwab_account_sync.json"
SCHWAB_ACCOUNT_SYNC_TEXT_FILE = REPORTS_DIR / "schwab_account_sync_latest.txt"
SCHWAB_ACCOUNT_SYNC_STAGE = "schwab-account-sync-read-only"
ACCOUNT_NUMBERS_ENDPOINT = "/trader/v1/accounts/accountNumbers"
ACCOUNTS_ENDPOINT = "/trader/v1/accounts"
DEFAULT_TIMEOUT_SECONDS = 20.0


class SchwabAccountAPIError(RuntimeError):
    """Safe exception wrapper for Schwab account API failures."""

    def __init__(self, message: str, *, status_code: int | None = None, endpoint: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.endpoint = endpoint


def https_context() -> ssl.SSLContext:
    """Return a certificate-validating HTTPS context for Schwab API calls."""
    try:
        import certifi  # type: ignore[import-not-found]

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def load_schwab_env(path: Path = ENV_FILE) -> dict[str, str]:
    """Load `.env.schwab` into this process for scheduled runs."""
    values = parse_env_file(path)
    for key, value in values.items():
        os.environ[key] = value
    return values


def schwab_account_enabled() -> bool:
    """Return True when the read-only account lane should try the API."""
    default = os.environ.get("SCHWAB_OPTIONS_ENABLED", "0")
    return os.environ.get("SCHWAB_ACCOUNT_ENABLED", default).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def timeout_seconds() -> float:
    """Return the configured Schwab account API timeout."""
    try:
        return float(os.environ.get("SCHWAB_ACCOUNT_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def text(value: Any) -> str:
    """Normalize optional values into display-safe text."""
    return str(value or "").strip()


def number(value: Any, default: float | None = None) -> float | None:
    """Coerce loose broker values into floats."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    raw = text(value).replace("$", "").replace(",", "").replace("%", "")
    if not raw or raw in {"--", "N/A", "nan"}:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def rounded(value: Any, digits: int = 4) -> float | None:
    """Round optional numeric values while preserving missing data."""
    parsed = number(value)
    return None if parsed is None else round(parsed, digits)


def money_text(value: Any) -> str:
    """Render optional money values for the text report."""
    parsed = number(value)
    if parsed is None:
        return "-"
    return f"${parsed:,.2f}"


def digits_only(value: Any) -> str:
    """Return just the digits from a broker identifier."""
    return "".join(ch for ch in text(value) if ch.isdigit())


def account_suffix(value: Any, *, length: int = 4) -> str | None:
    """Return the trailing account suffix without storing the full number."""
    digits = digits_only(value)
    if not digits:
        return None
    return digits[-length:]


def redacted_account(value: Any) -> str | None:
    """Return a redacted account label suitable for local artifacts."""
    suffix = account_suffix(value)
    return f"***{suffix}" if suffix else None


def build_account_url(config: dict[str, Any], endpoint: str, params: dict[str, Any] | None = None) -> str:
    """Build a Schwab Trader API URL for a read-only account endpoint."""
    base = str(config.get("api_base_url") or "https://api.schwabapi.com").rstrip("/")
    query = urlencode({key: value for key, value in (params or {}).items() if value not in {None, ""}})
    return f"{base}{endpoint}" + (f"?{query}" if query else "")


def schwab_get(
    config: dict[str, Any],
    endpoint: str,
    *,
    access_token: str,
    params: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> Any:
    """GET a read-only Schwab account endpoint and parse JSON."""
    request = Request(
        build_account_url(config, endpoint, params),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout or timeout_seconds(), context=https_context()) as response:  # noqa: S310
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.reason or "HTTP error"
        raise SchwabAccountAPIError(
            f"Schwab account API returned HTTP {exc.code}: {detail}",
            status_code=exc.code,
            endpoint=endpoint,
        ) from exc
    except URLError as exc:
        raise SchwabAccountAPIError(
            f"Schwab account API network error: {exc.reason}",
            endpoint=endpoint,
        ) from exc
    except OSError as exc:
        raise SchwabAccountAPIError(
            f"Schwab account API connection error: {exc}",
            endpoint=endpoint,
        ) from exc

    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SchwabAccountAPIError(f"Schwab account API returned non-JSON data from {endpoint}") from exc


def refresh_token_if_possible(config: dict[str, Any], *, skip_refresh: bool) -> dict[str, Any]:
    """Refresh OAuth if possible and return safe token status."""
    status = token_status(config)
    if skip_refresh or not status.get("refreshTokenPresent"):
        return status
    try:
        refresh_access_token(config)
    except Exception as exc:  # noqa: BLE001 - caller can still try the current access token.
        updated = dict(status)
        updated["refreshAttempted"] = True
        updated["refreshOk"] = False
        updated["refreshError"] = str(exc)
        return updated
    updated = token_status(config)
    updated["refreshAttempted"] = True
    updated["refreshOk"] = True
    return updated


def load_access_token(config: dict[str, Any]) -> str | None:
    """Load the ignored Schwab access token without printing it."""
    payload = read_token_file(config["token_file"])
    token = text(payload.get("access_token"))
    return token or None


def fixture_payload(path: Path) -> tuple[Any, Any]:
    """Load a local fixture with optional accountNumbers/accounts sections."""
    if not path.exists():
        raise SystemExit(f"Fixture not found or invalid JSON: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"Fixture not found or invalid JSON: {path}") from exc
    if isinstance(payload, dict):
        return payload.get("accountNumbers"), payload.get("accounts", payload)
    return None, payload


def extract_account_number_map(payload: Any) -> dict[str, dict[str, Any]]:
    """Build a full-number keyed lookup from account-number payloads."""
    rows = payload if isinstance(payload, list) else []
    mapping: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        raw_number = text(item.get("accountNumber"))
        if not raw_number:
            continue
        mapping[raw_number] = {
            "suffix": account_suffix(raw_number),
            "redacted": redacted_account(raw_number),
            "hashPresent": bool(item.get("hashValue")),
        }
    return mapping


def account_records(payload: Any) -> list[dict[str, Any]]:
    """Extract Schwab securities-account records from common response shapes."""
    if isinstance(payload, dict) and isinstance(payload.get("accounts"), list):
        payload = payload.get("accounts")
    if isinstance(payload, dict) and isinstance(payload.get("securitiesAccount"), dict):
        return [payload["securitiesAccount"]]
    if isinstance(payload, dict) and any(key in payload for key in ("currentBalances", "positions", "accountNumber")):
        return [payload]
    if not isinstance(payload, list):
        return []
    records: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("securitiesAccount"), dict):
            records.append(item["securitiesAccount"])
        else:
            records.append(item)
    return records


def position_multiplier(raw: dict[str, Any]) -> int:
    """Return the price multiplier implied by the asset type."""
    instrument = raw.get("instrument") or {}
    asset_type = text(instrument.get("assetType") or raw.get("assetType")).upper()
    return 100 if asset_type == "OPTION" else 1


def signed_quantity(raw: dict[str, Any]) -> float | None:
    """Return a signed long-minus-short quantity from Schwab position fields."""
    long_qty = number(raw.get("longQuantity"), 0.0) or 0.0
    short_qty = number(raw.get("shortQuantity"), 0.0) or 0.0
    if long_qty or short_qty:
        qty = long_qty - short_qty
        return int(qty) if float(qty).is_integer() else round(qty, 4)
    qty = number(raw.get("quantity"))
    if qty is None:
        return None
    return int(qty) if float(qty).is_integer() else round(qty, 4)


def average_price(raw: dict[str, Any], qty: float | None) -> float | None:
    """Return a position average price from Schwab fields."""
    if qty is not None and qty < 0:
        return rounded(raw.get("averageShortPrice") or raw.get("averagePrice"))
    return rounded(raw.get("averageLongPrice") or raw.get("averagePrice"))


def mark_from_market_value(raw: dict[str, Any], qty: float | None, market_value: float | None) -> float | None:
    """Derive a per-unit mark when Schwab omits an explicit mark."""
    explicit = number(raw.get("mark") or raw.get("currentPrice") or raw.get("lastPrice"))
    if explicit is not None:
        return round(explicit, 4)
    if qty is None or qty == 0 or market_value is None:
        return None
    denominator = abs(qty) * position_multiplier(raw)
    if denominator <= 0:
        return None
    return round(abs(market_value) / denominator, 4)


def open_profit_loss(raw: dict[str, Any], qty: float | None, avg_price: float | None, market_value: float | None) -> float | None:
    """Return open P/L from Schwab if present, otherwise derive it."""
    for key in ("longOpenProfitLoss", "shortOpenProfitLoss", "openProfitLoss", "profitLoss"):
        parsed = number(raw.get(key))
        if parsed is not None:
            return round(parsed, 4)
    if qty is None or avg_price is None or market_value is None:
        return None
    cost = abs(qty) * avg_price * position_multiplier(raw)
    if cost <= 0:
        return None
    if qty >= 0:
        return round(market_value - cost, 4)
    return round(cost - abs(market_value), 4)


def profit_loss_percent(pl_open: float | None, qty: float | None, avg_price: float | None, raw: dict[str, Any]) -> float | None:
    """Return open P/L percent on original cost basis."""
    explicit = number(raw.get("profitLossPercentage") or raw.get("openProfitLossPercentage"))
    if explicit is not None:
        return round(explicit, 4)
    if pl_open is None or qty is None or avg_price is None:
        return None
    cost = abs(qty) * avg_price * position_multiplier(raw)
    if cost <= 0:
        return None
    return round((pl_open / cost) * 100, 4)


def normalize_position(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize one Schwab position into the live-sync position shape."""
    instrument = raw.get("instrument") or {}
    symbol = text(instrument.get("symbol") or raw.get("symbol")).upper()
    qty = signed_quantity(raw)
    market_value = number(raw.get("marketValue"))
    avg = average_price(raw, qty)
    mark = mark_from_market_value(raw, qty, market_value)
    pl_open = open_profit_loss(raw, qty, avg, market_value)
    pl_pct = profit_loss_percent(pl_open, qty, avg, raw)
    day_pl = number(raw.get("currentDayProfitLoss"))
    day_pl_pct = number(raw.get("currentDayProfitLossPercentage"))
    return {
        "symbol": symbol,
        "description": text(instrument.get("description") or raw.get("description") or symbol),
        "assetType": text(instrument.get("assetType") or raw.get("assetType")).upper(),
        "qty": qty,
        "mark": mark,
        "markValue": rounded(market_value, 2),
        "derivedTradePrice": avg,
        "plOpen": rounded(pl_open, 2),
        "plPercent": rounded(pl_pct, 4),
        "dayPl": rounded(day_pl, 2),
        "dayPlPercent": rounded(day_pl_pct, 4),
        "brokerSource": "schwab-account-api",
    }


def balance_value(account: dict[str, Any], *keys: str) -> float | None:
    """Read a balance value from current/projected/initial Schwab balances."""
    for group_name in ("currentBalances", "projectedBalances", "initialBalances"):
        group = account.get(group_name) or {}
        for key in keys:
            parsed = number(group.get(key))
            if parsed is not None:
                return parsed
    return None


def normalize_account(account: dict[str, Any], number_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Normalize one Schwab account without retaining raw account numbers."""
    raw_number = text(account.get("accountNumber"))
    mapped = number_map.get(raw_number, {})
    suffix = account_suffix(raw_number) or mapped.get("suffix")
    approved = bool(suffix and suffix in TOS_ALLOWED_ACCOUNT_SUFFIXES)
    positions = (
        [normalize_position(item) for item in account.get("positions") or [] if isinstance(item, dict)]
        if approved
        else []
    )
    net_liq = balance_value(account, "liquidationValue", "accountValue") if approved else None
    cash = balance_value(account, "cashBalance", "cashAvailableForTrading", "cashAvailableForWithdrawal") if approved else None
    return {
        "accountType": text(account.get("type")),
        "accountSuffix": suffix,
        "redactedAccount": redacted_account(raw_number) or mapped.get("redacted"),
        "hashPresent": bool(mapped.get("hashPresent") or account.get("hashValue")),
        "approved": approved,
        "netLiquidatingValue": rounded(net_liq, 2),
        "totalCash": rounded(cash, 2),
        "cashAvailableForTrading": rounded(balance_value(account, "cashAvailableForTrading"), 2) if approved else None,
        "buyingPower": rounded(balance_value(account, "buyingPower", "optionBuyingPower"), 2) if approved else None,
        "dayTradingBuyingPower": rounded(balance_value(account, "dayTradingBuyingPower"), 2) if approved else None,
        "isDayTrader": account.get("isDayTrader"),
        "isClosingOnlyRestricted": account.get("isClosingOnlyRestricted"),
        "positions": sorted(positions, key=lambda item: abs(number(item.get("markValue"), 0) or 0), reverse=True),
    }


def normalize_account_payload(account_numbers_payload: Any, accounts_payload: Any) -> dict[str, Any]:
    """Normalize Schwab account responses into a redacted desk artifact."""
    number_map = extract_account_number_map(account_numbers_payload)
    accounts = [normalize_account(account, number_map) for account in account_records(accounts_payload)]
    suffixes = sorted({text(account.get("accountSuffix")) for account in accounts if text(account.get("accountSuffix"))})
    approved_accounts = [account for account in accounts if account.get("approved")]
    positions = [
        position
        for account in approved_accounts
        for position in account.get("positions") or []
    ]
    net_liq_values = [number(account.get("netLiquidatingValue")) for account in approved_accounts]
    cash_values = [number(account.get("totalCash")) for account in approved_accounts]
    net_liq = sum(value for value in net_liq_values if value is not None) if approved_accounts else None
    total_cash = sum(value for value in cash_values if value is not None) if approved_accounts else None
    matched_suffixes = [text(account.get("accountSuffix")) for account in approved_accounts if text(account.get("accountSuffix"))]

    return {
        "accountMode": "live",
        "allowedLiveReadonly": TOS_ALLOW_LIVE_READONLY,
        "allowedSuffixes": list(TOS_ALLOWED_ACCOUNT_SUFFIXES),
        "matchedSuffix": matched_suffixes[0] if matched_suffixes else None,
        "matchedSuffixes": matched_suffixes,
        "accountSuffixCandidates": suffixes,
        "accountCount": len(accounts),
        "approvedAccountCount": len(approved_accounts),
        "accounts": accounts,
        "positions": positions,
        "netLiquidatingValue": rounded(net_liq, 2),
        "totalCash": rounded(total_cash, 2),
        "counts": {
            "accounts": len(accounts),
            "approvedAccounts": len(approved_accounts),
            "positions": len(positions),
            "rawPositions": sum(len(account.get("positions") or []) for account in approved_accounts),
        },
    }


def base_report() -> dict[str, Any]:
    """Return the shared safe report scaffold."""
    return {
        "generatedAt": local_now().isoformat(),
        "stage": SCHWAB_ACCOUNT_SYNC_STAGE,
        "ok": False,
        "verdict": "blocked",
        "message": "",
        "configured": False,
        "brokerReadOnly": True,
        "accountDataOnly": True,
        "orderEndpointsAllowed": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "authorityChanged": False,
        "accountMode": "live",
        "allowedLiveReadonly": TOS_ALLOW_LIVE_READONLY,
        "allowedSuffixes": list(TOS_ALLOWED_ACCOUNT_SUFFIXES),
        "matchedSuffix": None,
        "matchedSuffixes": [],
        "accountSuffixCandidates": [],
        "accounts": [],
        "positions": [],
        "counts": {"accounts": 0, "approvedAccounts": 0, "positions": 0, "rawPositions": 0},
        "netLiquidatingValue": None,
        "totalCash": None,
        "tokenStatus": {},
        "nextActions": [],
    }


def finish_normalized_report(report: dict[str, Any], normalized: dict[str, Any]) -> dict[str, Any]:
    """Merge normalized accounts into the report and derive verdict/actions."""
    report.update(normalized)
    if not TOS_ALLOW_LIVE_READONLY:
        report["message"] = "live read-only account access is not approved locally"
        report["nextActions"] = ["Set the local live-readonly approval flag only after confirming the account scope."]
        return report
    if not TOS_ALLOWED_ACCOUNT_SUFFIXES:
        report["message"] = "no approved account suffix is configured"
        report["nextActions"] = ["Configure the approved account suffix allowlist before trusting live account data."]
        return report
    if not normalized.get("approvedAccountCount"):
        report["message"] = "Schwab account payload did not contain an approved account suffix"
        report["nextActions"] = ["Confirm the Schwab app is linked to the intended account and update the suffix allowlist if needed."]
        return report

    report["ok"] = True
    report["verdict"] = "healthy"
    report["message"] = f"Schwab account data synced for approved suffix {normalized.get('matchedSuffix')}"
    if not normalized.get("positions"):
        report["nextActions"] = ["Approved Schwab account is synced and has no open positions."]
    else:
        report["nextActions"] = ["Use Schwab account sync as broker truth; use TOS for visualization/manual trading."]
    return report


def build_schwab_account_sync(
    *,
    account_numbers_payload: Any | None = None,
    accounts_payload: Any | None = None,
    fixture: Path | None = None,
    skip_refresh: bool = False,
) -> dict[str, Any]:
    """Build the read-only Schwab account sync artifact."""
    ensure_dirs()
    load_schwab_env()
    report = base_report()

    if fixture:
        account_numbers_payload, accounts_payload = fixture_payload(fixture)
        report["configured"] = True
        report["sourceStatus"] = "fixture"
        normalized = normalize_account_payload(account_numbers_payload, accounts_payload)
        return finish_normalized_report(report, normalized)

    if account_numbers_payload is not None or accounts_payload is not None:
        report["configured"] = True
        report["sourceStatus"] = "fixture"
        normalized = normalize_account_payload(account_numbers_payload, accounts_payload)
        return finish_normalized_report(report, normalized)

    config = load_config()
    status = refresh_token_if_possible(config, skip_refresh=skip_refresh)
    report["tokenStatus"] = status
    report["configured"] = bool(
        schwab_account_enabled()
        and status.get("envFileExists")
        and status.get("clientIdConfigured")
        and status.get("clientSecretConfigured")
        and status.get("tokenFileExists")
        and status.get("accessTokenPresent")
    )
    if not schwab_account_enabled():
        report["verdict"] = "disabled"
        report["message"] = "Schwab account sync is disabled"
        report["nextActions"] = ["Set SCHWAB_ACCOUNT_ENABLED=1 to enable read-only account sync."]
        return report
    if not status.get("accessTokenPresent"):
        report["verdict"] = "not-configured"
        report["message"] = "Schwab access token is missing"
        report["nextActions"] = ["Run the Schwab OAuth helper and consent to read-only account access."]
        return report

    token = load_access_token(config)
    if not token:
        report["verdict"] = "not-configured"
        report["message"] = "Schwab access token could not be loaded"
        report["nextActions"] = ["Refresh Schwab OAuth and retry account sync."]
        return report

    try:
        account_numbers_payload = schwab_get(config, ACCOUNT_NUMBERS_ENDPOINT, access_token=token)
        accounts_payload = schwab_get(config, ACCOUNTS_ENDPOINT, access_token=token, params={"fields": "positions"})
    except SchwabAccountAPIError as exc:
        status_code = exc.status_code
        verdict = "scope-missing" if status_code in {401, 403} else "fetch-failed"
        report["verdict"] = verdict
        report["message"] = str(exc)
        report["apiError"] = {
            "endpoint": exc.endpoint,
            "statusCode": status_code,
            "classification": verdict,
        }
        if verdict == "scope-missing":
            report["nextActions"] = ["Re-consent the Schwab OAuth app with account-read access, then rerun the account sync."]
        else:
            report["nextActions"] = ["Retry Schwab account sync; if it repeats, inspect OAuth token status and Schwab API availability."]
        return report

    report["sourceStatus"] = "ok"
    normalized = normalize_account_payload(account_numbers_payload, accounts_payload)
    return finish_normalized_report(report, normalized)


def render_schwab_account_sync(report: dict[str, Any]) -> str:
    """Render the Schwab account sync into an operator memo."""
    counts = report.get("counts") or {}
    lines = [
        "Inferno Schwab Account Sync",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Verdict: {report.get('verdict')}",
        f"Message: {report.get('message')}",
        f"Configured: {report.get('configured')}",
        f"Read-only: {report.get('brokerReadOnly')} | orders allowed: {report.get('orderEndpointsAllowed')}",
        f"Allowed live readonly: {report.get('allowedLiveReadonly')}",
        f"Matched suffix: {report.get('matchedSuffix') or '-'}",
        f"Visible suffixes: {', '.join(report.get('accountSuffixCandidates') or []) or '-'}",
        f"Accounts: {counts.get('approvedAccounts', 0)}/{counts.get('accounts', 0)} approved",
        f"Positions: {counts.get('positions', 0)}",
        f"Net liq: {money_text(report.get('netLiquidatingValue'))}",
        f"Total cash: {money_text(report.get('totalCash'))}",
        "",
        "Next actions:",
    ]
    for action in report.get("nextActions") or []:
        lines.append(f"- {action}")
    lines.extend(["", "Positions:"])
    for item in report.get("positions") or []:
        lines.append(
            "- "
            + f"{item.get('symbol')} qty={item.get('qty')} mark={money_text(item.get('mark'))} "
            + f"mv={money_text(item.get('markValue'))} avg={money_text(item.get('derivedTradePrice'))} "
            + f"openPL={money_text(item.get('plOpen'))} openPL%={item.get('plPercent') if item.get('plPercent') is not None else '-'}"
        )
    if not report.get("positions"):
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def save_schwab_account_sync(report: dict[str, Any]) -> None:
    """Persist Schwab account sync JSON + text artifacts."""
    ensure_dirs()
    atomic_write_json(SCHWAB_ACCOUNT_SYNC_FILE, report)
    atomic_write_text(SCHWAB_ACCOUNT_SYNC_TEXT_FILE, render_schwab_account_sync(report))


def parse_args() -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(description="Build the read-only Schwab account sync report.")
    parser.add_argument("command", nargs="?", choices=("build", "status"), default="build")
    parser.add_argument("--fixture", type=Path, help="Use a Schwab account fixture instead of the live API.")
    parser.add_argument("--skip-refresh", action="store_true", help="Skip OAuth refresh before account reads.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    parser.add_argument("--quiet", action="store_true", help="Persist artifacts without printing the report.")
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    if args.command == "status" and SCHWAB_ACCOUNT_SYNC_TEXT_FILE.exists():
        print(SCHWAB_ACCOUNT_SYNC_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = build_schwab_account_sync(fixture=args.fixture, skip_refresh=args.skip_refresh)
    save_schwab_account_sync(report)
    if not args.quiet:
        print(json.dumps(report, indent=2) if args.json else render_schwab_account_sync(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
