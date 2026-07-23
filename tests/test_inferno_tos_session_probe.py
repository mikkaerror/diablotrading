from __future__ import annotations

"""Regression tests for thinkorswim session-account detection."""

import json
import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

import inferno_tos_session_probe as probe_module
from inferno_tos_session_probe import (
    extract_account_suffix_candidates,
    infer_account_mode,
    probe_tos_session_via_applescript,
    summarize_session,
    visible_tos_windows,
)


class TOSSessionProbeTests(unittest.TestCase):
    """Verify desktop session safety classification stays conservative."""

    def test_infer_account_mode_marks_login_only(self) -> None:
        mode, evidence = infer_account_mode({"windowNames": ["Logon to thinkorswim"]})
        self.assertEqual(mode, "login-only")
        self.assertTrue(evidence)

    def test_infer_account_mode_marks_paper_when_explicit(self) -> None:
        mode, _ = infer_account_mode(
            {
                "windowNames": ["Paper@thinkorswim [build 1991]"],
            }
        )
        self.assertEqual(mode, "paper")

    def test_infer_account_mode_marks_paper_from_button_label(self) -> None:
        mode, _ = infer_account_mode(
            {
                "windowNames": ["Main@thinkorswim"],
                "labeledButtons": [{"label": "paperMoney"}],
            }
        )
        self.assertEqual(mode, "paper")

    def test_infer_account_mode_marks_live_when_explicit(self) -> None:
        mode, _ = infer_account_mode(
            {
                "windowNames": ["Main@thinkorswim"],
                "labeledButtons": [{"label": "Live Trading"}],
            }
        )
        self.assertEqual(mode, "live")

    def test_infer_account_mode_marks_live_from_account_statement_text(self) -> None:
        mode, evidence = infer_account_mode(
            {
                "windowNames": ["Main@thinkorswim"],
                "staticTexts": [{"label": "Statement for account 11111234SCHW (Individual)"}],
            }
        )
        self.assertEqual(mode, "live")
        self.assertTrue(any("statement for account" in item.lower() for item in evidence))

    def test_summary_includes_account_suffix_when_known(self) -> None:
        summary = summarize_session(
            {
                "ok": True,
                "matchedProcessName": "thinkorswim",
                "mainWindowPresent": True,
                "currentPanel": "Monitor",
                "currentPanelSafety": "safe",
                "accountMode": "paper",
                "monitorSubpanel": None,
                "currentTabGroups": [],
            }
        )
        self.assertIn("account paper", summary)

    def test_extract_account_suffix_candidates_prefers_account_like_labels(self) -> None:
        suffixes = extract_account_suffix_candidates(
            {
                "selectedMonitorSubtabs": ["Statement for account 1234"],
                "windowNames": ["Main@thinkorswim [build 1991]"],
            }
        )
        self.assertEqual(suffixes, ["1234"])

    def test_extract_account_suffix_candidates_reads_static_texts(self) -> None:
        suffixes = extract_account_suffix_candidates(
            {
                "staticTexts": [{"label": "Account: 11111234SCHW (Individual)"}],
                "windowNames": ["Main@thinkorswim [build 1991]"],
            }
        )
        self.assertEqual(suffixes, ["11111234"])

    @patch("inferno_tos_session_probe.subprocess.run")
    def test_visible_tos_windows_parses_swift_window_inventory(self, mock_run) -> None:
        mock_run.return_value = CompletedProcess(
            args=[],
            returncode=0,
            stdout="27713\tjava-arm\tMain@thinkorswim [build 1991]\t0\n533\tthinkorswim\tLogon to thinkorswim\t0\n",
            stderr="",
        )

        windows = visible_tos_windows()

        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0]["pid"], 27713)
        self.assertEqual(windows[0]["windowName"], "Main@thinkorswim [build 1991]")

    @patch("inferno_tos_session_probe.run_osascript")
    @patch("inferno_tos_session_probe.applescript_list")
    @patch(
        "inferno_tos_session_probe.visible_tos_windows",
        return_value=[{"pid": 27713, "ownerName": "thinkorswim", "windowName": "Main@thinkorswim [build 1991]", "layer": 0}],
    )
    def test_probe_via_applescript_prefers_frontmost_tos_process(
        self,
        _mock_visible_tos_windows,
        mock_applescript_list,
        mock_run_osascript,
    ) -> None:
        def list_side_effect(script: str) -> list[str]:
            if "name of every application process" in script:
                return ["Finder", "java-arm"]
            if "first application process whose frontmost is true to set _items to name of windows" in script:
                return ["Main@thinkorswim [build 1991]"]
            if "role of every UI element of window 1" in script:
                return ["AXSplitGroup"]
            if "role of every UI element of UI element 1 of window 1" in script:
                return ["AXTabGroup"]
            if "description of every UI element of UI element 1 of window 1" in script:
                return ["Monitor"]
            if "value of every UI element of UI element 1 of window 1" in script:
                return [""]
            return []

        mock_applescript_list.side_effect = list_side_effect
        mock_run_osascript.return_value = CompletedProcess(args=[], returncode=0, stdout="java-arm\n", stderr="")

        payload = probe_tos_session_via_applescript()

        self.assertEqual(payload["matchedProcessName"], "thinkorswim")
        self.assertTrue(payload["mainWindowPresent"])
        self.assertEqual(payload["currentPanel"], "Monitor")

    @patch("inferno_tos_session_probe.run_osascript")
    @patch("inferno_tos_session_probe.applescript_list")
    @patch(
        "inferno_tos_session_probe.visible_tos_windows",
        return_value=[{"pid": 90752, "ownerName": "thinkorswim", "windowName": "Logon to thinkorswim", "layer": 0}],
    )
    def test_probe_via_applescript_uses_visible_login_window_when_workspace_missing(
        self,
        _mock_visible_tos_windows,
        mock_applescript_list,
        mock_run_osascript,
    ) -> None:
        def list_side_effect(script: str) -> list[str]:
            if "name of every application process" in script:
                return ["Finder", "Codex"]
            return []

        mock_applescript_list.side_effect = list_side_effect
        mock_run_osascript.return_value = CompletedProcess(args=[], returncode=0, stdout="Codex\n", stderr="")

        payload = probe_tos_session_via_applescript()

        self.assertEqual(payload["matchedProcessName"], "thinkorswim")
        self.assertEqual(payload["windowNames"], ["Logon to thinkorswim"])
        self.assertFalse(payload["mainWindowPresent"])


