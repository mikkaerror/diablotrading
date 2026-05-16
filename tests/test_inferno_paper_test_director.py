from __future__ import annotations

"""Regression tests for the paper-test director memo."""

import unittest
from unittest.mock import patch

from inferno_paper_test_director import build_director, load_strike_plan


class InfernoPaperTestDirectorTests(unittest.TestCase):
    """Verify the director classifies paper candidates honestly."""

    @patch("inferno_paper_test_director.load_strike_plan")
    @patch("inferno_paper_test_director.load_json_file")
    def test_build_director_surfaces_approval_bottleneck(self, mock_load_json_file, mock_load_strike_plan) -> None:
        strike_plan = {
            "items": [
                {
                    "ticker": "WSC",
                    "ok": True,
                    "approvalStatus": "pending",
                    "intentStatus": "blocked",
                    "setupRec": "Straddle",
                    "daysUntilEarnings": 2,
                    "marketContextSummary": {"trend": "Bullish"},
                    "strikePlan": {
                        "strategy": "LONG_STRADDLE",
                        "estimatedMaxLoss": 295.0,
                        "estimatedDebit": 2.95,
                        "liquidityNotes": [],
                    },
                    "riskVerdict": {"passed": True, "blocks": [], "warnings": ["thin confirmation"]},
                },
                {
                    "ticker": "PRIM",
                    "ok": True,
                    "approvalStatus": "pending",
                    "intentStatus": "blocked",
                    "setupRec": "Straddle",
                    "daysUntilEarnings": 0,
                    "marketContextSummary": {"trend": "Bullish"},
                    "strikePlan": {
                        "strategy": "LONG_STRADDLE",
                        "estimatedMaxLoss": 2800.0,
                        "estimatedDebit": 28.0,
                        "liquidityNotes": [],
                    },
                    "riskVerdict": {
                        "passed": False,
                        "blocks": ["max loss $2800.00 exceeds single-ticket cap $500.00"],
                        "warnings": [],
                    },
                },
            ]
        }
        mock_load_strike_plan.return_value = (strike_plan, False)
        execution_queue = {
            "items": [
                {"ticker": "WSC", "readiness": 88, "nextStep": "Approve for paper review."},
                {"ticker": "PRIM", "readiness": 92, "nextStep": "Too large for current risk caps."},
            ],
            "updatedAt": "2026-05-12T10:00:00-06:00",
        }
        snapshot = {"eligibleTickers": ["WSC", "PRIM"], "reviewQueueTickers": ["WSC", "PRIM"]}
        approval_queue = {"items": []}
        sandbox = {
            "stageableTickets": [],
            "watchlistTickets": [
                {
                    "ticker": "WSC",
                    "status": "blocked",
                    "reasons": ["human approval is missing", "human approval still required"],
                    "nextStep": "Human review still needs to approve or reject the ticket.",
                },
                {
                    "ticker": "PRIM",
                    "status": "blocked",
                    "reasons": [
                        "human approval is missing",
                        "max loss $2800.00 exceeds single-ticket cap $500.00",
                    ],
                    "nextStep": "Too large for current risk caps.",
                },
            ],
            "blockedTickets": [],
        }
        authority = {"decision": {"authorityLevel": "paper-evidence-only", "warnings": [], "nextMilestones": []}}
        performance = {"closedMetrics": {"scoredCount": 1}, "deskVerdict": {"level": "evidence-building"}}
        mock_load_json_file.side_effect = [snapshot, approval_queue, execution_queue, sandbox, authority, performance]

        payload = build_director()
        self.assertEqual(payload["verdict"], "approval-bottleneck")
        self.assertTrue(payload["paperCycleHealthy"])
        self.assertEqual(payload["counts"]["approvalOnly"], 1)
        self.assertEqual(payload["counts"]["hardBlocked"], 1)
        self.assertEqual(payload["approvalSlate"][0]["ticker"], "WSC")
        self.assertEqual(payload["hardBlockedSlate"][0]["ticker"], "PRIM")

    @patch("inferno_paper_test_director.load_strike_plan")
    @patch("inferno_paper_test_director.load_json_file")
    def test_build_director_marks_stageable_names_ready(self, mock_load_json_file, mock_load_strike_plan) -> None:
        strike_plan = {
            "items": [
                {
                    "ticker": "OTEX",
                    "ok": True,
                    "approvalStatus": "approved",
                    "intentStatus": "approval-ready",
                    "setupRec": "Vertical Call",
                    "daysUntilEarnings": 9,
                    "marketContextSummary": {"trend": "Bullish"},
                    "strikePlan": {
                        "strategy": "CALL_DEBIT_SPREAD",
                        "estimatedMaxLoss": 120.0,
                        "estimatedDebit": 1.2,
                        "liquidityNotes": [],
                    },
                    "riskVerdict": {"passed": True, "blocks": [], "warnings": []},
                }
            ]
        }
        mock_load_strike_plan.return_value = (strike_plan, False)
        snapshot = {"eligibleTickers": ["OTEX"], "reviewQueueTickers": ["OTEX"]}
        approval_queue = {"items": [{"ticker": "OTEX", "approvalStatus": "approved"}]}
        execution_queue = {"items": [{"ticker": "OTEX", "readiness": 90, "nextStep": "Ready."}], "updatedAt": "2026-05-12T10:00:00-06:00"}
        sandbox = {
            "stageableTickets": [{"ticker": "OTEX", "status": "stage-in-papermoney", "reasons": [], "nextStep": "Stage now."}],
            "watchlistTickets": [],
            "blockedTickets": [],
        }
        authority = {"decision": {"authorityLevel": "paper-evidence-only", "warnings": [], "nextMilestones": []}}
        performance = {"closedMetrics": {"scoredCount": 5}, "deskVerdict": {"level": "evidence-building"}}
        mock_load_json_file.side_effect = [snapshot, approval_queue, execution_queue, sandbox, authority, performance]

        payload = build_director()
        self.assertEqual(payload["verdict"], "ready-to-paper-stage")
        self.assertEqual(payload["counts"]["stageableNow"], 1)
        self.assertEqual(payload["stageableSlate"][0]["ticker"], "OTEX")

    @patch("inferno_paper_test_director.save_strike_plan")
    @patch("inferno_paper_test_director.build_strike_plan")
    @patch("inferno_paper_test_director.load_json_file")
    def test_load_strike_plan_refreshes_when_queue_tickers_drift(
        self,
        mock_load_json_file,
        mock_build_strike_plan,
        mock_save_strike_plan,
    ) -> None:
        stale_plan = {
            "generatedAt": "2026-05-12T09:00:00-06:00",
            "sourceExecutionQueueUpdatedAt": "2026-05-12T09:00:00-06:00",
            "items": [{"ticker": "OLD"}],
        }
        refreshed_plan = {
            "generatedAt": "2026-05-12T10:05:00-06:00",
            "sourceExecutionQueueUpdatedAt": "2026-05-12T10:00:00-06:00",
            "items": [{"ticker": "NEW"}],
        }
        mock_load_json_file.return_value = stale_plan
        mock_build_strike_plan.return_value = refreshed_plan
        execution_queue = {
            "updatedAt": "2026-05-12T10:00:00-06:00",
            "items": [{"ticker": "NEW"}],
        }

        plan, refreshed = load_strike_plan(execution_queue, refresh_if_stale=True)

        self.assertTrue(refreshed)
        self.assertEqual(plan, refreshed_plan)
        mock_build_strike_plan.assert_called_once()
        mock_save_strike_plan.assert_called_once_with(refreshed_plan)

    @patch("inferno_paper_test_director.build_strike_plan_from_queue")
    @patch("inferno_paper_test_director.build_execution_queue")
    @patch("inferno_paper_test_director.load_strike_plan")
    @patch("inferno_paper_test_director.load_json_file")
    def test_build_director_expands_rehearsal_universe_when_primary_queue_is_dead(
        self,
        mock_load_json_file,
        mock_load_strike_plan,
        mock_build_execution_queue,
        mock_build_strike_plan_from_queue,
    ) -> None:
        snapshot = {
            "eligibleTickers": ["THR", "DELL", "GDS", "DY", "NVDA", "HPE", "ENS"],
            "reviewQueueTickers": ["THR", "DELL", "GDS", "DY", "NVDA"],
        }
        execution_queue = {
            "items": [{"ticker": ticker} for ticker in snapshot["reviewQueueTickers"]],
            "updatedAt": "2026-05-13T00:00:00-06:00",
        }
        sandbox = {"stageableTickets": [], "watchlistTickets": [], "blockedTickets": []}
        authority = {"decision": {"authorityLevel": "paper-evidence-only", "warnings": [], "nextMilestones": []}}
        performance = {"closedMetrics": {"scoredCount": 0}, "deskVerdict": {"level": "insufficient-data"}}
        approval_queue = {"items": []}
        dead_primary_plan = {"items": []}
        expanded_queue = {
            "items": [{"ticker": "THR"}, {"ticker": "DELL"}, {"ticker": "GDS"}, {"ticker": "DY"}, {"ticker": "NVDA"}, {"ticker": "HPE"}, {"ticker": "ENS"}],
            "updatedAt": "2026-05-13T00:05:00-06:00",
        }
        expanded_plan = {
            "generatedAt": "2026-05-13T00:05:30-06:00",
            "items": [
                {
                    "ticker": "ENS",
                    "ok": True,
                    "approvalStatus": "pending",
                    "intentStatus": "blocked",
                    "setupRec": "Vertical Call",
                    "daysUntilEarnings": 7,
                    "marketContextSummary": {"trend": "Bullish"},
                    "strikePlan": {
                        "strategy": "CALL_DEBIT_SPREAD",
                        "estimatedMaxLoss": 185.0,
                        "estimatedDebit": 1.85,
                        "liquidityNotes": [],
                    },
                    "riskVerdict": {"passed": True, "blocks": [], "warnings": []},
                }
            ],
        }

        mock_load_json_file.side_effect = [snapshot, approval_queue, execution_queue, sandbox, authority, performance]
        mock_load_strike_plan.return_value = (dead_primary_plan, False)
        mock_build_execution_queue.return_value = expanded_queue
        mock_build_strike_plan_from_queue.return_value = expanded_plan

        payload = build_director()

        self.assertEqual(payload["verdict"], "approval-bottleneck")
        self.assertTrue(payload["expandedUniverseUsed"])
        self.assertEqual(payload["sourceUniverse"], "expanded-eligible-universe")
        self.assertIn("ENS", payload["expandedUniverseTickers"])
        self.assertEqual(payload["approvalSlate"][0]["ticker"], "ENS")


if __name__ == "__main__":
    unittest.main()
