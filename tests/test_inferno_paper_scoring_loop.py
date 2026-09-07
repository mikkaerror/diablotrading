from __future__ import annotations

"""End-to-end proof of the paper scoring loop.

Each mechanical link is unit-tested elsewhere; this proves the *seam*. It
takes a capture-template row, fills the six operator fields, writes it as a
CSV the way the operator would, imports it through the real Downloads
manager, and then runs the real fill-ingest scorer -- asserting a closed,
scored outcome comes out the far end. If canonicalization ever reshapes the
ticketId, environment, or timestamps in a way that breaks scoring, this test
fails.

Nothing real is touched: all paths are redirected to a temp directory and
the ledger writers are stubbed.
"""

import csv
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import inferno_paper_capture_template as ct
import inferno_downloads_manager as dm
import inferno_tos_fill_ingest as fi
from inferno_tos_sandbox import FILL_LOG_COLUMNS

try:  # Codex's evidence-completeness auditor (validation side of this lane)
    import inferno_paper_outcome_completeness as poc
except Exception:  # pragma: no cover - alignment test skips if module absent
    poc = None


# Keep the fixture fillable: the template drops expired staged tickets.
FUTURE_EXPIRATION = (date.today() + timedelta(days=45)).isoformat()

STAGED_CHKP = {
    "ticketId": "LOOPCHKP01",
    "ticker": "CHKP",
    "strategy": "CALL_DEBIT_SPREAD",
    "status": "paper-staged",
    "expiration": FUTURE_EXPIRATION,
    "entryCostType": "NET_DEBIT_LIMIT",
}