class TOSSessionProbeCompletenessTests(unittest.TestCase):
    """A failed observation must never be published as a negative finding."""

    @staticmethod
    def _timed_out_jxa(_script: str) -> CompletedProcess:
        return CompletedProcess(args=[], returncode=124, stdout="", stderr="JXA probe timed out")

    def test_timed_out_probe_is_marked_incomplete(self) -> None:
        """The fallback sees unrelated apps only, so the window layer is unknown."""
        fallback = {
            "frontmostApp": "Finder",
            "matchedProcessName": None,
            # Every foreground app on the machine; none of them are TOS.
            "visibleProcessNames": ["Finder", "Notes", "Google Chrome"],
            "windowNames": [],
            "mainWindowPresent": False,
            "currentPanel": None,
            "currentPanelSafety": "unknown",
        }

        with patch.object(probe_module, "run_jxa", side_effect=self._timed_out_jxa), \
             patch.object(probe_module, "probe_tos_session_via_applescript", return_value=fallback), \
             patch.object(probe_module, "save_session_probe"):
            report = probe_module.probe_tos_session()

        self.assertEqual(report["returncode"], 124)
        self.assertFalse(report["probeComplete"])
        # The reason the primary probe failed must survive the fallback.
        self.assertIn("timed out", report["probeIncompleteReason"])
        self.assertFalse(report["mainWindowPresent"])

    def test_fallback_that_sees_tos_windows_is_complete(self) -> None:
        """Real window evidence still counts as a completed observation."""
        fallback = {
            "frontmostApp": "thinkorswim",
            "matchedProcessName": "thinkorswim",
            "visibleProcessNames": ["Finder", "thinkorswim"],
            "windowNames": ["Main@thinkorswim"],
            "mainWindowPresent": True,
            "currentPanel": "Monitor",
            "currentPanelSafety": "safe",
        }

        with patch.object(probe_module, "run_jxa", side_effect=self._timed_out_jxa), \
             patch.object(probe_module, "probe_tos_session_via_applescript", return_value=fallback), \
             patch.object(probe_module, "save_session_probe"):
            report = probe_module.probe_tos_session()

        self.assertTrue(report["probeComplete"])
        self.assertIsNone(report["probeIncompleteReason"])
        self.assertTrue(report["mainWindowPresent"])

    def test_jxa_timeout_is_env_overridable(self) -> None:
        """Operator can raise the probe budget on the host without editing code."""
        self.assertEqual(probe_module._probe_timeout("MISSING_VAR_XYZ", 5.0), 5.0)
        with patch.dict(probe_module.os.environ, {"INFERNO_TOS_JXA_TIMEOUT": "12"}):
            self.assertEqual(probe_module._probe_timeout("INFERNO_TOS_JXA_TIMEOUT", 5.0), 12.0)
        # Garbage and non-positive values fall back to the default, never 0.
        with patch.dict(probe_module.os.environ, {"INFERNO_TOS_JXA_TIMEOUT": "nonsense"}):
            self.assertEqual(probe_module._probe_timeout("INFERNO_TOS_JXA_TIMEOUT", 5.0), 5.0)
        with patch.dict(probe_module.os.environ, {"INFERNO_TOS_JXA_TIMEOUT": "0"}):
            self.assertEqual(probe_module._probe_timeout("INFERNO_TOS_JXA_TIMEOUT", 5.0), 5.0)

    def test_missing_osascript_fails_closed_without_raising(self) -> None:
        """A stripped PATH / non-macOS host must not crash the daily loop."""
        real_run = probe_module.subprocess.run

        def fake_run(cmd, *args, **kwargs):
            argv = cmd if isinstance(cmd, (list, tuple)) else [cmd]
            if argv and argv[0] in {"osascript", "swift"}:
                raise FileNotFoundError(f"{argv[0]}: No such file or directory")
            return real_run(cmd, *args, **kwargs)

        with patch.object(probe_module.subprocess, "run", side_effect=fake_run), \
             patch.object(probe_module, "save_session_probe"):
            report = probe_module.probe_tos_session()

        # No exception, and the desk knows it could not observe the window.
        self.assertFalse(report["probeComplete"])
        self.assertFalse(report["mainWindowPresent"])
        self.assertEqual(report["returncode"], 127)

    def test_successful_primary_probe_is_complete(self) -> None:
        """No fallback means the JXA traversal answered for itself."""
        payload = json.dumps(
            {
                "frontmostApp": "thinkorswim",
                "matchedProcessName": "thinkorswim",
                "visibleProcessNames": ["thinkorswim"],
                "windowNames": ["Main@thinkorswim"],
                "mainWindowPresent": True,
                "currentPanel": "Monitor",
                "currentPanelSafety": "safe",
            }
        )

        with patch.object(
            probe_module,
            "run_jxa",
            side_effect=lambda _script: CompletedProcess(args=[], returncode=0, stdout=payload, stderr=""),
        ), patch.object(probe_module, "save_session_probe"):
            report = probe_module.probe_tos_session()

        self.assertTrue(report["probeComplete"])
        # fallbackProbe is only written when the fallback actually runs.
        self.assertIsNone(report.get("fallbackProbe"))


if __name__ == "__main__":
    unittest.main()
