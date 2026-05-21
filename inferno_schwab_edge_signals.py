from __future__ import annotations

"""Inferno Schwab Edge Signals — bridge from chain data to operator signals.

What it does:
    Reads the read-only Schwab option-chain artifact and classifies each
    ticker against the four-tier edge framework in
    ``docs/SCHWAB_EDGE_OPPORTUNITIES.md``. Emits per-ticker actionability
    lanes plus a cross-sectional regime read so the desk actually capitalizes
    on the edges that Schwab data can deliver today (Tier 0 don't-bleed and
    a single-snapshot version of Tier 1 vol calibration).

What it does NOT do:
    - Promote, approve, reject, or size any trade.
    - Touch any TOS, paper, or broker write surface.
    - Substitute for the historical IV-rank module proposed in the edge doc
      (``inferno_iv_calibration.py``), which still needs stored chain
      history. This module is the single-snapshot interim — explicitly so.
    - Change authority. Broker submit stays OFF.

Strict contract: research-only, diagnostic-only, promotable=False.

## The four tiers (see ``docs/SCHWAB_EDGE_OPPORTUNITIES.md``)

* Tier 0 — quality / liquidity / spread (already produced by the Schwab
  adapter; this module surfaces it as an explicit pass/fail with a reason).
* Tier 1 — vol calibration. With only one snapshot we can read cross-sectional
  IV ranks, expected-move buckets, and side-stats skew. Full IV-rank-vs-history
  is still a future build.
* Tier 2 — cross-instrument. Not implemented here; the module lists the
  metrics as "not built" in its reminders so the gap is honest.
* Tier 3 — positioning / flow. Same — explicitly listed as not built.

Per-ticker lane labels::

    tradable-research   Tier 0 pass + signal usable for research-only sizing.
    calibration-watch   Tier 0 pass + Tier 1 signal worth a manual look
                        (extreme ATM IV, hot expected move, or skewed
                        call/put IV) — never an auto-ticket.
    thin-data           Tier 0 fail. Useful only as a research datapoint;
                        do not trade. Mirrors ``avoid-chain`` semantics.
    no-chain            Chain empty or status not ok.

CLI::

    python3 inferno_schwab_edge_signals.py             # build + persist
    python3 inferno_schwab_edge_signals.py status      # print last artifact
"""

import argparse
from collections import Counter
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


# ───────────────────────── file locations ──────────────────────────────

SCHWAB_OPTIONS_FILE = DATA_DIR / "inferno_schwab_options.json"

EDGE_SIGNALS_FILE = DATA_DIR / "inferno_schwab_edge_signals.json"
EDGE_SIGNALS_TEXT_FILE = REPORTS_DIR / "schwab_edge_signals_latest.txt"

EDGE_SIGNALS_STAGE = "schwab-edge-signals-research-only"


# ───────────────────────── tier-0 thresholds (don't bleed) ──────────────

# Match the Schwab adapter's existing labels but make the pass criterion
# explicit here so callers can rely on one field.
TIER0_MIN_QUALITY_SCORE = 70           # "usable" or better
TIER0_MAX_ATM_SPREAD_PCT = 0.20        # past "workable" is a Tier 0 fail
TIER0_MIN_ATM_LIQUIDITY = 50           # "watch" or better
TIER0_HARD_FAIL_FLAGS = frozenset(
    {
        "empty-chain",
        "missing-underlying-price",
        "missing-atm-pair",
        "no-liquid-contracts",
    }
)


# ───────────────────────── tier-1 vol calibration buckets ────────────────

# Cross-sectional buckets you can read from a single snapshot. Once
# ``inferno_iv_calibration.py`` ships with stored history, the IV-percentile
# bucket replaces this with a per-ticker 252-day denominator.
IV_BUCKETS: tuple[tuple[str, float], ...] = (
    ("very-low", 0.20),
    ("low", 0.35),
    ("normal", 0.55),
    ("elevated", 0.80),
    ("extreme", float("inf")),
)

# Call-vs-put IV skew threshold. Real skew is computed at 25Δ; the current
# adapter averages across-strike per side, which is a usable proxy until
# per-strike skew is wired.
SIDE_SKEW_FLAG_ABS = 0.05               # absolute decimal IV gap


# ───────────────────────── helpers ──────────────────────────────────────


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _iv_bucket(iv: float | None) -> str:
    if iv is None:
        return "unknown"
    for label, ceiling in IV_BUCKETS:
        if iv < ceiling:
            return label
    return "unknown"


