from __future__ import annotations

"""Inferno Consensus Monitor — crowdedness regime classifier.

What it does:
    Reads the Schwab edge-signals bridge and the portfolio correlation
    artifact and emits a research-only five-tier verdict on whether
    today's slate is taking a *contrarian* or *consensus* trade. The
    verdict ladder is `uncrowded` / `normal` / `crowded-watch` /
    `consensus-extreme` / `awaiting-data` (see
    docs/CONSENSUS_AND_CROWDEDNESS.md §4).

What it does NOT do:
    - Approve, reject, or size any trade.
    - Block "crowded" tickets — the operator may have a deliberate
      consensus thesis (Brunnermeier-Nagel "ride the bubble until exit").
    - Use third-party "smart money" data feeds. None are wired here
      because none priced for retail are signal.
    - Promote any strategy. Research-only, diagnostic-only.

Strict contract: research-only, diagnostic-only, promotable=False.

## The signals (see docs/CONSENSUS_AND_CROWDEDNESS.md §3)

For v1 we use what's actually available:

1. **Side-skew lean** from the Schwab edge bridge: how many tickers
   have put-rich vs call-rich vs balanced IV.
2. **Slate concentration** from the portfolio correlation artifact:
   dominant-family share and effective bet count.
3. **Cross-family correlation** when ≥5-day data exists: family pairs
   with ρ > 0.7.

Each is mapped to a per-signal lean and then aggregated into a verdict.

## Not built yet (explicit so the next session knows)

- `/movers` feed integration
- Sector-ETF vs single-name vol comparison
- VIX term-structure overlay
- News-sentiment polarity (no MCP attached)

CLI::

    python3 inferno_consensus_monitor.py             # run + persist
    python3 inferno_consensus_monitor.py status      # show last memo
"""

import argparse
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


# ───────────────────────── file locations ──────────────────────────────

SCHWAB_EDGE_FILE = DATA_DIR / "inferno_schwab_edge_signals.json"
PORTFOLIO_CORRELATION_FILE = DATA_DIR / "inferno_portfolio_correlation.json"

CONSENSUS_FILE = DATA_DIR / "inferno_consensus_monitor.json"
CONSENSUS_TEXT_FILE = REPORTS_DIR / "consensus_monitor_latest.txt"

CONSENSUS_STAGE = "consensus-monitor-research-only"


# ───────────────────────── thresholds ──────────────────────────────────

# Side-skew aggregate: when ≥ this fraction of Schwab rows lean one way,
# the signal classifies as that-side-rich at slate level.
SIDE_SKEW_DOMINANT_FRACTION = 0.50

# Family-pair correlation above this → "fused families" signal.
FUSED_FAMILY_RHO = 0.70

# Slate concentration share at/above this → "concentrated own-side" signal.
OWN_SIDE_CONCENTRATION_FLOOR = 0.50


# ───────────────────────── per-signal classifiers ───────────────────────


def _side_skew_signal(edge_payload: dict[str, Any]) -> dict[str, Any]:
    """Aggregate Schwab side-skew lean across the slate."""
    summary = edge_payload.get("summary") or {}
    side_counts = summary.get("sideSkewCounts") or {}
    total = sum(int(v) for v in side_counts.values()) or 0
    if total == 0:
        return {"signal": "side-skew", "lean": "unknown", "reason": "no-schwab-rows"}
    put_rich = int(side_counts.get("put-rich", 0))
    call_rich = int(side_counts.get("call-rich", 0))
    balanced = int(side_counts.get("balanced", 0))
    put_share = put_rich / total
    call_share = call_rich / total
    if put_share >= SIDE_SKEW_DOMINANT_FRACTION:
        lean = "put-rich-consensus"
        reason = f"{put_rich}/{total} chains put-rich"
    elif call_share >= SIDE_SKEW_DOMINANT_FRACTION:
        lean = "call-rich-consensus"
        reason = f"{call_rich}/{total} chains call-rich"
    else:
        lean = "neutral"
        reason = f"put={put_rich} call={call_rich} balanced={balanced}"
    return {
        "signal": "side-skew",
        "lean": lean,
        "putShare": round(put_share, 4),
        "callShare": round(call_share, 4),
        "reason": reason,
    }


