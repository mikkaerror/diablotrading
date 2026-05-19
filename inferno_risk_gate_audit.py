from __future__ import annotations

"""Consolidated risk-gate audit for the Inferno desk.

Most desk modules own one narrow gate. This audit does not replace them. It
reads their latest artifacts and produces one operator-facing map of what is
hard-blocked, what is promotion-blocked, and what only needs delivery/capture
cleanup.

It is read-only. It cannot approve, submit, or broaden authority.
"""

import argparse
from typing import Any

from inferno_config import BROKER_ADAPTER_MODE, account_suffix_allowed, approved_account_scope, local_now, local_today
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


RISK_GATE_AUDIT_FILE = DATA_DIR / "inferno_risk_gate_audit.json"
RISK_GATE_AUDIT_TEXT_FILE = REPORTS_DIR / "risk_gate_audit_latest.txt"

AUTHORITY_MANIFEST_FILE = DATA_DIR / "inferno_authority_manifest.json"
CAPITAL_DEPLOYMENT_READINESS_FILE = DATA_DIR / "inferno_capital_deployment_readiness.json"
LIVE_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_live_account_sync.json"
LIVE_POSITION_REVIEW_FILE = DATA_DIR / "inferno_live_position_review.json"
PAPER_EVIDENCE_LOOP_FILE = DATA_DIR / "inferno_paper_evidence_loop.json"
PAPER_TEST_DIRECTOR_FILE = DATA_DIR / "inferno_paper_test_director.json"
STRATEGY_LAB_FILE = DATA_DIR / "inferno_strategy_lab.json"
BROKER_PREVIEW_FILE = DATA_DIR / "inferno_broker_preview.json"
APPROVAL_DISPATCH_FILE = DATA_DIR / "inferno_approval_dispatch.json"
APPROVAL_INBOX_FILE = DATA_DIR / "inferno_approval_inbox.json"
DAILY_SUCCESS_FILE = DATA_DIR / "inferno_daily_success.json"
OPS_MAINTENANCE_FILE = DATA_DIR / "inferno_ops_maintenance.json"
DOWNLOADS_WATCH_FILE = DATA_DIR / "inferno_downloads_watch.json"
DOWNLOADS_MANAGER_FILE = DATA_DIR / "inferno_downloads_manager.json"
TOS_FILL_INGEST_FILE = DATA_DIR / "inferno_tos_fill_ingest.json"
DESKTOP_AUTOMATION_FILE = DATA_DIR / "inferno_desktop_automation.json"
TOS_EXPORT_VERIFIER_FILE = DATA_DIR / "inferno_tos_export_verifier.json"
PAPER_EXIT_AUDIT_FILE = DATA_DIR / "inferno_paper_exit_audit.json"
DOCTOR_TEXT_FILE = REPORTS_DIR / "doctor_latest.txt"

SAFE_BROKER_MODES = {"OFF", "READ_ONLY", "PREVIEW_ONLY", "PAPER"}
HARD = "hard"
PROMOTION = "promotion"
DELIVERY = "delivery"
CAPTURE = "capture"


def text(value: Any, default: str = "") -> str:
    """Normalize loose values into concise text."""
    if value is None:
        return default
    rendered = str(value).strip()
    return rendered or default


def number(value: Any, default: float = 0.0) -> float:
    """Parse numeric values from JSON or broker-formatted strings."""
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = text(value).replace("$", "").replace(",", "").replace("%", "")
    try:
        return float(cleaned)
    except ValueError:
        return default


