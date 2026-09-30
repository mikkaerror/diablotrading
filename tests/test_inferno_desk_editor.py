from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from inferno_desk_editor import (
    DESK_EDITOR_STAGE,
    build_desk_editor,
    desk_editor_text,
    long_term_section,
)

NOW = datetime(2026, 9, 28, 7, 20, tzinfo=timezone.utc)
FRESH = "2026-09-28T06:00:00+00:00"
OLD = "2026-09-20T06:00:00+00:00"


def _write(folder: Path, name: str, payload: dict) -> None:
    (folder / name).write_text(json.dumps(payload), encoding="utf-8")


class DeskEditorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data = root / "data"
        self.reports = root / "reports"
        self.data.mkdir()
        self.reports.mkdir()
        _write(self.data, "inferno_live_account_sync.json",
               {"generatedAt": FRESH, "netLiquidatingValue": 900.0, "totalCash": 250.0})
        _write(self.data, "inferno_capital_scaling_state.json", {"peakNlv": 3600.0})
        _write(self.data, "inferno_capital_scaling.json",
               {"drawdownState": {"level": "pause", "newEntriesAllowed": False}})
        _write(self.data, "inferno_approval_queue.json", {
            "generatedAt": FRESH,
            "items": [
                {"ticker": "ACN", "approvalStatus": "pending", "daysUntilEarnings": 4, "readiness": 90,
                 "replyApprove": "APPROVE ACN T1", "replyDeny": "DENY ACN T1"},
                {"ticker": "OLD", "approvalStatus": "approved"},
            ],
        })
        _write(self.data, "inferno_strike_plan.json", {
            "generatedAt": FRESH,
            "items": [{
                "ticker": "ACN", "ok": True,
                "strikePlan": {"strategy": "LONG_STRADDLE", "expiration": "2026-10-02", "estimatedMaxLoss": 1510},
                "riskVerdict": {"blocks": ["max loss $1510.00 exceeds single-ticket cap $500.00",
                                           "human approval missing"],
                                "metrics": {"maxLossDollars": 1510.0}},
            }],
        })
        _write(self.data, "inferno_shadow_evidence.json", {
            "generatedAt": OLD, "updatedAt": FRESH,
            "strategies": [{"strategy": "LONG_STRADDLE", "closedCount": 4, "winRate": 0.25, "avgReturnOnRisk": -0.2}],
            "items": [
                {"ticker": "ACN", "strategy": "LONG_STRADDLE", "outcome": {"status": "closed", "estimatedReturnOnRisk": 0.5}},
                {"ticker": "ACN", "strategy": "LONG_STRADDLE", "outcome": {"status": "closed", "estimatedReturnOnRisk": -0.3}},
                {"ticker": "ACN", "strategy": "LONG_STRADDLE", "outcome": {"status": "open"}},
                {"ticker": "ZZZ", "strategy": "LONG_STRADDLE", "outcome": {"status": "closed", "estimatedReturnOnRisk": 1.0}},
            ],
        })
        _write(self.data, "inferno_action_pulse.json", {"generatedAt": OLD})
        _write(self.data, "inferno_performance_analytics.json", {"closedMetrics": {"scoredCount": 3}})
        _write(self.data, "inferno_live_position_review.json", {"positions": [
            {"symbol": "TE", "markValue": 151.2, "plPercent": -54.5},
            {"symbol": "CLSK", "markValue": 137.6, "plPercent": -14.6},
        ]})
        _write(self.data, "inferno_trade_management.json", {"openPositionCount": 1, "assessments": [
            {"ticker": "PL", "verdict": "stop-loss", "reason": "down 60%"},
            {"ticker": "HPE", "verdict": "hold"},
        ]})
        (self.reports / "long_term_buys_latest.txt").write_text(
            "Long-Term Accumulation Lane\n\n"
            "1. DBX | Accumulate | score 9.99 | value stack is still doing real work; not extended\n"
            "2. GNRC | Accumulate | score 9.5 | compressed\n", encoding="utf-8")
        self.payload = build_desk_editor(self.data, self.reports, now=NOW)

    def tearDown(self):
        self.tmp.cleanup()

    def test_contract_flags(self):
        p = self.payload
        self.assertEqual(p["stage"], DESK_EDITOR_STAGE)
        self.assertTrue(p["researchOnly"])
        self.assertFalse(p["promotable"])
        self.assertFalse(p["authorityChanged"])
        self.assertFalse(p["liveTradingAllowed"])
        self.assertFalse(p["brokerSubmitAllowed"])
        self.assertTrue(p["citations"])

    def test_money_and_drawdown(self):
        money = self.payload["money"]
        self.assertEqual(money["fromPeakPct"], -75.0)
        self.assertTrue(money["fresh"])
        self.assertFalse(money["newLiveEntriesAllowed"])
        self.assertIn("no new LIVE entries", desk_editor_text(self.payload))

    def test_only_pending_decisions_with_evidence(self):
        decisions = self.payload["decisions"]
        self.assertEqual([d["ticker"] for d in decisions], ["ACN"])
        acn = decisions[0]
        self.assertEqual(acn["maxLoss"], 1510.0)
        self.assertEqual(acn["riskBlocks"], ["over single-ticket cap"])
        self.assertFalse(acn["paperRiskPassed"])
        self.assertEqual(acn["tickerShadow"], {"closed": 2, "wins": 1, "avgR": 0.1})
        self.assertEqual(acn["strategyShadow"]["closed"], 4)
        self.assertIn("reply to the ACN [Inferno Approval] email", desk_editor_text(self.payload))
        self.assertNotIn("APPROVE ACN T1", desk_editor_text(self.payload))

    def test_positions_loss_rule_and_paper_actions(self):
        positions = self.payload["positions"]
        flags = {h["symbol"]: h["lossRule"] for h in positions["live"]}
        self.assertEqual(flags, {"TE": True, "CLSK": False})
        self.assertEqual([a["ticker"] for a in positions["paperActions"]], ["PL"])
        self.assertIn("never add", desk_editor_text(self.payload))

    def test_empty_sync_falls_back_to_nlv_history_and_flags_reauth(self):
        _write(self.data, "inferno_live_account_sync.json", {
            "generatedAt": FRESH, "ok": False, "netLiquidatingValue": None,
            "schwabAccountVerdict": "reauthorization-required",
        })
        (self.data / "nlv_history.csv").write_text(
            "timestamp,date,nlv,cash\n2026-09-27T00:31:33+00:00,2026-09-26,845.85,249.33\n", encoding="utf-8")
        payload = build_desk_editor(self.data, self.reports, NOW)
        self.assertEqual(payload["money"]["nlv"], 845.85)
        self.assertEqual(payload["money"]["source"], "nlv history")
        self.assertTrue(any("Schwab login expired" in a for a in payload["alerts"]))

    def test_short_premium_forward_line(self):
        _write(self.data, "inferno_short_premium_shadow.json", {"summary": {
            "verdict": "forward-awaiting-short-premium-records", "distinctEvents": 0, "distinctNames": 0,
            "openEvents": 1, "meanNetR": None, "meanEntryFrictionDollars": 472.5, "timeboxEnd": "2027-02-28"}})
        payload = build_desk_editor(self.data, self.reports, NOW)
        text = desk_editor_text(payload)
        self.assertIn("short-premium forward (iron fly shadow): 0/60 events, 0/40 names, 1 open", text)
        self.assertIn("entry friction $472/fly", text)

    def test_alerts_use_latest_write_time(self):
        alerts = self.payload["alerts"]
        self.assertTrue(any(a.startswith("action pulse: stale") for a in alerts))
        self.assertFalse(any(a.startswith("shadow evidence") for a in alerts))

    def test_headline(self):
        self.assertEqual(
            self.payload["headline"],
            "1 decision today | 1 paper position(s) need action | 1 holding(s) past the -20% rule | data needs a refresh",
        )

    def test_delegated_section(self):
        _write(self.data, "inferno_paper_delegate.json", {
            "generatedAt": FRESH,
            "decisions": [{"ticker": "ACN", "reason": "priced, fresh"}],
            "applied": [{"ticker": "ACN", "status": "approved", "rule": "clean-paper"}],
        })
        payload = build_desk_editor(self.data, self.reports, now=NOW)
        self.assertEqual(payload["delegated"][0]["status"], "approved")
        self.assertIn("1 paper call made for you (1 approved)", payload["headline"])
        self.assertIn("PAPER DECISIONS CLAUDE MADE", desk_editor_text(payload))
        _write(self.data, "inferno_paper_delegate.json", {"generatedAt": OLD, "applied": [{"ticker": "X"}]})
        self.assertEqual(build_desk_editor(self.data, self.reports, now=NOW)["delegated"], [])

    def test_performance_line(self):
        _write(self.data, "inferno_account_performance.json", {
            "verdict": "measured", "twrSinceStart": -0.267, "twrDrawdownCurrent": -0.294,
            "window": ["2026-06-17", "2026-09-25"],
            "benchmark": {"return": 0.041, "accountTwrSameWindow": -0.267},
            "peakIntegrity": {"supported": False}})
        text = desk_editor_text(build_desk_editor(self.data, self.reports, now=NOW))
        self.assertIn("Flow-adjusted return since 2026-06-17: -26.7% vs SPY +4.1%", text)
        self.assertIn("stored peak is not supported", text)

    def test_capex_flow_section(self):
        _write(self.data, "inferno_capex_flow.json", {
            "regime": {"regime": "accelerating-stretched", "growth": 0.79, "fcfPositive": 1, "spenders": 4, "tapeStale": False},
            "names": [{"ticker": "CRDO", "layer": "networking-optics", "action": "BUY", "instrument": "shares (core)"},
                      {"ticker": "X", "layer": "l", "action": "AVOID", "instrument": "none"}]})
        text = desk_editor_text(build_desk_editor(self.data, self.reports, now=NOW))
        self.assertIn("Tap: accelerating-stretched (spender capex +79% guided; FCF-positive 1/4)", text)
        self.assertIn("- CRDO [networking-optics]: shares (core)", text)
        self.assertNotIn("- X [", text)

    def test_long_term_parse(self):
        rows = long_term_section(self.reports)
        self.assertEqual([r["ticker"] for r in rows], ["DBX", "GNRC"])
        self.assertEqual(rows[0]["why"], "value stack is still doing real work")

    def test_empty_desk_is_quiet(self):
        with tempfile.TemporaryDirectory() as empty:
            payload = build_desk_editor(Path(empty), Path(empty), now=NOW)
        text = desk_editor_text(payload)
        self.assertIn("Nothing waiting on you.", text)
        self.assertEqual(payload["decisions"], [])
        self.assertIn("broker account: missing", payload["alerts"])

    def test_text_is_one_screen(self):
        self.assertLess(len(desk_editor_text(self.payload).splitlines()), 45)


if __name__ == "__main__":
    unittest.main()
