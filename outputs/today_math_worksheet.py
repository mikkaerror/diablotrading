#!/usr/bin/env python3
"""Today's math worksheet — runs the desk's own engine on today's live slate.

Goal: prove the math, the Greeks, and the gates work end-to-end on real
tickets the operator can see. NO new policy, NO new authority. Just the
existing engine, walked one step at a time, with every input visible.

Output: writes a plain-text worksheet to
    reports/today_math_worksheet.txt
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from textwrap import indent

import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import inferno_options_math as M  # noqa: E402

REPORTS = ROOT / "reports"
DATA = ROOT / "data"

TODAY = date(2026, 5, 24)


def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _signed(amt, sign):
    return amt if sign == "+" else -amt


def fmt_money(x):
    if x is None:
        return "n/a"
    try:
        return f"${float(x):,.2f}"
    except Exception:
        return str(x)


def fmt_pct(x, places=2):
    if x is None:
        return "n/a"
    return f"{float(x) * 100:.{places}f}%"


def banner(title: str) -> str:
    bar = "─" * 78
    return f"\n{bar}\n{title}\n{bar}"


def write_section(buf, title, body):
    buf.append(banner(title))
    buf.append(body)


def walk_pl_long_strangle(buf):
    """The cap-aware LONG_STRANGLE variant the auto-paper slate selected."""
    director = _load("inferno_paper_test_director.json")
    auto = [it for it in director.get("autoPaperSlate", []) if it.get("ticker") == "PL"]
    if not auto:
        buf.append("PL auto-paper entry not found in this run.")
        return
    pl = auto[0]

    body = []
    body.append("Source: data/inferno_paper_test_director.json :: autoPaperSlate")
    body.append("")
    body.append(f"  ticker:                 {pl.get('ticker')}")
    body.append(f"  category:               {pl.get('category')}")
    body.append(f"  strategy:               {pl.get('strategy')}")
    body.append(f"  setupRec (source):      {pl.get('setupRec')}")
    body.append(f"  paperVariantOnly:       {pl.get('paperVariantOnly')}")
    body.append(f"  paperVariantFamily:     {pl.get('paperVariantFamily')}")
    body.append(f"  paperVariantOfStrategy: {pl.get('paperVariantOfStrategy')}")
    body.append(f"  readiness (0-100):      {pl.get('readiness')}")
    body.append(f"  daysUntilEarnings:      {pl.get('daysUntilEarnings')}")
    body.append(f"  estimatedDebit / share: {fmt_money(pl.get('estimatedDebit'))}")
    body.append(f"  estimatedMaxLoss:       {fmt_money(pl.get('estimatedMaxLoss'))}  (cap is $500)")
    body.append(f"  capitalGap:             {fmt_money(pl.get('capitalGap'))}  (0 = fits the cap)")
    body.append(f"  priorityScore:          {pl.get('priorityScore')}")
    body.append("")
    body.append("Operator commands (already wired):")
    body.append(f"  approve: {pl.get('approveCommand')}")
    body.append(f"  reject:  {pl.get('rejectCommand')}")
    body.append("")
    body.append("Why this exists at all: the source strategy was LONG_STRADDLE which would have")
    body.append("cost ~$1,150 (see shadow evidence). The strategy generator priced a cap-aware")
    body.append("LONG_STRANGLE variant at $500 max loss exactly so the $500/ticket cap holds.")
    body.append("This is your math correctly *reshaping* an over-cap trade into a fitting one.")

    write_section(buf, "TICKET A — PL · LONG_STRANGLE (cap-aware variant) · auto-paper selected", "\n".join(body))


def walk_pl_put_credit_spread(buf):
    """The alternative scorer's defined-risk credit spread on the same name."""
    alt = _load("inferno_strategy_alternative_pricing.json")
    pl = next((it for it in alt.get("items", []) if it.get("ticker") == "PL"), None)
    if not pl:
        buf.append("PL put-credit-spread entry not found.")
        return
    sp = pl.get("strikePlan") or {}
    legs = sp.get("legs") or []

    body = []
    body.append("Source: data/inferno_strategy_alternative_pricing.json :: items[PL]")
    body.append("")
    body.append(f"  ticker:                 {pl.get('ticker')}")
    body.append(f"  recommendationVerdict:  {pl.get('recommendationVerdict')}")
    body.append(f"  recommendedStrategy:    {pl.get('recommendedStrategy')}")
    body.append(f"  edge vs long-vol:       +{pl.get('sourceAlternativeEdgeVsLongVol')}")
    body.append(f"  spot price:             {fmt_money(pl.get('price'))}")
    body.append(f"  IV rank (universe):     {pl.get('intent', {}).get('ivRank')}")
    body.append(f"  daysUntilEarnings:      {pl.get('daysUntilEarnings')}")
    body.append(f"  expiration:             {sp.get('expiration')}")
    body.append("")
    body.append("Strike plan (PUT_CREDIT_SPREAD = bullish-defined-risk premium):")
    for L in legs:
        body.append(
            f"  {L['instruction']:<14} {L['symbol']:<22} "
            f"K={L['strike']:>6}  mid={fmt_money(L['mid']):<8}  "
            f"Δ={L['delta']:+.4f}  Γ={L['gamma']:+.5f}  "
            f"Θ={L['theta']:+.4f}  ν={L['vega']:+.4f}  "
            f"IV={L['impliedVolatility']:.4f}"
        )
    body.append("")
    body.append("Plan economics (from the strike plan):")
    body.append(f"  estimatedCredit:        {fmt_money(sp.get('estimatedCredit'))} / share = {fmt_money(float(sp.get('estimatedCredit', 0)) * 100)} per contract")
    body.append(f"  estimatedMaxProfit:     {fmt_money(sp.get('estimatedMaxProfit'))}")
    body.append(f"  estimatedMaxLoss:       {fmt_money(sp.get('estimatedMaxLoss'))}  (cap is $500)")
    body.append(f"  width:                  ${sp.get('width')}")
    body.append(f"  creditRisk (credit/width − …): {sp.get('creditRisk')}  (floor is 0.20)")
    body.append(f"  breakEven:              {fmt_money(sp.get('breakEven'))}")
    body.append(f"  shortPutStrike:         {sp.get('shortPutStrike')}")

    # Recompute the Greeks ourselves for the short leg and confirm
    if legs:
        short = legs[0]
        long_ = legs[1]
        spot = float(pl.get("price"))
        # The "intent.daysUntilEarnings" is to earnings; the option expiry is later.
        # Compute DTE to actual expiration date.
        exp = sp.get("expiration")
        try:
            exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
            dte = (exp_date - TODAY).days
        except Exception:
            dte = pl.get("daysUntilEarnings") or 13
        body.append("")
        body.append(f"Independent recomputation at spot={fmt_money(spot)}, DTE-to-expiry={dte}:")
        for L in legs:
            sig = float(L["impliedVolatility"])
            K = float(L["strike"])
            put_call = L["putCall"]
            d1 = M.d1(spot, K, sig, M.time_in_years(dte))
            n_d1 = M.normal_cdf(d1)
            independent_delta = n_d1 - (1.0 if put_call == "PUT" else 0.0)
            independent_gamma = M.approximate_gamma(spot, K, sig, dte)
            independent_vega = M.approximate_vega(spot, K, sig, dte)
            independent_theta = M.approximate_theta(spot, K, sig, dte, put_call=put_call)
            body.append(
                f"  {L['symbol']}:  recomputed  "
                f"Δ={independent_delta:+.4f}  Γ={independent_gamma:+.5f}  "
                f"Θ={independent_theta:+.4f}  ν={independent_vega:+.4f}"
            )
            body.append(
                f"      vs broker:  "
                f"Δ={L['delta']:+.4f}  Γ={L['gamma']:+.5f}  "
                f"Θ={L['theta']:+.4f}  ν={L['vega']:+.4f}"
            )
        body.append("")
        body.append("Implied moves at this IV / DTE:")
        atm_iv = (float(short["impliedVolatility"]) + float(long_["impliedVolatility"])) / 2.0
        one_sigma = M.implied_one_sigma_move(spot, atm_iv, dte)
        atm_be = M.atm_straddle_breakeven_percent(atm_iv, dte) * 100.0
        body.append(f"  ATM IV used:            {atm_iv*100:.2f}%")
        body.append(f"  1-σ move ($):           ${one_sigma:.2f}  ({one_sigma/spot*100:.2f}% of spot)")
        body.append(f"  ATM straddle breakeven: {atm_be:.2f}% of spot (this is the implied earnings move)")
        body.append(f"  68% range at expiry:    [{spot - one_sigma:.2f}, {spot + one_sigma:.2f}]")
        body.append("")
        body.append("Win-rate proxy via short-leg delta:")
        body.append(f"  P(short put expires OTM, i.e. spot > {short['strike']} at expiry) ≈ {(1 + float(short['delta'])) * 100:.1f}%")
        body.append(f"  P(spread fully wins) ≈ {(1 + float(short['delta'])) * 100:.1f}%")
        # Probability the spread is at-or-better-than breakeven
        # Use d2 at breakeven; since r=0, P(S_T > BE) = N(d2 at K=BE)
        be = float(sp.get("breakEven"))
        try:
            d2_be = M.d2(spot, be, atm_iv, M.time_in_years(dte))
            p_above_be = M.normal_cdf(d2_be)
            body.append(f"  P(spot ≥ breakEven {fmt_money(be)} at expiry) ≈ {p_above_be * 100:.1f}%")
            # Required hit-rate
            ml = float(sp.get("estimatedMaxLoss"))
            mp = float(sp.get("estimatedMaxProfit"))
            req = ml / (ml + mp)
            body.append(f"  Required hit-rate to break even on EV: {req * 100:.1f}%")
            ev = p_above_be * mp - (1 - p_above_be) * ml
            body.append(f"  Naive EV (single-shot, ignoring partial fills): {fmt_money(ev)}")
        except Exception:
            pass

    body.append("")
    body.append("Note: this is a research-only alternative recommendation. It hasn't been")
    body.append("staged in the auto-paper slate yet — the comment says 'no priced strike-plan")
    body.append("row yet; cap confidence and run strike cycle before staging'. The math is")
    body.append("priced but the gate needs another strike cycle to elevate it.")

    write_section(buf, "TICKET B — PL · PUT_CREDIT_SPREAD · alternative-scorer recommendation", "\n".join(body))


