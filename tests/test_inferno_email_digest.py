from __future__ import annotations

import unittest
from datetime import date

from inferno_email_digest import (
    block_reason_counts,
    build_strike_digest,
    normalize_block_reason,
    verbose_requested,
)


def _plan_item(ticker, blocks=None, approval="pending", max_loss=400.0):
    return {
        "ticker": ticker,
        "ok": True,
        "approvalStatus": approval,
        "intentBlocks": ["human approval still required"],
        "daysUntilEarnings": 5,
        "strikePlan": {"strategy": "LONG_STRADDLE", "expiration": "2026-10-02"},
        "riskVerdict": {"blocks": blocks or [], "metrics": {"maxLossDollars": max_loss}},
    }


def _ledger_item(day, reasons, status="paper-blocked"):
    return {"tradeDate": day, "ticker": "X", "status": status, "blockReasons": reasons}


class NormalizeTests(unittest.TestCase):
    def test_universal_blocks_dropped(self):
        self.assertIsNone(normalize_block_reason("human approval missing"))
        self.assertIsNone(normalize_block_reason("execution intent is not approval-ready"))

    def test_caps_collapse(self):
        self.assertEqual(
            normalize_block_reason("max loss $1510.00 exceeds single-ticket cap $500.00"),
            "over single-ticket cap",
        )
        self.assertEqual(
            normalize_block_reason("projected daily max loss $1510.00 exceeds cap $1500.00"),
            "over daily loss cap",
        )
        self.assertEqual(
            normalize_block_reason("ACN261002P00182500 spread is wide at 44%"),
            "wide bid/ask spread",
        )
        self.assertEqual(
            normalize_block_reason("no supported strike plan for Vertical Call"),
            "no strike plan for Vertical Call",
        )


class DigestTests(unittest.TestCase):
    def test_old_blocked_history_not_listed(self):
        ledger = {
            "items": [
                _ledger_item("2026-08-01", ["max loss $9000.00 exceeds single-ticket cap $500.00"]),
                _ledger_item("2026-09-26", ["max loss $900.00 exceeds single-ticket cap $500.00"]),
                _ledger_item("2026-09-27", ["human approval missing"]),
                _ledger_item("2026-09-27", [], status="paper-staged"),
            ]
        }
        total, counts = block_reason_counts(ledger["items"], date(2026, 9, 27))
        self.assertEqual(total, 2)
        self.assertEqual(counts["over single-ticket cap"], 1)

        plan = {"generatedAt": "2026-09-27T07:52:00-06:00", "items": [_plan_item("ACN")]}
        text = build_strike_digest(plan, ledger=ledger)
        self.assertIn("Blocked last 7d: 2 ticket(s)", text)
        self.assertNotIn("$9000", text)
        self.assertNotIn("2026-08-01", text)

    def test_today_split_between_waiting_and_passed(self):
        plan = {
            "generatedAt": "2026-09-27T07:52:00-06:00",
            "items": [
                _plan_item("ACN"),
                _plan_item("ASML", blocks=["max loss $16850.00 exceeds single-ticket cap $500.00"], max_loss=16850),
                {"ticker": "BAD", "ok": False, "reason": "no chain"},
            ],
        }
        text = build_strike_digest(plan)
        self.assertIn("Waiting on your approval", text)
        self.assertIn("ACN long straddle", text)
        self.assertIn("Passed on 1:", text)
        self.assertIn("ASML long straddle", text)
        self.assertIn("over single-ticket cap", text)
        self.assertIn("could not be priced", text)

    def test_nothing_to_act_on(self):
        text = build_strike_digest({"generatedAt": "2026-09-27", "items": []})
        self.assertIn("Nothing to act on today.", text)
        self.assertIn("Nothing here places an order", text)

    def test_scoreboard_and_authority(self):
        shadow = {
            "strategies": [
                {"strategy": "LONG_STRADDLE", "closedCount": 10, "winRate": 0.3, "avgReturnOnRisk": -0.15},
                {"strategy": "Straddle", "closedCount": 0},
            ]
        }
        analytics = {"closedMetrics": {"scoredCount": 3}, "promotionTruth": {"qualified": 1, "target": 30, "estimatesNoCredit": 2}}
        authority = {"decision": {"authorityLevel": "paper-evidence-only", "liveTradingAllowed": False}}
        text = build_strike_digest(
            {"generatedAt": "2026-09-27", "items": []},
            shadow=shadow,
            analytics=analytics,
            authority=authority,
            sandbox={"stageableCount": 0},
        )
        self.assertIn("Paper outcomes qualified: 1/30", text)
        self.assertIn("long straddle: 10 closed | win 30% | avg -0.15R", text)
        self.assertNotIn("straddle: 0 closed", text)
        self.assertIn("live submit False", text)

    def test_digest_is_short(self):
        ledger = {"items": [_ledger_item("2026-09-2%d" % (i % 7 + 1), ["x spread is wide at 50%"]) for i in range(300)]}
        text = build_strike_digest({"generatedAt": "2026-09-27", "items": []}, ledger=ledger)
        self.assertLess(len(text.splitlines()), 20)

    def test_verbose_env(self):
        self.assertTrue(verbose_requested({"INFERNO_STRIKE_EMAIL_VERBOSE": "1"}))
        self.assertFalse(verbose_requested({}))


if __name__ == "__main__":
    unittest.main()
