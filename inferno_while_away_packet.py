from __future__ import annotations

"""Build the phone-readable while-away packet for the Inferno desk.

The Vegas/travel window needs one calm artifact: what is true, what is blocked,
what can be monitored casually, and what still needs deliberate human review.
This module is read-only. It never touches TOS, Schwab order endpoints, Sheets,
approval queues, or authority. It only aggregates already-written desk
artifacts into ``reports/while_away_latest.txt``.
"""

import argparse
import json
from typing import Any

from inferno_config import ROOT, local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


WHILE_AWAY_PACKET_FILE = DATA_DIR / "inferno_while_away_packet.json"
WHILE_AWAY_PACKET_TEXT_FILE = REPORTS_DIR / "while_away_latest.txt"
WHILE_AWAY_STAGE = "while-away-operator-packet"

SCHWAB_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_schwab_account_sync.json"
LIVE_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_live_account_sync.json"
LIVE_POSITION_REVIEW_FILE = DATA_DIR / "inferno_live_position_review.json"
LIVE_BOOK_REVIEW_PACKET_FILE = DATA_DIR / "inferno_live_book_review_packet.json"
CAPITAL_DEPLOYMENT_READINESS_FILE = DATA_DIR / "inferno_capital_deployment_readiness.json"
RISK_GATE_AUDIT_FILE = DATA_DIR / "inferno_risk_gate_audit.json"
TOS_METRIC_THEORY_AUDIT_FILE = DATA_DIR / "inferno_tos_metric_theory_audit.json"
SCHWAB_TOS_METRICS_SYNC_FILE = DATA_DIR / "inferno_schwab_tos_metrics_sync.json"
PAPER_TEST_DIRECTOR_FILE = DATA_DIR / "inferno_paper_test_director.json"
STRATEGY_SHADOW_COMPARISON_FILE = DATA_DIR / "inferno_strategy_shadow_comparison.json"
CAPITAL_SCALING_FILE = DATA_DIR / "inferno_capital_scaling.json"


def text(value: Any, default: str = "") -> str:
    """Normalize display text."""
    if value is None:
        return default
    rendered = str(value).strip()
    return rendered or default


def number(value: Any) -> float | None:
    """Parse loose numeric artifact values."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = text(value).replace("$", "").replace(",", "").replace("%", "")
    if not cleaned or cleaned.upper() in {"N/A", "NA", "NAN", "--"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def safe_round(value: Any, digits: int = 2) -> float | None:
    """Round optional numbers while preserving missing values."""
    parsed = number(value)
    return round(parsed, digits) if parsed is not None else None


def money(value: Any) -> str:
    """Render optional dollars."""
    parsed = number(value)
    return "-" if parsed is None else f"${parsed:,.2f}"


def status_value(payload: dict[str, Any], *keys: str, default: str = "missing") -> str:
    """Return the first non-empty status-like value from an artifact."""
    if not payload:
        return default
    for key in keys or ("verdict", "status", "stage"):
        value = text(payload.get(key))
        if value:
            return value
    return "unknown"


def top_positions(live_book: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    """Return the most important live-book rows for a small screen."""
    rows: list[dict[str, Any]] = []
    for row in live_book.get("positions") or []:
        if not isinstance(row, dict):
            continue
        math_block = row.get("math") or {}
        rows.append(
            {
                "symbol": text(row.get("symbol")).upper(),
                "unlockEffect": row.get("unlockEffect"),
                "posture": row.get("posture"),
                "reviewHeat": row.get("reviewHeat"),
                "weightPct": safe_round(math_block.get("weightPct")),
                "plPct": safe_round(math_block.get("plCushionPct")),
                "supportCushionPct": safe_round(math_block.get("supportCushionPct")),
                "resistanceHeadroomPct": safe_round(math_block.get("resistanceHeadroomPct")),
                "firstPrompt": (row.get("reviewPrompts") or [""])[0],
            }
        )
    rows.sort(
        key=lambda item: (
            item.get("unlockEffect") != "hard-blocks-new-capital",
            -(number(item.get("reviewHeat")) or 0),
            item.get("symbol") or "",
        )
    )
    return rows[:limit]


def failed_gate_summaries(risk_gate: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the risk gates that matter while traveling."""
    gates: list[dict[str, Any]] = []
    for gate in risk_gate.get("gates") or []:
        if not isinstance(gate, dict):
            continue
        if gate.get("status") not in {"fail", "warn"}:
            continue
        gates.append(
            {
                "id": gate.get("id"),
                "name": gate.get("name"),
                "severity": gate.get("severity"),
                "status": gate.get("status"),
                "detail": gate.get("detail"),
                "nextAction": gate.get("nextAction"),
            }
        )
    return gates