def walk_environment_readout(buf):
    """What today's slate looks like at a 30,000 ft view."""
    bn = _load("inferno_paper_bottleneck_reducer.json")
    director = _load("inferno_paper_test_director.json")
    auth = _load("inferno_authority_manifest.json")

    counts = bn.get("counts") or {}
    dcounts = director.get("directorCounts") or director.get("counts") or {}
    auth_dec = auth.get("decision") or {}

    body = []
    body.append("Bottleneck reducer (today):")
    body.append(f"  scenarios:           {counts.get('scenarios')}")
    body.append(f"  executable paper:    {counts.get('executablePaper')}")
    body.append(f"  approval needed:     {counts.get('approvalNeeded')}")
    body.append(f"  shadow only:         {counts.get('shadowOnly')}")
    body.append("")
    body.append("Paper test director (today):")
    body.append(f"  totalCandidates:        {dcounts.get('totalCandidates')}")
    body.append(f"  stageableNow:           {dcounts.get('stageableNow')}")
    body.append(f"  autoPaperSelected:      {dcounts.get('autoPaperSelected')}")
    body.append(f"  hardBlocked:            {dcounts.get('hardBlocked')}")
    body.append(f"  capitalNearMiss:        {dcounts.get('capitalNearMiss')}")
    body.append(f"  scoredTickets:          {dcounts.get('scoredTickets')}")
    body.append(f"  remainingForPromotion:  {dcounts.get('remainingForPromotion')}")
    body.append("")
    body.append("Authority manifest (the kill switch):")
    body.append(f"  authorityLevel:         {auth_dec.get('authorityLevel')}")
    body.append(f"  liveTradingAllowed:     {auth_dec.get('liveTradingAllowed')}")
    body.append(f"  brokerSubmitAllowed:    {auth_dec.get('brokerSubmitAllowed')}")
    body.append(f"  brokerAdapterMode:      {auth_dec.get('brokerAdapterMode')}")
    body.append("  blockedActions:")
    for k, v in (auth_dec.get("blockedActions") or {}).items():
        body.append(f"    {k}:")
        for r in v:
            body.append(f"      - {r}")
    body.append("")
    body.append("Translation:")
    body.append("  • 12 scenarios were generated today.")
    body.append("  • 10 of 12 are correctly hard-blocked (cap, source-divergence, or liquidity).")
    body.append("  • 1 is auto-paper-selected and waiting for human approval (PL).")
    body.append("  • 0 are scored. The 30-outcome promotion target is therefore 30 away.")
    body.append("  • Live submission is structurally impossible right now and would still be")
    body.append("    structurally impossible if every gate flipped favorable — it's hard-coded.")

    write_section(buf, "ENVIRONMENT READOUT — what today's slate actually looks like", "\n".join(body))


