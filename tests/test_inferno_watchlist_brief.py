from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import inferno_watchlist_brief as brief
from inferno_doctor import watchlist_brief_status


NOW = datetime.fromisoformat("2026-08-10T09:00:00-06:00")
EDGE = {
    "generatedAt": "2026-08-10T08:00:00-06:00",
    "researchWatchlist": [
        {"ticker": "ALPHA", "edgeScore": 88, "category": "Data Rails", "signalTrigger": True},
        {"ticker": "BETA", "edgeScore": 81, "category": "Compute", "signalTrigger": True},
        {"ticker": "GAMMA", "edgeScore": 75, "category": "Networking", "signalTrigger": True},
    ],
    "ranked": [
        {"ticker": "ALPHA", "edgeScore": 88, "category": "Data Rails", "signalTrigger": True},
        {"ticker": "BETA", "edgeScore": 81, "category": "Compute", "signalTrigger": True},
        {"ticker": "GAMMA", "edgeScore": 75, "category": "Networking", "signalTrigger": True},
    ],
}
CONVICTION = {
    "generatedAt": "2026-08-10T08:00:00-06:00",
    "ranked": [
        {
            "ticker": "ALPHA", "category": "Data Rails", "convictionAdjustedScore": 72,
            "evidenceGrade": "B", "signalTrigger": True, "readiness": 93,
            "daysUntilEarnings": 40, "researchAction": "inventory watchlist",
            "thesis": "ALPHA has broad support.", "riskFlags": [],
        },
        {
            "ticker": "BETA", "category": "Compute", "convictionAdjustedScore": 61,
            "evidenceGrade": "C", "signalTrigger": True, "readiness": 87,
            "daysUntilEarnings": 3, "researchAction": "manual thesis review",
            "thesis": "BETA reports soon.", "riskFlags": ["near resistance"],
        },
        {
            "ticker": "GAMMA", "category": "Networking", "convictionAdjustedScore": 57,
            "evidenceGrade": "C", "signalTrigger": True, "readiness": 85,
            "daysUntilEarnings": 30, "researchAction": "watch only",
            "thesis": "GAMMA needs confirmation.", "riskFlags": ["market context fallback"],
        },
    ],
}


class WatchlistBriefTests(unittest.TestCase):
    def test_current_tracker_priorities_are_compact_and_authority_safe(self) -> None:
        report = brief.build_watchlist_brief(
            edge_research=EDGE,
            conviction_research=CONVICTION,
            watchlist_input={"source": "tos-live-positions-2026-05-20", "tickers": ["ALPHA"]},
            limit=2,
            now=NOW,
        )
        self.assertEqual(report["stage"], brief.WATCHLIST_BRIEF_STAGE)
        self.assertEqual(report["verdict"], "ready")
        self.assertTrue(report["researchOnly"])
        self.assertFalse(report["promotable"])
        self.assertFalse(report["authorityChanged"])
        self.assertFalse(report["brokerSubmitAllowed"])
        self.assertFalse(report["liveTradingAllowed"])
        self.assertEqual(report["watchlistSource"]["kind"], "current-tracker-research-priorities")
        self.assertEqual([row["ticker"] for row in report["focus"]], ["ALPHA", "BETA"])
        self.assertEqual(report["focus"][0]["label"], "RESEARCH FIRST")
        self.assertEqual(report["focus"][1]["label"], "WAIT FOR EVENT")
        self.assertFalse(report["savedInputStatus"]["usableForOrdering"])
        self.assertIn("position-derived", report["savedInputStatus"]["reason"])
        self.assertTrue(watchlist_brief_status(report)[0])

    def test_fresh_explicit_watchlist_limits_the_rows_without_creating_a_signal(self) -> None:
        report = brief.build_watchlist_brief(
            edge_research=EDGE,
            conviction_research=CONVICTION,
            watchlist_input={"source": "operator-watchlist-2026-08-10", "tickers": ["GAMMA", "ALPHA"]},
            limit=3,
            now=NOW,
        )
        self.assertEqual(report["watchlistSource"]["kind"], "operator-watchlist-input")
        self.assertEqual([row["ticker"] for row in report["focus"]], ["ALPHA", "GAMMA"])
        self.assertEqual(report["focus"][0]["label"], "RESEARCH FIRST")
        self.assertEqual(report["focus"][1]["label"], "KEEP ON WATCH")
        rendered = brief.watchlist_brief_text(report).lower()
        self.assertIn("not orders", rendered)
        self.assertNotIn("buy now", rendered)

    def test_builder_does_not_mutate_source_artifacts(self) -> None:
        before = json.dumps([EDGE, CONVICTION], sort_keys=True)
        brief.build_watchlist_brief(
            edge_research=EDGE,
            conviction_research=CONVICTION,
            watchlist_input={},
            now=NOW,
        )
        after = json.dumps([EDGE, CONVICTION], sort_keys=True)
        self.assertEqual(before, after)

    def test_save_writes_only_its_own_artifacts(self) -> None:
        report = brief.build_watchlist_brief(
            edge_research=EDGE,
            conviction_research=CONVICTION,
            watchlist_input={},
            now=NOW,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                patch.object(brief, "WATCHLIST_BRIEF_FILE", root / "brief.json"),
                patch.object(brief, "WATCHLIST_BRIEF_TEXT_FILE", root / "brief.txt"),
            ):
                brief.save_watchlist_brief(report)
            self.assertTrue((root / "brief.json").exists())
            self.assertTrue((root / "brief.txt").exists())


if __name__ == "__main__":
    unittest.main()
