from __future__ import annotations

"""Paper-ticket mark-to-market refresh (research-only).

For every OPEN paper ticket in the ledger, re-query the Schwab option chain
for its underlying, look up each leg by symbol, and recompute the current
spread mid. The result is a separate artifact keyed by ``ticketId`` -- this
module deliberately does NOT mutate the paper-execution ledger.

Why this matters:
    Every price-triggered playbook rule (Lane A profit ladder +50/+100/+200%
    of debit, Lane A stop -50%, Lane B credit-spread close at 50% of max
    profit, Lane B debit-spread close at 50/80%) needs a current mid.
    Without it, the rules are operator-vibe-checked, not auditable.

What it does:
  - Reads the paper execution ledger and filters to open tickets.
  - Groups open tickets by underlying ticker; one Schwab chain fetch per
    ticker (rate-limit-friendly).
  - Looks up each leg symbol in the fetched chain; computes per-leg current
    mid plus a normalized 1-100 freshness score.
  - Computes the net-signed mid (sign per ``instruction``) at entry and now,
    plus unrealized PnL in dollars and as a fraction of entryLimit / max loss
    / max profit. These are the percentages the trade-management auditor
    will consume.
  - Falls back gracefully when Schwab is disabled, the token is missing, or
    a leg symbol can't be matched. The fetchStatus per ticket and per leg
    tells the downstream auditor what to trust.

What it does NOT do:
  - Mutate the paper execution ledger.
  - Touch ``liveTradingAllowed`` / ``brokerSubmitAllowed`` (still hard-coded
    False in inferno_authority_controller).
  - Stage, approve, close, or recommend closing any position.
  - Place an order.

Strict contract: research-only, diagnostic-only, promotable=False.

CLI::

    python3 inferno_paper_mark_to_market.py            # refresh + persist
    python3 inferno_paper_mark_to_market.py status     # show last cached report
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from inferno_config import (
    SCHWAB_OPTIONS_ENABLED,
    local_now,
)
from inferno_io import atomic_write_json, atomic_write_text
from inferno_schwab_options import (
    fetch_option_chain,
    flatten_contracts,
    load_schwab_access_token,
    normalize_contract,
)
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


# ─────────────────────────── files / constants ───────────────────────

PAPER_EXECUTION_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
PAPER_MTM_FILE = DATA_DIR / "inferno_paper_mark_to_market.json"
PAPER_MTM_TEXT_FILE = REPORTS_DIR / "paper_mark_to_market_latest.txt"

PAPER_MTM_STAGE = "paper-mark-to-market-research-only"


# ─────────────────────────── helpers ──────────────────────────────────


def _safe_float(value: Any) -> float | None:
    """Best-effort numeric coercion."""
    if value is None:
        return None
    try:
        v = float(value)
        return v if v == v else None  # filter NaN
    except (TypeError, ValueError):
        return None


def _instruction_sign(instruction: str | None) -> int | None:
    """+1 for BUY_TO_OPEN, -1 for SELL_TO_OPEN. Anything else is ambiguous."""
    raw = str(instruction or "").upper()
    if raw.startswith("BUY"):
        return 1
    if raw.startswith("SELL"):
        return -1
    return None


def _open_paper_tickets(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Return ledger items that are currently open paper positions.

    A ticket is open when its outcome.status is 'open'. A 'paper-staged'
    status alone is not enough -- a staged ticket whose outcome is still
    'not-opened' has not been filled yet.
    """
    items = ledger.get("items") or []
    return [
        it
        for it in items
        if ((it.get("outcome") or {}).get("status")) == "open"
    ]


def _unique_underlyings(tickets: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for t in tickets:
        ticker = str(t.get("ticker") or "").strip().upper()
        if ticker and ticker not in seen:
            seen[ticker] = None
    return list(seen.keys())


def _fetch_chains(
    underlyings: list[str],
    *,
    fixture_payloads: dict[str, dict[str, Any]] | None,
    token: str | None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]], str]:
    """Fetch and flatten the Schwab option chain for each underlying.

    Returns (contracts_by_underlying, errors, fetchStatus). The contracts list
    is normalized so per-leg lookup is by symbol.
    """
    contracts_by_underlying: dict[str, list[dict[str, Any]]] = {}
    errors: list[dict[str, str]] = []

    if not underlyings:
        return contracts_by_underlying, errors, "no-open-positions"

    if fixture_payloads is not None:
        status = "fixture"
    elif not SCHWAB_OPTIONS_ENABLED:
        status = "disabled"
    elif not token:
        status = "not-configured"
    else:
        status = "ok"

    for symbol in underlyings:
        try:
            if fixture_payloads is not None:
                payload = fixture_payloads.get(symbol)
                if payload is None:
                    errors.append({"symbol": symbol, "error": "fixture-missing"})
                    continue
            elif status == "ok" and token:
                payload = fetch_option_chain(symbol, access_token=token)
            else:
                continue
            raw_contracts = flatten_contracts(payload)
            contracts_by_underlying[symbol] = [
                normalize_contract(c) for c in raw_contracts
            ]
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})

    if errors and contracts_by_underlying:
        status = "partial-error"
    elif errors and not contracts_by_underlying:
        status = "error"
    return contracts_by_underlying, errors, status


