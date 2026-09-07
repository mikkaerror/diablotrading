from __future__ import annotations

"""Regression tests for the shadow evidence research lane.

Shadow evidence must help the desk learn without accidentally becoming an
execution permission. These tests pin the important safety flags and outcome
math before the module is wired into daily automation.
"""

import unittest
from datetime import date
from unittest.mock import patch

from inferno_shadow_evidence import (
    build_shadow_entry,
    build_shadow_evidence,
    load_strike_plan,
    expiration_price_evidence,
    merge_shadow_entry,
    review_shadow_ticket,
    shadow_ticket_ready_for_review,
)


def strike_item(expiration: str = "2026-04-20") -> dict[str, object]:
    """Build a minimal valid strike-plan item for shadow tests."""
    return {
        "ticker": "TEST",
        "setupRec": "Vertical Call",
        "ok": True,
        "price": 10.0,
        "daysUntilEarnings": 7,
        "intentStatus": "blocked",
        "approvalStatus": "pending",
        "strikePlan": {
            "strategy": "CALL_DEBIT_SPREAD",
            "expiration": expiration,
            "estimatedDebit": 1.0,
            "estimatedMaxLoss": 100.0,
            "estimatedMaxProfit": 100.0,
            "legs": [
                {
                    "instruction": "BUY_TO_OPEN",
                    "putCall": "CALL",
                    "symbol": "TEST260420C00010000",
                    "expiration": expiration,
                    "strike": 10.0,
                }
            ],
        },
    }


