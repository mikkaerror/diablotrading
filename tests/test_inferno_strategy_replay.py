from __future__ import annotations

"""Regression tests for the research-only strategy replay.

The replay must:
- never set ``promotable=True`` regardless of inputs
- never set ``researchOnly=False``
- correctly normalize shadow items so closed outcomes are visible to the lab
- write output to a clearly-distinct artifact path
"""

import unittest

from inferno_strategy_replay import (
    REPLAY_ARTIFACT_FILE,
    REPLAY_STAGE,
    REPLAY_TEXT_FILE,
    build_replay,
    normalize_shadow_item,
    replay_text,
)


def shadow_item(ticker: str, pnl: float | None, max_loss: float = 100.0,
                strategy: str = "CALL_DEBIT_SPREAD") -> dict:
    return {
        "ticketId": f"shadow-{ticker}",
        "ticker": ticker,
        "strategy": strategy,
        "status": "shadow-closed" if pnl is not None else "shadow-open",
        "riskVerdict": {"metrics": {"maxLossDollars": max_loss}},
        "outcome": {
            "status": "closed" if pnl is not None else "open",
            "estimatedPnl": pnl,
            "reviewedAt": "2026-04-27T09:00:00-06:00",
        },
    }


class StrategyReplayTests(unittest.TestCase):
    """Verify the replay stays research-only and faithfully wraps the lab."""

    def test_artifact_paths_are_distinct_from_real_lab(self) -> None:
        """The replay must not collide with the real lab artifact."""
        self.assertTrue(str(REPLAY_ARTIFACT_FILE).endswith("inferno_strategy_replay.json"))
        self.assertTrue(str(REPLAY_TEXT_FILE).endswith("strategy_replay_latest.txt"))
        self.assertEqual(REPLAY_STAGE, "shadow-replay-research-only")

    def test_normalize_shadow_item_retags_closed_status(self) -> None:
        item = shadow_item("FOO", pnl=10.0)
        normalized = normalize_shadow_item(item)
        self.assertEqual(normalized["status"], "paper-staged-replay")
        # The original must not be mutated.
        self.assertEqual(item["status"], "shadow-closed")

    def test_normalize_shadow_item_retags_open_status(self) -> None:
        item = shadow_item("BAR", pnl=None)
        normalized = normalize_shadow_item(item)
        self.assertEqual(normalized["status"], "shadow-open-replay")

    def test_replay_is_always_research_only(self) -> None:
        """No combination of shadow inputs may flip the research-only flags."""
        items = [shadow_item(f"T{i}", pnl=10.0) for i in range(50)]
        shadow = {"updatedAt": "2026-05-10T08:00:00-06:00", "items": items}
        replay = build_replay(shadow)
        self.assertTrue(replay["researchOnly"])
        self.assertFalse(replay["promotable"])
        self.assertEqual(replay["stage"], REPLAY_STAGE)
        self.assertIn("shadow-replay only; cannot promote broker authority",
                      replay["researchNotes"])

    def test_replay_counts_closed_shadow_items(self) -> None:
        items = [
            shadow_item("WIN1", 10.0),
            shadow_item("WIN2", 12.0),
            shadow_item("OPEN", None),
        ]
        replay = build_replay({"updatedAt": None, "items": items})
        self.assertEqual(replay["shadowItemCount"], 3)
        self.assertEqual(replay["closedShadowCount"], 2)

    def test_replay_text_mentions_research_only(self) -> None:
        items = [shadow_item("WIN", 10.0)]
        replay = build_replay({"updatedAt": None, "items": items})
        text = replay_text(replay)
        self.assertIn("research-only", text.lower())
        self.assertIn("cannot promote", text.lower())

    def test_replay_handles_empty_shadow_evidence(self) -> None:
        replay = build_replay({"items": []})
        self.assertEqual(replay["shadowItemCount"], 0)
        self.assertEqual(replay["closedShadowCount"], 0)
        self.assertTrue(replay["researchOnly"])


if __name__ == "__main__":
    unittest.main()
