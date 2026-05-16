from __future__ import annotations

"""Per-ticker decision brief generator.

For each pending ticker in the approval queue, gather the operator-relevant
context from the canonical artifacts (snapshot rows, edge research, exposure
analytics, live position review) into a one-paragraph memo. The intent is to
collapse the time-to-decide step so the operator can walk the cadence batting
order in seconds per ticker instead of switching between five reports.

Strict contract:
- diagnostic / read-only. Cannot approve, reject, or mutate any ticker.
- pulls only from existing on-disk artifacts; no network calls.
- writes only to ``data/inferno_decision_briefs.json`` and
  ``reports/decision_briefs_latest.txt``.
- cannot affect authority, performance analytics, or strategy lab state.
"""

import argparse
import json
from typing import Any

from inferno_approval_queue import load_queue
from inferno_config import local_now
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
EDGE_RESEARCH_FILE = DATA_DIR / "inferno_edge_research.json"
EXPOSURE_ANALYTICS_FILE = DATA_DIR / "inferno_exposure_analytics.json"
LIVE_POSITION_REVIEW_FILE = DATA_DIR / "inferno_live_position_review.json"
DECISION_BRIEF_FILE = DATA_DIR / "inferno_decision_briefs.json"
DECISION_BRIEF_TEXT_FILE = REPORTS_DIR / "decision_briefs_latest.txt"
DECISION_BRIEF_STAGE = "decision-brief-diagnostic-only"


def _by_ticker(items: list[dict[str, Any]] | None, key: str = "ticker") -> dict[str, dict[str, Any]]:
    """Index a list of dicts by their ticker (or another key) for O(1) lookup."""
    if not items:
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for item in items:
        value = item.get(key)
        if value is None and key == "ticker":
            value = item.get("symbol")
        if value is None:
            continue
        indexed.setdefault(str(value).upper(), item)
    return indexed


