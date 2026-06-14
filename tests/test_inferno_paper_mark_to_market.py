"""Contract tests for inferno_paper_mark_to_market.

Pinned invariants:
  - Module is research-only and promotable=False.
  - Open-position filter selects only outcome.status == 'open'.
  - Per-leg lookup matches by symbol with whitespace tolerance.
  - Signed-mid math: +1 for BUY_TO_OPEN, -1 for SELL_TO_OPEN, summed.
  - Unrealized PnL = (currentSignedMid - signedEntryReference) * 100.
      For debit:  signedEntryReference = +entryLimit  (the cost paid)
      For credit: signedEntryReference = -entryLimit  (the credit received,
                  expressed as the *position's signed entry value*).
  - playbookPctOfDebit is defined only on debit structures and equals the
    runner-ladder reference the trade-management auditor consumes.
  - When the Schwab chain is unavailable, the per-ticket fetchStatus is
    'chain-unavailable' and price fields are None (no fake numbers).
  - The module NEVER mutates the paper-execution ledger.
  - Graceful fallback on Schwab-disabled / no-token / partial-error.
"""

from __future__ import annotations

import copy
import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import inferno_paper_mark_to_market as mtm


NOW = datetime(2026, 5, 27, 4, 0, 0, tzinfo=timezone.utc)


def _ticket(
    *,
    ticket_id: str = "t-1",
    ticker: str = "MOD",
    strategy: str = "CALL_DEBIT_SPREAD",
    legs: list | None = None,
    entry_limit: float = 3.50,
    entry_cost_type: str = "debit",
    max_loss: float = 350.0,
    max_profit: float | str = 650.0,
    outcome_status: str = "open",
) -> dict:
    """Build a paper-ticket dict shaped like an entry in the ledger."""
    return {
        "ticketId": ticket_id,
        "ticker": ticker,
        "strategy": strategy,
        "expiration": "2026-06-18",
        "entryLimit": entry_limit,
        "entryCostType": entry_cost_type,
        "estimatedMaxLoss": max_loss,
        "estimatedMaxProfit": max_profit,
        "legs": legs or [
            {
                "instruction": "BUY_TO_OPEN",
                "symbol": "MOD260618C00290000",
                "bid": 8.3,
                "ask": 11.0,
                "mid": 9.65,
            },
            {
                "instruction": "SELL_TO_OPEN",
                "symbol": "MOD260618C00300000",
                "bid": 7.5,
                "ask": 9.0,
                "mid": 8.25,
            },
        ],
        "outcome": {"status": outcome_status},
    }


def _chain_contracts(symbol_to_mid: dict[str, float]) -> list[dict]:
    """Build a normalized-contract list suitable for the lookup helper."""
    rows = []
    for sym, mid in symbol_to_mid.items():
        rows.append(
            {
                "symbol": sym,
                "putCall": "CALL",
                "mid": mid,
                "bid": mid - 0.5,
                "ask": mid + 0.5,
                "spreadPct": round(1.0 / mid, 4) if mid > 0 else None,
            }
        )
    return rows


# ───────────────────── single-ticket MTM math ─────────────────────────


