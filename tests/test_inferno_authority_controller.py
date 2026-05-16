from __future__ import annotations

"""Regression tests for the automation authority controller.

This module decides what the desk is allowed to do today. The fail-closed
contract is that ``brokerSubmitAllowed`` and ``liveTradingAllowed`` must stay
``False`` no matter what evidence the upstream artifacts present, that any
unexpected ``liveTradingAllowed`` flag in nested artifacts forces the desk to
``halted``, and that a stale snapshot or unsafe broker adapter mode also forces
``halted``. These tests freeze that contract so future edits cannot quietly
flip a permission bit.
"""

import unittest
from unittest.mock import patch

from inferno_authority_controller import (
    SAFE_BROKER_MODES,
    broker_preview_clean,
    decide_authority,
    live_flag_detected,
    next_milestones,
)
from inferno_config import local_today


def fresh_iso(hour: int = 8) -> str:
    """Build an ISO timestamp that ``is_today`` will accept."""
    return f"{local_today()}T{hour:02d}:00:00-06:00"


def stale_iso() -> str:
    return "1999-01-01T08:00:00-06:00"


def healthy_inputs(scored_tickets: int = 0) -> dict[str, dict]:
    """Return a freshly-dated artifact set matching today's verified state.

    The defaults reproduce the 2026-05-10 desk: paper-evidence-only authority,
    Straddle setup concentration warning, no clean broker-preview orders.
    """
    return {
        "snapshot": {"generatedAt": fresh_iso(), "rows": [{"ticker": "CEG"}]},
        "execution_queue": {"generatedAt": fresh_iso(), "count": 5},
        "ledger": {"updatedAt": fresh_iso(), "items": []},
        "performance": {
            "generatedAt": fresh_iso(),
            "closedMetrics": {"scoredCount": scored_tickets},
            "strategies": [],
            "deskVerdict": {"level": "evidence-building"},
        },
        "strategy_lab": {
            "generatedAt": fresh_iso(),
            "deskVerdict": {"level": "insufficient-data", "promotable": False},
            "promotionCandidates": [],
        },
        "exposure": {
            "generatedAt": fresh_iso(),
            "verdict": {"level": "review", "message": "setup concentration high: Straddle at 80%"},
            "marketRegime": {"regime": "bullish-normal", "riskLevel": "normal"},
        },
        "broker_preview": {
            "generatedAt": fresh_iso(),
            "previewOnly": True,
            "liveTradingAllowed": False,
            "count": 0,
        },
    }


