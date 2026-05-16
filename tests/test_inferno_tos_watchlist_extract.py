from __future__ import annotations

"""Regression tests for the TOS watchlist extractor.

Contract:
- accessibility-tree path produces ticker-shaped tokens from injected labels
- noise tokens (USD, ATR, etc.) are filtered out
- CSV-fallback path triggers only when accessibility returns no tickers
- output payload freezes the researchOnly/promotable/diagnosticOnly contract
- stage constant is stable so external readers can grep for it
"""

import csv
import io
import json
import subprocess
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

import inferno_tos_watchlist_extract as extractor


def _fake_completed_process(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["osascript", "-e", "test"], returncode=returncode, stdout=stdout, stderr=""
    )


class StageContractTests(unittest.TestCase):
    def test_stage_constant_is_research_only(self) -> None:
        self.assertTrue(extractor.WATCHLIST_EXTRACT_STAGE.endswith("research-only"))

    def test_payload_freezes_research_contract(self) -> None:
        # Build a no-op payload via injected callbacks so we don't touch the OS.
        def fake_scraper(name, runner):
            return ["NVDA"], {"labelsInspected": 1, "method": "test"}

        payload = extractor.build_extract(accessibility_scraper=fake_scraper)
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["diagnosticOnly"])
        self.assertEqual(payload["stage"], extractor.WATCHLIST_EXTRACT_STAGE)


class AccessibilityScrapeTests(unittest.TestCase):
    def test_extracts_ticker_shapes_from_labels(self) -> None:
        # AppleScript would return one label per line. Pack multiple tokens
        # per label to confirm the splitter handles separators.
        stdout = "\n".join([
            "NVDA  $850.12",
            "AVGO|$1200.45",
            "AMD,$95.10",
            "USD",          # noise
            "WORKING",      # noise
            "12345",        # not letter-leading
            "TOO_LONG_TICKER",  # over the length cap
            "BRK.B",
        ])

        def runner(_script: str) -> subprocess.CompletedProcess:
            return _fake_completed_process(stdout)

        tickers, debug = extractor._scrape_accessibility_tickers("Earnings", runner)
        self.assertIn("NVDA", tickers)
        self.assertIn("AVGO", tickers)
        self.assertIn("AMD", tickers)
        self.assertIn("BRK.B", tickers)
        self.assertNotIn("USD", tickers)
        self.assertNotIn("WORKING", tickers)
        self.assertNotIn("12345", tickers)
        self.assertEqual(debug["scriptExitCode"], 0)
        self.assertGreaterEqual(debug["labelsInspected"], 4)

    def test_handles_empty_applescript_output(self) -> None:
        def runner(_script: str) -> subprocess.CompletedProcess:
            return _fake_completed_process("")

        tickers, debug = extractor._scrape_accessibility_tickers("Earnings", runner)
        self.assertEqual(tickers, [])
        self.assertEqual(debug["labelsInspected"], 0)


class CsvFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.downloads = Path(self._tmp.name)

    def _write_csv(self, name: str, rows: list[list[str]], mtime: float | None = None) -> Path:
        path = self.downloads / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows(rows)
        if mtime is not None:
            import os as _os
            _os.utime(path, (mtime, mtime))
        return path

    def test_picks_up_recent_watchlist_csv(self) -> None:
        self._write_csv("watchlist-export.csv", [["Symbol", "Last"], ["NVDA", "850"], ["AMD", "95"]])
        tickers, debug = extractor._scan_downloads_for_csv(downloads_dir=self.downloads)
        self.assertIn("NVDA", tickers)
        self.assertIn("AMD", tickers)
        self.assertEqual(debug["csvCandidates"], 1)
        self.assertEqual(debug["method"], "downloads-csv-fallback")

    def test_skips_stale_csv(self) -> None:
        ancient = time.time() - extractor.DOWNLOADS_CSV_MAX_AGE_SECONDS - 60
        self._write_csv("watchlist-old.csv", [["NVDA"]], mtime=ancient)
        tickers, debug = extractor._scan_downloads_for_csv(downloads_dir=self.downloads)
        self.assertEqual(tickers, [])
        self.assertEqual(debug["csvCandidates"], 0)

    def test_missing_directory_does_not_crash(self) -> None:
        missing = self.downloads / "definitely-not-here"
        tickers, debug = extractor._scan_downloads_for_csv(downloads_dir=missing)
        self.assertEqual(tickers, [])
        self.assertIn("error", debug)


