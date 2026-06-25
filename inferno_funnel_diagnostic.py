"""Inferno Funnel Diagnostic — why is the desk producing 0 candidates?

The cap-fit audit (BACKLOG #2, commit bd5ba6f) showed 100% of the 146
universe tickers fit *some* structure. But the live funnel produces 0
candidates daily. The director verdict reads `no-viable-paper-tests`,
the approval queue is empty, and the paper_blocker_swarm shows
`no-blocked-candidates` because nothing arrives to be diagnosed.

This module walks the 146 universe rows and surfaces three measurable
gaps:

  1. Strategy-family bias: how many setupRec values are premium-buying
     (the family the desk's own ledger and academic VRP literature both
     say has structurally negative expectancy)?
  2. Missed credit-spread setups: how many tickers have IV-rank > 50
     (Carr-Wu compensated premium-selling) but get a debit setupRec?
  3. Missed wheel candidates: how many cheap conviction-tier names
     could support cash-secured-put income generation but aren't being
     scanned?

Stage:        funnel-diagnostic-research-only
Promotable:   False
Authority:    unchanged

The output is for codex's strategy lab and the operator. It does NOT
mutate any setup, gate, or queue.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
REPORTS = ROOT / "reports"

SNAPSHOT_FILE = DATA / "latest_snapshot.json"
DIRECTOR_FILE = DATA / "inferno_paper_test_director.json"
APPROVAL_QUEUE_FILE = DATA / "inferno_approval_queue.json"
OUTPUT_JSON = DATA / "inferno_funnel_diagnostic.json"
OUTPUT_TEXT = REPORTS / "funnel_diagnostic_latest.txt"

STAGE = "funnel-diagnostic-research-only"

# Strategy classification: premium-buying vs premium-selling.
PREMIUM_BUY_SETUPS = {
    "Straddle",
    "Strangle",
    "Vertical Call",
    "Vertical Put",
    "Long Call",
    "Long Put",
}
PREMIUM_SELL_SETUPS = {
    "Iron Condor",
    "Put Credit",
    "Call Credit",
    "Credit Spread",
    "Wheel",
    "Cash-Secured Put",
}


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _classify_setup(setup_rec: str) -> str:
    s = (setup_rec or "").strip()
    if s in PREMIUM_BUY_SETUPS:
        return "premium-buy"
    if s in PREMIUM_SELL_SETUPS:
        return "premium-sell"
    if s.lower() == "avoid":
        return "avoid"
    if not s:
        return "no-setup"
    return "other"


def build_diagnostic() -> dict:
    snap = _load_json(SNAPSHOT_FILE)
    director = _load_json(DIRECTOR_FILE)
    queue = _load_json(APPROVAL_QUEUE_FILE)

    rows = snap.get("rows") or []
    funnel_state = {
        "universeSize": len(rows),
        "directorVerdict": director.get("verdict"),
        "directorCounts": director.get("counts") or {},
        "approvalQueueCount": queue.get("count") or 0,
    }

    setups = Counter()
    families = Counter()
    credit_spread_candidates = []
    wheel_candidates = []
    sweet_spot_candidates = []

    for r in rows:
        if not isinstance(r, dict):
            continue
        ticker = (r.get("ticker") or "").strip().upper()
        setup_rec = r.get("setupRec") or ""
        price = r.get("price")
        iv_rank = r.get("ivRank")
        atr_pct = r.get("atrPercent")
        dte = r.get("daysUntilEarnings")
        signal = r.get("signalTrigger")

        setups[setup_rec] += 1
        families[_classify_setup(setup_rec)] += 1

        if not isinstance(price, (int, float)):
            continue
        if not isinstance(iv_rank, (int, float)):
            continue

        # Premium-selling candidate: IV rank > 50 + no near-term event + price < $100
        no_nearby_earnings = dte is None or dte > 14
        if iv_rank > 50 and no_nearby_earnings and price < 100:
            credit_spread_candidates.append(
                {
                    "ticker": ticker,
                    "price": price,
                    "ivRank": iv_rank,
                    "dte_earn": dte,
                    "currentSetupRec": setup_rec,
                    "missedFamily": "credit-spread / iron-condor",
                }
            )

        # Wheel candidate: cheap stock + decent IV + signal
        if price < 30 and iv_rank > 30 and signal:
            wheel_candidates.append(
                {
                    "ticker": ticker,
                    "price": price,
                    "ivRank": iv_rank,
                    "dte_earn": dte,
                    "currentSetupRec": setup_rec,
                    "missedFamily": "wheel / cash-secured-put",
                }
            )

        # Sweet-spot debit: 7-14 DTE earnings, ATR%>2 (the only positive
        # cohort in the desk's net-R ledger per codex's DTE policy analysis).
        if (
            dte is not None
            and 7 <= dte <= 14
            and isinstance(atr_pct, (int, float))
            and atr_pct > 2
        ):
            sweet_spot_candidates.append(
                {
                    "ticker": ticker,
                    "price": price,
                    "ivRank": iv_rank,
                    "dte_earn": dte,
                    "atrPercent": atr_pct,
                    "currentSetupRec": setup_rec,
                    "alignedFamily": "long-straddle-7-14-dte",
                }
            )

    # Bias ratio: premium-buying setups vs premium-selling.
    pb = families.get("premium-buy", 0)
    ps = families.get("premium-sell", 0)
    bias_ratio = (pb / ps) if ps else None
    if pb >= 5 and ps == 0:
        bias_verdict = "premium-buy-monoculture"
    elif bias_ratio and bias_ratio > 5:
        bias_verdict = "premium-buy-heavily-weighted"
    elif bias_ratio and bias_ratio > 2:
        bias_verdict = "premium-buy-tilted"
    else:
        bias_verdict = "balanced"

    payload = {
        "generatedAt": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "stage": STAGE,
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "funnelState": funnel_state,
        "setupRecDistribution": dict(setups.most_common()),
        "familyDistribution": dict(families),
        "biasRatio": bias_ratio,
        "biasVerdict": bias_verdict,
        "creditSpreadCandidates": credit_spread_candidates,
        "wheelCandidates": wheel_candidates,
        "sweetSpotCandidates": sweet_spot_candidates,
        "counts": {
            "creditSpread": len(credit_spread_candidates),
            "wheel": len(wheel_candidates),
            "sweetSpot": len(sweet_spot_candidates),
        },
        "citations": [
            "Carr & Wu (2009) Variance Risk Premiums — negative VRP on equity indices",
            "Codex net-R ledger: Shadow Long Straddle 7-14 DTE n=36, win 56%, netR +0.86",
            "Codex net-R ledger: Shadow Vertical Debit n=49, win 39%, netR -0.38",
            "BACKLOG #2 cap-fit audit: 100% credit-spread fit on universe; 18% straddle fit",
        ],
        "reminders": [
            "research-only; this module proposes nothing for staging",
            "candidate lists are pattern matches, not edge proofs",
            "the operator and codex decide which families to scan; this only surfaces gaps",
        ],
    }
    return payload


def render_text(payload: dict) -> str:
    fs = payload["funnelState"]
    counts = payload["counts"]
    lines = [
        "Inferno Funnel Diagnostic",
        "",
        f"Generated: {payload.get('generatedAt','?')}",
        f"Universe size: {fs.get('universeSize',0)}",
        f"Director verdict: {fs.get('directorVerdict','?')}",
        f"Approval queue count: {fs.get('approvalQueueCount',0)}",
        "",
        "Strategy bias:",
        f"  Verdict: {payload.get('biasVerdict','?')}",
        f"  Bias ratio (premium-buy / premium-sell): {payload.get('biasRatio','?')}",
        f"  Family distribution: {payload.get('familyDistribution','?')}",
        "",
        "Top setupRec values:",
    ]
    for s, c in list(payload.get("setupRecDistribution", {}).items())[:10]:
        s_label = f"'{s}'" if s else "(empty)"
        lines.append(f"  {s_label}: {c}")
    lines.append("")
    lines.append(
        f"Credit-spread candidates (IVR>50, no nearby earnings, price<$100): {counts['creditSpread']}"
    )
    for r in payload.get("creditSpreadCandidates", [])[:10]:
        lines.append(
            f"  {r['ticker']:<6} ${r['price']:>7.2f}  IVR={r['ivRank']:>5.1f}  "
            f"dte_earn={r['dte_earn']}  currentSetup='{r['currentSetupRec']}'"
        )
    lines.append("")
    lines.append(
        f"Wheel candidates (cheap + IVR>30 + signal): {counts['wheel']}"
    )
    for r in payload.get("wheelCandidates", [])[:10]:
        lines.append(
            f"  {r['ticker']:<6} ${r['price']:>7.2f}  IVR={r['ivRank']:>5.1f}  "
            f"dte_earn={r['dte_earn']}  currentSetup='{r['currentSetupRec']}'"
        )
    lines.append("")
    lines.append(
        f"Sweet-spot debit candidates (7-14 DTE earnings, ATR%>2): {counts['sweetSpot']}"
    )
    for r in payload.get("sweetSpotCandidates", [])[:10]:
        lines.append(
            f"  {r['ticker']:<6} ${r['price']:>7.2f}  IVR={r['ivRank']:>5.1f}  "
            f"dte_earn={r['dte_earn']}  ATR%={r['atrPercent']:.2f}  "
            f"currentSetup='{r['currentSetupRec']}'"
        )
    lines.append("")
    lines.append("Reminders:")
    for r in payload.get("reminders", []):
        lines.append(f"  - {r}")
    return "\n".join(lines) + "\n"


def save_diagnostic(payload: dict | None = None) -> dict:
    if payload is None:
        payload = build_diagnostic()
    DATA.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    OUTPUT_TEXT.write_text(render_text(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Funnel diagnostic")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("run", help="Build the diagnostic and write artifacts")
    sub.add_parser("status", help="Print the latest report")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.cmd == "status":
        if OUTPUT_TEXT.exists():
            print(OUTPUT_TEXT.read_text(encoding="utf-8"))
        else:
            print("No diagnostic on disk. Run with no args to build one.")
        return 0
    payload = save_diagnostic()
    print(render_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