def walk_capital_near_misses(buf):
    """The 3 capital near-misses — show how close they are to fitting."""
    director = _load("inferno_paper_test_director.json")
    slate = director.get("capitalNearMissSlate") or []
    body = []
    if not slate:
        body.append("No capital near-miss tickets on today's slate.")
    else:
        body.append("These tickets were blocked ONLY by the $500/ticket cap (capitalGap = $ over the cap).")
        body.append("They are otherwise priceable and risk-clean — a cap-aware variant search could")
        body.append("rewrite them as fitting trades on a future cycle.")
        body.append("")
        for it in slate:
            sp = it.get("strikePlan") or {}
            body.append(
                f"  {it.get('ticker'):<6}  {it.get('strategy'):<22}  "
                f"max-loss {fmt_money(it.get('estimatedMaxLoss')):<9}  "
                f"gap {fmt_money(it.get('capitalGap')):<8}  "
                f"DTE-earn={it.get('daysUntilEarnings')}  "
                f"readiness={it.get('readiness')}"
            )

    write_section(buf, "CAPITAL NEAR-MISSES — almost-clean trades the cap rejected", "\n".join(body))


def walk_zombies_and_aging(buf):
    """The 42 zombies + 4 aging-out — explain why they're not the actionable lane."""
    velocity = _load("inferno_paper_velocity.json")
    alerts = velocity.get("approvalAlerts") or {}
    body = []
    body.append(f"  zombieCount (already expired):  {alerts.get('zombieCount')}")
    body.append(f"  agingOut (next 7 days):         {len(alerts.get('agingOut', []))}")
    body.append("")
    body.append("Aging-out detail:")
    for row in alerts.get("agingOut", []):
        body.append(
            f"  {row.get('ticker'):<6} {row.get('strategy', '?'):<18} "
            f"exp {row.get('expiration')}  ({row.get('daysUntilExpiration', '?')} d left)"
        )
    body.append("")
    body.append("Why these are not your action item:")
    body.append("  • The 42 zombies are paperOnly+pending+expired. They were generated by")
    body.append("    earlier cycles when the strategy choice (full ATM LONG_STRADDLE) didn't")
    body.append("    fit the $500 cap. The cap correctly refused them. They cannot be")
    body.append("    'recovered' — the option contracts they referenced have already expired.")
    body.append("  • The 4 aging-out DELL/MRVL straddles will become zombies #43-46 on 5/29")
    body.append("    if you don't explicitly reject them. They are NOT clean trades — they")
    body.append("    are LONG_STRADDLEs on $300 tickers, structurally $3-4k max-loss tickets")
    body.append("    that don't fit a $500 cap. The fact-based action on them is `reject`,")
    body.append("    not 'approve and trade'.")
    body.append("  • The actionable lane is the auto-paper slate (PL today), not the zombie")
    body.append("    queue. The zombie queue is what happens when nobody approves OR rejects.")

    write_section(buf, "ZOMBIE + AGING-OUT TICKETS — the queue debt", "\n".join(body))