class BuildExtractTests(unittest.TestCase):
    def test_accessibility_path_chosen_when_tickers_present(self) -> None:
        def fake_scraper(_name, _runner):
            return ["NVDA", "AVGO"], {"method": "test", "labelsInspected": 5}

        def fail_scanner():
            raise AssertionError("fallback should not run when accessibility succeeds")

        payload = extractor.build_extract(
            accessibility_scraper=fake_scraper,
            downloads_scanner=fail_scanner,
        )
        self.assertEqual(payload["source"], "tos-accessibility")
        self.assertEqual(payload["verdict"], "accessibility-ok")
        self.assertFalse(payload["fallbackUsed"])
        self.assertEqual(payload["tickers"], ["NVDA", "AVGO"])

    def test_csv_fallback_triggers_when_accessibility_empty(self) -> None:
        def empty_scraper(_name, _runner):
            return [], {"method": "test", "labelsInspected": 0}

        def fake_scanner():
            return ["AMD"], {"method": "downloads-csv-fallback", "csvCandidates": 1, "chosenFile": "/tmp/wl.csv", "fileAgeSeconds": 12}

        payload = extractor.build_extract(
            accessibility_scraper=empty_scraper,
            downloads_scanner=fake_scanner,
        )
        self.assertEqual(payload["source"], "tos-csv-export")
        self.assertEqual(payload["verdict"], "csv-fallback-ok")
        self.assertTrue(payload["fallbackUsed"])
        self.assertEqual(payload["tickers"], ["AMD"])

    def test_no_tickers_anywhere_returns_no_tickers_verdict(self) -> None:
        def empty_scraper(_name, _runner):
            return [], {"method": "test", "labelsInspected": 0}

        def empty_scanner():
            return [], {"method": "downloads-csv-fallback", "csvCandidates": 0}

        payload = extractor.build_extract(
            accessibility_scraper=empty_scraper,
            downloads_scanner=empty_scanner,
        )
        self.assertEqual(payload["verdict"], "no-tickers")
        self.assertEqual(payload["tickers"], [])

    def test_scraper_exception_is_isolated(self) -> None:
        def broken_scraper(_name, _runner):
            raise RuntimeError("accessibility tree locked")

        def fake_scanner():
            return ["NVDA"], {"method": "downloads-csv-fallback", "csvCandidates": 1}

        payload = extractor.build_extract(
            accessibility_scraper=broken_scraper,
            downloads_scanner=fake_scanner,
        )
        self.assertEqual(payload["source"], "tos-csv-export")
        self.assertIn("accessibility tree locked", payload["accessibilityError"])


class TextRenderTests(unittest.TestCase):
    def test_text_contains_expected_sections(self) -> None:
        def fake_scraper(_name, _runner):
            return ["NVDA"], {"method": "test", "labelsInspected": 1}

        payload = extractor.build_extract(accessibility_scraper=fake_scraper)
        text = extractor.extract_text(payload)
        self.assertIn("Watchlist:", text)
        self.assertIn("Verdict:", text)
        self.assertIn("Tickers:", text)
        self.assertIn("Narrative:", text)
        self.assertIn("- NVDA", text)


class WriteInputSlotTests(unittest.TestCase):
    def test_skips_write_when_no_tickers(self) -> None:
        payload = {"tickers": [], "source": "none"}
        result = extractor.write_input_slot(payload)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
