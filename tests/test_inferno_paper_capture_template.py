from __future__ import annotations

"""Tests for the research-only paper capture-template emitter.

The key guarantee: a row this module emits, once the operator fills the six
execution fields with valid values, passes the real scorer's immutable
evidence check -- so a closed paperMoney fill can actually score toward the
30-outcome gate. And it must never write live state or carry execution facts
of its own.
"""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from datetime import date, timedelta

import inferno_paper_capture_template as ct
import inferno_tos_fill_ingest as fi

# The template only emits rows for tickets that can still be filled, so the
# fixture expiration must stay in the future instead of rotting on a fixed date.
FUTURE_EXPIRATION = (date.today() + timedelta(days=45)).isoformat()


def _ledger(*tickets: dict) -> dict:
    return {"version": 1, "count": len(tickets), "items": list(tickets)}


STAGED_CHKP = {
    "ticketId": "SIMCHKP0001",
    "ticker": "CHKP",
    "strategy": "CALL_DEBIT_SPREAD",
    "status": "paper-staged",
    "expiration": FUTURE_EXPIRATION,
    "entryCostType": "NET_DEBIT_LIMIT",
}


class CaptureTemplateTests(unittest.TestCase):
    def test_one_row_per_paper_staged_ticket_only(self) -> None:
        ledger = _ledger(
            STAGED_CHKP,
            {"ticketId": "b1", "ticker": "AMD", "strategy": "CALL_DEBIT_SPREAD", "status": "paper-blocked"},
            {"ticketId": "r1", "ticker": "TSLA", "strategy": "LONG_STRADDLE", "status": "paper-rejected"},
        )
        payload = ct.build_capture_template(ledger=ledger)
        self.assertEqual(payload["stagedTicketCount"], 1)
        self.assertEqual(len(payload["rows"]), 1)
        self.assertEqual(payload["rows"][0]["ticker"], "CHKP")

    def test_row_carries_immutable_facts(self) -> None:
        payload = ct.build_capture_template(ledger=_ledger(STAGED_CHKP))
        row = payload["rows"][0]
        self.assertEqual(row["ticketId"], "SIMCHKP0001")
        self.assertEqual(row["strategy"], "CALL_DEBIT_SPREAD")
        self.assertEqual(row["expiration"], FUTURE_EXPIRATION)
        self.assertEqual(row["contracts"], "1")
        # Environment must be the exact token the scorer accepts (case-insensitively).
        self.assertEqual(row["environment"].lower(), fi.PAPER_MONEY_ENVIRONMENT)

    def test_execution_fields_are_blank(self) -> None:
        row = ct.build_capture_template(ledger=_ledger(STAGED_CHKP))["rows"][0]
        for field in ("entryPrice", "exitPrice", "realizedPnl", "status", "openedAt", "closedAt"):
            self.assertEqual(row[field], "", f"{field} must be blank in the template")

    def test_no_staged_tickets_yields_empty_verdict(self) -> None:
        payload = ct.build_capture_template(
            ledger=_ledger({"ticketId": "x", "ticker": "AMD", "status": "paper-blocked"})
        )
        self.assertEqual(payload["verdict"], "no-fillable-staged-tickets")
        self.assertEqual(payload["rows"], [])

    def test_expired_staged_ticket_is_not_fillable(self) -> None:
        """A staged ticket whose option already expired must not become a fillable row."""
        expired = {
            "ticketId": "MOD1",
            "ticker": "MOD",
            "strategy": "CALL_DEBIT_SPREAD",
            "status": "paper-staged",
            "expiration": "2020-06-18",  # long past
        }
        payload = ct.build_capture_template(ledger=_ledger(STAGED_CHKP, expired))
        tickers = [r["ticker"] for r in payload["rows"]]
        self.assertIn("CHKP", tickers)
        self.assertNotIn("MOD", tickers)
        self.assertEqual(payload["fillableTicketCount"], 1)
        self.assertEqual(payload["expiredTicketCount"], 1)
        self.assertEqual(payload["expiredStagedTickets"][0]["ticker"], "MOD")
        # The expired ticket is surfaced as cleanup, not hidden.
        self.assertIn("MOD", ct.template_text(payload))
        self.assertIn("NOT fillable", ct.template_text(payload))

    def test_unparseable_expiration_fails_open_to_fillable(self) -> None:
        """A malformed/blank expiration must not silently drop a staged ticket."""
        weird = dict(STAGED_CHKP, ticketId="W1", ticker="WEIRD", expiration="")
        payload = ct.build_capture_template(ledger=_ledger(weird))
        self.assertEqual(payload["fillableTicketCount"], 1)
        self.assertEqual(payload["rows"][0]["ticker"], "WEIRD")

    def test_safety_invariants(self) -> None:
        payload = ct.build_capture_template(ledger=_ledger(STAGED_CHKP))
        self.assertEqual(payload["stage"], "paper-capture-template-research-only")
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["authorityChanged"])
        self.assertFalse(payload["brokerSubmitAllowed"])
        self.assertFalse(payload["liveTradingAllowed"])

    def test_save_writes_only_template_artifacts(self) -> None:
        """The lifecycle JSON accompanies the worksheet without touching source evidence."""
        payload = ct.build_capture_template(ledger=_ledger(STAGED_CHKP))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_path = root / "data" / "inferno_paper_capture_template.json"
            csv_path = root / "reports" / "paper_capture_template_latest.csv"
            text_path = root / "reports" / "paper_capture_template_latest.txt"
            data_path.parent.mkdir()
            csv_path.parent.mkdir()
            with (
                patch.object(ct, "CAPTURE_TEMPLATE_FILE", data_path),
                patch.object(ct, "CAPTURE_TEMPLATE_CSV", csv_path),
                patch.object(ct, "CAPTURE_TEMPLATE_TEXT_FILE", text_path),
            ):
                ct.save_capture_template(payload)

            self.assertIn('"stage": "paper-capture-template-research-only"', data_path.read_text())
            self.assertIn("SIMCHKP0001", csv_path.read_text())
            self.assertIn("research-only", text_path.read_text())

    def test_csv_round_trips_canonical_schema(self) -> None:
        import csv
        import io

        payload = ct.build_capture_template(ledger=_ledger(STAGED_CHKP))
        reader = csv.DictReader(io.StringIO(ct.template_csv_text(payload)))
        self.assertEqual(reader.fieldnames, list(ct.FILL_LOG_COLUMNS))
        rows = list(reader)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticketId"], "SIMCHKP0001")

    def test_filled_template_row_passes_the_real_scorer(self) -> None:
        """The whole point: a filled row must satisfy fill_ingest's evidence check."""
        row = ct.build_capture_template(ledger=_ledger(STAGED_CHKP))["rows"][0]
        # Operator fills exactly the six blanks with valid values.
        row.update(
            {
                "entryPrice": "2.30",
                "exitPrice": "4.10",
                "realizedPnl": "180",
                "status": "closed-win",
                "openedAt": "2026-07-22T09:41:00-06:00",
                "closedAt": "2026-07-23T10:05:00-06:00",
            }
        )
        gaps = fi.closed_fill_evidence_gaps(row)
        self.assertEqual(gaps, [], f"filled template row should be scorable, gaps: {gaps}")
        # And its identity matches the staged ticket exactly.
        identity_gaps = fi.closed_fill_ticket_identity_gaps(STAGED_CHKP, row)
        self.assertEqual(identity_gaps, [])

    def test_blank_template_row_is_not_yet_scorable(self) -> None:
        """Before the operator fills it, the row must NOT pass as evidence."""
        row = ct.build_capture_template(ledger=_ledger(STAGED_CHKP))["rows"][0]
        gaps = fi.closed_fill_evidence_gaps(row)
        # Missing prices and timestamps -> genuinely blank, cannot masquerade as a fill.
        self.assertIn("entryPrice", gaps)
        self.assertIn("openedAt", gaps)


if __name__ == "__main__":
    unittest.main()
