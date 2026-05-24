"""Contract tests for inferno_paper_velocity.

Pinned invariants:
  - Module is research-only and promotable=False.
  - Status / outcome distributions reflect the ledger faithfully.
  - Closed-outcome counts use ``outcome.reviewedAt`` as the close timestamp.
  - Closed-outcome rolling windows (7 / 30 / 90 days) are inclusive.
  - Weekly rate is the 30d count scaled to weeks; zero rate => projection is None.
  - Verdict tiers: ``stalled`` < 4 closed last 30d, ``slow`` 4-9, ``on-track`` >= 10,
    ``promotion-ready`` if total closed >= 30 regardless of recent rate.
  - Approval-aging-out includes only ``paperOnly`` tickets with
    ``approvalStatus=pending`` and future expirations inside the window.
  - Approval zombies (past-expiration counterpart) are counted separately
    so the operator sees both "fix this now" and "this is dead".
  - paperAutoBlockReason histogram excludes ``ok`` and ``not-evaluated``
    so the diagnostic surface highlights real failures.
  - Empty ledger produces a clean ``stalled`` verdict, not a crash.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta

from inferno_paper_velocity import (
    AGING_OUT_WINDOW_DAYS,
    ON_TRACK_THRESHOLD_30D,
    PAPER_VELOCITY_STAGE,
    PROMOTION_TARGET,
    SLOW_THRESHOLD_30D,
    _approval_aging_alert,
    _auto_block_reason_distribution,
    _closed_outcome_velocity,
    _outcome_distribution,
    _status_distribution,
    _verdict,
    build_paper_velocity,
    paper_velocity_text,
)


TODAY = date(2026, 5, 24)


def _closed_ticket(*, days_ago: int) -> dict:
    """Helper: a closed ticket whose reviewedAt is N days before TODAY."""
    reviewed = (TODAY - timedelta(days=days_ago)).isoformat()
    return {
        "status": "paper-staged",
        "outcome": {"status": "closed", "reviewedAt": reviewed},
    }


def _aging_ticket(*, ticker: str, days_until_exp: int) -> dict:
    """Helper: a paper-only pending-approval ticket with future expiration."""
    return {
        "ticker": ticker,
        "strategy": "LONG_STRADDLE",
        "paperOnly": True,
        "approvalStatus": "pending",
        "expiration": (TODAY + timedelta(days=days_until_exp)).isoformat(),
        "ticketId": f"t-{ticker}",
    }


class StatusAndOutcomeDistributionTests(unittest.TestCase):
    def test_status_distribution_counts_every_status(self) -> None:
        items = [
            {"status": "paper-staged"},
            {"status": "paper-blocked"},
            {"status": "paper-blocked"},
            {"status": "paper-rejected"},
        ]
        self.assertEqual(
            _status_distribution(items),
            {"paper-staged": 1, "paper-blocked": 2, "paper-rejected": 1},
        )

    def test_outcome_distribution_handles_missing_outcome(self) -> None:
        items = [
            {"outcome": {"status": "closed"}},
            {"outcome": {"status": "open"}},
            {},  # no outcome key
        ]
        dist = _outcome_distribution(items)
        self.assertEqual(dist.get("closed"), 1)
        self.assertEqual(dist.get("open"), 1)


class VelocityRateTests(unittest.TestCase):
    def test_no_closed_tickets_returns_unknown_projection(self) -> None:
        velocity = _closed_outcome_velocity([], today=TODAY)
        self.assertEqual(velocity["totalClosed"], 0)
        self.assertEqual(velocity["weeklyRate30dWindow"], 0.0)
        self.assertIsNone(velocity["projectedWeeksToPromotion"])
        self.assertIsNone(velocity["projectedClearanceDate"])

    def test_recent_closes_drive_projection(self) -> None:
        items = [_closed_ticket(days_ago=i) for i in range(0, 12)]  # 12 in last 30d
        velocity = _closed_outcome_velocity(items, today=TODAY)
        self.assertEqual(velocity["closedLast30Days"], 12)
        self.assertGreater(velocity["weeklyRate30dWindow"], 0)
        self.assertIsNotNone(velocity["projectedWeeksToPromotion"])

    def test_promotion_target_already_reached(self) -> None:
        items = [_closed_ticket(days_ago=i % 60) for i in range(35)]
        velocity = _closed_outcome_velocity(items, today=TODAY)
        self.assertEqual(velocity["remainingToPromotion"], 0)
        self.assertEqual(velocity["projectedWeeksToPromotion"], 0.0)


class VerdictTests(unittest.TestCase):
    def _velocity(self, *, total: int, last_30: int) -> dict:
        return {
            "totalClosed": total,
            "closedLast30Days": last_30,
        }

    def test_stalled_when_recent_rate_below_slow_floor(self) -> None:
        self.assertEqual(_verdict(self._velocity(total=2, last_30=SLOW_THRESHOLD_30D - 1)), "stalled")

    def test_slow_in_middle_band(self) -> None:
        self.assertEqual(_verdict(self._velocity(total=SLOW_THRESHOLD_30D, last_30=SLOW_THRESHOLD_30D)), "slow")

    def test_on_track_at_threshold(self) -> None:
        self.assertEqual(_verdict(self._velocity(total=ON_TRACK_THRESHOLD_30D, last_30=ON_TRACK_THRESHOLD_30D)), "on-track")

    def test_promotion_ready_overrides_recent_rate(self) -> None:
        # Even with zero recent closes, hitting the total target promotes.
        self.assertEqual(_verdict(self._velocity(total=PROMOTION_TARGET, last_30=0)), "promotion-ready")


class ApprovalAgingAlertTests(unittest.TestCase):
    def test_includes_pending_paper_only_tickets_in_window(self) -> None:
        items = [
            _aging_ticket(ticker="AAA", days_until_exp=3),
            _aging_ticket(ticker="BBB", days_until_exp=AGING_OUT_WINDOW_DAYS),
        ]
        alert = _approval_aging_alert(items, today=TODAY, window_days=AGING_OUT_WINDOW_DAYS)
        tickers = {row["ticker"] for row in alert["agingOut"]}
        self.assertEqual(tickers, {"AAA", "BBB"})
        self.assertEqual(alert["zombieCount"], 0)

    def test_excludes_non_paper_only(self) -> None:
        item = _aging_ticket(ticker="AAA", days_until_exp=3)
        item["paperOnly"] = False
        alert = _approval_aging_alert([item], today=TODAY, window_days=AGING_OUT_WINDOW_DAYS)
        self.assertEqual(alert["agingOut"], [])

    def test_excludes_already_approved(self) -> None:
        item = _aging_ticket(ticker="AAA", days_until_exp=3)
        item["approvalStatus"] = "approved"
        alert = _approval_aging_alert([item], today=TODAY, window_days=AGING_OUT_WINDOW_DAYS)
        self.assertEqual(alert["agingOut"], [])

    def test_past_expiration_counted_as_zombie(self) -> None:
        item = _aging_ticket(ticker="AAA", days_until_exp=-5)
        alert = _approval_aging_alert([item], today=TODAY, window_days=AGING_OUT_WINDOW_DAYS)
        self.assertEqual(alert["zombieCount"], 1)
        self.assertEqual(alert["agingOut"], [])


class AutoBlockReasonHistogramTests(unittest.TestCase):
    def test_only_paper_blocked_tickets_contribute(self) -> None:
        items = [
            {"status": "paper-staged", "paperAutoBlockReason": "ok"},
            {"status": "paper-blocked", "paperAutoBlockReason": "risk-verdict-failed"},
            {"status": "paper-blocked", "paperAutoBlockReason": "risk-verdict-failed"},
            {"status": "paper-blocked", "paperAutoBlockReason": "intent-status-not-eligible: 'foo'"},
        ]
        hist = _auto_block_reason_distribution(items)
        # The 'intent-status-not-eligible: ...' reason is normalized to its head
        # so frequency surfaces cleanly even when the tail differs.
        reasons = {entry["reason"]: entry["count"] for entry in hist}
        self.assertEqual(reasons.get("risk-verdict-failed"), 2)
        self.assertEqual(reasons.get("intent-status-not-eligible"), 1)
        self.assertNotIn("ok", reasons)

    def test_not_evaluated_is_excluded(self) -> None:
        items = [
            {"status": "paper-blocked", "paperAutoBlockReason": "not-evaluated"},
            {"status": "paper-blocked", "paperAutoBlockReason": "item-not-ok"},
        ]
        hist = _auto_block_reason_distribution(items)
        reasons = {entry["reason"] for entry in hist}
        self.assertEqual(reasons, {"item-not-ok"})


class BuildAndRenderTests(unittest.TestCase):
    def test_module_is_research_only(self) -> None:
        self.assertEqual(PAPER_VELOCITY_STAGE, "paper-velocity-research-only")

    def test_build_against_live_data_is_research_only(self) -> None:
        payload = build_paper_velocity()
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["authorityChanged"])
        self.assertIn(payload["verdict"], {"stalled", "slow", "on-track", "promotion-ready"})
        self.assertEqual(payload["thresholds"]["promotionTarget"], PROMOTION_TARGET)

    def test_text_render_includes_key_sections(self) -> None:
        payload = build_paper_velocity(now=datetime(2026, 5, 24, 9, 0, 0))
        text = paper_velocity_text(payload)
        self.assertIn("Inferno Paper Evidence Velocity", text)
        self.assertIn("Verdict:", text)
        self.assertIn("Closed-outcome velocity:", text)
        self.assertIn("Approval alerts:", text)
        self.assertIn("Reminders:", text)


if __name__ == "__main__":
    unittest.main()
