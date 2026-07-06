"""Contract tests for inferno_capital_scaling.

Pinned invariants:
  - Module is research-only and promotable=False.
  - Recommendation = clamp(NLV * pct, floor, ceiling). Exactly.
  - Floor binds when NLV is too small for the target %.
  - Ceiling binds when NLV is large enough that target % exceeds it.
  - Effective % of NLV reflects the *actual* recommended cap (so the
    operator can see when they're risking >target because floor binds).
  - Stale NLV (>24h) produces the ``nlv-stale`` verdict, not ``aligned``.
  - Missing NLV produces ``nlv-missing``.
  - Without an ack file, the verdict is ``ack-required`` whenever the
    config cap diverges from the recommendation by >20%.
  - With an ack file within tolerance, ``shouldUseRecommendation=True``
    and ``effectiveCap`` reflects the ack'd cap (not the config default).
  - A drawdown of >25% from ack'd NLV forces ``needsFreshAck=True``
    regardless of how close the recommendation still is to the ack'd cap.
  - ``current_recommended_cap`` ALWAYS returns a safe ``effectiveCap``
    float; risk policy must be able to call it without exception.
"""

from __future__ import annotations

import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import inferno_capital_scaling as cs


NOW = datetime(2026, 5, 24, 14, 0, 0, tzinfo=timezone.utc)


def _write_sync(tmp_path: Path, *, nlv: float | None, generated_at: datetime) -> Path:
    """Write a minimal live-account-sync fixture for the module to read."""
    payload = {
        "generatedAt": generated_at.isoformat(),
        "netLiquidatingValue": nlv,
    }
    f = tmp_path / "inferno_live_account_sync.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    return f


class ComputeRecommendedCapTests(unittest.TestCase):
    """Pure-function tests on the clamp formula. No I/O."""

    def test_below_floor_binds_to_floor(self) -> None:
        rec = cs.compute_recommended_cap(1_108.08, target_pct=0.01, floor=25.0, ceiling=2000.0)
        self.assertAlmostEqual(rec["rawComputedCap"], 11.08, places=2)
        self.assertEqual(rec["recommendedCap"], 25.0)
        self.assertTrue(rec["atFloor"])
        self.assertFalse(rec["atCeiling"])
        # Effective % is higher than target because floor binds.
        self.assertAlmostEqual(rec["effectivePctOfNLV"], 25.0 / 1_108.08, places=4)

    def test_above_ceiling_binds_to_ceiling(self) -> None:
        rec = cs.compute_recommended_cap(500_000, target_pct=0.01, floor=25.0, ceiling=2000.0)
        self.assertEqual(rec["rawComputedCap"], 5000.0)
        self.assertEqual(rec["recommendedCap"], 2000.0)
        self.assertFalse(rec["atFloor"])
        self.assertTrue(rec["atCeiling"])

    def test_clean_middle_of_band(self) -> None:
        rec = cs.compute_recommended_cap(25_000, target_pct=0.01, floor=25.0, ceiling=2000.0)
        self.assertEqual(rec["rawComputedCap"], 250.0)
        self.assertEqual(rec["recommendedCap"], 250.0)
        self.assertFalse(rec["atFloor"])
        self.assertFalse(rec["atCeiling"])

    def test_zero_or_negative_nlv_returns_none(self) -> None:
        rec = cs.compute_recommended_cap(0)
        self.assertIsNone(rec["recommendedCap"])
        rec = cs.compute_recommended_cap(None)
        self.assertIsNone(rec["recommendedCap"])

    def test_2pct_rule_scales_linearly(self) -> None:
        # 2% on 25k should be exactly 500, hits the ceiling at 100k.
        self.assertEqual(
            cs.compute_recommended_cap(25_000, target_pct=0.02)["recommendedCap"], 500.0
        )
        self.assertEqual(
            cs.compute_recommended_cap(100_000, target_pct=0.02)["recommendedCap"], 2000.0
        )


