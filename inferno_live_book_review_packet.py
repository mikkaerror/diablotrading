from __future__ import annotations

"""Build a focused live-book review packet for capital deployment blockers.

The regular live-position review answers "is the book healthy?" This module
answers the next operator question: "what exactly needs to be reviewed before
new capital can be sized?" It is read-only, math-only, and designed to make the
capital deployment blocker explainable without opening the broker.
"""

import argparse
import json
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


LIVE_POSITION_REVIEW_FILE = DATA_DIR / "inferno_live_position_review.json"
CAPITAL_DEPLOYMENT_READINESS_FILE = DATA_DIR / "inferno_capital_deployment_readiness.json"
LIVE_BOOK_REVIEW_PACKET_FILE = DATA_DIR / "inferno_live_book_review_packet.json"
LIVE_BOOK_REVIEW_PACKET_TEXT_FILE = REPORTS_DIR / "live_book_review_packet_latest.txt"


def text(value: Any, default: str = "") -> str:
    """Return a stripped string for stable comparisons and report rendering."""
    if value is None:
        return default
    rendered = str(value).strip()
    return rendered or default


def number(value: Any) -> float | None:
    """Parse loose broker/tracker values into floats without throwing."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("$", "").replace(",", "").replace("%", "").strip()
    if not cleaned or cleaned.upper() in {"N/A", "NA", "--", "-"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def safe_round(value: float | None, places: int = 2) -> float | None:
    """Round values while preserving missing data as None."""
    return round(value, places) if value is not None else None


def percentage(numerator: float | None, denominator: float | None) -> float | None:
    """Return a percentage while avoiding divide-by-zero failures."""
    if numerator is None or denominator in (None, 0):
        return None
    return (numerator / denominator) * 100


def infer_mark_price(position: dict[str, Any]) -> float | None:
    """Infer current per-share mark from mark value and quantity."""
    mark_value = number(position.get("markValue"))
    qty = number(position.get("qty"))
    if mark_value is None or qty in (None, 0):
        return None
    return mark_value / qty


def support_cushion_pct(mark_price: float | None, support: float | None) -> float | None:
    """Return how far price can fall before reaching support, as % of mark.

    Positive values mean the mark is above support. Negative values mean the
    name is already below the tracked support level.
    """
    if mark_price in (None, 0) or support is None:
        return None
    return ((mark_price - support) / mark_price) * 100


def resistance_headroom_pct(mark_price: float | None, resistance: float | None) -> float | None:
    """Return upside distance to resistance, as % of current mark."""
    if mark_price in (None, 0) or resistance is None:
        return None
    return ((resistance - mark_price) / mark_price) * 100


def earnings_window_bucket(days_until_earnings: float | None) -> str:
    """Classify catalyst proximity for review triage."""
    if days_until_earnings is None:
        return "unknown"
    if days_until_earnings < 0:
        return "stale-date"
    if days_until_earnings <= 7:
        return "immediate"
    if days_until_earnings <= 14:
        return "near"
    if days_until_earnings <= 30:
        return "watch"
    return "open-field"


def review_heat(position: dict[str, Any], math_block: dict[str, Any]) -> int:
    """Score urgency of review from 0 to 100.

    This is intentionally not an add/buy score. It is a blocker heat score:
    fragile posture, tight catalyst timing, weak conviction, low support
    cushion, and large book weight all increase the need for human review.
    """
    posture = text(position.get("posture")).lower()
    tracker = position.get("trackerContext") or {}
    flags = set(position.get("riskFlags") or [])

    heat = 0
    if posture == "fragile":
        heat += 40
    elif posture == "review":
        heat += 25

    if "earnings-soon" in flags:
        heat += 18
    if "fragile-alignment" in flags:
        heat += 18
    if "close-window" in flags:
        heat += 8

    conviction = number(position.get("convictionScore")) or 0.0
    heat += max(0, 30 - int(conviction / 2))

    weight = number(position.get("weightPct")) or 0.0
    if weight >= 20:
        heat += 10
    elif weight >= 15:
        heat += 6

    support_cushion = number(math_block.get("supportCushionPct"))
    if support_cushion is not None and support_cushion < 5:
        heat += 12

    resistance_headroom = number(math_block.get("resistanceHeadroomPct"))
    pl_percent = number(position.get("plPercent")) or 0.0
    # Positive P/L near resistance is not "bad"; it just deserves a trim/hold
    # decision before adding fresh capital.
    if resistance_headroom is not None and resistance_headroom < 5 and pl_percent > 0:
        heat += 8

    if text(tracker.get("alignmentLabel")).lower() == "developing":
        heat = max(0, heat - 8)

    return max(0, min(100, heat))


def unlock_effect(position: dict[str, Any]) -> str:
    """Explain how a position affects the capital preflight."""
    posture = text(position.get("posture")).lower()
    if posture == "fragile":
        return "hard-blocks-new-capital"
    if posture == "review":
        return "warning-before-adding"
    return "does-not-block"


def review_prompt(position: dict[str, Any], math_block: dict[str, Any]) -> list[str]:
    """Build practical operator prompts for the review packet."""
    ticker = text(position.get("symbol")).upper()
    prompts: list[str] = []
    posture = text(position.get("posture")).lower()
    tracker = position.get("trackerContext") or {}
    earnings_bucket = text(math_block.get("earningsBucket"))

    if posture == "fragile":
        prompts.append(
            f"Decide whether {ticker} still deserves to exist in the live book before adding any new exposure."
        )
        prompts.append(
            "Under current rules, a still-open fragile holding keeps capital deployment blocked."
        )
    if earnings_bucket in {"immediate", "near"}:
        prompts.append(
            f"Confirm whether the {ticker} earnings/catalyst plan is hold-through, trim-before, or exit-before."
        )
    if text(tracker.get("alignmentLabel")).lower() == "fragile":
        prompts.append(
            "Re-check support/resistance and trend alignment; the tracker currently calls structure fragile."
        )
    if number(math_block.get("resistanceHeadroomPct")) is not None and number(math_block.get("resistanceHeadroomPct")) < 5:
        prompts.append("Price is close to tracked resistance; review whether gains should be protected before adding elsewhere.")
    if not prompts:
        prompts.append("Routine monitor only; no deployment blocker from this holding.")
    return prompts


def build_position_packet(position: dict[str, Any]) -> dict[str, Any]:
    """Build one position's deployment-review math packet."""
    tracker = position.get("trackerContext") or {}
    mark_price = infer_mark_price(position)
    support = number(tracker.get("support"))
    resistance = number(tracker.get("resistance"))
    days_until_earnings = number(tracker.get("daysUntilEarnings"))
    mark_value = number(position.get("markValue"))
    pl_open = number(position.get("plOpen"))

    math_block = {
        "markPrice": safe_round(mark_price),
        "support": safe_round(support),
        "resistance": safe_round(resistance),
        "supportCushionPct": safe_round(support_cushion_pct(mark_price, support)),
        "resistanceHeadroomPct": safe_round(resistance_headroom_pct(mark_price, resistance)),
        "daysUntilEarnings": safe_round(days_until_earnings, 0),
        "earningsBucket": earnings_window_bucket(days_until_earnings),
        "plCushionPct": safe_round(number(position.get("plPercent"))),
        "plOpen": safe_round(pl_open),
        "plOpenPctOfPosition": safe_round(percentage(pl_open, mark_value)),
        "weightPct": safe_round(number(position.get("weightPct"))),
        "convictionScore": safe_round(number(position.get("convictionScore"))),
        "priority": safe_round(number(tracker.get("priority"))),
        "readyScore": safe_round(number(tracker.get("readyScore"))),
        "longTermScore": safe_round(number(tracker.get("longTermScore"))),
        "alignmentScore": safe_round(number(tracker.get("alignmentScore"))),
        "rvol": safe_round(number(tracker.get("rvol"))),
    }
    return {
        "symbol": text(position.get("symbol")).upper(),
        "posture": position.get("posture"),
        "actionLabel": position.get("actionLabel"),
        "unlockEffect": unlock_effect(position),
        "reviewHeat": review_heat(position, math_block),
        "math": math_block,
        "reasons": list(position.get("reasons") or []),
        "riskFlags": list(position.get("riskFlags") or []),
        "reviewPrompts": review_prompt(position, math_block),
        "trackerContext": tracker,
        "edgeContext": position.get("edgeContext"),
        "shadowContext": position.get("shadowContext"),
    }


