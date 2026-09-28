from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from inferno_paper_delegate import (
    MAX_APPROVALS_PER_RUN,
    ack_status,
    apply_decisions,
    build_paper_delegate,
    decide,
)

NOW = datetime(2026, 9, 28, 13, 0, tzinfo=timezone.utc)


def plan_item(ticker="ACN", max_loss=1510.0, cap=2000.0, blocks=None, ok=True):
    return {
        "ticker": ticker,
        "ok": ok,
        "strikePlan": {"strategy": "LONG_STRADDLE"},
        "riskVerdict": {
            "passed": not blocks,
            "blocks": blocks or [],
            "metrics": {"maxLossDollars": max_loss, "effectiveSingleTicketCap": cap},
        },
    }


def queue_item(ticker="ACN", days=4):
    return {"ticker": ticker, "approvalStatus": "pending", "approvalToken": f"T{ticker}", "daysUntilEarnings": days}


def shadow(ticker="ACN", values=()):
    return {"items": [
        {"ticker": ticker, "strategy": "LONG_STRADDLE", "outcome": {"status": "closed", "estimatedReturnOnRisk": v}}
        for v in values
    ]}


class PolicyTests(unittest.TestCase):
    def test_clean_candidate_is_approved(self):
        d = decide(queue_item(), plan_item(), 10.0, shadow(values=[0.2, -0.1]))
        self.assertEqual((d["action"], d["rule"]), ("approve", "clean-paper"))

    def test_approval_only_blocks_do_not_hold(self):
        d = decide(queue_item(), plan_item(blocks=["human approval missing"]), 10.0, {})
        self.assertEqual(d["action"], "approve")

    def test_far_over_cap_rejected(self):
        d = decide(queue_item("ASML"), plan_item("ASML", max_loss=16380, blocks=[
            "max loss $16380.00 exceeds single-ticket cap $2000.00"]), 10.0, {})
        self.assertEqual((d["action"], d["rule"]), ("reject", "far-over-cap"))

    def test_near_cap_miss_held_for_cap_fit_variant(self):
        d = decide(queue_item(), plan_item(max_loss=2500, blocks=[
            "max loss $2500.00 exceeds single-ticket cap $2000.00"]), 10.0, {})
        self.assertEqual((d["action"], d["rule"]), ("hold", "soft-blocks"))

    def test_shadow_answered_rejected(self):
        d = decide(queue_item(), plan_item(), 10.0, shadow(values=[-0.6] * 15))
        self.assertEqual((d["action"], d["rule"]), ("reject", "shadow-answered"))

    def test_small_negative_shadow_still_approved(self):
        d = decide(queue_item(), plan_item(), 10.0, shadow(values=[-0.6] * 14))
        self.assertEqual(d["action"], "approve")

    def test_holds(self):
        self.assertEqual(decide(queue_item(), None, 10.0, {})["rule"], "no-priced-plan")
        self.assertEqual(decide(queue_item(), plan_item(ok=False), 10.0, {})["rule"], "no-priced-plan")
        self.assertEqual(decide(queue_item(), plan_item(), 200.0, {})["rule"], "stale-plan")
        self.assertEqual(decide(queue_item(days=0), plan_item(), 10.0, {})["rule"], "event-passed")
        wide = plan_item(blocks=["ACN261002P00182500 spread is wide at 44%"])
        self.assertEqual(decide(queue_item(), wide, 10.0, {})["rule"], "soft-blocks")

    def test_ack_status(self):
        self.assertFalse(ack_status({})[0])
        self.assertFalse(ack_status({"active": False, "scope": "paper-only"})[0])
        self.assertFalse(ack_status({"active": True, "scope": "live"})[0])
        self.assertTrue(ack_status({"active": True, "scope": "paper-only", "grantedAt": "x"})[0])


class BuildApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        items = [queue_item(f"T{i}") for i in range(MAX_APPROVALS_PER_RUN + 2)]
        items.append({"ticker": "DONE", "approvalStatus": "approved"})
        (self.data / "inferno_approval_queue.json").write_text(json.dumps({"items": items}))
        (self.data / "inferno_strike_plan.json").write_text(json.dumps({
            "generatedAt": "2026-09-28T12:00:00+00:00",
            "items": [plan_item(f"T{i}") for i in range(MAX_APPROVALS_PER_RUN + 2)],
        }))

    def tearDown(self):
        self.tmp.cleanup()

    def test_without_ack_nothing_applied(self):
        payload = build_paper_delegate(self.data, now=NOW)
        self.assertFalse(payload["ackActive"])
        calls = []
        apply_decisions(payload, updater=lambda i, s: calls.append((i, s)) or 0, log_path=self.data / "log.csv")
        self.assertEqual(calls, [])
        self.assertFalse((self.data / "log.csv").exists())

    def test_with_ack_applies_capped_and_logs(self):
        (self.data / "inferno_paper_delegation_ack.json").write_text(
            json.dumps({"active": True, "scope": "paper-only", "grantedAt": "2026-09-27"}))
        payload = build_paper_delegate(self.data, now=NOW)
        self.assertFalse(payload["liveTradingAllowed"])
        self.assertFalse(payload["brokerSubmitAllowed"])
        self.assertFalse(payload["authorityChanged"])
        calls = []
        apply_decisions(payload, updater=lambda i, s: calls.append((i, s)) or 0, log_path=self.data / "log.csv")
        self.assertEqual(len(calls), MAX_APPROVALS_PER_RUN)
        self.assertTrue(all(status == "approved" for _, status in calls))
        self.assertEqual(sum(1 for d in payload["decisions"] if d["rule"] == "per-run-limit"), 2)
        rows = list(csv.reader((self.data / "log.csv").open()))
        self.assertEqual(len(rows), MAX_APPROVALS_PER_RUN + 1)
        self.assertIn("claude-delegated", rows[1][3])


if __name__ == "__main__":
    unittest.main()
