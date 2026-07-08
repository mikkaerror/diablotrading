#!/usr/bin/env python3
"""Defined-risk short-premium study (research-only).

The buy-premium program is a KILL (see docs/DECISIVE_MOVE_EDGE_KILL_2026-07-07.md):
in this universe realized move averaged 21.9% vs 32.5% implied, so the variance
risk premium runs against the buyer -- which means it runs *for* a defined-risk
seller. This module tests, honestly, whether selling premium with a capped tail
shows a real, name-diversified edge on the desk's own 100-record expected-move
ledger.

Model
-----
Each closed long-vol record carries `moveRatio = realizedAbsMovePct / impliedMovePct`.
A short-straddle seller (credit normalized to 1R) earns, per event:

    rawSellR = 1 - moveRatio                     # >0 when realized < implied
    netSellR = rawSellR - FRICTION_R             # charge round-trip spread
    cappedSellR = max(-lossCapR, netSellR)       # protective wings cap the tail

We sweep `lossCapR` because tighter wings cap the tail but also cost credit. This
backward study can bound the tail effect but CANNOT price the credit given up for
protection -- only the forward paper test with real chains can. So a tighter cap
here *overstates* the edge; treat the widest cap as the conservative read.

The decisive checks (same rigor that killed the buy side):
  - friction-charged
  - clustered by name (cluster bootstrap CI, resample names not events)
  - leave-the-two-best-names-out (the buy side died here; does the sell side?)
  - tail concentration (how much of the loss is in the worst 2 names)

Boundary: research-only. No authority/gate/risk-constant change. Renders a verdict
string but promotes nothing.
"""

from __future__ import annotations

import json
import os
import random
import statistics as st
from collections import defaultdict
from datetime import date
from typing import Any, Optional

SHORT_PREMIUM_STAGE = "short-premium-study-research-only"

FRICTION_R = 0.10                     # round-trip spread as fraction of credit
LOSS_CAPS_R = (3.0, 2.0, 1.5)         # protective-wing tail caps to sweep
CONSERVATIVE_CAP_R = 3.0              # the read we trust (widest wings, least modeled credit loss)
LEDGER_FILE = os.environ.get(
    "INFERNO_EXPECTED_MOVE_FILE", "data/inferno_expected_move_ledger.json"
)
PAPER_LEDGER_FILE = os.environ.get(
    "INFERNO_PAPER_LEDGER_FILE", "data/inferno_paper_execution_ledger.json"
)

# Confirm/kill thresholds for the sell-side lead (pre-registered; see the memo).
CONFIRM_MIN_MEAN_R = 0.15            # conservative-cap mean net-R, ex-two-best
CONFIRM_MIN_NAMES = 12              # distinct names required
CONFIRM_MIN_CI_LOW = 0.0           # cluster-bootstrap 95% CI low > 0

# Forward campaign thresholds from docs/SHORT_PREMIUM_PREREG_2026-07-07.md.
FORWARD_MIN_NAMES = 40
FORWARD_MIN_EVENTS = 60
FORWARD_CONFIRM_MIN_EX_BEST_R = 0.10
FORWARD_CONFIRM_MIN_CI_LOW = 0.0
FORWARD_MAX_WORST_TWO_LOSS_SHARE_PCT = 40.0
FORWARD_MAX_NAME_RISK_SHARE_PCT = 4.0
FORWARD_TIMEBOX_END = date(2026, 10, 5)
SHORT_PREMIUM_DEFINED_ARM = "SHORT_PREMIUM_DEFINED"


def _find_records(obj: Any, best=None) -> list:
    best = best if best is not None else [None]
    if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "impliedMovePct" in obj[0]:
        if best[0] is None or len(obj) > len(best[0]):
            best[0] = obj
    if isinstance(obj, dict):
        for v in obj.values():
            _find_records(v, best)
    if isinstance(obj, list):
        for v in obj:
            _find_records(v, best)
    return best[0] or []


def _move_ratio(r: dict) -> Optional[float]:
    mr = r.get("moveRatio")
    if mr is not None:
        return mr
    im = r.get("impliedMovePct")
    rm = r.get("realizedAbsMovePct")
    return (rm / im) if im else None


