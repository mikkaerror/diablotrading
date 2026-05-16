from __future__ import annotations

"""Regression tests for thinkorswim session-account detection."""

import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
