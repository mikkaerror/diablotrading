from __future__ import annotations

"""Inferno Options Math — Black-Scholes primitives used across the desk.

What it does:
    Pure mathematical functions for the options surface — d1 / d2, implied
    1-σ move, short-horizon expected absolute move approximation, ATM straddle parity,
    annualised IV from IV rank. No I/O, no disk writes, no module state.

What it does NOT do:
    - Anything live. Anything that touches a broker. Anything that writes.

Strict contract: pure functions. Every caller passes its own inputs; no
ambient state is read. Tests do not need fixtures because the functions
are deterministic for any input tuple.

## The math

Standard Black-Scholes (1973) with risk-free rate ``r`` (defaults to 0
since the desk operates on short horizons where the risk-free term is
negligible compared to vol):

```
d1 = ( ln(S / K) + (r + σ²/2) · T ) / ( σ · √T )
d2 = d1 - σ · √T
```

Implied 1-σ move at the money (S=K, r=0):

```
move_1σ = S · σ · √T
```

Short-horizon expected absolute move approximation at the money:

```
E[|S_T - S_0|] ≈ S · σ · √T · √(2/π)
                ≈ 0.7979 · S · σ · √T
```

ATM straddle parity — the price of an at-the-money straddle (call + put)
is approximately ``2 · S · σ · √T · φ(0)`` where ``φ`` is the standard
normal density:

```
P_straddle_ATM ≈ S · σ · √T · √(2/π)
```

…which is the same as the small-move expected absolute move approximation.
This is the canonical "breakeven move" the options market is pricing in.

## Why we ship this as a module

Multiple modules need the same primitives: the vol-premium discriminator
wants to compare *implied* vs *realised* moves, the strike selector wants
expected dollar ranges, the morning brief wants the implied move
alongside the IV rank. Centralising the math here means we have one
audited source and one place to test it.

References:
    Black & Scholes (1973), *The Pricing of Options and Corporate
    Liabilities*, Journal of Political Economy 81(3).
"""

import math

# Constants used across the module.
SQRT_TWO_OVER_PI = math.sqrt(2.0 / math.pi)
DAYS_PER_YEAR = 365.0


def _validate_positive(value: float, name: str) -> None:
    """Reject non-positive ``value``; we never approximate over a domain
    where the formulas would produce nan or inf."""
    if value is None:
        raise ValueError(f"{name} must not be None")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value}")
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")


def annualised_iv_from_rank(
    iv_rank: float,
    *,
    iv_floor: float = 0.10,
    iv_ceiling: float = 1.20,
) -> float:
    """Convert an IV rank in ``[0, 100]`` into an annualised IV proxy.

    IV rank is *not* IV. It tells you where today's IV sits within the
    one-year range of IVs for that ticker. To turn it back into an
    annualised IV we linearly interpolate between ``iv_floor`` (rank=0)
    and ``iv_ceiling`` (rank=100). The defaults (10% / 120%) cover most
    earnings-active equities; pass tickered floors when you have them.

    Rank values outside ``[0, 100]`` are clipped to that range.
    """
    if iv_rank is None or not math.isfinite(iv_rank):
        raise ValueError("iv_rank must be a finite number")
    if iv_floor <= 0 or iv_ceiling <= iv_floor:
        raise ValueError("iv_floor must be > 0 and iv_ceiling must exceed iv_floor")
    clipped = max(0.0, min(100.0, float(iv_rank)))
    return iv_floor + (clipped / 100.0) * (iv_ceiling - iv_floor)


def time_in_years(days_to_expiry: float) -> float:
    """Convert days-to-expiry to year fraction. Floors at 1e-6 to avoid
    division by zero when callers pass zero days."""
    if days_to_expiry is None or not math.isfinite(days_to_expiry):
        raise ValueError("days_to_expiry must be a finite number")
    return max(float(days_to_expiry), 1e-6) / DAYS_PER_YEAR