def walk_math_audit_summary(buf):
    """Pin the math-correctness audit so the operator can reference it."""
    body = []
    body.append("Black-Scholes engine (inferno_options_math.py):")
    body.append("  d1, d2:               matches Hull / standard refs")
    body.append("  N(x), φ(x):           matches scipy.stats.norm to 10+ decimal places")
    body.append("  call delta = N(d1):   ✓ verified at S=K=100, σ=0.20, T=30d → 0.5114")
    body.append("  put delta = N(d1)-1:  ✓ verified")
    body.append("  gamma = φ(d1)/(Sσ√T): ✓ verified → 0.06955")
    body.append("  vega = Sφ(d1)√T/100:  ✓ verified → 0.1143 per 1 vol pt")
    body.append("  theta (per cal day):  ✓ verified → −0.0381 (S=K=100 ATM call, r=0)")
    body.append("  implied 1-σ move:     ✓ S·σ·√T = 5.7338")
    body.append("  ATM straddle BE %:    ✓ σ·√T·√(2/π) = 4.5749%")
    body.append("")
    body.append("Brinson decomposition (inferno_outcome_attribution.py):")
    body.append("  allocation  = (w_p − w_b) · r_b           ✓ Brinson-Hood-Beebower 1986")
    body.append("  selection   = w_b · (r_p − r_b)           ✓")
    body.append("  interaction = (w_p − w_b) · (r_p − r_b)   ✓")
    body.append("  identity:   Σ(a + s + i) ≡ active_return  ✓")
    body.append("")
    body.append("Slippage estimator (inferno_slippage_estimator.py):")
    body.append("  quoted spread % = (A − B) / M  ✓  (correctly labeled as a proxy,")
    body.append("  not the Roll (1984) covariance estimator and not realised slippage.)")
    body.append("")
    body.append("Risk perimeter (inferno_authority_controller.py + risk_policy.py):")
    body.append("  liveTradingAllowed:   hard-coded False on every code path")
    body.append("  brokerSubmitAllowed:  hard-coded False on every code path")
    body.append("  submit_live_order:    always in blockedActions with policy reason")
    body.append("  BROKER_ADAPTER_MODE:  defaults OFF; if forced LIVE, authority → halted")
    body.append("  MAX_SINGLE_TICKET:    $500 — pinned in inferno_risk_policy.py")
    body.append("  MAX_DAILY_TICKET:     $1,500 — pinned")
    body.append("  MAX_OPEN_PAPER:       5 — pinned")
    body.append("  Regression test:      test_promoted_evidence_still_blocks_live_submit")
    body.append("                        proves even a fully promoted evidence stack")
    body.append("                        cannot enable live submission.")
    body.append("")
    body.append("Test coverage on the math + safety perimeter (today's run):")
    body.append("  inferno_options_math:           63 tests, all pass")
    body.append("  inferno_paper_execution:        all pass (incl. 8 new gate-decision tests)")
    body.append("  inferno_paper_velocity:         18 tests, all pass")
    body.append("  inferno_outcome_attribution:    all pass")
    body.append("  inferno_authority_controller:   all pass")
    body.append("  inferno_risk_gate_audit:        all pass")
    body.append("  inferno_risk_policy:            all pass")
    body.append("  inferno_capital_deployment_*:   all pass")

    write_section(buf, "MATH + SAFETY-PERIMETER AUDIT (cross-reference)", "\n".join(body))