class SingleTicketMTMTests(unittest.TestCase):
    def test_debit_spread_profit_path(self) -> None:
        """Debit spread mid widened: PnL positive."""
        # Entry legs: long mid 9.65, short mid 8.25 -> signed_entry = +1.40
        # Current legs: long mid 10.20, short mid 8.40 -> signed_now = +1.80
        # Per-share PnL vs entryLimit (3.50): 1.80 - 3.50 = -1.70 -> $-170
        # Per-share PnL vs entry mid (1.40):  1.80 - 1.40 = +0.40 -> not used
        ticket = _ticket()
        contracts = _chain_contracts({
            "MOD260618C00290000": 10.20,
            "MOD260618C00300000": 8.40,
        })
        out = mtm.mark_to_market_one_ticket(
            ticket, contracts=contracts, underlying_price=290.0, now=NOW
        )
        self.assertAlmostEqual(out["currentSignedMid"], 1.80, places=2)
        self.assertEqual(out["unrealizedPnlDollars"], -170.0)
        self.assertAlmostEqual(out["unrealizedPnlPctOfEntryLimit"], -0.4857, places=3)
        self.assertEqual(out["fetchStatus"], "ok")
        self.assertEqual(out["warnings"], [])

    def test_debit_spread_at_double(self) -> None:
        """When current spread mid = 2x entry limit, PnL = +max profit-ish."""
        # entryLimit 3.50 -> current mid 7.00 -> PnL = +3.50 per share = +$350
        ticket = _ticket()
        contracts = _chain_contracts({
            "MOD260618C00290000": 15.00,
            "MOD260618C00300000": 8.00,
        })
        out = mtm.mark_to_market_one_ticket(
            ticket, contracts=contracts, underlying_price=300.0, now=NOW
        )
        self.assertAlmostEqual(out["currentSignedMid"], 7.00, places=2)
        self.assertEqual(out["unrealizedPnlDollars"], 350.0)
        self.assertAlmostEqual(out["unrealizedPnlPctOfEntryLimit"], 1.0, places=3)
        self.assertAlmostEqual(out["playbookPctOfDebit"], 1.0, places=3)

    def test_chain_unavailable_returns_blocked_status(self) -> None:
        ticket = _ticket()
        out = mtm.mark_to_market_one_ticket(
            ticket, contracts=None, underlying_price=None, now=NOW
        )
        self.assertEqual(out["fetchStatus"], "chain-unavailable")
        self.assertIsNone(out["currentSignedMid"])
        self.assertIsNone(out["unrealizedPnlDollars"])
        self.assertIn(
            "current net mid is unavailable; price-triggered rules are blocked",
            out["warnings"],
        )

    def test_partial_unmatched_leg(self) -> None:
        """One matched leg, one missing -> partial fetch status, no net mid."""
        ticket = _ticket()
        contracts = _chain_contracts({
            "MOD260618C00290000": 10.20,
            # short-leg symbol intentionally absent
        })
        out = mtm.mark_to_market_one_ticket(
            ticket, contracts=contracts, underlying_price=290.0, now=NOW
        )
        self.assertEqual(out["fetchStatus"], "partial")
        self.assertIsNone(out["currentSignedMid"])
        self.assertIn(
            "at least one leg could not be matched in the chain",
            out["warnings"],
        )

    def test_credit_spread_signs(self) -> None:
        """Put credit spread: BUY lower-strike put (long), SELL higher-strike put (short).

        entry: BUY 38P mid 3.10, SELL 40P mid 4.20 -> signed_entry = +3.10 - 4.20 = -1.10
                entryLimit = 1.10 (credit), entryCostType="credit"
                signedEntryReference = -entry_limit = -1.10 (matches signed_entry)
        Move favorably: BUY 38P mid 2.50, SELL 40P mid 3.30 -> signed_now = -0.80
        per_share_pnl = -0.80 - (-1.10) = +0.30 -> $+30 per contract.
        """
        legs = [
            {
                "instruction": "BUY_TO_OPEN",
                "symbol": "PL260618P00038000",
                "bid": 2.9,
                "ask": 3.3,
                "mid": 3.10,
            },
            {
                "instruction": "SELL_TO_OPEN",
                "symbol": "PL260618P00040000",
                "bid": 3.9,
                "ask": 4.5,
                "mid": 4.20,
            },
        ]
        ticket = _ticket(
            ticker="PL",
            strategy="PUT_CREDIT_SPREAD",
            legs=legs,
            entry_limit=1.10,
            entry_cost_type="credit",
            max_loss=90.0,  # width 2 - credit 1.10 = 0.90
            max_profit=110.0,
        )
        contracts = _chain_contracts({
            "PL260618P00038000": 2.50,
            "PL260618P00040000": 3.30,
        })
        out = mtm.mark_to_market_one_ticket(
            ticket, contracts=contracts, underlying_price=42.0, now=NOW
        )
        self.assertAlmostEqual(out["entrySignedMid"], -1.10, places=2)
        self.assertAlmostEqual(out["currentSignedMid"], -0.80, places=2)
        self.assertAlmostEqual(out["unrealizedPnlDollars"], 30.0, places=2)
        # Credit structures don't get playbookPctOfDebit (Lane A rule);
        # auditor uses unrealizedPnlPctOfMaxProfit instead.
        self.assertIsNone(out["playbookPctOfDebit"])
        # +$30 / $110 max profit ~= 0.273
        self.assertAlmostEqual(out["unrealizedPnlPctOfMaxProfit"], 0.273, places=2)


# ───────────────────── filtering + lookup helpers ─────────────────────


class OpenPositionFilterTests(unittest.TestCase):
    def test_open_filter_picks_only_outcome_open(self) -> None:
        ledger = {
            "items": [
                {"ticketId": "t1", "outcome": {"status": "open"}},
                {"ticketId": "t2", "outcome": {"status": "closed"}},
                {"ticketId": "t3", "outcome": {"status": "not-opened"}},
                {"ticketId": "t4"},  # no outcome key
                {"ticketId": "t5", "outcome": {"status": "open"}},
            ]
        }
        open_tickets = mtm._open_paper_tickets(ledger)
        self.assertEqual([t["ticketId"] for t in open_tickets], ["t1", "t5"])

    def test_unique_underlyings_dedupes(self) -> None:
        tickets = [
            {"ticker": "mod"},
            {"ticker": "MOD"},
            {"ticker": "PL"},
            {"ticker": ""},
        ]
        self.assertEqual(mtm._unique_underlyings(tickets), ["MOD", "PL"])


