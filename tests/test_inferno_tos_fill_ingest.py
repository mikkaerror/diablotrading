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

    def test_closed_fill_missing_immutable_evidence_cannot_mutate_ticket(self) -> None:
        ticket = _ticket()
        incomplete = _row(ticketId="", contracts="", entryPrice="", exitPrice="", openedAt="", closedAt="")

        updated, changed, result = ingest.apply_fill_row(ticket, incomplete)

        self.assertFalse(changed)
        self.assertEqual(updated, ticket)
        self.assertIn("closed fill rejected", result)
        for field in ("ticketId", "contracts", "entryPrice", "exitPrice", "openedAt", "closedAt"):
            self.assertIn(field, result)

    def test_closed_fill_rejects_invalid_numeric_or_ticket_identity(self) -> None:
        ticket = _ticket()
        invalid_numeric = _row(contracts="1.5", exitPrice="nan")

        updated, changed, result = ingest.apply_fill_row(ticket, invalid_numeric)

        self.assertFalse(changed)
        self.assertEqual(updated, ticket)
        self.assertIn("contracts", result)
        self.assertIn("exitPrice", result)

        updated, changed, result = ingest.apply_fill_row(ticket, _row(ticker="WRONG"))

        self.assertFalse(changed)
        self.assertEqual(updated, ticket)
        self.assertIn("immutable identity does not match ticket", result)
        self.assertIn("ticker", result)

    def test_closed_fill_rejects_invalid_time_evidence_and_nonstaged_ticket(self) -> None:
        ticket = _ticket()
        invalid_time = _row(openedAt="2026-07-07T10:00:00-06:00", closedAt="2026-07-07T09:45:00-06:00")

        updated, changed, result = ingest.apply_fill_row(ticket, invalid_time)

        self.assertFalse(changed)
        self.assertEqual(updated, ticket)
        self.assertIn("closedAt", result)

        updated, changed, result = ingest.apply_fill_row(_ticket(status="paper-blocked"), _row())

        self.assertFalse(changed)
        self.assertIn("not paper-staged", result)

    def test_closed_fill_ignores_nonfinite_supplied_pnl_and_derives_from_execution_facts(self) -> None:
        updated, changed, result = ingest.apply_fill_row(_ticket(), _row(realizedPnl="nan"))

        self.assertTrue(changed)
        self.assertEqual(result, "closed")
        self.assertAlmostEqual(updated["paperExecution"]["realizedPnl"], 70.0)

    def test_ingest_nonfinal_row_requires_one_matching_paper_staged_ticket(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fill_log = Path(tmpdir) / "fills.csv"
            with fill_log.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FILL_COLUMNS)
                writer.writeheader()
                writer.writerow(_row(ticketId="missing-ticket", ticker="ORPH", strategy="LONG_STRADDLE", status="open"))

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
        self.assertEqual(saved_ledgers[0]["lifecycleStatus"], "success")
        self.assertEqual(saved_ledgers[0]["producer"], "inferno-tos-fill-ingest")
        self.assertEqual(report["ledgerLifecycleStatus"], "success")
        self.assertEqual(report["outcome"], "accepted-progress")
        self.assertEqual(report["acceptedProgressUnits"], 1)

    def test_planned_rows_are_reported_as_no_progress_not_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fill_log = Path(tmpdir) / "fills.csv"
            with fill_log.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FILL_COLUMNS)
                writer.writeheader()
                writer.writerow(_row(status="planned", entryPrice="", exitPrice="", openedAt="", closedAt=""))

            with (
                patch.object(ingest, "TOS_FILL_LOG_WORK_FILE", fill_log),
                patch.object(ingest, "write_fill_log_template", return_value=None),
                patch.object(ingest, "load_ledger", return_value={"items": [_ticket()]}),
                patch.object(ingest, "save_ledger", return_value=None),
                patch.object(ingest, "save_ingest_report", return_value=None),
            ):
                report = ingest.ingest_fill_log()

        self.assertEqual(report["importedRows"], 0)
        self.assertEqual(report["outcome"], "no-progress-planned-or-ignored")
        self.assertEqual(report["acceptedProgressUnits"], 0)

    def test_ingest_rejects_incomplete_closed_row_without_changing_ticket(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fill_log = Path(tmpdir) / "fills.csv"
            with fill_log.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FILL_COLUMNS)
                writer.writeheader()
                writer.writerow(_row(exitPrice="", closedAt=""))

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
        self.assertEqual(report["rejectedRows"], 1)
        self.assertEqual(saved_ledgers[0]["items"][0], _ticket())
        self.assertIn("closed fill rejected", report["notes"][0])

    def test_ingest_closed_row_requires_exact_ticket_id_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fill_log = Path(tmpdir) / "fills.csv"
            with fill_log.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FILL_COLUMNS)
                writer.writeheader()
                writer.writerow(_row(ticketId="other-ticket"))

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
        self.assertEqual(report["rejectedRows"], 1)
        self.assertEqual(report["unmatchedRows"], [])
        self.assertEqual(saved_ledgers[0]["items"][0], _ticket())
        self.assertIn("exact paper-staged ticketId match required", report["notes"][0])


if __name__ == "__main__":
    unittest.main()
