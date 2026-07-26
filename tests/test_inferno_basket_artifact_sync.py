"""The live tracker artifact must agree with the universe contract.

Why this test exists: the tracker artifact (ai_basket_tracker.html) is
standalone HTML and cannot import the Python config, so it carries its own copy
of the ticker list. For weeks that copy held 30 names while
research/ai_basket_universe.json held 27 — the bearings sleeve (RBC, RRX, TKR)
was visible in the tracker but invisible to every engine, so the weekly email
silently covered a smaller universe than the operator believed.

Nobody noticed because nothing compared them. This does.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = ROOT / "ai_basket_tracker.html"
UNIVERSE = ROOT / "research" / "ai_basket_universe.json"


def artifact_basket() -> list[tuple[str, str]]:
    """Extract [ticker, category] pairs from the artifact's BASKET array."""
    html = ARTIFACT.read_text(encoding="utf-8")
    block = re.search(r"const BASKET\s*=\s*\[(.*?)\];", html, re.S)
    if not block:
        raise AssertionError("could not find the BASKET array in the artifact")
    return re.findall(r'\["([A-Z.]+)"\s*,\s*"([^"]*)"\]', block.group(1))


def universe() -> tuple[list[str], dict[str, str]]:
    payload = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    cats = {r["symbol"]: r.get("cat", "") for r in payload["records"]}
    return payload["expectedUniverse"], cats


@unittest.skipUnless(ARTIFACT.exists(), "tracker artifact not present")
class ArtifactSyncTests(unittest.TestCase):
    def test_artifact_covers_every_universe_symbol(self):
        expected, _ = universe()
        art = [s for s, _ in artifact_basket()]
        missing = [s for s in expected if s not in art]
        self.assertEqual(missing, [],
                         f"universe symbols missing from the tracker: {missing}")

    def test_artifact_has_no_symbols_outside_the_universe(self):
        expected, _ = universe()
        art = [s for s, _ in artifact_basket()]
        extra = [s for s in art if s not in expected]
        self.assertEqual(extra, [],
                         f"tracker shows symbols the engines do not track: {extra}")

    def test_categories_match_the_contract(self):
        _, cats = universe()
        mismatched = [(s, c, cats[s]) for s, c in artifact_basket()
                      if s in cats and c != cats[s]]
        self.assertEqual(mismatched, [],
                         f"category drift (symbol, artifact, contract): {mismatched}")

    def test_no_duplicate_symbols_in_artifact(self):
        art = [s for s, _ in artifact_basket()]
        dupes = sorted({s for s in art if art.count(s) > 1})
        self.assertEqual(dupes, [], f"duplicate tickers in the tracker: {dupes}")


if __name__ == "__main__":
    unittest.main()