def _sell_r(mr: float, loss_cap_r: float) -> float:
    raw = 1.0 - mr
    net = raw - FRICTION_R
    return max(-loss_cap_r, net)


def _cluster_bootstrap_ci(by_name: dict[str, list], iters: int = 4000,
                          seed: int = 7) -> tuple[float, float]:
    """Resample NAMES with replacement (not events) -> honest CI under clustering."""
    rng = random.Random(seed)
    names = list(by_name.keys())
    if len(names) < 2:
        return (float("nan"), float("nan"))
    means = []
    for _ in range(iters):
        picks = [rng.choice(names) for _ in names]
        vals = [x for nm in picks for x in by_name[nm]]
        if vals:
            means.append(st.mean(vals))
    means.sort()
    lo = means[int(0.025 * len(means))]
    hi = means[int(0.975 * len(means))]
    return (round(lo, 3), round(hi, 3))


def _num(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value or "").strip().replace("$", "").replace(",", "").replace("%", "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _txt(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return _txt(value).upper()


def _strategy_plan(ticket: dict[str, Any]) -> dict[str, Any]:
    return ticket.get("strikePlan") if isinstance(ticket.get("strikePlan"), dict) else ticket


def _max_loss(ticket: dict[str, Any]) -> float:
    plan = _strategy_plan(ticket)
    metrics = ((ticket.get("riskVerdict") or {}).get("metrics") or {})
    for value in (
        metrics.get("maxLossDollars"),
        plan.get("estimatedMaxLoss"),
        ticket.get("estimatedMaxLoss"),
        ticket.get("maxLossDollars"),
    ):
        parsed = _num(value)
        if parsed and parsed > 0:
            return parsed
    return 0.0


def _credit_dollars(ticket: dict[str, Any]) -> float | None:
    plan = _strategy_plan(ticket)
    for value in (plan.get("estimatedCredit"), ticket.get("entryLimit"), ticket.get("entryCredit")):
        parsed = _num(value)
        if parsed and parsed > 0:
            return round(parsed * 100.0, 4)
    return None


def _is_short_premium_defined(ticket: dict[str, Any]) -> bool:
    labels = {
        _norm(ticket.get("arm")),
        _norm(ticket.get("campaignArm")),
        _norm(ticket.get("strategy")),
        _norm(ticket.get("paperVariantFamily")),
        _norm((_strategy_plan(ticket)).get("strategy")),
        _norm((_strategy_plan(ticket)).get("variantFamily")),
    }
    return SHORT_PREMIUM_DEFINED_ARM in labels or bool(ticket.get("shortPremiumDefined"))


def forward_record(ticket: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one closed forward short-premium paper record."""
    if not _is_short_premium_defined(ticket):
        return None
    outcome = ticket.get("outcome") or {}
    if _txt(outcome.get("status")).lower() != "closed":
        return None
    max_loss = _max_loss(ticket)
    if max_loss <= 0:
        return None
    direct_r = _num(outcome.get("estimatedReturnOnRisk"))
    pnl = _num(outcome.get("estimatedPnl"))
    net_r = direct_r if direct_r is not None else (pnl / max_loss if pnl is not None else None)
    if net_r is None:
        return None
    event_id = _txt(ticket.get("eventId"))
    ticker = _norm(ticket.get("ticker"))
    if not event_id and ticker:
        event_date = _txt(ticket.get("earningsDate") or ticket.get("nextEarnings") or ticket.get("reportDate"))
        event_id = f"{ticker}|{event_date or 'unknown-event'}"
    return {
        "ticketId": ticket.get("ticketId"),
        "ticker": ticker,
        "eventId": event_id,
        "strategy": _norm(ticket.get("strategy") or (_strategy_plan(ticket)).get("strategy")),
        "arm": SHORT_PREMIUM_DEFINED_ARM,
        "entryDate": ticket.get("tradeDate") or ticket.get("createdAt"),
        "reviewedAt": outcome.get("reviewedAt"),
        "netR": round(net_r, 6),
        "pnlDollars": pnl,
        "maxLossDollars": max_loss,
        "creditCollectedDollars": _credit_dollars(ticket),
        "estimatedSpreadFrictionDollars": _num(ticket.get("estimatedTotalSpreadFrictionDollars"), 0.0) or 0.0,
        "frictionModel": ticket.get("frictionModel") or ticket.get("paperFillFrictionModel"),
        "impliedMovePct": _num(ticket.get("impliedMovePct") or (_strategy_plan(ticket)).get("impliedMovePct")),
        "realizedAbsMovePct": _num(outcome.get("realizedAbsMovePct")),
        "definedRisk": True,
    }


def load_forward_records(path: str = PAPER_LEDGER_FILE) -> list[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except FileNotFoundError:
        return []
    records: list[dict[str, Any]] = []
    for ticket in payload.get("items") or []:
        if not isinstance(ticket, dict):
            continue
        record = forward_record(ticket)
        if record:
            records.append(record)
    return records


def _loss_share_pct(name_sums: dict[str, float], total: float) -> float | None:
    losses = {name: value for name, value in name_sums.items() if value < 0}
    total_loss = abs(sum(losses.values()))
    if total_loss <= 0:
        return 0.0
    worst_two_loss = abs(sum(value for _, value in sorted(losses.items(), key=lambda item: item[1])[:2]))
    return round(100.0 * worst_two_loss / total_loss, 1)


def forward_summary(records: list[dict[str, Any]], *, today: date | None = None) -> dict[str, Any]:
    """Score forward friction-real short-premium paper evidence against prereg gates."""
    today = today or date.today()
    by_name: dict[str, list[float]] = defaultdict(list)
    by_event: dict[str, dict[str, Any]] = {}
    for record in records:
        event_id = _txt(record.get("eventId")) or f"{record.get('ticker')}|{record.get('ticketId')}"
        if event_id in by_event:
            continue
        by_event[event_id] = record
        by_name[_norm(record.get("ticker"))].append(float(record["netR"]))

    values = [float(record["netR"]) for record in by_event.values()]
    name_sums = {name: sum(items) for name, items in by_name.items()}
    name_risk: dict[str, float] = defaultdict(float)
    for record in by_event.values():
        name_risk[_norm(record.get("ticker"))] += float(record.get("maxLossDollars") or 0.0)
    total_risk = sum(name_risk.values())
    max_name_risk_share = (
        round(100.0 * max(name_risk.values()) / total_risk, 1)
        if total_risk > 0 and name_risk
        else None
    )
    best2 = sorted(name_sums, key=lambda name: name_sums[name], reverse=True)[:2]
    ex_best = [value for name, items in by_name.items() if name not in best2 for value in items]
    ci = _cluster_bootstrap_ci(by_name) if by_name else (float("nan"), float("nan"))
    worst_loss_share = _loss_share_pct(name_sums, sum(values)) if values else None
    max_single_loss = min(values) if values else None
    mean_ex_best = round(st.mean(ex_best), 3) if ex_best else None
    distinct_names = len(by_name)
    distinct_events = len(by_event)
    timebox_expired = today > FORWARD_TIMEBOX_END

    confirm = (
        distinct_names >= FORWARD_MIN_NAMES
        and distinct_events >= FORWARD_MIN_EVENTS
        and mean_ex_best is not None
        and mean_ex_best > FORWARD_CONFIRM_MIN_EX_BEST_R
        and ci[0] > FORWARD_CONFIRM_MIN_CI_LOW
        and (worst_loss_share is not None and worst_loss_share < FORWARD_MAX_WORST_TWO_LOSS_SHARE_PCT)
        and (max_name_risk_share is not None and max_name_risk_share <= FORWARD_MAX_NAME_RISK_SHARE_PCT)
    )
    kill_reasons: list[str] = []
    if distinct_events >= FORWARD_MIN_EVENTS and ci[0] <= FORWARD_CONFIRM_MIN_CI_LOW:
        kill_reasons.append("cluster-ci-crosses-zero")
    if distinct_events >= FORWARD_MIN_EVENTS and mean_ex_best is not None and mean_ex_best <= 0:
        kill_reasons.append("mean-ex-two-best-nonpositive")
    if (
        distinct_names >= FORWARD_MIN_NAMES
        and worst_loss_share is not None
        and worst_loss_share >= FORWARD_MAX_WORST_TWO_LOSS_SHARE_PCT
    ):
        kill_reasons.append("worst-two-loss-share-too-high")
    if (
        distinct_names >= FORWARD_MIN_NAMES
        and max_name_risk_share is not None
        and max_name_risk_share > FORWARD_MAX_NAME_RISK_SHARE_PCT
    ):
        kill_reasons.append("single-name-risk-share-too-high")
    if timebox_expired and (distinct_names < FORWARD_MIN_NAMES or distinct_events < FORWARD_MIN_EVENTS):
        kill_reasons.append("timebox-expired-without-breadth")

    if confirm:
        verdict = "forward-short-premium-confirmed"
    elif kill_reasons:
        verdict = "forward-short-premium-killed"
    elif distinct_events:
        verdict = "forward-short-premium-collecting"
    else:
        verdict = "forward-awaiting-short-premium-records"

    return {
        "verdict": verdict,
        "records": len(records),
        "distinctEvents": distinct_events,
        "distinctNames": distinct_names,
        "meanNetR": round(st.mean(values), 3) if values else None,
        "medianNetR": round(st.median(values), 3) if values else None,
        "meanNetR_exTwoBest": mean_ex_best,
        "clusterCI95": ci,
        "winRatePct": round(100.0 * sum(1 for value in values if value > 0) / len(values), 1) if values else None,
        "namesNetPositive": sum(1 for value in name_sums.values() if value > 0),
        "twoBestNames": best2,
        "twoWorstNames": sorted(name_sums, key=lambda name: name_sums[name])[:2],
        "worstTwoShareOfLossPct": worst_loss_share,
        "maxNameRiskSharePct": max_name_risk_share,
        "maxSingleEventLossR": round(max_single_loss, 3) if max_single_loss is not None else None,
        "killReasons": kill_reasons,
        "confirmThresholds": {
            "distinctNames": FORWARD_MIN_NAMES,
            "distinctEvents": FORWARD_MIN_EVENTS,
            "meanNetR_exTwoBest": FORWARD_CONFIRM_MIN_EX_BEST_R,
            "clusterCI95Low": FORWARD_CONFIRM_MIN_CI_LOW,
            "worstTwoShareOfLossPctMax": FORWARD_MAX_WORST_TWO_LOSS_SHARE_PCT,
            "maxNameRiskSharePct": FORWARD_MAX_NAME_RISK_SHARE_PCT,
        },
        "timeboxEnd": FORWARD_TIMEBOX_END.isoformat(),
        "promotionEligible": False,
        "researchOnly": True,
    }


def data_integrity(recs: list) -> dict[str, Any]:
    """Detect the two defects found on 2026-07-07 in the realized-move column:
    pseudo-replication (same earnings event sampled many times -> realized value
    constant within a name) and implausible earnings-move magnitudes."""
    by_name: dict[str, set] = defaultdict(set)
    for r in recs:
        rm = r.get("realizedAbsMovePct")
        if rm is not None:
            by_name[r.get("ticker")].add(round(rm, 2))
    n_records = sum(1 for r in recs if r.get("realizedAbsMovePct") is not None)
    n_distinct = sum(len(v) for v in by_name.values())
    implausible = sum(
        1 for r in recs
        if (r.get("realizedAbsMovePct") or 0) > 40.0  # >40% is not an earnings-day move
    )
    # names whose realized value never changes across multiple records
    frozen = [nm for nm, v in by_name.items()
              if len(v) == 1 and sum(1 for r in recs if r.get("ticker") == nm) > 2]
    replication_ratio = (n_records / n_distinct) if n_distinct else float("inf")
    reliable = (
        replication_ratio <= 1.5
        and implausible == 0
        and not frozen
    )
    return {
        "records": n_records,
        "distinctRealizedValues": n_distinct,
        "effectiveObservations": n_distinct,
        "replicationRatio": round(replication_ratio, 2),
        "implausibleMagnitudeRecords": implausible,
        "frozenRealizedNames": frozen,
        "reliable": reliable,
    }


def build_study(path: str = LEDGER_FILE, *, paper_ledger_path: str = PAPER_LEDGER_FILE) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        recs = _find_records(json.load(fh))

    integrity = data_integrity(recs)
    forward_records = load_forward_records(paper_ledger_path)
    forward = forward_summary(forward_records)

    ratios = [(r.get("ticker"), _move_ratio(r)) for r in recs]
    ratios = [(t, m) for t, m in ratios if m is not None]

    caps: dict[str, Any] = {}
    for cap in LOSS_CAPS_R:
        by_name: dict[str, list] = defaultdict(list)
        allv: list[float] = []
        for tkr, mr in ratios:
            v = _sell_r(mr, cap)
            by_name[tkr].append(v)
            allv.append(v)
        name_sums = {nm: sum(v) for nm, v in by_name.items()}
        best2 = sorted(name_sums, key=lambda n: name_sums[n], reverse=True)[:2]
        worst2 = sorted(name_sums, key=lambda n: name_sums[n])[:2]
        ex_best = [x for nm, vs in by_name.items() if nm not in best2 for x in vs]
        ci = _cluster_bootstrap_ci(by_name)
        total = sum(allv)
        worst2_sum = sum(name_sums[n] for n in worst2)
        caps[f"{cap:.1f}"] = {
            "lossCapR": cap,
            "n": len(allv),
            "distinctNames": len(by_name),
            "winRatePct": round(100 * sum(1 for x in allv if x > 0) / len(allv), 1),
            "meanR": round(st.mean(allv), 3),
            "medianR": round(st.median(allv), 3),
            "minR": round(min(allv), 3),
            "clusterCI95": ci,
            "namesNetPositive": sum(1 for s in name_sums.values() if s > 0),
            "meanR_exTwoBest": round(st.mean(ex_best), 3) if ex_best else None,
            "twoBestNames": best2,
            "twoWorstNames": worst2,
            "worstTwoShareOfLossPct": (
                round(100 * worst2_sum / total, 0) if total else None
            ),
        }

    cons = caps[f"{CONSERVATIVE_CAP_R:.1f}"]
    # Verdict on the conservative (widest-wing) read, ex-two-best, clustered.
    ex_best = cons["meanR_exTwoBest"]
    ci_low = cons["clusterCI95"][0]
    names = cons["distinctNames"]
    if not integrity["reliable"]:
        # The backward realized-move column is corrupted (pseudo-replication and/or
        # implausible magnitudes). No backward verdict can be trusted; only the
        # forward, per-event, friction-real paper test can decide. See
        # docs/DATA_INTEGRITY_REALIZED_MOVE_2026-07-07.md.
        verdict = "data-unreliable-cannot-conclude-backward"
    elif (ex_best is not None and ex_best >= CONFIRM_MIN_MEAN_R
            and names >= CONFIRM_MIN_NAMES and ci_low > CONFIRM_MIN_CI_LOW):
        verdict = "sell-side-edge-supported-backward"
    elif ex_best is not None and ex_best > 0:
        verdict = "promising-unproven-needs-forward-test"
    else:
        verdict = "sell-side-negative-backward"

    return {
        "stage": SHORT_PREMIUM_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "ledger": path,
        "friction_R": FRICTION_R,
        "conservativeCapR": CONSERVATIVE_CAP_R,
        "dataIntegrity": integrity,
        "forwardCampaign": forward,
        "forwardRecords": forward_records,
        "caps": caps,
        "verdict": verdict,
        "caveats": [
            "Backward study; friction-charged but credit-cost of protective wings "
            "NOT modeled -> tighter caps OVERSTATE the edge.",
            "Only ~18 names / 100 events; cluster CI is wide.",
            "Forward paper test with real condor pricing is the deciding evidence.",
        ],
        "citations": [
            "data/inferno_expected_move_ledger.json",
            "docs/DECISIVE_MOVE_EDGE_KILL_2026-07-07.md",
            "docs/SHORT_PREMIUM_PREREG_2026-07-07.md",
        ],
    }


def study_text(p: dict[str, Any]) -> str:
    L = []
    L.append("Inferno Defined-Risk Short-Premium Study (research-only)")
    L.append(f"Ledger: {p['ledger']} | friction {p['friction_R']}R/trade")
    L.append(f"VERDICT: {p['verdict']}")
    di = p.get("dataIntegrity", {})
    if not di.get("reliable", True):
        L.append(
            f"** DATA INTEGRITY FAIL: {di.get('records')} records but only "
            f"{di.get('distinctRealizedValues')} distinct realized values "
            f"(replication {di.get('replicationRatio')}x); "
            f"{di.get('implausibleMagnitudeRecords')} records >40% 'move'; "
            f"frozen names: {','.join(di.get('frozenRealizedNames', [])) or 'none'}. "
            f"Numbers below are NOT trustworthy — forward test only. **"
        )
    L.append("")
    L.append(f"{'lossCap':>8}{'n':>5}{'names':>7}{'win%':>7}{'mean':>8}{'median':>8}"
             f"{'min':>7}{'CI95':>16}{'exBest2':>9}")
    for key in sorted(p["caps"], key=lambda k: -float(k)):
        c = p["caps"][key]
        ci = f"[{c['clusterCI95'][0]},{c['clusterCI95'][1]}]"
        L.append(
            f"{c['lossCapR']:>8.1f}{c['n']:>5}{c['distinctNames']:>7}{c['winRatePct']:>7}"
            f"{c['meanR']:>8.2f}{c['medianR']:>8.2f}{c['minR']:>7.1f}{ci:>16}"
            f"{(c['meanR_exTwoBest'] if c['meanR_exTwoBest'] is not None else 0):>9.2f}"
        )
    cons = p["caps"][f"{p['conservativeCapR']:.1f}"]
    L.append("")
    L.append(f"Conservative read (widest {p['conservativeCapR']:.0f}R cap): "
             f"mean {cons['meanR']}R, median {cons['medianR']}R, "
             f"{cons['namesNetPositive']}/{cons['distinctNames']} names net-positive.")
    L.append(f"Two best names: {cons['twoBestNames']} | two worst (the tail): "
             f"{cons['twoWorstNames']} carry {cons['worstTwoShareOfLossPct']}% of net.")
    L.append(f"Ex-two-best, clustered: mean {cons['meanR_exTwoBest']}R, "
             f"95% CI {cons['clusterCI95']}.")
    L.append("")
    fwd = p.get("forwardCampaign") or {}
    L.append("Forward SHORT_PREMIUM_DEFINED campaign:")
    L.append(f"- verdict: {fwd.get('verdict')}")
    L.append(
        f"- evidence: {fwd.get('distinctEvents', 0)}/"
        f"{(fwd.get('confirmThresholds') or {}).get('distinctEvents')} events, "
        f"{fwd.get('distinctNames', 0)}/"
        f"{(fwd.get('confirmThresholds') or {}).get('distinctNames')} names"
    )
    L.append(
        f"- mean net-R ex two best: {fwd.get('meanNetR_exTwoBest')} | "
        f"cluster CI95: {fwd.get('clusterCI95')} | "
        f"worst-2 loss share: {fwd.get('worstTwoShareOfLossPct')}% | "
        f"max name risk share: {fwd.get('maxNameRiskSharePct')}%"
    )
    if fwd.get("killReasons"):
        L.append(f"- kill reasons: {', '.join(fwd.get('killReasons') or [])}")
    L.append("")
    for c in p["caveats"]:
        L.append(f"- {c}")
    L.append("Research-only. Promotes nothing. Authority unchanged.")
    return "\n".join(L)


def save_study(p: dict[str, Any]) -> None:
    os.makedirs("data", exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    with open("data/inferno_short_premium_study.json", "w", encoding="utf-8") as fh:
        json.dump(p, fh, indent=2)
    with open("reports/short_premium_study_latest.txt", "w", encoding="utf-8") as fh:
        fh.write(study_text(p))


def main(argv: Optional[list] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    ap.add_argument("--file", default=LEDGER_FILE)
    ap.add_argument("--paper-ledger", default=PAPER_LEDGER_FILE)
    args = ap.parse_args(argv)
    p = build_study(args.file, paper_ledger_path=args.paper_ledger)
    print(study_text(p))
    if args.command == "run":
        save_study(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