def build_review_packet() -> dict[str, Any]:
    """Build and persist the live-book deployment review packet."""
    ensure_dirs()
    live_review = load_json_file(LIVE_POSITION_REVIEW_FILE) or {}
    capital = load_json_file(CAPITAL_DEPLOYMENT_READINESS_FILE) or {}
    positions = [
        build_position_packet(position)
        for position in (live_review.get("positions") or [])
        if isinstance(position, dict)
    ]
    positions.sort(
        key=lambda row: (
            row.get("unlockEffect") != "hard-blocks-new-capital",
            -(row.get("reviewHeat") or 0),
            row.get("symbol") or "",
        )
    )

    hard_blockers = [row for row in positions if row.get("unlockEffect") == "hard-blocks-new-capital"]
    warnings = [row for row in positions if row.get("unlockEffect") == "warning-before-adding"]
    supported = [row for row in positions if row.get("unlockEffect") == "does-not-block"]

    packet = {
        "generatedAt": local_now().isoformat(),
        "verdict": "blocked" if hard_blockers else "review" if warnings else "clear",
        "sourceLiveReviewGeneratedAt": live_review.get("generatedAt"),
        "sourceCapitalReadinessGeneratedAt": capital.get("generatedAt"),
        "capitalReadinessVerdict": capital.get("verdict"),
        "manualDeploymentAllowed": bool(capital.get("manualDeploymentAllowed")),
        "autoLiveAllowed": bool(capital.get("autoLiveAllowed")),
        "counts": {
            "positions": len(positions),
            "hardBlockers": len(hard_blockers),
            "warnings": len(warnings),
            "supported": len(supported),
        },
        "unlockChecklist": build_unlock_checklist(hard_blockers, warnings),
        "positions": positions,
    }
    save_review_packet(packet)
    return packet


