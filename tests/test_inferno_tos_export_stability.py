from __future__ import annotations

"""Regression tests for the TOS export stability runner.

The stability runner wraps the verifier with retry-with-backoff and classifies
each attempt into a fail-mode bucket. The tests below freeze the contract:

- ``researchOnly`` and ``promotable`` are immutable.
- Every verifier verdict lands in exactly one fail-mode bucket.
- A run that recovers reports ``transient-recovered`` even though some probes
  blocked.
- A run that never recovers reports ``blocked`` and surfaces the dominant
  fail mode in the narrative.
"""

import unittest
from typing import Any
from unittest.mock import patch

import inferno_tos_export_stability as stability_module
from inferno_tos_export_stability import (
    FAIL_MODES,
    REMEDIATION,
    STABILITY_STAGE,
    build_stability_report,
    classify_attempt,
    finalize_stability_report,
    stability_text,
)


def _attempt(
    verdict: str,
    *,
    app_running: bool = True,
    system_events_ok: bool = True,
    main_window: bool = True,
    panel_safety: str = "safe",
    account_mode: str = "live",
    ui_route_ok: bool = True,
    shortcut_valid: bool = True,
    app_path_exists: bool = True,
    message: str = "",
) -> dict[str, Any]:
    """Build a minimal verifier-shaped attempt dict for the classifier."""
    return {
        "verdict": verdict,
        "message": message,
        "appRunning": app_running,
        "systemEventsOk": system_events_ok,
        "shortcutValid": shortcut_valid,
        "appPathExists": app_path_exists,
        "uiRoute": {"ok": ui_route_ok},
        "sessionProbe": {
            "mainWindowPresent": main_window,
            "currentPanelSafety": panel_safety,
            "accountMode": account_mode,
        },
    }


class ClassifyAttemptTests(unittest.TestCase):
    """Each verifier verdict + signal combo must land in exactly one bucket."""

    def test_ready_live_readonly_classifies_as_ok(self) -> None:
        self.assertEqual(classify_attempt(_attempt("ready-live-readonly")), "ok-ready-live-readonly")

    def test_ready_classifies_as_ok_paper(self) -> None:
        self.assertEqual(classify_attempt(_attempt("ready")), "ok-ready-paper")

    def test_inactive_safe_classifies_as_inactive(self) -> None:
        self.assertEqual(classify_attempt(_attempt("inactive-safe")), "inactive-by-config")

    def test_app_not_running_classifies_as_tos_not_running(self) -> None:
        self.assertEqual(classify_attempt(_attempt("manual-check", app_running=False)), "tos-not-running")

    def test_accessibility_blocked_classifies_correctly(self) -> None:
        self.assertEqual(
            classify_attempt(_attempt("blocked", system_events_ok=False)),
            "accessibility-blocked",
        )

    def test_window_missing_takes_priority_over_panel(self) -> None:
        self.assertEqual(
            classify_attempt(_attempt("manual-check", main_window=False)),
            "window-missing",
        )

    def test_unsafe_panel_classifies(self) -> None:
        self.assertEqual(
            classify_attempt(_attempt("manual-check", panel_safety="unsafe")),
            "panel-unsafe",
        )

    def test_ui_route_failure_classifies(self) -> None:
        self.assertEqual(
            classify_attempt(_attempt("manual-check", ui_route_ok=False)),
            "ui-route-dry-run-failed",
        )

    def test_unauthorized_account_classifies(self) -> None:
        self.assertEqual(
            classify_attempt(_attempt("manual-check", account_mode="live")),
            "account-not-authorized",
        )

    def test_app_path_missing_short_circuits(self) -> None:
        self.assertEqual(
            classify_attempt(_attempt("blocked", app_path_exists=False)),
            "app-path-missing",
        )

    def test_invalid_shortcut_short_circuits(self) -> None:
        self.assertEqual(
            classify_attempt(_attempt("blocked", shortcut_valid=False)),
            "shortcut-invalid",
        )

    def test_generic_blocked_falls_to_transient(self) -> None:
        self.assertEqual(
            classify_attempt(_attempt("manual-check", account_mode="paper")),
            "transient-blocked",
        )


