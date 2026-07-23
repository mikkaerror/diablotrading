from __future__ import annotations

"""Tests for the research-only paper work-order renderer.

These lock in two things: that the renderer turns already-computed strike
plans into a correct, operator-readable order sheet, and that it never
drifts across the safety line into staging or authority.
"""

import unittest
from unittest.mock import patch

import inferno_paper_work_order as wo


def _spread(ticker: str, max_loss: float, *, complete: bool = True) -> dict:
    """A CALL_DEBIT_SPREAD strike plan with a known max loss."""
    legs = [
        {
            "instruction": "BUY_TO_OPEN",
            "putCall": "CALL",
            "symbol": f"{ticker}260821C00130000" if complete else "",
            "expiration": "2026-08-21",
            "strike": 130.0 if complete else None,
            "mid": 6.65,
        },
        {
            "instruction": "SELL_TO_OPEN",
            "putCall": "CALL",
            "symbol": f"{ticker}260821C00135000",
            "expiration": "2026-08-21",
            "strike": 135.0,
            "mid": 4.95,
        },
    ]
    return {
        "strategy": "CALL_DEBIT_SPREAD",
        "direction": "bullish-defined-risk",
        "expiration": "2026-08-21",
        "legs": legs,
        "estimatedDebit": round(max_loss / 100, 2),
        "estimatedMaxLoss": max_loss,
        "estimatedMaxProfit": 270.0,
        "breakEven": 132.3,
        "width": 5.0,
    }


def _plan(*items: dict) -> dict:
    return {"generatedAt": "2026-07-22T18:30:39-06:00", "items": list(items)}


class PaperWorkOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        # Pin the cap so tests do not depend on the ambient env override.
        self._cap_patch = patch.object(wo, "MAX_SINGLE_TICKET_DOLLARS", 500.0)
        self._cap_patch.start()
        self.addCleanup(self._cap_patch.stop)

    def test_awaiting_plan_when_no_strike_plan(self) -> None:
        # None means "load from disk"; patch the loader so the missing-file
        # path is what gets exercised, not the ambient real artifact.
        with patch.object(wo, "load_json_file", return_value=None):
            payload = wo.build_work_order(strike_plan_report=None, evidence_loop={})
        self.assertEqual(payload["verdict"], "awaiting-strike-plan")
        self.assertEqual(payload["orderCount"], 0)
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["authorityChanged"])

    def test_renders_concrete_legs_from_plan(self) -> None:
        plan = _plan({"ticker": "CHKP", "strikePlan": _spread("CHKP", 230.0)})
        payload = wo.build_work_order(strike_plan_report=plan, evidence_loop={})
        order = payload["orders"][0]
        self.assertEqual(order["ticker"], "CHKP")
        self.assertEqual(len(order["legs"]), 2)
        self.assertIn("CHKP260821C00130000", order["legs"][0]["symbol"])
        self.assertEqual(order["legs"][0]["quantitySigned"], "+1")
        self.assertEqual(order["legs"][1]["quantitySigned"], "-1")
        text = wo.work_order_text(payload)
        self.assertIn("BUY_TO_OPEN", text)
        self.assertIn("130 CALL", text)
        self.assertIn("net debit", text)

    def test_flags_orders_over_single_ticket_cap(self) -> None:
        plan = _plan(
            {"ticker": "CHKP", "strikePlan": _spread("CHKP", 230.0)},   # within cap
            {"ticker": "WDC", "strikePlan": _spread("WDC", 11700.0)},   # way over
        )
        payload = wo.build_work_order(strike_plan_report=plan, evidence_loop={})
        by_ticker = {o["ticker"]: o for o in payload["orders"]}
        self.assertTrue(by_ticker["CHKP"]["withinSingleTicketCap"])
        self.assertFalse(by_ticker["WDC"]["withinSingleTicketCap"])
        self.assertEqual(payload["readyCount"], 1)
        self.assertEqual(payload["oversizedCount"], 1)
        # Within-cap order sorts ahead of the oversized one.
        self.assertEqual(payload["orders"][0]["ticker"], "CHKP")
        self.assertIn("NOT SIZED FOR THIS ACCOUNT", wo.work_order_text(payload))

    def test_route_now_and_cap_breach_are_both_surfaced(self) -> None:
        """The evidence loop can route a ticket that still breaches the cap."""
        plan = _plan({"ticker": "CIFR", "strikePlan": _spread("CIFR", 609.0)})
        payload = wo.build_work_order(
            strike_plan_report=plan,
            evidence_loop={"stageableTickers": ["CIFR"]},
        )
        order = payload["orders"][0]
        self.assertTrue(order["routeNow"])
        self.assertFalse(order["withinSingleTicketCap"])
        text = wo.work_order_text(payload)
        self.assertIn("ROUTE NOW", text)
        self.assertIn("OVER", text)

    def test_ready_within_cap_route_now_sorts_first(self) -> None:
        plan = _plan(
            {"ticker": "WDC", "strikePlan": _spread("WDC", 11700.0)},
            {"ticker": "CLFD", "strikePlan": _spread("CLFD", 130.0)},
            {"ticker": "CHKP", "strikePlan": _spread("CHKP", 230.0)},
        )
        payload = wo.build_work_order(
            strike_plan_report=plan,
            evidence_loop={"stageableTickers": ["CHKP"]},
        )
        # CHKP is within-cap AND route-now -> first. WDC oversized -> last.
        self.assertEqual(payload["orders"][0]["ticker"], "CHKP")
        self.assertEqual(payload["orders"][-1]["ticker"], "WDC")
        self.assertEqual(payload["verdict"], "orders-ready")

    def test_incomplete_legs_marked_not_keyable(self) -> None:
        plan = _plan({"ticker": "BAD", "strikePlan": _spread("BAD", 200.0, complete=False)})
        payload = wo.build_work_order(strike_plan_report=plan, evidence_loop={})
        order = payload["orders"][0]
        self.assertFalse(order["stageable"])
        self.assertIn("missing", order["notStageableReason"])
        self.assertEqual(payload["verdict"], "no-stageable-orders")

    def test_all_oversized_yields_orders_oversized_verdict(self) -> None:
        plan = _plan(
            {"ticker": "ANET", "strikePlan": _spread("ANET", 2660.0)},
            {"ticker": "WDC", "strikePlan": _spread("WDC", 11700.0)},
        )
        payload = wo.build_work_order(strike_plan_report=plan, evidence_loop={})
        self.assertEqual(payload["verdict"], "orders-oversized")
        self.assertEqual(payload["readyCount"], 0)

    def test_never_signals_authority_or_promotion(self) -> None:
        plan = _plan({"ticker": "CHKP", "strikePlan": _spread("CHKP", 230.0)})
        payload = wo.build_work_order(strike_plan_report=plan, evidence_loop={})
        self.assertEqual(payload["stage"], "paper-work-order-research-only")
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["authorityChanged"])
        text = wo.work_order_text(payload).lower()
        self.assertIn("stages nothing", text)
        # Never claims to have placed or staged an order.
        self.assertNotIn("order placed", text)
        self.assertNotIn("staged for you", text)

    def test_cap_is_read_from_config_not_hardcoded(self) -> None:
        plan = _plan({"ticker": "CIFR", "strikePlan": _spread("CIFR", 609.0)})
        with patch.object(wo, "MAX_SINGLE_TICKET_DOLLARS", 1000.0):
            payload = wo.build_work_order(strike_plan_report=plan, evidence_loop={})
        # At a $1000 cap, the $609 order is now within cap.
        self.assertTrue(payload["orders"][0]["withinSingleTicketCap"])
        self.assertEqual(payload["readyCount"], 1)


if __name__ == "__main__":
    unittest.main()
