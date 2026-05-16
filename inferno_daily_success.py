from __future__ import annotations

"""Daily success-criteria diagnostic for the Inferno desk.

Aggregates the existing artifacts into one green/yellow/red verdict so the
operator can answer "did we have a good day?" in one glance. Read-only.

Success criteria (all derived from existing on-disk artifacts):

1. ``morningBriefDelivered``  — ops_status.emailSent is true today
2. ``doctorHealthy``           — last doctor run cycle had zero warnings (we
   infer this from the ops maintenance report, since the doctor itself is
   shell-driven)
3. ``approvalVelocityPositive`` — at least one approve/reject decision today
4. ``authorityIntact``         — authority manifest still at
   ``paper-evidence-only`` and ``brokerSubmitAllowed`` is false
5. ``noNewFragileHoldings``    — live position review fragile count has not
   increased vs the previous run (we compare against the latest artifact;
   absent a prior snapshot, we treat unchanged as pass)

Each criterion produces a boolean. The overall verdict is:
- green: all criteria pass
- yellow: any non-safety criterion fails (1, 3, 5)
- red: any safety-anchored criterion fails (2, 4)

Strict contract:
- diagnostic / read-only. Cannot mutate any artifact.
- writes only to ``data/inferno_daily_success.json`` and
  ``reports/daily_success_latest.txt``.
- cannot affect authority, performance analytics, or strategy lab state.
"""

import argparse
import json
from typing import Any

from inferno_config import local_now, local_today
from server import (
    DATA_DIR,
    OPS_STATUS_FILE,
    REPORTS_DIR,
    ensure_dirs,
    load_json_file,
)


AUTHORITY_MANIFEST_FILE = DATA_DIR / "inferno_authority_manifest.json"
LIVE_POSITION_REVIEW_FILE = DATA_DIR / "inferno_live_position_review.json"
APPROVAL_QUEUE_FILE = DATA_DIR / "inferno_approval_queue.json"
OPS_MAINTENANCE_FILE = DATA_DIR / "inferno_ops_maintenance.json"

DAILY_SUCCESS_FILE = DATA_DIR / "inferno_daily_success.json"
DAILY_SUCCESS_TEXT_FILE = REPORTS_DIR / "daily_success_latest.txt"
DAILY_SUCCESS_STAGE = "daily-success-diagnostic-only"


def check_morning_brief(ops_status: dict[str, Any], *, today: str) -> dict[str, Any]:
    generated_at = str(ops_status.get("generatedAt") or "")
    delivered = bool(ops_status.get("emailSent")) and generated_at.startswith(today)
    return {
        "name": "morningBriefDelivered",
        "pass": delivered,
        "detail": f"emailSent={ops_status.get('emailSent')} generatedAt={ops_status.get('generatedAt')}",
        "category": "operational",
    }


def check_doctor_proxy(ops_maintenance: dict[str, Any], *, today: str) -> dict[str, Any]:
    """Use ops_maintenance.ok as a proxy for doctor health.

    The doctor itself shells out to macOS-only commands so it isn't cleanly
    importable here. The ops maintenance ``ok`` flag is the most faithful
    proxy: it AND-s together every refreshable lane.
    """
    generated_at = str(ops_maintenance.get("generatedAt") or "")
    fresh_today = generated_at.startswith(today)
    ok = bool(ops_maintenance.get("ok")) and fresh_today
    return {
        "name": "doctorHealthy",
        "pass": ok,
        "detail": f"opsOk={ops_maintenance.get('ok')} freshToday={fresh_today}",
        "category": "safety",
    }


def check_approval_velocity(queue: dict[str, Any], *, today: str) -> dict[str, Any]:
    decided_today = 0
    for item in queue.get("items") or []:
        status = str(item.get("approvalStatus") or "").lower()
        decision_at = str(item.get("decisionAt") or "")
        if status in {"approved", "rejected"} and decision_at.startswith(today):
            decided_today += 1
    return {
        "name": "approvalVelocityPositive",
        "pass": decided_today > 0,
        "detail": f"decidedToday={decided_today}",
        "category": "operational",
    }


def check_authority_intact(authority: dict[str, Any]) -> dict[str, Any]:
    decision = authority.get("decision") or {}
    level = str(decision.get("authorityLevel") or "")
    broker_submit = bool(decision.get("brokerSubmitAllowed"))
    live_trading = bool(decision.get("liveTradingAllowed"))
    intact = (
        level in {"paper-evidence-only", "broker-preview-only", "recommendations-only", "halted"}
        and not broker_submit
        and not live_trading
    )
    return {
        "name": "authorityIntact",
        "pass": intact,
        "detail": (
            f"level={level} brokerSubmit={broker_submit} liveTrading={live_trading}"
        ),
        "category": "safety",
    }