def double_count_register(theory_audit: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert high-correlation pairs into explicit scoring guardrails."""
    register: list[dict[str, Any]] = []
    pairs = (theory_audit.get("redundancy") or {}).get("highCorrelationPairs") or []
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        left = text(pair.get("left"))
        right = text(pair.get("right"))
        if not left or not right:
            continue
        register.append(
            {
                "left": left,
                "right": right,
                "spearman": safe_round(pair.get("spearman"), 4),
                "policy": "Use as one evidence family; do not add both as independent conviction points.",
            }
        )
    return register


def formula_roles(theory_audit: dict[str, Any]) -> list[dict[str, Any]]:
    """Summarize what each TOS-derived formula is allowed to prove."""
    roles: list[dict[str, Any]] = []
    theory = theory_audit.get("formulaTheory") or {}
    for key, item in theory.items():
        if not isinstance(item, dict):
            continue
        roles.append(
            {
                "metric": key,
                "verdict": item.get("theoryVerdict"),
                "role": item.get("decisionRole"),
                "preferredCompanion": item.get("preferredCompanion"),
            }
        )
    return roles


def shadow_comparison_summary(shadow: dict[str, Any]) -> dict[str, Any]:
    """Summarize the condor/alternative shadow register without staging."""
    register = [row for row in shadow.get("register") or [] if isinstance(row, dict)]
    return {
        "verdict": shadow.get("verdict"),
        "counts": shadow.get("counts") or {},
        "top": [
            {
                "ticker": row.get("ticker"),
                "status": row.get("registerStatus"),
                "strategy": ((row.get("bestPassingVariant") or {}).get("strategy")),
                "expiration": (((row.get("bestPassingVariant") or {}).get("plan") or {}).get("expiration")),
                "paperStageAllowed": bool(shadow.get("paperStageAllowed")),
            }
            for row in register[:5]
        ],
    }


def decide_verdict(
    *,
    capital: dict[str, Any],
    risk_gate: dict[str, Any],
    live_book: dict[str, Any],
) -> str:
    """Collapse the travel posture into a single operator verdict."""
    capital_verdict = status_value(capital)
    risk_verdict = status_value(risk_gate)
    live_counts = live_book.get("counts") or {}
    hard_blockers = int(number(live_counts.get("hardBlockers")) or 0)

    if capital_verdict == "not-ready" or risk_verdict == "blocked" or hard_blockers:
        return "monitor-only"
    if capital.get("manualDeploymentAllowed"):
        return "manual-review-ready"
    return "research-only"


def build_action_lists(verdict: str, live_book: dict[str, Any]) -> dict[str, list[str]]:
    """Return what the operator can and cannot do from the packet."""
    allowed = [
        "Read this packet and the live-book packet before making any manual decision.",
        "Refresh read-only Schwab account truth and derived reports.",
        "Track paper/shadow evidence and formula-theory warnings.",
    ]
    if verdict == "manual-review-ready":
        allowed.append("Consider manual orders only after a fresh capital-readiness rerun and explicit final confirmation.")
    else:
        allowed.append("Make notes and plan trims; keep fresh exposure off until blockers clear.")

    blocked = [
        "No automated broker submit.",
        "No live order from this packet.",
        "No fresh exposure while live-book hard blockers remain.",
        "No treating correlated TOS companions as separate confirmation votes.",
    ]

    focus = list(live_book.get("unlockChecklist") or [])
    if not focus:
        focus = ["No live-book checklist found; rerun the live book packet before acting."]
    return {"allowed": allowed, "blocked": blocked, "focus": focus[:8]}


def build_while_away_packet() -> dict[str, Any]:
    """Build and persist the while-away operator packet."""
    ensure_dirs()
    schwab_account = load_json_file(SCHWAB_ACCOUNT_SYNC_FILE) or {}
    live_sync = load_json_file(LIVE_ACCOUNT_SYNC_FILE) or {}
    live_review = load_json_file(LIVE_POSITION_REVIEW_FILE) or {}
    live_book = load_json_file(LIVE_BOOK_REVIEW_PACKET_FILE) or {}
    capital = load_json_file(CAPITAL_DEPLOYMENT_READINESS_FILE) or {}
    risk_gate = load_json_file(RISK_GATE_AUDIT_FILE) or {}
    theory_audit = load_json_file(TOS_METRIC_THEORY_AUDIT_FILE) or {}
    schwab_metrics = load_json_file(SCHWAB_TOS_METRICS_SYNC_FILE) or {}
    paper_director = load_json_file(PAPER_TEST_DIRECTOR_FILE) or {}
    shadow = load_json_file(STRATEGY_SHADOW_COMPARISON_FILE) or {}
    capital_scaling = load_json_file(CAPITAL_SCALING_FILE) or {}

    verdict = decide_verdict(capital=capital, risk_gate=risk_gate, live_book=live_book)
    action_lists = build_action_lists(verdict, live_book)
    guardrails = capital.get("guardrails") or {}
    risk_summary = risk_gate.get("summary") or {}

    packet = {
        "generatedAt": local_now().isoformat(),
        "stage": WHILE_AWAY_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authority": {
            "brokerSubmitAllowed": False,
            "liveTradingAllowed": False,
            "touchesTos": False,
            "touchesBrokerOrders": False,
            "touchesSheets": False,
        },
        "verdict": verdict,
        "account": {
            "source": live_sync.get("accountDataSource") or "schwab-account-api",
            "schwabVerdict": schwab_account.get("verdict"),
            "liveSyncVerdict": live_sync.get("verdict"),
            "matchedSuffix": live_sync.get("matchedSuffix") or schwab_account.get("matchedSuffix"),
            "netLiquidatingValue": safe_round(live_sync.get("netLiquidatingValue") or schwab_account.get("netLiquidatingValue")),
            "totalCash": safe_round(live_sync.get("totalCash") or schwab_account.get("totalCash")),
            "positions": (schwab_account.get("counts") or {}).get("positions"),
            "generatedAt": live_sync.get("generatedAt") or schwab_account.get("generatedAt"),
        },
        "capital": {
            "verdict": capital.get("verdict"),
            "deploymentDate": capital.get("deploymentDate"),
            "manualDeploymentAllowed": bool(capital.get("manualDeploymentAllowed")),
            "autoLiveAllowed": bool(capital.get("autoLiveAllowed")),
            "deployableCash": safe_round(guardrails.get("deployableCash")),
            "maxOptionsRisk": safe_round(guardrails.get("maxOptionsRisk")),
            "maxStarterTicket": safe_round(guardrails.get("maxStarterTicket")),
            "maxLongTermBuy": safe_round(guardrails.get("maxLongTermBuy")),
            "reserveCash": safe_round(guardrails.get("reserveCash")),
            "blockers": capital.get("blockers") or [],
            "warnings": capital.get("warnings") or [],
        },
        "risk": {
            "verdict": risk_gate.get("verdict"),
            "hardFails": risk_summary.get("hardFails"),
            "promotionFails": risk_summary.get("promotionFails"),
            "warnings": risk_summary.get("warnings"),
            "blockedGateIds": risk_summary.get("blockedGateIds") or [],
            "failedOrWarningGates": failed_gate_summaries(risk_gate),
        },
        "liveBook": {
            "verdict": live_book.get("verdict"),
            "liveReviewVerdict": live_review.get("verdict"),
            "counts": live_book.get("counts") or {},
            "topPositions": top_positions(live_book),
        },
        "formulaPolicy": {
            "schwabMetricsSourceStatus": schwab_metrics.get("sourceStatus"),
            "customMetricsVerdict": schwab_metrics.get("customMetricsVerdict"),
            "metricValueCount": schwab_metrics.get("metricValueCount"),
            "theoryVerdict": theory_audit.get("verdict"),
            "postureCounts": theory_audit.get("postureCounts") or {},
            "roles": formula_roles(theory_audit),
            "doubleCountRegister": double_count_register(theory_audit),
            "nextActions": theory_audit.get("nextActions") or [],
        },
        "paperEvidence": {
            "verdict": paper_director.get("verdict"),
            "counts": paper_director.get("counts") or {},
            "capitalScalingVerdict": capital_scaling.get("verdict"),
        },
        "shadowComparisons": shadow_comparison_summary(shadow),
        "operatorActions": action_lists,
        "refreshCommands": [
            f'cd "{ROOT}"',
            "./run_inferno_schwab_account_sync.sh --json",
            "./run_inferno_live_account_sync.sh build",
            "./run_inferno_live_position_review.sh build",
            "./run_inferno_live_book_review_packet.sh",
            "./run_inferno_schwab_tos_metrics_sync.sh --from-snapshot --limit 12 --json",
            "./run_inferno_tos_metric_theory_audit.sh --limit 12",
            "./run_inferno_while_away_packet.sh",
        ],
    }
    save_while_away_packet(packet)
    return packet


def render_while_away_packet(packet: dict[str, Any]) -> str:
    """Render a compact report intended for a phone screen."""
    account = packet.get("account") or {}
    capital = packet.get("capital") or {}
    risk = packet.get("risk") or {}
    live_book = packet.get("liveBook") or {}
    formula = packet.get("formulaPolicy") or {}
    paper = packet.get("paperEvidence") or {}
    shadow = packet.get("shadowComparisons") or {}
    actions = packet.get("operatorActions") or {}

    lines = [
        "Inferno While Away Packet",
        "",
        f"Generated: {packet.get('generatedAt')}",
        f"Verdict: {packet.get('verdict')}",
        f"Authority: research-only; broker submit OFF; live automation OFF",
        "",
        "Account truth:",
        f"- Source: {account.get('source')} | Schwab {account.get('schwabVerdict')} | live sync {account.get('liveSyncVerdict')}",
        f"- NLV: {money(account.get('netLiquidatingValue'))} | cash: {money(account.get('totalCash'))} | positions: {account.get('positions')}",
        "",
        "Capital guardrails:",
        f"- Readiness: {capital.get('verdict')} | manual allowed {capital.get('manualDeploymentAllowed')} | auto-live {capital.get('autoLiveAllowed')}",
        f"- Deployable cash {money(capital.get('deployableCash'))} | max options risk {money(capital.get('maxOptionsRisk'))} | reserve {money(capital.get('reserveCash'))}",
        "",
        "Risk blockers:",
        f"- Risk gate: {risk.get('verdict')} | hard fails {risk.get('hardFails')} | promotion fails {risk.get('promotionFails')} | warnings {risk.get('warnings')}",
    ]
    for item in (capital.get("blockers") or [])[:5]:
        lines.append(f"- Capital blocker: {item}")
    for gate in (risk.get("failedOrWarningGates") or [])[:6]:
        lines.append(f"- {gate.get('status')}: {gate.get('name')} | {gate.get('detail')}")

    counts = live_book.get("counts") or {}
    lines.extend(
        [
            "",
            "Live book focus:",
            f"- Packet: {live_book.get('verdict')} | hard blockers {counts.get('hardBlockers', 0)} | warnings {counts.get('warnings', 0)} | supported {counts.get('supported', 0)}",
        ]
    )
    for row in live_book.get("topPositions") or []:
        lines.append(
            "- "
            f"{row.get('symbol')}: {row.get('unlockEffect')} | heat {row.get('reviewHeat')} | "
            f"weight {row.get('weightPct')}% | P/L {row.get('plPct')}% | "
            f"resistance room {row.get('resistanceHeadroomPct')}%"
        )
        if row.get("firstPrompt"):
            lines.append(f"  review: {row.get('firstPrompt')}")

    lines.extend(
        [
            "",
            "Formula and double-count guard:",
            f"- Schwab custom metrics: {formula.get('customMetricsVerdict')} | values {formula.get('metricValueCount')} | theory {formula.get('theoryVerdict')}",
        ]
    )
    pairs = formula.get("doubleCountRegister") or []
    if pairs:
        for pair in pairs[:5]:
            lines.append(
                f"- Do not double-count {pair.get('left')} + {pair.get('right')} "
                f"(spearman {pair.get('spearman')})"
            )
    else:
        lines.append("- No high-correlation pairs flagged.")

    lines.extend(
        [
            "",
            "Paper and shadow evidence:",
            f"- Paper director: {paper.get('verdict')} | counts {json.dumps(paper.get('counts') or {})}",
            f"- Capital scaling: {paper.get('capitalScalingVerdict')}",
            f"- Shadow comparisons: {shadow.get('verdict')} | counts {json.dumps(shadow.get('counts') or {})}",
        ]
    )
    for item in shadow.get("top") or []:
        lines.append(
            f"- Shadow {item.get('ticker')}: {item.get('strategy')} exp {item.get('expiration')} | no staging"
        )

    lines.extend(["", "Allowed from this packet:"])
    for item in actions.get("allowed") or []:
        lines.append(f"- {item}")
    lines.extend(["", "Blocked from this packet:"])
    for item in actions.get("blocked") or []:
        lines.append(f"- {item}")
    lines.extend(["", "Focus checklist:"])
    for item in actions.get("focus") or []:
        lines.append(f"- {item}")
    lines.extend(["", "Refresh commands:"])
    for command in packet.get("refreshCommands") or []:
        lines.append(f"- `{command}`")
    return "\n".join(lines).rstrip() + "\n"


def save_while_away_packet(packet: dict[str, Any]) -> None:
    """Persist JSON and text artifacts."""
    ensure_dirs()
    atomic_write_json(WHILE_AWAY_PACKET_FILE, packet)
    atomic_write_text(WHILE_AWAY_PACKET_TEXT_FILE, render_while_away_packet(packet))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Build the Inferno while-away operator packet.")
    parser.add_argument("command", nargs="?", default="build", choices=("build", "status"))
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    if args.command == "status" and WHILE_AWAY_PACKET_TEXT_FILE.exists():
        print(WHILE_AWAY_PACKET_TEXT_FILE.read_text(encoding="utf-8"), end="")
        return 0
    packet = build_while_away_packet()
    if args.json:
        print(json.dumps(packet, indent=2))
    else:
        print(render_while_away_packet(packet), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
