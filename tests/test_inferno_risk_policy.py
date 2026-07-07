"""Contract tests for inferno_risk_policy.

Pins the gates that prevent unsafe tickets from entering paper evidence
or any execution surface. Several of these encode invariants that **must
never silently regress** while broker submit stays OFF:

  - A ticket carrying ``liveTradingAllowed=True`` is ALWAYS blocked. This
    is the broker-submit-OFF tripwire — even a non-malicious upstream
    flip of that flag should hit a block here.
  - Per-ticket loss caps at MAX_SINGLE_TICKET_DOLLARS ($500).
  - Projected daily loss caps at MAX_DAILY_TICKET_DOLLARS ($1500).
  - Duplicate ticker (same ticker already open) → block.
  - Strike plan staleness (> MAX_STRIKE_PLAN_AGE_MINUTES) → block.
  - Buy legs need a visible ask; sell legs need a visible bid.
  - Schwab "hard" quality flags (empty-chain, wide-atm-spread, etc.) → block.
  - Schwab quote-quality < 50 → block; 50-69 → warn only.
  - Debit-spread R:R below MIN_DEBIT_SPREAD_REWARD_RISK → block.
  - Credit-spread credit/risk below MIN_CREDIT_SPREAD_CREDIT_RISK → block.
  - Intent price vs Schwab underlying drift above the configured floor → block.
  - A clean ticket with all the above satisfied → passes.

These tests are *read-only* against the policy module. They do not mutate
the live ledger, authority manifest, or any artifact.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import inferno_capital_scaling as _capital_scaling

from inferno_config import (
    MAX_DAILY_TICKET_DOLLARS,
    MAX_OPEN_PAPER_TICKETS,
    MAX_SINGLE_TICKET_DOLLARS,
    MAX_STRIKE_PLAN_AGE_MINUTES,
    MAX_UNDERLYING_SOURCE_DIVERGENCE_PCT,
    MIN_CREDIT_SPREAD_CREDIT_RISK,
    MIN_DEBIT_SPREAD_REWARD_RISK,
    PAPER_DAILY_BUDGET_DOLLARS,
    PAPER_TICKET_BUDGET_DOLLARS,
    local_now,
)
from inferno_risk_policy import (
    RiskVerdict,
    credit_spread_credit_risk,
    debit_spread_reward_risk,
    evaluate_strike_item,
    max_loss_dollars,
    same_ticker_open,
    schwab_option_quality_guards,
    underlying_source_drift,
    visible_quote_blocks,
)


def _fresh_plan_timestamp() -> str:
    """Return a current-time ISO string so strike-plan staleness doesn't fire."""
    return local_now().isoformat()


def _clean_item(**overrides):
    """Return a strike item that should pass the policy when handed in alone.

    All fields chosen to be inside every cap. Overrides let each test
    flip exactly one knob and confirm only that knob fires.
    """
    base = {
        "ok": True,
        "ticker": "AAA",
        "liveTradingAllowed": False,
        "strikePlan": {
            "strategy": "CALL_DEBIT_SPREAD",
            "estimatedMaxLoss": 250.0,
            "estimatedMaxProfit": 250.0,
            "estimatedDebit": 2.5,
            "legs": [
                {
                    "instruction": "BUY_TO_OPEN",
                    "symbol": "AAA_C_100",
                    "bid": 1.95,
                    "ask": 2.05,
                },
                {
                    "instruction": "SELL_TO_OPEN",
                    "symbol": "AAA_C_105",
                    "bid": 0.45,
                    "ask": 0.55,
                },
            ],
            "liquidityNotes": [],
        },
        "marketContext": {
            "trend": {"label": "Bullish"},
            "rvol": 1.10,
            "atrExpansion": 0.20,
            "distanceToResistancePct": 4.0,
            "distanceToSupportPct": 4.0,
        },
    }
    base.update(overrides)
    return base