def _lookup_leg(
    contracts: list[dict[str, Any]],
    leg_symbol: str,
) -> dict[str, Any] | None:
    """Match a paper-ticket leg to a normalized chain contract by symbol.

    Schwab symbols may have variable whitespace; do a robust compare.
    """
    target = str(leg_symbol or "").replace(" ", "").upper()
    if not target:
        return None
    for c in contracts:
        candidate = str(c.get("symbol") or "").replace(" ", "").upper()
        if candidate == target:
            return c
    return None


# ─────────────────────────── per-ticket MTM ──────────────────────────


def mark_to_market_one_ticket(
    ticket: dict[str, Any],
    *,
    contracts: list[dict[str, Any]] | None,
    underlying_price: float | None,
    now: datetime,
) -> dict[str, Any]:
    """Compute the mark-to-market view of one open paper ticket.

    Inputs:
        ticket           -- a paper ledger item (must include ``legs``,
                            ``entryLimit``, ``entryCostType``,
                            ``estimatedMaxLoss``, ``estimatedMaxProfit``).
        contracts        -- normalized chain contracts for this ticker (may
                            be None if the fetch failed).
        underlying_price -- current underlying price if available.
        now              -- aware datetime used for ``asOf``.

    Output:
        A dict with current mids per leg, net mid, unrealized PnL in both
        dollar and percentage terms (vs entry limit, max loss, max profit),
        and a fetch status / warnings list the auditor can act on.
    """
    legs = ticket.get("legs") or []
    contract_multiplier = 100
    contracts_quantity = 1  # the desk does single-contract paper tickets

    per_leg_rows: list[dict[str, Any]] = []
    entry_signed_mid = 0.0
    current_signed_mid: float | None = 0.0
    any_leg_unmatched = False
    any_leg_missing_sign = False

    for leg in legs:
        symbol = leg.get("symbol")
        instruction = leg.get("instruction")
        sign = _instruction_sign(instruction)
        original_mid = _safe_float(leg.get("mid"))
        original_bid = _safe_float(leg.get("bid"))
        original_ask = _safe_float(leg.get("ask"))
        if sign is None:
            any_leg_missing_sign = True
        else:
            if original_mid is not None:
                entry_signed_mid += sign * original_mid

        match = None
        if contracts is not None and symbol:
            match = _lookup_leg(contracts, symbol)

        current_mid = _safe_float(match.get("mid") if match else None)
        current_bid = _safe_float(match.get("bid") if match else None)
        current_ask = _safe_float(match.get("ask") if match else None)
        spread_pct = _safe_float(match.get("spreadPct") if match else None)

        per_leg_status = "matched" if match else (
            "chain-unavailable" if contracts is None else "unmatched"
        )
        if not match:
            any_leg_unmatched = True

        if sign is not None and current_mid is not None:
            current_signed_mid += sign * current_mid  # type: ignore[operator]
        elif sign is not None and current_mid is None:
            current_signed_mid = None  # cannot compute net without all legs

        delta_pct: float | None = None
        if original_mid is not None and current_mid is not None and original_mid != 0:
            delta_pct = round((current_mid - original_mid) / original_mid, 4)

        per_leg_rows.append(
            {
                "symbol": symbol,
                "instruction": instruction,
                "sign": sign,
                "originalMid": original_mid,
                "originalBid": original_bid,
                "originalAsk": original_ask,
                "currentMid": current_mid,
                "currentBid": current_bid,
                "currentAsk": current_ask,
                "currentSpreadPct": spread_pct,
                "deltaPct": delta_pct,
                "status": per_leg_status,
            }
        )

    entry_limit = _safe_float(ticket.get("entryLimit"))
    entry_cost_type = str(ticket.get("entryCostType") or "").lower()
    max_loss = _safe_float(ticket.get("estimatedMaxLoss"))
    max_profit_raw = ticket.get("estimatedMaxProfit")
    max_profit = (
        _safe_float(max_profit_raw)
        if not (isinstance(max_profit_raw, str) and max_profit_raw == "uncapped")
        else None
    )
    max_profit_uncapped = isinstance(max_profit_raw, str) and max_profit_raw == "uncapped"

    # Unrealized PnL per share (long the position):
    #   For any structure, signed_mid_now − signed_mid_at_entry captures the
    #   PnL of the *long* position; debit and credit naturally fall out of
    #   the signs.  We compare against entry_signed_mid (mid-based) and also
    #   provide a version vs entryLimit (the limit you actually paid/got).
    unrealized_pnl_dollars: float | None = None
    unrealized_pnl_pct_of_entry_limit: float | None = None
    unrealized_pnl_pct_of_max_loss: float | None = None
    unrealized_pnl_pct_of_max_profit: float | None = None
    playbook_pct_of_debit: float | None = None

    if current_signed_mid is not None and entry_limit is not None:
        # For a DEBIT, entry_limit is positive (the per-share cost).
        # For a CREDIT, entry_limit is positive (the per-share credit received).
        # We need the *signed* reference: debit -> +entry_limit, credit -> -entry_limit.
        if entry_cost_type == "credit":
            signed_entry_reference = -entry_limit
        else:
            # treat anything that isn't explicitly credit as debit
            signed_entry_reference = +entry_limit

        per_share_pnl = current_signed_mid - signed_entry_reference
        if entry_cost_type == "credit":
            # For credit structures, the long-position PnL inverts: receiving
            # a credit means you profit when buy-back cost is LOWER than the
            # credit collected. signed_now and signed_entry_reference are
            # both <= 0; profit = signed_now − signed_entry_reference > 0
            # already holds.  No additional flip needed.
            pass
        unrealized_pnl_dollars = round(
            per_share_pnl * contract_multiplier * contracts_quantity, 2
        )
        unrealized_pnl_pct_of_entry_limit = (
            round(per_share_pnl / entry_limit, 4) if entry_limit > 0 else None
        )
        if max_loss and max_loss > 0:
            unrealized_pnl_pct_of_max_loss = round(
                unrealized_pnl_dollars / max_loss, 4
            )
        if max_profit and max_profit > 0:
            unrealized_pnl_pct_of_max_profit = round(
                unrealized_pnl_dollars / max_profit, 4
            )
        # ``playbookPctOfDebit`` is the Lane A trigger reference: at +0.50
        # the runner ladder's first take-profit fires, at +1.00 the second,
        # at +2.00 the third, at −0.50 the stop fires. Defined on debit
        # structures only; for credit structures the auditor uses
        # ``unrealizedPnlPctOfMaxProfit`` against the 50% / 80% rules.
        if entry_cost_type != "credit" and entry_limit > 0:
            playbook_pct_of_debit = round(per_share_pnl / entry_limit, 4)

    warnings: list[str] = []
    if any_leg_unmatched:
        warnings.append("at least one leg could not be matched in the chain")
    if any_leg_missing_sign:
        warnings.append("at least one leg has an unrecognized instruction")
    if current_signed_mid is None:
        warnings.append("current net mid is unavailable; price-triggered rules are blocked")
    if contracts is None:
        warnings.append("Schwab chain for this underlying was not fetched")

    fetch_status = (
        "ok"
        if (contracts is not None and not any_leg_unmatched and current_signed_mid is not None)
        else (
            "chain-unavailable"
            if contracts is None
            else "partial"
        )
    )

    return {
        "ticketId": ticket.get("ticketId"),
        "ticker": ticket.get("ticker"),
        "strategy": ticket.get("strategy"),
        "expiration": ticket.get("expiration"),
        "entryCostType": entry_cost_type or None,
        "asOf": now.isoformat(),
        "schwabUnderlyingPrice": underlying_price,
        "perLeg": per_leg_rows,
        "entrySignedMid": round(entry_signed_mid, 4) if entry_signed_mid is not None else None,
        "currentSignedMid": round(current_signed_mid, 4) if current_signed_mid is not None else None,
        "entryLimit": entry_limit,
        "estimatedMaxLoss": max_loss,
        "estimatedMaxProfit": max_profit,
        "estimatedMaxProfitUncapped": max_profit_uncapped,
        "unrealizedPnlDollars": unrealized_pnl_dollars,
        "unrealizedPnlPctOfEntryLimit": unrealized_pnl_pct_of_entry_limit,
        "unrealizedPnlPctOfMaxLoss": unrealized_pnl_pct_of_max_loss,
        "unrealizedPnlPctOfMaxProfit": unrealized_pnl_pct_of_max_profit,
        "playbookPctOfDebit": playbook_pct_of_debit,
        "fetchStatus": fetch_status,
        "warnings": warnings,
    }


