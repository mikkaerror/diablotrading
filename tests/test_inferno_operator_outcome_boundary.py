"""Background readers must not turn expiration or a populated CSV into action."""

import copy
import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import inferno_outcome_reviewer as reviewer
import inferno_tos_fill_ingest as ingest
from tests.test_inferno_tos_fill_ingest import FILL_COLUMNS, _row, _ticket


class OperatorOutcomeBoundaryTests(unittest.TestCase):
    def test_expiration_day_waits_and_later_review_never_closes(self):
        ticket = _ticket(expiration="2026-07-17")
        self.assertFalse(reviewer.ticket_ready_for_review(ticket, date(2026, 7, 17))[0])
        self.assertTrue(reviewer.ticket_ready_for_review(ticket, date(2026, 7, 18))[0])
        before = copy.deepcopy(ticket)
        with patch.object(reviewer, "latest_underlying_price") as quote:
            updated, changed, reason = reviewer.review_ticket(ticket)
        quote.assert_not_called()
        self.assertFalse(changed)
        self.assertEqual(updated, before)
        self.assertIn("automatic closure disabled", reason)

    def test_reviewer_preserves_all_records_and_only_writes_queue(self):
        ledger = {"updatedAt": "original", "items": [
            _ticket(expiration="2026-01-01"),
            _ticket(ticketId="historical", outcome={"status": "closed", "estimatedPnl": 42}),
        ]}
        before = copy.deepcopy(ledger)
        with patch.object(reviewer, "load_ledger", return_value=ledger), patch.object(
            reviewer, "save_outcome_report"
        ), patch.object(reviewer, "latest_underlying_price") as quote:
            report = reviewer.review_ledger()
        self.assertEqual(ledger, before)
        self.assertEqual(report["closed"], 0)
        self.assertEqual(report["ticketMutations"], 0)
        self.assertEqual(len(report["pendingOperatorReview"]), 1)
        quote.assert_not_called()
        self.assertNotIn("save_ledger", vars(reviewer))

    def test_background_ingest_previews_closed_fill_without_any_evidence_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fills.csv"
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FILL_COLUMNS)
                writer.writeheader()
                writer.writerow(_row())
            original_csv = path.read_bytes()
            ledger = {"updatedAt": "original", "items": [_ticket()]}
            before = copy.deepcopy(ledger)
            with patch.object(ingest, "TOS_FILL_LOG_WORK_FILE", path), patch.object(
                ingest, "load_ledger", return_value=ledger
            ), patch.object(ingest, "save_ledger") as save, patch.object(
                ingest, "save_ingest_report"
            ) as report_save, patch.object(ingest, "write_fill_log_template") as template:
                result = ingest.ingest_fill_log()
            save.assert_not_called()
            report_save.assert_not_called()
            template.assert_not_called()
            self.assertEqual(path.read_bytes(), original_csv)
            self.assertEqual(ledger, before)
            self.assertEqual(result["proposedClosedRows"], 1)
            self.assertEqual(result["closedRows"], 0)
            self.assertEqual(result["acceptedProgressUnits"], 0)

    def test_stale_ingest_cli_and_missing_status_report_cannot_apply(self):
        for arguments in (["ingest"], ["status"], [], ["preview", "--operator-requested"]):
            with self.subTest(arguments=arguments), tempfile.TemporaryDirectory() as directory:
                with patch("sys.argv", ["fill-ingest", *arguments]), patch.object(
                    ingest, "TOS_FILL_INGEST_TEXT_FILE", Path(directory) / "missing.txt"
                ), patch.object(ingest, "ingest_fill_log", return_value={}) as run, patch("builtins.print"):
                    ingest.main()
                run.assert_called_once_with(operator_requested=False)

    def test_operator_ingest_requires_explicit_cli_intent(self):
        with patch("sys.argv", ["fill-ingest", "ingest", "--operator-requested"]), patch.object(
            ingest, "ingest_fill_log", return_value={}
        ) as run, patch("builtins.print"):
            ingest.main()
        run.assert_called_once_with(operator_requested=True)

    def test_targeted_operator_import_does_not_apply_another_ticket(self):
        ledger = {"items": [_ticket(), _ticket(ticketId="other")]}
        with patch.object(ingest, "load_ledger", return_value=ledger), patch.object(
            ingest, "load_fill_rows", return_value=[_row(), _row(ticketId="other")]
        ), patch.object(ingest, "save_ledger") as save, patch.object(ingest, "save_ingest_report"):
            result = ingest.ingest_fill_log(operator_requested=True, ticket_id="ticket-1")
        self.assertEqual(result["closedRows"], 1)
        self.assertEqual(save.call_args.args[0]["items"][1], ledger["items"][1])


if __name__ == "__main__":
    unittest.main()
