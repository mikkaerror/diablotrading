from __future__ import annotations

"""Tests for the research-only scenario observation ledger."""

from datetime import datetime
import unittest

import inferno_scenario_evidence as evidence


def fixed_now(day: int) -> datetime:
    return datetime(2026, 5, day, 9, 30)


def sample_reducer() -> dict:
    return {
        "generatedAt": "2026-05-19T09:00:00-06:00",
        "scenarioSlate": [
            {
                "scenarioId": "2026-05-19:NVDA:auto-paper",
                "rank": 1,
                "ticker": "NVDA",
                "sourceLane": "auto-paper",
                "evidenceLane": "paper-auto-stage",
                "strategy": "CALL_DEBIT_SPREAD",
                "setupRec": "Vertical Call",
                "daysUntilEarnings": 7,
                "scenarioScore": 92.0,
                "marketContextSummary": {"price": 100.0},
            },
            {
                "scenarioId": "2026-05-19:MRVL:shadow",
                "rank": 2,
                "ticker": "MRVL",
                "sourceLane": "tracker-shadow",
                "evidenceLane": "tracker-shadow-scenario",
                "strategy": "LONG_STRADDLE",
                "setupRec": "Straddle",
                "daysUntilEarnings": 12,
                "scenarioScore": 80.0,
            },
        ],
    }


class ScenarioEvidenceTests(unittest.TestCase):
    def test_build_records_research_only_observations(self) -> None:
        prices = {"MRVL": 50.0, "NVDA": 101.0}
        payload = evidence.build_scenario_evidence(
            reducer=sample_reducer(),
            ledger={"observations": []},
            price_lookup=lambda ticker: prices.get(ticker),
            now=fixed_now(19),
        )

        self.assertEqual(payload["sourceScenarioCount"], 2)
        self.assertEqual(payload["counts"]["observations"], 2)
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["brokerSubmitAllowed"])
        self.assertTrue(all(item["safety"]["researchOnly"] for item in payload["observations"]))
        self.assertEqual(payload["observations"][0]["baselineUnderlyingPrice"], 100.0)
        self.assertEqual(payload["observations"][1]["baselineUnderlyingPrice"], 50.0)

    def test_review_closes_due_call_observation_as_favorable(self) -> None:
        initial = evidence.build_scenario_evidence(
            reducer=sample_reducer(),
            ledger={"observations": []},
            price_lookup=lambda ticker: {"NVDA": 100.0, "MRVL": 50.0}.get(ticker),
            now=fixed_now(19),
        )
        reviewed = evidence.build_scenario_evidence(
            reducer={"scenarioSlate": []},
            ledger=initial,
            price_lookup=lambda ticker: {"NVDA": 103.0, "MRVL": 50.0}.get(ticker),
            now=fixed_now(20),
        )

        nvda = next(item for item in reviewed["observations"] if item["ticker"] == "NVDA")
        self.assertEqual(nvda["outcome"]["status"], "closed")
        self.assertEqual(nvda["outcome"]["resultClass"], "favorable")
        self.assertEqual(nvda["outcome"]["underlyingReturnPct"], 3.0)

    def test_straddle_rewards_absolute_movement(self) -> None:
        result, score, note = evidence.classify_move("STRADDLE", -3.2)

        self.assertEqual(result, "favorable")
        self.assertEqual(score, 3.2)
        self.assertIn("movement", note)

    def test_closed_observations_are_preserved(self) -> None:
        closed = {
            "observations": [
                {
                    "observationId": "closed-1",
                    "ticker": "NVDA",
                    "tradeDate": "2026-05-19",
                    "family": "CALL_VERTICAL",
                    "baselineUnderlyingPrice": 100,
                    "outcome": {"status": "closed", "observationScore": 2.0, "resultClass": "favorable"},
                }
            ]
        }
        payload = evidence.build_scenario_evidence(
            reducer={"scenarioSlate": []},
            ledger=closed,
            price_lookup=lambda ticker: 90.0,
            now=fixed_now(21),
        )

        item = payload["observations"][0]
        self.assertEqual(item["outcome"]["status"], "closed")
        self.assertEqual(item["outcome"]["observationScore"], 2.0)


if __name__ == "__main__":
    unittest.main()