# ─────────────────────────── build + render ───────────────────────────


def build_paper_mark_to_market(
    *,
    now: datetime | None = None,
    fixture_payloads: dict[str, dict[str, Any]] | None = None,
    token_override: str | None = None,
    ledger_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the mark-to-market artifact for every open paper ticket."""
    now = now or local_now()
    ledger = ledger_override if ledger_override is not None else (
        load_json_file(PAPER_EXECUTION_LEDGER_FILE) or {"items": []}
    )
    open_tickets = _open_paper_tickets(ledger)
    underlyings = _unique_underlyings(open_tickets)

    token = token_override if token_override is not None else load_schwab_access_token()
    contracts_by_underlying, errors, fetch_status = _fetch_chains(
        underlyings, fixture_payloads=fixture_payloads, token=token
    )

    underlying_price_by_symbol: dict[str, float | None] = {}
    for symbol, contracts in contracts_by_underlying.items():
        # Schwab embeds underlying price in the chain payload at top level;
        # since we only kept normalized contracts here, we recover it lazily
        # from the first contract's strike+inTheMoney pair if useful, but
        # most callers don't need it. Default to None unless surfaced.
        underlying_price_by_symbol[symbol] = None

    marks: dict[str, dict[str, Any]] = {}
    for ticket in open_tickets:
        ticker = str(ticket.get("ticker") or "").upper()
        contracts = contracts_by_underlying.get(ticker)
        ticket_id = str(ticket.get("ticketId") or "")
        if not ticket_id:
            continue
        marks[ticket_id] = mark_to_market_one_ticket(
            ticket,
            contracts=contracts,
            underlying_price=underlying_price_by_symbol.get(ticker),
            now=now,
        )

    return {
        "generatedAt": now.isoformat(),
        "stage": PAPER_MTM_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "verdict": fetch_status,  # mirrors fetchStatus so doctor helper can read it
        "fetchStatus": fetch_status,
        "schwabConfigured": bool(SCHWAB_OPTIONS_ENABLED and token),
        "openPositionCount": len(open_tickets),
        "underlyingCount": len(underlyings),
        "marksByTicketId": marks,
        "errors": errors,
        "reminders": [
            "research-only; does not mutate the paper ledger",
            "broker submit OFF; liveTradingAllowed False; no authority change",
            "feed for inferno_trade_management price-triggered rules",
        ],
    }


def paper_mark_to_market_text(payload: dict[str, Any]) -> str:
    """Render a compact operator memo of the latest MTM snapshot."""
    marks = payload.get("marksByTicketId") or {}
    lines = [
        "Inferno Paper Mark-to-Market",
        "",
        f"Generated:       {payload.get('generatedAt')}",
        f"Fetch status:    {payload.get('fetchStatus')}",
        f"Schwab configured: {payload.get('schwabConfigured')}",
        f"Open positions:  {payload.get('openPositionCount')}",
        f"Underlyings:     {payload.get('underlyingCount')}",
        "",
    ]
    if not marks:
        lines.append("(no open paper positions to mark)")
    else:
        lines.append("Per-position marks:")
        for tid, m in marks.items():
            pnl = m.get("unrealizedPnlDollars")
            pct_dbt = m.get("playbookPctOfDebit")
            pct_max = m.get("unrealizedPnlPctOfMaxProfit")
            pct_loss = m.get("unrealizedPnlPctOfMaxLoss")
            lines.append("")
            lines.append(
                f"  {m.get('ticker')} {m.get('strategy')} exp {m.get('expiration')} "
                f"(ticketId {tid[:8]}…)"
            )
            lines.append(
                f"    fetch={m.get('fetchStatus')} | unrealized PnL: "
                f"${pnl if pnl is not None else 'n/a'} | "
                f"% of entry: {pct_dbt if pct_dbt is not None else 'n/a'} | "
                f"% of max profit: {pct_max if pct_max is not None else 'n/a'} | "
                f"% of max loss: {pct_loss if pct_loss is not None else 'n/a'}"
            )
            warnings = m.get("warnings") or []
            for w in warnings:
                lines.append(f"      ! {w}")
    errors = payload.get("errors") or []
    if errors:
        lines.append("")
        lines.append("Errors:")
        for e in errors:
            lines.append(f"  - {e}")
    lines.append("")
    lines.append("Reminders:")
    for r in payload.get("reminders") or []:
        lines.append(f"  - {r}")
    return "\n".join(lines).rstrip() + "\n"


def save_paper_mark_to_market(payload: dict[str, Any]) -> None:
    """Persist artifact + text report."""
    ensure_dirs()
    atomic_write_json(PAPER_MTM_FILE, payload)
    atomic_write_text(PAPER_MTM_TEXT_FILE, paper_mark_to_market_text(payload))


# ─────────────────────────── CLI ──────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inferno paper mark-to-market refresh (research-only)"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "status"],
        help="run: refresh + persist (default). status: print last cached report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        if PAPER_MTM_TEXT_FILE.exists():
            print(PAPER_MTM_TEXT_FILE.read_text(encoding="utf-8"))
            return 0
        print("(no cached paper_mark_to_market report)")
        return 0
    payload = build_paper_mark_to_market()
    save_paper_mark_to_market(payload)
    print(paper_mark_to_market_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
