from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import inferno_paper_blocker_swarm as swarm


NOW = datetime(2026, 6, 24, 9, 30, tzinfo=ZoneInfo("America/Denver"))


def hard_blocked_director() -> dict:
    return {
        "generatedAt": NOW.isoformat(),
        "verdict": "no-viable-paper-tests",
        "authorityLevel": "paper-evidence-only",
        "counts": {
            "totalCandidates": 1,
            "stageableNow": 0,
            "autoPaperSelected": 0,
            "approvalOnly": 0,
            "hardBlocked": 1,
        },
        "hardBlockedSlate": [
            {
                "ticker": "MEI",
                "category": "failed-construction",
                "strategy": "Straddle",
                "readiness": 90,
                "priorityScore": 60.42,
                "reasons": [
                    "human approval is missing",
                    "human approval still required",
                    "no supported strike plan for Straddle across expirations",
                    "source price $14.12 diverges from Schwab underlying $13.40 by 5.10%; refresh tracker/execution queue before staging",
                    "Schwab option chain quality block: no-liquid-contracts",
                    "Schwab quote quality 36/poor is below paper threshold",
                    "Schwab ATM liquidity score 26 is too thin",
                    "Decision card incomplete or the premium hurdle failed: maximum-loss, net-greeks, long-vol-premium-hurdle",
                ],
                "warnings": ["Schwab option chain warning: thin-atm-liquidity"],
            }
        ],
    }


def cap_fit() -> dict:
    return {
        "generatedAt": NOW.isoformat(),
        "verdict": "universe-well-suited-to-cap",
        "counts": {"anyFits": 1, "total": 1},
        "perTicker": [
            {
                "ticker": "MEI",
                "verdict": "any-fits",
                "structures": {
                    "straddle": 334.79,
                    "long_leg": 167.40,
                    "debit_5w": 193.94,
                    "credit_1w": 64.85,
                },
                "fits": {
                    "straddle": True,
                    "long_leg": True,
                    "debit_5w": True,
                    "credit_1w": True,
                },
            }
        ],
    }


def empty_alt_context() -> dict:
    return {
        "generatedAt": NOW.isoformat(),
        "verdict": "no-pressure-candidates",
        "counts": {},
    }


class PaperBlockerSwarmTests(unittest.TestCase):
    def test_hard_blocker_is_split_into_parallel_lanes(self) -> None:
        payload = swarm.build_swarm(
            paper_director=hard_blocked_director(),
            universe_cap_fit=cap_fit(),
            alternative_scorer=empty_alt_context(),
            alternative_pricing={"verdict": "no-priceable-candidates", "counts": {}},
            shadow_comparison={"verdict": "no-passing-alternatives", "counts": {}},
            expected_move={"verdict": "move-edge-negative", "counts": {}},
            now=NOW,
        )

        self.assertEqual(payload["verdict"], "fixable-blockers-present")
        self.assertTrue(payload["researchOnly"])
        self.assertTrue(payload["diagnosticOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["authorityChanged"])
        self.assertFalse(payload["brokerSubmitAllowed"])
        self.assertFalse(payload["liveTradingAllowed"])
        self.assertEqual(payload["counts"]["blockedCandidatesAnalyzed"], 1)
        self.assertEqual(payload["counts"]["operatorActionRequired"], 1)
        self.assertEqual(payload["counts"]["marketDataBlocked"], 1)
        self.assertEqual(payload["counts"]["marketQualityBlocked"], 1)
        self.assertEqual(payload["counts"]["strategyFallbackSuggested"], 1)
        self.assertEqual(payload["counts"]["fixableByTooling"], 1)
        self.assertEqual(payload["dominantLane"], "data_freshness")
        self.assertEqual(payload["rewards"]["coverageReward"], 1.0)
        self.assertEqual(payload["rewards"]["finishReward"], 1.0)
        self.assertEqual(payload["rewards"]["outcomeReward"], 0.0)
        self.assertFalse(payload["rewards"]["acceptedOutcome"])

        finding = payload["candidateFindings"][0]
        self.assertEqual(finding["ticker"], "MEI")
        self.assertEqual(finding["fixability"], "data-refresh")
        self.assertTrue(finding["strategyFallbackSuggested"])
        self.assertIn("5-wide debit spread", finding["capFit"]["boundedFits"])
        self.assertIn("operator_action", finding["activeLanes"])
        self.assertIn("data_freshness", finding["activeLanes"])
        self.assertIn("liquidity", finding["activeLanes"])
        self.assertIn("strike_construction", finding["activeLanes"])
        self.assertIn("premium_hurdle", finding["activeLanes"])

    def test_no_blocked_candidates_is_safe_clean_diagnostic(self) -> None:
        payload = swarm.build_swarm(
            paper_director={
                "generatedAt": NOW.isoformat(),
                "verdict": "auto-paper-selected",
                "authorityLevel": "paper-evidence-only",
                "counts": {
                    "totalCandidates": 1,
                    "stageableNow": 0,
                    "autoPaperSelected": 1,
                    "approvalOnly": 0,
                    "hardBlocked": 0,
                },
                "hardBlockedSlate": [],
            },
            universe_cap_fit={"verdict": "universe-well-suited-to-cap", "perTicker": []},
            now=NOW,
        )

        self.assertEqual(payload["verdict"], "no-blocked-candidates")
        self.assertEqual(payload["counts"]["blockedCandidatesAnalyzed"], 0)
        self.assertEqual(payload["counts"]["assignedSubtasks"], 0)
        self.assertEqual(payload["rewards"]["finishReward"], 1.0)
        self.assertEqual(payload["rewards"]["outcomeReward"], 0.0)

    def test_approval_only_stays_operator_owned(self) -> None:
        payload = swarm.build_swarm(
            paper_director={
                "generatedAt": NOW.isoformat(),
                "verdict": "approval-bottleneck",
                "authorityLevel": "paper-evidence-only",
                "counts": {
                    "totalCandidates": 1,
                    "stageableNow": 0,
                    "autoPaperSelected": 0,
                    "approvalOnly": 1,
                    "hardBlocked": 0,
                },
                "approvalSlate": [
                    {
                        "ticker": "AAA",
                        "category": "approval-only",
                        "strategy": "Debit Spread",
                        "reasons": ["human approval still required"],
                    }
                ],
            },
            universe_cap_fit={"verdict": "universe-well-suited-to-cap", "perTicker": []},
            now=NOW,
        )

        self.assertEqual(payload["verdict"], "operator-action-required")
        self.assertEqual(payload["counts"]["operatorActionRequired"], 1)
        self.assertEqual(payload["counts"]["fixableByTooling"], 0)
        self.assertEqual(payload["candidateFindings"][0]["dominantLane"], "operator_action")
        self.assertEqual(payload["candidateFindings"][0]["fixability"], "operator-action")

    def test_render_text_exposes_reward_and_safety_contract(self) -> None:
        payload = swarm.build_swarm(
            paper_director=hard_blocked_director(),
            universe_cap_fit=cap_fit(),
            now=NOW,
        )
        text = swarm.render_text(payload)

        self.assertIn("Inferno Paper Blocker Swarm", text)
        self.assertIn("outcome reward: 0.0", text)
        self.assertIn("broker submit OFF", text)
        self.assertIn("MEI | Straddle", text)


if __name__ == "__main__":
    unittest.main()