def _slate_concentration_signal(corr_payload: dict[str, Any]) -> dict[str, Any]:
    """Detect own-side concentration in the desk's active slate."""
    slate = corr_payload.get("slateConcentration") or {}
    headcount = int(slate.get("headcount") or 0)
    if headcount == 0:
        return {"signal": "own-side-concentration", "lean": "unknown", "reason": "no-active-slate"}
    by_direction = slate.get("byDirection") or {}
    if not by_direction:
        return {"signal": "own-side-concentration", "lean": "unknown", "reason": "no-direction-data"}
    # Dominant direction share
    direction, count = max(by_direction.items(), key=lambda kv: kv[1])
    share = count / headcount
    if share >= OWN_SIDE_CONCENTRATION_FLOOR:
        lean = f"{direction}-heavy"
        reason = f"{count}/{headcount} active tickets are {direction}"
    else:
        lean = "balanced"
        reason = f"top direction {direction}={count}/{headcount} (<{int(OWN_SIDE_CONCENTRATION_FLOOR * 100)}%)"
    return {
        "signal": "own-side-concentration",
        "lean": lean,
        "dominantDirection": direction,
        "dominantShare": round(share, 4),
        "effectiveBetCount": slate.get("effectiveBetCount"),
        "reason": reason,
    }


def _family_fusion_signal(corr_payload: dict[str, Any]) -> dict[str, Any]:
    """Detect family pairs whose pairwise ρ is in the 'fused' regime."""
    fam = (corr_payload.get("familyCorrelations") or {}).get("pairs") or []
    if not fam:
        return {"signal": "family-fusion", "lean": "unknown", "reason": "no-closed-pairs"}
    fused: list[dict[str, Any]] = []
    for pair in fam:
        rho = pair.get("correlation")
        if isinstance(rho, (int, float)) and rho >= FUSED_FAMILY_RHO:
            fused.append(
                {"familyA": pair["familyA"], "familyB": pair["familyB"], "rho": rho}
            )
    if fused:
        return {
            "signal": "family-fusion",
            "lean": "fused",
            "fusedPairs": fused,
            "reason": f"{len(fused)} family pair(s) at ρ ≥ {FUSED_FAMILY_RHO}",
        }
    return {
        "signal": "family-fusion",
        "lean": "diverse",
        "reason": f"no family pair at ρ ≥ {FUSED_FAMILY_RHO}",
    }


# ───────────────────────── aggregation ──────────────────────────────────