def _put_credit_item(**overrides):
    """Return a small defined-risk put credit spread fixture."""
    base = _clean_item(ticker="FCX")
    base["strikePlan"] = {
        "strategy": "PUT_CREDIT_SPREAD",
        "estimatedCredit": 0.35,
        "estimatedMaxLoss": 127.0,
        "estimatedMaxProfit": 35.0,
        "legs": [
            {"instruction": "SELL_TO_OPEN", "symbol": "FCX_P_38", "bid": 0.55, "ask": 0.60},
            {"instruction": "BUY_TO_OPEN", "symbol": "FCX_P_36", "bid": 0.18, "ask": 0.20},
        ],
        "liquidityNotes": [],
    }
    base["marketContext"]["distanceToSupportPct"] = 8.0
    base.update(overrides)
    return base


class RiskVerdictTests(unittest.TestCase):
    def test_as_dict_round_trips(self):
        v = RiskVerdict(passed=True, blocks=[], warnings=["w"], metrics={"k": 1})
        d = v.as_dict()
        self.assertEqual(d["passed"], True)
        self.assertEqual(d["warnings"], ["w"])
        self.assertEqual(d["metrics"]["k"], 1)


class UnderlyingSourceDriftTests(unittest.TestCase):
    def test_source_drift_measures_schwab_underlying_gap(self):
        drift = underlying_source_drift(
            {
                "sourcePrice": 100.0,
                "price": 106.0,
                "schwabOptions": {"underlyingPrice": 106.0},
            }
        )
        self.assertEqual(drift["underlyingSourceDriftPct"], 6.0)
        self.assertEqual(drift["maxUnderlyingSourceDivergencePct"], MAX_UNDERLYING_SOURCE_DIVERGENCE_PCT)


class MaxLossTests(unittest.TestCase):
    def test_explicit_max_loss_wins(self):
        self.assertEqual(
            max_loss_dollars({"strikePlan": {"estimatedMaxLoss": 425.0, "estimatedDebit": 9.0}}),
            425.0,
        )

    def test_falls_back_to_debit_times_100(self):
        self.assertEqual(
            max_loss_dollars({"strikePlan": {"estimatedDebit": 2.5}}),
            250.0,
        )

    def test_zero_loss_is_zero(self):
        self.assertEqual(
            max_loss_dollars({"strikePlan": {"estimatedMaxLoss": 0.0}}),
            0.0,
        )


class DebitSpreadRewardRiskTests(unittest.TestCase):
    def test_below_floor(self):
        item = {"strikePlan": {"estimatedDebit": 3.0, "estimatedMaxLoss": 300.0, "estimatedMaxProfit": 100.0}}
        rr = debit_spread_reward_risk(item)
        self.assertIsNotNone(rr)
        self.assertLess(rr, MIN_DEBIT_SPREAD_REWARD_RISK)

    def test_above_floor(self):
        item = {"strikePlan": {"estimatedDebit": 2.0, "estimatedMaxLoss": 200.0, "estimatedMaxProfit": 200.0}}
        rr = debit_spread_reward_risk(item)
        self.assertIsNotNone(rr)
        self.assertGreaterEqual(rr, MIN_DEBIT_SPREAD_REWARD_RISK)

    def test_missing_debit_returns_none(self):
        self.assertIsNone(debit_spread_reward_risk({"strikePlan": {}}))


class CreditSpreadCreditRiskTests(unittest.TestCase):
    def test_below_floor(self):
        item = {"strikePlan": {"estimatedCredit": 0.25, "estimatedMaxLoss": 200.0}}
        cr = credit_spread_credit_risk(item)
        self.assertIsNotNone(cr)
        self.assertLess(cr, MIN_CREDIT_SPREAD_CREDIT_RISK)

    def test_above_floor(self):
        item = {"strikePlan": {"estimatedCredit": 0.75, "estimatedMaxLoss": 250.0}}
        cr = credit_spread_credit_risk(item)
        self.assertIsNotNone(cr)
        self.assertGreaterEqual(cr, MIN_CREDIT_SPREAD_CREDIT_RISK)

    def test_missing_credit_returns_none(self):
        self.assertIsNone(credit_spread_credit_risk({"strikePlan": {}}))


