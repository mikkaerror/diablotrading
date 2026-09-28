from __future__ import annotations

"""Read-only Schwab transaction ledger for cash-attribution evidence.

This adapter is deliberately narrower than account sync.  It makes GET requests
only, scopes them to the configured account suffixes, and persists a normalized
ledger that never contains account numbers, account hashes, OAuth tokens, or
raw transaction descriptions.  A transaction record can explain a cash
movement; it is not enough to calculate realized options P/L or grant any
trading authority.
"""

import argparse
import csv
import io
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from inferno_config import TOS_ALLOWED_ACCOUNT_SUFFIXES, TOS_ALLOW_LIVE_READONLY, local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_schwab_account_sync import (
    ACCOUNT_NUMBERS_ENDPOINT,
    SchwabAccountAPIError,
    account_suffix,
    load_access_token,
    load_schwab_env,
    schwab_get,
)
from inferno_schwab_oauth import load_config, token_status
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


SCHWAB_TRANSACTION_LEDGER_FILE = DATA_DIR / "inferno_schwab_transaction_ledger.json"
SCHWAB_TRANSACTION_LEDGER_TEXT_FILE = REPORTS_DIR / "schwab_transaction_ledger_latest.txt"
SCHWAB_TRANSACTION_CSV_FILE = DATA_DIR / "schwab_transactions.csv"
SCHWAB_TRANSACTION_LEDGER_STAGE = "schwab-transaction-ledger-read-only"
TRANSACTIONS_ENDPOINT_TEMPLATE = "/trader/v1/accounts/{account_hash}/transactions"
DEFAULT_LOOKBACK_DAYS = 90
MAX_LOOKBACK_DAYS = 365
DEFAULT_TIMEOUT_SECONDS = 20.0
CSV_FIELDS = (
    "account_suffix",
    "transaction_id",
    "occurred_at",
    "trade_date",
    "settlement_date",
    "transaction_type",
    "status",
    "net_amount",
    "symbol",
    "asset_type",
    "quantity",
    "price",
    "fee",
    "source",
)


def text(value: Any, default: str = "") -> str:
    """Return a compact, display-safe string."""
    if value is None:
        return default
    rendered = str(value).strip()
    return rendered or default


def number(value: Any, default: float | None = None) -> float | None:
    """Parse a broker number without pretending malformed values are zero."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else default
    raw = text(value).replace("$", "").replace(",", "")
    if not raw:
        return default
    try:
        parsed = float(raw)
        return parsed if math.isfinite(parsed) else default
    except ValueError:
        return default


def rounded(value: Any, digits: int = 4) -> float | None:
    """Round an optional number while preserving missing broker fields."""
    parsed = number(value)
    return round(parsed, digits) if parsed is not None else None


def truthy(value: Any) -> bool:
    """Interpret one conventional environment switch."""
    return text(value).lower() in {"1", "true", "yes", "on"}


def transaction_ledger_enabled() -> bool:
    """Return whether the read-only transaction lane is explicitly enabled."""
    fallback = os.environ.get("SCHWAB_ACCOUNT_ENABLED", os.environ.get("SCHWAB_OPTIONS_ENABLED", "0"))
    return truthy(os.environ.get("SCHWAB_TRANSACTIONS_ENABLED", fallback))


def timeout_seconds() -> float:
    """Return the bounded transaction-read timeout."""
    try:
        return max(1.0, float(os.environ.get("SCHWAB_TRANSACTIONS_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def configured_lookback_days(value: int | None = None) -> int:
    """Return a bounded query window to avoid unbounded historical reads."""
    if value is None:
        try:
            value = int(os.environ.get("SCHWAB_TRANSACTIONS_LOOKBACK_DAYS", DEFAULT_LOOKBACK_DAYS))
        except ValueError:
            value = DEFAULT_LOOKBACK_DAYS
    return min(MAX_LOOKBACK_DAYS, max(1, int(value)))


def iso_utc(value: datetime) -> str:
    """Render an API query timestamp in explicit UTC ISO-8601 form."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def transaction_window(now: datetime | None = None, *, lookback_days: int | None = None) -> dict[str, Any]:
    """Build a bounded, inclusive transaction query window."""
    current = now or local_now()
    days = configured_lookback_days(lookback_days)
    return {
        "lookbackDays": days,
        "startDate": iso_utc(current - timedelta(days=days)),
        "endDate": iso_utc(current),
    }