def _aggregate_verdict(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduce per-signal leans to the five-tier verdict.

    Heuristic:
      * Count signals leaning "consensus" (any *-consensus / *-heavy /
        fused). Each non-neutral, non-unknown lean counts.
      * 0 consensus signals + ≥1 neutral → "uncrowded".
      * 1 consensus signal → "normal".
      * 2 consensus signals → "crowded-watch".
      * 3+ consensus signals → "consensus-extreme".
      * All "unknown" → "awaiting-data".
    """
    unknown = sum(1 for s in signals if s.get("lean") == "unknown")
    if unknown == len(signals):
        return {"verdict": "awaiting-data", "consensusCount": 0, "unknownCount": unknown}

    consensus_leans = {
        "put-rich-consensus", "call-rich-consensus",
        "long-vol-heavy", "short-vol-heavy",
        "long-equity-heavy", "short-equity-heavy",
        "neutral-heavy", "unknown-heavy",
        "fused",
    }
    # neutral-heavy and unknown-heavy are dominant-direction labels that
    # happen to fall into the *-heavy form; we still count them because
    # a dominant share of any one direction is itself a positioning lean.

    consensus_count = sum(1 for s in signals if s.get("lean") in consensus_leans)

    if consensus_count >= 3:
        verdict = "consensus-extreme"
    elif consensus_count == 2:
        verdict = "crowded-watch"
    elif consensus_count == 1:
        verdict = "normal"
    else:
        verdict = "uncrowded"
    return {
        "verdict": verdict,
        "consensusCount": consensus_count,
        "unknownCount": unknown,
    }


# ───────────────────────── builder ──────────────────────────────────────


def build_consensus_monitor(now: Any | None = None) -> dict[str, Any]:
    edge_payload = load_json_file(SCHWAB_EDGE_FILE) or {}
    corr_payload = load_json_file(PORTFOLIO_CORRELATION_FILE) or {}

    signals = [
        _side_skew_signal(edge_payload),
        _slate_concentration_signal(corr_payload),
        _family_fusion_signal(corr_payload),
    ]
    aggregate = _aggregate_verdict(signals)

    return {
        "version": 1,
        "stage": CONSENSUS_STAGE,
        "promotable": False,
        "researchOnly": True,
        "authorityChanged": False,
        "generatedAt": str(now or local_now()),
        "verdict": aggregate["verdict"],
        "consensusCount": aggregate["consensusCount"],
        "unknownCount": aggregate["unknownCount"],
        "sources": {
            "schwabEdgeGeneratedAt": edge_payload.get("generatedAt"),
            "portfolioCorrelationGeneratedAt": corr_payload.get("generatedAt"),
        },
        "signals": signals,
        "thresholds": {
            "sideSkewDominantFraction": SIDE_SKEW_DOMINANT_FRACTION,
            "fusedFamilyRho": FUSED_FAMILY_RHO,
            "ownSideConcentrationFloor": OWN_SIDE_CONCENTRATION_FLOOR,
        },
        "notBuiltYet": [
            "Schwab /movers feed integration (top-sector mover detection)",
            "Sector-ETF vs single-name vol comparison",
            "VIX term-structure overlay (contango / backwardation regime)",
            "News-sentiment polarity (no MCP attached)",
        ],
        "reminders": [
            "Crowdedness is a regime read, not a trade ticket. The operator "
            "may have a deliberate consensus thesis (Brunnermeier-Nagel "
            "ride-the-bubble) — the module flags, never blocks.",
            "Consensus-extreme is the regime where Marks-pendulum and "
            "Soros-reflexivity warnings are most informative. Pair with the "
            "trade conviction auditor's bear rules before sizing up.",
            "Stein-2009 insight: the trade where smart money agrees with "
            "you is the trade to size smaller, not larger.",
        ],
        "citations": [
            "STEIN-2009",
            "BRUNNERMEIER-NAGEL-2004",
            "LOU-POLK-2013",
            "KHANDANI-LO-2007",
            "SOROS-REFLEXIVITY",
        ],
    }


def save_consensus_monitor(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(CONSENSUS_FILE, payload)
    atomic_write_text(CONSENSUS_TEXT_FILE, consensus_monitor_text(payload))


# ───────────────────────── rendering ────────────────────────────────────


def consensus_monitor_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Inferno Consensus Monitor (research-only)")
    lines.append("")
    lines.append(f"Generated: {payload.get('generatedAt')}")
    lines.append(f"Stage:     {payload.get('stage')}")
    lines.append(f"Verdict:   {payload.get('verdict')}")
    lines.append(
        f"Consensus signals: {payload.get('consensusCount', 0)}  "
        f"unknown: {payload.get('unknownCount', 0)}"
    )
    lines.append("")
    sources = payload.get("sources") or {}
    lines.append("SOURCES")
    lines.append("-------")
    lines.append(f"  Schwab edge generated:        {sources.get('schwabEdgeGeneratedAt')}")
    lines.append(f"  Portfolio correlation gen.:   {sources.get('portfolioCorrelationGeneratedAt')}")
    lines.append("")
    lines.append("PER-SIGNAL READS")
    lines.append("----------------")
    for sig in payload.get("signals") or []:
        lines.append(f"  · {sig.get('signal')}: lean={sig.get('lean')}  ({sig.get('reason')})")
    lines.append("")
    nbt = payload.get("notBuiltYet") or []
    if nbt:
        lines.append("Not built yet:")
        for item in nbt:
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
            "Research-only consensus / crowdedness monitor. "
            "See docs/CONSENSUS_AND_CROWDEDNESS.md."
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
        existing = load_json_file(CONSENSUS_FILE) or {}
        print(consensus_monitor_text(existing))
        return 0

    payload = build_consensus_monitor()
    save_consensus_monitor(payload)
    print(consensus_monitor_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
