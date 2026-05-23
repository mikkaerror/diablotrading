from __future__ import annotations

"""Regression tests for Inferno automation guardrails.

These tests focus on the highest-risk automation primitives:
shortcut parsing, session summarization, and fail-closed UI routing.
They intentionally avoid live broker windows and instead validate the
logic we rely on before any desktop automation is allowed to move.
"""

import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from inferno_tos_export_bridge import (
    applescript_keystroke,
    build_applescript,
    build_dump_account_applescript,
    parse_shortcut,
)
from inferno_tos_export_bridge import run_export_bridge
from inferno_config import local_now
from inferno_tos_session_probe import summarize_session
from inferno_tos_ui_route import monitor_account_statement_visible, preferred_center, recover_tos_window, route_to_account_statement


class ExportShortcutTests(unittest.TestCase):
    """Verify keyboard shortcut parsing stays deterministic."""

    def setUp(self) -> None:
        """Keep export-bridge tests independent from the operator's local mode.

        We patch both the automation enabled flag and the app path. The
        path patch points at the repo root (which always exists) so the
        production `app_path.exists()` guard inside `run_export_bridge`
        does not early-exit on test hosts that don't have thinkorswim
        installed at the default location. The guard's contract is
        preserved -- tests are simply handing it a path that's actually
        there, not removing the check.
        """
        self._export_enabled_patch = patch(
            "inferno_tos_export_bridge.TOS_EXPORT_AUTOMATION_ENABLED",
            True,
        )
        self._export_enabled_patch.start()
        self.addCleanup(self._export_enabled_patch.stop)

        # Path(__file__).resolve().parent is tests/, .parent.parent is repo root.
        existing_path = Path(__file__).resolve().parent.parent
        self._app_path_patch = patch(
            "inferno_tos_export_bridge.TOS_APP_PATH",
            existing_path,
        )
        self._app_path_patch.start()
        self.addCleanup(self._app_path_patch.stop)

    def test_parse_shortcut_keeps_key_and_modifiers(self) -> None:
        """A standard command-shift shortcut should parse cleanly."""
        key, modifiers = parse_shortcut("command+shift+e")
        self.assertEqual(key, "e")
        self.assertEqual(modifiers, ["command down", "shift down"])

    def test_applescript_keystroke_renders_expected_command(self) -> None:
        """Shortcut rendering should stay stable for export automation."""
        self.assertEqual(
            applescript_keystroke("command+shift+e"),
            'keystroke "e" using {command down, shift down}',
        )

    def test_export_applescript_attaches_only_to_running_tos(self) -> None:
        """The export shortcut script must not launch or activate TOS by app path."""
        script = build_applescript(Path("/Applications/thinkorswim.app"), "command+shift+e", 0.1, 0.2)
        self.assertNotIn('tell application "/Applications/thinkorswim.app" to activate', script)
        self.assertNotIn("open -a", script)
        self.assertIn("no existing thinkorswim process found", script)
        self.assertIn("application process targetProcessName", script)

    def test_dump_account_applescript_attaches_only_to_running_tos(self) -> None:
        """The Dump Account click script should fail closed unless the process exists."""
        script = build_dump_account_applescript(Path("/Applications/thinkorswim.app"), "thinkorswim", 14, 82, 26, 0.2)
        self.assertNotIn("to activate", script)
        self.assertNotIn("open -a", script)
        self.assertIn('exists application process "thinkorswim"', script)
        self.assertIn("set frontmost to true", script)

    def test_monitor_account_statement_visible_accepts_statement_header_signal(self) -> None:
        """Statement header visibility should count as an Account Statement win."""
        self.assertTrue(
            monitor_account_statement_visible(
                {
                    "monitorSubpanel": "Activity and Positions",
                    "selectedMonitorSubtabs": ["Statement for account 11111234SCHW (Individual)"],
                    "labeledButtons": [],
                    "staticTexts": [],
                }
            )
        )

    @patch("inferno_tos_export_bridge.save_export_report")
    @patch(
        "inferno_tos_export_bridge.route_to_account_statement",
        return_value={"ok": True, "status": "dry-run", "message": "route dry-run only; no clicks executed"},
    )
    def test_export_bridge_dry_run_never_requests_window_recovery(
        self,
        route_mock,
        _save_mock,
    ) -> None:
        """Export dry runs should use the live window only and never request app recovery."""
        report = run_export_bridge(dry_run=True)
        self.assertTrue(report["ok"])
        route_mock.assert_called_once_with(dry_run=True, allow_recovery=False)

    @patch("inferno_tos_export_bridge.save_export_report")
    @patch("inferno_tos_export_bridge.load_prior_export_report", return_value={})
    @patch(
        "inferno_tos_export_bridge.recent_artifact_markers",
        side_effect=[set(), {('/Users/tester/Downloads/tos-export.csv', 1234, 99)}],
    )
    @patch("inferno_tos_export_bridge.read_clipboard_text", side_effect=["", ""])
    @patch("inferno_tos_export_bridge.run_applescript", return_value=type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    @patch(
        "inferno_tos_export_bridge.probe_tos_session",
        return_value={
            "summary": "main window live via thinkorswim | current panel Monitor/Account Statement | safety safe | account paper",
            "matchedProcessName": "thinkorswim",
            "currentPanel": "Monitor",
            "monitorSubpanel": "Account Statement",
            "splitGroupIndex": 26,
            "monitorGroupIndex": 82,
            "labeledButtons": [{"label": "Dump Account", "index": 14}],
        },
    )
    @patch(
        "inferno_tos_export_bridge.route_to_account_statement",
        return_value={"ok": True, "status": "account-statement-routed", "message": "routed thinkorswim into Monitor > Account Statement"},
    )
    def test_export_bridge_live_trigger_uses_existing_window_only(
        self,
        route_mock,
        _probe_mock,
        _run_applescript_mock,
        _clipboard_mock,
        _recent_markers_mock,
        _prior_mock,
        _save_mock,
    ) -> None:
        """Live export triggers should route within the current session without reopening TOS."""
        report = run_export_bridge(dry_run=False)
        self.assertTrue(report["ok"])
        self.assertTrue(report["artifactDetected"])
        self.assertEqual(report["status"], "triggered")
        route_mock.assert_called_once_with(dry_run=False, allow_recovery=False)

    @patch("inferno_tos_export_bridge.save_export_report")
    @patch(
        "inferno_tos_export_bridge.load_prior_export_report",
        return_value={"generatedAt": local_now().isoformat(), "status": "triggered"},
    )
    @patch("inferno_tos_export_bridge.route_to_account_statement")
    def test_export_bridge_respects_cooldown_before_triggering_again(
        self,
        route_mock,
        _prior_mock,
        _save_mock,
    ) -> None:
        """Repeated export requests should fail closed into a cooldown instead of spamming TOS."""
        report = run_export_bridge(dry_run=False)
        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "cooldown-skipped")
        self.assertGreater(report["cooldownRemainingSeconds"], 0)
        route_mock.assert_not_called()

    @patch("inferno_tos_export_bridge.save_export_report")
    @patch("inferno_tos_export_bridge.load_prior_export_report", return_value={})
    @patch("inferno_tos_export_bridge.recent_artifact_markers", side_effect=[set(), set()])
    @patch("inferno_tos_export_bridge.read_clipboard_text", side_effect=["", ""])
    @patch("inferno_tos_export_bridge.run_applescript", return_value=type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    @patch(
        "inferno_tos_export_bridge.scrape_account_statement",
        return_value={"ok": False, "message": "statement scrape unavailable", "positions": []},
    )
    @patch(
        "inferno_tos_export_bridge.probe_tos_session",
        return_value={
            "summary": "main window live via thinkorswim | current panel Monitor/Account Statement | safety safe | account paper",
            "matchedProcessName": "thinkorswim",
            "currentPanel": "Monitor",
            "monitorSubpanel": "Account Statement",
            "splitGroupIndex": 26,
            "monitorGroupIndex": 82,
            "labeledButtons": [{"label": "Dump Account", "index": 14}],
        },
    )
    @patch(
        "inferno_tos_export_bridge.route_to_account_statement",
        return_value={"ok": True, "status": "account-statement-routed", "message": "routed thinkorswim into Monitor > Account Statement"},
    )
    def test_export_bridge_flags_missing_download_artifact_after_trigger(
        self,
        route_mock,
        _probe_mock,
        _scrape_mock,
        _run_applescript_mock,
        _clipboard_mock,
        _recent_markers_mock,
        _prior_mock,
        _save_mock,
    ) -> None:
        """Shortcut success alone is not enough; the bridge should report missing CSV evidence."""
        report = run_export_bridge(dry_run=False)
        self.assertTrue(report["ok"])
        self.assertFalse(report["artifactDetected"])
        self.assertEqual(report["status"], "triggered-no-artifact")
        route_mock.assert_called_once_with(dry_run=False, allow_recovery=False)

    @patch("inferno_tos_export_bridge.save_export_report")
    @patch("inferno_tos_export_bridge.load_prior_export_report", return_value={})
    @patch(
        "inferno_tos_export_bridge.recent_artifact_markers",
        side_effect=[set(), {('/Users/tester/Downloads/tos-export.csv', 1234, 99)}],
    )
    @patch("inferno_tos_export_bridge.read_clipboard_text", side_effect=["", ""])
    @patch("inferno_tos_export_bridge.run_applescript", return_value=type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    @patch(
        "inferno_tos_export_bridge.probe_tos_session",
        return_value={
            "summary": "main window live via thinkorswim | current panel Monitor/Account Statement | safety safe | account live",
            "matchedProcessName": "thinkorswim",
            "currentPanel": "Monitor",
            "monitorSubpanel": "Account Statement",
            "splitGroupIndex": 26,
            "monitorGroupIndex": 82,
            "labeledButtons": [{"label": "Dump Account", "index": 14}],
        },
    )
    @patch(
        "inferno_tos_export_bridge.route_to_account_statement",
        return_value={"ok": True, "status": "account-statement-routed", "message": "routed thinkorswim into Monitor > Account Statement"},
    )
    def test_export_bridge_prefers_dump_account_button_when_visible(
        self,
        route_mock,
        _probe_mock,
        run_applescript_mock,
        _clipboard_mock,
        _recent_markers_mock,
        _prior_mock,
        _save_mock,
    ) -> None:
        """Account Statement exports should prefer the explicit Dump Account control."""
        report = run_export_bridge(dry_run=False)
        self.assertEqual(report["triggerMethod"], "dump-account-button")
        invoked_script = run_applescript_mock.call_args.args[0]
        self.assertIn("click UI element 14 of UI element 82 of UI element 26 of window 1", invoked_script)
        route_mock.assert_called_once_with(dry_run=False, allow_recovery=False)

    @patch("inferno_tos_export_bridge.save_export_report")
    @patch("inferno_tos_export_bridge.load_prior_export_report", return_value={})
    @patch(
        "inferno_tos_export_bridge.scrape_account_statement",
        return_value={
            "ok": True,
            "message": "statement scraped from the live Account Statement pane",
            "positions": [{"symbol": "FLR"}],
            "accountMode": "live",
            "netLiquidatingValue": "$571.89",
        },
    )
    @patch("inferno_tos_export_bridge.persist_clipboard_export", return_value=type("P", (), {"name": "account_statement_export_20260508-230000.txt", "stat": lambda self: type('S', (), {'st_size': 2048})(), "__str__": lambda self: "/tmp/account_statement_export_20260508-230000.txt"})())
    @patch("inferno_tos_export_bridge.recent_artifact_markers", side_effect=[set(), set()])
    @patch(
        "inferno_tos_export_bridge.read_clipboard_text",
        side_effect=[
            "",
            "Statement for account 11111234SCHW (Individual)\nCash & Sweep Vehicle\nTrade History\nAccount Summary",
        ],
    )
    @patch("inferno_tos_export_bridge.run_applescript", return_value=type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    @patch(
        "inferno_tos_export_bridge.probe_tos_session",
        return_value={
            "summary": "main window live via thinkorswim | current panel Monitor/Account Statement | safety safe | account live",
            "matchedProcessName": "thinkorswim",
            "currentPanel": "Monitor",
            "monitorSubpanel": "Account Statement",
            "splitGroupIndex": 26,
            "monitorGroupIndex": 82,
            "labeledButtons": [{"label": "Dump Account", "index": 14}],
        },
    )
    @patch(
        "inferno_tos_export_bridge.route_to_account_statement",
        return_value={"ok": True, "status": "account-statement-routed", "message": "routed thinkorswim into Monitor > Account Statement"},
    )
    def test_export_bridge_treats_clipboard_statement_as_valid_artifact(
        self,
        route_mock,
        _probe_mock,
        _run_applescript_mock,
        _clipboard_mock,
        _recent_markers_mock,
        _persist_mock,
        _statement_mock,
        _prior_mock,
        _save_mock,
    ) -> None:
        """Account dumps copied to the clipboard should still count as export evidence."""
        report = run_export_bridge(dry_run=False)
        self.assertTrue(report["ok"])
        self.assertTrue(report["artifactDetected"])
        self.assertEqual(report["status"], "triggered")
        self.assertEqual(report["newArtifacts"][0]["source"], "clipboard")
        route_mock.assert_called_once_with(dry_run=False, allow_recovery=False)

    @patch("inferno_tos_export_bridge.save_export_report")
    @patch("inferno_tos_export_bridge.load_prior_export_report", return_value={})
    @patch(
        "inferno_tos_export_bridge.scrape_account_statement",
        return_value={
            "ok": True,
            "message": "statement scraped from the live Account Statement pane",
            "positions": [{"symbol": "FLR"}, {"symbol": "GDS"}],
            "accountMode": "live",
            "netLiquidatingValue": "$571.89",
        },
    )
    @patch("inferno_tos_export_bridge.recent_artifact_markers", side_effect=[set(), set()])
    @patch("inferno_tos_export_bridge.read_clipboard_text", side_effect=["", ""])
    @patch("inferno_tos_export_bridge.run_applescript", return_value=type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    @patch(
        "inferno_tos_export_bridge.probe_tos_session",
        return_value={
            "summary": "main window live via thinkorswim | current panel Monitor/Account Statement | safety safe | account live",
            "matchedProcessName": "thinkorswim",
            "currentPanel": "Monitor",
            "monitorSubpanel": "Account Statement",
            "splitGroupIndex": 26,
            "monitorGroupIndex": 82,
            "labeledButtons": [{"label": "Dump Account", "index": 14}],
        },
    )
    @patch(
        "inferno_tos_export_bridge.route_to_account_statement",
        return_value={"ok": True, "status": "account-statement-routed", "message": "routed thinkorswim into Monitor > Account Statement"},
    )
    def test_export_bridge_uses_statement_scrape_when_file_and_clipboard_are_empty(
        self,
        route_mock,
        _probe_mock,
        _run_applescript_mock,
        _clipboard_mock,
        _recent_markers_mock,
        statement_mock,
        _prior_mock,
        _save_mock,
    ) -> None:
        """The bridge should still emit a usable artifact when TOS refuses file export."""
        report = run_export_bridge(dry_run=False)
        self.assertTrue(report["ok"])
        self.assertTrue(report["artifactDetected"])
        self.assertEqual(report["status"], "triggered")
        self.assertTrue(any(item["source"] == "statement-scrape" for item in report["newArtifacts"]))
        statement_mock.assert_called_once_with(route_if_needed=False)
        route_mock.assert_called_once_with(dry_run=False, allow_recovery=False)


class SessionSummaryTests(unittest.TestCase):
    """Verify operator-facing session summaries stay truthful."""

    def test_monitor_subpanel_appears_in_summary(self) -> None:
        """Monitor summaries should include the active subpanel when known."""
        report = {
            "ok": True,
            "matchedProcessName": "thinkorswim",
            "mainWindowPresent": True,
            "currentPanel": "Monitor",
            "currentPanelSafety": "safe",
            "monitorSubpanel": "Account Statement",
        }
        summary = summarize_session(report)
        self.assertIn("Monitor/Account Statement", summary)
        self.assertIn("safety safe", summary)


class UiRouteTests(unittest.TestCase):
    """Verify the guarded TOS route helper fails closed and succeeds cleanly."""

    def test_preferred_center_returns_accessibility_center_for_label(self) -> None:
        """Dynamic accessibility centers should win when the label is present."""
        point = preferred_center(
            [
                {"label": "Order Entry", "center": [100, 50]},
                {"label": "Monitor", "center": [240, 60]},
            ],
            "Monitor",
        )
        self.assertEqual(point, (240, 60))

    @patch("inferno_tos_ui_route.save_ui_route_report")
    @patch("inferno_tos_ui_route.capture_route_screenshot", return_value="/tmp/no-window.png")
    @patch(
        "inferno_tos_ui_route.probe_tos_session",
        return_value={
            "summary": "no visible thinkorswim window detected",
            "currentPanel": None,
            "currentPanelSafety": "unknown",
            "monitorSubpanel": None,
            "mainWindowPresent": False,
        },
    )
    def test_route_fails_closed_when_window_missing(
        self,
        probe_mock,
        screenshot_mock,
        save_mock,
    ) -> None:
        """The route helper should stop immediately when the main window is gone."""
        report = route_to_account_statement(dry_run=True)
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "no-window")
        self.assertIn("main window is not visible", report["message"])
        probe_mock.assert_called()
        screenshot_mock.assert_called_once()
        save_mock.assert_called_once()

    @patch("inferno_tos_ui_route.time.sleep")
    @patch("inferno_tos_ui_route.save_ui_route_report")
    @patch("inferno_tos_ui_route.capture_route_screenshot", return_value="/tmp/reprobe-ok.png")
    @patch(
        "inferno_tos_ui_route.probe_tos_session",
        side_effect=[
            {
                "summary": "no visible thinkorswim window detected",
                "currentPanel": None,
                "currentPanelSafety": "unknown",
                "monitorSubpanel": None,
                "mainWindowPresent": False,
            },
            {
                "summary": "main window live via thinkorswim | current panel Monitor/Account Statement | safety safe",
                "currentPanel": "Monitor",
                "currentPanelSafety": "safe",
                "monitorSubpanel": "Account Statement",
                "mainWindowPresent": True,
            },
        ],
    )
    @patch(
        "inferno_tos_ui_route.bring_tos_frontmost",
        return_value={"ok": True, "frontmostProcess": "java-arm", "stderr": "", "returncode": 0},
    )
    def test_route_dry_run_uses_observation_only_reprobe_before_failing(
        self,
        _frontmost_mock,
        probe_mock,
        screenshot_mock,
        save_mock,
        _sleep_mock,
    ) -> None:
        """A transient hidden-window probe should recover without reopening TOS."""
        report = route_to_account_statement(dry_run=True, allow_recovery=False)
        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "dry-run")
        self.assertEqual(report["steps"][0]["name"], "initial-reprobe")
        self.assertEqual(probe_mock.call_count, 2)
        screenshot_mock.assert_called_once()
        save_mock.assert_called_once()

    @patch("inferno_tos_ui_route.save_ui_route_report")
    @patch("inferno_tos_ui_route.capture_route_screenshot", return_value="/tmp/no-window.png")
    @patch(
        "inferno_tos_ui_route.recover_tos_window",
        return_value={"ok": False, "stdout": "", "stderr": "", "returncode": 0, "sessionSummary": "no window"},
    )
    @patch(
        "inferno_tos_ui_route.probe_tos_session",
        return_value={
            "summary": "no visible thinkorswim window detected",
            "currentPanel": None,
            "currentPanelSafety": "unknown",
            "monitorSubpanel": None,
            "mainWindowPresent": False,
        },
    )
    def test_route_only_recovers_window_when_explicitly_allowed(
        self,
        probe_mock,
        recover_mock,
        screenshot_mock,
        save_mock,
    ) -> None:
        """Window recovery should stay opt-in so background lanes never spawn new TOS windows."""
        report = route_to_account_statement(dry_run=True, allow_recovery=True)
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "no-window")
        self.assertTrue(report["allowRecovery"])
        probe_mock.assert_called()
        recover_mock.assert_called_once()
        screenshot_mock.assert_called_once()
        save_mock.assert_called_once()

    @patch("inferno_tos_ui_route.time.sleep")
    @patch(
        "inferno_tos_ui_route.probe_tos_session",
        return_value={"summary": "no visible thinkorswim window detected", "mainWindowPresent": False},
    )
    @patch("inferno_tos_ui_route.run_command")
    def test_recover_tos_window_never_launches_tos(
        self,
        run_command_mock,
        _probe_mock,
        _sleep_mock,
    ) -> None:
        """Attach-only recovery must never call macOS open or any shell command."""
        report = recover_tos_window()
        self.assertFalse(report["ok"])
        self.assertEqual(report["returncode"], 1)
        self.assertIn("reopen disabled", report["stderr"])
        run_command_mock.assert_not_called()

    @patch("inferno_tos_ui_route.time.sleep")
    @patch(
        "inferno_tos_ui_route.probe_tos_session",
        return_value={
            "summary": "main window live via thinkorswim | current panel Monitor/Account Statement | safety safe",
            "mainWindowPresent": True,
        },
    )
    @patch("inferno_tos_ui_route.run_command")
    def test_recover_tos_window_can_attach_when_window_is_visible(
        self,
        run_command_mock,
        _probe_mock,
        _sleep_mock,
    ) -> None:
        """Attach-only recovery may pass when the existing window becomes visible."""
        report = recover_tos_window()
        self.assertTrue(report["ok"])
        self.assertEqual(report["returncode"], 0)
        self.assertEqual(report["stderr"], "")
        run_command_mock.assert_not_called()

    @patch("inferno_tos_ui_route.time.sleep")
    @patch("inferno_tos_ui_route.save_ui_route_report")
    @patch("inferno_tos_ui_route.capture_route_screenshot", return_value="/tmp/route-ok.png")
    @patch(
        "inferno_tos_ui_route.dismiss_transient_overlay",
        return_value={"ok": True, "stderr": "", "returncode": 0},
    )
    @patch(
        "inferno_tos_ui_route.click_point",
        side_effect=[
            {"ok": True, "point": [580, 88], "stdout": "", "stderr": "", "returncode": 0},
        ],
    )
    @patch(
        "inferno_tos_ui_route.bring_tos_frontmost",
        return_value={"ok": True, "frontmostProcess": "java-arm", "stderr": "", "returncode": 0},
    )
    @patch(
        "inferno_tos_ui_route.probe_tos_session",
        side_effect=[
            {
                "summary": "main window live via thinkorswim | current panel MarketWatch | safety safe",
                "currentPanel": "MarketWatch",
                "currentPanelSafety": "safe",
                "monitorSubpanel": None,
                "mainWindowPresent": True,
            },
            {
                "summary": "main window live via thinkorswim | current panel Monitor/Activity and Positions | safety safe",
                "currentPanel": "Monitor",
                "currentPanelSafety": "safe",
                "monitorSubpanel": "Activity and Positions",
                "selectedMonitorSubtabs": ["Activity and Positions"],
                "mainWindowPresent": True,
            },
            {
                "summary": "main window live via thinkorswim | current panel Monitor/Account Statement | safety safe",
                "currentPanel": "Monitor",
                "currentPanelSafety": "safe",
                "monitorSubpanel": "Activity and Positions",
                "selectedMonitorSubtabs": ["Statement for account 11111234SCHW (Individual)"],
                "labeledButtons": [{"label": "Dump Account"}],
                "mainWindowPresent": True,
            },
        ],
    )
    def test_route_reaches_account_statement(
        self,
        probe_mock,
        frontmost_mock,
        click_mock,
        dismiss_mock,
        screenshot_mock,
        save_mock,
        sleep_mock,
    ) -> None:
        """The route helper should dismiss overlays before finishing Account Statement routing."""
        report = route_to_account_statement(dry_run=False)
        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "account-statement-routed")
        self.assertIn("Account Statement", report["message"])
        self.assertEqual(click_mock.call_count, 1)
        dismiss_mock.assert_called_once()
        frontmost_mock.assert_called_once()
        screenshot_mock.assert_called_once()
        save_mock.assert_called_once()
        self.assertEqual(probe_mock.call_count, 3)
        self.assertGreaterEqual(sleep_mock.call_count, 2)

    @patch("inferno_tos_ui_route.time.sleep")
    @patch("inferno_tos_ui_route.save_ui_route_report")
    @patch("inferno_tos_ui_route.capture_route_screenshot", return_value="/tmp/route-dynamic.png")
    @patch(
        "inferno_tos_ui_route.click_point",
        side_effect=[
            {"ok": True, "point": [240, 60], "stdout": "", "stderr": "", "returncode": 0},
            {"ok": True, "point": [480, 92], "stdout": "", "stderr": "", "returncode": 0},
        ],
    )
    @patch(
        "inferno_tos_ui_route.bring_tos_frontmost",
        return_value={"ok": True, "frontmostProcess": "java-arm", "stderr": "", "returncode": 0},
    )
    @patch(
        "inferno_tos_ui_route.probe_tos_session",
        side_effect=[
            {
                "summary": "main window live via thinkorswim | current panel Order Entry | safety unknown | account paper",
                "currentPanel": "Order Entry",
                "currentPanelSafety": "unknown",
                "monitorSubpanel": None,
                "monitorSubtabs": [],
                "currentTabGroups": [{"label": "Monitor", "center": [240, 60]}],
                "mainWindowPresent": True,
            },
            {
                "summary": "main window live via thinkorswim | current panel Monitor/Activity and Positions | safety safe | account paper",
                "currentPanel": "Monitor",
                "currentPanelSafety": "safe",
                "monitorSubpanel": "Activity and Positions",
                "monitorSubtabs": [{"label": "Account Statement", "center": [480, 92]}],
                "currentTabGroups": [{"label": "Monitor", "center": [240, 60]}],
                "mainWindowPresent": True,
            },
            {
                "summary": "main window live via thinkorswim | current panel Monitor/Account Statement | safety safe | account paper",
                "currentPanel": "Monitor",
                "currentPanelSafety": "safe",
                "monitorSubpanel": "Account Statement",
                "monitorSubtabs": [{"label": "Account Statement", "center": [480, 92]}],
                "currentTabGroups": [{"label": "Monitor", "center": [240, 60]}],
                "mainWindowPresent": True,
            },
        ],
    )
    def test_route_prefers_dynamic_accessibility_centers_when_available(
        self,
        probe_mock,
        frontmost_mock,
        click_mock,
        screenshot_mock,
        save_mock,
        sleep_mock,
    ) -> None:
        """The route helper should use live accessibility centers before static fallbacks."""
        report = route_to_account_statement(dry_run=False)
        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "account-statement-routed")
        self.assertEqual(click_mock.call_args_list[0].args[0], (240, 60))
        self.assertEqual(click_mock.call_args_list[1].args[0], (480, 92))
        frontmost_mock.assert_called_once()
        screenshot_mock.assert_called_once()
        save_mock.assert_called_once()
        self.assertEqual(probe_mock.call_count, 3)
        self.assertGreaterEqual(sleep_mock.call_count, 2)

    @patch("inferno_tos_ui_route.TOS_MONITOR_TAB_CANDIDATES", new=((250, 70), (392, 57)))
    @patch("inferno_tos_ui_route.time.sleep")
    @patch("inferno_tos_ui_route.save_ui_route_report")
    @patch("inferno_tos_ui_route.capture_route_screenshot", return_value="/tmp/route-candidate-sweep.png")
    @patch(
        "inferno_tos_ui_route.click_point",
        side_effect=[
            {"ok": True, "point": [250, 70], "stdout": "", "stderr": "", "returncode": 0},
            {"ok": True, "point": [392, 57], "stdout": "", "stderr": "", "returncode": 0},
            {"ok": True, "point": [480, 92], "stdout": "", "stderr": "", "returncode": 0},
        ],
    )
    @patch(
        "inferno_tos_ui_route.bring_tos_frontmost",
        return_value={"ok": True, "frontmostProcess": "java-arm", "stderr": "", "returncode": 0},
    )
    @patch(
        "inferno_tos_ui_route.probe_tos_session",
        side_effect=[
            {
                "summary": "main window live via thinkorswim | current panel Scan | safety unsafe | account paper",
                "currentPanel": "Scan",
                "currentPanelSafety": "unsafe",
                "monitorSubpanel": None,
                "monitorSubtabs": [],
                "currentTabGroups": [],
                "mainWindowPresent": True,
            },
            {
                "summary": "main window live via thinkorswim | current panel Scan | safety unsafe | account paper",
                "currentPanel": "Scan",
                "currentPanelSafety": "unsafe",
                "monitorSubpanel": None,
                "monitorSubtabs": [],
                "currentTabGroups": [],
                "mainWindowPresent": True,
            },
            {
                "summary": "main window live via thinkorswim | current panel Monitor/Activity and Positions | safety safe | account paper",
                "currentPanel": "Monitor",
                "currentPanelSafety": "safe",
                "monitorSubpanel": "Activity and Positions",
                "monitorSubtabs": [{"label": "Account Statement", "center": [480, 92]}],
                "currentTabGroups": [{"label": "Monitor", "center": [250, 70]}],
                "mainWindowPresent": True,
            },
            {
                "summary": "main window live via thinkorswim | current panel Monitor/Account Statement | safety safe | account paper",
                "currentPanel": "Monitor",
                "currentPanelSafety": "safe",
                "monitorSubpanel": "Account Statement",
                "monitorSubtabs": [{"label": "Account Statement", "center": [480, 92]}],
                "currentTabGroups": [{"label": "Monitor", "center": [250, 70]}],
                "mainWindowPresent": True,
            },
        ],
    )
    def test_route_sweeps_monitor_candidates_until_one_lands(
        self,
        probe_mock,
        frontmost_mock,
        click_mock,
        screenshot_mock,
        save_mock,
        sleep_mock,
    ) -> None:
        """The route helper should try backup Monitor points when the first one misses."""
        report = route_to_account_statement(dry_run=False)
        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "account-statement-routed")
        self.assertEqual(click_mock.call_args_list[0].args[0], (250, 70))
        self.assertEqual(click_mock.call_args_list[1].args[0], (392, 57))
        self.assertEqual(report["monitorPoint"], [392, 57])
        frontmost_mock.assert_called_once()
        screenshot_mock.assert_called_once()
        save_mock.assert_called_once()
        self.assertEqual(probe_mock.call_count, 4)
        self.assertGreaterEqual(sleep_mock.call_count, 3)


if __name__ == "__main__":
    unittest.main()