class StabilityReportTests(unittest.TestCase):
    """End-to-end stability runner behaviour with stub verifiers."""

    def test_research_only_is_immutable(self) -> None:
        payload = build_stability_report(
            attempts=1,
            backoff_seconds=0,
            sleep=lambda _seconds: None,
            verifier=lambda **_kw: _attempt("ready-live-readonly"),
        )
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertEqual(payload["stage"], STABILITY_STAGE)

    def test_all_ok_yields_stable_ready(self) -> None:
        payload = build_stability_report(
            attempts=3,
            backoff_seconds=0,
            sleep=lambda _seconds: None,
            verifier=lambda **_kw: _attempt("ready-live-readonly"),
        )
        self.assertEqual(payload["verdict"], "stable-ready")
        self.assertEqual(payload["okCount"], 3)

    def test_mixed_recovery_yields_transient(self) -> None:
        calls = {"index": 0}
        attempts_sequence = [
            _attempt("manual-check", main_window=False),
            _attempt("ready-live-readonly"),
            _attempt("ready-live-readonly"),
        ]

        def verifier(**_kw: Any) -> dict[str, Any]:
            attempt = attempts_sequence[calls["index"]]
            calls["index"] += 1
            return attempt

        payload = build_stability_report(
            attempts=3,
            backoff_seconds=0,
            sleep=lambda _seconds: None,
            verifier=verifier,
        )
        self.assertEqual(payload["verdict"], "transient-recovered")
        self.assertEqual(payload["okCount"], 2)
        # Narrative should mention both probes recovered.
        self.assertIn("recovered", payload["narrative"].lower())

    def test_all_blocked_yields_blocked_with_dominant(self) -> None:
        with patch.object(stability_module, "TOS_EXPORT_AUTOMATION_ENABLED", True):
            payload = build_stability_report(
                attempts=3,
                backoff_seconds=0,
                sleep=lambda _seconds: None,
                verifier=lambda **_kw: _attempt("manual-check", main_window=False),
            )
        self.assertEqual(payload["verdict"], "blocked")
        self.assertEqual(payload["dominantFailMode"], "window-missing")
        self.assertIn(
            REMEDIATION["window-missing"].split(".")[0].lower(),
            payload["narrative"].lower(),
        )

    def test_all_inactive_yields_inactive_safe(self) -> None:
        payload = build_stability_report(
            attempts=2,
            backoff_seconds=0,
            sleep=lambda _seconds: None,
            verifier=lambda **_kw: _attempt("inactive-safe"),
        )
        self.assertEqual(payload["verdict"], "inactive-safe")

    def test_closed_tos_low_power_mode_is_inactive_safe(self) -> None:
        """Closed TOS is expected when background export automation is off."""
        with (
            patch.object(stability_module, "TOS_EXPORT_AUTOMATION_ENABLED", False),
            patch.object(stability_module, "TOS_BACKGROUND_EXPORT_ALLOWED", False),
        ):
            payload = build_stability_report(
                attempts=2,
                backoff_seconds=0,
                sleep=lambda _seconds: None,
                verifier=lambda **_kw: _attempt("manual-check", app_running=False),
            )
        self.assertEqual(payload["verdict"], "inactive-safe")
        self.assertEqual(payload["dominantFailMode"], "tos-closed-low-power")
        self.assertIn("low-performance mode", payload["narrative"])

    def test_exception_in_verifier_lands_in_unknown(self) -> None:
        def verifier(**_kw: Any) -> dict[str, Any]:
            raise RuntimeError("simulated boom")

        payload = build_stability_report(
            attempts=2,
            backoff_seconds=0,
            sleep=lambda _seconds: None,
            verifier=verifier,
        )
        self.assertEqual(payload["okCount"], 0)
        self.assertEqual(payload["verdict"], "blocked")
        self.assertEqual(payload["classificationCounts"]["unknown"], 2)

    def test_finalize_handles_no_classification(self) -> None:
        # Empty inputs should not raise; we accept a zero-attempt diagnosis.
        report = finalize_stability_report(0, [], {mode: 0 for mode in FAIL_MODES})
        self.assertIn("verdict", report)

    def test_stability_text_renders_each_section(self) -> None:
        payload = build_stability_report(
            attempts=1,
            backoff_seconds=0,
            sleep=lambda _seconds: None,
            verifier=lambda **_kw: _attempt("ready-live-readonly"),
        )
        rendered = stability_text(payload)
        self.assertIn("TOS Export Stability", rendered)
        self.assertIn("Verdict:", rendered)
        self.assertIn("Narrative:", rendered)
        self.assertIn("Reminders:", rendered)


if __name__ == "__main__":
    unittest.main()
