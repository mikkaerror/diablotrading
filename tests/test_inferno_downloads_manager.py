from __future__ import annotations

"""End-to-end tests for the Downloads fill-capture path.

This module is the entry point that turns a broker/paperMoney CSV export
sitting in ~/Downloads into canonical fill-log rows the evidence loop can
score toward the 30-outcome promotion gate. It had no dedicated test
coverage, despite being on the critical path for closing paper outcomes.
These tests prove the capture works for the two supported shapes and
fails safe (quarantine / ignore / dedup) for everything else.
"""

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_downloads_manager as dm
from inferno_tos_sandbox import FILL_LOG_COLUMNS


class DownloadsCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.downloads = self.tmp / "Downloads"
        self.downloads.mkdir()
        self.fill_log = self.tmp / "fill_log.csv"
        self._seed_empty_fill_log()

        patches = {
            "TOS_FILL_LOG_WORK_FILE": self.fill_log,
            "DOWNLOADS_MANAGER_STATE_FILE": self.tmp / "state.json",
            "PROCESSED_ARCHIVE_DIR": self.tmp / "archive" / "processed",
            "QUARANTINE_ARCHIVE_DIR": self.tmp / "archive" / "quarantine",
        }
        for attr, value in patches.items():
            p = patch.object(dm, attr, value)
            p.start()
            self.addCleanup(p.stop)
        (self.tmp / "archive" / "processed").mkdir(parents=True)
        (self.tmp / "archive" / "quarantine").mkdir(parents=True)

    def _seed_empty_fill_log(self) -> None:
        with self.fill_log.open("w", newline="") as handle:
            csv.DictWriter(handle, fieldnames=FILL_LOG_COLUMNS).writeheader()

    def _write_csv(self, name: str, header: list[str], *rows: list[str]) -> Path:
        path = self.downloads / name
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for row in rows:
                writer.writerow(row)
        return path

    def _fill_rows(self) -> list[dict[str, str]]:
        with self.fill_log.open(newline="") as handle:
            return list(csv.DictReader(handle))

    def _run(self):
        return dm.import_downloads(source_dir=self.downloads, lookback_hours=99999)

    def test_captures_thinkorswim_style_order_export(self) -> None:
        """A paperMoney order export (Symbol/Qty/Price/Exec Time) is captured."""
        self._write_csv(
            "2026-07-22-AccountStatement_paperMoney_orders.csv",
            ["Exec Time", "Symbol", "Spread", "Side", "Qty", "Price", "Order Type", "Account"],
            ["2026-07-22 09:41:07", "CHKP", "CALL_DEBIT_SPREAD", "BUY", "1", "2.30", "NET_DEBIT", "paperMoney"],
        )
        report = self._run()
        self.assertEqual(report["importedFiles"], 1)
        self.assertEqual(report["importedRows"], 1)

        rows = self._fill_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticker"], "CHKP")
        self.assertEqual(rows[0]["entryPrice"], "2.30")
        # Filename carries paperMoney, so environment is inferred, not broker-import.
        self.assertEqual(rows[0]["environment"], "thinkorswim-paperMoney")

    def test_captures_canonical_fill_log_export(self) -> None:
        """A CSV already in canonical fill-log shape imports verbatim."""
        blank = {c: "" for c in FILL_LOG_COLUMNS}
        row = {
            **blank,
            "sessionDate": "2026-07-22",
            "ticketId": "aa11",
            "ticker": "CLFD",
            "strategy": "CALL_DEBIT_SPREAD",
            "expiration": "2026-08-21",
            "environment": "thinkorswim-paperMoney",
            "contracts": "1",
            "entryPrice": "1.30",
            "status": "open",
            "openedAt": "2026-07-22 09:45:00",
        }
        path = self.downloads / "tos_fill_log_export.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FILL_LOG_COLUMNS)
            writer.writeheader()
            writer.writerow(row)

        report = self._run()
        self.assertEqual(report["importedRows"], 1)
        self.assertEqual(self._fill_rows()[0]["ticker"], "CLFD")

    def test_quarantines_trading_like_but_unmapped_csv(self) -> None:
        """A file that looks trading-related but has no usable columns is quarantined, not imported."""
        self._write_csv(
            "tos_export_weird.csv",
            ["Foo", "Bar", "Baz"],
            ["1", "2", "3"],
        )
        report = self._run()
        self.assertEqual(report["importedRows"], 0)
        self.assertEqual(report["quarantinedFiles"], 1)
        self.assertEqual(len(self._fill_rows()), 0)

    def test_ignores_non_trading_csv(self) -> None:
        """An unrelated CSV is left alone."""
        self._write_csv(
            "grocery_list.csv",
            ["item", "aisle"],
            ["milk", "3"],
        )
        report = self._run()
        self.assertEqual(report["importedRows"], 0)
        self.assertEqual(report["quarantinedFiles"], 0)
        self.assertEqual(report.get("ignoredFiles"), 1)

    def test_rescanning_same_file_does_not_double_import(self) -> None:
        """Idempotency: the same export processed twice yields one row."""
        self._write_csv(
            "paperMoney_fills.csv",
            ["Exec Time", "Symbol", "Qty", "Price", "Status"],
            ["2026-07-22 09:41:07", "CHKP", "1", "2.30", "FILLED"],
        )
        first = self._run()
        second = self._run()
        self.assertEqual(first["importedRows"], 1)
        self.assertEqual(second["importedRows"], 0)
        self.assertEqual(len(self._fill_rows()), 1)


if __name__ == "__main__":
    unittest.main()
