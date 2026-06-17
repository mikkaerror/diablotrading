from __future__ import annotations

"""Read-only live holdings review for the Inferno desk.

This module sits between broker visibility and any future execution workflow.
It does not trade. It simply grades the currently synced live holdings against
three things we already trust:

1. tracker conviction and market-context alignment from the live sync artifact
2. shadow evidence, so we can see whether a ticker's research lane is strong
3. edge research, so long-term shovel conviction is visible beside the book

The result is one durable review artifact that helps the desk decide what needs
attention next week before a human ever considers adding or reducing exposure.
"""

import argparse
import json
from collections import Counter, defaultdict
from typing import Any

from inferno_config import local_now
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


LIVE_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_live_account_sync.json"
SHADOW_EVIDENCE_FILE = DATA_DIR / "inferno_shadow_evidence.json"
EDGE_RESEARCH_FILE = DATA_DIR / "inferno_edge_research.json"
OPERATOR_LONG_TERM_HOLDS_FILE = DATA_DIR / "operator_long_term_holds.json"

LIVE_POSITION_REVIEW_FILE = DATA_DIR / "inferno_live_position_review.json"
LIVE_POSITION_REVIEW_TEXT_FILE = REPORTS_DIR / "live_position_review_latest.txt"


def text(value: Any) -> str:
    """Normalize loose values into trimmed text."""
    return str(value or "").strip()


def numeric(value: Any) -> float | None:
    """Parse loose dashboard/broker values into floats when possible."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = text(value).replace("$", "").replace(",", "").replace("%", "")
    if not raw or raw in {"N/A", "--"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def load_operator_long_term_holds(path: Any = OPERATOR_LONG_TERM_HOLDS_FILE) -> set[str]:
    """Load operator-declared long-term core holds from a tiny JSON config."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    except (OSError, json.JSONDecodeError):
        return set()

    raw_symbols = payload.get("symbols") if isinstance(payload, dict) else payload
    if not isinstance(raw_symbols, list):
        return set()
    return {
        text(symbol).upper()
        for symbol in raw_symbols
        if text(symbol)
    }


