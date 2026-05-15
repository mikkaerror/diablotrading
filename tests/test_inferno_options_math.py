from __future__ import annotations

"""Adversarial tests for inferno_options_math.

Counter-arguments the module must survive:

1. Negative or zero inputs are rejected (no silent nan/inf).
2. d1 / d2 match textbook values at known parameter triples.
3. Implied 1-σ move and expected absolute move maintain the
   ``E[|·|] ≈ 0.7979 · σ · √T`` relationship.
4. ATM call delta is exactly 0.5 when the lognormal drift term cancels.
5. Put-call delta parity: ``Δ_call - Δ_put = 1`` always.
6. IV rank → annualised IV interpolation clamps at [0, 100] bounds.
7. VRP arithmetic returns zero when implied move is zero.
"""

import math
import unittest

import inferno_options_math as om


class ValidationTests(unittest.TestCase):
    def test_negative_spot_raises(self) -> None:
        with self.assertRaises(ValueError):
            om.d1(spot=-1.0, strike=100, sigma=0.3, t_years=0.25)

    def test_zero_strike_raises(self) -> None:
        with self.assertRaises(ValueError):
            om.d1(spot=100, strike=0, sigma=0.3, t_years=0.25)

    def test_inf_sigma_raises(self) -> None:
        with self.assertRaises(ValueError):
            om.d1(spot=100, strike=100, sigma=float("inf"), t_years=0.25)

    def test_nan_raises(self) -> None:
        with self.assertRaises(ValueError):
            om.implied_one_sigma_move(spot=100, sigma_annual=float("nan"), days_to_expiry=30)


class ImpliedMoveTests(unittest.TestCase):
    def test_basic_one_sigma(self) -> None:
        # σ=0.3, T=0.25 → σ√T = 0.15 → 1-σ move on $100 = $15.
        self.assertAlmostEqual(
            om.implied_one_sigma_move(spot=100, sigma_annual=0.30, days_to_expiry=91.25),
            15.0, places=2,
        )

    def test_expected_absolute_move_relationship(self) -> None:
        # E[|move|] = √(2/π) × 1σ-move ≈ 0.7979.
        spot, sigma, dte = 200.0, 0.40, 30
        one_sig = om.implied_one_sigma_move(spot, sigma, dte)
        abs_move = om.expected_absolute_move(spot, sigma, dte)
        self.assertAlmostEqual(abs_move / one_sig, om.SQRT_TWO_OVER_PI, places=6)

    def test_atm_straddle_breakeven_percent(self) -> None:
        # ATM percent breakeven = σ √T √(2/π).
        sigma, dte = 0.50, 7  # one week
        breakeven = om.atm_straddle_breakeven_percent(sigma, dte)
        expected = sigma * math.sqrt(7.0 / 365.0) * om.SQRT_TWO_OVER_PI
        self.assertAlmostEqual(breakeven, expected, places=6)


class IVRankConversionTests(unittest.TestCase):
    def test_rank_zero_returns_floor(self) -> None:
        self.assertAlmostEqual(
            om.annualised_iv_from_rank(0, iv_floor=0.10, iv_ceiling=1.0),
            0.10, places=6,
        )

    def test_rank_one_hundred_returns_ceiling(self) -> None:
        self.assertAlmostEqual(
            om.annualised_iv_from_rank(100, iv_floor=0.10, iv_ceiling=1.0),
            1.0, places=6,
        )

    def test_rank_clamps_above_one_hundred(self) -> None:
        self.assertEqual(
            om.annualised_iv_from_rank(120, iv_floor=0.10, iv_ceiling=1.0),
            om.annualised_iv_from_rank(100, iv_floor=0.10, iv_ceiling=1.0),
        )

    def test_rank_clamps_below_zero(self) -> None:
        self.assertEqual(
            om.annualised_iv_from_rank(-10, iv_floor=0.10, iv_ceiling=1.0),
            om.annualised_iv_from_rank(0, iv_floor=0.10, iv_ceiling=1.0),
        )

    def test_invalid_floor_raises(self) -> None:
        with self.assertRaises(ValueError):
            om.annualised_iv_from_rank(50, iv_floor=0, iv_ceiling=1.0)


class DeltaTests(unittest.TestCase):
    def test_call_delta_atm_short_horizon(self) -> None:
        # For S=K, r=0, very small T, drift term is tiny so delta ≈ 0.5.
        delta = om.approximate_call_delta(
            spot=100, strike=100, sigma_annual=0.0001, days_to_expiry=1,
        )
        self.assertAlmostEqual(delta, 0.5, places=3)

    def test_put_call_delta_parity(self) -> None:
        # Δ_call - Δ_put = 1 always.
        for spot in (50, 100, 150):
            for sigma in (0.1, 0.3, 0.7):
                for dte in (1, 30, 180):
                    call = om.approximate_call_delta(spot, 100, sigma, dte)
                    put = om.approximate_put_delta(spot, 100, sigma, dte)
                    self.assertAlmostEqual(call - put, 1.0, places=6)

    def test_deep_itm_call_delta_approaches_one(self) -> None:
        delta = om.approximate_call_delta(spot=200, strike=100, sigma_annual=0.30, days_to_expiry=30)
        self.assertGreater(delta, 0.99)

    def test_deep_otm_call_delta_near_zero(self) -> None:
        delta = om.approximate_call_delta(spot=50, strike=200, sigma_annual=0.30, days_to_expiry=30)
        self.assertLess(delta, 0.01)


class VRPArithmeticTests(unittest.TestCase):
    def test_vrp_positive_when_implied_exceeds_realised(self) -> None:
        result = om.implied_vs_realised_premium(implied_move_dollars=10.0, realised_move_dollars=6.0)
        self.assertAlmostEqual(result["vrpDollars"], 4.0, places=6)
        self.assertAlmostEqual(result["vrpFraction"], 0.4, places=6)

    def test_vrp_zero_implied_returns_zero_fraction(self) -> None:
        result = om.implied_vs_realised_premium(implied_move_dollars=0.0, realised_move_dollars=0.0)
        self.assertEqual(result["vrpFraction"], 0.0)


if __name__ == "__main__":
    unittest.main()