def build_unlock_checklist(hard_blockers: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> list[str]:
    """Build the concise checklist that can unblock capital review."""
    checklist: list[str] = []
    for row in hard_blockers:
        ticker = text(row.get("symbol")).upper()
        checklist.append(
            f"Resolve {ticker}: current posture is fragile, so capital preflight stays blocked while it remains open/fragile."
        )
    for row in warnings:
        ticker = text(row.get("symbol")).upper()
        checklist.append(
            f"Review {ticker}: warning only, but do not add fresh exposure until catalyst/structure plan is explicit."
        )
    if not checklist:
        checklist.append("No live-book blocker from current positions; rerun capital readiness before sizing.")
    checklist.append("Rerun live account sync, live position review, this packet, and capital readiness after any manual decision.")
    checklist.append("Automation remains locked; any real order still requires explicit final confirmation.")
    return checklist


def render_review_packet(packet: dict[str, Any]) -> str:
    """Render the review packet into a concise operator memo."""
    counts = packet.get("counts") or {}
    lines = [
        "Inferno Live Book Review Packet",
        "",
        f"Generated: {packet.get('generatedAt')}",
        f"Verdict: {packet.get('verdict')}",
        f"Capital readiness: {packet.get('capitalReadinessVerdict')}",
        f"Manual deployment allowed: {packet.get('manualDeploymentAllowed')}",
        f"Auto live allowed: {packet.get('autoLiveAllowed')}",
        "",
        "Counts:",
        f"- Positions: {counts.get('positions', 0)}",
        f"- Hard blockers: {counts.get('hardBlockers', 0)}",
        f"- Review warnings: {counts.get('warnings', 0)}",
        f"- Supported: {counts.get('supported', 0)}",
        "",
        "Unlock checklist:",
    ]
    lines.extend(f"- {item}" for item in packet.get("unlockChecklist") or [])
    lines.append("")
    lines.append("Position math:")
    for row in packet.get("positions") or []:
        math_block = row.get("math") or {}
        lines.append(
            "- "
            f"{row.get('symbol')} | {row.get('unlockEffect')} | heat={row.get('reviewHeat')} | "
            f"posture={row.get('posture')} | score={math_block.get('convictionScore')} | "
            f"days={math_block.get('daysUntilEarnings')} ({math_block.get('earningsBucket')}) | "
            f"P/L={math_block.get('plCushionPct')}% | "
            f"support cushion={math_block.get('supportCushionPct')}% | "
            f"resistance room={math_block.get('resistanceHeadroomPct')}%"
        )
        for prompt in row.get("reviewPrompts") or []:
            lines.append(f"  review: {prompt}")
    return "\n".join(lines).rstrip() + "\n"


def save_review_packet(packet: dict[str, Any]) -> None:
    """Persist the JSON and text review-packet artifacts."""
    ensure_dirs()
    atomic_write_json(LIVE_BOOK_REVIEW_PACKET_FILE, packet)
    atomic_write_text(LIVE_BOOK_REVIEW_PACKET_TEXT_FILE, render_review_packet(packet))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for build/status usage."""
    parser = argparse.ArgumentParser(description="Build a live-book deployment review packet.")
    parser.add_argument("command", nargs="?", default="build", choices=("build", "status"))
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    if args.command == "status" and LIVE_BOOK_REVIEW_PACKET_TEXT_FILE.exists():
        print(LIVE_BOOK_REVIEW_PACKET_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    packet = build_review_packet()
    print(render_review_packet(packet))
    return 0 if packet.get("verdict") != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