class SameTickerOpenTests(unittest.TestCase):
    def test_open_ticket_is_detected(self):
        ledger = [{"ticker": "AAA", "status": "paper-staged", "outcome": {"status": "open"}}]
        self.assertTrue(same_ticker_open("AAA", ledger))

    def test_case_insensitive(self):
        ledger = [{"ticker": "aaa", "status": "paper-staged", "outcome": {"status": "open"}}]
        self.assertTrue(same_ticker_open("AAA", ledger))

    def test_closed_ticket_does_not_count(self):
        ledger = [{"ticker": "AAA", "status": "paper-staged", "outcome": {"status": "closed"}}]
        self.assertFalse(same_ticker_open("AAA", ledger))

    def test_empty_ledger(self):
        self.assertFalse(same_ticker_open("AAA", []))


class VisibleQuoteBlockTests(unittest.TestCase):
    def test_buy_leg_without_ask_blocks(self):
        blocks = visible_quote_blocks(
            {"strikePlan": {"legs": [{"instruction": "BUY_TO_OPEN", "symbol": "X", "ask": 0}]}}
        )
        self.assertTrue(any("below visible-market floor" in b for b in blocks))

    def test_sell_leg_without_bid_blocks(self):
        blocks = visible_quote_blocks(
            {"strikePlan": {"legs": [{"instruction": "SELL_TO_OPEN", "symbol": "X", "bid": 0}]}}
        )
        self.assertTrue(any("below visible-market floor" in b for b in blocks))

    def test_sell_leg_with_nickel_bid_blocks(self):
        """Phase A investigation case: bid=$0.05 is not a real market."""
        blocks = visible_quote_blocks(
            {"strikePlan": {"legs": [{"instruction": "SELL_TO_OPEN", "symbol": "THR_C_75", "bid": 0.05, "ask": 2.60}]}}
        )
        self.assertTrue(any("below visible-market floor" in b for b in blocks))

    def test_sell_leg_with_dime_bid_passes(self):
        """Bid exactly at the floor ($0.10) passes — the floor is strict."""
        blocks = visible_quote_blocks(
            {"strikePlan": {"legs": [{"instruction": "SELL_TO_OPEN", "symbol": "X", "bid": 0.10, "ask": 0.20}]}}
        )
        self.assertEqual(blocks, [])

    def test_buy_leg_with_nickel_ask_blocks(self):
        blocks = visible_quote_blocks(
            {"strikePlan": {"legs": [{"instruction": "BUY_TO_OPEN", "symbol": "X", "ask": 0.08}]}}
        )
        self.assertTrue(any("below visible-market floor" in b for b in blocks))

    def test_clean_legs_no_blocks(self):
        blocks = visible_quote_blocks(
            {
                "strikePlan": {
                    "legs": [
                        {"instruction": "BUY_TO_OPEN", "symbol": "X", "ask": 1.0},
                        {"instruction": "SELL_TO_OPEN", "symbol": "Y", "bid": 0.5},
                    ]
                }
            }
        )
        self.assertEqual(blocks, [])


