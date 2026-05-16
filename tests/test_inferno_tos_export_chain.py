from __future__ import annotations

"""Regression tests for the TOS export chain diagnostic.

Contract:
- researchOnly / promotable hard-pinned
- ready when every step passes
- blocked + firstFailure populated when any step fails
- short-circuit: once a step fails its downstream steps are SKIPPED
- the text renderer covers each section
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import inferno_tos_export_chain as chain


def _good_probe() -> dict:
    return {
        "ok": True,
        "summary": "main window live via thinkorswim",
        "mainWindowPresent": True,
        "currentPanel": "Monitor",
        "currentPanelSafety": "safe",
        "accountMode": "live",
        "accountSuffixCandidates": ["1234"],
        "windowNames": ["Main@thinkorswim"],
    }


def _good_route() -> dict:
    return {"ok": True, "message": "route dry-run only; no clicks executed"}


def _good_builder(*_args, **_kwargs) -> str:
    return "tell application 'foo' to activate"


def _good_parser(_shortcut: str) -> tuple[str, list[str]]:
    return "e", ["command down", "shift down"]


def _make_kwargs(tmp_dir: Path, **overrides):
    """Build the canonical happy-path kwarg set, with overrides."""
    # The chain's app-installed step checks Path.exists(); create a stub
    # path that will resolve as installed so the happy-path tests don't
    # depend on a real thinkorswim.app being on the sandbox filesystem.
    fake_app = tmp_dir / "thinkorswim.app"
    fake_app.mkdir(exist_ok=True)
    defaults = {
        "app_path": fake_app,
        "process_check": lambda _name: True,
        "accessibility_check": lambda: (True, "java-arm"),
        "session_probe_fn": _good_probe,
        "ui_route_fn": lambda **_kw: _good_route(),
        "applescript_builder": _good_builder,
        "shortcut_parser": _good_parser,
        "downloads_scan_dir": tmp_dir,
    }
    defaults.update(overrides)
    return defaults


class ChainHappyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_dir = Path(self._tmp.name)
        self._live_flag = mock.patch.object(chain, "TOS_ALLOW_LIVE_READONLY", True)
        self._suffixes = mock.patch.object(chain, "TOS_ALLOWED_ACCOUNT_SUFFIXES", ("1234",))
        self._live_flag.start()
        self._suffixes.start()
        self.addCleanup(self._live_flag.stop)
        self.addCleanup(self._suffixes.stop)

    def test_research_only_and_stage(self) -> None:
        payload = chain.build_chain_report(**_make_kwargs(self.tmp_dir))
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertEqual(payload["stage"], chain.CHAIN_STAGE)

    def test_all_steps_pass_yields_ready(self) -> None:
        payload = chain.build_chain_report(**_make_kwargs(self.tmp_dir))
        self.assertEqual(payload["verdict"], "ready")
        self.assertEqual(payload["failCount"], 0)
        self.assertEqual(payload["skipCount"], 0)
        self.assertIsNone(payload["firstFailure"])
        for step in payload["steps"]:
            self.assertEqual(step["status"], "pass", step)


class ChainFailurePropagationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_dir = Path(self._tmp.name)
        self._live_flag = mock.patch.object(chain, "TOS_ALLOW_LIVE_READONLY", True)
        self._suffixes = mock.patch.object(chain, "TOS_ALLOWED_ACCOUNT_SUFFIXES", ("1234",))
        self._live_flag.start()
        self._suffixes.start()
        self.addCleanup(self._live_flag.stop)
        self.addCleanup(self._suffixes.stop)

    def test_app_not_running_short_circuits_downstream(self) -> None:
        kwargs = _make_kwargs(self.tmp_dir, process_check=lambda _name: False)
        payload = chain.build_chain_report(**kwargs)
        self.assertEqual(payload["verdict"], "blocked")
        self.assertEqual(payload["firstFailure"], "app-running")
        # Downstream session-probe steps should be skipped.
        statuses = {step["name"]: step["status"] for step in payload["steps"]}
        self.assertEqual(statuses["main-window-present"], "skipped")
        self.assertEqual(statuses["panel-safe"], "skipped")
        self.assertEqual(statuses["account-authorized"], "skipped")
        self.assertEqual(statuses["ui-route-dry-run"], "skipped")

    def test_accessibility_failure_marks_step(self) -> None:
        kwargs = _make_kwargs(self.tmp_dir,
                              accessibility_check=lambda: (False, "permission denied"))
        payload = chain.build_chain_report(**kwargs)
        access = next(s for s in payload["steps"] if s["name"] == "accessibility-ok")
        self.assertEqual(access["status"], "fail")
        self.assertIn("permission denied", access["detail"])
        self.assertEqual(payload["firstFailure"], "accessibility-ok")

    def test_unsafe_panel_short_circuits_route(self) -> None:
        unsafe_probe = {
            **_good_probe(),
            "currentPanelSafety": "unsafe",
            "currentPanel": "Trade",
        }
        kwargs = _make_kwargs(self.tmp_dir, session_probe_fn=lambda: unsafe_probe)
        payload = chain.build_chain_report(**kwargs)
        statuses = {step["name"]: step["status"] for step in payload["steps"]}
        self.assertEqual(statuses["panel-safe"], "fail")
        self.assertEqual(statuses["ui-route-dry-run"], "skipped")

    def test_unauthorized_account_blocks(self) -> None:
        bad_probe = {**_good_probe(), "accountSuffixCandidates": ["9999"]}
        kwargs = _make_kwargs(self.tmp_dir, session_probe_fn=lambda: bad_probe)
        payload = chain.build_chain_report(**kwargs)
        statuses = {step["name"]: step["status"] for step in payload["steps"]}
        self.assertEqual(statuses["account-authorized"], "fail")
        self.assertEqual(statuses["ui-route-dry-run"], "skipped")

    def test_ui_route_failure_does_not_block_shortcut_or_applescript(self) -> None:
        kwargs = _make_kwargs(self.tmp_dir,
                              ui_route_fn=lambda **_kw: {"ok": False, "message": "drifted"})
        payload = chain.build_chain_report(**kwargs)
        # ui-route-dry-run fails but shortcut + applescript steps still run.
        statuses = {step["name"]: step["status"] for step in payload["steps"]}
        self.assertEqual(statuses["ui-route-dry-run"], "fail")
        self.assertEqual(statuses["shortcut-valid"], "pass")
        self.assertEqual(statuses["applescript-builds"], "pass")

    def test_invalid_shortcut_is_attributed(self) -> None:
        def _bad_parser(_s: str):
            raise ValueError("unsupported modifier")
        kwargs = _make_kwargs(self.tmp_dir, shortcut_parser=_bad_parser)
        payload = chain.build_chain_report(**kwargs)
        shortcut = next(s for s in payload["steps"] if s["name"] == "shortcut-valid")
        self.assertEqual(shortcut["status"], "fail")
        self.assertIn("unsupported modifier", shortcut["detail"])

    def test_ingest_path_missing_is_attributed(self) -> None:
        kwargs = _make_kwargs(self.tmp_dir, downloads_scan_dir=self.tmp_dir / "missing")
        payload = chain.build_chain_report(**kwargs)
        ingest = next(s for s in payload["steps"] if s["name"] == "ingest-ready")
        self.assertEqual(ingest["status"], "fail")


class ChainTextRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_dir = Path(self._tmp.name)
        self._live_flag = mock.patch.object(chain, "TOS_ALLOW_LIVE_READONLY", True)
        self._suffixes = mock.patch.object(chain, "TOS_ALLOWED_ACCOUNT_SUFFIXES", ("1234",))
        self._live_flag.start()
        self._suffixes.start()
        self.addCleanup(self._live_flag.stop)
        self.addCleanup(self._suffixes.stop)

    def test_text_renderer_includes_each_section(self) -> None:
        payload = chain.build_chain_report(**_make_kwargs(self.tmp_dir))
        rendered = chain.chain_text(payload)
        self.assertIn("TOS Export Chain", rendered)
        self.assertIn("Verdict:", rendered)
        self.assertIn("Steps:", rendered)
        self.assertIn("Reminders:", rendered)
        # Every named step appears in the rendered output.
        for step_name in chain.CHAIN_STEPS:
            self.assertIn(step_name, rendered)


if __name__ == "__main__":
    unittest.main()
