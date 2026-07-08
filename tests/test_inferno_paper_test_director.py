from __future__ import annotations

"""Regression tests for the paper-test director memo."""

import unittest
from unittest.mock import patch

from inferno_paper_test_director import build_director, blocker_table, load_strike_plan, split_candidates


class InfernoPaperTestDirectorTests(unittest.TestCase):
    """Verify the director classifies paper candidates honestly."""

    def setUp(self) -> None:
        self.cap_patch = patch(
            "inferno_paper_test_director.current_ticket_cap_policy",
            return_value={
                "effectiveBand": {
                    "hardCapDollars": 500.0,
                    "minTargetDollars": 250.0,
                    "targetTicketDollars": 250.0,
                }
            },
        )
        self.cap_patch.start()

    def tearDown(self) -> None:
        self.cap_patch.stop()

    def test_blocker_table_suppresses_approval_noise_for_hard_blocks(self) -> None:
        counts = blocker_table(
            [
                {
                    "ticker": "PRIM",
                    "category": "hard-blocked",
                    "reasons": [
                        "human approval is missing",
                        "human approval still required",
                        "max loss $2800.00 exceeds single-ticket cap $500.00",
                    ],
                },
                {
                    "ticker": "CLEAN",
                    "category": "approval-only",
                    "reasons": ["human approval still required"],
                },
            ]
        )
        rendered = {item["reason"]: item["count"] for item in counts}
        self.assertEqual(rendered["max loss $2800.00 exceeds single-ticket cap $500.00"], 1)
        self.assertEqual(rendered["human approval still required"], 1)
        self.assertNotIn("human approval is missing", rendered)

    @patch("inferno_paper_test_director.load_strike_plan")
    @patch("inferno_paper_test_director.load_json_file")
    def test_build_director_auto_selects_approval_only_paper_candidates(self, mock_load_json_file, mock_load_strike_plan) -> None:
        strike_plan = {
            "items": [
                {
                    "ticker": "WSC",
                    "ok": True,
                    "approvalStatus": "pending",
                    "intentStatus": "blocked",
                    "setupRec": "Straddle",
                    "daysUntilEarnings": 2,
                    "trackerContext": {"nextEarnings": "2026-07-08"},
                    "price": 50.0,
                    "ivRank": 25.0,
                    "atrPercent": 3.0,
                    "forecastRealizedMovePct": 12.0,
                    "marketContextSummary": {"trend": "Bullish", "ivRank": 25.0, "atrPercent": 3.0},
                    "strikePlan": {
                        "strategy": "LONG_STRADDLE",
                        "estimatedMaxLoss": 295.0,
                        "estimatedDebit": 2.95,
                        "lowerBreakEven": 45.0,
                        "upperBreakEven": 55.0,
                        "greekSummary": {
                            "netDelta": 0.0,
                            "netGamma": 0.1,
                            "netTheta": -0.2,
                            "netVega": 0.3,
                            "greeksComplete": True,
                        },
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
        mock_load_json_file.side_effect = [snapshot, approval_queue, execution_queue, sandbox, authority, performance, {}, {"items": []}]

        payload = build_director()
        self.assertEqual(payload["verdict"], "auto-paper-selected")
        self.assertTrue(payload["paperCycleHealthy"])
        self.assertEqual(payload["counts"]["autoPaperSelected"], 1)
        self.assertEqual(payload["counts"]["distinctAutoPaperEvents"], 1)
        self.assertEqual(payload["counts"]["approvalOnly"], 0)
        self.assertEqual(payload["counts"]["hardBlocked"], 1)
        self.assertEqual(payload["autoPaperSlate"][0]["ticker"], "WSC")
        self.assertEqual(payload["autoPaperSlate"][0]["eventTicketCount"], 0)
        self.assertEqual(payload["autoPaperSlate"][0]["eventId"], "WSC|2026-07-08")
        self.assertEqual(payload["hardBlockedSlate"][0]["ticker"], "PRIM")
        self.assertIn("operator-owned paper workflow", payload["nextActions"][0])
        self.assertIn("do not stage, approve, reject, or close", payload["nextActions"][0])
        self.assertNotIn("Rehearse the auto paper slate", payload["nextActions"][0])

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
                    "ivRank": 40.0,
                    "marketContextSummary": {"trend": "Bullish", "ivRank": 40.0},
                    "strikePlan": {
                        "strategy": "CALL_DEBIT_SPREAD",
                        "estimatedMaxLoss": 120.0,
                        "estimatedDebit": 1.2,
                        "greekSummary": {
                            "netDelta": 0.2,
                            "netGamma": 0.01,
                            "netTheta": -0.02,
                            "netVega": 0.05,
                            "greeksComplete": True,
                        },
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
        mock_load_json_file.side_effect = [snapshot, approval_queue, execution_queue, sandbox, authority, performance, {}, {"items": []}]

        payload = build_director()
        self.assertEqual(payload["verdict"], "operator-paper-candidates")
        self.assertEqual(payload["counts"]["stageableNow"], 1)
        self.assertEqual(payload["stageableSlate"][0]["ticker"], "OTEX")
        self.assertIn("operator-owned paper workflow", payload["nextActions"][0])
        self.assertIn("do not stage autonomously", payload["nextActions"][0])
        self.assertNotIn("Rehearse", payload["nextActions"][0])

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
                    "ivRank": 35.0,
                    "marketContextSummary": {"trend": "Bullish", "ivRank": 35.0},
                    "strikePlan": {
                        "strategy": "CALL_DEBIT_SPREAD",
                        "estimatedMaxLoss": 185.0,
                        "estimatedDebit": 1.85,
                        "greekSummary": {
                            "netDelta": 0.2,
                            "netGamma": 0.01,
                            "netTheta": -0.02,
                            "netVega": 0.05,
                            "greeksComplete": True,
                        },
                        "liquidityNotes": [],
                    },
                    "riskVerdict": {"passed": True, "blocks": [], "warnings": []},
                }
            ],
        }

        mock_load_json_file.side_effect = [snapshot, approval_queue, execution_queue, sandbox, authority, performance, {}, {"items": []}]
        mock_load_strike_plan.return_value = (dead_primary_plan, False)
        mock_build_execution_queue.return_value = expanded_queue
        mock_build_strike_plan_from_queue.return_value = expanded_plan

        payload = build_director()

        self.assertEqual(payload["verdict"], "auto-paper-selected")
        self.assertTrue(payload["expandedUniverseUsed"])
        self.assertEqual(payload["sourceUniverse"], "expanded-eligible-universe")
        self.assertIn("ENS", payload["expandedUniverseTickers"])
        self.assertEqual(payload["autoPaperSlate"][0]["ticker"], "ENS")

    @patch("inferno_paper_test_director.load_strike_plan")
    @patch("inferno_paper_test_director.load_json_file")
    def test_build_director_surfaces_construction_watch_when_paper_risk_is_paused(
        self,
        mock_load_json_file,
        mock_load_strike_plan,
    ) -> None:
        snapshot = {"eligibleTickers": ["AEHR"], "reviewQueueTickers": ["AEHR"]}
        approval_queue = {"items": []}
        execution_queue = {"items": [{"ticker": "AEHR", "readiness": 60}], "updatedAt": "2026-05-13T00:00:00-06:00"}
        sandbox = {"stageableTickets": [], "watchlistTickets": [], "blockedTickets": []}
        authority = {"decision": {"authorityLevel": "paper-evidence-only", "warnings": [], "nextMilestones": []}}
        performance = {"closedMetrics": {"scoredCount": 1}, "deskVerdict": {"level": "evidence-building"}}
        strategy_pricing = {
            "ticketCapPolicy": {
                "constructionBand": {"hardCapDollars": 500.0, "minTargetDollars": 250.0},
                "effectiveBand": {"hardCapDollars": 0.0},
            },
            "items": [
                {
                    "ticker": "AEHR",
                    "status": "priced",
                    "optimizerPassed": True,
                    "paperRiskPassed": False,
                    "combinedPassed": False,
                    "expiration": "2026-07-17",
                    "sourceAlternativeScore": 55.0,
                    "recommendedStrategy": "CALL_DEBIT_SPREAD",
                    "strikePlan": {
                        "strategy": "CALL_DEBIT_SPREAD",
                        "estimatedMaxLoss": 370.0,
                        "estimatedDebit": 3.7,
                        "optimizerWarnings": [],
                    },
                    "riskVerdict": {
                        "passed": False,
                        "blocks": [
                            "max loss $370.00 exceeds single-ticket cap $0.00 (ack; drawdown pause; new entries allowed False)"
                        ],
                        "warnings": [],
                    },
                }
            ],
        }
        mock_load_strike_plan.return_value = ({"items": []}, False)
        mock_load_json_file.side_effect = [
            snapshot,
            approval_queue,
            execution_queue,
            sandbox,
            authority,
            performance,
            strategy_pricing,
            {"items": []},
        ]

        payload = build_director()

        self.assertEqual(payload["verdict"], "construction-watch")
        self.assertEqual(payload["counts"]["constructionWatch"], 1)
        self.assertEqual(payload["constructionWatchlist"][0]["ticker"], "AEHR")
        self.assertEqual(payload["constructionWatchlist"][0]["strategy"], "CALL_DEBIT_SPREAD")
        self.assertIn("paper-stage-paused", payload["constructionWatchlist"][0]["blockCategories"])

    @patch("inferno_paper_test_director.load_strike_plan")
    @patch("inferno_paper_test_director.load_json_file")
    def test_build_director_surfaces_priced_paper_variant_selection_without_staging(
        self,
        mock_load_json_file,
        mock_load_strike_plan,
    ) -> None:
        snapshot = {"eligibleTickers": ["USAR"], "reviewQueueTickers": ["USAR"]}
        approval_queue = {"items": []}
        execution_queue = {"items": [{"ticker": "USAR", "readiness": 99}], "updatedAt": "2026-07-06T10:00:00-06:00"}
        sandbox = {"stageableTickets": [], "watchlistTickets": [], "blockedTickets": []}
        authority = {"decision": {"authorityLevel": "paper-evidence-only", "warnings": [], "nextMilestones": []}}
        performance = {"closedMetrics": {"scoredCount": 1}, "deskVerdict": {"level": "evidence-building"}}
        strategy_pricing = {
            "items": [
                {
                    "ticker": "USAR",
                    "status": "priced",
                    "combinedPassed": True,
                    "paperVariantOnly": True,
                    "paperVariantFamily": "wheel-proxy",
                    "expiration": "2026-08-21",
                    "recommendedStrategy": "PUT_CREDIT_SPREAD",
                    "sourceAlternativeScore": 55.87,
                    "marketContextSummary": {"trend": "Bearish", "rvol": 0.21, "support": 18.54},
                    "strikePlan": {
                        "paperVariantOnly": True,
                        "sourcePaperVariant": True,
                        "variantForStrategy": "wheel-proxy",
                        "strategy": "PUT_CREDIT_SPREAD",
                        "expiration": "2026-08-21",
                        "estimatedMaxLoss": 198.0,
                        "estimatedCredit": 1.02,
                    },
                    "riskVerdict": {"passed": True, "blocks": [], "warnings": []},
                }
            ]
        }
        mock_load_strike_plan.return_value = ({"items": []}, False)
        mock_load_json_file.side_effect = [
            snapshot,
            approval_queue,
            execution_queue,
            sandbox,
            authority,
            performance,
            strategy_pricing,
            {"items": []},
        ]

        payload = build_director()

        self.assertEqual(payload["verdict"], "paper-research-selected")
        self.assertEqual(payload["counts"]["pricedPaperVariantWatch"], 1)
        self.assertEqual(payload["counts"]["paperResearchSelected"], 1)
        self.assertEqual(payload["counts"]["distinctPaperResearchEvents"], 1)
        self.assertEqual(payload["counts"]["stageableNow"], 0)
        self.assertEqual(payload["counts"]["autoPaperSelected"], 0)
        self.assertEqual(payload["pricedPaperVariantWatchlist"][0]["ticker"], "USAR")
        self.assertEqual(payload["pricedPaperVariantWatchlist"][0]["strategy"], "PUT_CREDIT_SPREAD")
        self.assertEqual(payload["pricedPaperVariantWatchlist"][0]["paperVariantFamily"], "wheel-proxy")
        self.assertEqual(payload["pricedPaperVariantWatchlist"][0]["eventId"], "USAR|2026-08-21")
        self.assertTrue(payload["pricedPaperVariantWatchlist"][0]["paperResearchSelected"])

    @patch("inferno_paper_test_director.load_strike_plan")
    @patch("inferno_paper_test_director.load_json_file")
    def test_build_director_event_caps_priced_paper_variant_selection(
        self,
        mock_load_json_file,
        mock_load_strike_plan,
    ) -> None:
        snapshot = {"eligibleTickers": ["USAR"], "reviewQueueTickers": ["USAR"]}
        approval_queue = {"items": []}
        execution_queue = {"items": [{"ticker": "USAR", "readiness": 99}], "updatedAt": "2026-07-06T10:00:00-06:00"}
        sandbox = {"stageableTickets": [], "watchlistTickets": [], "blockedTickets": []}
        authority = {"decision": {"authorityLevel": "paper-evidence-only", "warnings": [], "nextMilestones": []}}
        performance = {"closedMetrics": {"scoredCount": 1}, "deskVerdict": {"level": "evidence-building"}}
        strategy_pricing = {
            "items": [
                {
                    "ticker": "USAR",
                    "status": "priced",
                    "combinedPassed": True,
                    "paperVariantOnly": True,
                    "paperVariantFamily": "wheel-proxy",
                    "expiration": "2026-08-21",
                    "recommendedStrategy": "PUT_CREDIT_SPREAD",
                    "sourceAlternativeScore": 55.87,
                    "strikePlan": {
                        "paperVariantOnly": True,
                        "sourcePaperVariant": True,
                        "variantForStrategy": "wheel-proxy",
                        "strategy": "PUT_CREDIT_SPREAD",
                        "expiration": "2026-08-21",
                        "estimatedMaxLoss": 198.0,
                        "estimatedCredit": 1.02,
                    },
                    "riskVerdict": {"passed": True, "blocks": [], "warnings": []},
                }
            ]
        }
        ledger = {
            "items": [
                {"ticker": "USAR", "eventId": "USAR|2026-08-21", "status": "paper-staged", "outcome": {"status": "open"}},
                {"ticker": "USAR", "eventId": "USAR|2026-08-21", "status": "paper-staged", "outcome": {"status": "scored"}},
            ]
        }
        mock_load_strike_plan.return_value = ({"items": []}, False)
        mock_load_json_file.side_effect = [
            snapshot,
            approval_queue,
            execution_queue,
            sandbox,
            authority,
            performance,
            strategy_pricing,
            ledger,
        ]

        payload = build_director()

        self.assertEqual(payload["verdict"], "paper-variant-watch")
        self.assertEqual(payload["counts"]["pricedPaperVariantWatch"], 1)
        self.assertEqual(payload["counts"]["paperResearchSelected"], 0)
        row = payload["pricedPaperVariantWatchlist"][0]
        self.assertTrue(row["eventCapped"])
        self.assertFalse(row["paperResearchSelected"])
        self.assertIn("cap 2", row["eventCapReason"])

    @patch("inferno_paper_test_director.load_strike_plan")
    @patch("inferno_paper_test_director.load_json_file")
    def test_build_director_caps_repeated_distinct_event(
        self,
        mock_load_json_file,
        mock_load_strike_plan,
    ) -> None:
        strike_plan = {
            "items": [
                {
                    "ticker": "WSC",
                    "ok": True,
                    "approvalStatus": "pending",
                    "intentStatus": "blocked",
                    "setupRec": "Straddle",
                    "daysUntilEarnings": 2,
                    "trackerContext": {"nextEarnings": "2026-07-08"},
                    "price": 50.0,
                    "ivRank": 25.0,
                    "atrPercent": 3.0,
                    "forecastRealizedMovePct": 12.0,
                    "marketContextSummary": {"trend": "Bullish", "ivRank": 25.0, "atrPercent": 3.0},
                    "strikePlan": {
                        "strategy": "LONG_STRADDLE",
                        "expiration": "2026-07-17",
                        "estimatedMaxLoss": 495.0,
                        "estimatedDebit": 5.5,
                        "lowerBreakEven": 44.5,
                        "upperBreakEven": 55.5,
                        "greekSummary": {
                            "netDelta": 0.0,
                            "netGamma": 0.1,
                            "netTheta": -0.2,
                            "netVega": 0.3,
                            "greeksComplete": True,
                        },
                        "liquidityNotes": [],
                    },
                    "riskVerdict": {"passed": True, "blocks": [], "warnings": []},
                }
            ]
        }
        ledger = {
            "items": [
                {
                    "ticker": "WSC",
                    "eventId": "WSC|2026-07-08",
                    "status": "paper-staged",
                    "outcome": {"status": "open"},
                },
                {
                    "ticker": "WSC",
                    "eventId": "WSC|2026-07-08",
                    "status": "paper-staged",
                    "outcome": {"status": "scored"},
                },
            ]
        }
        mock_load_strike_plan.return_value = (strike_plan, False)
        mock_load_json_file.side_effect = [
            {"eligibleTickers": ["WSC"], "reviewQueueTickers": ["WSC"]},
            {"items": []},
            {"items": [{"ticker": "WSC", "readiness": 88}], "updatedAt": "2026-07-06T10:00:00-06:00"},
            {"stageableTickets": [], "watchlistTickets": [], "blockedTickets": []},
            {"decision": {"authorityLevel": "paper-evidence-only", "warnings": [], "nextMilestones": []}},
            {"closedMetrics": {"scoredCount": 2}, "deskVerdict": {"level": "evidence-building"}},
            {"items": []},
            ledger,
        ]

        payload = build_director()

        self.assertEqual(payload["verdict"], "event-capped")
        self.assertTrue(payload["paperCycleHealthy"])
        self.assertEqual(payload["counts"]["eventCapped"], 1)
        self.assertEqual(payload["counts"]["autoPaperSelected"], 0)
        self.assertEqual(payload["eventCappedSlate"][0]["eventId"], "WSC|2026-07-08")
        self.assertIn("cap 2", payload["eventCappedSlate"][0]["eventCapReason"])

    def test_split_candidates_prefers_zero_ticket_events_for_auto_paper(self) -> None:
        candidates = [
            {
                "ticker": "OLD",
                "category": "auto-paper-selected",
                "priorityScore": 99,
                "estimatedMaxLoss": 100,
                "eventTicketCount": 1,
            },
            {
                "ticker": "NEW",
                "category": "auto-paper-selected",
                "priorityScore": 80,
                "estimatedMaxLoss": 150,
                "eventTicketCount": 0,
            },
        ]

        _, auto_paper, *_ = split_candidates(candidates)

        self.assertEqual([item["ticker"] for item in auto_paper], ["NEW", "OLD"])


if __name__ == "__main__":
    unittest.main()
