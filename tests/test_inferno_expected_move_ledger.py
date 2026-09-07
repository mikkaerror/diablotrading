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
                "tradeDate": "2026-05-01",
                "daysUntilEarnings": 5,
                "strategy": "LONG_STRADDLE",
                "underlyingPrice": 100,
                "entryLimit": 5,
                "lowerBreakEven": 95,
                "upperBreakEven": 105,
                "estimatedMaxLoss": 500,
                "outcome": {
                    "status": "closed",
                    "exitUnderlyingPrice": 130,
                    "estimatedReturnOnRisk": 0.6,
                },
            },
            {
                "ticketId": "miss",
                "ticker": "BBB",
                "tradeDate": "2026-05-01",
                "daysUntilEarnings": 5,
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
                "tradeDate": "2026-05-01",
                "daysUntilEarnings": 5,
                "strategy": "CALL_DEBIT_SPREAD",
                "underlyingPrice": 80,
                "entryLimit": 1.25,
                "outcome": {"status": "closed", "exitUnderlyingPrice": 85},
            },
        ],
    }


def price_history() -> dict:
    return {
        "rows": [
            {
                "symbol": "AAA",
                "candles": [
                    {"datetime": "2026-05-05T05:00:00+00:00", "close": 100},
                    {"datetime": "2026-05-06T05:00:00+00:00", "close": 104},
                    {"datetime": "2026-05-07T05:00:00+00:00", "close": 108},
                ],
            },
            {
                "symbol": "BBB",
                "candles": [
                    {"datetime": "2026-05-05T05:00:00+00:00", "close": 50},
                    {"datetime": "2026-05-07T05:00:00+00:00", "close": 51},
                ],
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
            price_history=price_history(),
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
        self.assertEqual(first["reactionStartDate"], "2026-05-05")
        self.assertEqual(first["reactionEndDate"], "2026-05-07")
        self.assertTrue(first["beatImpliedMove"])
        self.assertTrue(payload["dataIntegrity"]["reliable"])

    def test_current_candidates_surface_missing_prices(self) -> None:
        payload = ledger.build_expected_move_ledger(
            paper_ledger={"items": []},
            shadow_ledger=shadow_ledger(),
            paper_reducer=reducer(),
            price_history=price_history(),
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
            price_history=price_history(),
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
            price_history=price_history(),
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
            price_history=price_history(),
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

    def test_duplicate_snapshots_collapse_to_latest_pre_event_snapshot(self) -> None:
        duplicate = shadow_ledger()["items"][0]
        duplicate = {
            **duplicate,
            "ticketId": "latest",
            "tradeDate": "2026-05-03",
            "daysUntilEarnings": 3,
            "underlyingPrice": 102,
            "lowerBreakEven": 97,
            "upperBreakEven": 107,
            "outcome": {"status": "closed", "estimatedReturnOnRisk": 0.2},
        }

        payload = ledger.build_expected_move_ledger(
            paper_ledger={"items": []},
            shadow_ledger={"items": [shadow_ledger()["items"][0], duplicate]},
            paper_reducer={"scenarioSlate": []},
            price_history=price_history(),
        )

        self.assertEqual(payload["counts"]["sourceClosedLongVolRows"], 2)
        self.assertEqual(payload["counts"]["closedLongVolRecords"], 1)
        self.assertEqual(payload["counts"]["dedupedExcessSnapshots"], 1)
        record = payload["closedRecords"][0]
        self.assertEqual(record["ticketId"], "latest")
        self.assertEqual(record["eventId"], "AAA|2026-05-06")
        self.assertEqual(record["dedupedSnapshotCount"], 2)
        self.assertEqual(record["baselineUnderlyingPrice"], 102)
        self.assertEqual(record["realizedAbsMovePct"], 8.0)

    def test_data_integrity_flags_repeated_and_implausible_realized_moves(self) -> None:
        diagnostics = ledger.data_integrity(
            [
                {"eventId": "AAA|1", "ticker": "AAA", "realizedAbsMovePct": 3.0},
                {"eventId": "AAA|2", "ticker": "AAA", "realizedAbsMovePct": 3.0},
                {"eventId": "AAA|3", "ticker": "AAA", "realizedAbsMovePct": 3.0},
                {"eventId": "BBB|1", "ticker": "BBB", "realizedAbsMovePct": 45.0},
                {"eventId": "BBB|1", "ticker": "BBB", "realizedAbsMovePct": 4.0},
            ]
        )

        self.assertFalse(diagnostics["reliable"])
        self.assertEqual(diagnostics["implausibleMagnitudeRecords"], 1)
        self.assertEqual(diagnostics["frozenRealizedNames"], ["AAA"])
        self.assertEqual(diagnostics["duplicateEventIds"], ["BBB|1"])


if __name__ == "__main__":
    unittest.main()


class PremiumHurdleRebaseTests(unittest.TestCase):
    """Event-move hurdle: per-name history first, event-rebased ATR multiples as fallback."""

    def _entry(self, score: float = 64.0, atr_pct: float = 4.0) -> dict:
        return {"ticker": "ORCL", "scenarioScore": score, "atrPercent": atr_pct}

    def test_three_x_atr_is_no_longer_extreme_on_the_atr_fallback(self) -> None:
        hurdle = ledger.premium_hurdle(entry=self._entry(), implied_pct=12.2, baseline=158.0)
        self.assertEqual(hurdle["hurdleBasis"], ledger.HURDLE_BASIS_ATR)
        self.assertEqual(hurdle["requiredMoveAtrMultiple"], 3.05)
        self.assertEqual(hurdle["label"], "hard")
        self.assertEqual(hurdle["legacyLabel"], "extreme")
        self.assertEqual(hurdle["rankPenalty"], 12.0)
        softer = ledger.premium_hurdle(entry=self._entry(), implied_pct=11.0, baseline=158.0)
        self.assertEqual(softer["label"], "stretch")
        self.assertEqual(softer["legacyLabel"], "hard")

    def test_atr_fallback_ladder_edges(self) -> None:
        for implied, expected in ((7.9, "reasonable"), (8.0, "reasonable"), (12.0, "stretch"), (16.0, "hard"), (16.4, "extreme")):
            hurdle = ledger.premium_hurdle(entry=self._entry(), implied_pct=implied, baseline=100.0)
            self.assertEqual(hurdle["label"], expected, implied)

    def test_curated_name_history_outranks_atr(self) -> None:
        benchmark = {"medianRealizedAbsMovePct": 11.75, "eventCount": 2, "eventSource": ledger.CURATED_EVENT_SOURCE}
        hurdle = ledger.premium_hurdle(entry=self._entry(), implied_pct=12.2, baseline=158.0, benchmark=benchmark)
        self.assertEqual(hurdle["hurdleBasis"], ledger.HURDLE_BASIS_HISTORICAL)
        self.assertAlmostEqual(hurdle["impliedToHistoricalRatio"], 1.0383, places=3)
        self.assertEqual(hurdle["label"], "stretch")
        self.assertEqual(hurdle["legacyLabel"], "extreme")
        rich = ledger.premium_hurdle(entry=self._entry(), implied_pct=20.0, baseline=158.0, benchmark=benchmark)
        self.assertEqual(rich["label"], "extreme")
        cheap = ledger.premium_hurdle(entry=self._entry(), implied_pct=10.0, baseline=158.0, benchmark=benchmark)
        self.assertEqual(cheap["label"], "reasonable")
        self.assertEqual(cheap["rankPenalty"], 0.0)

    def test_inferred_tail_history_is_descriptive_only(self) -> None:
        inferred = {"medianRealizedAbsMovePct": 11.75, "eventCount": 2, "eventSource": "inferred-large-move-volume-surge"}
        hurdle = ledger.premium_hurdle(entry=self._entry(), implied_pct=12.2, baseline=158.0, benchmark=inferred)
        self.assertEqual(hurdle["hurdleBasis"], ledger.HURDLE_BASIS_ATR)
        self.assertIsNone(hurdle["impliedToHistoricalRatio"])
        self.assertIsNone(hurdle["benchmarkMedianRealizedMovePct"])
        self.assertEqual(hurdle["descriptiveTailMedianMovePct"], 11.75)
        self.assertEqual(hurdle["label"], "hard")

    def test_unpriced_and_unknown_stay_penalty_free(self) -> None:
        unpriced = ledger.premium_hurdle(entry=self._entry(), implied_pct=None, baseline=158.0)
        self.assertEqual(unpriced["label"], "unpriced")
        self.assertEqual(unpriced["rankPenalty"], 0.0)
        unknown = ledger.premium_hurdle(entry={"ticker": "ZZZ", "scenarioScore": 50.0}, implied_pct=10.0, baseline=None)
        self.assertEqual(unknown["label"], "unknown")
        self.assertIsNone(unknown["hurdleBasis"])

    def test_candidates_carry_basis_and_use_explicit_benchmarks(self) -> None:
        reducer_payload = {
            "generatedAt": "2026-09-04T16:00:00-06:00",
            "scenarioSlate": [
                {"ticker": "ORCL", "strategy": "LONG_STRADDLE", "scenarioScore": 64.0, "atrPercent": 4.0, "underlyingPrice": 158.0, "lowerBreakEven": 139.0, "upperBreakEven": 177.0}
            ],
        }
        rows = ledger.current_long_vol_candidates(reducer_payload, benchmarks={"ORCL": {"medianRealizedAbsMovePct": 11.75, "eventCount": 2, "eventSource": ledger.CURATED_EVENT_SOURCE}})
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["premiumHurdleBasis"], ledger.HURDLE_BASIS_HISTORICAL)
        self.assertEqual(row["benchmarkEventCount"], 2)
        self.assertIn(row["premiumHurdleLabel"], {"reasonable", "stretch", "hard", "extreme"})
        rows_no_history = ledger.current_long_vol_candidates(reducer_payload, benchmarks={})
        self.assertEqual(rows_no_history[0]["premiumHurdleBasis"], ledger.HURDLE_BASIS_ATR)
