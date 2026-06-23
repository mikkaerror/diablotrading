"""Inferno Universe Cap-Fit Audit (BACKLOG #2, research-only).

What it does:
    Walks every ticker in `data/latest_snapshot.json` (the desk's working
    universe) and estimates, per ticker, the approximate per-contract dollar
    cost of each of four standard option structures. Compares each to the
    desk's current per-ticket cap. Emits a diagnostic report that answers
    the question the discipline doc and the deep-dive can't answer alone:

        "Of N tickers in the universe, how many produce ANY structure that
        fits the current per-ticket cap? Which structures? And of the ones
        that don't fit, what's the binding constraint — price, vol, or both?"

What it doesn't do:
    - It does NOT touch live prices, the broker, or any authority.
    - It does NOT mutate the universe, the slate, or any ledger.
    - It produces estimates from the snapshot, not Schwab quotes — so the
      numbers are first-order accurate (within ~30%), not pricing-grade.
      That's fine for the question being asked.

Stage:        universe-cap-fit-research-only
Promotable:   False
Authority:    unchanged

Estimation model (Brenner-Subrahmanyam approximation + ATR proxy):
    - Annualized vol proxy:    sigma = atrPercent% * sqrt(252)
    - 30-DTE ATM straddle:     0.8 * S * sigma * sqrt(30/365)
    - 30-DTE single ATM leg:   straddle / 2
    - $5-wide ATM debit:       0.35 * width = $175  (typical, scaled by IV rank)
    - $1-wide credit spread:   max-loss = $100 - credit (credit ~ $40)
    - Narrow iron condor:      max-loss ~ $80

References:
    Brenner, M. & Subrahmanyam, M.G. (1988). "A Simple Formula to Compute
    the Implied Standard Deviation," Financial Analysts Journal 44(5).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
REPORTS = ROOT / "reports"

SNAPSHOT_FILE = DATA / "latest_snapshot.json"
CAPITAL_SCALING_FILE = DATA / "inferno_capital_scaling.json"
OUTPUT_JSON = DATA / "inferno_universe_cap_fit.json"
OUTPUT_TEXT = REPORTS / "universe_cap_fit_latest.txt"

STAGE = "universe-cap-fit-research-only"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _current_cap_dollars() -> tuple[float, str]:
    """Return (cap_dollars, source_label). Defaults to $500 config cap."""
    payload = _load_json(CAPITAL_SCALING_FILE)
    enforced = payload.get("currentEnforced") or {}
    cap = enforced.get("singleTicketCapDollars")
    if isinstance(cap, (int, float)) and cap > 0:
        return float(cap), "currentEnforced.singleTicketCapDollars"
    rec = (payload.get("recommendation") or {}).get("perTicketDollars")
    if isinstance(rec, (int, float)) and rec > 0:
        return float(rec), "recommendation.perTicketDollars"
    return 500.0, "fallback-default"


def _estimate_structure_costs(
    price: float, atr_pct: float | None, iv_rank: float | None
) -> dict[str, float | None]:
    """Estimate per-contract dollar cost for four standard structures.

    All four are 30-DTE approximations. The point is order-of-magnitude
    triage, not pricing-grade. Returns dollar cost per contract; None if
    inputs insufficient.
    """
    if not isinstance(price, (int, float)) or price <= 0:
        return {"straddle": None, "long_leg": None, "debit_5w": None, "credit_1w": None}

    # Annualized vol proxy from ATR%; fallback to mid-vol when ATR missing.
    if isinstance(atr_pct, (int, float)) and atr_pct > 0:
        sigma_annual = (atr_pct / 100.0) * math.sqrt(252)
    else:
        sigma_annual = 0.35  # mid retail-stock IV when no signal

    # IV-rank tilt: high ivRank means premium is rich (multiplier > 1).
    if isinstance(iv_rank, (int, float)):
        iv_tilt = 0.7 + (iv_rank / 100.0) * 0.6  # 0.7x at IVR=0, 1.3x at IVR=100
    else:
        iv_tilt = 1.0

    # Brenner-Subrahmanyam ATM straddle, 30 DTE
    t = 30.0 / 365.0
    straddle_per_share = 0.8 * price * sigma_annual * math.sqrt(t) * iv_tilt
    straddle_dollars = straddle_per_share * 100.0
    long_leg_dollars = straddle_dollars / 2.0

    # Wide debit spread ($5 wide ATM) costs about 30-50% of width, IV-tilted.
    debit_5w_dollars = 5.0 * 100.0 * (0.30 + 0.10 * iv_tilt)

    # Narrow credit spread ($1 wide), max loss = $100 - credit (credit ~ 30-50%)
    credit_1w_max_loss = 100.0 - (40.0 * iv_tilt)

    return {
        "straddle": round(straddle_dollars, 2),
        "long_leg": round(long_leg_dollars, 2),
        "debit_5w": round(debit_5w_dollars, 2),
        "credit_1w": round(max(credit_1w_max_loss, 25.0), 2),
    }


def _fits(cost: float | None, cap: float) -> bool:
    return isinstance(cost, (int, float)) and cost <= cap


def build_audit(*, snapshot: dict | None = None, cap_dollars: float | None = None) -> dict:
    snap = snapshot if snapshot is not None else _load_json(SNAPSHOT_FILE)
    rows = snap.get("rows") or []

    if cap_dollars is None:
        cap, cap_source = _current_cap_dollars()
    else:
        cap, cap_source = float(cap_dollars), "explicit"

    per_ticker: list[dict[str, Any]] = []
    counts = {
        "total": 0,
        "anyFits": 0,
        "noneFits": 0,
        "straddleFits": 0,
        "longLegFits": 0,
        "debit5wFits": 0,
        "credit1wFits": 0,
        "missingPrice": 0,
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        counts["total"] += 1
        ticker = (row.get("ticker") or "").strip().upper()
        price = row.get("price")
        atr_pct = row.get("atrPercent")
        iv_rank = row.get("ivRank")
        dte_earn = row.get("daysUntilEarnings")

        if not isinstance(price, (int, float)) or price <= 0:
            counts["missingPrice"] += 1
            per_ticker.append(
                {
                    "ticker": ticker,
                    "price": price,
                    "verdict": "missing-price",
                    "structures": None,
                }
            )
            continue

        costs = _estimate_structure_costs(float(price), atr_pct, iv_rank)
        fits = {k: _fits(v, cap) for k, v in costs.items()}
        any_fits = any(fits.values())
        if any_fits:
            counts["anyFits"] += 1
        else:
            counts["noneFits"] += 1
        if fits["straddle"]:
            counts["straddleFits"] += 1
        if fits["long_leg"]:
            counts["longLegFits"] += 1
        if fits["debit_5w"]:
            counts["debit5wFits"] += 1
        if fits["credit_1w"]:
            counts["credit1wFits"] += 1

        per_ticker.append(
            {
                "ticker": ticker,
                "price": price,
                "atrPercent": atr_pct,
                "ivRank": iv_rank,
                "daysUntilEarnings": dte_earn,
                "structures": costs,
                "fits": fits,
                "verdict": "any-fits" if any_fits else "none-fits",
            }
        )

    # Bottom-line: of total, how many fit at all?
    fit_rate = (counts["anyFits"] / counts["total"]) if counts["total"] else 0.0

    # If <30% fit, the universe is structurally too expensive for the cap.
    if fit_rate < 0.30:
        verdict = "universe-too-expensive-for-cap"
    elif fit_rate < 0.60:
        verdict = "many-tickers-cap-stretched"
    else:
        verdict = "universe-well-suited-to-cap"

    payload = {
        "generatedAt": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "stage": STAGE,
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "capDollars": cap,
        "capSource": cap_source,
        "verdict": verdict,
        "counts": counts,
        "fitRate": round(fit_rate, 4),
        "perTicker": per_ticker,
        "citations": [
            "Brenner & Subrahmanyam (1988) — simple ATM straddle formula",
            "Estimates are order-of-magnitude; not pricing-grade",
        ],
        "reminders": [
            "this module estimates from snapshot; not pricing-grade",
            "research-only; never approves, rejects, or routes a trade",
            "use to diagnose the funnel bottleneck, not to size a trade",
        ],
    }
    return payload


def render_text(payload: dict) -> str:
    cap = payload.get("capDollars", "?")
    counts = payload.get("counts", {})
    fit_rate = payload.get("fitRate", 0) * 100
    lines = [
        "Inferno Universe Cap-Fit Audit",
        "",
        f"Generated: {payload.get('generatedAt','?')}",
        f"Verdict:   {payload.get('verdict','?')}",
        f"Cap:       ${cap:.2f}  (source: {payload.get('capSource','?')})",
        f"Fit rate:  {fit_rate:.1f}% ({counts.get('anyFits',0)}/{counts.get('total',0)} tickers fit at least one structure)",
        "",
        "Per-structure breakdown:",
        f"  Straddle (30-DTE ATM):     {counts.get('straddleFits',0)}/{counts.get('total',0)}",
        f"  Single ATM leg (30-DTE):   {counts.get('longLegFits',0)}/{counts.get('total',0)}",
        f"  $5-wide debit spread:      {counts.get('debit5wFits',0)}/{counts.get('total',0)}",
        f"  $1-wide credit spread:     {counts.get('credit1wFits',0)}/{counts.get('total',0)}",
        f"  Missing price:             {counts.get('missingPrice',0)}/{counts.get('total',0)}",
        "",
    ]
    # Top-5 most-expensive that don't fit
    no_fit = [r for r in payload.get("perTicker", []) if r.get("verdict") == "none-fits"]
    if no_fit:
        no_fit_sorted = sorted(no_fit, key=lambda r: -(r.get("price") or 0))
        lines.append("Top 10 tickers that don't fit any structure (sorted by price):")
        for r in no_fit_sorted[:10]:
            s = r.get("structures", {}) or {}
            lines.append(
                f"  {r['ticker']:<6} ${r['price']:>8.2f}  "
                f"straddle≈${s.get('straddle','?')}  "
                f"long_leg≈${s.get('long_leg','?')}"
            )
        lines.append("")
    # Best 10 fits (cheapest that fit something)
    fits = [r for r in payload.get("perTicker", []) if r.get("verdict") == "any-fits"]
    if fits:
        fits_sorted = sorted(fits, key=lambda r: (r.get("structures") or {}).get("long_leg") or 1e9)
        lines.append("Top 10 cheapest fits (sorted by long-leg cost):")
        for r in fits_sorted[:10]:
            s = r.get("structures", {}) or {}
            dte = r.get("daysUntilEarnings", "?")
            lines.append(
                f"  {r['ticker']:<6} ${r['price']:>8.2f}  "
                f"long_leg≈${s.get('long_leg','?')}  "
                f"straddle≈${s.get('straddle','?')}  "
                f"dte_earn={dte}"
            )
        lines.append("")
    lines.append("Reminders:")
    for r in payload.get("reminders", []):
        lines.append(f"  - {r}")
    return "\n".join(lines) + "\n"


def save_audit(payload: dict | None = None) -> dict:
    if payload is None:
        payload = build_audit()
    DATA.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    OUTPUT_TEXT.write_text(render_text(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Universe cap-fit audit")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("run", help="Build the audit and write artifacts")
    sub.add_parser("status", help="Print the latest report")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.cmd == "status":
        if OUTPUT_TEXT.exists():
            print(OUTPUT_TEXT.read_text(encoding="utf-8"))
        else:
            print("No audit on disk. Run with no args (or `run`) to build one.")
        return 0
    payload = save_audit()
    print(render_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