def approved_account_hashes(payload: Any) -> list[dict[str, str]]:
    """Extract in-memory account hashes for approved suffixes only.

    The hash is needed solely to make the subsequent GET request and is never
    placed into the normalized report, CSV, logs, or exception output.
    """
    rows = payload if isinstance(payload, list) else []
    approved: list[dict[str, str]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        suffix = account_suffix(item.get("accountNumber"))
        account_hash = text(item.get("hashValue"))
        if suffix and suffix in TOS_ALLOWED_ACCOUNT_SUFFIXES and account_hash:
            approved.append({"suffix": suffix, "hash": account_hash})
    return sorted(approved, key=lambda item: item["suffix"])


def transaction_rows(payload: Any) -> list[dict[str, Any]]:
    """Extract transaction objects from the supported Schwab response shapes."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("transactions", "items", "data"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [item for item in rows if isinstance(item, dict)]
    return []


def safe_api_error_message(exc: SchwabAccountAPIError, *, resource: str) -> str:
    """Render an API failure without exposing an account hash embedded in a path."""
    status_code = f"HTTP {exc.status_code}" if exc.status_code is not None else "request failure"
    return f"Schwab {resource} API {status_code}; no transaction data was accepted."


def normalize_transfer_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    """Retain every leg/fee using a field allowlist, without allocating cash."""
    instrument = item.get("instrument") if isinstance(item.get("instrument"), dict) else {}
    def first_value(*keys):
        return next((item[k] for k in keys if item.get(k) is not None), None)
    return {
        "sourceIndex": index,
        "symbol": text(instrument.get("symbol") or item.get("symbol")).upper() or None,
        "assetType": text(instrument.get("assetType") or item.get("assetType")).upper() or None,
        "underlyingSymbol": text(instrument.get("underlyingSymbol")).upper() or None,
        "putCall": text(instrument.get("putCall")).upper() or None,
        "expirationDate": text(instrument.get("expirationDate")) or None,
        "strikePrice": rounded(instrument.get("strikePrice")),
        "quantity": rounded(first_value("amount", "quantity")),
        "price": rounded(item.get("price")),
        "cost": rounded(item.get("cost"), 2),
        "fee": rounded(first_value("fee", "fees"), 2),
        "feeType": text(item.get("feeType")).upper() or None,
        "positionEffect": text(item.get("positionEffect")).upper() or None,
    }


def normalize_transaction(raw: dict[str, Any], *, account_suffix_value: str) -> dict[str, Any]:
    """Normalize one broker transaction without retaining sensitive payload fields."""
    transfers = [normalize_transfer_item(item, index) for index, item in enumerate(raw.get("transferItems") or [])
                 if isinstance(item, dict)]
    securities = [item for item in transfers if item.get("assetType") not in {None, "CURRENCY"}]
    item = securities[0] if len(securities) == 1 else transfers[0] if len(transfers) == 1 else {}
    transaction_id = text(raw.get("activityId") or raw.get("transactionId") or raw.get("id"))
    occurred_at = text(raw.get("time") or raw.get("transactionDate") or raw.get("date"))
    return {
        "accountSuffix": account_suffix_value,
        "transactionId": transaction_id or None,
        "occurredAt": occurred_at or None,
        "tradeDate": text(raw.get("tradeDate")) or None,
        "settlementDate": text(raw.get("settlementDate")) or None,
        "transactionType": text(raw.get("type") or raw.get("transactionType")).upper() or None,
        "status": text(raw.get("status")).upper() or None,
        "netAmount": rounded(raw.get("netAmount"), 2),
        "symbol": item.get("symbol"),
        "assetType": "MULTI_ASSET" if len(securities) > 1 else item.get("assetType"),
        "quantity": item.get("quantity"),
        "price": item.get("price"),
        "fee": item.get("fee"),
        "transferItems": transfers,
        "normalizationVersion": 2,
        "cashBasis": "one parent netAmount; transfer items never added to net cash",
        "descriptionPresent": bool(text(raw.get("description"))),
        "source": "schwab-transaction-api",
    }


def transaction_sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
    """Return a deterministic oldest-first key for redacted transaction rows."""
    return (text(row.get("occurredAt")), text(row.get("accountSuffix")), text(row.get("transactionId")))


def closed_contract_cash_reconciliation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconcile only balanced single-security transaction groups; never allocate fees.

    This is a bounded-window cash diagnostic, not tax-lot accounting or proof of
    account completeness. Multi-security parents require a separate allocation.
    """
    groups: dict[tuple, list[dict]] = {}
    excluded = 0
    ambiguous_contracts = set()
    for row in rows:
        items = row.get("transferItems") or []
        securities = [item for item in items if item.get("assetType") != "CURRENCY"]
        if len(securities) == 1 and securities[0].get("assetType") == "OPTION":
            leg = securities[0]
            key = (row.get("accountSuffix"), leg.get("symbol"))
            groups.setdefault(key, []).append(row)
        elif any(item.get("assetType") == "OPTION" for item in items):
            excluded += 1
            ambiguous_contracts.update((row.get("accountSuffix"), item.get("symbol")) for item in items if item.get("assetType") == "OPTION")
    matched, unresolved = [], []
    for (suffix, symbol), group in sorted(groups.items(), key=lambda entry: str(entry[0])):
        balance, gross, net, ids = 0.0, 0.0, 0.0, []
        problem = "multi-security-parent-needs-allocation" if (suffix, symbol) in ambiguous_contracts else None
        def chronological(row):
            try:
                parsed = datetime.fromisoformat(row.get("occurredAt") or "")
                return parsed.timestamp() if parsed.tzinfo else float("-inf")
            except ValueError:
                return float("-inf")
        for row in sorted(group, key=chronological):
            if problem:
                break
            items = row["transferItems"]
            leg = next(item for item in items if item.get("assetType") == "OPTION")
            qty, cash = number(leg.get("quantity")), number(row.get("netAmount"))
            costs = [number(item.get("cost")) for item in items]
            try:
                observed = datetime.fromisoformat(row.get("occurredAt") or "")
                time_ok = observed.tzinfo is not None
            except ValueError:
                time_ok = False
            if not symbol or not row.get("transactionId") or row["transactionId"] in ids or not time_ok or row.get("status") != "VALID" or row.get("transactionType") != "TRADE":
                problem = "missing-or-ambiguous-transaction-identity-status-time"; break
            if qty is None or qty == 0 or cash is None or any(cost is None for cost in costs):
                problem = "missing-quantity-or-source-cost"; break
            if any(item.get("assetType") == "CURRENCY" and not item.get("feeType") for item in items):
                problem = "unallocated-currency-item"; break
            if abs(sum(costs) - cash) > .011:
                problem = "transfer-costs-do-not-reconcile-to-parent-cash"; break
            effect = leg.get("positionEffect")
            if effect == "OPENING" and balance * qty >= 0:
                balance += qty
            elif effect == "CLOSING" and balance * qty < 0 and abs(qty) <= abs(balance) + 1e-8:
                balance += qty
            else:
                problem = "unmatched-close-or-conflicting-position-effect"; break
            gross += leg["cost"]; net += cash; ids.append(row["transactionId"])
        if not problem and abs(balance) > 1e-8:
            problem = "open-quantity-remains-in-window"
        identity = {"accountSuffix": suffix, "symbol": symbol}
        if problem:
            unresolved.append({**identity, "reason": problem})
        else:
            matched.append({**identity, "transactionIds": ids, "grossCash": round(gross, 2),
                            "reportedCosts": round(gross - net, 2), "netCash": round(net, 2)})
    return {"matchedContractGroups": matched, "unresolvedContractGroups": unresolved,
            "excludedMultiSecurityTransactions": excluded,
            "matchedNetCash": round(sum(item["netCash"] for item in matched), 2) if matched else None,
            "accountProfitKnown": False, "sweepEligible": False,
            "basis": "balanced opening/closing quantities and broker transfer costs reconciled to each parent; not independent trade count, tax lots or complete account profit"}


def summarize_transactions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize transaction facts without calculating realized performance."""
    types: dict[str, int] = {}
    statuses: dict[str, int] = {}
    rows_with_net_amount = 0
    net_amount = 0.0
    option_rows = 0
    for row in rows:
        transaction_type = text(row.get("transactionType"), "UNKNOWN")
        status = text(row.get("status"), "UNKNOWN")
        types[transaction_type] = types.get(transaction_type, 0) + 1
        statuses[status] = statuses.get(status, 0) + 1
        amount = number(row.get("netAmount"))
        if amount is not None:
            rows_with_net_amount += 1
            net_amount += amount
        if text(row.get("assetType")).upper() == "OPTION" or any(
                item.get("assetType") == "OPTION" for item in row.get("transferItems") or []):
            option_rows += 1
    option_legs = [item for row in rows for item in row.get("transferItems") or [] if item.get("assetType") == "OPTION"]
    return {
        "transactionCount": len(rows),
        "rowsWithNetAmount": rows_with_net_amount,
        "netAmountAcrossWindow": round(net_amount, 2) if rows_with_net_amount else None,
        "optionTransactionCount": option_rows,
        "optionLegCount": len(option_legs),
        "closedContractCashReconciliation": closed_contract_cash_reconciliation(rows),
        "optionLegsMissingPositionEffect": sum(not item.get("positionEffect") for item in option_legs),
        "optionLegsMissingQuantityOrPrice": sum(item.get("quantity") is None or item.get("price") is None for item in option_legs),
        "rowsWithoutTransferProvenance": sum("transferItems" not in row for row in rows),
        "transactionTypes": dict(sorted(types.items())),
        "statuses": dict(sorted(statuses.items())),
        "realizedOptionsProfitKnown": False,
        "neverInferRealizedOptionsProfitFromNetCash": True,
    }


def base_report(now: datetime | None = None, *, lookback_days: int | None = None) -> dict[str, Any]:
    """Return the fail-closed shared transaction-ledger scaffold."""
    window = transaction_window(now, lookback_days=lookback_days)
    return {
        "generatedAt": (now or local_now()).isoformat(),
        "stage": SCHWAB_TRANSACTION_LEDGER_STAGE,
        "ok": False,
        "verdict": "blocked",
        "message": "",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerReadOnly": True,
        "accountDataOnly": True,
        "orderEndpointsAllowed": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "configured": False,
        "sourceStatus": "unavailable",
        "allowedLiveReadonly": TOS_ALLOW_LIVE_READONLY,
        "allowedSuffixes": list(TOS_ALLOWED_ACCOUNT_SUFFIXES),
        "matchedSuffixes": [],
        "window": window,
        "transactionSummary": summarize_transactions([]),
        "transactions": [],
        "tokenStatus": {},
        "nextActions": [],
        "citations": [
            "Schwab Trader API read-only transaction endpoint",
            "data/schwab_transactions.csv",
        ],
    }


def finish_report(
    report: dict[str, Any],
    *,
    rows_by_suffix: list[tuple[str, Any]],
    source_status: str,
) -> dict[str, Any]:
    """Populate an artifact from already-fetched or fixture transaction data."""
    normalized: list[dict[str, Any]] = []
    matched_suffixes: list[str] = []
    for suffix, payload in rows_by_suffix:
        matched_suffixes.append(suffix)
        normalized.extend(normalize_transaction(row, account_suffix_value=suffix) for row in transaction_rows(payload))
    # An API duplicate must not count cash twice. Conflicting versions require review.
    unique, seen, duplicates, conflicts = [], {}, 0, []
    for row in normalized:
        key = (row["accountSuffix"], row["transactionId"])
        if not key[1]:
            unique.append(row)
        elif key not in seen:
            seen[key] = row
            unique.append(row)
        elif seen[key] == row:
            duplicates += 1
        else:
            conflicts.append({"accountSuffix": key[0], "transactionId": key[1]})
    report["duplicateTransactionsSuppressed"] = duplicates
    report["conflictingTransactionIds"] = conflicts
    if conflicts:
        report.update(verdict="conflicting-transactions", message="Conflicting records share a broker transaction ID; prior ledger retained.")
        return report
    normalized = unique
    report["matchedSuffixes"] = sorted(set(matched_suffixes))
    report["transactions"] = sorted(normalized, key=transaction_sort_key)
    report["transactionSummary"] = summarize_transactions(report["transactions"])
    report["sourceStatus"] = source_status
    report["ok"] = True
    report["verdict"] = "healthy" if normalized else "healthy-no-transactions"
    report["message"] = (
        "Read-only Schwab transactions are normalized for cash reconciliation; realized options P/L remains unknown."
        if normalized
        else "Read-only Schwab transaction query completed with no rows in the bounded window."
    )
    report["nextActions"] = [
        "Use matched broker transaction net amounts only to reconcile cash movements; do not infer realized options P/L.",
        "If a cash movement cannot be matched to this ledger, keep it unattributed and review the broker statement.",
    ]
    return report


def fixture_payload(path: Path) -> tuple[Any, dict[str, Any]]:
    """Load a local fixture without widening the live API surface."""
    if not path.exists():
        raise SystemExit(f"Fixture not found or invalid JSON: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"Fixture not found or invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Fixture not found or invalid JSON: {path}")
    account_numbers = payload.get("accountNumbers")
    transactions = payload.get("transactionsByAccount") or payload.get("transactionsByHash") or {}
    return account_numbers, transactions if isinstance(transactions, dict) else {}


def build_schwab_transaction_ledger(
    *,
    account_numbers_payload: Any | None = None,
    transactions_by_hash: dict[str, Any] | None = None,
    fixture: Path | None = None,
    skip_refresh: bool = True,
    now: datetime | None = None,
    lookback_days: int | None = None,
) -> dict[str, Any]:
    """Build the transaction ledger using fixtures or approved read-only GETs.

    `skip_refresh=True` is the safe default.  Scheduled wrappers own OAuth
    refresh once, then invoke this adapter with the fresh access token.  A
    standalone invocation with an expiring token records that absence rather
    than silently mutating OAuth state.
    """
    ensure_dirs()
    load_schwab_env()
    report = base_report(now, lookback_days=lookback_days)

    if fixture:
        account_numbers_payload, transactions_by_hash = fixture_payload(fixture)
    if account_numbers_payload is not None or transactions_by_hash is not None:
        accounts = approved_account_hashes(account_numbers_payload)
        if not accounts:
            report["verdict"] = "blocked"
            report["sourceStatus"] = "fixture"
            report["message"] = "No configured approved account suffix was present in the transaction fixture."
            report["nextActions"] = ["Provide a fixture with an approved account suffix; unapproved accounts are never queried or persisted."]
            return report
        by_hash = transactions_by_hash or {}
        return finish_report(
            report,
            rows_by_suffix=[(item["suffix"], by_hash.get(item["hash"], [])) for item in accounts],
            source_status="fixture",
        )

    config = load_config()
    status = token_status(config)
    report["tokenStatus"] = status
    report["configured"] = bool(
        transaction_ledger_enabled()
        and status.get("envFileExists")
        and status.get("clientIdConfigured")
        and status.get("clientSecretConfigured")
        and status.get("tokenFileExists")
        and status.get("accessTokenPresent")
    )
    if not transaction_ledger_enabled():
        report["verdict"] = "disabled"
        report["message"] = "Schwab transaction ledger is disabled."
        report["nextActions"] = ["Set SCHWAB_TRANSACTIONS_ENABLED=1 to allow the read-only transaction fetch."]
        return report
    if not TOS_ALLOW_LIVE_READONLY:
        report["verdict"] = "disabled"
        report["message"] = "Live broker reads are disabled by desk policy."
        report["nextActions"] = ["Keep the transaction ledger disabled until the operator enables the existing read-only broker lane."]
        return report
    if not status.get("accessTokenPresent"):
        report["verdict"] = "not-configured"
        report["message"] = "Schwab access token is missing."
        report["nextActions"] = ["Refresh Schwab OAuth, then run the transaction ledger again."]
        return report
    if status.get("reauthorizationRequired"):
        report["verdict"] = "reauthorization-required"
        report["message"] = "Schwab rejected the stored refresh token."
        report["nextActions"] = ["Run `python3 inferno_schwab_oauth.py restart` once, then rerun the transaction ledger."]
        return report
    if status.get("accessTokenNeedsRefresh"):
        report["verdict"] = "access-token-refresh-needed"
        report["message"] = "The saved Schwab access token needs refresh; no account request was made."
        report["nextActions"] = ["Run the OAuth preflight, then rerun the transaction ledger with --skip-refresh."]
        return report

    token = load_access_token(config)
    if not token:
        report["verdict"] = "not-configured"
        report["message"] = "Schwab access token could not be loaded."
        report["nextActions"] = ["Refresh Schwab OAuth and retry the read-only transaction ledger."]
        return report

    try:
        account_numbers = schwab_get(
            config,
            ACCOUNT_NUMBERS_ENDPOINT,
            access_token=token,
            timeout=timeout_seconds(),
        )
    except SchwabAccountAPIError as exc:
        status_code = exc.status_code
        report["verdict"] = "scope-missing" if status_code in {401, 403} else "fetch-failed"
        report["message"] = safe_api_error_message(exc, resource="account-number")
        report["nextActions"] = ["Verify read-only Schwab account scope, then retry the transaction ledger."]
        return report

    accounts = approved_account_hashes(account_numbers)
    if not accounts:
        report["verdict"] = "blocked"
        report["message"] = "No configured approved account suffix was returned by Schwab."
        report["nextActions"] = ["Verify the configured approved account suffix before reading transactions."]
        return report

    rows_by_suffix: list[tuple[str, Any]] = []
    for item in accounts:
        endpoint = TRANSACTIONS_ENDPOINT_TEMPLATE.format(account_hash=item["hash"])
        try:
            payload = schwab_get(
                config,
                endpoint,
                access_token=token,
                params={"startDate": report["window"]["startDate"], "endDate": report["window"]["endDate"]},
                timeout=timeout_seconds(),
            )
        except SchwabAccountAPIError as exc:
            status_code = exc.status_code
            report["verdict"] = "scope-missing" if status_code in {401, 403} else "fetch-failed"
            report["message"] = safe_api_error_message(exc, resource="transaction")
            report["nextActions"] = ["Retry the transaction ledger; retain the prior CSV until a complete read succeeds."]
            return report
        rows_by_suffix.append((item["suffix"], payload))
    return finish_report(report, rows_by_suffix=rows_by_suffix, source_status="api")


def csv_row(transaction: dict[str, Any]) -> dict[str, Any]:
    """Map a normalized record to the stable downstream cash-ledger CSV contract."""
    return {
        "account_suffix": transaction.get("accountSuffix") or "",
        "transaction_id": transaction.get("transactionId") or "",
        "occurred_at": transaction.get("occurredAt") or "",
        "trade_date": transaction.get("tradeDate") or "",
        "settlement_date": transaction.get("settlementDate") or "",
        "transaction_type": transaction.get("transactionType") or "",
        "status": transaction.get("status") or "",
        "net_amount": transaction.get("netAmount") if transaction.get("netAmount") is not None else "",
        "symbol": transaction.get("symbol") or "",
        "asset_type": transaction.get("assetType") or "",
        "quantity": transaction.get("quantity") if transaction.get("quantity") is not None else "",
        "price": transaction.get("price") if transaction.get("price") is not None else "",
        "fee": transaction.get("fee") if transaction.get("fee") is not None else "",
        "source": transaction.get("source") or "schwab-transaction-api",
    }


def save_schwab_transaction_ledger(report: dict[str, Any]) -> None:
    """Persist the safe report and replace CSV only after a complete read."""
    ensure_dirs()
    persisted = dict(report)
    if not report.get("ok") and SCHWAB_TRANSACTION_LEDGER_FILE.exists():
        try:
            previous = json.loads(SCHWAB_TRANSACTION_LEDGER_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            previous = {}
        if previous.get("ok") or previous.get("retainedPriorEvidence"):
            for key in ("transactions", "transactionSummary", "window", "matchedSuffixes"):
                persisted[key] = previous.get(key)
            persisted["retainedPriorEvidence"] = True
            persisted["evidenceGeneratedAt"] = previous.get("evidenceGeneratedAt") or previous.get("generatedAt")
            persisted["evidenceSourceStatus"] = previous.get("evidenceSourceStatus") or previous.get("sourceStatus")
    atomic_write_json(SCHWAB_TRANSACTION_LEDGER_FILE, persisted)
    atomic_write_text(SCHWAB_TRANSACTION_LEDGER_TEXT_FILE, render_schwab_transaction_ledger(persisted))
    if report.get("ok") and report.get("sourceStatus") in {"api", "fixture"}:
        rows = [csv_row(item) for item in report.get("transactions") or []]
        lines: list[str] = []
        with io.StringIO(newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            lines.append(handle.getvalue())
        atomic_write_text(SCHWAB_TRANSACTION_CSV_FILE, "".join(lines))


def money(value: Any) -> str:
    """Format optional cash values without turning unknown into zero."""
    parsed = number(value)
    if parsed is None:
        return "-"
    return f"{'-$' if parsed < 0 else '$'}{abs(parsed):,.2f}"


def render_schwab_transaction_ledger(report: dict[str, Any]) -> str:
    """Render a compact operator memo for the read-only transaction artifact."""
    summary = report.get("transactionSummary") or {}
    window = report.get("window") or {}
    lines = [
        "Inferno Schwab Transaction Ledger",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Verdict: {report.get('verdict')}",
        f"Message: {report.get('message')}",
        f"Configured: {report.get('configured')}",
        f"Read-only: {report.get('brokerReadOnly')} | orders allowed: {report.get('orderEndpointsAllowed')}",
        f"Source: {report.get('sourceStatus')}",
        f"Window: {window.get('startDate') or '-'} to {window.get('endDate') or '-'} ({window.get('lookbackDays') or '-'} days)",
        f"Matched suffixes: {', '.join(report.get('matchedSuffixes') or []) or '-'}",
        "",
        "Transaction facts",
        f"- Rows: {summary.get('transactionCount', 0)}",
        f"- Rows with net amount: {summary.get('rowsWithNetAmount', 0)}",
        f"- Net amount across window: {money(summary.get('netAmountAcrossWindow'))}",
        f"- Option rows: {summary.get('optionTransactionCount', 0)}",
        f"- Option legs: {summary.get('optionLegCount', 0)}; missing position effect: {summary.get('optionLegsMissingPositionEffect', 0)}",
        f"- Matched closed-contract cash: {money((summary.get('closedContractCashReconciliation') or {}).get('matchedNetCash'))}; not complete account profit",
        f"- Duplicate transaction rows suppressed: {report.get('duplicateTransactionsSuppressed', 0)}",
        f"- Prior evidence retained after failed attempt: {bool(report.get('retainedPriorEvidence'))}; evidence time: {report.get('evidenceGeneratedAt') or report.get('generatedAt')}",
        f"- Types: {', '.join(f'{key}={value}' for key, value in (summary.get('transactionTypes') or {}).items()) or '-'}",
        "- Realized options P/L remains unknown; net cash is not lot-level P/L proof.",
        "",
        "Next actions",
    ]
    lines.extend(f"- {item}" for item in report.get("nextActions") or ["none"])
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    """Parse the small, read-only CLI surface."""
    parser = argparse.ArgumentParser(description="Build the read-only Inferno Schwab transaction ledger.")
    parser.add_argument("command", nargs="?", choices=("build", "status"), default="build")
    parser.add_argument("--fixture", type=Path, help="Use a local transaction fixture instead of the live API.")
    parser.add_argument("--skip-refresh", action="store_true", help="Do not refresh OAuth before a transaction request.")
    parser.add_argument("--lookback-days", type=int, help="Bounded transaction-history window (1-365 days).")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    parser.add_argument("--quiet", action="store_true", help="Persist artifacts without printing the memo.")
    return parser.parse_args()


def main() -> int:
    """Run the transaction ledger and persist its safe artifact."""
    args = parse_args()
    if args.command == "status" and SCHWAB_TRANSACTION_LEDGER_TEXT_FILE.exists():
        print(SCHWAB_TRANSACTION_LEDGER_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = build_schwab_transaction_ledger(
        fixture=args.fixture,
        skip_refresh=args.skip_refresh,
        lookback_days=args.lookback_days,
    )
    save_schwab_transaction_ledger(report)
    if not args.quiet:
        print(json.dumps(report, indent=2) if args.json else render_schwab_transaction_ledger(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
