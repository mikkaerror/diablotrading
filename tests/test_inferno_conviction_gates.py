from __future__ import annotations

"""The candidate conviction gates must be single-sourced in inferno_config.

These thresholds used to be redefined byte-for-byte in two modules and kept in
sync by hand. This test fails the moment they drift, so the single-source
refactor cannot silently regress.
"""

import unittest

import inferno_config as cfg
import inferno_operator_briefing as ob
import inferno_paper_bootstrap as pb


class ConvictionGateSingleSourceTests(unittest.TestCase):
    def test_paper_bootstrap_traces_to_config(self) -> None:
        self.assertEqual(pb.MIN_READY_SCORE, cfg.CANDIDATE_MIN_READINESS)
        self.assertEqual(pb.MIN_CONFIDENCE, cfg.CANDIDATE_MIN_CONFIDENCE)
        self.assertEqual(pb.MAX_DAYS_UNTIL_EARNINGS, cfg.CANDIDATE_MAX_DAYS_UNTIL_EARNINGS)
        self.assertEqual(pb.BANNED_SETUPS, cfg.CANDIDATE_BANNED_SETUPS)

    def test_operator_briefing_traces_to_config(self) -> None:
        self.assertEqual(ob.MIN_READY_SCORE, cfg.CANDIDATE_MIN_READINESS)
        self.assertEqual(ob.MIN_CONFIDENCE, cfg.CANDIDATE_MIN_CONFIDENCE)
        self.assertEqual(ob.MAX_DAYS_UNTIL_EARNINGS, cfg.CANDIDATE_MAX_DAYS_UNTIL_EARNINGS)
        self.assertEqual(ob.BANNED_SETUPS, cfg.CANDIDATE_BANNED_SETUPS)

    def test_two_modules_agree(self) -> None:
        self.assertEqual(pb.MIN_READY_SCORE, ob.MIN_READY_SCORE)
        self.assertEqual(pb.MIN_CONFIDENCE, ob.MIN_CONFIDENCE)
        self.assertEqual(pb.MAX_DAYS_UNTIL_EARNINGS, ob.MAX_DAYS_UNTIL_EARNINGS)
        self.assertEqual(pb.BANNED_SETUPS, ob.BANNED_SETUPS)

    def test_defaults_unchanged(self) -> None:
        # Refactor must preserve the historical values exactly.
        self.assertEqual(cfg.CANDIDATE_MIN_READINESS, 72)
        self.assertEqual(cfg.CANDIDATE_MIN_CONFIDENCE, 2)
        self.assertEqual(cfg.CANDIDATE_MAX_DAYS_UNTIL_EARNINGS, 21)
        self.assertEqual(cfg.CANDIDATE_BANNED_SETUPS, frozenset({"Avoid"}))


if __name__ == "__main__":
    unittest.main()