def d1(spot: float, strike: float, sigma: float, t_years: float, r: float = 0.0) -> float:
    """Black-Scholes ``d1``."""
    _validate_positive(spot, "spot")
    _validate_positive(strike, "strike")
    _validate_positive(sigma, "sigma")
    _validate_positive(t_years, "t_years")
    return (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / (sigma * math.sqrt(t_years))


def d2(spot: float, strike: float, sigma: float, t_years: float, r: float = 0.0) -> float:
    """Black-Scholes ``d2 = d1 - σ√T``."""
    return d1(spot, strike, sigma, t_years, r) - sigma * math.sqrt(t_years)


def implied_one_sigma_move(
    spot: float,
    sigma_annual: float,
    days_to_expiry: float,
) -> float:
    """Implied 1-σ move at the money: ``S · σ · √T``.

    Returns the dollar move (absolute, not percent) the market is pricing
    in as one standard deviation. The 68% confidence band around spot at
    expiry is roughly ``[spot - move_1σ, spot + move_1σ]``.
    """
    _validate_positive(spot, "spot")
    _validate_positive(sigma_annual, "sigma_annual")
    t = time_in_years(days_to_expiry)
    return spot * sigma_annual * math.sqrt(t)


def expected_absolute_move(
    spot: float,
    sigma_annual: float,
    days_to_expiry: float,
) -> float:
    """Short-horizon expected absolute price move at the money.

    ``E[|S_T - S_0|] ≈ S · σ · √T · √(2/π) ≈ 0.7979 · S · σ · √T``.

    This normal/small-move approximation is the canonical "breakeven
    move" priced into an ATM straddle. Always less than the one-sigma
    move; the gap is the cost of the tails.
    """
    return implied_one_sigma_move(spot, sigma_annual, days_to_expiry) * SQRT_TWO_OVER_PI


def atm_straddle_breakeven_percent(sigma_annual: float, days_to_expiry: float) -> float:
    """ATM straddle breakeven as a percentage of spot.

    Equivalent to ``expected_absolute_move / spot``. Convenient when
    comparing across tickers.
    """
    _validate_positive(sigma_annual, "sigma_annual")
    t = time_in_years(days_to_expiry)
    return sigma_annual * math.sqrt(t) * SQRT_TWO_OVER_PI


def implied_vs_realised_premium(
    implied_move_dollars: float,
    realised_move_dollars: float,
) -> dict[str, float]:
    """Compute the volatility risk premium in dollar terms.

    Positive ``vrp_dollars`` → the options market priced in *more* than
    actually happened → short-vol was the right side. Negative → long-vol
    was the right side.

    Returns a dict so callers can pick what they need without recomputing.
    """
    if implied_move_dollars is None or realised_move_dollars is None:
        raise ValueError("implied and realised move must both be provided")
    vrp_dollars = implied_move_dollars - realised_move_dollars
    if implied_move_dollars == 0:
        vrp_fraction = 0.0
    else:
        vrp_fraction = vrp_dollars / implied_move_dollars
    return {
        "impliedMoveDollars": float(implied_move_dollars),
        "realisedMoveDollars": float(realised_move_dollars),
        "vrpDollars": float(vrp_dollars),
        "vrpFraction": float(vrp_fraction),
    }


def normal_cdf(x: float) -> float:
    """Standard normal CDF via the error function.

    Used in any downstream Greek computation; ``math.erf`` is in stdlib
    so we keep the dependency surface at zero.
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def approximate_call_delta(
    spot: float,
    strike: float,
    sigma_annual: float,
    days_to_expiry: float,
    r: float = 0.0,
) -> float:
    """Black-Scholes call delta = N(d1).

    For a call: delta ∈ [0, 1]. At-the-money is ~0.5; deep ITM → 1; deep
    OTM → 0. The strike-selector uses this to keep target deltas in the
    operator's preferred band.
    """
    return normal_cdf(d1(spot, strike, sigma_annual, time_in_years(days_to_expiry), r))


def approximate_put_delta(
    spot: float,
    strike: float,
    sigma_annual: float,
    days_to_expiry: float,
    r: float = 0.0,
) -> float:
    """Black-Scholes put delta = N(d1) - 1, so puts are in ``[-1, 0]``."""
    return approximate_call_delta(spot, strike, sigma_annual, days_to_expiry, r) - 1.0
