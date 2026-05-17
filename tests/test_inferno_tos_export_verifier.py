from __future__ import annotations

"""Regression tests for guarded thinkorswim export verification."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from inferno_tos_export_verifier import main, verify_export_bridge


class TOSExportVerifierTests(unittest.TestCase):
    """Verify the export verifier stays safe around hidden-window states."""

    @patch("inferno_tos_export_verifier.save_export_verifier_report")
    @patch(
        "inferno_tos_export_verifier.route_to_account_statement",
        return_value={"ok": True, "status": "dry-run", "message": "route dry-run only; no clicks executed"},
    )
    @patch(
        "inferno_tos_export_verifier.probe_tos_session",
        side_effect=[
            {
                "ok": True,
                "message": "no visible thinkorswim window detected",
                "summary": "no visible thinkorswim window detected",
                "matchedProcessName": None,
                "mainWindowPresent": False,
                "currentPanel": None,
                "currentPanelSafety": "unknown",
                "accountMode": "unknown",
                "accountEvidence": [],
                "accountSuffixCandidates": [],
                "windowNames": [],
                "currentTabGroups": [],
            },
            {
                "ok": True,
                "message": "main window live via thinkorswim | current panel Monitor | safety safe | account live",
                "summary": "main window live via thinkorswim | current panel Monitor | safety safe | account live",
                "matchedProcessName": "thinkorswim",
                "mainWindowPresent": True,
                "currentPanel": "Monitor",
                "currentPanelSafety": "safe",
                "monitorSubpanel": "Account Statement",
                "accountMode": "live",
                "accountEvidence": ["Statement for account 11111234SCHW (Individual)"],
                "accountSuffixCandidates": ["11111234"],
                "windowNames": ["Main@thinkorswim [build 1991]"],
                "currentTabGroups": [],
            },
        ],
    )
    @patch("inferno_tos_export_verifier.frontmost_app_name", return_value=(True, "java-arm"))
    @patch("inferno_tos_export_verifier.app_running", return_value=True)
    @patch("inferno_tos_export_verifier.launch_agent_loaded", side_effect=[False, True])
    @patch("inferno_tos_export_verifier.parse_shortcut")
    @patch("inferno_tos_export_verifier.build_applescript", return_value='keystroke "e" using {command down, shift down}')
    def test_verify_export_bridge_uses_reprobe_before_manual_check(
        self,
        _build_script_mock: object,
        _parse_shortcut_mock: object,
        _launch_agent_mock: object,
        _app_running_mock: object,
        _frontmost_app_mock: object,
        _probe_mock: object,
        _route_mock: object,
        _save_mock: object,
    ) -> None:
        """A transient visibility miss should self-heal without enabling recovery."""
        with patch("inferno_tos_export_verifier.TOS_ALLOW_LIVE_READONLY", True), patch(
            "inferno_tos_export_verifier.TOS_ALLOWED_ACCOUNT_SUFFIXES",
            ("1234",),
        ):
            report = verify_export_bridge(require_enabled=False, allow_recovery=False)
        self.assertEqual(report["verdict"], "ready-live-readonly")
        self.assertEqual(report["sessionRecovery"][0]["step"], "stabilize-reprobe")
        self.assertFalse(report["allowRecovery"])

    @patch("inferno_tos_export_verifier.save_export_verifier_report")
    @patch("inferno_tos_export_verifier.route_to_account_statement")
    @patch(
        "inferno_tos_export_verifier.probe_tos_session",
        return_value={
            "ok": True,
            "message": "no visible thinkorswim window detected",
            "summary": "no visible thinkorswim window detected",
            "matchedProcessName": None,
            "mainWindowPresent": False,
            "currentPanel": None,
            "currentPanelSafety": "unknown",
            "accountMode": "unknown",
            "accountEvidence": [],
            "windowNames": [],
            "currentTabGroups": [],
        },
    )
    @patch("inferno_tos_export_verifier.bring_tos_frontmost")
    @patch("inferno_tos_export_verifier.recover_tos_window")
    @patch("inferno_tos_export_verifier.frontmost_app_name", return_value=(True, "java-arm"))
    @patch("inferno_tos_export_verifier.app_running", return_value=True)
    @patch("inferno_tos_export_verifier.launch_agent_loaded", side_effect=[False, True])
    @patch("inferno_tos_export_verifier.parse_shortcut")
    @patch("inferno_tos_export_verifier.build_applescript", return_value='keystroke "e" using {command down, shift down}')
    def test_verify_export_bridge_background_mode_stays_observation_only(
        self,
        _build_script_mock: object,
        _parse_shortcut_mock: object,
        _launch_agent_mock: object,
        _app_running_mock: object,
        _frontmost_app_mock: object,
        recover_mock: object,
        bring_frontmost_mock: object,
        _probe_mock: object,
        _route_mock: object,
        _save_mock: object,
    ) -> None:
        report = verify_export_bridge(require_enabled=False, allow_recovery=False)
        self.assertEqual(report["verdict"], "manual-check")
        self.assertFalse(report["allowRecovery"])
        self.assertEqual(report["sessionRecovery"][0]["step"], "stabilize-reprobe")
        self.assertFalse(report["sessionRecovery"][0]["ok"])
        self.assertIn("observation-only", report["message"])
        bring_frontmost_mock.assert_not_called()
        recover_mock.assert_not_called()

    @patch("inferno_tos_export_verifier.save_export_verifier_report")
    @patch(
        "inferno_tos_export_verifier.route_to_account_statement",
        return_value={"ok": True, "status": "dry-run", "message": "route dry-run only; no clicks executed"},
    )
    @patch(
        "inferno_tos_export_verifier.probe_tos_session",
        side_effect=[
            {
                "ok": True,
                "message": "no visible thinkorswim window detected",
                "summary": "no visible thinkorswim window detected",
                "matchedProcessName": None,
                "mainWindowPresent": False,
                "currentPanel": None,
                "currentPanelSafety": "unknown",
                "accountMode": "unknown",
                "accountEvidence": [],
                "windowNames": [],
                "currentTabGroups": [],
            },
            {
                "ok": True,
                "message": "main window live via thinkorswim | current panel Monitor | safety safe | account paper",
                "summary": "main window live via thinkorswim | current panel Monitor | safety safe | account paper",
                "matchedProcessName": "thinkorswim",
                "mainWindowPresent": True,
                "currentPanel": "Monitor",
                "currentPanelSafety": "safe",
                "monitorSubpanel": "Activity and Positions",
                "accountMode": "paper",
                "accountEvidence": ["Paper@thinkorswim [build 1991]"],
                "windowNames": ["Paper@thinkorswim [build 1991]"],
                "currentTabGroups": [],
            },
        ],
    )
    @patch(
        "inferno_tos_export_verifier.bring_tos_frontmost",
        return_value={"ok": True, "frontmostProcess": "java-arm", "stderr": "", "returncode": 0},
    )
    @patch("inferno_tos_export_verifier.recover_tos_window")
    @patch("inferno_tos_export_verifier.frontmost_app_name", return_value=(True, "java-arm"))
    @patch("inferno_tos_export_verifier.app_running", return_value=True)
    @patch("inferno_tos_export_verifier.launch_agent_loaded", side_effect=[False, True])
    @patch("inferno_tos_export_verifier.parse_shortcut")
    @patch("inferno_tos_export_verifier.build_applescript", return_value='keystroke "e" using {command down, shift down}')
    def test_verify_export_bridge_recovers_hidden_window_via_frontmost(
        self,
        _build_script_mock: object,
        _parse_shortcut_mock: object,
        _launch_agent_mock: object,
        _app_running_mock: object,
        _frontmost_app_mock: object,
        recover_mock: object,
        _bring_frontmost_mock: object,
        _probe_mock: object,
        _route_mock: object,
        _save_mock: object,
    ) -> None:
        with patch("inferno_tos_export_verifier.TOS_EXPORT_AUTOMATION_ENABLED", True):
            report = verify_export_bridge(require_enabled=False, allow_recovery=True)
        self.assertEqual(report["verdict"], "ready")
        self.assertTrue(report["allowRecovery"])
        self.assertEqual(report["sessionProbe"]["accountMode"], "paper")
        self.assertTrue(report["sessionProbe"]["mainWindowPresent"])
        self.assertEqual(report["sessionRecovery"][0]["step"], "stabilize-reprobe")
        _bring_frontmost_mock.assert_not_called()
        recover_mock.assert_not_called()

    @patch("inferno_tos_export_verifier.TOS_ALLOW_LIVE_READONLY", True)
    @patch("inferno_tos_export_verifier.TOS_ALLOWED_ACCOUNT_SUFFIXES", ("1234",))
    @patch("inferno_tos_export_verifier.save_export_verifier_report")
    @patch(
        "inferno_tos_export_verifier.route_to_account_statement",
        return_value={"ok": True, "status": "dry-run", "message": "route dry-run only; no clicks executed"},
    )
    @patch(
        "inferno_tos_export_verifier.probe_tos_session",
        return_value={
            "ok": True,
            "message": "main window live via thinkorswim | current panel Monitor | safety safe | account live",
            "summary": "main window live via thinkorswim | current panel Monitor | safety safe | account live",
            "matchedProcessName": "thinkorswim",
            "mainWindowPresent": True,
            "currentPanel": "Monitor",
            "currentPanelSafety": "safe",
            "monitorSubpanel": "Activity and Positions",
            "accountMode": "live",
            "accountEvidence": ["Statement for account 1234"],
            "accountSuffixCandidates": ["1234"],
            "windowNames": ["Main@thinkorswim [build 1991]"],
            "currentTabGroups": [],
        },
    )
    @patch("inferno_tos_export_verifier.frontmost_app_name", return_value=(True, "java-arm"))
    @patch("inferno_tos_export_verifier.app_running", return_value=True)
    @patch("inferno_tos_export_verifier.launch_agent_loaded", side_effect=[False, True])
    @patch("inferno_tos_export_verifier.parse_shortcut")
    @patch("inferno_tos_export_verifier.build_applescript", return_value='keystroke "e" using {command down, shift down}')
    def test_verify_export_bridge_allows_live_readonly_when_suffix_matches(
        self,
        _build_script_mock: object,
        _parse_shortcut_mock: object,
        _launch_agent_mock: object,
        _app_running_mock: object,
        _frontmost_app_mock: object,
        _probe_mock: object,
        _route_mock: object,
        _save_mock: object,
    ) -> None:
        report = verify_export_bridge(require_enabled=False, allow_recovery=False)
        self.assertEqual(report["verdict"], "ready-live-readonly")
        self.assertIn("1234", report["message"])

    @patch("inferno_tos_export_verifier.TOS_ALLOW_LIVE_READONLY", True)
    @patch("inferno_tos_export_verifier.TOS_ALLOWED_ACCOUNT_SUFFIXES", ("1234",))
    @patch("inferno_tos_export_verifier.save_export_verifier_report")
    @patch(
        "inferno_tos_export_verifier.route_to_account_statement",
        return_value={"ok": True, "status": "dry-run", "message": "route dry-run only; no clicks executed"},
    )
    @patch(
        "inferno_tos_export_verifier.probe_tos_session",
        return_value={
            "ok": True,
            "message": "main window live via thinkorswim | current panel Monitor | safety safe | account live",
            "summary": "main window live via thinkorswim | current panel Monitor | safety safe | account live",
            "matchedProcessName": "thinkorswim",
            "mainWindowPresent": True,
            "currentPanel": "Monitor",
            "currentPanelSafety": "safe",
            "monitorSubpanel": "Account Statement",
            "accountMode": "live",
            "accountEvidence": ["Statement for account 11111234SCHW (Individual)"],
            "accountSuffixCandidates": ["11111234"],
            "windowNames": ["Main@thinkorswim [build 1991]"],
            "currentTabGroups": [],
        },
    )
    @patch("inferno_tos_export_verifier.frontmost_app_name", return_value=(True, "java-arm"))
    @patch("inferno_tos_export_verifier.app_running", return_value=True)
    @patch("inferno_tos_export_verifier.launch_agent_loaded", side_effect=[False, True])
    @patch("inferno_tos_export_verifier.parse_shortcut")
    @patch("inferno_tos_export_verifier.build_applescript", return_value='keystroke "e" using {command down, shift down}')
    def test_verify_export_bridge_allows_live_readonly_when_suffix_is_account_tail(
        self,
        _build_script_mock: object,
        _parse_shortcut_mock: object,
        _launch_agent_mock: object,
        _app_running_mock: object,
        _frontmost_app_mock: object,
        _probe_mock: object,
        _route_mock: object,
        _save_mock: object,
    ) -> None:
        report = verify_export_bridge(require_enabled=False, allow_recovery=False)
        self.assertEqual(report["verdict"], "ready-live-readonly")

    @patch("inferno_tos_export_verifier.export_verifier_report_text", return_value="ok\n")
    @patch(
        "inferno_tos_export_verifier.verify_export_bridge",
        return_value={"verdict": "ready-live-readonly"},
    )
    @patch("inferno_tos_export_verifier.parse_args", return_value=SimpleNamespace(command="run", require_enabled=False, allow_recovery=False))
    def test_main_treats_live_readonly_verdict_as_success(
        self,
        _parse_args_mock: object,
        _verify_mock: object,
        _render_mock: object,
    ) -> None:
        """The CLI exit code should stay healthy when the live read-only guard passes."""
        self.assertEqual(main(), 0)


if __name__ == "__main__":
    unittest.main()
