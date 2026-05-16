from __future__ import annotations

"""Regression tests for the watchlist ingest module.

Contract:
- preview mode never writes the sheet
- apply mode refuses without --confirm or INFERNO_WATCHLIST_CONFIRM=1
- input validation surfaces every error, not just the first
- ticker shape is enforced (uppercase, alphanumeric + dot/dash)
- duplicates are flagged
- diff against universe split tickers into newAdds / alreadyKnown
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import inferno_watchlist_ingest as ingest


def _write_input(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class LoadInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.input = Path(self._tmp.name) / "input.json"

    def test_missing_file_returns_error(self) -> None:
        tickers, source, errors = ingest.load_watchlist_input(self.input)
        self.assertEqual(tickers, [])
        self.assertEqual(source, "missing")
        self.assertEqual(len(errors), 1)

    def test_uppercases_and_dedupes(self) -> None:
        _write_input(self.input, {"tickers": ["nvda", "AMD", "nvda", "AVGO"]})
        tickers, _source, errors = ingest.load_watchlist_input(self.input)
        self.assertEqual(tickers, ["NVDA", "AMD", "AVGO"])
        # Duplicate is flagged but other tickers still load.
        self.assertTrue(any("duplicate" in err.lower() for err in errors))

    def test_invalid_ticker_shape_is_rejected(self) -> None:
        _write_input(self.input, {"tickers": ["NVDA", "123!", "OK"]})
        tickers, _source, errors = ingest.load_watchlist_input(self.input)
        self.assertIn("NVDA", tickers)
        self.assertIn("OK", tickers)
        self.assertNotIn("123!", tickers)
        self.assertTrue(any("123!" in err for err in errors))

    def test_cap_truncates_with_error(self) -> None:
        too_many = [f"T{i}" for i in range(ingest.MAX_TICKERS_PER_INGEST + 5)]
        _write_input(self.input, {"tickers": too_many})
        tickers, _source, errors = ingest.load_watchlist_input(self.input)
        self.assertEqual(len(tickers), ingest.MAX_TICKERS_PER_INGEST)
        self.assertTrue(any("cap is" in err.lower() for err in errors))


class DiffTests(unittest.TestCase):
    def test_diff_splits_into_new_and_known(self) -> None:
        diff = ingest.diff_against_universe(
            ["NVDA", "AVGO", "AMD"], ["AMD", "TSLA"]
        )
        self.assertEqual(diff["newAdds"], ["NVDA", "AVGO"])
        self.assertEqual(diff["alreadyKnown"], ["AMD"])

    def test_empty_universe_makes_everything_new(self) -> None:
        diff = ingest.diff_against_universe(["NVDA", "AMD"], [])
        self.assertEqual(diff["newAdds"], ["NVDA", "AMD"])
        self.assertEqual(diff["alreadyKnown"], [])


class RunIngestTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.input = Path(self._tmp.name) / "input.json"
        self.universe = lambda: ["AMD", "TSLA"]
        self.writer_calls: list[list[str]] = []

        def _writer(tickers: list[str]) -> tuple[bool, str]:
            self.writer_calls.append(list(tickers))
            return True, f"wrote {len(tickers)}"

        self.writer = _writer

    def test_preview_never_writes(self) -> None:
        _write_input(self.input, {"tickers": ["NVDA", "AMD"]})
        payload = ingest.run_ingest(
            mode="preview", confirm=True,
            universe_loader=self.universe,
            apply_writer=self.writer,
            input_path=self.input,
        )
        self.assertEqual(payload["verdict"], "preview-only")
        self.assertFalse(payload["applied"])
        self.assertEqual(self.writer_calls, [])

    def test_apply_without_confirm_refuses(self) -> None:
        _write_input(self.input, {"tickers": ["NVDA"]})
        payload = ingest.run_ingest(
            mode="apply", confirm=False,
            universe_loader=self.universe,
            apply_writer=self.writer,
            input_path=self.input,
        )
        self.assertEqual(payload["verdict"], "apply-blocked")
        self.assertFalse(payload["applied"])
        self.assertEqual(self.writer_calls, [])

    def test_apply_with_confirm_writes(self) -> None:
        _write_input(self.input, {"tickers": ["NVDA", "AMD"]})
        payload = ingest.run_ingest(
            mode="apply", confirm=True,
            universe_loader=self.universe,
            apply_writer=self.writer,
            input_path=self.input,
        )
        self.assertEqual(payload["verdict"], "applied")
        self.assertTrue(payload["applied"])
        # Only NVDA is new; AMD is already in the universe.
        self.assertEqual(self.writer_calls, [["NVDA"]])

    def test_input_errors_block_apply(self) -> None:
        _write_input(self.input, {"tickers": ["NVDA", "123!"]})
        payload = ingest.run_ingest(
            mode="apply", confirm=True,
            universe_loader=self.universe,
            apply_writer=self.writer,
            input_path=self.input,
        )
        self.assertEqual(payload["verdict"], "input-errors")
        self.assertEqual(self.writer_calls, [])

    def test_empty_input_yields_empty_verdict(self) -> None:
        _write_input(self.input, {"tickers": []})
        payload = ingest.run_ingest(
            mode="preview", confirm=False,
            universe_loader=self.universe,
            apply_writer=self.writer,
            input_path=self.input,
        )
        self.assertEqual(payload["verdict"], "empty-input")

    def test_no_op_when_every_ticker_already_known(self) -> None:
        _write_input(self.input, {"tickers": ["AMD"]})
        payload = ingest.run_ingest(
            mode="apply", confirm=True,
            universe_loader=self.universe,
            apply_writer=self.writer,
            input_path=self.input,
        )
        self.assertTrue(payload["applied"])
        self.assertIn("no-op", payload["applyMessage"])
        self.assertEqual(self.writer_calls, [])


class RenderTests(unittest.TestCase):
    def test_text_renderer_includes_each_section(self) -> None:
        payload = ingest.build_ingest_report(
            tickers=["NVDA", "AMD"],
            source="manual",
            errors=[],
            diff={"newAdds": ["NVDA"], "alreadyKnown": ["AMD"]},
            mode="preview",
            applied=False,
            apply_message="",
        )
        rendered = ingest.ingest_text(payload)
        self.assertIn("Watchlist Ingest", rendered)
        self.assertIn("Mode:", rendered)
        self.assertIn("Verdict:", rendered)
        self.assertIn("Reminders:", rendered)


class SheetWriterFallbackTests(unittest.TestCase):
    """Direct-sheet writer should fall back to the staged file when the
    gspread import or sheet open fails, without crashing the ingest.
    """

    def test_default_writer_uses_stage_when_disabled(self) -> None:
        import os
        prior = os.environ.get("INFERNO_WATCHLIST_SHEET_DISABLED")
        os.environ["INFERNO_WATCHLIST_SHEET_DISABLED"] = "1"
        try:
            ok, msg = ingest._default_apply_writer(["NVDA"])
        finally:
            if prior is None:
                os.environ.pop("INFERNO_WATCHLIST_SHEET_DISABLED", None)
            else:
                os.environ["INFERNO_WATCHLIST_SHEET_DISABLED"] = prior
        # We don't assert ok=True (it depends on writable disk) — only that
        # the message says we hit the staged-file path.
        self.assertIn("staged", msg)

    def test_sheet_writer_falls_back_on_import_error(self) -> None:
        # When `inferno_config` / `morning_inferno_pipeline` aren't importable
        # in the test sandbox, the sheet writer should still return
        # (True/False, message) — never raise. Patch the lazy import to raise.
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "morning_inferno_pipeline":
                raise ImportError("simulated missing")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = fake_import
        try:
            ok, msg = ingest._sheet_apply_writer(["NVDA"])
        finally:
            builtins.__import__ = real_import
        self.assertIn("sheet-writer-unavailable", msg)


if __name__ == "__main__":
    unittest.main()
