from __future__ import annotations

"""Regression tests for the hypothesis ledger.

Contract:
- new hypotheses get trajectory ``new``
- repeat hypotheses with bumped Wilson lower bound get ``strengthening``
- repeat hypotheses with dropped Wilson lower bound get ``weakening``
- hypotheses absent today get trajectory ``abandoned``
- ledger is append-only and atomic
- research-only, never promotable
"""

import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import inferno_hypothesis_ledger as hl


def _hypothesis(
    hid: str,
    wilson_lower: float,
    *,
    template: str = "dimension-edge",
    sample_size: int = 8,
    test_confidence: float = 0.6,
) -> dict:
    """Build a lab-shaped hypothesis dict for tests."""
    return {
        "id": hid,
        "template": template,
        "claim": f"hypothesis {hid}",
        "cell": {"strategy": "LONG_STRADDLE", "regime": "bullish-normal"},
        "suggestedAction": "tighten-filter-to-cell",
        "testConfidence": test_confidence,
        "stats": {
            "sampleSize": sample_size,
            "winRate": 0.6,
            "winRateLower": wilson_lower,
            "winRateUpper": 0.9,
            "expectancyMean": 0.5,
            "expectancyLower": 0.1,
            "profitFactor": 2.0,
        },
    }


class LedgerUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "ledger.json"
        patcher = mock.patch.object(hl, "LEDGER_ARTIFACT_FILE", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_first_appearance_is_new(self) -> None:
        payload = hl.update_ledger(
            [_hypothesis("h1", 0.4)],
            now=datetime(2026, 5, 10, 8, 0),
        )
        record = payload["hypotheses"]["h1"]
        self.assertEqual(record["currentTrajectory"], "new")
        self.assertEqual(record["reproductionCount"], 1)
        self.assertEqual(payload["trajectorySummary"]["new"], 1)

    def test_strengthening_when_lower_bound_rises(self) -> None:
        hl.update_ledger(
            [_hypothesis("h1", 0.40)],
            now=datetime(2026, 5, 10, 8, 0),
        )
        payload = hl.update_ledger(
            [_hypothesis("h1", 0.55)],
            now=datetime(2026, 5, 11, 8, 0),
        )
        record = payload["hypotheses"]["h1"]
        self.assertEqual(record["currentTrajectory"], "strengthening")
        self.assertEqual(record["reproductionCount"], 2)
        self.assertEqual(payload["trajectorySummary"]["strengthening"], 1)

    def test_weakening_when_lower_bound_falls(self) -> None:
        hl.update_ledger(
            [_hypothesis("h1", 0.55)],
            now=datetime(2026, 5, 10, 8, 0),
        )
        payload = hl.update_ledger(
            [_hypothesis("h1", 0.40)],
            now=datetime(2026, 5, 11, 8, 0),
        )
        record = payload["hypotheses"]["h1"]
        self.assertEqual(record["currentTrajectory"], "weakening")

    def test_stable_inside_noise_band(self) -> None:
        hl.update_ledger(
            [_hypothesis("h1", 0.50)],
            now=datetime(2026, 5, 10, 8, 0),
        )
        payload = hl.update_ledger(
            [_hypothesis("h1", 0.51)],
            now=datetime(2026, 5, 11, 8, 0),
        )
        self.assertEqual(payload["hypotheses"]["h1"]["currentTrajectory"], "stable")

    def test_missing_hypothesis_is_abandoned(self) -> None:
        hl.update_ledger(
            [_hypothesis("h1", 0.5), _hypothesis("h2", 0.5)],
            now=datetime(2026, 5, 10, 8, 0),
        )
        payload = hl.update_ledger(
            [_hypothesis("h1", 0.55)],
            now=datetime(2026, 5, 11, 8, 0),
        )
        self.assertEqual(payload["hypotheses"]["h2"]["currentTrajectory"], "abandoned")
        self.assertEqual(payload["trajectorySummary"]["abandoned"], 1)

    def test_history_is_capped(self) -> None:
        with mock.patch.object(hl, "MAX_HISTORY_PER_ID", 3):
            for index in range(5):
                hl.update_ledger(
                    [_hypothesis("h1", 0.5 + index * 0.001)],
                    now=datetime(2026, 5, 10 + index, 8, 0),
                )
            payload = json.loads(self.path.read_text())
            history = payload["hypotheses"]["h1"]["history"]
            self.assertEqual(len(history), 3)

    def test_atomic_write_persists_payload(self) -> None:
        hl.update_ledger([_hypothesis("h1", 0.5)], now=datetime(2026, 5, 10, 8, 0))
        on_disk = json.loads(self.path.read_text())
        self.assertIn("h1", on_disk["hypotheses"])


class LedgerReportTests(unittest.TestCase):
    def test_report_classifies_trajectories(self) -> None:
        payload = {
            "hypotheses": {
                "stronger": {
                    "id": "stronger",
                    "currentTrajectory": "strengthening",
                    "reproductionCount": 3,
                    "currentTestConfidence": 0.7,
                    "currentStats": {"winRate": 0.7, "winRateLower": 0.5, "winRateUpper": 0.9},
                    "claim": "stronger claim",
                },
                "weaker": {
                    "id": "weaker",
                    "currentTrajectory": "weakening",
                    "reproductionCount": 2,
                    "currentTestConfidence": 0.4,
                    "currentStats": {"winRate": 0.3, "winRateLower": 0.1, "winRateUpper": 0.5},
                    "claim": "weaker claim",
                },
            }
        }
        report = hl.build_ledger_report(payload=payload, now=datetime(2026, 5, 11, 8, 0))
        self.assertEqual(report["trajectoryCounts"]["strengthening"], 1)
        self.assertEqual(report["trajectoryCounts"]["weakening"], 1)
        self.assertTrue(report["researchOnly"])
        self.assertFalse(report["promotable"])

    def test_text_renderer_includes_each_section(self) -> None:
        payload = {
            "hypotheses": {
                "h1": {
                    "id": "h1",
                    "currentTrajectory": "strengthening",
                    "reproductionCount": 4,
                    "currentTestConfidence": 0.6,
                    "currentStats": {"winRate": 0.6, "winRateLower": 0.4, "winRateUpper": 0.8},
                    "claim": "stronger claim",
                },
            }
        }
        report = hl.build_ledger_report(payload=payload, now=datetime(2026, 5, 11, 8, 0))
        rendered = hl.ledger_text(report)
        self.assertIn("Hypothesis Ledger", rendered)
        self.assertIn("Strengthening", rendered)


if __name__ == "__main__":
    unittest.main()
