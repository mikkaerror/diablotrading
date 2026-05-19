from __future__ import annotations

"""Tests for the research-only scenario backtest scorecard."""

import unittest

import inferno_scenario_backtest as backtest


def sample_reducer() -> dict:
    return {
        "generatedAt": "2026-05-19T10:00:00-06:00",
        "scenarioSlate": [
            {
                "rank": 1,
                "ticker": "MOD",
                "sourceLane": "auto-paper",
                "evidenceLane": "paper-auto-stage",
                "strategy": "CALL_DEBIT_SPREAD",
                "setupRec": "Vertical Call",
                "daysUntilEarnings": 7,
                "scenarioScore": 81.04,
                "executableInPaperMoney": True,
            },
            {
                "rank": 2,
                "ticker": "MRVL",
                "sourceLane": "near-miss",
                "evidenceLane": "shadow-scenario",
                "strategy": "LONG_STRADDLE",
                "setupRec": "Straddle",
                "daysUntilEarnings": 8,
                "scenarioScore": 70.39,
                "shadowOnly": True,
            },
        ],
    }


def closed_shadow() -> dict:
    return {
        "items": [
            {
                "ticketId": "s1",
                "ticker": "MOD",
                "strategy": "CALL_DEBIT_SPREAD",
                "setupRec": "Vertical Call",
                "daysUntilEarnings": 6,
                "outcome": {"status": "closed", "estimatedReturnOnRisk": 0.8, "estimatedPnl": 80},
            },
            {
                "ticketId": "s2",
                "ticker": "THR",
                "strategy": "CALL_DEBIT_SPREAD",
                "setupRec": "Vertical Call",
                "daysUntilEarnings": 5,
                "outcome": {"status": "closed", "estimatedReturnOnRisk": 0.4, "estimatedPnl": 40},
            },
            {
                "ticketId": "s3",
                "ticker": "AVGO",
                "strategy": "CALL_DEBIT_SPREAD",
                "setupRec": "Vertical Call",
                "daysUntilEarnings": 10,
                "outcome": {"status": "closed", "estimatedReturnOnRisk": -0.2, "estimatedPnl": -20},
            },
            {
                "ticketId": "s4",
                "ticker": "MRVL",
                "strategy": "LONG_STRADDLE",
                "setupRec": "Straddle",
                "daysUntilEarnings": 8,
                "outcome": {"status": "open"},
            },
        ],
    }


def closed_paper() -> dict:
    return {
        "items": [
            {
                "ticketId": "p1",
                "ticker": "CEG",
                "strategy": "CALL_DEBIT_SPREAD",
                "setupRec": "Vertical Call",
                "daysUntilEarnings": 4,
                "riskVerdict": {"metrics": {"maxLossDollars": 100}},
                "outcome": {"status": "closed", "estimatedPnl": 50},
            }
        ],
    }


class ScenarioBacktestTests(unittest.TestCase):
    """Scenario backtest should stay descriptive and authority-safe."""

    def test_closed_evidence_records_normalize_paper_and_shadow(self) -> None:
        records = backtest.closed_evidence_records(
            paper_ledger=closed_paper(),
            shadow_ledger=closed_shadow(),
        )

        self.assertEqual(len(records), 4)
        self.assertTrue(any(record["source"] == "paper" for record in records))
        self.assertTrue(any(record["ticker"] == "MOD" for record in records))
        self.assertEqual(backtest.strategy_family("CALL_DEBIT_SPREAD"), "CALL_VERTICAL")

    def test_scenario_scorecard_uses_most_specific_useful_scope(self) -> None:
        payload = backtest.build_scenario_backtest(
            reducer=sample_reducer(),
            paper_ledger=closed_paper(),
            shadow_ledger=closed_shadow(),
        )

        mod = payload["scorecards"][0]
        mrvl = payload["scorecards"][1]

        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["liveTradingAllowed"])
        self.assertEqual(mod["ticker"], "MOD")
        self.assertEqual(mod["bestEvidenceScope"], "familyAndWindow")
        self.assertEqual(mod["headlineStats"]["sampleCount"], 3)
        self.assertIn(mod["evidenceVerdict"], {"supportive", "mixed"})
        self.assertEqual(mrvl["evidenceVerdict"], "insufficient-data")

    def test_text_report_renders_top_focus(self) -> None:
        payload = backtest.build_scenario_backtest(
            reducer=sample_reducer(),
            paper_ledger=closed_paper(),
            shadow_ledger=closed_shadow(),
        )
        rendered = backtest.scenario_backtest_text(payload)

        self.assertIn("Inferno Scenario Backtest", rendered)
        self.assertIn("Top focus scorecards", rendered)
        self.assertIn("MOD", rendered)


if __name__ == "__main__":
    unittest.main()
