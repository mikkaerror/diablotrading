from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_paper_outcome_completeness as completeness


def closed_staged_ticket(**overrides) -> dict:
    ticket = {
        "ticketId": "ticket-1",
        "ticker": "TEST",
        "strategy": "CALL_DEBIT_SPREAD",
        "eventId": "TEST|2026-08-01",
        "status": "paper-staged",
        "estimatedMaxLoss": 100.0,
        "riskVerdict": {"metrics": {"maxLossDollars": 100.0}},
        "outcome": {
            "status": "closed",
            "reviewedAt": "2026-08-02T10:00:00-06:00",
            "estimatedPnl": 25.0,
        },
        "paperExecution": {
            "environment": "thinkorswim-paperMoney",
            "source": "paper-fill-log",
            "contracts": 1,
            "entryPrice": 1.5,
            "exitPrice": 1.75,
            "openedAt": "2026-08-01T10:00:00-06:00",
            "closedAt": "2026-08-02T10:00:00-06:00",
            "realizedPnl": 25.0,
        },
    }
    ticket.update(overrides)
    return ticket


class PaperOutcomeCompletenessTests(unittest.TestCase):
    def test_fill_backed_closed_staged_ticket_is_audit_complete(self) -> None:
        payload = completeness.build_paper_outcome_completeness(
            {"items": [closed_staged_ticket()]}
        )

        self.assertEqual(payload["counts"]["labScorableRows"], 1)
        self.assertEqual(payload["counts"]["auditCompleteRows"], 1)
        self.assertEqual(payload["outcomes"][0]["state"], "audit-complete")
        self.assertEqual(payload["outcomes"][0]["missingFields"], [])

    def test_estimated_closed_outcome_remains_lab_scorable_but_has_provenance_debt(self) -> None:
        ticket = closed_staged_ticket(
            paperExecution=None,
            outcome={
                "status": "closed",
                "reviewedAt": "2026-08-02T10:00:00-06:00",
                "estimatedPnl": -100.0,
                "notes": "estimated from expiration intrinsic value",
            },
        )
        payload = completeness.build_paper_outcome_completeness({"items": [ticket]})

        self.assertEqual(payload["counts"]["labScorableRows"], 1)
        self.assertEqual(payload["counts"]["auditCompleteRows"], 0)
        self.assertEqual(payload["counts"]["labScorableWithProvenanceDebt"], 1)
        outcome = payload["outcomes"][0]
        self.assertEqual(outcome["state"], "lab-scorable-provenance-debt")
        self.assertIn("paperExecution.source", outcome["missingFields"])

    def test_closed_staged_ticket_without_usable_pnl_is_not_lab_scorable(self) -> None:
        ticket = closed_staged_ticket(outcome={"status": "closed", "reviewedAt": "2026-08-02"})
        payload = completeness.build_paper_outcome_completeness({"items": [ticket]})

        self.assertEqual(payload["counts"]["labScorableRows"], 0)
        self.assertEqual(payload["outcomes"][0]["state"], "closed-unscorable")

    def test_only_closed_staged_rows_are_in_contract_scope(self) -> None:
        blocked = closed_staged_ticket(status="paper-blocked")
        open_ticket = closed_staged_ticket(outcome={"status": "open"})
        payload = completeness.build_paper_outcome_completeness(
            {"items": [blocked, open_ticket]}
        )

        self.assertEqual(payload["counts"]["closedStagedRows"], 0)
        self.assertEqual(payload["outcomes"], [])

    def test_fill_intake_readiness_distinguishes_close_ready_from_incomplete_and_ignored_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fill_log = root / "inferno_tos_fill_log.csv"
            ingest_report = root / "inferno_tos_fill_ingest.json"
            with fill_log.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=completeness.FILL_LOG_COLUMNS)
                writer.writeheader()
                writer.writerow(
                    {
                        "ticketId": "ticket-ready",
                        "ticker": "TEST",
                        "strategy": "CALL_DEBIT_SPREAD",
                        "environment": "thinkorswim-paperMoney",
                        "contracts": "1",
                        "entryPrice": "1.50",
                        "exitPrice": "1.75",
                        "status": "closed",
                        "openedAt": "2026-08-01T10:00:00-06:00",
                        "closedAt": "2026-08-02T10:00:00-06:00",
                    }
                )
                writer.writerow(
                    {
                        "ticketId": "ticket-incomplete",
                        "ticker": "MISS",
                        "strategy": "CALL_DEBIT_SPREAD",
                        "environment": "thinkorswim-paperMoney",
                        "contracts": "1",
                        "entryPrice": "1.50",
                        "status": "closed",
                        "openedAt": "2026-08-01T10:00:00-06:00",
                    }
                )
                writer.writerow({"ticketId": "ticket-pending", "ticker": "WAIT", "status": "planned"})
            ingest_report.write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-08-02T11:00:00-06:00",
                        "processedRows": 3,
                        "importedRows": 0,
                        "closedRows": 0,
                        "rejectedRows": 1,
                        "unmatchedRows": [],
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(completeness, "TOS_FILL_LOG_WORK_FILE", fill_log),
                patch.object(completeness, "TOS_FILL_INGEST_FILE", ingest_report),
            ):
                payload = completeness.build_paper_outcome_completeness(
                    {"items": [closed_staged_ticket(ticketId="ticket-ready")]}
                )

        intake = payload["fillIntake"]
        self.assertTrue(intake["schemaValid"])
        self.assertEqual(intake["nonblankRows"], 3)
        self.assertEqual(intake["closedRows"], 2)
        self.assertEqual(intake["closedRowsFormatComplete"], 1)
        self.assertEqual(intake["closeReadyRows"], 1)
        self.assertEqual(intake["closedRowsMissingEvidence"], 1)
        self.assertEqual(intake["ignoredRows"], 1)
        self.assertEqual(intake["plannedStubRows"], 1)
        self.assertEqual(intake["rawStatusCounts"]["planned"], 1)
        self.assertEqual(intake["verdict"], "closed-fill-ready-for-operator-ingest")
        self.assertTrue(intake["operatorIngestNeeded"])
        self.assertFalse(intake["ingestRunsAutomaticallyFromThisAudit"])
        self.assertEqual(intake["lastIngest"]["processedRows"], 3)
        self.assertEqual(intake["lastIngest"]["rejectedRows"], 1)
        self.assertEqual(intake["closedMissingFieldCounts"]["exitPrice"], 1)
        work_items = payload["operatorWorkItems"]
        self.assertEqual(work_items[0]["kind"], "complete-paper-fill-stubs-after-actual-execution")

    def test_format_complete_closed_row_is_not_ready_without_exact_staged_ticket(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fill_log = Path(temp_dir) / "inferno_tos_fill_log.csv"
            with fill_log.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=completeness.FILL_LOG_COLUMNS)
                writer.writeheader()
                writer.writerow(
                    {
                        "ticketId": "missing-ticket",
                        "ticker": "TEST",
                        "strategy": "CALL_DEBIT_SPREAD",
                        "environment": "thinkorswim-paperMoney",
                        "contracts": "1",
                        "entryPrice": "1.50",
                        "exitPrice": "1.75",
                        "status": "closed",
                        "openedAt": "2026-08-01T10:00:00-06:00",
                        "closedAt": "2026-08-02T10:00:00-06:00",
                    }
                )
            with patch.object(completeness, "TOS_FILL_LOG_WORK_FILE", fill_log):
                payload = completeness.build_paper_outcome_completeness(
                    {"items": [closed_staged_ticket()]}
                )

        intake = payload["fillIntake"]
        self.assertEqual(intake["closedRowsFormatComplete"], 1)
        self.assertEqual(intake["closeReadyRows"], 0)
        self.assertEqual(intake["closedRowsUnmatchedTicket"], 1)
        self.assertEqual(intake["verdict"], "closed-fill-ticket-unmatched")
        self.assertFalse(intake["operatorIngestNeeded"])

    def test_planned_only_rows_are_explicit_templates_not_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fill_log = root / "inferno_tos_fill_log.csv"
            with fill_log.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=completeness.FILL_LOG_COLUMNS)
                writer.writeheader()
                writer.writerow({"ticketId": "ticket-template", "ticker": "WAIT", "status": "planned"})

            with patch.object(completeness, "TOS_FILL_LOG_WORK_FILE", fill_log):
                payload = completeness.build_paper_outcome_completeness({"items": []})

        intake = payload["fillIntake"]
        self.assertEqual(intake["plannedStubRows"], 1)
        self.assertEqual(intake["verdict"], "fill-log-stubbed-awaiting-operator-execution")
        self.assertFalse(intake["operatorIngestNeeded"])
        self.assertEqual(
            payload["operatorWorkItems"],
            [
                {
                    "kind": "complete-paper-fill-stubs-after-actual-execution",
                    "rowCount": 1,
                    "instruction": "Planned rows are templates, not evidence. Update one only after its actual paperMoney fill and keep the exact ticketId.",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