class AuthorityControllerSafetyTests(unittest.TestCase):
    """Verify the fail-closed contract for the authority controller."""

    def test_safe_modes_include_off(self) -> None:
        """The committed safe-mode allowlist must continue to include OFF."""
        self.assertIn("OFF", SAFE_BROKER_MODES)
        self.assertNotIn("LIVE", SAFE_BROKER_MODES)

    def test_paper_evidence_only_with_fresh_artifacts(self) -> None:
        """Fresh artifacts but no closed evidence stay at paper-evidence-only."""
        inputs = healthy_inputs()
        with patch("inferno_authority_controller.smtp_configured", return_value=True):
            decision = decide_authority(**inputs)
        self.assertEqual(decision["authorityLevel"], "paper-evidence-only")
        self.assertFalse(decision["brokerSubmitAllowed"])
        self.assertFalse(decision["liveTradingAllowed"])
        self.assertEqual(decision["blockers"], [])
        # The exposure warning and zero-scored-tickets warning must propagate.
        warnings = " | ".join(decision["warnings"])
        self.assertIn("setup concentration", warnings)
        self.assertIn("scored paper tickets", warnings)

    def test_stale_snapshot_halts_authority(self) -> None:
        """A stale snapshot is a hard blocker, not a warning."""
        inputs = healthy_inputs()
        inputs["snapshot"]["generatedAt"] = stale_iso()
        with patch("inferno_authority_controller.smtp_configured", return_value=True):
            decision = decide_authority(**inputs)
        self.assertEqual(decision["authorityLevel"], "halted")
        self.assertFalse(decision["brokerSubmitAllowed"])
        self.assertFalse(decision["liveTradingAllowed"])
        self.assertIn("latest snapshot is stale", decision["blockers"])
        # When halted, the only allowed action is inspection.
        self.assertEqual(decision["allowedActions"], ["inspect_reports"])

    def test_unexpected_live_flag_halts_authority(self) -> None:
        """Any nested liveTradingAllowed=True must trigger halted."""
        inputs = healthy_inputs()
        inputs["broker_preview"]["liveTradingAllowed"] = True
        with patch("inferno_authority_controller.smtp_configured", return_value=True):
            decision = decide_authority(**inputs)
        self.assertEqual(decision["authorityLevel"], "halted")
        self.assertFalse(decision["brokerSubmitAllowed"])
        self.assertFalse(decision["liveTradingAllowed"])
        self.assertIn(
            "unexpected liveTradingAllowed flag detected",
            decision["blockers"],
        )

    def test_unsafe_broker_mode_halts_authority(self) -> None:
        """Broker adapter modes outside the safe allowlist must halt the desk."""
        inputs = healthy_inputs()
        with patch("inferno_authority_controller.BROKER_ADAPTER_MODE", "LIVE"), \
             patch("inferno_authority_controller.smtp_configured", return_value=True):
            decision = decide_authority(**inputs)
        self.assertEqual(decision["authorityLevel"], "halted")
        self.assertFalse(decision["brokerSubmitAllowed"])
        self.assertFalse(decision["liveTradingAllowed"])
        self.assertTrue(
            any("not in safe preview modes" in blocker for blocker in decision["blockers"]),
            decision["blockers"],
        )

    def test_promoted_evidence_still_blocks_live_submit(self) -> None:
        """Even a fully promoted evidence stack cannot enable live submission."""
        inputs = healthy_inputs(scored_tickets=40)
        inputs["performance"]["strategies"] = [{"eligibleForPromotion": True}]
        inputs["performance"]["deskVerdict"] = {"level": "review-for-promotion"}
        inputs["strategy_lab"]["deskVerdict"] = {
            "level": "review-for-promotion",
            "promotable": True,
        }
        inputs["strategy_lab"]["promotionCandidates"] = ["PROMOTABLE_EDGE"]
        inputs["exposure"]["verdict"] = {"level": "clear", "message": "exposure clear"}
        inputs["broker_preview"]["count"] = 1
        with patch("inferno_authority_controller.smtp_configured", return_value=True):
            decision = decide_authority(**inputs)
        # The level may escalate to broker-preview-only, but the live and submit
        # gates must remain shut.
        self.assertEqual(decision["authorityLevel"], "broker-preview-only")
        self.assertFalse(decision["brokerSubmitAllowed"])
        self.assertFalse(decision["liveTradingAllowed"])
        self.assertIn("submit_live_order", decision["blockedActions"])

    def test_blocked_actions_always_include_live_submit(self) -> None:
        """submit_live_order must stay blocked across every healthy code path."""
        inputs = healthy_inputs()
        with patch("inferno_authority_controller.smtp_configured", return_value=True):
            decision = decide_authority(**inputs)
        self.assertIn("submit_live_order", decision["blockedActions"])
        self.assertIn(
            "live broker submission is disabled by policy",
            decision["blockedActions"]["submit_live_order"],
        )


class AuthorityHelperTests(unittest.TestCase):
    """Verify helper predicates that decide_authority depends on."""

    def test_live_flag_detected_walks_nested_structures(self) -> None:
        payload = {
            "outer": {
                "items": [
                    {"meta": {"liveTradingAllowed": True}},
                ],
            },
        }
        self.assertTrue(live_flag_detected(payload))

    def test_live_flag_detected_returns_false_for_clean_payload(self) -> None:
        payload = {"outer": {"items": [{"meta": {"liveTradingAllowed": False}}]}}
        self.assertFalse(live_flag_detected(payload))

    def test_broker_preview_clean_requires_preview_only_and_count(self) -> None:
        clean = {
            "previewOnly": True,
            "liveTradingAllowed": False,
            "count": 1,
        }
        dirty_no_count = dict(clean, count=0)
        dirty_blocked = dict(clean, blockedReason="missing chains")
        dirty_live = dict(clean, liveTradingAllowed=True)
        dirty_not_preview = dict(clean, previewOnly=False)
        self.assertTrue(broker_preview_clean(clean))
        self.assertFalse(broker_preview_clean(dirty_no_count))
        self.assertFalse(broker_preview_clean(dirty_blocked))
        self.assertFalse(broker_preview_clean(dirty_live))
        self.assertFalse(broker_preview_clean(dirty_not_preview))

    def test_next_milestones_always_keeps_live_disabled_reminder(self) -> None:
        inputs = healthy_inputs()
        milestones = next_milestones(
            inputs["performance"],
            inputs["strategy_lab"],
            inputs["exposure"],
            inputs["broker_preview"],
        )
        self.assertTrue(
            any("keep live submit authority disabled" in milestone for milestone in milestones),
            milestones,
        )


if __name__ == "__main__":
    unittest.main()