def _side_skew(side_stats: dict[str, Any]) -> dict[str, Any]:
    """Compute the call-vs-put IV gap from the chain's sideStats."""
    call_iv = _safe_float((side_stats.get("CALL") or {}).get("avgImpliedVolatility"))
    put_iv = _safe_float((side_stats.get("PUT") or {}).get("avgImpliedVolatility"))
    if call_iv is None or put_iv is None:
        return {"callIv": call_iv, "putIv": put_iv, "skew": None, "lean": "unknown"}
    skew = round(put_iv - call_iv, 6)
    if abs(skew) < SIDE_SKEW_FLAG_ABS:
        lean = "balanced"
    elif skew > 0:
        lean = "put-rich"      # downside fear priced richer than upside
    else:
        lean = "call-rich"     # upside chase priced richer than downside
    return {"callIv": call_iv, "putIv": put_iv, "skew": skew, "lean": lean}


def _tier0_verdict(row: dict[str, Any]) -> dict[str, Any]:
    """Pass/fail Tier 0 with an explicit reason string."""
    quality_flags = list(row.get("qualityFlags") or [])
    hard_fail = sorted(TIER0_HARD_FAIL_FLAGS.intersection(quality_flags))

    quality_score = _safe_float(row.get("quoteQualityScore")) or 0.0
    atm_spread = _safe_float(row.get("atmSpreadPct"))
    atm_liquidity = _safe_float(row.get("atmLiquidityScore")) or 0.0

    fails: list[str] = []
    if hard_fail:
        fails.append("hard-flags=" + ",".join(hard_fail))
    if quality_score < TIER0_MIN_QUALITY_SCORE:
        fails.append(
            f"quality<{TIER0_MIN_QUALITY_SCORE} ({int(quality_score)})"
        )
    if atm_spread is not None and atm_spread > TIER0_MAX_ATM_SPREAD_PCT:
        fails.append(
            f"atm-spread>{int(TIER0_MAX_ATM_SPREAD_PCT * 100)}% "
            f"({round(atm_spread * 100, 1)}%)"
        )
    if atm_liquidity < TIER0_MIN_ATM_LIQUIDITY:
        fails.append(
            f"atm-liq<{TIER0_MIN_ATM_LIQUIDITY} ({int(atm_liquidity)})"
        )

    return {
        "pass": not fails,
        "reasons": fails,
        "qualityScore": int(quality_score),
        "qualityLabel": row.get("quoteQualityLabel"),
        "atmSpreadPct": atm_spread,
        "atmLiquidityScore": int(atm_liquidity),
    }


def _tier1_read(row: dict[str, Any]) -> dict[str, Any]:
    """Single-snapshot Tier 1 vol calibration read.

    This is intentionally cross-sectional. Once chain history exists the
    IV-rank denominator becomes per-ticker; until then, the bucket is a
    fixed-scale read.
    """
    iv = _safe_float(row.get("atmImpliedVolatility"))
    move_pct = _safe_float(row.get("atmImpliedMovePct"))
    move_bucket = row.get("atmExpectedMoveBucket") or "unknown"
    side_stats = row.get("sideStats") or {}
    skew = _side_skew(side_stats)
    return {
        "atmImpliedVolatility": iv,
        "atmIvBucket": _iv_bucket(iv),
        "atmImpliedMovePct": move_pct,
        "atmExpectedMoveBucket": move_bucket,
        "sideIvSkew": skew,
    }


def _lane_for_row(tier0: dict[str, Any], tier1: dict[str, Any], row: dict[str, Any]) -> str:
    """Map the tier reads onto an operator-facing lane label."""
    if row.get("status") != "ok":
        return "no-chain"
    if not tier0["pass"]:
        return "thin-data"
    iv_bucket = tier1["atmIvBucket"]
    move_bucket = tier1["atmExpectedMoveBucket"]
    skew_lean = (tier1.get("sideIvSkew") or {}).get("lean") or "unknown"
    interesting = (
        iv_bucket in {"very-low", "elevated", "extreme"}
        or move_bucket in {"hot", "inferno"}
        or skew_lean in {"put-rich", "call-rich"}
    )
    return "calibration-watch" if interesting else "tradable-research"


