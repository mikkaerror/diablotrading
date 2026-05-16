from __future__ import annotations

"""Regression tests for the watchlist autorefresh coordinator.

Contract:
- single tick produces failure-isolated steps
- delta detection compares this tick to the persisted snapshot
- --auto-apply gate is required for the ingest apply step
- dawn-refresh step fires only on delta
- step failure in one branch doesn't abort the others
- ledger entries are bounded to the configured max
- stage constant is research-only
"""

import unittest

import inferno_watchlist_autorefresh as autorefresh


class StageContractTests(unittest.TestCase):
    def test_stage_constant_is_research_only(self) -> None:
        self.assertTrue(autorefresh.WATCHLIST_AUTOREFRESH_STAGE.endswith("research-only"))


def _ok_extractor(tickers):
    def _fn(*_args, **_kwargs):
        return {"tickers": list(tickers), "verdict": "accessibility-ok", "source": "test"}
    return _fn


def _ok_ingester(verdict="preview-only"):
    def _fn(*, mode, confirm):
        return {"mode": mode, "confirm": confirm, "verdict": verdict, "applied": False}
    return _fn


def _ok_reconciler(verdict="clean"):
    def _fn():
        return {"verdict": verdict, "inTosOnly": [], "inSheetOnly": []}
    return _fn


def _fake_dawn():
    return {"breadcrumb": "dawn-request"}


class DeltaDetectionTests(unittest.TestCase):
    def test_no_change_when_snapshot_matches(self) -> None:
        payload = autorefresh.build_autorefresh(
            extractor=_ok_extractor(["NVDA", "AMD"]),
            ingester=_ok_ingester(),
            reconciler=_ok_reconciler(),
            snapshot_loader=lambda: ["NVDA", "AMD"],
            dawn_refresh=_fake_dawn,
        )
        self.assertEqual(payload["verdict"], "no-change")
        self.assertEqual(payload["delta"], [])
        self.assertFalse(payload["hasDelta"])

    def test_delta_detected_surveillance(self) -> None:
        payload = autorefresh.build_autorefresh(
            auto_apply=False,
            extractor=_ok_extractor(["NVDA", "AMD", "AVGO"]),
            ingester=_ok_ingester(),
            reconciler=_ok_reconciler(),
            snapshot_loader=lambda: ["NVDA", "AMD"],
            dawn_refresh=_fake_dawn,
        )
        self.assertEqual(payload["verdict"], "delta-detected")
        self.assertEqual(payload["delta"], ["AVGO"])
        self.assertTrue(payload["hasDelta"])

    def test_delta_applied_with_auto_apply(self) -> None:
        payload = autorefresh.build_autorefresh(
            auto_apply=True,
            extractor=_ok_extractor(["NVDA", "AMD", "AVGO"]),
            ingester=_ok_ingester(verdict="applied"),
            reconciler=_ok_reconciler(),
            snapshot_loader=lambda: ["NVDA", "AMD"],
            dawn_refresh=_fake_dawn,
        )
        self.assertEqual(payload["verdict"], "delta-applied")
        ingest_step = next(step for step in payload["steps"] if step["name"] == "ingest")
        self.assertEqual(ingest_step["result"]["mode"], "apply")
        self.assertTrue(ingest_step["result"]["confirm"])

    def test_departed_tickers_count(self) -> None:
        payload = autorefresh.build_autorefresh(
            extractor=_ok_extractor(["NVDA"]),
            ingester=_ok_ingester(),
            reconciler=_ok_reconciler(),
            snapshot_loader=lambda: ["NVDA", "AMD"],
            dawn_refresh=_fake_dawn,
        )
        self.assertEqual(payload["departed"], ["AMD"])
        self.assertTrue(payload["hasDelta"])


class FailureIsolationTests(unittest.TestCase):
    def test_extractor_failure_isolated(self) -> None:
        def broken_extractor():
            raise RuntimeError("accessibility down")

        payload = autorefresh.build_autorefresh(
            extractor=broken_extractor,
            ingester=_ok_ingester(),
            reconciler=_ok_reconciler(),
            snapshot_loader=lambda: [],
            dawn_refresh=_fake_dawn,
        )
        extract_step = next(step for step in payload["steps"] if step["name"] == "extract")
        self.assertFalse(extract_step["ok"])
        # Reconcile still ran.
        reconcile_step = next(step for step in payload["steps"] if step["name"] == "reconcile")
        self.assertTrue(reconcile_step["ok"])

    def test_step_failure_verdict(self) -> None:
        def broken(*_args, **_kwargs):
            raise RuntimeError("test failure")

        payload = autorefresh.build_autorefresh(
            extractor=broken,
            ingester=broken,
            reconciler=broken,
            snapshot_loader=lambda: [],
            dawn_refresh=_fake_dawn,
        )
        self.assertEqual(payload["verdict"], "step-failures")
        self.assertGreaterEqual(payload["failedCount"], 3)


class TextRenderTests(unittest.TestCase):
    def test_text_surfaces_delta_and_steps(self) -> None:
        payload = autorefresh.build_autorefresh(
            extractor=_ok_extractor(["NVDA", "AVGO"]),
            ingester=_ok_ingester(),
            reconciler=_ok_reconciler(),
            snapshot_loader=lambda: ["NVDA"],
            dawn_refresh=_fake_dawn,
        )
        text = autorefresh.autorefresh_text(payload)
        self.assertIn("Verdict:", text)
        self.assertIn("New tickers this tick", text)
        self.assertIn("- AVGO", text)
        self.assertIn("extract", text)
        self.assertIn("reconcile", text)


if __name__ == "__main__":
    unittest.main()
