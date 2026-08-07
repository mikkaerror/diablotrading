from __future__ import annotations

"""Tests for bounded, research-only supplemental strategy quote coverage."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_strategy_quote_coverage as coverage


def scorer_payload() -> dict:
    return {
        "scorecards": [
            {
                "ticker": "AAA",
                "longVolPressureScore": 70,
                "recommendation": {"strategy": "PUT_CREDIT_SPREAD", "verdict": "prefer-alternative-research"},
            },
            {
                "ticker": "BBB",
                "longVolPressureScore": 50,
                "recommendation": {"strategy": "CALL_DEBIT_SPREAD", "verdict": "compare-in-paper"},
            },
        ]
    }


def primary_report() -> dict:
    return {
        "generatedAt": "2026-05-01T12:00:00+00:00",
        "status": "ok",
        "configured": True,
        "researchOnly": True,
        "rows": [{"symbol": "AAA", "contracts": [{"symbol": "AAA contract"}]}],
    }


def cap_fit_blocker_swarm() -> dict:
    return {
        "candidateFindings": [
            {
                "ticker": "CAP",
                "strategy": "LONG_STRADDLE",
                "strategyFallbackSuggested": True,
                "priorityScore": 55,
                "capFit": {
                    "fits": {"straddle": False, "debit_5w": True},
                    "structures": {"straddle": 900, "debit_5w": 250},
                },
            }
        ]
    }


def cap_fit_reducer() -> dict:
    return {
        "scenarioSlate": [
            {
                "ticker": "CAP",
                "price": 50,
                "marketContextSummary": {"trend": "Bullish"},
            }
        ]
    }


class StrategyQuoteCoverageTests(unittest.TestCase):
    def test_fetches_only_uncovered_pricing_candidates_with_bounded_cap(self) -> None:
        calls: list[list[str]] = []

        def report_builder(symbols: list[str]) -> dict:
            calls.append(symbols)
            return {
                "generatedAt": "2026-05-01T12:05:00+00:00",
                "stage": "schwab-options-read-only",
                "status": "ok",
                "rows": [{"symbol": "BBB", "contracts": [{"symbol": "BBB contract"}]}],
                "errors": [],
            }

        payload = coverage.build_strategy_quote_coverage(
            scorer=scorer_payload(),
            paper_variant_scanner={"pricingCandidates": []},
            primary_report=primary_report(),
            limit=2,
            variants_per_ticker=1,
            supplemental_limit=1,
            report_builder=report_builder,
            environment_loader=lambda: {},
        )

        self.assertEqual(calls, [["BBB"]])
        self.assertEqual(payload["targets"], ["BBB"])
        self.assertEqual(payload["counts"]["primaryCoveredTickers"], 1)
        self.assertEqual(payload["counts"]["missingTickerGroups"], 1)
        self.assertEqual(payload["chainSource"], coverage.SUPPLEMENTAL_CHAIN_SOURCE)
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["brokerSubmitAllowed"])
        self.assertFalse(payload["liveTradingAllowed"])

    def test_cap_fit_fallbacks_share_the_pricing_slate_and_supplemental_cap(self) -> None:
        calls: list[list[str]] = []

        def report_builder(symbols: list[str]) -> dict:
            calls.append(symbols)
            return {
                "generatedAt": "2026-05-01T12:05:00+00:00",
                "stage": "schwab-options-read-only",
                "status": "ok",
                "rows": [],
                "errors": [],
            }

        payload = coverage.build_strategy_quote_coverage(
            scorer=scorer_payload(),
            paper_variant_scanner={"pricingCandidates": []},
            paper_blocker_swarm=cap_fit_blocker_swarm(),
            reducer=cap_fit_reducer(),
            primary_report=primary_report(),
            limit=2,
            variants_per_ticker=1,
            supplemental_limit=1,
            report_builder=report_builder,
            environment_loader=lambda: {},
        )

        self.assertEqual(payload["counts"]["pricingCandidateRows"], 3)
        self.assertEqual(payload["counts"]["pricingCandidateTickers"], 3)
        self.assertEqual(payload["candidateTickers"], ["CAP", "AAA", "BBB"])
        self.assertEqual(payload["targets"], ["CAP"])
        self.assertEqual(calls, [["CAP"]])
        self.assertEqual(
            payload["sourceLineage"]["candidateInputs"]["paperBlockerSwarmGeneratedAt"],
            None,
        )
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["brokerSubmitAllowed"])
        self.assertFalse(payload["liveTradingAllowed"])

    def test_skips_network_when_primary_tape_covers_entire_pricing_slate(self) -> None:
        primary = primary_report()
        primary["rows"].append({"symbol": "BBB", "contracts": [{"symbol": "BBB contract"}]})

        payload = coverage.build_strategy_quote_coverage(
            scorer=scorer_payload(),
            paper_variant_scanner={"pricingCandidates": []},
            primary_report=primary,
            limit=2,
            variants_per_ticker=1,
            report_builder=lambda symbols: self.fail(f"unexpected coverage fetch: {symbols}"),
            environment_loader=lambda: self.fail("unexpected environment load"),
        )

        self.assertEqual(payload["status"], "no-gap")
        self.assertEqual(payload["targets"], [])
        self.assertEqual(payload["counts"]["requestedSupplementalTickers"], 0)

    def test_loader_rejects_non_research_artifacts_and_preserves_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "coverage.json"
            path.write_text(
                json.dumps(
                    {
                        "stage": coverage.STRATEGY_QUOTE_COVERAGE_STAGE,
                        "researchOnly": True,
                        "promotable": False,
                        "authorityChanged": False,
                        "brokerSubmitAllowed": False,
                        "liveTradingAllowed": False,
                        "generatedAt": "now",
                        "status": "ok",
                        "rows": [{"symbol": "BBB", "contracts": [{"symbol": "BBB contract"}]}],
                    }
                ),
                encoding="utf-8",
            )
            index = coverage.load_supplemental_schwab_options_index(path)
            self.assertEqual(index["BBB"]["chainSource"], coverage.SUPPLEMENTAL_CHAIN_SOURCE)
            self.assertEqual(index["BBB"]["sourceGeneratedAt"], "now")

            path.write_text(json.dumps({"researchOnly": False, "authorityChanged": False, "rows": []}), encoding="utf-8")
            self.assertEqual(coverage.load_supplemental_schwab_options_index(path), {})

            path.write_text(
                json.dumps(
                    {
                        "stage": coverage.STRATEGY_QUOTE_COVERAGE_STAGE,
                        "researchOnly": True,
                        "promotable": False,
                        "authorityChanged": False,
                        "brokerSubmitAllowed": True,
                        "liveTradingAllowed": False,
                        "rows": [],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(coverage.load_supplemental_schwab_options_index(path), {})

    def test_text_memo_keeps_read_only_authority_boundary_visible(self) -> None:
        rendered = coverage.strategy_quote_coverage_text(
            {
                "generatedAt": "now",
                "stage": coverage.STRATEGY_QUOTE_COVERAGE_STAGE,
                "status": "ok",
                "counts": {"pricingCandidateRows": 2, "pricingCandidateTickers": 2},
                "targets": ["BBB"],
                "reminders": ["read-only market-data lane"],
            }
        )

        self.assertIn("Authority: research-only", rendered)
        self.assertIn("BBB", rendered)