class PaperScoringLoopTests(unittest.TestCase):
    def test_template_to_downloads_to_scored_outcome(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        downloads = tmp / "Downloads"
        downloads.mkdir()
        fill_log = tmp / "fill_log.csv"
        with fill_log.open("w", newline="") as handle:
            csv.DictWriter(handle, fieldnames=FILL_LOG_COLUMNS).writeheader()

        # 1) Capture template for the staged ticket, then operator fills blanks.
        row = ct.build_capture_template(ledger={"items": [dict(STAGED_CHKP)]})["rows"][0]
        row.update(
            {
                "entryPrice": "2.30",
                "exitPrice": "4.10",
                "realizedPnl": "180",
                "status": "closed-win",
                "openedAt": "2026-07-25T09:41:00-06:00",
                "closedAt": "2026-07-25T14:05:00-06:00",
            }
        )
        # 2) Operator saves it as a CSV and drops it in Downloads.
        drop = downloads / "paperMoney_CHKP_closed.csv"
        with drop.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FILL_LOG_COLUMNS)
            writer.writeheader()
            writer.writerow(row)

        # 3) Real Downloads manager imports it into the fill log.
        with patch.object(dm, "TOS_FILL_LOG_WORK_FILE", fill_log), \
             patch.object(dm, "DOWNLOADS_MANAGER_STATE_FILE", tmp / "state.json"), \
             patch.object(dm, "PROCESSED_ARCHIVE_DIR", tmp / "arch" / "p"), \
             patch.object(dm, "QUARANTINE_ARCHIVE_DIR", tmp / "arch" / "q"):
            (tmp / "arch" / "p").mkdir(parents=True)
            (tmp / "arch" / "q").mkdir(parents=True)
            import_report = dm.import_downloads(source_dir=downloads, lookback_hours=99999)
        self.assertEqual(import_report["importedRows"], 1)

        # 4) Real fill-ingest scorer reads that fill log against the staged ledger.
        with patch.object(fi, "write_fill_log_template", lambda *a, **k: None), \
             patch.object(fi, "TOS_FILL_LOG_WORK_FILE", fill_log), \
             patch.object(fi, "load_ledger", return_value={"items": [dict(STAGED_CHKP)]}), \
             patch.object(fi, "save_ledger", lambda *a, **k: None), \
             patch.object(fi, "save_ingest_report", lambda *a, **k: None):
            score_report = fi.ingest_fill_log(operator_requested=True)

        # The far end: one closed, scored outcome, nothing rejected.
        self.assertEqual(score_report["closedRows"], 1, score_report.get("notes"))
        self.assertEqual(score_report["rejectedRows"], 0, score_report.get("notes"))
        self.assertEqual(score_report["unmatchedRows"], [])

    @unittest.skipIf(poc is None, "outcome-completeness auditor not present")
    def test_filled_template_reads_as_close_ready_in_codex_auditor(self) -> None:
        """Lane contract: a filled capture-template row is close-ready per the completeness auditor.

        My module generates the operator template; Codex's auditor decides what
        counts as evidence. This pins the two together so a change on either
        side that breaks the handshake is caught immediately.
        """
        tmp = Path(tempfile.mkdtemp())
        fill_log = tmp / "fill_log.csv"

        row = ct.build_capture_template(ledger={"items": [dict(STAGED_CHKP)]})["rows"][0]
        row.update(
            {
                "entryPrice": "2.30",
                "exitPrice": "4.10",
                "realizedPnl": "180",
                "status": "closed-win",
                "openedAt": "2026-07-25T09:41:00-06:00",
                "closedAt": "2026-07-25T14:05:00-06:00",
            }
        )
        with fill_log.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FILL_LOG_COLUMNS)
            writer.writeheader()
            writer.writerow(row)

        with patch.object(poc, "TOS_FILL_LOG_WORK_FILE", fill_log):
            intake = poc.fill_intake_readiness(ledger={"items": [dict(STAGED_CHKP)]})

        self.assertEqual(intake["closeReadyRows"], 1, intake)
        self.assertEqual(intake.get("closedRowsMissingEvidence", 0), 0)
        self.assertEqual(intake.get("closedRowsIdentityMismatch", 0), 0)

    def test_raw_export_without_ticketid_does_not_score(self) -> None:
        """The negative control: a TOS-style export lacking the ticketId can't score a close."""
        tmp = Path(tempfile.mkdtemp())
        downloads = tmp / "Downloads"
        downloads.mkdir()
        fill_log = tmp / "fill_log.csv"
        with fill_log.open("w", newline="") as handle:
            csv.DictWriter(handle, fieldnames=FILL_LOG_COLUMNS).writeheader()

        # A realistic TOS export: real fills, but no Inferno ticketId column.
        drop = downloads / "paperMoney_orders.csv"
        with drop.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Exec Time", "Symbol", "Strategy", "Qty", "Price", "Exit Price", "Status"])
            writer.writerow(["2026-07-25T09:41:00-06:00", "CHKP", "CALL_DEBIT_SPREAD", "1", "2.30", "4.10", "closed"])

        with patch.object(dm, "TOS_FILL_LOG_WORK_FILE", fill_log), \
             patch.object(dm, "DOWNLOADS_MANAGER_STATE_FILE", tmp / "state.json"), \
             patch.object(dm, "PROCESSED_ARCHIVE_DIR", tmp / "arch" / "p"), \
             patch.object(dm, "QUARANTINE_ARCHIVE_DIR", tmp / "arch" / "q"):
            (tmp / "arch" / "p").mkdir(parents=True)
            (tmp / "arch" / "q").mkdir(parents=True)
            dm.import_downloads(source_dir=downloads, lookback_hours=99999)

        with patch.object(fi, "write_fill_log_template", lambda *a, **k: None), \
             patch.object(fi, "TOS_FILL_LOG_WORK_FILE", fill_log), \
             patch.object(fi, "load_ledger", return_value={"items": [dict(STAGED_CHKP)]}), \
             patch.object(fi, "save_ledger", lambda *a, **k: None), \
             patch.object(fi, "save_ingest_report", lambda *a, **k: None):
            score_report = fi.ingest_fill_log(operator_requested=True)

        # No scored outcome: this is exactly why the template exists.
        self.assertEqual(score_report["closedRows"], 0)
        self.assertGreaterEqual(score_report["rejectedRows"], 1)


if __name__ == "__main__":
    unittest.main()
