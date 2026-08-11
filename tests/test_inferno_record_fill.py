from __future__ import annotations

"""End-to-end safety tests for the short paperMoney fill-recording command."""

import csv
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import inferno_record_fill as record_fill
import inferno_tos_fill_ingest as fill_ingest
import inferno_tos_sandbox as sandbox


TICKET_ID = "1be6f96d665a730e"


def staged_ticket() -> dict:
    return {
        "ticketId": TICKET_ID,
        "ticker": "IREN",
        "strategy": "CALL_DEBIT_SPREAD",
        "status": "paper-staged",
        "entryCostType": "debit",
        "entryLimit": 2.0,
        "estimatedMaxLoss": 200.0,
        "outcome": {"status": "not-opened"},
    }


def seeded_row() -> dict[str, str]:
    return {
        "sessionDate": "2026-08-11",
        "ticketId": TICKET_ID,
        "ticker": "IREN",
        "strategy": "CALL_DEBIT_SPREAD",
        "expiration": "2026-08-28",
        "environment": "thinkorswim-paperMoney",
        "paperAccount": "paperMoney",
        "routeFamily": "defined-risk-call",
        "orderType": "LIMIT",
        "contracts": "1",
        "entryPrice": "",
        "exitPrice": "",
        "realizedPnl": "",
        "status": "planned",
        "openedAt": "",
        "closedAt": "",
        "notes": "seeded by inferno_tos_sandbox",
    }


class RecordFillTests(unittest.TestCase):
    """Prove a seed can move to open, close, and a scored outcome safely."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.fill_log = Path(self.temp_dir.name) / "inferno_tos_fill_log.csv"
        with self.fill_log.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=sandbox.FILL_LOG_COLUMNS)
            writer.writeheader()
            writer.writerow(seeded_row())
        self.state = {"ledger": {"items": [staged_ticket()]}}
        self.saved_analytics: list[dict] = []

    def _save_ledger(self, ledger: dict) -> None:
        self.state["ledger"] = ledger

    def _patches(self):
        return (
            patch.object(sandbox, "TOS_FILL_LOG_WORK_FILE", self.fill_log),
            patch.object(fill_ingest, "TOS_FILL_LOG_WORK_FILE", self.fill_log),
            patch.object(fill_ingest, "write_fill_log_template", return_value=None),
            patch.object(record_fill, "load_ledger", side_effect=lambda: self.state["ledger"]),
            patch.object(fill_ingest, "load_ledger", side_effect=lambda: self.state["ledger"]),
            patch.object(fill_ingest, "save_ledger", side_effect=self._save_ledger),
            patch.object(fill_ingest, "save_ingest_report", return_value=None),
            patch.object(record_fill, "save_performance_analytics", side_effect=self.saved_analytics.append),
        )

    def test_seed_to_open_to_close_to_scored_outcome(self) -> None:
        with ExitStack() as stack:
            for patcher in self._patches():
                stack.enter_context(patcher)
            opened = record_fill.record_fill("IREN", entry_price=2.0, contracts=1)
            self.assertEqual(opened["action"], "open")
            self.assertEqual(opened["ingest"]["openedRows"], 1)
            self.assertEqual(self.state["ledger"]["items"][0]["outcome"]["status"], "open")

            closed = record_fill.record_fill(TICKET_ID, exit_price=3.5)

        self.assertEqual(closed["action"], "closed")
        self.assertEqual(closed["ingest"]["closedRows"], 1)
        self.assertEqual(closed["scoredCount"], 1)
        self.assertEqual(self.state["ledger"]["items"][0]["outcome"]["status"], "closed")
        self.assertAlmostEqual(self.state["ledger"]["items"][0]["outcome"]["estimatedPnl"], 150.0)
        self.assertEqual(self.saved_analytics[-1]["closedMetrics"]["scoredCount"], 1)
        self.assertFalse(closed["liveTradingAllowed"])
        self.assertFalse(closed["brokerSubmitAllowed"])

        with self.fill_log.open("r", encoding="utf-8", newline="") as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual(row["ticketId"], TICKET_ID)
        self.assertEqual(row["status"], "closed")
        self.assertEqual(row["entryPrice"], "2")
        self.assertEqual(row["exitPrice"], "3.5")
        self.assertTrue(row["openedAt"].endswith("00:00") or "+" in row["openedAt"] or "-" in row["openedAt"][10:])
        self.assertTrue(row["closedAt"])

    def test_blocked_ticket_cannot_be_recorded_even_when_a_seed_row_exists(self) -> None:
        self.state["ledger"]["items"][0]["status"] = "paper-blocked"
        original = self.fill_log.read_text(encoding="utf-8")
        with ExitStack() as stack:
            for patcher in self._patches():
                stack.enter_context(patcher)
            with self.assertRaisesRegex(record_fill.RecordFillError, "no matching sandbox-seeded paper-staged ticket"):
                record_fill.record_fill(TICKET_ID, entry_price=2.0)

        self.assertEqual(self.fill_log.read_text(encoding="utf-8"), original)

    def test_exit_requires_prior_open_evidence(self) -> None:
        original = self.fill_log.read_text(encoding="utf-8")
        with ExitStack() as stack:
            for patcher in self._patches():
                stack.enter_context(patcher)
            with self.assertRaisesRegex(record_fill.RecordFillError, "exit may only be recorded after an imported open fill"):
                record_fill.record_fill(TICKET_ID, exit_price=3.5)

        self.assertEqual(self.fill_log.read_text(encoding="utf-8"), original)

    def test_nonfinite_operator_price_fails_before_any_csv_write(self) -> None:
        original = self.fill_log.read_text(encoding="utf-8")
        with ExitStack() as stack:
            for patcher in self._patches():
                stack.enter_context(patcher)
            with self.assertRaisesRegex(record_fill.RecordFillError, "finite non-negative"):
                record_fill.record_fill(TICKET_ID, entry_price=float("nan"))

        self.assertEqual(self.fill_log.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