class SchwabOptionQualityTests(unittest.TestCase):
    def test_no_attachment_silent(self):
        b, w, m = schwab_option_quality_guards({})
        self.assertEqual(b, [])
        self.assertEqual(w, [])
        self.assertFalse(m["attached"])

    def test_hard_flag_blocks(self):
        b, w, _ = schwab_option_quality_guards(
            {"schwabOptions": {"qualityFlags": ["empty-chain"], "quoteQualityScore": 80}}
        )
        self.assertTrue(any("empty-chain" in s for s in b))

    def test_wide_atm_spread_blocks(self):
        b, w, _ = schwab_option_quality_guards(
            {
                "schwabOptions": {
                    "qualityFlags": [],
                    "quoteQualityScore": 80,
                    "atmSpreadQuality": "wide",
                }
            }
        )
        self.assertTrue(any("wide" in s for s in b))

    def test_low_score_blocks(self):
        b, w, _ = schwab_option_quality_guards(
            {"schwabOptions": {"qualityFlags": [], "quoteQualityScore": 40, "quoteQualityLabel": "poor"}}
        )
        self.assertTrue(any("below paper threshold" in s for s in b))

    def test_mid_score_warns_only(self):
        b, w, _ = schwab_option_quality_guards(
            {"schwabOptions": {"qualityFlags": [], "quoteQualityScore": 60, "quoteQualityLabel": "fragile"}}
        )
        self.assertEqual(b, [])
        self.assertTrue(any("fragile" in s for s in w))

    def test_thin_atm_liquidity_blocks(self):
        b, w, _ = schwab_option_quality_guards(
            {
                "schwabOptions": {
                    "qualityFlags": [],
                    "quoteQualityScore": 75,
                    "atmSpreadQuality": "tight",
                    "atmLiquidityScore": 40,
                }
            }
        )
        self.assertTrue(any("too thin" in s for s in b))

    def test_explicit_paper_spread_oi_gate_lifts_legacy_liquidity_score_to_warning(self):
        b, w, metrics = schwab_option_quality_guards(
            {
                "schwabOptions": {
                    "qualityFlags": [],
                    "quoteQualityScore": 45,
                    "quoteQualityLabel": "poor",
                    "atmSpreadQuality": "workable",
                    "atmLiquidityScore": 40,
                    "atmWindowMedianSpreadPct": 0.18,
                    "atmWindowOpenInterest": 500,
                    "paperLiquidityPass": True,
                    "paperLiquidityBlockReason": None,
                    "liveLiquidityPass": False,
                    "liveLiquidityBlockReason": "atm-window-spread 18.00% exceeds gate 12%",
                    "paperFillFrictionPct": 0.18,
                }
            }
        )

        self.assertEqual(b, [])
        self.assertTrue(any("spread/OI paper gate passed" in s for s in w))
        self.assertTrue(any("secondary to spread/OI gate" in s for s in w))
        self.assertTrue(metrics["paperLiquidityPass"])
        self.assertEqual(metrics["paperFillFrictionPct"], 0.18)

    def test_explicit_paper_gate_blocks_hard_wide_even_with_high_legacy_score(self):
        b, _, metrics = schwab_option_quality_guards(
            {
                "schwabOptions": {
                    "qualityFlags": ["thin-atm-liquidity"],
                    "quoteQualityScore": 90,
                    "quoteQualityLabel": "institutional",
                    "atmSpreadQuality": "wide",
                    "atmLiquidityScore": 100,
                    "atmWindowMedianSpreadPct": 0.30,
                    "atmWindowOpenInterest": 10000,
                    "paperLiquidityPass": False,
                    "paperLiquidityBlockReason": "atm-window-spread 30.00% exceeds hard-wide ceiling 25%",
                    "liveLiquidityPass": False,
                    "liveLiquidityBlockReason": "atm-window-spread 30.00% exceeds hard-wide ceiling 25%",
                }
            }
        )

        self.assertFalse(metrics["paperLiquidityPass"])
        self.assertTrue(any("paper liquidity gate failed" in s for s in b))
        self.assertTrue(any("ATM spread is wide" in s for s in b))

    def test_stale_schwab_chain_blocks(self):
        b, _, metrics = schwab_option_quality_guards(
            {
                "schwabOptions": {
                    "qualityFlags": [],
                    "quoteQualityScore": 80,
                    "atmSpreadQuality": "tight",
                    "atmLiquidityScore": 80,
                    "sourceStatus": "ok",
                    "sourceGeneratedAt": "2000-01-01T00:00:00+00:00",
                }
            }
        )
        self.assertTrue(any("chain is stale" in value for value in b))
        self.assertGreater(metrics["sourceAgeHours"], metrics["maxSourceAgeHours"])