def check_no_new_fragile(live_review: dict[str, Any], *, prior: dict[str, Any] | None) -> dict[str, Any]:
    counts = live_review.get("counts") or {}
    current_fragile = int(counts.get("fragile") or 0)
    prior_fragile = None
    if prior:
        prior_counts = (prior.get("liveReview") or {}).get("counts") or {}
        if prior_counts:
            prior_fragile = int(prior_counts.get("fragile") or 0)
    if prior_fragile is None:
        verdict = True
        detail = f"fragile={current_fragile} (no prior snapshot — treating unchanged as pass)"
    else:
        verdict = current_fragile <= prior_fragile
        detail = f"fragile={current_fragile} (prior {prior_fragile})"
    return {
        "name": "noNewFragileHoldings",
        "pass": verdict,
        "detail": detail,
        "category": "operational",
    }


def overall_verdict(criteria: list[dict[str, Any]]) -> str:
    """Roll up criteria into green / yellow / red."""
    for criterion in criteria:
        if not criterion["pass"] and criterion["category"] == "safety":
            return "red"
    failing = [c for c in criteria if not c["pass"]]
    if failing:
        return "yellow"
    return "green"


def build_daily_success(
    *,
    ops_status: dict[str, Any] | None = None,
    ops_maintenance: dict[str, Any] | None = None,
    queue: dict[str, Any] | None = None,
    authority: dict[str, Any] | None = None,
    live_review: dict[str, Any] | None = None,
    prior: dict[str, Any] | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """Build the full daily-success report."""
    today = today or local_today()
    ops_status = ops_status if ops_status is not None else (load_json_file(OPS_STATUS_FILE) or {})
    ops_maintenance = ops_maintenance if ops_maintenance is not None else (load_json_file(OPS_MAINTENANCE_FILE) or {})
    queue = queue if queue is not None else (load_json_file(APPROVAL_QUEUE_FILE) or {})
    authority = authority if authority is not None else (load_json_file(AUTHORITY_MANIFEST_FILE) or {})
    live_review = live_review if live_review is not None else (load_json_file(LIVE_POSITION_REVIEW_FILE) or {})
    prior = prior if prior is not None else (load_json_file(DAILY_SUCCESS_FILE) or {})

    criteria = [
        check_morning_brief(ops_status, today=today),
        check_doctor_proxy(ops_maintenance, today=today),
        check_approval_velocity(queue, today=today),
        check_authority_intact(authority),
        check_no_new_fragile(live_review, prior=prior),
    ]

    return {
        "generatedAt": local_now().isoformat(),
        "stage": DAILY_SUCCESS_STAGE,
        "diagnosticOnly": True,
        "day": today,
        "verdict": overall_verdict(criteria),
        "passCount": sum(1 for c in criteria if c["pass"]),
        "totalCount": len(criteria),
        "criteria": criteria,
        "liveReview": {"counts": (live_review.get("counts") or {})},
        "researchNotes": [
            "diagnostic only; cannot change any artifact",
            "verdict red = any safety criterion failed",
            "verdict yellow = any operational criterion failed",
        ],
    }


def daily_success_text(report: dict[str, Any]) -> str:
    lines = [
        "Inferno Daily Success Scorecard",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Day: {report.get('day')}",
        f"Verdict: {report.get('verdict').upper()}",
        f"Passed: {report.get('passCount')}/{report.get('totalCount')}",
        "",
        "Criteria:",
    ]
    for criterion in report.get("criteria") or []:
        mark = "PASS" if criterion["pass"] else "FAIL"
        lines.append(f"- [{mark}] {criterion['name']} ({criterion['category']}): {criterion['detail']}")
    lines.extend([
        "",
        "Reminders:",
        "- red verdict means a SAFETY-anchored criterion failed; stop and investigate",
        "- yellow verdict means an operational criterion failed; act today",
        "- diagnostic only; nothing here changes desk state",
    ])
    return "\n".join(lines).rstrip() + "\n"


def save_daily_success(report: dict[str, Any]) -> None:
    ensure_dirs()
    DAILY_SUCCESS_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    DAILY_SUCCESS_TEXT_FILE.write_text(daily_success_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Daily success-criteria diagnostic. Read-only. Aggregates existing "
            "artifacts into one green/yellow/red verdict."
        )
    )
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and DAILY_SUCCESS_TEXT_FILE.exists():
        print(DAILY_SUCCESS_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = build_daily_success()
    save_daily_success(report)
    print(daily_success_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
