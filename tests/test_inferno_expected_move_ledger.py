from __future__ import annotations

"""Tests for the research-only expected-move ledger."""

import unittest

import inferno_expected_move_ledger as ledger


def shadow_ledger() -> dict:
    return {
        "items": [
            {
                "ticketId": "win",
                "ticker": "AAA",
                "strategy": "LONG_STRADDLE",
                "underlyingPrice": 100,
                "entryLimit": 5,
                "lowerBreakEven": 95,
                "upperBreakEven": 105,
                "estimatedMaxLoss": 500,
                "outcome": {
                    "status": "closed",
                    "exitUnderlyingPrice": 108,
                    "estimatedReturnOnRisk": 0.6,
                },
            },
            {
                "ticketId": "miss",
                "ticker": "BBB",
                "strategy": "LONG_STRANGLE",
                "underlyingPrice": 50,
                "entryLimit": 2,
                "estimatedMaxLoss": 200,
                "outcome": {
                    "status": "closed",
                    "exitUnderlyingPrice": 51,
                    "estimatedReturnOnRisk": -0.4,
                },
            },
            {
                "ticketId": "vertical",
                "ticker": "CCC",
                "strategy": "CALL_DEBIT_SPREAD",
                "underlyingPrice": 80,
                "entryLimit": 1.25,
                "outcome": {"status": "closed", "exitUnderlyingPrice": 85},
            },
        ],
    }


def reducer() -> dict:
    return {
        "scenarioSlate": [
            {
                "rank": 1,
                "ticker": "PL",
                "strategy": "LONG_STRANGLE",
                "readiness": 83,
                "scenarioScore": 60.21,
                "estimatedMaxLoss": 500,
                "paperAutoSelected": True,
                "brokerSubmitAllowed": False,
                "liveTradingAllowed": False,
            },
            {
                "rank": 2,
                "ticker": "XYZ",
                "strategy": "LONG_STRADDLE",
                "underlyingPrice": 40,
                "entryLimit": 4,
                "scenarioScore": 70,
                "marketContextSummary": {"atrPercent": 2.0},
                "brokerSubmitAllowed": False,
                "liveTradingAllowed": False,
            },
        ],
    }


class ExpectedMoveLedgerTests(unittest.TestCase):
    """Expected-move math should stay clear and authority-safe."""

    def test_closed_records_measure_realized_move_against_implied_move(self) -> None:
        payload = ledger.build_expected_move_ledger(
            paper_ledger={"items": []},
            shadow_ledger=shadow_ledger(),
            paper_reducer=reducer(),
        )

        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["liveTradingAllowed"])
        self.assertEqual(payload["counts"]["closedLongVolRecords"], 2)
        self.assertEqual(payload["overall"]["beatCount"], 1)
        self.assertEqual(payload["overall"]["beatRate"], 0.5)
        first = payload["closedRecords"][0]
        self.assertEqual(first["impliedMoveSource"], "breakeven-min")
        self.assertEqual(first["impliedMovePct"], 5.0)
        self.assertEqual(first["realizedAbsMovePct"], 8.0)
        self.assertTrue(first["beatImpliedMove"])

    def test_current_candidates_surface_missing_prices(self) -> None:
        payload = ledger.build_expected_move_ledger(
            paper_ledger={"items": []},
            shadow_ledger=shadow_ledger(),
            paper_reducer=reducer(),
        )

        self.assertEqual(payload["counts"]["currentLongVolCandidates"], 2)
        self.assertEqual(payload["counts"]["currentPricedCandidates"], 1)
        missing = next(item for item in payload["currentCandidates"] if item["ticker"] == "PL")
        self.assertEqual(missing["status"], "missing-underlying-price")
        self.assertEqual(missing["premiumHurdleLabel"], "unpriced")

    def test_current_candidates_get_premium_hurdle_pressure(self) -> None:
        payload = ledger.build_expected_move_ledger(
            paper_ledger={"items": []},
            shadow_ledger=shadow_ledger(),
            paper_reducer=reducer(),
        )

        xyz = next(item for item in payload["currentCandidates"] if item["ticker"] == "XYZ")

        self.assertEqual(xyz["premiumHurdleLabel"], "extreme")
        self.assertEqual(xyz["requiredMoveAtrMultiple"], 5.0)
        self.assertEqual(xyz["rankPenalty"], 20.0)
        self.assertEqual(xyz["rankPressureScore"], 50.0)
        self.assertEqual(payload["currentHurdleCounts"], {"extreme": 1, "unpriced": 1})
        self.assertEqual(payload["counts"]["currentPremiumPressured"], 1)

    def test_text_report_renders_core_sections(self) -> None:
        payload = ledger.build_expected_move_ledger(
            paper_ledger={"items": []},
            shadow_ledger=shadow_ledger(),
            paper_reducer=reducer(),
        )
        rendered = ledger.expected_move_ledger_text(payload)

        self.assertIn("Inferno Expected Move Ledger", rendered)
        self.assertIn("Closed long-vol expected-move summary", rendered)
        self.assertIn("Current long-vol candidates", rendered)
        self.assertIn("Regime and evidence diagnostics", rendered)
        self.assertIn("research-only", rendered)

    def test_regime_diagnostics_surface_concentration_recency_and_quality(self) -> None:
        payload = ledger.build_expected_move_ledger(
            paper_ledger={"items": []},
            shadow_ledger=shadow_ledger(),
            paper_reducer={"scenarioSlate": []},
        )
        diagnostics = payload["regimeDiagnostics"]

        self.assertFalse(diagnostics["causalClaimAllowed"])
        self.assertFalse(diagnostics["promotionEvidenceEligible"])
        self.assertEqual(
            diagnostics["concentration"]["topPositiveContributorTickers"],
            ["AAA"],
        )
        self.assertEqual(len(diagnostics["chronologicalCohorts"]), 2)
        self.assertEqual(
            [row["bucket"] for row in diagnostics["impliedMoveBuckets"]],
            ["0-10%"],
        )


if __name__ == "__main__":
    unittest.main()