def load_edge_index(edge_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return edge research rows by ticker."""
    ranked = edge_payload.get("ranked") or []
    return {
        text(row.get("ticker")).upper(): row
        for row in ranked
        if isinstance(row, dict) and text(row.get("ticker"))
    }


def shadow_summary_by_ticker(shadow_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Aggregate shadow evidence into one compact ticker-level view."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in shadow_payload.get("items") or []:
        ticker = text(item.get("ticker")).upper()
        if ticker:
            grouped[ticker].append(item)

    summary: dict[str, dict[str, Any]] = {}
    for ticker, items in grouped.items():
        closed = [item for item in items if text((item.get("outcome") or {}).get("status")) == "closed"]
        open_items = [item for item in items if text((item.get("outcome") or {}).get("status")) == "open"]
        returns = [
            numeric((item.get("outcome") or {}).get("estimatedReturnOnRisk"))
            for item in closed
            if numeric((item.get("outcome") or {}).get("estimatedReturnOnRisk")) is not None
        ]
        pnls = [
            numeric((item.get("outcome") or {}).get("estimatedPnl"))
            for item in closed
            if numeric((item.get("outcome") or {}).get("estimatedPnl")) is not None
        ]
        wins = [pnl for pnl in pnls if pnl > 0]
        latest = max(
            items,
            key=lambda item: (
                text((item.get("outcome") or {}).get("reviewedAt")),
                text(item.get("tradeDate")),
                text(item.get("createdAt")),
            ),
        )
        summary[ticker] = {
            "trackedCount": len(items),
            "openCount": len(open_items),
            "closedCount": len(closed),
            "winRate": round(len(wins) / len(pnls), 4) if pnls else None,
            "avgReturnOnRisk": round(sum(returns) / len(returns), 6) if returns else None,
            "avgPnl": round(sum(pnls) / len(pnls), 2) if pnls else None,
            "latestStrategy": latest.get("strategy"),
            "latestOutcomeStatus": (latest.get("outcome") or {}).get("status"),
            "latestTradeDate": latest.get("tradeDate"),
            "latestBlockReasons": list((latest.get("blockReasons") or [])[:3]),
        }
    return summary


def conviction_score(position: dict[str, Any], edge_row: dict[str, Any] | None, shadow: dict[str, Any] | None) -> float:
    """Blend tracker, market-structure, and research evidence into one score.

    This is not an execution score. It is a triage score for the existing live
    book so we can quickly see which names deserve calm attention.
    """
    tracker = position.get("trackerContext") or {}
    alignment_label = text(tracker.get("alignmentLabel")).lower()
    long_term_score = numeric(tracker.get("longTermScore")) or 0.0
    ready_score = numeric(tracker.get("readyScore")) or 0.0
    priority = numeric(tracker.get("priority")) or 0.0

    score = long_term_score * 8 + ready_score * 8 + priority * 3
    if alignment_label == "aligned":
        score += 18
    elif alignment_label == "developing":
        score += 8
    elif alignment_label == "fragile":
        score -= 12

    if edge_row:
        score += (numeric(edge_row.get("edgeScore")) or 0.0) * 0.15
    if shadow:
        shadow_r = numeric(shadow.get("avgReturnOnRisk"))
        if shadow_r is not None:
            score += shadow_r * 12
        if (shadow.get("closedCount") or 0) >= 2 and (shadow.get("winRate") or 0.0) >= 0.6:
            score += 6

    for flag in position.get("riskFlags") or []:
        if flag == "concentration":
            score -= 10
        elif flag == "fragile-alignment":
            score -= 8
        elif flag == "earnings-soon":
            score -= 6
        elif flag == "drawdown":
            score -= 8
        elif flag == "close-window":
            score -= 5
        elif flag == "untracked":
            score -= 18

    return round(max(0.0, min(score, 100.0)), 2)


def posture_for_position(
    position: dict[str, Any],
    edge_row: dict[str, Any] | None,
    shadow: dict[str, Any] | None,
    score: float,
    operator_hold_symbols: set[str] | None = None,
) -> tuple[str, str, list[str]]:
    """Return a live-book posture, action label, and reasons for one holding."""
    ticker = text(position.get("symbol")).upper()
    tracker = position.get("trackerContext") or {}
    flags = set(position.get("riskFlags") or [])
    reasons: list[str] = []

    if "untracked" in flags:
        reasons.append("not represented in the tracker snapshot")
    if "fragile-alignment" in flags:
        reasons.append("market-context alignment is fragile")
    if "earnings-soon" in flags:
        reasons.append("earnings window is close")
    if "concentration" in flags:
        reasons.append("position size is concentrated")

    if edge_row and text(edge_row.get("lane")) == "Long-Term Shovel Accumulation":
        reasons.append("edge research still likes this as a long-term shovel")
    if shadow and (shadow.get("closedCount") or 0) > 0:
        reasons.append(
            f"shadow evidence: {shadow.get('closedCount')} closed / win {shadow.get('winRate')}"
        )

    if ticker in (operator_hold_symbols or set()) and "untracked" not in flags:
        reasons.append("operator-declared long-term hold; not a fresh-capital blocker")
        return "supported", "hold-core", reasons

    if "untracked" in flags or score < 35:
        return "fragile", "manual-review", reasons or ["weak conviction stack"]
    if "concentration" in flags or "earnings-soon" in flags or "fragile-alignment" in flags or score < 55:
        return "review", "review-before-adding", reasons or ["mixed conviction stack"]
    if text(position.get("bucket")) == "long-term-core" and score >= 70:
        return "supported", "hold-core", reasons or ["long-term core still supported"]
    if score >= 55:
        return "constructive", "hold-and-monitor", reasons or ["constructive but not fully clean"]
    return "review", "review-before-adding", reasons or ["mixed conviction stack"]


def build_position_review(
    position: dict[str, Any],
    edge_index: dict[str, dict[str, Any]],
    shadow_index: dict[str, dict[str, Any]],
    operator_hold_symbols: set[str] | None = None,
) -> dict[str, Any]:
    """Build one live holding review packet."""
    ticker = text(position.get("symbol")).upper()
    edge_row = edge_index.get(ticker)
    shadow = shadow_index.get(ticker)
    score = conviction_score(position, edge_row, shadow)
    operator_declared = ticker in (operator_hold_symbols or set())
    posture, action, reasons = posture_for_position(position, edge_row, shadow, score, operator_hold_symbols)
    tracker = position.get("trackerContext") or {}
    return {
        "symbol": ticker,
        "qty": position.get("qty"),
        "markValue": position.get("markValue"),
        "weightPct": position.get("weightPct"),
        "plOpen": position.get("plOpen"),
        "plPercent": position.get("plPercent"),
        "bucket": position.get("bucket"),
        "riskFlags": list(position.get("riskFlags") or []),
        "convictionScore": score,
        "posture": posture,
        "actionLabel": action,
        "operatorLongTermHold": operator_declared,
        "reasons": reasons,
        "trackerContext": tracker,
        "edgeContext": (
            {
                "lane": edge_row.get("lane"),
                "category": edge_row.get("category"),
                "edgeScore": edge_row.get("edgeScore"),
                "thesis": edge_row.get("thesis"),
            }
            if edge_row
            else None
        ),
        "shadowContext": shadow,
    }


def build_live_position_review(*, refresh_live_sync: bool = False) -> dict[str, Any]:
    """Build the live-position review artifact from existing read-only desk data."""
    ensure_dirs()

    from inferno_live_account_sync import build_live_account_sync

    live_sync = build_live_account_sync(refresh_statement=refresh_live_sync) if refresh_live_sync else (load_json_file(LIVE_ACCOUNT_SYNC_FILE) or {})
    if not live_sync:
        live_sync = build_live_account_sync(refresh_statement=False)

    edge_payload = load_json_file(EDGE_RESEARCH_FILE) or {}
    shadow_payload = load_json_file(SHADOW_EVIDENCE_FILE) or {}
    edge_index = load_edge_index(edge_payload)
    shadow_index = shadow_summary_by_ticker(shadow_payload)
    operator_hold_symbols = load_operator_long_term_holds()

    report: dict[str, Any] = {
        "generatedAt": local_now().isoformat(),
        "ok": False,
        "verdict": "blocked",
        "message": "",
        "liveSyncGeneratedAt": live_sync.get("generatedAt"),
        "matchedSuffix": live_sync.get("matchedSuffix"),
        "positions": [],
        "counts": {
            "positions": 0,
            "supported": 0,
            "constructive": 0,
            "review": 0,
            "fragile": 0,
            "operatorLongTermHolds": 0,
            "withEdgeContext": 0,
            "withShadowContext": 0,
        },
        "nextActions": [],
    }

    if not live_sync.get("ok"):
        report["message"] = text(live_sync.get("message")) or "live account sync unavailable"
        save_live_position_review(report)
        return report

    reviews = [
        build_position_review(position, edge_index, shadow_index, operator_hold_symbols)
        for position in (live_sync.get("positions") or [])
    ]
    reviews.sort(key=lambda row: (numeric(row.get("weightPct")) or 0.0, numeric(row.get("convictionScore")) or 0.0), reverse=True)

    posture_counts = Counter(text(row.get("posture")) for row in reviews)
    report["positions"] = reviews
    report["counts"] = {
        "positions": len(reviews),
        "supported": posture_counts.get("supported", 0),
        "constructive": posture_counts.get("constructive", 0),
        "review": posture_counts.get("review", 0),
        "fragile": posture_counts.get("fragile", 0),
        "operatorLongTermHolds": sum(1 for row in reviews if row.get("operatorLongTermHold")),
        "withEdgeContext": sum(1 for row in reviews if row.get("edgeContext")),
        "withShadowContext": sum(1 for row in reviews if row.get("shadowContext")),
    }

    next_actions: list[str] = []
    review_names = [row["symbol"] for row in reviews if row.get("posture") in {"review", "fragile"}]
    fragile_names = [row["symbol"] for row in reviews if row.get("posture") == "fragile"]
    if fragile_names:
        next_actions.append(f"Manual risk review: {', '.join(fragile_names)}.")
    if review_names and not fragile_names:
        next_actions.append(f"Re-check structure before adding: {', '.join(review_names)}.")
    if any("concentration" in (row.get("riskFlags") or []) for row in reviews):
        next_actions.append("One or more positions are concentrated; confirm sizing before layering exposure.")
    if any("earnings-soon" in (row.get("riskFlags") or []) for row in reviews):
        next_actions.append("At least one live name is near earnings; reconfirm catalyst plan before next week.")
    declared_holds = [row["symbol"] for row in reviews if row.get("operatorLongTermHold")]
    if declared_holds:
        next_actions.append(
            f"Declared long-term holds do not block fresh-capital review: {', '.join(declared_holds)}."
        )
    if not next_actions:
        next_actions.append("Live book is tracker-aligned and only needs routine monitoring.")
    report["nextActions"] = next_actions

    if report["counts"]["fragile"] > 0:
        report["verdict"] = "review"
        report["ok"] = True
        report["message"] = "live book synced; at least one holding needs operator review"
    else:
        report["verdict"] = "healthy"
        report["ok"] = True
        report["message"] = "live book synced and tracker-aligned"

    save_live_position_review(report)
    return report


def live_position_review_text(report: dict[str, Any]) -> str:
    """Render the live-position review into a compact operator memo."""
    counts = report.get("counts") or {}
    lines = [
        "Inferno Live Position Review",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Verdict: {report.get('verdict')}",
        f"Message: {report.get('message')}",
        f"Live sync source: {report.get('liveSyncGeneratedAt') or '-'}",
        f"Matched suffix: {report.get('matchedSuffix') or '-'}",
        f"Positions: {counts.get('positions', 0)}",
        f"Supported: {counts.get('supported', 0)}",
        f"Constructive: {counts.get('constructive', 0)}",
        f"Review: {counts.get('review', 0)}",
        f"Fragile: {counts.get('fragile', 0)}",
        f"Declared long-term holds: {counts.get('operatorLongTermHolds', 0)}",
        f"Edge context: {counts.get('withEdgeContext', 0)}",
        f"Shadow context: {counts.get('withShadowContext', 0)}",
        "",
        "Next actions:",
    ]
    for action in report.get("nextActions") or []:
        lines.append(f"- {action}")
    lines.append("")
    lines.append("Positions:")
    for row in report.get("positions") or []:
        tracker = row.get("trackerContext") or {}
        edge = row.get("edgeContext") or {}
        shadow = row.get("shadowContext") or {}
        lines.append(
            "- "
            + f"{row.get('symbol')} | {row.get('actionLabel')} | posture={row.get('posture')} | "
            + f"score={row.get('convictionScore')} | weight={row.get('weightPct') or '-'}% | "
            + f"P/L%={row.get('plPercent') or '-'} | "
            + f"declaredHold={bool(row.get('operatorLongTermHold'))} | "
            + f"align={tracker.get('alignmentLabel') or '-'} | "
            + f"edge={edge.get('edgeScore') or '-'} | "
            + f"shadowR={shadow.get('avgReturnOnRisk') if shadow else '-'}"
        )
        if row.get("reasons"):
            lines.append(f"  reasons: {'; '.join(row.get('reasons')[:4])}")
    return "\n".join(lines).rstrip() + "\n"


def save_live_position_review(report: dict[str, Any]) -> None:
    """Persist the live-position review JSON and text artifacts."""
    ensure_dirs()
    LIVE_POSITION_REVIEW_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    LIVE_POSITION_REVIEW_TEXT_FILE.write_text(live_position_review_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse the tiny CLI surface for build/status usage."""
    parser = argparse.ArgumentParser(description="Review live holdings against tracker and shadow evidence.")
    parser.add_argument("command", nargs="?", choices=("build", "status"), default="build")
    parser.add_argument(
        "--refresh-live-sync",
        action="store_true",
        help="Rebuild the read-only live account sync before reviewing holdings.",
    )
    return parser.parse_args()


def main() -> int:
    """Build or print the live-position review report."""
    args = parse_args()
    if args.command == "status" and LIVE_POSITION_REVIEW_TEXT_FILE.exists():
        print(LIVE_POSITION_REVIEW_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = build_live_position_review(refresh_live_sync=args.refresh_live_sync)
    print(live_position_review_text(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
