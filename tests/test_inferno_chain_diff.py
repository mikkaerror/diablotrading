from __future__ import annotations

"""Regression tests for read-only, thresholded Schwab chain diffs."""

import unittest
from datetime import datetime

import inferno_chain_diff as chain_diff
import inferno_chain_history as chain_history


NOW = datetime.fromisoformat("2026-08-07T07:10:00-06:00")


def descriptor(capture_date: str) -> dict:
    return {
        "captureDate": capture_date,
        "capturedAt": f"{capture_date}T18:30:00-06:00",
        "path": f"chain_history/hot/{capture_date}.json",
    }


def snapshot(capture_date: str, *, spread: float = 0.10, volume: int = 10, open_interest: int = 100, **overrides: object) -> dict:
    payload = {
        "stage": chain_history.CHAIN_HISTORY_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "captureDate": capture_date,
        "source": {
            "stage": chain_history.EXPECTED_SOURCE_STAGE,
            "status": "ok",
        },
        "rows": [
            {
                "symbol": "ORCL",
                "status": "ok",
                "contracts": [
                    {
                        "symbol": "ORCL  260821C00100000",
                        "spreadPct": spread,
                        "volume": volume,
                        "openInterest": open_interest,
                    }
                ],
            }
        ],
    }
    payload.update(overrides)
    return payload


def manifest(*capture_dates: str) -> dict:
    payload = chain_history.empty_manifest()
    payload["hotSnapshots"] = [descriptor(capture_date) for capture_date in capture_dates]
    return payload


class ChainDiffTests(unittest.TestCase):
    """Pin non-actionable source validation and exact threshold semantics."""

    def test_one_valid_snapshot_reports_insufficient_history(self) -> None:
        payload = chain_diff.build_chain_diff(
            manifest=manifest("2026-08-06"),
            snapshots={"2026-08-06": snapshot("2026-08-06")},
            now=NOW,
        )

        self.assertEqual(payload["verdict"], "insufficient-history")
        self.assertEqual(payload["history"]["availableSnapshots"], 1)
        self.assertEqual(payload["counts"]["events"], 0)
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["brokerSubmitAllowed"])
        self.assertIn("data/inferno_chain_history_manifest.json", payload["citations"])

    def test_emits_only_documented_material_contract_changes(self) -> None:
        payload = chain_diff.build_chain_diff(
            manifest=manifest("2026-08-05", "2026-08-06"),
            snapshots={
                "2026-08-05": snapshot("2026-08-05", spread=0.10, volume=10, open_interest=100),
                "2026-08-06": snapshot("2026-08-06", spread=0.13, volume=21, open_interest=111),
            },
            now=NOW,
        )

        self.assertEqual(payload["verdict"], "meaningful-changes")
        self.assertEqual(payload["counts"]["events"], 3)
        self.assertEqual(payload["counts"]["spreadWidened"], 1)
        self.assertEqual(payload["counts"]["volumeSpiked"], 1)
        self.assertEqual(payload["counts"]["openInterestChanged"], 1)
        self.assertEqual(
            {event["type"] for event in payload["events"]},
            {"spread-widened", "volume-spiked", "open-interest-changed"},
        )

    def test_exact_thresholds_remain_quiet(self) -> None:
        payload = chain_diff.build_chain_diff(
            manifest=manifest("2026-08-05", "2026-08-06"),
            snapshots={
                "2026-08-05": snapshot("2026-08-05", spread=0.10, volume=10, open_interest=100),
                "2026-08-06": snapshot("2026-08-06", spread=0.125, volume=20, open_interest=110),
            },
            now=NOW,
        )

        self.assertEqual(payload["verdict"], "no-meaningful-change")
        self.assertEqual(payload["counts"]["events"], 0)

    def test_rejects_invalid_history_before_comparison(self) -> None:
        payload = chain_diff.build_chain_diff(
            manifest=manifest("2026-08-05", "2026-08-06"),
            snapshots={
                "2026-08-05": snapshot("2026-08-05"),
                "2026-08-06": snapshot("2026-08-06", promotable=True),
            },
            now=NOW,
        )

        self.assertEqual(payload["verdict"], "history-invalid")
        self.assertEqual(payload["counts"]["events"], 0)
        self.assertTrue(any("promotable" in item for item in payload["validationErrors"]))

    def test_render_keeps_authority_and_interpretation_boundaries_explicit(self) -> None:
        payload = chain_diff.build_chain_diff(
            manifest=manifest("2026-08-06"),
            snapshots={"2026-08-06": snapshot("2026-08-06")},
            now=NOW,
        )

        rendered = chain_diff.render_chain_diff(payload)

        self.assertIn("non-promotable", rendered)
        self.assertIn("1 / 2 required", rendered)
        self.assertIn("not that a trade is safe", rendered)


if __name__ == "__main__":
    unittest.main()
