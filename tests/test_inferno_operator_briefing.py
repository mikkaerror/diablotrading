from __future__ import annotations

"""Regression tests for operator briefing readiness math.

These keep the daily operator memo aligned to the same 0-100 readiness
axis used by the dashboard and paper bootstrapper. The raw sheet
``readyScore`` can be tiny, so live gates must never compare it directly
against the 72% threshold when computed ``readiness`` is present.
"""

import unittest

import inferno_operator_briefing as ob


def make_row(**overrides) -> dict:
    row = {
        "ticker": "TEST",
        "readiness": 90,
        "readyScore": 2,
        "confidence": 3,
        "daysUntilEarnings": 10,
        "setupRec": "Vertical Call",
        "signalTrigger": "lit",
    }
    row.update(overrides)
    return row


class GateTests(unittest.TestCase):
    def test_computed_readiness_drives_gate(self) -> None:
        passes, failures = ob.evaluate_gates(make_row(readiness=88, readyScore=1))
        self.assertTrue(passes)
        self.assertEqual(failures, [])

    def test_low_computed_readiness_blocks_high_raw_score(self) -> None:
        passes, failures = ob.evaluate_gates(make_row(readiness=60, readyScore=99))
        self.assertFalse(passes)
        self.assertIn("readiness=60 < 72", failures)

    def test_legacy_raw_ready_score_still_supported(self) -> None:
        row = make_row(readyScore=80)
        row.pop("readiness")
        passes, failures = ob.evaluate_gates(row)
        self.assertTrue(passes)
        self.assertEqual(failures, [])


class RankingAndSizingTests(unittest.TestCase):
    def test_filter_sorts_by_computed_readiness(self) -> None:
        rows = [
            make_row(ticker="RAW_HIGH", readiness=75, readyScore=99),
            make_row(ticker="READY_HIGH", readiness=95, readyScore=1),
        ]
        qualified = ob.filter_qualified(rows)
        self.assertEqual([row["ticker"] for row in qualified], ["READY_HIGH", "RAW_HIGH"])

    def test_size_tickets_carries_readiness_and_raw_score(self) -> None:
        sizing = ob.size_tickets([make_row(ticker="ONE", readiness=93, readyScore=2)], cash=100, max_tickets=1)
        ticket = sizing["tickets"][0]
        self.assertEqual(ticket["readiness"], 93)
        self.assertEqual(ticket["readyScore"], 2)

    def test_size_tickets_caps_total_to_options_risk_budget(self) -> None:
        rows = [make_row(ticker=f"T{i}", readiness=95 - i) for i in range(5)]
        sizing = ob.size_tickets(rows, cash=1000, max_tickets=5)

        self.assertEqual(sizing["maxOptionsRiskBudget"], 250.0)
        self.assertEqual(sizing["totalDeployed"], 250.0)
        self.assertEqual(sizing["perTicket"], 50.0)
        self.assertEqual(sizing["binding"], "options-risk-budget")


class RenderTests(unittest.TestCase):
    def test_render_text_labels_readiness_percent(self) -> None:
        payload = {
            "generatedAt": "2026-05-17T06:00:00-06:00",
            "verdict": "ready-to-execute",
            "narrative": "test",
            "sizing": ob.size_tickets([make_row(ticker="ONE", readiness=93, readyScore=2)], cash=100, max_tickets=1),
            "gates": {"minReadyScore": 72, "minConfidence": 2, "maxDaysUntilEarnings": 21, "bannedSetups": ["Avoid"]},
            "rankedSlate": {},
            "paperBootstrap": {},
        }
        text = ob.render_text(payload)
        self.assertIn("Ready%", text)
        self.assertIn("Readiness% >= 72", text)
        self.assertIn("ONE", text)
        self.assertIn("    93", text)
        self.assertNotIn("Ready Score >= 72", text)


if __name__ == "__main__":
    unittest.main()
