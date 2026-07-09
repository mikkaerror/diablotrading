from __future__ import annotations

"""Tests for the earnings-history CSV importer."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

import inferno_earnings_history_import as imp


def _write_csv(path: Path, rows: list[tuple]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


class EarningsHistoryImportTests(unittest.TestCase):
    HEADER = ("ticker", "earningsDate", "impliedMovePct", "realizedAbsMovePct")

    def test_valid_import_computes_ratio_and_dedupes(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "in.csv"
            out = Path(tmp) / "out.json"
            _write_csv(csv_path, [
                self.HEADER,
                ("aapl", "2026-05-01", "8.0", "4.0"),      # ratio 0.5
                ("AAPL", "2026-05-01", "8.0", "4.0"),      # duplicate event
                ("MSFT", "2026-04-24", "5.0", "6.0"),      # ratio 1.2
            ])
            result = imp.import_csv(str(csv_path), str(out))
            recs = json.loads(out.read_text())["records"]
            payload = json.loads(out.read_text())
            self.assertEqual(len(recs), 2)  # dupe collapsed
            self.assertTrue(payload["researchOnly"])
            self.assertFalse(payload["authorityChanged"])
            self.assertFalse(payload["brokerSubmitAllowed"])
            self.assertFalse(payload["liveTradingAllowed"])
            aapl = next(r for r in recs if r["ticker"] == "AAPL")
            self.assertEqual(aapl["moveRatio"], 0.5)
            self.assertEqual(aapl["eventId"], "AAPL|2026-05-01")

    def test_missing_columns_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "bad.csv"
            _write_csv(csv_path, [("ticker", "earningsDate"), ("AAPL", "2026-05-01")])
            with self.assertRaises(ValueError):
                imp.import_csv(str(csv_path), str(Path(tmp) / "o.json"))

    def test_header_whitespace_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "in.csv"
            out = Path(tmp) / "out.json"
            _write_csv(csv_path, [
                (" ticker ", " earningsDate ", " impliedMovePct ", " realizedAbsMovePct "),
                (" aapl ", "2026-05-01", "8.0", "4.0"),
            ])
            result = imp.import_csv(str(csv_path), str(out))

        self.assertEqual(result["payload"]["summary"]["events"], 1)

    def test_bad_values_skipped_and_warned(self):
        rows = [
            self.HEADER,
            ("AAPL", "2026-05-01", "0", "4.0"),      # implied <= 0 -> skip
            ("MSFT", "", "5.0", "6.0"),                # missing date -> skip
            ("META", "05/01/2026", "5.0", "4.0"),      # invalid date -> skip
            ("NVDA", "2026-05-28", "6.0", "3.0"),      # good
        ]
        recs, warnings = imp.parse_rows([dict(zip(self.HEADER, r)) for r in rows[1:]])
        self.assertEqual([r["ticker"] for r in recs], ["NVDA"])
        self.assertGreaterEqual(len(warnings), 3)

    def test_implausible_realized_warns_but_keeps(self):
        recs, warnings = imp.parse_rows(
            [{"ticker": "X", "earningsDate": "2026-01-01",
              "impliedMovePct": "10", "realizedAbsMovePct": "91"}]
        )
        self.assertEqual(len(recs), 1)
        self.assertTrue(any(">40%" in w for w in warnings))

    def test_template_has_required_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.csv"
            imp.write_template(str(path))
            header = path.read_text().splitlines()[0].split(",")
            for col in self.HEADER:
                self.assertIn(col, header)

    def test_refuses_to_overwrite_canonical_expected_move_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "in.csv"
            _write_csv(csv_path, [
                self.HEADER,
                ("AAPL", "2026-05-01", "8.0", "4.0"),
            ])
            with self.assertRaises(ValueError):
                imp.import_csv(str(csv_path), imp.LIVE_EXPECTED_MOVE_LEDGER)


if __name__ == "__main__":
    unittest.main()