def snapshot_row_for(ticker: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    rows = snapshot.get("rows") or []
    return _by_ticker(rows).get(ticker.upper(), {})


def edge_entry_for(ticker: str, edge: dict[str, Any]) -> dict[str, Any]:
    return _by_ticker(edge.get("ranked") or []).get(ticker.upper(), {})


def live_position_for(ticker: str, review: dict[str, Any]) -> dict[str, Any]:
    return _by_ticker(review.get("positions") or [], key="symbol").get(ticker.upper(), {})


def exposure_impact(ticker: str, exposure: dict[str, Any]) -> dict[str, Any]:
    """Quick read on whether the ticker is already inside the current slate."""
    sector_exposure = exposure.get("sectorExposure") or {}
    rows = sector_exposure.get("rows") or []
    ticker_row = _by_ticker(rows).get(ticker.upper(), {})
    return {
        "alreadyInSlate": bool(ticker_row),
        "sector": ticker_row.get("sector"),
        "industry": ticker_row.get("industry"),
        "riskUnits": ticker_row.get("riskUnits"),
        "intentStatus": ticker_row.get("intentStatus"),
        "largestSector": sector_exposure.get("largestSector"),
        "largestSectorShare": sector_exposure.get("largestSectorShare"),
        "setupShares": (exposure.get("setupExposure") or {}).get("setupShares") or {},
        "verdictLevel": (exposure.get("verdict") or {}).get("level"),
        "marketRegime": (exposure.get("marketRegime") or {}).get("regime"),
    }


def build_brief_for_ticker(
    ticker: str,
    *,
    approval_item: dict[str, Any] | None = None,
    snapshot: dict[str, Any],
    edge: dict[str, Any],
    exposure: dict[str, Any],
    live_review: dict[str, Any],
) -> dict[str, Any]:
    row = snapshot_row_for(ticker, snapshot)
    edge_entry = edge_entry_for(ticker, edge)
    live_pos = live_position_for(ticker, live_review)
    exposure_view = exposure_impact(ticker, exposure)

    market_context = row.get("marketContext") or {}
    trend_label = (market_context.get("trend") or {}).get("label")

    return {
        "ticker": ticker.upper(),
        "tracker": {
            "readiness": row.get("readiness"),
            "confidence": row.get("confidence"),
            "daysUntilEarnings": row.get("daysUntilEarnings"),
            "atrPercent": row.get("atrPercent"),
            "ivRank": row.get("ivRank"),
            "ivRankChange": row.get("ivRankChange"),
            "rec1": row.get("rec1"),
            "rec2": row.get("rec2"),
            "accumulationBias": row.get("accumulationBias"),
            "distanceToSupportPct": row.get("distanceToSupportPct"),
            "distanceToResistancePct": row.get("distanceToResistancePct"),
            "rvol": row.get("rvol") or market_context.get("rvol"),
            "trend": trend_label,
        },
        "edge": {
            "category": edge_entry.get("category"),
            "lane": edge_entry.get("lane"),
            "edgeScore": edge_entry.get("edgeScore"),
            "industry": edge_entry.get("industry") or exposure_view.get("industry"),
            "sector": edge_entry.get("sector") or exposure_view.get("sector"),
            "thesisFirstLine": (edge_entry.get("thesis") or "").split("\n", 1)[0],
        },
        "exposure": exposure_view,
        "liveBook": {
            "held": bool(live_pos),
            "posture": live_pos.get("posture"),
            "actionLabel": live_pos.get("actionLabel"),
            "bucket": live_pos.get("bucket"),
            "weightPct": live_pos.get("weightPct"),
            "plPercent": live_pos.get("plPercent"),
            "riskFlags": live_pos.get("riskFlags") or [],
            "reasons": live_pos.get("reasons") or [],
        },
        "approval": {
            "token": (approval_item or {}).get("approvalToken"),
            "replyApprove": (approval_item or {}).get("replyApprove"),
            "replyDeny": (approval_item or {}).get("replyDeny"),
            "replyApproveShort": (approval_item or {}).get("replyApproveShort"),
            "replyDenyShort": (approval_item or {}).get("replyDenyShort"),
        },
        "considerations": brief_considerations(
            row=row,
            edge_entry=edge_entry,
            exposure_view=exposure_view,
            live_pos=live_pos,
        ),
    }


def brief_considerations(
    *,
    row: dict[str, Any],
    edge_entry: dict[str, Any],
    exposure_view: dict[str, Any],
    live_pos: dict[str, Any],
) -> list[str]:
    """Return short human-readable bullets to support the operator decision."""
    bullets: list[str] = []
    days = row.get("daysUntilEarnings")
    if isinstance(days, (int, float)):
        if days <= 3:
            bullets.append(f"earnings imminent ({int(days)}d) — decide today or not at all")
        elif days <= 7:
            bullets.append(f"earnings inside the conviction window ({int(days)}d)")
    iv_rank = row.get("ivRank")
    if isinstance(iv_rank, (int, float)) and iv_rank >= 70:
        bullets.append(f"IV rank {iv_rank} — rich vol favors premium-selling structures")
    if isinstance(iv_rank, (int, float)) and iv_rank <= 25:
        bullets.append(f"IV rank {iv_rank} — cheap vol favors long premium")
    trend_label = (row.get("marketContext") or {}).get("trend", {}).get("label")
    if trend_label and trend_label.lower() in {"bearish", "down"}:
        bullets.append(f"trend label is {trend_label} — directional bull setups carry extra risk")
    if exposure_view.get("largestSector") and (exposure_view.get("largestSectorShare") or 0) >= 0.5:
        bullets.append(
            f"slate already heavy in {exposure_view['largestSector']} "
            f"({int((exposure_view['largestSectorShare'] or 0) * 100)}%)"
        )
    setup_shares = exposure_view.get("setupShares") or {}
    dominant_setup = max(setup_shares.items(), key=lambda kv: kv[1], default=(None, 0.0))
    if dominant_setup[0] and dominant_setup[1] >= 0.6:
        bullets.append(
            f"setup concentration on {dominant_setup[0]} is "
            f"{int(dominant_setup[1] * 100)}% — concentration governor may demote excess"
        )
    if live_pos:
        bullets.append(
            f"already held in live book (qty {live_pos.get('qty')}, "
            f"posture {live_pos.get('posture') or '-'}, "
            f"P/L {live_pos.get('plPercent')}%)"
        )
        for flag in (live_pos.get("riskFlags") or []):
            bullets.append(f"live-book flag: {flag}")
    if edge_entry.get("category"):
        bullets.append(f"edge bucket: {edge_entry.get('category')} (lane: {edge_entry.get('lane')})")
    if not bullets:
        bullets.append("no special considerations flagged from the current artifacts")
    return bullets


def build_decision_briefs(
    *,
    queue: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
    edge: dict[str, Any] | None = None,
    exposure: dict[str, Any] | None = None,
    live_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build briefs for every pending ticker in the approval queue."""
    queue = queue if queue is not None else load_queue()
    snapshot = snapshot if snapshot is not None else (load_json_file(SNAPSHOT_FILE) or {})
    edge = edge if edge is not None else (load_json_file(EDGE_RESEARCH_FILE) or {})
    exposure = exposure if exposure is not None else (load_json_file(EXPOSURE_ANALYTICS_FILE) or {})
    live_review = live_review if live_review is not None else (
        load_json_file(LIVE_POSITION_REVIEW_FILE) or {}
    )

    pending = [
        item for item in queue.get("items") or []
        if str(item.get("approvalStatus") or "").lower() == "pending"
    ]
    briefs = [
        build_brief_for_ticker(
            item.get("ticker") or "",
            approval_item=item,
            snapshot=snapshot,
            edge=edge,
            exposure=exposure,
            live_review=live_review,
        )
        for item in pending if item.get("ticker")
    ]
    return {
        "generatedAt": local_now().isoformat(),
        "stage": DECISION_BRIEF_STAGE,
        "diagnosticOnly": True,
        "queueGeneratedAt": queue.get("generatedAt"),
        "snapshotGeneratedAt": snapshot.get("generatedAt"),
        "edgeGeneratedAt": edge.get("generatedAt"),
        "exposureGeneratedAt": exposure.get("generatedAt"),
        "liveReviewGeneratedAt": live_review.get("generatedAt"),
        "pendingCount": len(pending),
        "briefs": briefs,
        "researchNotes": [
            "diagnostic only; cannot approve, reject, or move any ticker",
            "pulls only from on-disk artifacts; no network calls",
        ],
    }


def briefs_text(report: dict[str, Any]) -> str:
    lines = [
        "Inferno Decision Briefs (diagnostic-only)",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Stage: {report.get('stage')}",
        f"Pending tickers: {report.get('pendingCount', 0)}",
        "",
    ]
    if not report.get("briefs"):
        lines.append("No pending approvals — queue is clear.")
        return "\n".join(lines).rstrip() + "\n"
    for brief in report.get("briefs") or []:
        ticker = brief.get("ticker")
        tracker = brief.get("tracker") or {}
        edge = brief.get("edge") or {}
        live = brief.get("liveBook") or {}
        exposure = brief.get("exposure") or {}
        approval = brief.get("approval") or {}
        lines.extend([
            f"=== {ticker} ===",
            f"Tracker: readiness={tracker.get('readiness')} | "
            f"confidence={tracker.get('confidence')} | "
            f"daysToEarnings={tracker.get('daysUntilEarnings')} | "
            f"ivRank={tracker.get('ivRank')} | "
            f"atr%={tracker.get('atrPercent')} | "
            f"rec1={tracker.get('rec1')} | rec2={tracker.get('rec2')}",
            f"Market: rvol={tracker.get('rvol')} | trend={tracker.get('trend')} | "
            f"toSupport%={tracker.get('distanceToSupportPct')} | "
            f"toResistance%={tracker.get('distanceToResistancePct')}",
            f"Edge: category={edge.get('category')} | lane={edge.get('lane')} | "
            f"score={edge.get('edgeScore')} | sector={edge.get('sector')}",
            f"Live book: held={live.get('held')} | posture={live.get('posture') or '-'} | "
            f"P/L%={live.get('plPercent')} | weight%={live.get('weightPct')}",
            f"Slate: alreadyInSlate={exposure.get('alreadyInSlate')} | "
            f"largestSector={exposure.get('largestSector')} "
            f"({int((exposure.get('largestSectorShare') or 0) * 100)}%) | "
            f"regime={exposure.get('marketRegime')}",
            f"Reply desk: token={approval.get('token')} | "
            f"approve='{approval.get('replyApprove')}' | deny='{approval.get('replyDeny')}'",
            "Considerations:",
        ])
        for bullet in brief.get("considerations") or []:
            lines.append(f"  - {bullet}")
        lines.append("")
    lines.extend([
        "Reminders:",
        "- diagnostic only; nothing here changes ticket state",
        "- approve/reject decisions still flow through inferno_approval_queue.py",
    ])
    return "\n".join(lines).rstrip() + "\n"


def save_decision_briefs(report: dict[str, Any]) -> None:
    ensure_dirs()
    DECISION_BRIEF_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    DECISION_BRIEF_TEXT_FILE.write_text(briefs_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Per-ticker decision brief generator. Builds one paragraph of "
            "context per pending approval. Diagnostic only."
        )
    )
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and DECISION_BRIEF_TEXT_FILE.exists():
        print(DECISION_BRIEF_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = build_decision_briefs()
    save_decision_briefs(report)
    print(briefs_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