class BuildIntegrationTests(unittest.TestCase):
    """End-to-end build with mocked file paths."""

    def _patched_paths(self, tmp: Path, sync_file: Path):
        """Patch the module-level file paths to live inside the tmp dir."""
        ack_file = tmp / "inferno_capital_scaling_ack.json"
        state_file = tmp / "inferno_capital_scaling_state.json"
        return [
            patch.object(cs, "LIVE_ACCOUNT_SYNC_FILE", sync_file),
            patch.object(cs, "CAPITAL_SCALING_ACK_FILE", ack_file),
            patch.object(cs, "CAPITAL_SCALING_STATE_FILE", state_file),
        ]

    def test_build_research_only_invariants(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            sync = _write_sync(tmp, nlv=1108.08, generated_at=NOW - timedelta(hours=4))
            patches = self._patched_paths(tmp, sync)
            for p in patches:
                p.start()
            try:
                payload = cs.build_capital_scaling(now=NOW)
            finally:
                for p in patches:
                    p.stop()
        self.assertEqual(payload["stage"], cs.CAPITAL_SCALING_STAGE)
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["authorityChanged"])

    def test_small_account_triggers_ack_required(self) -> None:
        """$1,108 NLV with $500 config cap → 20x divergence, ack required."""
        with TemporaryDirectory() as td:
            tmp = Path(td)
            sync = _write_sync(tmp, nlv=1108.08, generated_at=NOW - timedelta(hours=4))
            patches = self._patched_paths(tmp, sync)
            with patch.object(cs, "MAX_SINGLE_TICKET_DOLLARS", 500.0):
                for p in patches:
                    p.start()
                try:
                    payload = cs.build_capital_scaling(now=NOW)
                finally:
                    for p in patches:
                        p.stop()
        self.assertEqual(payload["verdict"], "ack-required")
        self.assertEqual(payload["recommendation"]["recommendedCap"], 25.0)
        self.assertTrue(payload["recommendation"]["atFloor"])

    def test_aligned_when_cap_matches_recommendation(self) -> None:
        """NLV $25k @ 1% → $250 recommendation; if config cap is $250 → aligned."""
        with TemporaryDirectory() as td:
            tmp = Path(td)
            sync = _write_sync(tmp, nlv=25_000, generated_at=NOW - timedelta(hours=4))
            patches = self._patched_paths(tmp, sync)
            with patch.object(cs, "MAX_SINGLE_TICKET_DOLLARS", 250.0):
                for p in patches:
                    p.start()
                try:
                    payload = cs.build_capital_scaling(now=NOW)
                finally:
                    for p in patches:
                        p.stop()
        self.assertEqual(payload["verdict"], "aligned")
        self.assertEqual(payload["recommendation"]["recommendedCap"], 250.0)

    def test_stale_nlv_produces_nlv_stale_verdict(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            sync = _write_sync(tmp, nlv=25_000, generated_at=NOW - timedelta(hours=48))
            patches = self._patched_paths(tmp, sync)
            for p in patches:
                p.start()
            try:
                payload = cs.build_capital_scaling(now=NOW)
            finally:
                for p in patches:
                    p.stop()
        self.assertEqual(payload["verdict"], "nlv-stale")

    def test_missing_nlv_produces_nlv_missing_verdict(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            sync = _write_sync(tmp, nlv=None, generated_at=NOW - timedelta(hours=4))
            patches = self._patched_paths(tmp, sync)
            for p in patches:
                p.start()
            try:
                payload = cs.build_capital_scaling(now=NOW)
            finally:
                for p in patches:
                    p.stop()
        self.assertEqual(payload["verdict"], "nlv-missing")


class AckFlowTests(unittest.TestCase):
    """Once the operator acks the formula, the cap auto-applies within tolerance."""

    def _setup(self, tmp: Path, *, nlv: float, generated_at: datetime, acked_cap: float | None = None, acked_nlv: float | None = None):
        sync = _write_sync(tmp, nlv=nlv, generated_at=generated_at)
        ack_file = tmp / "inferno_capital_scaling_ack.json"
        if acked_cap is not None:
            ack_payload = {
                "acceptedAt": (NOW - timedelta(days=1)).isoformat(),
                "acceptedCap": acked_cap,
                "acceptedNlv": acked_nlv,
                "targetPctPerTicket": 0.01,
                "floorDollars": 25.0,
                "ceilingDollars": 2000.0,
                "dailyTicketsRatio": 3.0,
                "scalingBehavior": "symmetric-on-current-nlv",
                "ackTolerancePct": 0.20,
                "drawdownPausePct": 0.25,
            }
            ack_file.write_text(json.dumps(ack_payload), encoding="utf-8")
        return sync, ack_file

    def _patched_ack_paths(self, tmp: Path, sync_file: Path, ack_file: Path):
        state_file = tmp / "inferno_capital_scaling_state.json"
        return [
            patch.object(cs, "LIVE_ACCOUNT_SYNC_FILE", sync_file),
            patch.object(cs, "CAPITAL_SCALING_ACK_FILE", ack_file),
            patch.object(cs, "CAPITAL_SCALING_STATE_FILE", state_file),
        ]

    def test_ack_within_tolerance_yields_should_use_recommendation(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            sync, ack = self._setup(
                tmp,
                nlv=25_500,  # 25.5k → $255 rec, within 20% of $250 acked
                generated_at=NOW - timedelta(hours=2),
                acked_cap=250.0,
                acked_nlv=25_000,
            )
            state_file = tmp / "inferno_capital_scaling_state.json"
            with patch.object(cs, "LIVE_ACCOUNT_SYNC_FILE", sync), \
                 patch.object(cs, "CAPITAL_SCALING_ACK_FILE", ack), \
                 patch.object(cs, "CAPITAL_SCALING_STATE_FILE", state_file), \
                 patch.object(cs, "MAX_SINGLE_TICKET_DOLLARS", 500.0):
                payload = cs.build_capital_scaling(now=NOW)
        ack_status = payload["ack"]
        self.assertTrue(ack_status["ackPresent"])
        self.assertTrue(ack_status["withinAckTolerance"])
        self.assertFalse(ack_status["drawdownTrigger"])
        self.assertFalse(ack_status["needsFreshAck"])

    def test_drawdown_greater_than_25pct_forces_fresh_ack(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            # NLV dropped from 25k to 17k = 32% drawdown
            sync, ack = self._setup(
                tmp,
                nlv=17_000,
                generated_at=NOW - timedelta(hours=2),
                acked_cap=250.0,
                acked_nlv=25_000,
            )
            state_file = tmp / "inferno_capital_scaling_state.json"
            with patch.object(cs, "LIVE_ACCOUNT_SYNC_FILE", sync), \
                 patch.object(cs, "CAPITAL_SCALING_ACK_FILE", ack), \
                 patch.object(cs, "CAPITAL_SCALING_STATE_FILE", state_file), \
                 patch.object(cs, "MAX_SINGLE_TICKET_DOLLARS", 500.0):
                payload = cs.build_capital_scaling(now=NOW)
        ack_status = payload["ack"]
        self.assertTrue(ack_status["drawdownTrigger"])
        self.assertTrue(ack_status["needsFreshAck"])

    def test_accept_cli_records_cap_using_requested_floor(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            sync = _write_sync(tmp, nlv=1_000, generated_at=NOW - timedelta(hours=2))
            ack_file = tmp / "inferno_capital_scaling_ack.json"
            state_file = tmp / "inferno_capital_scaling_state.json"
            artifact_file = tmp / "inferno_capital_scaling.json"
            report_file = tmp / "capital_scaling_latest.txt"
            argv = ["inferno_capital_scaling.py", "accept", "--floor", "500"]
            with patch.object(cs, "LIVE_ACCOUNT_SYNC_FILE", sync), \
                 patch.object(cs, "CAPITAL_SCALING_ACK_FILE", ack_file), \
                 patch.object(cs, "CAPITAL_SCALING_STATE_FILE", state_file), \
                 patch.object(cs, "CAPITAL_SCALING_FILE", artifact_file), \
                 patch.object(cs, "CAPITAL_SCALING_TEXT_FILE", report_file), \
                 patch.object(sys, "argv", argv):
                with redirect_stdout(StringIO()):
                    exit_code = cs.main()
            self.assertEqual(exit_code, 0)
            ack = json.loads(ack_file.read_text(encoding="utf-8"))
            self.assertEqual(ack["acceptedCap"], 500.0)
            self.assertEqual(ack["floorDollars"], 500.0)


class CurrentRecommendedCapAccessorTests(unittest.TestCase):
    """The risk-policy-facing accessor must always be safe to call."""

    def test_no_ack_falls_back_to_config_default(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            sync = _write_sync(tmp, nlv=1108.08, generated_at=NOW - timedelta(hours=4))
            with patch.object(cs, "LIVE_ACCOUNT_SYNC_FILE", sync), \
                 patch.object(cs, "CAPITAL_SCALING_ACK_FILE", tmp / "missing.json"), \
                 patch.object(cs, "CAPITAL_SCALING_STATE_FILE", tmp / "state.json"), \
                 patch.object(cs, "MAX_SINGLE_TICKET_DOLLARS", 500.0):
                info = cs.current_recommended_cap(now=NOW)
        self.assertEqual(info["effectiveCap"], 500.0)
        self.assertFalse(info["shouldUseRecommendation"])
        self.assertEqual(info["recommendedCap"], 25.0)
        self.assertEqual(info["verdict"], "ack-required")

    def test_ack_within_tolerance_uses_acked_cap(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            state_file = tmp / "state.json"
            sync = _write_sync(tmp, nlv=25_500, generated_at=NOW - timedelta(hours=2))
            ack_file = tmp / "inferno_capital_scaling_ack.json"
            ack_file.write_text(json.dumps({
                "acceptedAt": (NOW - timedelta(days=1)).isoformat(),
                "acceptedCap": 250.0,
                "acceptedNlv": 25_000,
                "targetPctPerTicket": 0.01,
                "floorDollars": 25.0,
                "ceilingDollars": 2000.0,
                "ackTolerancePct": 0.20,
                "drawdownPausePct": 0.25,
            }), encoding="utf-8")
            with patch.object(cs, "LIVE_ACCOUNT_SYNC_FILE", sync), \
                 patch.object(cs, "CAPITAL_SCALING_ACK_FILE", ack_file), \
                 patch.object(cs, "CAPITAL_SCALING_STATE_FILE", state_file), \
                 patch.object(cs, "MAX_SINGLE_TICKET_DOLLARS", 500.0):
                info = cs.current_recommended_cap(now=NOW)
        # The acked cap is 250, well below the config default of 500, so it wins.
        self.assertEqual(info["effectiveCap"], 250.0)
        self.assertTrue(info["shouldUseRecommendation"])

    def test_accessor_swallows_exceptions_and_returns_safe_default(self) -> None:
        """Anything raises → we return the config default. Risk policy must never blow up."""
        with patch.object(cs, "build_capital_scaling", side_effect=RuntimeError("nope")), \
             patch.object(cs, "MAX_SINGLE_TICKET_DOLLARS", 500.0):
            info = cs.current_recommended_cap(now=NOW)
        self.assertEqual(info["effectiveCap"], 500.0)
        self.assertFalse(info["shouldUseRecommendation"])
        self.assertEqual(info["verdict"], "build-failed")


class PeakNlvTrackerTests(unittest.TestCase):
    """Pin the auto-maintained peak-NLV state file behavior."""

    def test_first_run_records_current_nlv_as_peak(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            state_file = tmp / "state.json"
            with patch.object(cs, "CAPITAL_SCALING_STATE_FILE", state_file):
                state = cs._update_drawdown_state(nlv=5000.0, nlv_age_hours=1.0, now=NOW)
        self.assertEqual(state["peakNlv"], 5000.0)
        self.assertEqual(state["lastNlv"], 5000.0)

    def test_higher_nlv_advances_peak(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            state_file = tmp / "state.json"
            with patch.object(cs, "CAPITAL_SCALING_STATE_FILE", state_file):
                cs._update_drawdown_state(nlv=5000.0, nlv_age_hours=1.0, now=NOW)
                state = cs._update_drawdown_state(
                    nlv=5500.0,
                    nlv_age_hours=1.0,
                    now=NOW + timedelta(days=1),
                )
        self.assertEqual(state["peakNlv"], 5500.0)
        self.assertEqual(state["lastNlv"], 5500.0)

    def test_lower_nlv_preserves_peak(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            state_file = tmp / "state.json"
            with patch.object(cs, "CAPITAL_SCALING_STATE_FILE", state_file):
                cs._update_drawdown_state(nlv=5000.0, nlv_age_hours=1.0, now=NOW)
                state = cs._update_drawdown_state(
                    nlv=4500.0,
                    nlv_age_hours=1.0,
                    now=NOW + timedelta(days=1),
                )
        self.assertEqual(state["peakNlv"], 5000.0)  # peak holds
        self.assertEqual(state["lastNlv"], 4500.0)

    def test_stale_nlv_does_not_advance_peak(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            state_file = tmp / "state.json"
            with patch.object(cs, "CAPITAL_SCALING_STATE_FILE", state_file):
                # Stale (>24h) NLV reading -- ignore for peak purposes.
                state = cs._update_drawdown_state(
                    nlv=10000.0, nlv_age_hours=48.0, now=NOW
                )
        self.assertEqual(state, {})  # nothing persisted

    def test_missing_nlv_does_not_advance_peak(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            state_file = tmp / "state.json"
            with patch.object(cs, "CAPITAL_SCALING_STATE_FILE", state_file):
                state = cs._update_drawdown_state(nlv=None, nlv_age_hours=1.0, now=NOW)
        self.assertEqual(state, {})


class DrawdownStepperTests(unittest.TestCase):
    """Pin the drawdown stepper output for each playbook tier."""

    def test_at_peak_returns_normal(self) -> None:
        out = cs._drawdown_stepper(peak=10_000, current=10_000)
        self.assertEqual(out["level"], "normal")
        self.assertEqual(out["capMultiplier"], 1.0)
        self.assertTrue(out["newEntriesAllowed"])
        self.assertEqual(out["drawdownFraction"], 0.0)

    def test_below_step_1_threshold_returns_normal(self) -> None:
        # 9% drawdown
        out = cs._drawdown_stepper(peak=10_000, current=9_100)
        self.assertEqual(out["level"], "normal")
        self.assertEqual(out["capMultiplier"], 1.0)

    def test_step_1_at_exact_threshold(self) -> None:
        out = cs._drawdown_stepper(peak=10_000, current=9_000)
        self.assertEqual(out["level"], "step-1-half")
        self.assertEqual(out["capMultiplier"], 0.5)

    def test_step_2_at_exact_threshold(self) -> None:
        out = cs._drawdown_stepper(peak=10_000, current=8_000)
        self.assertEqual(out["level"], "step-2-quarter")
        self.assertEqual(out["capMultiplier"], 0.25)

    def test_pause_above_30pct(self) -> None:
        out = cs._drawdown_stepper(peak=10_000, current=6_900)
        self.assertEqual(out["level"], "pause")
        self.assertEqual(out["capMultiplier"], 0.0)
        self.assertFalse(out["newEntriesAllowed"])

    def test_unknown_when_peak_missing(self) -> None:
        out = cs._drawdown_stepper(peak=None, current=5_000)
        self.assertEqual(out["level"], "unknown")
        self.assertEqual(out["capMultiplier"], 1.0)
        self.assertTrue(out["newEntriesAllowed"])

    def test_negative_drawdown_floored_at_zero(self) -> None:
        # NLV exceeds recorded peak (shouldn't happen because peak advances,
        # but guard against arithmetic surprises).
        out = cs._drawdown_stepper(peak=10_000, current=11_000)
        self.assertEqual(out["drawdownFraction"], 0.0)
        self.assertEqual(out["level"], "normal")


class DrawdownCapMultiplierIntegrationTests(unittest.TestCase):
    """The drawdown stepper must shrink the effectiveCap in current_recommended_cap()."""

    def test_step_1_halves_config_cap_when_no_ack(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            sync = _write_sync(tmp, nlv=9_000, generated_at=NOW - timedelta(hours=2))
            state_file = tmp / "state.json"
            # Seed the state file with a peak that puts us at >=10% drawdown.
            state_file.write_text(json.dumps({
                "peakNlv": 10_000,
                "peakNlvAt": (NOW - timedelta(days=1)).isoformat(),
                "lastNlv": 10_000,
                "lastUpdatedAt": (NOW - timedelta(days=1)).isoformat(),
            }), encoding="utf-8")
            with patch.object(cs, "LIVE_ACCOUNT_SYNC_FILE", sync), \
                 patch.object(cs, "CAPITAL_SCALING_ACK_FILE", tmp / "missing.json"), \
                 patch.object(cs, "CAPITAL_SCALING_STATE_FILE", state_file), \
                 patch.object(cs, "MAX_SINGLE_TICKET_DOLLARS", 500.0):
                info = cs.current_recommended_cap(now=NOW)
        self.assertEqual(info["effectiveCap"], 250.0)  # 500 * 0.5
        self.assertEqual(info["drawdownLevel"], "step-1-half")
        self.assertEqual(info["drawdownCapMultiplier"], 0.5)

    def test_pause_zeros_effective_cap(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            sync = _write_sync(tmp, nlv=6_500, generated_at=NOW - timedelta(hours=2))
            state_file = tmp / "state.json"
            state_file.write_text(json.dumps({
                "peakNlv": 10_000,
                "peakNlvAt": (NOW - timedelta(days=1)).isoformat(),
                "lastNlv": 10_000,
                "lastUpdatedAt": (NOW - timedelta(days=1)).isoformat(),
            }), encoding="utf-8")
            with patch.object(cs, "LIVE_ACCOUNT_SYNC_FILE", sync), \
                 patch.object(cs, "CAPITAL_SCALING_ACK_FILE", tmp / "missing.json"), \
                 patch.object(cs, "CAPITAL_SCALING_STATE_FILE", state_file), \
                 patch.object(cs, "MAX_SINGLE_TICKET_DOLLARS", 500.0):
                info = cs.current_recommended_cap(now=NOW)
        self.assertEqual(info["effectiveCap"], 0.0)
        self.assertEqual(info["drawdownLevel"], "pause")
        self.assertFalse(info["newEntriesAllowed"])


class TextRendererTests(unittest.TestCase):
    """Smoke test the operator-facing text report."""

    def test_text_renderer_includes_all_sections(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            sync = _write_sync(tmp, nlv=1108.08, generated_at=NOW - timedelta(hours=4))
            with patch.object(cs, "LIVE_ACCOUNT_SYNC_FILE", sync), \
                 patch.object(cs, "CAPITAL_SCALING_ACK_FILE", tmp / "missing.json"), \
                 patch.object(cs, "MAX_SINGLE_TICKET_DOLLARS", 500.0):
                payload = cs.build_capital_scaling(now=NOW)
        text = cs.capital_scaling_text(payload)
        for required in (
            "Inferno Capital Scaling Recommender",
            "Verdict:",
            "Inputs:",
            "Recommendation:",
            "Currently enforced",
            "Ack status:",
            "Reminders:",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
