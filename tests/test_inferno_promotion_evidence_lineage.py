from __future__ import annotations

import unittest

import inferno_promotion_evidence_lineage as lineage


def paper_ticket(
    ticket_id: str,
    *,
    status: str = "paper-staged",
    outcome_status: str = "closed",
    estimated_pnl: float | None = 25.0,
    max_loss: float = 100.0,
) -> dict:
    return {
        "ticketId": ticket_id,
        "ticker": "TEST",
        "strategy": "CALL_DEBIT_SPREAD",
        "eventId": f"TEST|2026-08-{ticket_id[-2:]}",
        "status": status,
        "estimatedMaxLoss": max_loss,
        "outcome": {"status": outcome_status, "estimatedPnl": estimated_pnl},
    }


class PromotionEvidenceLineageTests(unittest.TestCase):
    def test_only_closed_staged_paper_with_usable_risk_qualifies(self) -> None:
        payload = lineage.build_promotion_evidence_lineage(
            paper_ledger={
                "items": [
                    paper_ticket("paper-01"),
                    paper_ticket("paper-02", status="paper-blocked", outcome_status="not-opened"),
                    paper_ticket("paper-03", outcome_status="open"),
                    paper_ticket("paper-04", estimated_pnl=None),
                ]
            },
            fast_ledger={"items": []},
            shadow_evidence={"items": []},
            strategy_lab={"overall": {"scoredCount": 1}},
        )

        promotion = payload["promotion"]
        paper = payload["sources"][lineage.PAPER_SOURCE]
        self.assertEqual(promotion["qualifiedPaperOutcomes"], 1)
        self.assertEqual(promotion["remainingForPromotion"], 29)
        self.assertTrue(promotion["strategyLabCountMatchesLineage"])
        self.assertTrue(promotion["strictPolicyMatchesStrategyLab"])
        self.assertEqual(paper["exclusionReasons"]["paper-status-paper-blocked"], 1)
        self.assertEqual(paper["exclusionReasons"]["paper-outcome-open"], 1)
        self.assertEqual(paper["exclusionReasons"]["closed-paper-row-missing-usable-pnl-or-risk"], 1)

    def test_fast_and_shadow_closed_outcomes_remain_quarantined(self) -> None:
        payload = lineage.build_promotion_evidence_lineage(
            paper_ledger={"items": []},
            fast_ledger={"items": [paper_ticket("fast-01")]},
            shadow_evidence={"items": [paper_ticket("shadow-01")]},
            strategy_lab={"overall": {"scoredCount": 0}},
        )

        self.assertEqual(payload["promotion"]["qualifiedPaperOutcomes"], 0)
        self.assertEqual(
            payload["sources"][lineage.FAST_SOURCE]["exclusionReasons"],
            {"isolated-fast-simulations-never-earn-promotion-credit": 1},
        )
        self.assertEqual(
            payload["sources"][lineage.SHADOW_SOURCE]["exclusionReasons"],
            {"shadow-observations-never-earn-promotion-credit": 1},
        )

    def test_nonstaged_row_counted_by_lab_is_an_integrity_attention(self) -> None:
        payload = lineage.build_promotion_evidence_lineage(
            paper_ledger={"items": [paper_ticket("paper-05", status="paper-blocked")]},
            fast_ledger={"items": []},
            shadow_evidence={"items": []},
            strategy_lab={"overall": {"scoredCount": 1}},
        )

        self.assertEqual(payload["promotion"]["qualifiedPaperOutcomes"], 0)
        self.assertEqual(payload["promotion"]["integrityAttentionCount"], 1)
        self.assertFalse(payload["promotion"]["strictPolicyMatchesStrategyLab"])
        self.assertEqual(
            payload["integrityAttention"][0]["exclusionReason"],
            "strategy-lab-counts-nonstaged-paper-row",
        )


if __name__ == "__main__":
    unittest.main()