def _signal_notes(tier0: dict[str, Any], tier1: dict[str, Any], lane: str) -> list[str]:
    """Plain-English bullets that say WHY a ticker landed in its lane.

    These are diagnostic; they don't become trade tickets.
    """
    notes: list[str] = []
    if lane == "no-chain":
        notes.append("Chain payload status not ok — skip until refresh.")
        return notes
    if lane == "thin-data":
        notes.append(
            "Tier 0 fail — research-only datapoint, do not size. "
            "Reasons: " + ("; ".join(tier0["reasons"]) or "(none recorded)")
        )
        return notes
    iv_bucket = tier1["atmIvBucket"]
    move_bucket = tier1["atmExpectedMoveBucket"]
    skew_lean = (tier1.get("sideIvSkew") or {}).get("lean") or "unknown"
    if iv_bucket == "extreme":
        notes.append(
            "ATM IV in the EXTREME bucket — premium is rich; "
            "favor sell-vol or hedged structures; check earnings calendar."
        )
    elif iv_bucket == "elevated":
        notes.append("ATM IV elevated — premium is priced for movement.")
    elif iv_bucket == "very-low":
        notes.append(
            "ATM IV very low — premium is cheap; "
            "favor buy-vol structures if a catalyst is plausible."
        )
    if move_bucket == "inferno":
        notes.append(
            "Expected move bucket = INFERNO — chain is pricing a large "
            "event; do not enter naive long premium without an event thesis."
        )
    elif move_bucket == "hot":
        notes.append("Expected move bucket = hot — sizable event priced in.")
    if skew_lean == "put-rich":
        notes.append(
            "Put-side IV richer than call-side — market pricing downside "
            "fear; bear cases are not free, but call-side structures may "
            "carry a relative pricing advantage."
        )
    elif skew_lean == "call-rich":
        notes.append(
            "Call-side IV richer than put-side — possible chase regime; "
            "Marks-pendulum caution applies before buying upside premium."
        )
    if lane == "tradable-research" and not notes:
        notes.append(
            "Tier 0 clean and Tier 1 calibration unremarkable — usable for "
            "strike selection; thesis must come from elsewhere."
        )
    return notes


def _classify_row(row: dict[str, Any]) -> dict[str, Any]:
    tier0 = _tier0_verdict(row)
    tier1 = _tier1_read(row)
    lane = _lane_for_row(tier0, tier1, row)
    return {
        "symbol": row.get("symbol"),
        "status": row.get("status"),
        "lane": lane,
        "tier0": tier0,
        "tier1": tier1,
        "notes": _signal_notes(tier0, tier1, lane),
    }


