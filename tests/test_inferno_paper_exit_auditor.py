from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_paper_exit_auditor as auditor


class PaperExitAuditorTests(unittest.TestCase):
    """Verify the paper exit audit stays deterministic and honest."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.fill_log = self.root / "inferno_tos_fill_log.csv"
        self.ledger_file = self.root / "inferno_paper_execution_ledger.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_fill_log(self, rows: list[dict[str, str]]) -> None:
        with self.fill_log.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
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
                ],
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    @patch.object(auditor, "TOS_FILL_LOG_WORK_FILE", new_callable=lambda: Path("/dev/null"))
    def test_clean_when_no_open_positions(self, _mock_fill_log: Path) -> None:
        """No open positions should yield a clean exit memo."""
        with patch.object(auditor, "load_open_ledger_tickets", return_value=[]), patch.object(
            auditor, "load_fill_rows", return_value=[]
        ):
            payload = auditor.build_audit()
        self.assertEqual(payload["verdict"], "clean")
        self.assertEqual(payload["counts"]["openLedgerTickets"], 0)

    def test_close_today_when_expired_open_ticket_exists(self) -> None:
        """Expired open paper tickets should be escalated immediately."""
        ticket = {
            "ticker": "TEST",
            "ticketId": "abc123",
            "strategy": "LONG_STRADDLE",
            "tradeDate": "2026-05-01",
            "expiration": "2026-05-05",
            "paperExecution": {"status": "open", "openedAt": "2026-05-01T09:30:00-10:00"},
            "outcome": {"status": "open"},
        }
        with patch.object(auditor, "load_open_ledger_tickets", return_value=[ticket]), patch.object(
            auditor, "load_fill_rows", return_value=[]
        ), patch.object(auditor, "local_now") as now_mock:
            now_mock.return_value = __import__("datetime").datetime.fromisoformat("2026-05-06T10:00:00-10:00")
            payload = auditor.build_audit()
        self.assertEqual(payload["verdict"], "close-today")
        self.assertEqual(payload["counts"]["closeNow"], 1)

    def test_reconcile_when_open_fill_row_has_no_matching_ticket(self) -> None:
        """Orphan open fill rows should trigger reconciliation."""
        row = {
            "sessionDate": "2026-05-06",
            "ticketId": "orphan-ticket",
            "ticker": "ORPH",
            "strategy": "LONG_STRADDLE",
            "expiration": "2026-05-09",
            "environment": "thinkorswim-paperMoney",
            "paperAccount": "paperMoney",
            "routeFamily": "straddle",
            "orderType": "LIMIT",
            "contracts": "1",
            "entryPrice": "1.25",
            "exitPrice": "",
            "realizedPnl": "",
            "status": "open",
            "openedAt": "2026-05-06T09:31:00-10:00",
            "closedAt": "",
            "notes": "",
        }
        with patch.object(auditor, "load_open_ledger_tickets", return_value=[]), patch.object(
            auditor, "load_fill_rows", return_value=[row]
        ):
            payload = auditor.build_audit()
        self.assertEqual(payload["verdict"], "reconcile-open-rows")
        self.assertEqual(payload["counts"]["orphanOpenFillRows"], 1)


if __name__ == "__main__":
    unittest.main()
