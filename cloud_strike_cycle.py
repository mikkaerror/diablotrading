from __future__ import annotations

import sys
import os

from inferno_authority_controller import authority_text, build_authority_manifest, save_authority_manifest
from inferno_broker_preview import build_broker_preview, preview_text, save_broker_preview
from inferno_capital_allocator import allocator_text, build_capital_allocator, save_capital_allocator
from inferno_cloud_state import persist_cloud_artifacts, restore_cloud_artifacts
from inferno_email_policy import suppress_routine_email
from inferno_email_digest import build_strike_digest, verbose_requested
from inferno_exposure_analytics import build_exposure_analytics, exposure_text, save_exposure_analytics
from inferno_paper_execution import ledger_summary, load_ledger
from inferno_performance_analytics import build_performance_analytics, analytics_text, save_performance_analytics
from inferno_shadow_evidence import build_shadow_evidence, save_shadow_evidence, shadow_evidence_text
from inferno_strategy_lab import build_strategy_lab, save_strategy_lab, strategy_lab_text
from inferno_strike_selector import build_strike_plan, build_text_report, save_strike_plan, send_strike_plan_email
from inferno_tos_sandbox import build_tos_sandbox_session, save_tos_sandbox_session, tos_sandbox_text
from morning_inferno_pipeline import main as run_morning_pipeline


from inferno_ledger_ownership import cloud_research_entrypoint


@cloud_research_entrypoint
def main() -> int:
    restore_report = restore_cloud_artifacts()
    if restore_report.get("ok") is False:
        print("Canonical paper restore failed; cloud research stopped without writes or mail.")
        return 1
    if restore_report.get("enabled"):
        print(
            "Cloud state restore: "
            f"{len(restore_report.get('restored', []))} restored, "
            f"{len(restore_report.get('missing', []))} missing, ok={restore_report.get('ok')}"
        )

    original_argv = sys.argv[:]
    try:
        sys.argv = ["morning_inferno_pipeline.py", "--cloud-native", "--skip-email"]
        pipeline_result = run_morning_pipeline()
    finally:
        sys.argv = original_argv

    if pipeline_result != 0:
        return pipeline_result

    plan = build_strike_plan()
    from server import DATA_DIR, load_json_file
    source_receipt = load_json_file(DATA_DIR / "inferno_canonical_paper_receipt.json") or {}
    plan["canonicalPaperRevision"] = source_receipt.get("revision") or restore_report.get("canonicalRevision")
    plan["paperLedgerOwner"] = "mac"
    save_strike_plan(plan)
    ledger_result = {"ledger": load_ledger()}  # canonical read-only snapshot
    ledger_text = ledger_summary(ledger_result["ledger"])
    shadow = build_shadow_evidence(plan)
    save_shadow_evidence(shadow)
    shadow_report = shadow_evidence_text(shadow)
    analytics = build_performance_analytics(ledger_result["ledger"])
    save_performance_analytics(analytics)
    analytics_report = analytics_text(analytics)
    strategy_lab = build_strategy_lab(ledger_result["ledger"])
    save_strategy_lab(strategy_lab)
    strategy_lab_report = strategy_lab_text(strategy_lab)
    exposure = build_exposure_analytics()
    save_exposure_analytics(exposure)
    exposure_report = exposure_text(exposure)
    preview = build_broker_preview()
    save_broker_preview(preview)
    preview_report = preview_text(preview)
    authority = build_authority_manifest()
    save_authority_manifest(authority)
    authority_report = authority_text(authority)
    allocator = build_capital_allocator()
    save_capital_allocator(allocator)
    allocator_report = allocator_text(allocator)
    sandbox = build_tos_sandbox_session()
    save_tos_sandbox_session(sandbox)
    sandbox_report = tos_sandbox_text(sandbox)
    print(build_text_report(plan))
    print(ledger_text)
    print(shadow_report)
    print(analytics_report)
    print(strategy_lab_report)
    print(exposure_report)
    print(preview_report)
    print(authority_report)
    print(allocator_report)
    print(sandbox_report)
    full_appendix = "\n\n".join(
        [
            ledger_text,
            shadow_report,
            analytics_report,
            strategy_lab_report,
            exposure_report,
            preview_report,
            authority_report,
            allocator_report,
            sandbox_report,
        ]
    )
    sent = False  # cloud never dispatches approval/strike emails
    persist_report = persist_cloud_artifacts()
    if persist_report.get("enabled"):
        print(
            "Cloud state persist: "
            f"{len(persist_report.get('persisted', []))} persisted, "
            f"{len(persist_report.get('missing', []))} missing, ok={persist_report.get('ok')}"
        )
    print("Strike email delivery: canonical Mac owner; cloud research-only")
    return 0 if persist_report.get("ok", True) else 1



if __name__ == "__main__":
    raise SystemExit(main())
