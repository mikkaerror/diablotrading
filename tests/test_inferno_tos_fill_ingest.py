from __future__ import annotations

"""Regression tests for importing paperMoney fill rows into paper evidence."""

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_tos_fill_ingest as ingest


FILL_COLUMNS = [
    "sessionDate",
    "ticketId",
    "ticker",
    "strategy",
    "expiration",
    "environment",
    "paperAccount",
    "routeFamily",
    "orderType",
    "contracts",
    "entryPrice",
    "exitPrice",
    "realizedPnl",
    "status",
    "openedAt",
    "closedAt",
    "notes",
]


def _ticket(**overrides):
    base = {
        "ticketId": "ticket-1",
        "ticker": "GOOG",
        "strategy": "LONG_STRANGLE",
        "status": "paper-staged",
        "entryCostType": "debit",
        "entryLimit": 1.5,
        "outcome": {"status": "open"},
    }
    base.update(overrides)
    return base


def _row(**overrides):
    base = {
        "sessionDate": "2026-07-06",
        "ticketId": "ticket-1",
        "ticker": "GOOG",
        "strategy": "LONG_STRANGLE",
        "expiration": "2026-07-17",
        "environment": "thinkorswim-paperMoney",
        "paperAccount": "paperMoney",
        "routeFamily": "long-volatility event",
        "orderType": "LIMIT",
        "contracts": "1",
        "entryPrice": "1.50",
        "exitPrice": "2.20",
        "realizedPnl": "",
        "status": "closed",
        "openedAt": "2026-07-06T09:45:00-06:00",
        "closedAt": "2026-07-07T09:45:00-06:00",
        "notes": "closed by paper playbook",
    }
    base.update(overrides)
    return base


class InfernoTosFillIngestTests(unittest.TestCase):
    """Verify fill ingestion is idempotent, strict, and evidence-safe."""

    def test_closed_debit_fill_updates_outcome_with_realized_pnl(self) -> None:
        ticket = _ticket()
        updated, changed, result = ingest.apply_fill_row(ticket, _row())

        self.assertTrue(changed)
        self.assertEqual(result, "closed")
        self.assertEqual(updated["paperExecution"]["status"], "closed")
        self.assertAlmostEqual(updated["paperExecution"]["realizedPnl"], 70.0)
        self.assertEqual(updated["outcome"]["status"], "closed")
        self.assertAlmostEqual(updated["outcome"]["exitValue"], 2.2)
        self.assertAlmostEqual(updated["outcome"]["estimatedPnl"], 70.0)
        self.assertIn("realized paper fill imported", updated["outcome"]["notes"])

    def test_closed_credit_fill_derives_profit_from_buyback_cost(self) -> None:
        ticket = _ticket(strategy="PUT_CREDIT_SPREAD", entryCostType="credit", entryLimit=0.9)
        row = _row(strategy="PUT_CREDIT_SPREAD", entryPrice="0.90", exitPrice="0.30")

        updated, changed, result = ingest.apply_fill_row(ticket, row)

        self.assertTrue(changed)
        self.assertEqual(result, "closed")
        self.assertAlmostEqual(updated["paperExecution"]["realizedPnl"], 60.0)
        self.assertAlmostEqual(updated["outcome"]["estimatedPnl"], 60.0)

    def test_duplicate_fill_row_is_idempotent(self) -> None:
        row = _row()
        ticket = _ticket(importedFillKeys=[ingest.row_fingerprint(row)])

        updated, changed, result = ingest.apply_fill_row(ticket, row)

        self.assertFalse(changed)
        self.assertEqual(result, "duplicate fill row already imported")
        self.assertEqual(updated, ticket)

    def test_ingest_requires_one_matching_paper_staged_ticket(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fill_log = Path(tmpdir) / "fills.csv"
            with fill_log.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FILL_COLUMNS)
                writer.writeheader()
                writer.writerow(_row(ticketId="missing-ticket", ticker="ORPH", strategy="LONG_STRADDLE"))

            saved_ledgers: list[dict] = []
            with (
                patch.object(ingest, "TOS_FILL_LOG_WORK_FILE", fill_log),
                patch.object(ingest, "write_fill_log_template", return_value=None),
                patch.object(ingest, "load_ledger", return_value={"items": [_ticket()]}),
                patch.object(ingest, "save_ledger", side_effect=saved_ledgers.append),
                patch.object(ingest, "save_ingest_report", return_value=None),
            ):
                report = ingest.ingest_fill_log()

        self.assertEqual(report["importedRows"], 0)
        self.assertEqual(report["closedRows"], 0)
        self.assertEqual(len(report["unmatchedRows"]), 1)
        self.assertIn("no matching paper-staged ticket", report["unmatchedRows"][0])
        self.assertEqual(saved_ledgers[0]["items"][0]["outcome"]["status"], "open")

    def test_ingest_closed_row_persists_updated_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fill_log = Path(tmpdir) / "fills.csv"
            with fill_log.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FILL_COLUMNS)
                writer.writeheader()
                writer.writerow(_row())

            saved_ledgers: list[dict] = []
            with (
                patch.object(ingest, "TOS_FILL_LOG_WORK_FILE", fill_log),
                patch.object(ingest, "write_fill_log_template", return_value=None),
                patch.object(ingest, "load_ledger", return_value={"items": [_ticket()]}),
                patch.object(ingest, "save_ledger", side_effect=saved_ledgers.append),
                patch.object(ingest, "save_ingest_report", return_value=None),
            ):
                report = ingest.ingest_fill_log()

        self.assertEqual(report["importedRows"], 1)
        self.assertEqual(report["closedRows"], 1)
        updated_ticket = saved_ledgers[0]["items"][0]
        self.assertEqual(updated_ticket["outcome"]["status"], "closed")
        self.assertAlmostEqual(updated_ticket["outcome"]["estimatedPnl"], 70.0)


if __name__ == "__main__":
    unittest.main()
