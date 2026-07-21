#!/usr/bin/env python3
"""AI / data-center basket — position-sizing recommender (research-only).

Turns the locked momentum lane (docs/MOMENTUM_VS_BUYLOW_VERDICT_2026-07-15.md)
into target weights, with the two risk controls this book actually needs:

  1. Trend gate      — AVOID names (below their 200-day) get weight ZERO. The
                       verdict was explicit: weakness is a stand-aside, not a
                       discount. This module will never size into a broken name.
  2. Concentration   — a single-name cap and a FACTOR-BUCKET cap. The basket is
                       ~73% one AI-capex hardware factor; the bucket cap is what
                       stops that from silently becoming the whole portfolio.

Sizing logic (transparent by design):
    base weight  ∝  composite RS score (0-100)  ×  tag multiplier
      LEADER 1.00 · HOLD 0.70 · REDUCE 0.35 · AVOID 0.00
    then: normalize → apply single-name cap → apply bucket cap → re-check caps
    anything that cannot be allocated without breaching a cap becomes CASH
    (explicitly held, never force-fed into the remaining names).

Actions are produced against your CURRENT weights if you supply them:
    EXIT  — target 0, currently held (trend broken)
    TRIM  — target materially below current
    ADD   — target materially above current
    HOLD  — within tolerance

Boundary: research-only, decision-support. This module RECOMMENDS weights; it
sizes nothing, places no orders, and changes no authority. The operator decides.
Not financial advice.

Lane note: sizing is adjacent to the capital-deployment lane. This is built as an
opt-in recommender (the pattern inferno_capital_scaling.py established) and does
NOT read or mutate risk constants, authority flags, or the broker path.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from inferno_ai_basket_config import BASKET as CATS
from inferno_ai_basket_config import factor_bucket, normalize_symbol
from inferno_io import atomic_write_json, atomic_write_text

ROOT = Path(__file__).resolve().parent
OUT_JSON = ROOT / "data" / "ai_basket_sizing.json"
OUT_TXT = ROOT / "reports" / "ai_basket_sizing_latest.txt"

SIZING_STAGE = "ai-basket-sizing-research-only"

# Defaults — operator-tunable via CLI, never read from risk constants.
MAX_NAME_WEIGHT = 0.08      # no single position above 8% of the book
MAX_BUCKET_WEIGHT = 0.60    # no factor bucket above 60% (vs ~73% today)
MIN_NAME_WEIGHT = 0.015     # below 1.5% is dust: not worth the ticket or the attention
ACTION_TOLERANCE = 0.01     # 1 percentage point = noise, call it HOLD

TAG_MULTIPLIER = {"LEADER": 1.00, "HOLD": 0.70, "REDUCE": 0.35, "AVOID": 0.00}


def _normalize(w: dict[str, float]) -> dict[str, float]:
    total = sum(w.values())
    if total <= 0:
        return {k: 0.0 for k in w}
    return {k: v / total for k, v in w.items()}


def _apply_name_cap(w: dict[str, float], caps: dict[str, float]) -> dict[str, float]:
    """Water-fill against PER-NAME ceilings.

    Ceilings are quality-scaled (see `build`), so a REDUCE name can never be
    inflated to a LEADER's weight just because diversification freed up room.
    Weight that no eligible name is allowed to hold simply stays unallocated —
    it becomes cash.
    """
    for _ in range(200):
        over = {k: v for k, v in w.items() if v > caps.get(k, 1.0) + 1e-12}
        if not over:
            return w
        excess = sum(v - caps.get(k, 1.0) for k, v in over.items())
        for k in over:
            w[k] = caps.get(k, 1.0)
        under = {k: v for k, v in w.items()
                 if v > 0 and v < caps.get(k, 1.0) - 1e-12}
        under_sum = sum(under.values())
        if under_sum <= 1e-12 or excess <= 1e-12:
            break  # nobody may hold it -> residual becomes cash
        for k in under:
            w[k] = under[k] + excess * under[k] / under_sum
    return w


def _apply_bucket_cap(w: dict[str, float], cap: float,
                      bucket_of: Callable[[str], str]) -> dict[str, float]:
    """Scale down any factor bucket over `cap`; offer the freed weight to others."""
    for _ in range(50):
        totals: dict[str, float] = {}
        for k, v in w.items():
            totals[bucket_of(k)] = totals.get(bucket_of(k), 0.0) + v
        over = {b: t for b, t in totals.items() if t > cap + 1e-12}
        if not over:
            return w
        freed = 0.0
        for b, t in over.items():
            scale = cap / t if t > 0 else 0.0
            for k in list(w):
                if bucket_of(k) == b:
                    freed += w[k] * (1.0 - scale)
                    w[k] *= scale
        absorbers = [k for k in w if bucket_of(k) not in over and w[k] > 0]
        absorb_sum = sum(w[k] for k in absorbers)
        if absorb_sum <= 1e-12 or freed <= 1e-12:
            break  # other buckets cannot absorb -> residual becomes cash
        for k in absorbers:
            w[k] += freed * w[k] / absorb_sum
    return w


def solve_weights(scores: dict[str, float], *, caps: dict[str, float],
                  max_bucket: float = MAX_BUCKET_WEIGHT,
                  bucket_of: Optional[Callable[[str], str]] = None) -> dict[str, float]:
    """Raw preference scores -> capped target weights.

    `caps` is a PER-NAME ceiling map (quality-scaled). Result may sum to < 1;
    the remainder is cash by design — we never force-feed weak names to fill the
    book.
    """
    if bucket_of is None:
        def bucket_of(sym: str) -> str:
            return factor_bucket(CATS.get(sym, ""))
    w = {k: max(0.0, v) for k, v in scores.items()}
    if sum(w.values()) <= 0:
        return {k: 0.0 for k in w}
    w = _normalize(w)
    # alternate the two caps until both hold (or we stop making progress)
    for _ in range(50):
        before = dict(w)
        w = _apply_name_cap(w, caps)
        w = _apply_bucket_cap(w, max_bucket, bucket_of)
        if all(abs(w[k] - before.get(k, 0.0)) < 1e-9 for k in w):
            break
    # final safety clip: bucket redistribution must never breach a name ceiling
    w = {k: min(v, caps.get(k, 1.0)) for k, v in w.items()}
    return w


def build(composite: dict[str, Any], current_weights: Optional[dict[str, float]] = None,
          *, max_name: float = MAX_NAME_WEIGHT, max_bucket: float = MAX_BUCKET_WEIGHT,
          min_weight: float = MIN_NAME_WEIGHT,
          tolerance: float = ACTION_TOLERANCE) -> dict[str, Any]:
    trusted = composite.get("signalsTrusted") is not False
    ranking = composite.get("ranking") or []
    if not trusted or not ranking:
        return {
            "stage": SIZING_STAGE, "researchOnly": True, "promotable": False,
            "authorityChanged": False, "brokerSubmitAllowed": False,
            "liveTradingAllowed": False,
            "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(),
            "verdict": "fail-closed", "signalsTrusted": False,
            "reason": "composite inputs not trusted or empty — no weights produced",
            "targets": [], "bucketTotals": {}, "cashWeight": 1.0,
        }

    cur = {normalize_symbol(k): float(v) for k, v in (current_weights or {}).items()}
    # if the operator passed percentages (e.g. 8 for 8%), normalize to fractions
    if cur and sum(cur.values()) > 1.5:
        cur = {k: v / 100.0 for k, v in cur.items()}

    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}
    for r in ranking:
        sym = normalize_symbol(r.get("symbol"))
        if not sym:
            continue
        tag = r.get("tag", "HOLD")
        rs = float(r.get("composite") or 0.0)
        mult = TAG_MULTIPLIER.get(tag, 0.0)
        scores[sym] = rs * mult
        meta[sym] = {"cat": r.get("cat", ""), "tag": tag, "rs": rs}

    # bucket by the category carried on the composite row, so the caps we enforce
    # and the buckets we report are always the same thing
    def _bucket_of(sym: str) -> str:
        return factor_bucket(meta.get(sym, {}).get("cat", ""))

    # PER-NAME ceilings, scaled by conviction: a REDUCE name may never be sized
    # like a LEADER just because the bucket cap freed up room.
    caps = {sym: max_name * TAG_MULTIPLIER.get(m["tag"], 0.0)
            for sym, m in meta.items()}

    weights = solve_weights(scores, caps=caps, max_bucket=max_bucket,
                            bucket_of=_bucket_of)

    # Drop dust and re-solve. A 0.7% position costs a ticket and attention but
    # cannot move the book; better to concentrate that weight into names that
    # earned it. Re-solving (rather than just deleting) keeps every cap intact.
    if min_weight > 0:
        for _ in range(5):
            survivors = {k: v for k, v in scores.items()
                         if weights.get(k, 0.0) >= min_weight}
            if not survivors or len(survivors) == len([
                    k for k, v in weights.items() if v > 0]):
                break
            weights = solve_weights(survivors, caps=caps, max_bucket=max_bucket,
                                    bucket_of=_bucket_of)
            weights = {k: weights.get(k, 0.0) for k in scores}

    targets = []
    for sym, m in meta.items():
        tw = round(weights.get(sym, 0.0), 4)
        cw = round(cur.get(sym, 0.0), 4) if cur else None
        if cw is None:
            action, delta = "—", None
        else:
            delta = round(tw - cw, 4)
            if tw <= 1e-9 and cw > 1e-9:
                action = "EXIT"
            elif delta > tolerance:
                action = "ADD"
            elif delta < -tolerance:
                action = "TRIM"
            else:
                action = "HOLD"
        targets.append({
            "symbol": sym, "cat": m["cat"], "bucket": factor_bucket(m["cat"]),
            "tag": m["tag"], "rs": m["rs"], "targetWeight": tw,
            "currentWeight": cw, "delta": delta, "action": action,
        })
    targets.sort(key=lambda d: -d["targetWeight"])

    bucket_totals: dict[str, float] = {}
    for t in targets:
        bucket_totals[t["bucket"]] = round(
            bucket_totals.get(t["bucket"], 0.0) + t["targetWeight"], 4)
    invested = round(sum(t["targetWeight"] for t in targets), 4)

    return {
        "stage": SIZING_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(),
        "verdict": "trusted",
        "signalsTrusted": True,
        "params": {"maxNameWeight": max_name, "maxBucketWeight": max_bucket,
                   "minNameWeight": min_weight, "tolerance": tolerance,
                   "tagMultiplier": TAG_MULTIPLIER},
        "count": len(targets),
        "investedWeight": invested,
        "cashWeight": round(max(0.0, 1.0 - invested), 4),
        "bucketTotals": bucket_totals,
        # names with no category fall through to the default bucket — surface them
        # so a mis-tagged name can't quietly dodge the concentration cap
        "unclassifiedSymbols": sorted(s for s, m in meta.items() if not m["cat"]),
        # Two very different reasons a name is unfunded — never conflate them.
        # belowTrend = trend is broken (stand aside, do not average down).
        # droppedAsDust = trend intact, but conviction too low to justify a
        # position worth holding; these are still legitimate re-entry candidates.
        "belowTrend": [t["symbol"] for t in targets if t["tag"] == "AVOID"],
        "droppedAsDust": [t["symbol"] for t in targets
                          if t["targetWeight"] <= 1e-9 and t["tag"] != "AVOID"],
        "zeroWeighted": [t["symbol"] for t in targets if t["targetWeight"] <= 1e-9],
        "targets": targets,
        "citations": ["docs/MOMENTUM_VS_BUYLOW_VERDICT_2026-07-15.md"],
    }


def text(p: dict[str, Any]) -> str:
    L = ["AI / data-center basket — position-sizing recommendation (research-only)",
         f"Generated: {p['generatedAt']}"]
    if not p.get("signalsTrusted"):
        L.append(f"Verdict: {p.get('verdict')} — {p.get('reason','')}")
        return "\n".join(L)
    q = p["params"]
    L.append(f"Caps: max {q['maxNameWeight']*100:.0f}% per name · "
             f"max {q['maxBucketWeight']*100:.0f}% per factor bucket · "
             f"min {q.get('minNameWeight', 0)*100:.1f}% to hold a position")
    L.append(f"Invested {p['investedWeight']*100:.0f}% · cash {p['cashWeight']*100:.0f}%")
    L.append("")
    has_cur = any(t["currentWeight"] is not None for t in p["targets"])
    hdr = f"{'sym':<6}{'cat':<15}{'tag':<8}{'RS':>4}{'target':>8}"
    if has_cur:
        hdr += f"{'current':>9}{'delta':>7}  action"
    L.append(hdr)
    for t in p["targets"]:
        row = (f"{t['symbol']:<6}{t['cat']:<15}{t['tag']:<8}{t['rs']:>4.0f}"
               f"{t['targetWeight']*100:>7.1f}%")
        if has_cur:
            cw = t["currentWeight"] or 0.0
            row += f"{cw*100:>8.1f}%{(t['delta'] or 0)*100:>+7.1f}  {t['action']}"
        L.append(row)
    L.append("")
    L.append("Factor buckets:")
    for b, w in sorted(p["bucketTotals"].items(), key=lambda kv: -kv[1]):
        L.append(f"  {b:<28}{w*100:>6.1f}%")
    below = p.get("belowTrend") or []
    dust = p.get("droppedAsDust") or []
    if below:
        L.append("")
        L.append(f"Below 200-day — stand aside, do NOT average down: {', '.join(below)}")
    if dust:
        L.append(f"Trend intact but conviction too low to size ({p['params']['minNameWeight']*100:.1f}% "
                 f"minimum): {', '.join(dust)}")
    L.append("")
    L.append("Recommendation only. Sizes nothing, places no orders, authority unchanged. "
             "Not financial advice.")
    return "\n".join(L)


def save(p: dict[str, Any]) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUT_JSON, p)
    atomic_write_text(OUT_TXT, text(p) + "\n")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--composite", required=True, help="inferno_ai_basket_composite output JSON")
    ap.add_argument("--current", help="optional JSON {\"NVDA\": 0.10, ...} of current weights")
    ap.add_argument("--max-name", type=float, default=MAX_NAME_WEIGHT)
    ap.add_argument("--max-bucket", type=float, default=MAX_BUCKET_WEIGHT)
    ap.add_argument("--min-weight", type=float, default=MIN_NAME_WEIGHT,
                    help="drop positions below this weight as dust (0 to disable)")
    args = ap.parse_args(argv)
    composite = json.loads(Path(args.composite).read_text(encoding="utf-8"))
    current = None
    if args.current:
        current = json.loads(Path(args.current).read_text(encoding="utf-8"))
    p = build(composite, current, max_name=args.max_name, max_bucket=args.max_bucket,
              min_weight=args.min_weight)
    print(text(p))
    if p.get("signalsTrusted"):
        save(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