class ShadowEvidenceTests(unittest.TestCase):
    """Verify shadow research stays useful and non-executable."""

    def test_entry_is_shadow_only_even_when_not_approved(self) -> None:
        """A valid strike plan can be studied without gaining authority."""
        entry = build_shadow_entry(strike_item(), "2026-04-13T07:45:00-06:00", {"items": []})
        self.assertEqual(entry["status"], "shadow-open")
        self.assertTrue(entry["shadowOnly"])
        self.assertTrue(entry["paperOnly"])
        self.assertFalse(entry["liveTradingAllowed"])
        self.assertFalse(entry["brokerSubmitAllowed"])
        self.assertFalse(entry["authorityEligible"])

    def test_entry_preserves_score_context_for_option_calibration(self) -> None:
        """Shadow option outcomes should keep their entry-time rank context."""
        item = {
            **strike_item(),
            "readiness": 89,
            "priority": 5.75,
            "scenarioScore": 76.2,
            "routeFamily": "defined-risk directional",
            "sourceRecommendedStrategy": "PAPER_VARIANT_SCANNER",
            "sourceAlternativeScore": 73.0,
        }
        entry = build_shadow_entry(item, "2026-04-13T07:45:00-06:00", {"items": []})

        self.assertEqual(entry["readiness"], 89)
        self.assertEqual(entry["priorityScore"], 5.75)
        self.assertEqual(entry["scenarioScore"], 76.2)
        self.assertEqual(entry["setupFamily"], "defined-risk directional")
        self.assertEqual(entry["sourceRecommendedStrategy"], "PAPER_VARIANT_SCANNER")
        self.assertEqual(entry["sourceAlternativeScore"], 73.0)
        self.assertFalse(entry["brokerSubmitAllowed"])
        refreshed = build_shadow_entry({**item, "readiness": 99}, "2026-04-14T07:45:00-06:00", {"items": []})
        merged = merge_shadow_entry(entry, refreshed)
        self.assertEqual(merged["entryScoreSnapshot"]["readiness"], 89)
        self.assertEqual(merged["readiness"], 99)
        legacy = {k: v for k, v in entry.items() if not k.startswith("entryScoreSnapshot")}
        self.assertIsNone(merge_shadow_entry(legacy, refreshed)["entryScoreSnapshot"])

    def test_build_shadow_evidence_dedupes_same_candidate(self) -> None:
        """Repeated runs refresh the same semantic ticket instead of duplicating."""
        plan = {
            "generatedAt": "2026-04-13T07:45:00-06:00",
            "items": [strike_item(expiration="2026-05-15")],
        }
        first = build_shadow_evidence(plan, {"items": []})
        second = build_shadow_evidence(plan, first)
        self.assertEqual(first["count"], 1)
        self.assertEqual(second["count"], 1)
        self.assertEqual(second["lastRun"]["inserted"], 0)

    def test_shadow_ledger_records_source_and_success_lifecycle(self) -> None:
        plan = {"generatedAt": "2026-07-26T09:00:00-06:00", "items": []}

        ledger = build_shadow_evidence(plan, {"items": []})

        self.assertEqual(ledger["sourceDataAsOf"], "2026-07-26T09:00:00-06:00")
        self.assertEqual(ledger["lifecycleStatus"], "success")
        self.assertEqual(ledger["producer"], "inferno-shadow-evidence")
        self.assertEqual(ledger["freshnessPolicy"]["ttlHours"], 36)

    @patch("inferno_shadow_evidence.save_strike_plan")
    @patch("inferno_shadow_evidence.build_strike_plan")
    @patch("inferno_shadow_evidence.load_json_file")
    def test_load_strike_plan_refreshes_when_stale(
        self,
        load_json_file_mock,
        build_strike_plan_mock,
        save_strike_plan_mock,
    ) -> None:
        """Shadow research should rebuild stale strike plans before analysis."""
        stale_plan = {
            "generatedAt": "2026-05-01T07:45:00-06:00",
            "items": [strike_item(expiration="2026-05-15")],
        }
        fresh_plan = {
            "generatedAt": "2026-05-10T07:45:00-06:00",
            "items": [strike_item(expiration="2026-05-15")],
        }
        load_json_file_mock.side_effect = [stale_plan, {}]
        build_strike_plan_mock.return_value = fresh_plan

        plan, refreshed = load_strike_plan(refresh_if_stale=True)

        self.assertTrue(refreshed)
        self.assertEqual(plan["generatedAt"], fresh_plan["generatedAt"])
        build_strike_plan_mock.assert_called_once()
        save_strike_plan_mock.assert_called_once_with(fresh_plan)

    @patch("inferno_shadow_evidence.save_strike_plan")
    @patch("inferno_shadow_evidence.build_strike_plan")
    @patch("inferno_shadow_evidence.load_json_file")
    def test_build_shadow_evidence_marks_auto_refresh(
        self,
        load_json_file_mock,
        build_strike_plan_mock,
        save_strike_plan_mock,
    ) -> None:
        """The ledger should record when it regenerated a stale source plan."""
        stale_plan = {
            "generatedAt": "2026-05-01T07:45:00-06:00",
            "items": [strike_item(expiration="2026-05-15")],
        }
        fresh_plan = {
            "generatedAt": "2026-05-10T07:45:00-06:00",
            "items": [strike_item(expiration="2026-05-15")],
        }
        load_json_file_mock.side_effect = [stale_plan, {}, {"items": []}]
        build_strike_plan_mock.return_value = fresh_plan

        with patch("inferno_shadow_evidence.expiration_price_evidence", return_value=None):
            ledger = build_shadow_evidence()

        self.assertTrue(ledger["sourceStrikePlanRefreshed"])
        self.assertEqual(ledger["sourceStrikePlanGeneratedAt"], fresh_plan["generatedAt"])
        save_strike_plan_mock.assert_called_once_with(fresh_plan)

    @patch("inferno_shadow_evidence.in_current_service_cycle", return_value=True)
    @patch("inferno_shadow_evidence.load_json_file")
    def test_load_strike_plan_prefers_expanded_rehearsal_plan(self, load_json_file_mock, _fresh_mock) -> None:
        """Shadow evidence should use the wider rehearsal plan when it is fresh."""
        primary_plan = {
            "generatedAt": "2026-05-13T00:00:00-06:00",
            "items": [strike_item(expiration="2026-05-15")],
        }
        rehearsal_plan = {
            "generatedAt": "2026-05-13T00:05:00-06:00",
            "sourceUniverse": "expanded-eligible-universe",
            "items": [
                strike_item(expiration="2026-05-15"),
                {**strike_item(expiration="2026-05-15"), "ticker": "WIDE"},
            ],
        }
        load_json_file_mock.side_effect = [primary_plan, rehearsal_plan]

        plan, refreshed = load_strike_plan(refresh_if_stale=True)

        self.assertFalse(refreshed)
        self.assertEqual(plan["sourceUniverse"], "expanded-eligible-universe")
        self.assertEqual(len(plan["items"]), 2)

    def test_future_shadow_ticket_waits_for_expiration(self) -> None:
        """The reviewer should not close a ticket before expiration."""
        entry = build_shadow_entry(strike_item(expiration="2099-01-20"), "2026-04-13T07:45:00-06:00", {"items": []})
        ready, reason = shadow_ticket_ready_for_review(entry)
        self.assertFalse(ready)
        self.assertIn("expiration has not arrived", reason)

    def test_expiration_day_must_finish_before_review(self) -> None:
        ticket = {"status": "shadow-open", "outcome": {"status": "open"}, "expiration": "2026-09-04"}
        self.assertFalse(shadow_ticket_ready_for_review(ticket, today=date(2026, 9, 4))[0])
        self.assertTrue(shadow_ticket_ready_for_review(ticket, today=date(2026, 9, 5))[0])

    @patch("inferno_shadow_evidence.load_json_file")
    def test_expiration_price_requires_exact_day_and_later_capture(self, load) -> None:
        payload = {"generatedAt": "2026-09-05T09:00:00-04:00", "rows": [{
            "symbol": "TEST", "status": "ok", "candles": [
                {"datetime": "2026-09-03T05:00:00+00:00", "close": 10},
                {"datetime": "2026-09-04T05:00:00+00:00", "close": 12},
                {"datetime": "2026-09-07T05:00:00+00:00", "close": 99},
            ]}]}
        load.return_value = payload
        result = expiration_price_evidence("TEST", date(2026, 9, 4))
        self.assertEqual(result["price"], 12)
        self.assertEqual(result["priceDate"], "2026-09-04")
        self.assertIsNone(expiration_price_evidence("TEST", date(2026, 9, 2)))
        self.assertIsNone(expiration_price_evidence("MISSING", date(2026, 9, 4)))
        for captured in ["2026-09-04T10:00:00-04:00", "2026-09-05T01:00:00+00:00", "2026-09-05", "bad"]:
            payload["generatedAt"] = captured
            self.assertIsNone(expiration_price_evidence("TEST", date(2026, 9, 4)))

    @patch("inferno_shadow_evidence.expiration_price_evidence", return_value=None)
    def test_missing_expiration_price_waits_without_inventing_pnl(self, lookup) -> None:
        entry = build_shadow_entry(strike_item(), "2026-04-13T07:45:00-06:00", {"items": []})
        updated, _, _ = review_shadow_ticket(entry)
        self.assertEqual(updated["outcome"]["status"], "review-pending")
        self.assertIsNone(updated["outcome"]["estimatedPnl"])

    @patch("inferno_shadow_evidence.expiration_price_evidence", return_value={"price": 12.0, "priceDate": "2026-04-20"})
    def test_review_closes_expired_ticket_with_research_pnl(self, _price_mock) -> None:
        """Expired shadow tickets are scored using the shared option payoff math."""
        entry = build_shadow_entry(strike_item(), "2026-04-13T07:45:00-06:00", {"items": []})
        updated, changed, note = review_shadow_ticket(entry)
        outcome = updated["outcome"]
        self.assertTrue(changed)
        self.assertEqual(note, "closed")
        self.assertEqual(outcome["status"], "closed")
        self.assertEqual(outcome["estimatedPnl"], 100.0)
        self.assertEqual(outcome["estimatedReturnOnRisk"], 1.0)
        self.assertFalse(updated["brokerSubmitAllowed"])


if __name__ == "__main__":
    unittest.main()
