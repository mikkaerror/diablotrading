#!/usr/bin/env python3
"""Liquidity-gate reference-basket acceptance test (research-only).

Purpose
-------
The paper campaign is stuck at 1/30 distinct events. A dominant blocker is the
`thin-atm-liquidity` quality flag / `atmLiquidityScore < 70` gate, which fires on
~10 of 12 names in the live chain pull and starves the funnel.

This module is a diagnostic + acceptance test for the implemented
spread-primary gate in `inferno_schwab_options.py`. It:

  1. Loads the live Schwab options snapshot (`data/inferno_schwab_options.json`).
  2. For every symbol, prints the current verdict (is `thin-atm-liquidity` set?)
     next to the implemented spread-primary verdict.
  3. Applies two production thresholds:
       - LIVE gate  (tight): ATM window median spread <= LIVE_MAX_SPREAD_PCT
       - PAPER gate (admit-with-friction): spread <= PAPER_MAX_SPREAD_PCT, on the
         understanding that the paper fill model charges the FULL spread as cost.
  4. Reference-basket acceptance: any known-liquid name present in the pull MUST
     pass the PAPER gate. If one doesn't, the gate is miscalibrated by
     construction and `acceptance_passed` is False (CLI exits non-zero).

Why spread-primary, and why a friction-charged paper gate
---------------------------------------------------------
Raw volume/OI reward a meme-stock options frenzy over an orderly market, so a
score built on them can rank a crypto-miner above a mega-cap. The bid/ask
*spread* is the direct execution cost and the honest tradeability signal. For a
paper test with simulated fills, a wide spread is not a reason to exclude a name
outright -- it is a cost to charge. Excluding wide names entirely both starves
the funnel AND biases the sample toward high-volume meme names. Admit them, charge
the spread, and let the pre-registered kill/confirm gates decide.

Boundary: research-only. `liveTradingAllowed`/`brokerSubmitAllowed` untouched.
No risk constant edited. Diagnostic output only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from inferno_schwab_options import (
    HARD_WIDE_SPREAD_PCT,
    LIVE_MAX_SPREAD_PCT,
    PAPER_MAX_SPREAD_PCT,
    PAPER_MIN_WINDOW_OI,
    live_liquidity_gate,
    paper_liquidity_gate,
    spread_for_liquidity_gate,
)

LIQUIDITY_REF_STAGE = "liquidity-reference-basket-research-only"

# Known-liquid names that MUST pass the paper gate whenever they appear in a pull.
# If any of these is present and fails, the gate is broken by construction.
REFERENCE_BASKET = ("GOOG", "GOOGL", "AAPL", "MSFT", "SPY", "QQQ", "NVDA", "AMZN")

OPTIONS_SNAPSHOT = os.environ.get(
    "INFERNO_SCHWAB_OPTIONS_FILE", "data/inferno_schwab_options.json"
)


@dataclass
class NameVerdict:
    symbol: str
    underlyingPrice: Optional[float]
    atmSpreadPct: Optional[float]
    windowMedianSpreadPct: Optional[float]
    windowOpenInterest: Optional[int]
    windowContractCount: Optional[int]
    atmLiquidityScore: Optional[int]
    currentThinFlag: bool
    currentQualityFlags: list = field(default_factory=list)
    proposedLivePass: bool = False
    proposedPaperPass: bool = False
    inReferenceBasket: bool = False
    note: str = ""


def _spread_for_gate(row: dict) -> Optional[float]:
    """Prefer the robust window-median spread; fall back to single ATM spread."""
    return spread_for_liquidity_gate(row)


def evaluate_row(row: dict) -> NameVerdict:
    sym = row.get("symbol", "")
    flags = list(row.get("qualityFlags", []) or [])
    spread = _spread_for_gate(row)
    oi = row.get("atmWindowOpenInterest")
    in_ref = sym.upper() in REFERENCE_BASKET
    live_gate = live_liquidity_gate(row)
    paper_gate = paper_liquidity_gate(row)
    live_pass = bool(live_gate["passed"])
    paper_pass = bool(paper_gate["passed"])

    note = ""
    if spread is None:
        note = "no ATM spread available"
    elif spread > HARD_WIDE_SPREAD_PCT:
        note = "genuinely wide -> excluded from paper too (correct)"
    elif not paper_pass and (oi is None or oi < PAPER_MIN_WINDOW_OI):
        note = "fails on thin window OI, not spread"
    elif paper_pass and not live_pass:
        note = "paper: admit + charge full spread as friction"

    return NameVerdict(
        symbol=sym,
        underlyingPrice=row.get("underlyingPrice"),
        atmSpreadPct=row.get("atmSpreadPct"),
        windowMedianSpreadPct=row.get("atmWindowMedianSpreadPct"),
        windowOpenInterest=oi,
        windowContractCount=row.get("atmWindowContractCount"),
        atmLiquidityScore=row.get("atmLiquidityScore"),
        currentThinFlag="thin-atm-liquidity" in flags,
        currentQualityFlags=flags,
        proposedLivePass=live_pass,
        proposedPaperPass=paper_pass,
        inReferenceBasket=in_ref,
        note=note,
    )


def build_reference_basket(path: str = OPTIONS_SNAPSHOT) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        snap = json.load(fh)
    rows = snap.get("rows", []) or []
    verdicts = [evaluate_row(r) for r in rows]

    present_ref = [v for v in verdicts if v.inReferenceBasket]
    ref_failures = [v for v in present_ref if not v.proposedPaperPass]
    acceptance_passed = len(ref_failures) == 0

    current_thin = sum(1 for v in verdicts if v.currentThinFlag)
    paper_admits = sum(1 for v in verdicts if v.proposedPaperPass)
    live_admits = sum(1 for v in verdicts if v.proposedLivePass)

    return {
        "stage": LIQUIDITY_REF_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "generatedFrom": path,
        "snapshotGeneratedAt": snap.get("generatedAt"),
        "symbolCount": len(rows),
        "currentThinFlagCount": current_thin,
        "proposedPaperAdmitCount": paper_admits,
        "proposedLiveAdmitCount": live_admits,
        "referenceBasketPresent": [v.symbol for v in present_ref],
        "referenceBasketFailures": [v.symbol for v in ref_failures],
        "acceptancePassed": acceptance_passed,
        "thresholds": {
            "LIVE_MAX_SPREAD_PCT": LIVE_MAX_SPREAD_PCT,
            "PAPER_MAX_SPREAD_PCT": PAPER_MAX_SPREAD_PCT,
            "PAPER_MIN_WINDOW_OI": PAPER_MIN_WINDOW_OI,
            "HARD_WIDE_SPREAD_PCT": HARD_WIDE_SPREAD_PCT,
        },
        "verdicts": [asdict(v) for v in verdicts],
        "citations": [
            "data/inferno_schwab_options.json (live chain pull)",
            "docs/LIQUIDITY_METRIC_MISCALIBRATION_2026-07-06.md",
            "docs/CAMPAIGN_KILL_GATES_2026-07-06.md",
        ],
    }


def reference_basket_text(payload: dict[str, Any]) -> str:
    lines = []
    lines.append("Inferno Liquidity Reference-Basket Acceptance Test (research-only)")
    lines.append(f"Snapshot: {payload.get('snapshotGeneratedAt')}")
    lines.append(
        f"Names: {payload['symbolCount']} | current 'thin' flags: "
        f"{payload['currentThinFlagCount']} | proposed paper-admit: "
        f"{payload['proposedPaperAdmitCount']} | proposed live-admit: "
        f"{payload['proposedLiveAdmitCount']}"
    )
    lines.append("")
    hdr = f"{'sym':<6}{'px':>9}{'spr%':>7}{'winOI':>8}{'liq':>5}  {'now':>5} {'paper':>6} {'live':>5}  note"
    lines.append(hdr)
    for v in payload["verdicts"]:
        sp = v["windowMedianSpreadPct"]
        sp = sp if sp is not None else v["atmSpreadPct"]
        sp_s = f"{sp*100:.1f}" if sp is not None else "NA"
        now = "THIN" if v["currentThinFlag"] else "ok"
        paper = "PASS" if v["proposedPaperPass"] else "fail"
        live = "PASS" if v["proposedLivePass"] else "fail"
        star = "*" if v["inReferenceBasket"] else " "
        lines.append(
            f"{v['symbol']:<6}{(v['underlyingPrice'] or 0):>9.2f}{sp_s:>7}"
            f"{(v['windowOpenInterest'] or 0):>8}{(v['atmLiquidityScore'] or 0):>5}"
            f"  {now:>5} {paper:>6} {live:>5}{star} {v['note']}"
        )
    lines.append("")
    ref_present = payload["referenceBasketPresent"]
    if ref_present:
        status = "PASS" if payload["acceptancePassed"] else "FAIL"
        lines.append(
            f"Reference-basket acceptance: {status} "
            f"(present: {', '.join(ref_present)}; "
            f"failures: {', '.join(payload['referenceBasketFailures']) or 'none'})"
        )
    else:
        lines.append(
            "Reference-basket acceptance: N/A this pull "
            "(no reference-basket names present in the snapshot). "
            "Re-run after a chain pull that includes GOOG/AAPL/MSFT/SPY."
        )
    lines.append("")
    lines.append("Reading: 'now' = quality flag state; 'paper'/'live' = implemented spread-primary")
    lines.append("gates. Paper admits wide names and CHARGES the full spread as friction;")
    lines.append("the pre-registered kill/confirm gates then decide if any edge survives.")
    lines.append("Research-only. Authority unchanged.")
    return "\n".join(lines)


def save_reference_basket(payload: dict[str, Any]) -> None:
    os.makedirs("data", exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    with open("data/inferno_liquidity_reference_basket.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    with open("reports/liquidity_reference_basket_latest.txt", "w", encoding="utf-8") as fh:
        fh.write(reference_basket_text(payload))


def main(argv: Optional[list] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "status", "assert"])
    parser.add_argument("--file", default=OPTIONS_SNAPSHOT)
    args = parser.parse_args(argv)

    payload = build_reference_basket(args.file)
    if args.command in ("run", "status"):
        print(reference_basket_text(payload))
        if args.command == "run":
            save_reference_basket(payload)
    # `assert` mode: exit non-zero if a present reference name fails the paper gate.
    if args.command == "assert" and not payload["acceptancePassed"]:
        print("ACCEPTANCE FAILED:", payload["referenceBasketFailures"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