class LegLookupTests(unittest.TestCase):
    def test_symbol_match_tolerates_whitespace(self) -> None:
        contracts = [
            {"symbol": "MOD  260618C00290000", "mid": 9.65},
            {"symbol": "MOD  260618C00300000", "mid": 8.25},
        ]
        match = mtm._lookup_leg(contracts, "MOD260618C00290000")
        self.assertIsNotNone(match)
        self.assertEqual(match["mid"], 9.65)

    def test_no_match_returns_none(self) -> None:
        contracts = [{"symbol": "MOD260618C00290000", "mid": 9.65}]
        self.assertIsNone(mtm._lookup_leg(contracts, "MOD260618C99999999"))


# ───────────────────── end-to-end build with fixture ──────────────────


class BuildIntegrationTests(unittest.TestCase):
    def test_load_schwab_env_enables_scheduled_market_data_config(self) -> None:
        with (
            patch.object(
                mtm,
                "parse_env_file",
                return_value={"SCHWAB_OPTIONS_ENABLED": "1"},
            ),
            patch.dict(os.environ, {}, clear=True),
        ):
            values = mtm.load_schwab_env()
            self.assertEqual(os.environ["SCHWAB_OPTIONS_ENABLED"], "1")

        self.assertEqual(values["SCHWAB_OPTIONS_ENABLED"], "1")

    def test_research_only_invariants(self) -> None:
        ledger_override = {"items": []}
        payload = mtm.build_paper_mark_to_market(
            now=NOW, ledger_override=ledger_override
        )
        self.assertEqual(payload["stage"], mtm.PAPER_MTM_STAGE)
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["authorityChanged"])
        self.assertEqual(payload["openPositionCount"], 0)
        self.assertEqual(payload["fetchStatus"], "no-open-positions")

    def test_does_not_mutate_ledger(self) -> None:
        """Critical invariant: building the artifact never edits the ledger."""
        ledger = {"items": [_ticket()]}
        ledger_snapshot = copy.deepcopy(ledger)
        mtm.build_paper_mark_to_market(
            now=NOW, ledger_override=ledger, fixture_payloads={}
        )
        self.assertEqual(ledger, ledger_snapshot)

    def test_open_position_with_fixture_chain(self) -> None:
        ledger = {"items": [_ticket()]}

        # The Schwab adapter's fetch_option_chain returns the *raw* chain
        # payload; flatten_contracts then turns it into a contract list. We
        # bypass that step by mocking both helpers so this test stays a
        # tight unit on this module's logic, not the adapter's.
        fake_chain = {
            "callExpDateMap": {
                "2026-06-18:23": {
                    "290.0": [
                        {
                            "symbol": "MOD260618C00290000",
                            "bid": 9.8,
                            "ask": 10.6,
                            "putCall": "CALL",
                            "expirationDate": "2026-06-18",
                            "strikePrice": 290.0,
                        }
                    ],
                    "300.0": [
                        {
                            "symbol": "MOD260618C00300000",
                            "bid": 8.1,
                            "ask": 8.7,
                            "putCall": "CALL",
                            "expirationDate": "2026-06-18",
                            "strikePrice": 300.0,
                        }
                    ],
                }
            }
        }
        with patch.object(mtm, "SCHWAB_OPTIONS_ENABLED", True):
            payload = mtm.build_paper_mark_to_market(
                now=NOW,
                ledger_override=ledger,
                token_override="fake-bearer-token",
                fixture_payloads={"MOD": fake_chain},
            )
        self.assertEqual(payload["fetchStatus"], "fixture")
        self.assertEqual(payload["openPositionCount"], 1)
        marks = payload["marksByTicketId"]
        self.assertIn("t-1", marks)
        m = marks["t-1"]
        self.assertEqual(m["fetchStatus"], "ok")
        # current mids: (9.8+10.6)/2 = 10.20, (8.1+8.7)/2 = 8.40
        # signed_now = +10.20 - 8.40 = +1.80
        # per_share PnL vs entryLimit 3.50 = 1.80 - 3.50 = -1.70 -> $-170
        self.assertAlmostEqual(m["currentSignedMid"], 1.80, places=2)
        self.assertEqual(m["unrealizedPnlDollars"], -170.0)


# ───────────────────── render smoke test ──────────────────────────────


class TextRendererTests(unittest.TestCase):
    def test_text_includes_all_sections(self) -> None:
        ledger = {"items": [_ticket()]}
        payload = mtm.build_paper_mark_to_market(
            now=NOW, ledger_override=ledger, fixture_payloads={}
        )
        text = mtm.paper_mark_to_market_text(payload)
        for required in (
            "Inferno Paper Mark-to-Market",
            "Generated:",
            "Fetch status:",
            "Open positions:",
            "Reminders:",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