def _regime_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate cross-sectional regime read for the slate."""
    lane_counts = Counter(r["lane"] for r in rows)
    iv_buckets = Counter(r["tier1"]["atmIvBucket"] for r in rows if r.get("tier1"))
    move_buckets = Counter(
        r["tier1"]["atmExpectedMoveBucket"] for r in rows if r.get("tier1")
    )
    skew_leans = Counter(
        (r["tier1"].get("sideIvSkew") or {}).get("lean") or "unknown"
        for r in rows
        if r.get("tier1")
    )
    total = len(rows) or 1
    return {
        "rows": len(rows),
        "laneCounts": dict(lane_counts),
        "ivBucketCounts": dict(iv_buckets),
        "expectedMoveBucketCounts": dict(move_buckets),
        "sideSkewCounts": dict(skew_leans),
        "tier0PassRate": round(
            lane_counts.get("tradable-research", 0) / total
            + lane_counts.get("calibration-watch", 0) / total,
            3,
        ),
    }


# ───────────────────────── builder ──────────────────────────────────────


def build_schwab_edge_signals(now: Any | None = None) -> dict[str, Any]:
    """Build the bridge payload (research-only, diagnostic-only)."""
    source = load_json_file(SCHWAB_OPTIONS_FILE) or {}
    source_rows = source.get("rows") or []
    classified = [_classify_row(row) for row in source_rows if isinstance(row, dict)]
    summary = _regime_summary(classified)

    source_status = str(source.get("status") or "missing")
    if not source:
        verdict = "no-source"
    elif source_status in {"not-configured", "disabled", "no-symbols"}:
        verdict = "schwab-not-configured"
    elif not classified:
        verdict = "no-rows"
    elif summary["laneCounts"].get("tradable-research", 0) > 0:
        verdict = "edge-actionable"
    elif summary["laneCounts"].get("calibration-watch", 0) > 0:
        verdict = "watch-only"
    else:
        verdict = "thin-data-only"

    return {
        "version": 1,
        "stage": EDGE_SIGNALS_STAGE,
        "promotable": False,
        "researchOnly": True,
        "authorityChanged": False,
        "generatedAt": str(now or local_now()),
        "sourceGeneratedAt": source.get("generatedAt"),
        "sourceStatus": source_status,
        "sourceConfigured": bool(source.get("configured")),
        "verdict": verdict,
        "summary": summary,
        "rows": classified,
        "notBuiltYet": [
            "Tier 1 IV rank vs 252-day per-ticker history "
            "(needs inferno_chain_history.py + inferno_iv_calibration.py)",
            "Tier 1 realized-vol comparison (needs /pricehistory adapter)",
            "Tier 1 earnings implied-vs-realized log "
            "(needs inferno_event_vol_history.py)",
            "Tier 2 cross-instrument vol ratios (needs index/sector chain)",
            "Tier 3 positioning / movers / OI delta (needs /movers + diff)",
        ],
        "reminders": [
            "Bridge module: research-only; broker submit stays OFF.",
            "Lane = research label, not a trade ticket. The trade conviction "
            "auditor and risk policy still own the go/no-go on any ticket.",
            "Cross-sectional IV bucket is a fixed-scale read until "
            "per-ticker history exists. Don't infer relative cheapness "
            "across two names from this field alone.",
        ],
        "citations": [
            "HASBROUCK-1991",
            "ALMGREN-CHRISS-2000",
            "BECKERS-1981",
            "KLARMAN-MARGIN-OF-SAFETY",
        ],
    }


def save_schwab_edge_signals(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(EDGE_SIGNALS_FILE, payload)
    atomic_write_text(EDGE_SIGNALS_TEXT_FILE, schwab_edge_signals_text(payload))


# ───────────────────────── rendering ────────────────────────────────────


def schwab_edge_signals_text(payload: dict[str, Any]) -> str:
    lines: list[str] = [
        "Inferno Schwab Edge Signals (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Source generated: {payload.get('sourceGeneratedAt')}",
        f"Source status: {payload.get('sourceStatus')}",
        f"Source configured: {payload.get('sourceConfigured')}",
        f"Stage: {payload.get('stage')}",
        f"Verdict: {payload.get('verdict')}",
        "",
    ]

    summary = payload.get("summary") or {}
    lines.append(
        "Lane counts: "
        + (
            ", ".join(f"{k}={v}" for k, v in (summary.get("laneCounts") or {}).items())
            or "(none)"
        )
    )
    lines.append(
        "IV bucket distribution: "
        + (
            ", ".join(f"{k}={v}" for k, v in (summary.get("ivBucketCounts") or {}).items())
            or "(none)"
        )
    )
    lines.append(
        "Expected-move distribution: "
        + (
            ", ".join(
                f"{k}={v}" for k, v in (summary.get("expectedMoveBucketCounts") or {}).items()
            )
            or "(none)"
        )
    )
    lines.append(
        "Side-skew distribution: "
        + (
            ", ".join(f"{k}={v}" for k, v in (summary.get("sideSkewCounts") or {}).items())
            or "(none)"
        )
    )
    lines.append(f"Tier 0 pass rate: {summary.get('tier0PassRate')}")
    lines.append("")
    lines.append("Per-ticker signals:")
    for row in payload.get("rows") or []:
        tier0 = row.get("tier0") or {}
        tier1 = row.get("tier1") or {}
        move = tier1.get("atmImpliedMovePct")
        move_text = f"{round(move * 100, 2)}%" if isinstance(move, (int, float)) else "-"
        lines.append(
            f"- {row.get('symbol')}: lane={row.get('lane')} "
            f"quality={tier0.get('qualityScore')}/{tier0.get('qualityLabel')} "
            f"iv={tier1.get('atmIvBucket')} move={tier1.get('atmExpectedMoveBucket')} "
            f"({move_text}) skew={(tier1.get('sideIvSkew') or {}).get('lean')}"
        )
        for note in row.get("notes") or []:
            lines.append(f"    · {note}")
    lines.append("")
    lines.append("Not built yet (see docs/SCHWAB_EDGE_OPPORTUNITIES.md):")
    for item in payload.get("notBuiltYet") or []:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("Reminders:")
    for item in payload.get("reminders") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


# ───────────────────────── CLI ──────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bridge from Schwab chain data to operator-facing edge signals. "
            "Research-only. See docs/SCHWAB_EDGE_OPPORTUNITIES.md."
        )
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=("run", "status"),
        help="run = build + persist; status = print last artifact.",
    )
    args = parser.parse_args(argv)

    if args.command == "status":
        existing = load_json_file(EDGE_SIGNALS_FILE) or {}
        print(schwab_edge_signals_text(existing))
        return 0

    payload = build_schwab_edge_signals()
    save_schwab_edge_signals(payload)
    print(schwab_edge_signals_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
