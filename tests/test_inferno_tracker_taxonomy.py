from __future__ import annotations

from datetime import datetime, timedelta
import unittest

import inferno_tracker_taxonomy as taxonomy


NOW = datetime.fromisoformat("2026-07-20T12:00:00-06:00")


def snapshot() -> dict:
    return {"rows": [{"ticker": "NVDA"}, {"ticker": "PWR"}, {"ticker": "MISS"}]}


def edge_cache() -> dict:
    return {
        "tickers": {
            "NVDA": {
                "ticker": "NVDA",
                "shortName": "NVIDIA",
                "sector": "Technology",
                "industry": "Semiconductors",
                "fetchedAt": "2026-07-12T12:00:00-06:00",
                "source": "yfinance",
            },
            "PWR": {
                "ticker": "PWR",
                "shortName": "Quanta Services",
                "sector": "Industrials",
                "industry": "Engineering & Construction",
                "fetchedAt": "2026-07-12T12:00:00-06:00",
                "source": "yfinance",
            },
        }
    }


class InfernoTrackerTaxonomyTests(unittest.TestCase):
    """Protect reference coverage and the no-allocation boundary."""

    def test_build_uses_existing_reference_caches_without_network_refresh(self) -> None:
        report, cache = taxonomy.build_tracker_taxonomy(
            snapshot=snapshot(),
            taxonomy_cache_payload={"tickers": {}},
            edge_cache_payload=edge_cache(),
            ticker_cache_payload={"tickers": {}},
            refresh_missing=False,
            now=NOW,
        )

        self.assertEqual(report["coverage"]["trackedRows"], 3)
        self.assertEqual(report["coverage"]["referenceCoveredRows"], 2)
        self.assertEqual(report["coverage"]["missingSymbols"], ["MISS"])
        nvda = next(item for item in report["entries"] if item["ticker"] == "NVDA")
        self.assertEqual(nvda["economicExposure"], "semiconductors and equipment")
        self.assertIn("edge-metadata-cache", nvda["referenceSource"])
        self.assertEqual(cache, {"tickers": {}})

    def test_build_refreshes_only_missing_reference_rows_with_bound(self) -> None:
        calls: list[str] = []

        def fetcher(symbol: str, *, now: datetime) -> dict:
            calls.append(symbol)
            return {
                "ticker": symbol,
                "shortName": "Missing Co",
                "sector": "Utilities",
                "industry": "Utilities - Regulated Electric",
                "fetchedAt": now.isoformat(),
                "source": "fixture",
            }

        report, cache = taxonomy.build_tracker_taxonomy(
            snapshot=snapshot(),
            taxonomy_cache_payload={"tickers": {}},
            edge_cache_payload=edge_cache(),
            ticker_cache_payload={"tickers": {}},
            refresh_missing=True,
            max_refresh=1,
            now=NOW,
            fetcher=fetcher,
        )

        self.assertEqual(calls, ["MISS"])
        self.assertEqual(report["coverage"]["referenceCoveredRows"], 3)
        self.assertTrue(report["coverage"]["referenceComplete"])
        self.assertEqual(report["refresh"]["refreshedSymbols"], ["MISS"])
        self.assertEqual(cache["tickers"]["MISS"]["source"], "fixture")

    def test_reference_coverage_never_claims_dca_weights_are_ready(self) -> None:
        report, _ = taxonomy.build_tracker_taxonomy(
            snapshot=snapshot(),
            taxonomy_cache_payload={"tickers": {}},
            edge_cache_payload=edge_cache(),
            ticker_cache_payload={"tickers": {}},
            refresh_missing=False,
            now=NOW,
        )

        self.assertTrue(report["researchOnly"])
        self.assertFalse(report["promotable"])
        self.assertFalse(report["authorityChanged"])
        self.assertFalse(report["brokerSubmitAllowed"])
        self.assertFalse(report["liveTradingAllowed"])
        self.assertFalse(report["authorityBoundary"]["targetWeightsProduced"])
        self.assertFalse(report["nextBuildGate"]["readyForDcaWeights"])

    def test_text_explains_reference_and_portfolio_policy_are_different(self) -> None:
        report, _ = taxonomy.build_tracker_taxonomy(
            snapshot=snapshot(),
            taxonomy_cache_payload={"tickers": {}},
            edge_cache_payload=edge_cache(),
            ticker_cache_payload={"tickers": {}},
            refresh_missing=False,
            now=NOW,
        )

        rendered = taxonomy.tracker_taxonomy_text(report)
        self.assertIn("Reference coverage", rendered)
        self.assertIn("does not define portfolio roles, target weights", rendered)

    def test_failed_reference_uses_finite_backoff_without_hiding_the_gap(self) -> None:
        calls: list[str] = []

        def missing_fetcher(symbol: str, *, now: datetime) -> dict:
            calls.append(symbol)
            return {
                "ticker": symbol,
                "shortName": symbol,
                "sector": "Unknown",
                "industry": "Unknown",
                "fetchedAt": now.isoformat(),
                "source": "test",
            }

        report, cache = taxonomy.build_tracker_taxonomy(
            snapshot={"rows": [{"ticker": "MISS"}]},
            taxonomy_cache_payload={"tickers": {}},
            edge_cache_payload={"tickers": {}},
            ticker_cache_payload={"tickers": {}},
            now=NOW,
            fetcher=missing_fetcher,
        )
        self.assertEqual(calls, ["MISS"])
        self.assertEqual(report["coverage"]["missingSymbols"], ["MISS"])
        self.assertEqual(cache["tickers"]["MISS"]["failureCount"], 1)

        deferred, _ = taxonomy.build_tracker_taxonomy(
            snapshot={"rows": [{"ticker": "MISS"}]},
            taxonomy_cache_payload=cache,
            edge_cache_payload={"tickers": {}},
            ticker_cache_payload={"tickers": {}},
            now=NOW + timedelta(minutes=30),
            fetcher=missing_fetcher,
        )
        self.assertEqual(calls, ["MISS"])
        self.assertEqual(deferred["refresh"]["deferredSymbols"], ["MISS"])


if __name__ == "__main__":
    unittest.main()
