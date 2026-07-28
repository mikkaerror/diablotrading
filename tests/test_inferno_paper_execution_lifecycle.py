from __future__ import annotations

import unittest
from unittest.mock import patch

import inferno_paper_execution as paper_execution


class InfernoPaperExecutionLifecycleTests(unittest.TestCase):
    """Ensure a paper-ledger refresh describes its evidence lifecycle."""

    def test_recording_empty_plan_writes_lifecycle_without_ticket_mutation(self) -> None:
        strike_plan = {"generatedAt": "2026-07-26T09:00:00-06:00", "items": []}
        with (
            patch.object(paper_execution, "load_ledger", return_value={"items": []}),
            patch.object(paper_execution, "save_ledger") as save_mock,
        ):
            result = paper_execution.record_from_strike_plan(strike_plan)

        ledger = result["ledger"]
        self.assertEqual(result["inserted"], 0)
        self.assertEqual(ledger["sourceDataAsOf"], "2026-07-26T09:00:00-06:00")
        self.assertEqual(ledger["lifecycleStatus"], "success")
        self.assertEqual(ledger["producer"], "inferno-paper-execution")
        self.assertEqual(ledger["freshnessPolicy"]["ttlHours"], 36)
        save_mock.assert_called_once_with(ledger)


if __name__ == "__main__":
    unittest.main()