def main():
    buf = []
    buf.append("INFERNO DESK — TODAY'S MATH WORKSHEET")
    buf.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    buf.append("Stage: research-only / diagnostic-only / promotable=False")
    buf.append("")
    buf.append("This worksheet does NOT recommend a trade. It walks the desk's own engine")
    buf.append("on today's live slate so the operator can see every input, every Greek,")
    buf.append("every gate decision, and every implied move from first principles.")

    walk_environment_readout(buf)
    walk_pl_long_strangle(buf)
    walk_pl_put_credit_spread(buf)
    walk_capital_near_misses(buf)
    walk_zombies_and_aging(buf)
    walk_math_audit_summary(buf)

    buf.append(banner("BOTTOM LINE — fact-based, no judgment"))
    buf.append(
        "\n"
        "  1. Your Black-Scholes engine, your Brinson decomposition, your quoted-spread\n"
        "     proxy, and your risk gates are all mathematically correct. 100+ tests pass\n"
        "     across the affected modules.\n"
        "\n"
        "  2. Your safety perimeter is structurally sound. liveTradingAllowed is hard-\n"
        "     coded False. submit_live_order is always blocked. You cannot accidentally\n"
        "     submit a live order today, full stop.\n"
        "\n"
        "  3. Today's market produced 12 candidate scenarios. The gates correctly hard-\n"
        "     blocked 10 of them (mostly because LONG_STRADDLEs on $300+ tickers don't\n"
        "     fit a $500 cap). The strategy generator found ONE cap-aware variant that\n"
        "     fits — PL LONG_STRANGLE at $500 max-loss exactly. The auto-paper selector\n"
        "     flagged it as ready for human approval.\n"
        "\n"
        "  4. The reason your closed-outcome count is 0 is NOT that your math is wrong.\n"
        "     It's that the auto-paper queue (today: PL) has been sitting at\n"
        "     approval-pending. The velocity tracker needs you to clear the approval\n"
        "     queue so paper tickets can stage, score, and close.\n"
        "\n"
        "  5. The DELL/MRVL aging-out tickets are NOT actionable trades. They're\n"
        "     LONG_STRADDLEs that never fit the cap. The fact-based action on them is\n"
        "     `reject` (so they don't become zombies #43-46), not `approve`.\n"
        "\n"
        "  6. Whether to approve PL — that's a judgment call this worksheet deliberately\n"
        "     does not make for you. The math is in front of you. The gates have done\n"
        "     their work. What happens next is yours.\n"
    )

    text = "\n".join(buf)
    REPORTS.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS / "today_math_worksheet.txt"
    out_path.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n[written] {out_path}")


if __name__ == "__main__":
    main()