def truthy(value: Any) -> bool:
    """Interpret common JSON/string booleans."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return text(value).lower() in {"true", "yes", "y", "1", "enabled"}


def nested(payload: dict[str, Any], path: tuple[str, ...], default: Any = None) -> Any:
    """Safely read a nested path from an artifact."""
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def verdict(payload: dict[str, Any], default: str = "missing") -> str:
    """Extract the most common verdict/status field from an artifact."""
    return text(
        payload.get("verdict")
        or payload.get("status")
        or nested(payload, ("deskVerdict", "level"))
        or default
    )


def fresh_today(payload: dict[str, Any]) -> bool:
    """Return whether an artifact appears to have been generated today."""
    stamp = text(payload.get("generatedAt") or payload.get("updatedAt"))
    return stamp.startswith(local_today())


def doctor_has(fragment: str, doctor_text: str) -> bool:
    """Check for a passing line in the latest doctor text report."""
    return f"[PASS] {fragment}" in doctor_text


def load_artifacts() -> dict[str, Any]:
    """Load all artifacts consumed by the risk-gate audit."""
    doctor_text = DOCTOR_TEXT_FILE.read_text(encoding="utf-8") if DOCTOR_TEXT_FILE.exists() else ""
    return {
        "authority": load_json_file(AUTHORITY_MANIFEST_FILE) or {},
        "capitalReadiness": load_json_file(CAPITAL_DEPLOYMENT_READINESS_FILE) or {},
        "liveSync": load_json_file(LIVE_ACCOUNT_SYNC_FILE) or {},
        "liveReview": load_json_file(LIVE_POSITION_REVIEW_FILE) or {},
        "paperLoop": load_json_file(PAPER_EVIDENCE_LOOP_FILE) or {},
        "paperDirector": load_json_file(PAPER_TEST_DIRECTOR_FILE) or {},
        "strategyLab": load_json_file(STRATEGY_LAB_FILE) or {},
        "brokerPreview": load_json_file(BROKER_PREVIEW_FILE) or {},
        "approvalDispatch": load_json_file(APPROVAL_DISPATCH_FILE) or {},
        "approvalInbox": load_json_file(APPROVAL_INBOX_FILE) or {},
        "dailySuccess": load_json_file(DAILY_SUCCESS_FILE) or {},
        "opsMaintenance": load_json_file(OPS_MAINTENANCE_FILE) or {},
        "downloadsWatch": load_json_file(DOWNLOADS_WATCH_FILE) or {},
        "downloadsManager": load_json_file(DOWNLOADS_MANAGER_FILE) or {},
        "fillIngest": load_json_file(TOS_FILL_INGEST_FILE) or {},
        "desktopAutomation": load_json_file(DESKTOP_AUTOMATION_FILE) or {},
        "tosVerifier": load_json_file(TOS_EXPORT_VERIFIER_FILE) or {},
        "paperExitAudit": load_json_file(PAPER_EXIT_AUDIT_FILE) or {},
        "doctorText": doctor_text,
    }


def gate(
    gate_id: str,
    name: str,
    lane: str,
    severity: str,
    status: str,
    detail: str,
    next_action: str,
    *,
    artifact: str | None = None,
) -> dict[str, Any]:
    """Create a normalized gate row."""
    return {
        "id": gate_id,
        "name": name,
        "lane": lane,
        "severity": severity,
        "status": status,
        "detail": detail,
        "artifact": artifact,
        "nextAction": next_action,
    }


def evaluate_authority_gate(authority: dict[str, Any]) -> dict[str, Any]:
    """Verify live submit authority is locked down."""
    decision = authority.get("decision") or authority
    level = text(decision.get("authorityLevel"), "missing")
    broker_submit = truthy(decision.get("brokerSubmitAllowed"))
    live_trading = truthy(decision.get("liveTradingAllowed"))
    passed = level != "missing" and not broker_submit and not live_trading
    status = "pass" if passed else "fail"
    return gate(
        "authority-live-submit-lock",
        "Authority live-submit lock",
        "authority",
        HARD,
        status,
        f"level={level} brokerSubmit={broker_submit} liveTrading={live_trading}",
        "Run ./run_inferno_authority_controller.sh and inspect authority_manifest_latest.txt.",
        artifact="data/inferno_authority_manifest.json",
    )


def evaluate_live_account_gate(live_sync: dict[str, Any]) -> dict[str, Any]:
    """Verify the live account sync is scoped to the approved account."""
    suffix = text(live_sync.get("matchedSuffix") or live_sync.get("accountSuffix"))
    live_ok = truthy(live_sync.get("ok")) and verdict(live_sync) == "healthy"
    passed = live_ok and account_suffix_allowed(suffix)
    return gate(
        "live-account-scope",
        "Live account scope",
        "live-book",
        HARD,
        "pass" if passed else "fail",
        f"verdict={verdict(live_sync)} suffix={suffix or 'missing'} expected={approved_account_scope()}",
        f"Run ./run_inferno_live_account_sync.sh and confirm only {approved_account_scope()} is used.",
        artifact="data/inferno_live_account_sync.json",
    )


def evaluate_live_position_gate(live_review: dict[str, Any]) -> dict[str, Any]:
    """Verify existing live holdings do not contain fragile exposure."""
    counts = live_review.get("counts") or {}
    fragile = number(counts.get("fragile"))
    review = number(counts.get("review"))
    status = "pass" if fragile <= 0 else "fail"
    if fragile <= 0 and review > 0:
        status = "warn"
    return gate(
        "live-position-fragility",
        "Live position fragility",
        "live-book",
        HARD,
        status,
        f"supported={counts.get('supported', 0)} review={int(review)} fragile={int(fragile)}",
        "Resolve fragile live holdings before adding new exposure.",
        artifact="data/inferno_live_position_review.json",
    )


def evaluate_capital_gate(capital: dict[str, Any]) -> dict[str, Any]:
    """Verify the capital deployment preflight is not hard-blocked."""
    cap_verdict = verdict(capital)
    guardrails = capital.get("guardrails") or {}
    deployable_cash = number(guardrails.get("deployableCash") or capital.get("deployableCash"))
    deployable_cash_arg = str(int(deployable_cash)) if deployable_cash.is_integer() else f"{deployable_cash:.2f}"
    next_action = (
        f"Run ./run_inferno_capital_deployment_readiness.sh --deployable-cash {deployable_cash_arg}."
        if deployable_cash > 0
        else "Run ./run_inferno_capital_deployment_readiness.sh with the current deployable cash."
    )
    if cap_verdict == "manual-ready":
        status = "pass"
    elif cap_verdict == "manual-ready-with-warnings":
        status = "warn"
    else:
        status = "fail"
    return gate(
        "capital-deployment-preflight",
        "Capital deployment preflight",
        "capital",
        HARD,
        status,
        f"verdict={cap_verdict} manualAllowed={capital.get('manualDeploymentAllowed')} autoLive={capital.get('autoLiveAllowed')}",
        next_action,
        artifact="data/inferno_capital_deployment_readiness.json",
    )


def evaluate_broker_preview_gate(preview: dict[str, Any]) -> dict[str, Any]:
    """Verify broker-preview output cannot submit live orders."""
    mode = text(preview.get("adapterMode") or BROKER_ADAPTER_MODE)
    preview_only = truthy(preview.get("previewOnly"))
    live_allowed = truthy(preview.get("liveTradingAllowed"))
    passed = mode in SAFE_BROKER_MODES and preview_only and not live_allowed
    return gate(
        "broker-preview-safety",
        "Broker preview safety",
        "broker-preview",
        HARD,
        "pass" if passed else "fail",
        f"mode={mode} previewOnly={preview_only} liveTradingAllowed={live_allowed} count={preview.get('count', 0)}",
        "Run ./run_inferno_broker_preview.sh and keep adapter mode preview-safe.",
        artifact="data/inferno_broker_preview.json",
    )


def evaluate_paper_evidence_gate(paper_loop: dict[str, Any]) -> dict[str, Any]:
    """Verify whether strategy evidence has cleared promotion gates."""
    counts = paper_loop.get("counts") or {}
    remaining = number(counts.get("remainingForPromotion"))
    scored = number(counts.get("scoredTickets"))
    status = "pass" if remaining <= 0 and scored > 0 else "fail"
    return gate(
        "paper-evidence-promotion",
        "Paper evidence promotion",
        "paper-evidence",
        PROMOTION,
        status,
        f"scored={int(scored)} remainingForPromotion={int(remaining)}",
        "Keep generating closed scored paper outcomes before authority promotion.",
        artifact="data/inferno_paper_evidence_loop.json",
    )


def evaluate_paper_director_gate(paper_director: dict[str, Any]) -> dict[str, Any]:
    """Verify there is a clean paper action path for the next cycle."""
    counts = paper_director.get("counts") or {}
    stageable = number(counts.get("stageableNow"))
    auto_paper = number(counts.get("autoPaperSelected"))
    approval_only = number(counts.get("approvalOnly"))
    hard_blocked = number(counts.get("hardBlocked"))
    if stageable > 0 or auto_paper > 0:
        status = "pass"
    elif approval_only > 0:
        status = "warn"
    else:
        status = "fail"
    return gate(
        "paper-test-action-path",
        "Paper test action path",
        "paper-evidence",
        PROMOTION,
        status,
        f"stageable={int(stageable)} autoPaper={int(auto_paper)} approvalOnly={int(approval_only)} hardBlocked={int(hard_blocked)}",
        "Use stageable or auto-selected paper tickets only; do not force hard-blocked tickets.",
        artifact="data/inferno_paper_test_director.json",
    )


def evaluate_strategy_gate(strategy_lab: dict[str, Any]) -> dict[str, Any]:
    """Verify the strategy lab has enough scored evidence for promotion."""
    lab_verdict = verdict(strategy_lab)
    status = "fail" if lab_verdict in {"missing", "insufficient-data"} else "pass"
    return gate(
        "strategy-lab-evidence",
        "Strategy lab evidence",
        "paper-evidence",
        PROMOTION,
        status,
        f"verdict={lab_verdict}",
        "Do not widen authority until strategy lab has positive closed evidence.",
        artifact="data/inferno_strategy_lab.json",
    )


def daily_success_passed(daily_success: dict[str, Any], criterion_name: str) -> bool:
    """Return whether one daily-success criterion passed."""
    for criterion in daily_success.get("criteria") or []:
        if criterion.get("name") == criterion_name:
            return truthy(criterion.get("pass"))
    return False


def evaluate_delivery_gate(
    doctor_text: str,
    dispatch: dict[str, Any],
    inbox: dict[str, Any],
    daily_success: dict[str, Any],
    ops_maintenance: dict[str, Any],
) -> dict[str, Any]:
    """Verify morning delivery and one-word approval plumbing are healthy."""
    # The doctor is usually terminal output, while daily-success is persisted.
    # Prefer persisted criteria so the audit works without scraping a console.
    smtp_ok = doctor_has("SMTP", doctor_text) or truthy(ops_maintenance.get("ok"))
    morning_ok = (
        doctor_has("Morning run", doctor_text)
        or daily_success_passed(daily_success, "morningBriefDelivered")
    )
    doctor_ok = (
        doctor_has("Desk status: healthy", doctor_text)
        or daily_success_passed(daily_success, "doctorHealthy")
        or truthy(ops_maintenance.get("ok"))
    )
    dispatch_ok = truthy(dispatch.get("ok"))
    inbox_ok = truthy(inbox.get("ok"))
    status = "pass" if smtp_ok and morning_ok and doctor_ok and dispatch_ok and inbox_ok else "warn"
    return gate(
        "email-delivery-approval-capture",
        "Email delivery and approval capture",
        "delivery",
        DELIVERY,
        status,
        f"smtp={smtp_ok} morning={morning_ok} doctor={doctor_ok} dispatchOk={dispatch_ok} inboxOk={inbox_ok}",
        "Run inferno_doctor.py, approval dispatch, and approval inbox before market open.",
        artifact="reports/doctor_latest.txt",
    )


def evaluate_download_capture_gate(
    downloads_watch: dict[str, Any],
    downloads_manager: dict[str, Any],
    fill_ingest: dict[str, Any],
) -> dict[str, Any]:
    """Verify the TOS export/download/fill ingest path is observable."""
    export_first = truthy(downloads_watch.get("exportFirst"))
    watch_fresh = fresh_today(downloads_watch)
    manager_fresh = fresh_today(downloads_manager)
    ingest_fresh = fresh_today(fill_ingest)
    skipped = truthy(downloads_watch.get("skipped"))
    imported_rows = number(downloads_manager.get("importedRows"))
    unmatched_rows = number(fill_ingest.get("unmatchedRows"))
    if export_first and watch_fresh and manager_fresh and ingest_fresh and not skipped:
        status = "pass"
    else:
        status = "warn"
    detail = (
        f"exportFirst={export_first} skipped={skipped} importedRows={int(imported_rows)} "
        f"unmatchedRows={int(unmatched_rows)} fresh={watch_fresh}/{manager_fresh}/{ingest_fresh}"
    )
    return gate(
        "downloads-fill-capture",
        "Downloads and fill capture",
        "capture",
        CAPTURE,
        status,
        detail,
        "Run ./run_inferno_downloads_watch.sh after a TOS export attempt.",
        artifact="data/inferno_downloads_watch.json",
    )


def evaluate_tos_capture_gate(desktop: dict[str, Any], verifier: dict[str, Any]) -> dict[str, Any]:
    """Verify the desktop/TOS capture lane is usable without submit authority."""
    app_running = truthy(verifier.get("appRunning"))
    readonly = truthy(verifier.get("allowedLiveReadonly"))
    verifier_ready = verdict(verifier) in {"ready-live-readonly", "manual-check"}
    desktop_status = verdict(desktop)
    status = "pass" if app_running and readonly and verifier_ready else "warn"
    return gate(
        "tos-readonly-capture",
        "TOS readonly capture",
        "capture",
        CAPTURE,
        status,
        f"verifier={verdict(verifier)} appRunning={app_running} readonly={readonly} desktop={desktop_status}",
        "Use the already-open TOS window; do not open a new instance.",
        artifact="data/inferno_tos_export_verifier.json",
    )


def evaluate_paper_exit_gate(exit_audit: dict[str, Any]) -> dict[str, Any]:
    """Verify the paper exit capture path is not carrying unresolved closes."""
    audit_verdict = verdict(exit_audit)
    counts = exit_audit.get("counts") or {}
    close_now = number(counts.get("closeNow") or exit_audit.get("closeNow"))
    review = number(counts.get("review") or exit_audit.get("review"))
    status = "pass" if audit_verdict in {"clean", "healthy", "ok"} and close_now <= 0 else "warn"
    return gate(
        "paper-exit-capture",
        "Paper exit capture",
        "capture",
        CAPTURE,
        status,
        f"verdict={audit_verdict} closeNow={int(close_now)} review={int(review)}",
        "Run ./run_inferno_paper_exit_auditor.sh before relying on closed paper evidence.",
        artifact="data/inferno_paper_exit_audit.json",
    )


def summarize_gates(gates: list[dict[str, Any]]) -> dict[str, Any]:
    """Build counts and verdict from normalized gates."""
    hard_fails = [gate for gate in gates if gate["severity"] == HARD and gate["status"] == "fail"]
    promotion_fails = [gate for gate in gates if gate["severity"] == PROMOTION and gate["status"] == "fail"]
    warnings = [gate for gate in gates if gate["status"] == "warn"]
    if hard_fails:
        audit_verdict = "blocked"
        message = "Hard risk gates are blocking new deployment."
    elif promotion_fails:
        audit_verdict = "manual-only"
        message = "Manual review can continue, but automation promotion is blocked."
    elif warnings:
        audit_verdict = "review"
        message = "Risk gates pass, but delivery or capture needs review."
    else:
        audit_verdict = "clear"
        message = "All audited gates are clear."
    return {
        "verdict": audit_verdict,
        "message": message,
        "hardFails": len(hard_fails),
        "promotionFails": len(promotion_fails),
        "warnings": len(warnings),
        "passed": sum(1 for gate in gates if gate["status"] == "pass"),
        "total": len(gates),
        "blockedGateIds": [gate["id"] for gate in hard_fails],
        "warningGateIds": [gate["id"] for gate in warnings],
        "promotionBlockedGateIds": [gate["id"] for gate in promotion_fails],
    }


def build_risk_gate_audit() -> dict[str, Any]:
    """Build and persist the consolidated risk-gate audit."""
    ensure_dirs()
    artifacts = load_artifacts()
    gates = [
        evaluate_authority_gate(artifacts["authority"]),
        evaluate_live_account_gate(artifacts["liveSync"]),
        evaluate_live_position_gate(artifacts["liveReview"]),
        evaluate_capital_gate(artifacts["capitalReadiness"]),
        evaluate_broker_preview_gate(artifacts["brokerPreview"]),
        evaluate_paper_evidence_gate(artifacts["paperLoop"]),
        evaluate_paper_director_gate(artifacts["paperDirector"]),
        evaluate_strategy_gate(artifacts["strategyLab"]),
        evaluate_delivery_gate(
            artifacts["doctorText"],
            artifacts["approvalDispatch"],
            artifacts["approvalInbox"],
            artifacts["dailySuccess"],
            artifacts["opsMaintenance"],
        ),
        evaluate_download_capture_gate(
            artifacts["downloadsWatch"],
            artifacts["downloadsManager"],
            artifacts["fillIngest"],
        ),
        evaluate_tos_capture_gate(artifacts["desktopAutomation"], artifacts["tosVerifier"]),
        evaluate_paper_exit_gate(artifacts["paperExitAudit"]),
    ]
    summary = summarize_gates(gates)
    payload = {
        "generatedAt": local_now().isoformat(),
        "stage": "risk-gate-audit",
        "readOnly": True,
        "liveTradingAllowed": False,
        "summary": summary,
        "verdict": summary["verdict"],
        "message": summary["message"],
        "gates": gates,
        "nextActions": build_next_actions(gates),
    }
    save_risk_gate_audit(payload)
    return payload


def build_next_actions(gates: list[dict[str, Any]]) -> list[str]:
    """Return concise next actions for failed or warning gates."""
    items = [
        f"{gate['name']}: {gate['nextAction']}"
        for gate in gates
        if gate["status"] in {"fail", "warn"}
    ]
    return items[:10] or ["No risk-gate action required."]


def risk_gate_audit_text(payload: dict[str, Any]) -> str:
    """Render the risk-gate audit for operator review."""
    summary = payload.get("summary") or {}
    lines = [
        "Inferno Risk Gate Audit",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')} | {payload.get('message')}",
        f"Read-only: {payload.get('readOnly')} | Live trading allowed: {payload.get('liveTradingAllowed')}",
        (
            f"Gates: {summary.get('passed', 0)}/{summary.get('total', 0)} pass | "
            f"hard fails {summary.get('hardFails', 0)} | "
            f"promotion fails {summary.get('promotionFails', 0)} | "
            f"warnings {summary.get('warnings', 0)}"
        ),
        "",
        "Gate matrix:",
    ]
    for item in payload.get("gates") or []:
        lines.append(
            f"- {item.get('status', '').upper()} [{item.get('severity')}/{item.get('lane')}] "
            f"{item.get('name')}: {item.get('detail')}"
        )
    lines.extend(["", "Next actions:"])
    for action in payload.get("nextActions") or []:
        lines.append(f"- {action}")
    return "\n".join(lines).rstrip() + "\n"


def save_risk_gate_audit(payload: dict[str, Any]) -> None:
    """Persist JSON and text copies of the risk-gate audit."""
    atomic_write_json(RISK_GATE_AUDIT_FILE, payload)
    atomic_write_text(RISK_GATE_AUDIT_TEXT_FILE, risk_gate_audit_text(payload))


def parse_args() -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(description="Build the Inferno risk-gate audit.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    """Run the risk-gate audit CLI."""
    args = parse_args()
    if args.command == "status" and RISK_GATE_AUDIT_TEXT_FILE.exists():
        print(RISK_GATE_AUDIT_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_risk_gate_audit()
    print(risk_gate_audit_text(payload))
    return 0 if payload.get("verdict") != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