class EvaluateStrikeItemTests(unittest.TestCase):
    """Top-level policy evaluation tests.

    These tests need the capital-scaling state file isolated to a tmp dir,
    because the drawdown stepper reads the live state and would otherwise
    shrink the effective cap based on whatever NLV state is on disk.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._state_patch = patch.object(
            _capital_scaling,
            "CAPITAL_SCALING_STATE_FILE",
            tmp / "scaling_state.json",
        )
        self._ack_patch = patch.object(
            _capital_scaling,
            "CAPITAL_SCALING_ACK_FILE",
            tmp / "scaling_ack.json",
        )
        self._sync_patch = patch.object(
            _capital_scaling,
            "LIVE_ACCOUNT_SYNC_FILE",
            tmp / "missing_sync.json",
        )
        self._state_patch.start()
        self._ack_patch.start()
        self._sync_patch.start()

    def tearDown(self):
        self._state_patch.stop()
        self._ack_patch.stop()
        self._sync_patch.stop()
        self._tmp.cleanup()

    def test_clean_ticket_passes(self):
        v = evaluate_strike_item(
            _clean_item(),
            strike_plan_generated_at=_fresh_plan_timestamp(),
            ledger_items=[],
        )
        self.assertTrue(v.passed, f"clean ticket should pass, got blocks={v.blocks}")

    def test_live_trading_flag_always_blocks(self):
        """BROKER-SUBMIT-OFF TRIPWIRE.

        If anything upstream flips this flag to True on its way through the
        risk policy, this test fires. It must keep failing forever as long as
        broker submit is off.
        """
        v = evaluate_strike_item(
            _clean_item(liveTradingAllowed=True),
            strike_plan_generated_at=_fresh_plan_timestamp(),
            ledger_items=[],
        )
        self.assertFalse(v.passed)
        self.assertTrue(any("liveTradingAllowed" in b for b in v.blocks))

    def test_paper_mode_live_trading_flag_still_blocks(self):
        v = evaluate_strike_item(
            _clean_item(liveTradingAllowed=True),
            strike_plan_generated_at=_fresh_plan_timestamp(),
            ledger_items=[],
            mode="paper",
        )
        self.assertFalse(v.passed)
        self.assertTrue(any("liveTradingAllowed" in b for b in v.blocks))

    def test_oversize_ticket_blocks(self):
        item = _clean_item()
        item["strikePlan"]["estimatedMaxLoss"] = MAX_SINGLE_TICKET_DOLLARS + 1.0
        v = evaluate_strike_item(item, strike_plan_generated_at=_fresh_plan_timestamp())
        self.assertFalse(v.passed)
        self.assertTrue(any("single-ticket cap" in b for b in v.blocks))

    def test_paper_mode_ignores_live_drawdown_pause_cap(self):
        drawdown_paused_cap = {
            "effectiveCap": 0.0,
            "source": "ack",
            "recommendedCap": 25.0,
            "ackedCap": 250.0,
            "verdict": "config-cap-too-high",
            "shouldUseRecommendation": True,
            "drawdownLevel": "pause",
            "drawdownCapMultiplier": 0.0,
            "newEntriesAllowed": False,
        }
        with patch("inferno_risk_policy.current_single_ticket_cap", return_value=drawdown_paused_cap):
            v = evaluate_strike_item(
                _put_credit_item(),
                strike_plan_generated_at=_fresh_plan_timestamp(),
                ledger_items=[],
                mode="paper",
            )
        self.assertFalse(any("single-ticket cap" in b for b in v.blocks), v.blocks)
        self.assertEqual(v.metrics["riskMode"], "paper")
        self.assertEqual(v.metrics["effectiveSingleTicketCap"], PAPER_TICKET_BUDGET_DOLLARS)
        self.assertEqual(v.metrics["effectiveSingleTicketCapSource"], "paper-budget")

    def test_live_mode_preserves_drawdown_pause_cap_block(self):
        drawdown_paused_cap = {
            "effectiveCap": 0.0,
            "source": "ack",
            "recommendedCap": 25.0,
            "ackedCap": 250.0,
            "verdict": "config-cap-too-high",
            "shouldUseRecommendation": True,
            "drawdownLevel": "pause",
            "drawdownCapMultiplier": 0.0,
            "newEntriesAllowed": False,
        }
        with patch("inferno_risk_policy.current_single_ticket_cap", return_value=drawdown_paused_cap):
            v = evaluate_strike_item(
                _put_credit_item(),
                strike_plan_generated_at=_fresh_plan_timestamp(),
                ledger_items=[],
                mode="live",
            )
        self.assertFalse(v.passed)
        self.assertTrue(
            any("single-ticket cap $0.00" in b and "drawdown pause" in b for b in v.blocks),
            v.blocks,
        )

    def test_paper_mode_blocks_above_paper_budget(self):
        item = _clean_item()
        item["strikePlan"]["estimatedMaxLoss"] = PAPER_TICKET_BUDGET_DOLLARS + 100.0
        item["strikePlan"]["estimatedMaxProfit"] = PAPER_TICKET_BUDGET_DOLLARS + 100.0
        v = evaluate_strike_item(
            item,
            strike_plan_generated_at=_fresh_plan_timestamp(),
            ledger_items=[],
            mode="paper",
        )
        self.assertFalse(v.passed)
        self.assertTrue(
            any(f"single-ticket cap ${PAPER_TICKET_BUDGET_DOLLARS:.2f} (paper-budget)" in b for b in v.blocks),
            v.blocks,
        )

    def test_paper_mode_preserves_paper_hygiene_guards(self):
        ledger = [
            {
                "ticker": "AAA" if i == 0 else f"T{i}",
                "status": "paper-staged",
                "outcome": {"status": "open"},
                "estimatedMaxLoss": 50.0,
            }
            for i in range(MAX_OPEN_PAPER_TICKETS)
        ]
        v = evaluate_strike_item(
            _clean_item(),
            strike_plan_generated_at=_fresh_plan_timestamp(),
            ledger_items=ledger,
            mode="paper",
        )
        self.assertFalse(v.passed)
        self.assertTrue(any("already has an open paper ticket" in b for b in v.blocks), v.blocks)
        self.assertTrue(any("open paper ticket cap" in b for b in v.blocks), v.blocks)

    def test_daily_cap_blocks(self):
        # Five existing open tickets at $300 + today's $250 = $1750 > $1500.
        # Use a different ticker so the duplicate-ticker rule doesn't fire.
        today = local_now().date().isoformat()
        ledger = [
            {
                "ticker": f"T{i}",
                "status": "paper-staged",
                "tradeDate": today,
                "estimatedMaxLoss": 300.0,
                "outcome": {"status": "open"},
            }
            for i in range(5)
        ]
        v = evaluate_strike_item(
            _clean_item(),
            strike_plan_generated_at=_fresh_plan_timestamp(),
            ledger_items=ledger,
        )
        self.assertFalse(v.passed)
        # Daily cap OR open ticket cap (5) fires; either is acceptable
        self.assertTrue(
            any("daily max loss" in b or "open paper ticket cap" in b for b in v.blocks),
            f"expected daily-cap or open-cap block, got {v.blocks}",
        )

    def test_open_ticket_cap_blocks(self):
        ledger = [
            {
                "ticker": f"T{i}",
                "status": "paper-staged",
                "outcome": {"status": "open"},
                "estimatedMaxLoss": 50.0,
            }
            for i in range(MAX_OPEN_PAPER_TICKETS)
        ]
        v = evaluate_strike_item(
            _clean_item(),
            strike_plan_generated_at=_fresh_plan_timestamp(),
            ledger_items=ledger,
        )
        self.assertFalse(v.passed)
        self.assertTrue(any("open paper ticket cap" in b for b in v.blocks))

    def test_duplicate_ticker_blocks(self):
        ledger = [
            {"ticker": "AAA", "status": "paper-staged", "outcome": {"status": "open"}}
        ]
        v = evaluate_strike_item(
            _clean_item(),
            strike_plan_generated_at=_fresh_plan_timestamp(),
            ledger_items=ledger,
        )
        self.assertFalse(v.passed)
        self.assertTrue(any("already has an open paper ticket" in b for b in v.blocks))

    def test_stale_strike_plan_blocks(self):
        from datetime import timedelta
        old = (local_now() - timedelta(minutes=MAX_STRIKE_PLAN_AGE_MINUTES + 5)).isoformat()
        v = evaluate_strike_item(
            _clean_item(),
            strike_plan_generated_at=old,
            ledger_items=[],
        )
        self.assertFalse(v.passed)
        self.assertTrue(any("stale" in b for b in v.blocks))

    def test_failed_strike_plan_blocks(self):
        v = evaluate_strike_item(
            _clean_item(ok=False, reason="no expirable contracts"),
            strike_plan_generated_at=_fresh_plan_timestamp(),
        )
        self.assertFalse(v.passed)
        self.assertTrue(any("no expirable contracts" in b for b in v.blocks))

    def test_low_reward_risk_blocks(self):
        item = _clean_item()
        item["strikePlan"]["estimatedMaxProfit"] = 50.0  # 50 / 250 = 0.20
        v = evaluate_strike_item(
            item,
            strike_plan_generated_at=_fresh_plan_timestamp(),
            ledger_items=[],
        )
        self.assertFalse(v.passed)
        self.assertTrue(any("reward/risk" in b for b in v.blocks))

    def test_low_credit_risk_blocks(self):
        item = _clean_item()
        item["strikePlan"] = {
            "strategy": "PUT_CREDIT_SPREAD",
            "estimatedCredit": 0.20,
            "estimatedMaxLoss": 300.0,
            "estimatedMaxProfit": 20.0,
            "legs": [
                {"instruction": "SELL_TO_OPEN", "symbol": "AAA_P_95", "bid": 0.70, "ask": 0.80},
                {"instruction": "BUY_TO_OPEN", "symbol": "AAA_P_90", "bid": 0.45, "ask": 0.50},
            ],
            "liquidityNotes": [],
        }
        item["marketContext"]["distanceToSupportPct"] = 8.0
        v = evaluate_strike_item(
            item,
            strike_plan_generated_at=_fresh_plan_timestamp(),
            ledger_items=[],
        )
        self.assertFalse(v.passed)
        self.assertTrue(any("credit/risk" in b for b in v.blocks))

    def test_schwab_underlying_drift_blocks_stale_context(self):
        item = _clean_item(
            sourcePrice=100.0,
            price=106.0,
            schwabOptions={
                "underlyingPrice": 106.0,
                "qualityFlags": [],
                "quoteQualityScore": 90,
                "quoteQualityLabel": "institutional",
                "atmSpreadQuality": "tight",
                "atmLiquidityScore": 90,
            },
        )
        v = evaluate_strike_item(
            item,
            strike_plan_generated_at=_fresh_plan_timestamp(),
            ledger_items=[],
        )
        self.assertFalse(v.passed)
        self.assertTrue(any("diverges from Schwab underlying" in b for b in v.blocks))
        self.assertEqual(v.metrics["underlyingSourceDriftPct"], 6.0)

    def test_schwab_quality_attachment_blocks(self):
        item = _clean_item()
        item["schwabOptions"] = {
            "qualityFlags": ["wide-atm-spread"],
            "quoteQualityScore": 40,
            "quoteQualityLabel": "poor",
        }
        v = evaluate_strike_item(
            item,
            strike_plan_generated_at=_fresh_plan_timestamp(),
            ledger_items=[],
        )
        self.assertFalse(v.passed)
        # at least one Schwab-quality block should fire
        self.assertTrue(any("Schwab" in b for b in v.blocks))

    def test_no_legs_blocks(self):
        item = _clean_item()
        item["strikePlan"]["legs"] = []
        v = evaluate_strike_item(
            item,
            strike_plan_generated_at=_fresh_plan_timestamp(),
        )
        self.assertFalse(v.passed)
        self.assertTrue(any("no option legs" in b for b in v.blocks))

    def test_metrics_carry_caps(self):
        """The verdict's metrics dict must surface the caps for audit."""
        v = evaluate_strike_item(
            _clean_item(),
            strike_plan_generated_at=_fresh_plan_timestamp(),
            ledger_items=[],
        )
        self.assertEqual(v.metrics["maxSingleTicketDollars"], MAX_SINGLE_TICKET_DOLLARS)
        self.assertEqual(v.metrics["maxDailyTicketDollars"], MAX_DAILY_TICKET_DOLLARS)
        self.assertEqual(v.metrics["paperTicketBudgetDollars"], PAPER_TICKET_BUDGET_DOLLARS)
        self.assertEqual(v.metrics["paperDailyBudgetDollars"], PAPER_DAILY_BUDGET_DOLLARS)
        self.assertEqual(v.metrics["maxOpenPaperTickets"], MAX_OPEN_PAPER_TICKETS)
        self.assertEqual(v.metrics["minDebitSpreadRewardRisk"], MIN_DEBIT_SPREAD_REWARD_RISK)
        self.assertEqual(v.metrics["minCreditSpreadCreditRisk"], MIN_CREDIT_SPREAD_CREDIT_RISK)
        self.assertEqual(v.metrics["maxUnderlyingSourceDivergencePct"], MAX_UNDERLYING_SOURCE_DIVERGENCE_PCT)


if __name__ == "__main__":
    unittest.main()
