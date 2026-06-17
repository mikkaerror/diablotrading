from __future__ import annotations

"""Non-destructive ops maintenance sweep for the Inferno desk.

This runner exists for the gap between the morning market build and the rest of
the operating day. It refreshes stale read-mostly artifacts, repairs a missed
brief email from the already-built snapshot, and re-checks the watchdog without
sending duplicate alert spam.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from inferno_cloud_control_plane import (
    DEFAULT_REGION as DEFAULT_CLOUD_REGION,
    build_report as build_cloud_control_plane_report,
)
from inferno_approval_inbox import poll_approval_inbox
from inferno_approval_dispatch import dispatch_pending_approval_prompts
from inferno_approval_queue import (
    DEFAULT_STALE_APPROVAL_TTL_MARKET_DAYS,
    ensure_pending_since,
    expire_stale_approvals,
    load_queue as load_approval_queue,
    refresh_execution_queue,
    save_queue as save_approval_queue,
)
from inferno_broker_preview import build_broker_preview, save_broker_preview
from inferno_cloud_execution_auditor import build_audit as build_cloud_execution_audit
from inferno_paper_bottleneck_reducer import build_reducer as build_paper_bottleneck_reducer
from inferno_paper_bottleneck_reducer import save_reducer as save_paper_bottleneck_reducer
from inferno_paper_exit_auditor import build_audit as build_paper_exit_audit, save_audit as save_paper_exit_audit
from inferno_paper_evidence_loop import build_audit as build_paper_evidence_loop_audit, save_audit as save_paper_evidence_loop_audit
from inferno_paper_mark_to_market import build_paper_mark_to_market, save_paper_mark_to_market
from inferno_paper_test_director import build_director as build_paper_test_director, save_director as save_paper_test_director
from inferno_config import DEFAULT_SHEET_NAME, ROOT, default_backtest_root, local_now
from inferno_heartbeat import record_heartbeat
from inferno_data_readiness_audit import run_audit
from inferno_downloads_watch import run_watch
from inferno_io import atomic_write_json, atomic_write_text
from inferno_live_account_sync import build_live_account_sync
from inferno_live_position_review import build_live_position_review
from inferno_model_command_center import build_command_center
from inferno_research_cycle import build_research_cycle, save_research_cycle
from inferno_schwab_account_sync import build_schwab_account_sync, save_schwab_account_sync
from inferno_ticker_universe_audit import build_ticker_universe_audit_from_sheet
from inferno_watchdog import run_watchdog_check
from morning_inferno_pipeline import append_log
from server import (
    DATA_DIR,
    OPS_STATUS_FILE,
    REPORTS_DIR,
    SNAPSHOT_FILE,
    ensure_dirs,
    load_json_file,
    send_email,
    smtp_configured,
)


OPS_MAINTENANCE_FILE = DATA_DIR / "inferno_ops_maintenance.json"
OPS_MAINTENANCE_TEXT_FILE = REPORTS_DIR / "ops_maintenance_latest.txt"


def advisory_failures(*reports: tuple[str, dict[str, Any]]) -> list[str]:
    """Return non-blocking maintenance lanes that need operator awareness.

    Cloud checks can be noisy on a sleeping laptop or stale shell. We still
    record their exact status and error, but they should not drown out the
    local desk verdict when the doctor, math, email, paper, and broker-safety
    lanes are otherwise healthy.
    """
    return [name for name, report in reports if not bool((report or {}).get("ok"))]


def load_env_file(path: Path) -> None:
    """Load a simple KEY=VALUE env file into the current process."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # This runner only needs SMTP visibility, so last writer wins is fine.
        import os

        os.environ[key.strip()] = value.strip()


def repair_morning_email(*, force: bool = False) -> dict[str, Any]:
    """Send the latest built snapshot if today's dawn cycle missed its email."""
    ops_status = load_json_file(OPS_STATUS_FILE) or {}
    snapshot = load_json_file(SNAPSHOT_FILE) or {}
    if not ops_status:
        return {"attempted": False, "ok": False, "status": "missing-ops-status"}
    if not snapshot:
        return {"attempted": False, "ok": False, "status": "missing-snapshot"}
    if ops_status.get("emailSent") and not force:
        return {"attempted": False, "ok": True, "status": "already-sent"}
    if not smtp_configured():
        return {"attempted": False, "ok": False, "status": "smtp-not-configured"}

    snapshot_generated_at = str(snapshot.get("generatedAt") or "")
    ops_generated_at = str(ops_status.get("generatedAt") or "")
    if not force and snapshot_generated_at != ops_generated_at:
        return {
            "attempted": False,
            "ok": False,
            "status": "snapshot-mismatch",
            "opsGeneratedAt": ops_generated_at,
            "snapshotGeneratedAt": snapshot_generated_at,
        }

    try:
        sent = send_email(snapshot)
    except Exception as exc:  # noqa: BLE001
        ops_status["emailError"] = str(exc)
        ops_status["emailRecoveredAt"] = None
        atomic_write_json(OPS_STATUS_FILE, ops_status)
        return {"attempted": True, "ok": False, "status": "send-failed", "error": str(exc)}

    if sent:
        repaired_at = local_now().isoformat()
        ops_status["emailSent"] = True
        ops_status["emailError"] = None
        ops_status["emailRecoveredAt"] = repaired_at
        ops_status["emailRecoverySource"] = "inferno_ops_maintenance"
        atomic_write_json(OPS_STATUS_FILE, ops_status)
        append_log(
            {
                "job": "inferno_ops_maintenance_email_repair",
                "generatedAt": repaired_at,
                "ok": True,
                "repairedOpsGeneratedAt": ops_generated_at,
                "sourceSnapshotGeneratedAt": snapshot_generated_at,
                "emailSent": True,
            }
        )
        return {
            "attempted": True,
            "ok": True,
            "status": "email-recovered",
            "repairedOpsGeneratedAt": ops_generated_at,
        }

    return {"attempted": True, "ok": False, "status": "send-returned-false"}


def refresh_cloud_control_plane(*, region: str) -> dict[str, Any]:
    """Refresh the read-only cloud control-plane artifact for doctor freshness.

    The maintenance sweep should never explode just because gcloud had a rough
    moment. We capture the failure as status instead so the doctor can surface
    it cleanly without masking the rest of the maintenance work.
    """
    try:
        report = build_cloud_control_plane_report(region=region)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "refresh-failed",
            "error": str(exc),
        }
    return {
        "ok": report.get("verdict") in {"deployable", "ready"},
        "status": str(report.get("verdict") or "unknown"),
        "region": report.get("region"),
        "projectId": report.get("projectId"),
        "message": report.get("message"),
    }


def refresh_cloud_execution_audit(*, region: str) -> dict[str, Any]:
    """Refresh the cloud execution audit artifact for doctor freshness."""
    try:
        report = build_cloud_execution_audit(region=region)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "refresh-failed",
            "error": str(exc),
        }
    return {
        "ok": report.get("verdict") == "healthy",
        "status": str(report.get("verdict") or "unknown"),
        "region": report.get("region"),
        "projectId": report.get("projectId"),
    }


def refresh_paper_test_director() -> dict[str, Any]:
    """Rebuild the paper-test director so doctor reflects the current paper lane."""
    try:
        report = build_paper_test_director()
        save_paper_test_director(report)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "refresh-failed",
            "error": str(exc),
        }
    return {
        "ok": True,
        "status": str(report.get("verdict") or "unknown"),
        "generatedAt": report.get("generatedAt"),
        "counts": report.get("counts") or {},
    }


def refresh_paper_evidence_loop() -> dict[str, Any]:
    """Rebuild the paper evidence loop so stale blockers do not linger."""
    try:
        report = build_paper_evidence_loop_audit()
        save_paper_evidence_loop_audit(report)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "refresh-failed",
            "error": str(exc),
        }
    return {
        "ok": True,
        "status": str(report.get("verdict") or "unknown"),
        "generatedAt": report.get("generatedAt"),
        "counts": report.get("counts") or {},
    }


def refresh_paper_bottleneck_reducer() -> dict[str, Any]:
    """Rebuild the high-throughput paper/shadow scenario slate."""
    try:
        report = build_paper_bottleneck_reducer()
        save_paper_bottleneck_reducer(report)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "refresh-failed",
            "error": str(exc),
        }
    counts = report.get("counts") or {}
    return {
        "ok": True,
        "status": str(report.get("verdict") or "unknown"),
        "generatedAt": report.get("generatedAt"),
        "counts": counts,
        "topFocusTickers": [
            item.get("ticker")
            for item in (report.get("topFiveFocus") or [])[:5]
            if item.get("ticker")
        ],
    }


def refresh_paper_exit_audit() -> dict[str, Any]:
    """Rebuild the paper exit audit so open-position hygiene stays fresh."""
    try:
        report = build_paper_exit_audit()
        save_paper_exit_audit(report)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "refresh-failed",
            "error": str(exc),
        }
    return {
        "ok": True,
        "status": str(report.get("verdict") or "unknown"),
        "generatedAt": report.get("generatedAt"),
        "counts": report.get("counts") or {},
    }


def refresh_paper_mark_to_market() -> dict[str, Any]:
    """Rebuild paper-ticket MTM so trade-management inputs stay fresh."""
    try:
        report = build_paper_mark_to_market()
        save_paper_mark_to_market(report)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "refresh-failed",
            "error": str(exc),
        }
    return {
        "ok": True,
        "status": str(report.get("fetchStatus") or report.get("verdict") or "unknown"),
        "generatedAt": report.get("generatedAt"),
        "openPositionCount": report.get("openPositionCount"),
        "markedTickets": len(report.get("marksByTicketId") or {}),
    }


def refresh_stale_approval_governor(
    *,
    ttl_market_days: int = DEFAULT_STALE_APPROVAL_TTL_MARKET_DAYS,
) -> dict[str, Any]:
    """Run the staleness governor against the approval queue.

    The governor only demotes — never approves — pending tickets that have sat
    longer than ``ttl_market_days`` without an operator decision. Approved or
    rejected items are immutable to this pass. We rebuild the execution queue
    only when demotions actually happened so a no-op run stays cheap.
    """
    try:
        queue = load_approval_queue()
        ensure_pending_since(queue)
        demoted = expire_stale_approvals(queue, ttl_market_days=ttl_market_days)
        save_approval_queue(queue)
        if demoted:
            try:
                refresh_execution_queue()
            except Exception as exc:  # noqa: BLE001
                return {
                    "ok": False,
                    "status": "execution-refresh-failed",
                    "error": str(exc),
                    "demoted": demoted,
                    "ttlMarketDays": ttl_market_days,
                }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "refresh-failed",
            "error": str(exc),
        }
    return {
        "ok": True,
        "status": "no-action" if not demoted else f"demoted-{len(demoted)}",
        "demoted": demoted,
        "ttlMarketDays": ttl_market_days,
    }


def refresh_approval_inbox() -> dict[str, Any]:
    """Poll the inbound approval mailbox for approve/deny replies.

    This is the automation path that turns a simple email reply into a queue
    update. It stays tightly scoped to the approval desk and cannot broaden
    broker authority.
    """
    try:
        report = poll_approval_inbox()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "refresh-failed",
            "error": str(exc),
        }
    return {
        "ok": bool(report.get("ok", True)),
        "status": str(report.get("status") or "unknown"),
        "generatedAt": report.get("generatedAt"),
        "checkedCount": int(report.get("checkedCount") or 0),
        "appliedCount": int(report.get("appliedCount") or 0),
        "skippedCount": int(report.get("skippedCount") or 0),
    }


def refresh_approval_dispatch() -> dict[str, Any]:
    """Send any unsent one-word approval prompts for the current queue."""
    try:
        report = dispatch_pending_approval_prompts()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "dispatch-failed",
            "error": str(exc),
        }
    return {
        "ok": bool(report.get("ok")),
        "status": str(report.get("status") or "unknown"),
        "generatedAt": report.get("generatedAt"),
        "pendingCount": int(report.get("pendingCount") or 0),
        "sentCount": int(report.get("sentCount") or 0),
        "skippedCount": int(report.get("skippedCount") or 0),
    }


def refresh_broker_preview() -> dict[str, Any]:
    """Rebuild the broker-preview artifact so the desk has a fresh paper-only payload.

    The preview is intentionally broker-neutral and stays read-only. We refresh it
    here so the authority manifest sees a current artifact instead of one that has
    aged past the operating cycle. An empty payload is still a healthy refresh.
    """
    try:
        report = build_broker_preview()
        save_broker_preview(report)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "refresh-failed",
            "error": str(exc),
        }
    return {
        "ok": True,
        "status": str(report.get("verdict") or "preview-built"),
        "generatedAt": report.get("generatedAt"),
        "count": int(report.get("count") or 0),
        "previewOnly": bool(report.get("previewOnly")),
    }


def refresh_schwab_account_sync() -> dict[str, Any]:
    """Refresh the Schwab read-only account packet before live-book review."""
    try:
        report = build_schwab_account_sync()
        save_schwab_account_sync(report)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "refresh-failed",
            "error": str(exc),
        }
    return {
        "ok": bool(report.get("ok")),
        "status": str(report.get("verdict") or "unknown"),
        "generatedAt": report.get("generatedAt"),
        "counts": report.get("counts") or {},
        "matchedSuffix": report.get("matchedSuffix"),
        "readOnly": bool(report.get("brokerReadOnly")),
    }


def refresh_live_account_sync() -> dict[str, Any]:
    """Refresh the live-account sync artifact from Schwab, with TOS fallback.

    This maintenance path stays read-only. Schwab is preferred for automation
    because it does not depend on the desktop window being visible.
    """
    try:
        report = build_live_account_sync(refresh_schwab=True, refresh_statement=False)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "refresh-failed",
            "error": str(exc),
        }
    return {
        "ok": bool(report.get("ok")),
        "status": str(report.get("verdict") or "unknown"),
        "generatedAt": report.get("generatedAt"),
        "counts": report.get("counts") or {},
        "matchedSuffix": report.get("matchedSuffix"),
        "accountDataSource": report.get("accountDataSource"),
    }


def refresh_live_position_review() -> dict[str, Any]:
    """Refresh the live-position review artifact from the current live sync."""
    try:
        report = build_live_position_review(refresh_live_sync=False)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "refresh-failed",
            "error": str(exc),
        }
    return {
        "ok": bool(report.get("ok")),
        "status": str(report.get("verdict") or "unknown"),
        "generatedAt": report.get("generatedAt"),
        "counts": report.get("counts") or {},
    }


def refresh_model_command_center() -> dict[str, Any]:
    """Rebuild the shared multi-model command center artifact.

    This gives Codex, Claude, or any future collaborator one canonical desk
    summary instead of making each model rediscover the current state from raw
    reports.
    """
    try:
        report = build_command_center()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "refresh-failed",
            "error": str(exc),
        }
    return {
        "ok": True,
        "status": "ready",
        "generatedAt": report.get("generatedAt"),
        "headlineMetrics": report.get("headlineMetrics") or {},
        "missionCount": len(report.get("activeMissions") or []),
        "noteCount": len(report.get("recentNotes") or []),
    }


def refresh_research_cycle() -> dict[str, Any]:
    """Refresh the consolidated backtest lane as part of normal desk upkeep.

    This keeps the shadow, replay, and hypothesis layers from going stale
    between manual operator runs. The result is still research-only, but it is
    now part of the same redundancy loop as the rest of the desk.
    """
    try:
        report = build_research_cycle()
        save_research_cycle(report)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "refresh-failed",
            "error": str(exc),
        }
    strategy = report.get("strategyLab") or {}
    replay = report.get("strategyReplay") or {}
    shadow = report.get("shadow") or {}
    scenario_backtest = report.get("scenarioBacktest") or {}
    return {
        "ok": bool(report.get("ok", True)),
        "status": str(report.get("verdict") or "unknown"),
        "generatedAt": report.get("generatedAt"),
        "shadowTrackedCount": int(shadow.get("trackedCount") or 0),
        "shadowClosedCount": int(shadow.get("closedCount") or 0),
        "strategyVerdict": strategy.get("verdict"),
        "strategyScoredCount": int(strategy.get("scoredCount") or 0),
        "replayVerdict": replay.get("verdict"),
        "replayScoredCount": int(replay.get("scoredCount") or 0),
        "scenarioCount": int(scenario_backtest.get("scenarioCount") or 0),
        "scenarioClosedEvidenceCount": int(scenario_backtest.get("closedEvidenceCount") or 0),
        "scenarioClosedObservationCount": int(scenario_backtest.get("closedObservationCount") or 0),
        "scenarioVerdictCounts": scenario_backtest.get("verdictCounts") or {},
        "scenarioObservationVerdictCounts": scenario_backtest.get("observationVerdictCounts") or {},
        "scenarioTopFocusTickers": scenario_backtest.get("topFocusTickers") or [],
    }


def maintenance_report_text(report: dict[str, Any]) -> str:
    """Render a short operator-friendly maintenance report."""
    lines = [
        "Inferno Ops Maintenance",
        "",
        f"Generated: {report.get('generatedAt')}",
    ]
    ticker_audit = report.get("tickerUniverseAudit") or {}
    if ticker_audit:
        counts = ticker_audit.get("counts") or {}
        lines.append(
            f"Ticker universe: {ticker_audit.get('verdict')} | "
            f"critical {counts.get('criticalIssueCount', 0)} | "
            f"advisory {counts.get('advisoryIssueCount', 0)}"
        )
    data_audit = report.get("dataReadinessAudit") or {}
    if data_audit:
        lines.append(
            f"Data readiness: {data_audit.get('verdict')} | "
            f"daily-safe {data_audit.get('dailyPrepReady')} | "
            f"research-ready {data_audit.get('researchReady')}"
        )
    downloads_watch = report.get("downloadsWatch") or {}
    if downloads_watch:
        lines.append(
            f"Downloads watch: skipped {downloads_watch.get('skipped')} | "
            f"imported {(downloads_watch.get('downloadsManager') or {}).get('importedFiles', 0)} files"
        )
    email_repair = report.get("emailRepair") or {}
    if email_repair:
        lines.append(f"Email repair: {email_repair.get('status')}")
    cloud_control_plane = report.get("cloudControlPlane") or {}
    if cloud_control_plane:
        detail = cloud_control_plane.get("message") or cloud_control_plane.get("error") or "-"
        lines.append(
            f"Cloud control plane: {cloud_control_plane.get('status')} | "
            f"{cloud_control_plane.get('projectId') or '-'} | {detail}"
        )
    cloud_execution = report.get("cloudExecutionAudit") or {}
    if cloud_execution:
        detail = cloud_execution.get("error") or "-"
        lines.append(
            f"Cloud execution audit: {cloud_execution.get('status')} | "
            f"{cloud_execution.get('projectId') or '-'}"
            + (f" | {detail}" if detail != "-" else "")
        )
    advisories = report.get("advisories") or []
    if advisories:
        lines.append(f"Advisories: {', '.join(advisories)}")
    paper_director = report.get("paperTestDirector") or {}
    if paper_director:
        counts = paper_director.get("counts") or {}
        lines.append(
            f"Paper test director: {paper_director.get('status')} | "
            f"stageable {counts.get('stageableNow', 0)} | "
            f"auto-paper {counts.get('autoPaperSelected', 0)} | "
            f"approval-only {counts.get('approvalOnly', 0)}"
        )
    paper_loop = report.get("paperEvidenceLoop") or {}
    if paper_loop:
        counts = paper_loop.get("counts") or {}
        lines.append(
            f"Paper evidence loop: {paper_loop.get('status')} | "
            f"planned {counts.get('plannedFillRows', 0)} | "
            f"open {counts.get('openFillRows', 0)} | "
            f"remaining {counts.get('remainingForPromotion', 0)}"
        )
    paper_bottleneck = report.get("paperBottleneckReducer") or {}
    if paper_bottleneck:
        counts = paper_bottleneck.get("counts") or {}
        lines.append(
            f"Paper bottleneck reducer: {paper_bottleneck.get('status')} | "
            f"scenarios {counts.get('scenarios', 0)} | "
            f"paper {counts.get('executablePaper', 0)} | "
            f"shadow {counts.get('shadowOnly', 0)}"
        )
    paper_exit = report.get("paperExitAudit") or {}
    if paper_exit:
        counts = paper_exit.get("counts") or {}
        lines.append(
            f"Paper exit audit: {paper_exit.get('status')} | "
            f"open {counts.get('openLedgerTickets', 0)} | "
            f"close-now {counts.get('closeNow', 0)} | "
            f"reconcile {counts.get('orphanOpenFillRows', 0)}"
        )
    paper_mtm = report.get("paperMarkToMarket") or {}
    if paper_mtm:
        lines.append(
            f"Paper mark-to-market: {paper_mtm.get('status')} | "
            f"open {paper_mtm.get('openPositionCount', 0)} | "
            f"marked {paper_mtm.get('markedTickets', 0)}"
        )
    broker_preview = report.get("brokerPreview") or {}
    if broker_preview:
        lines.append(
            f"Broker preview: {broker_preview.get('status')} | "
            f"count {broker_preview.get('count', 0)} | "
            f"preview-only {broker_preview.get('previewOnly', False)}"
        )
    stale_approvals = report.get("staleApprovalGovernor") or {}
    if stale_approvals:
        demoted = stale_approvals.get("demoted") or []
        tickers = ", ".join(entry.get("ticker") or "?" for entry in demoted) or "-"
        lines.append(
            f"Stale approval governor: {stale_approvals.get('status')} | "
            f"ttl {stale_approvals.get('ttlMarketDays')}d | demoted {tickers}"
        )
    approval_inbox = report.get("approvalInbox") or {}
    if approval_inbox:
        lines.append(
            f"Approval inbox: {approval_inbox.get('status')} | "
            f"checked {approval_inbox.get('checkedCount', 0)} | "
            f"applied {approval_inbox.get('appliedCount', 0)} | "
            f"skipped {approval_inbox.get('skippedCount', 0)}"
        )
    approval_dispatch = report.get("approvalDispatch") or {}
    if approval_dispatch:
        lines.append(
            f"Approval dispatch: {approval_dispatch.get('status')} | "
            f"pending {approval_dispatch.get('pendingCount', 0)} | "
            f"sent {approval_dispatch.get('sentCount', 0)} | "
            f"skipped {approval_dispatch.get('skippedCount', 0)}"
        )
    schwab_account_sync = report.get("schwabAccountSync") or {}
    if schwab_account_sync:
        counts = schwab_account_sync.get("counts") or {}
        lines.append(
            f"Schwab account sync: {schwab_account_sync.get('status')} | "
            f"positions {counts.get('positions', 0)} | "
            f"approved {counts.get('approvedAccounts', 0)}/{counts.get('accounts', 0)} | "
            f"suffix {schwab_account_sync.get('matchedSuffix') or '-'}"
        )
    live_account_sync = report.get("liveAccountSync") or {}
    if live_account_sync:
        counts = live_account_sync.get("counts") or {}
        lines.append(
            f"Live account sync: {live_account_sync.get('status')} | "
            f"positions {counts.get('positions', 0)} | "
            f"matched {counts.get('matchedPositions', 0)} | "
            f"suffix {live_account_sync.get('matchedSuffix') or '-'} | "
            f"source {live_account_sync.get('accountDataSource') or '-'}"
        )
    live_position_review = report.get("livePositionReview") or {}
    if live_position_review:
        counts = live_position_review.get("counts") or {}
        lines.append(
            f"Live position review: {live_position_review.get('status')} | "
            f"supported {counts.get('supported', 0)} | "
            f"review {counts.get('review', 0)} | "
            f"fragile {counts.get('fragile', 0)}"
        )
    model_command_center = report.get("modelCommandCenter") or {}
    if model_command_center:
        metrics = model_command_center.get("headlineMetrics") or {}
        lines.append(
            f"Model command center: {model_command_center.get('status')} | "
            f"missions {model_command_center.get('missionCount', 0)} | "
            f"notes {model_command_center.get('noteCount', 0)} | "
            f"live-fragile {metrics.get('liveFragile', 0)}"
        )
    research_cycle = report.get("researchCycle") or {}
    if research_cycle:
        lines.append(
            f"Research cycle: {research_cycle.get('status')} | "
            f"shadow tracked {research_cycle.get('shadowTrackedCount', 0)} | "
            f"shadow closed {research_cycle.get('shadowClosedCount', 0)} | "
            f"strategy {research_cycle.get('strategyVerdict') or '-'} "
            f"({research_cycle.get('strategyScoredCount', 0)} scored) | "
            f"scenarios {research_cycle.get('scenarioCount', 0)} | "
            f"scenario evidence {research_cycle.get('scenarioClosedEvidenceCount', 0)} | "
            f"scenario observations {research_cycle.get('scenarioClosedObservationCount', 0)}"
        )
    watchdog = report.get("watchdog") or {}
    if watchdog:
        lines.append(
            f"Watchdog: {'ok' if watchdog.get('ok') else 'attention'} | "
            f"reasons {len(watchdog.get('reasons') or [])}"
        )
    return "\n".join(lines).rstrip() + "\n"


def save_report(report: dict[str, Any]) -> None:
    """Persist maintenance artifacts for doctor/runbook use."""
    ensure_dirs()
    atomic_write_json(OPS_MAINTENANCE_FILE, report)
    atomic_write_text(OPS_MAINTENANCE_TEXT_FILE, maintenance_report_text(report))


def run_maintenance(
    *,
    backtest_root: Path,
    sheet_name: str,
    force_email: bool = False,
    skip_email_repair: bool = False,
    skip_outbound: bool = False,
    cloud_region: str = DEFAULT_CLOUD_REGION,
) -> dict[str, Any]:
    """Run the safe maintenance sweep and persist the result."""
    load_env_file(ROOT / ".env.smtp")
    ensure_dirs()
    ticker_audit = build_ticker_universe_audit_from_sheet(backtest_root, sheet_name)
    data_audit = run_audit()
    downloads_watch = run_watch(automation=False, export_first=False)
    email_repair = (
        {"attempted": False, "ok": True, "status": "skipped"}
        if skip_email_repair or skip_outbound
        else repair_morning_email(force=force_email)
    )
    cloud_control_plane = refresh_cloud_control_plane(region=cloud_region)
    cloud_execution_audit = refresh_cloud_execution_audit(region=cloud_region)
    paper_test_director = refresh_paper_test_director()
    paper_bottleneck_reducer = refresh_paper_bottleneck_reducer()
    paper_evidence_loop = refresh_paper_evidence_loop()
    paper_exit_audit = refresh_paper_exit_audit()
    paper_mark_to_market = refresh_paper_mark_to_market()
    broker_preview = refresh_broker_preview()
    stale_approvals = refresh_stale_approval_governor()
    approval_inbox = refresh_approval_inbox()
    approval_dispatch = (
        {"ok": True, "status": "skipped", "pendingCount": 0, "sentCount": 0, "skippedCount": 0}
        if skip_outbound
        else refresh_approval_dispatch()
    )
    schwab_account_sync = refresh_schwab_account_sync()
    live_account_sync = refresh_live_account_sync()
    live_position_review = refresh_live_position_review()
    model_command_center = refresh_model_command_center()
    research_cycle = refresh_research_cycle()
    watchdog_status, watchdog_exit = run_watchdog_check(send_alerts=False)
    advisories = advisory_failures(
        ("cloud-control-plane", cloud_control_plane),
        ("cloud-execution-audit", cloud_execution_audit),
    )
    report = {
        "generatedAt": local_now().isoformat(),
        "tickerUniverseAudit": {
            "verdict": ticker_audit.get("verdict"),
            "counts": ticker_audit.get("counts"),
        },
        "dataReadinessAudit": {
            "verdict": data_audit.get("verdict"),
            "dailyPrepReady": data_audit.get("dailyPrepReady"),
            "researchReady": data_audit.get("researchReady"),
        },
        "downloadsWatch": {
            "generatedAt": downloads_watch.get("generatedAt"),
            "skipped": downloads_watch.get("skipped"),
            "skipReason": downloads_watch.get("skipReason"),
            "downloadsManager": downloads_watch.get("downloadsManager"),
            "fillIngest": downloads_watch.get("fillIngest"),
        },
        "emailRepair": email_repair,
        "cloudControlPlane": cloud_control_plane,
        "cloudExecutionAudit": cloud_execution_audit,
        "advisories": advisories,
        "paperTestDirector": paper_test_director,
        "paperBottleneckReducer": paper_bottleneck_reducer,
        "paperEvidenceLoop": paper_evidence_loop,
        "paperExitAudit": paper_exit_audit,
        "paperMarkToMarket": paper_mark_to_market,
        "brokerPreview": broker_preview,
        "staleApprovalGovernor": stale_approvals,
        "approvalInbox": approval_inbox,
        "approvalDispatch": approval_dispatch,
        "schwabAccountSync": schwab_account_sync,
        "liveAccountSync": live_account_sync,
        "livePositionReview": live_position_review,
        "modelCommandCenter": model_command_center,
        "researchCycle": research_cycle,
        "watchdog": watchdog_status,
        "ok": (
            ticker_audit.get("ok")
            and bool(data_audit.get("dailyPrepReady"))
            and bool(paper_test_director.get("ok"))
            and bool(paper_bottleneck_reducer.get("ok"))
            and bool(paper_evidence_loop.get("ok"))
            and bool(paper_exit_audit.get("ok"))
            and bool(paper_mark_to_market.get("ok"))
            and bool(broker_preview.get("ok"))
            and bool(stale_approvals.get("ok"))
            and bool(approval_inbox.get("ok"))
            and bool(approval_dispatch.get("ok"))
            and bool(live_account_sync.get("ok"))
            and bool(live_position_review.get("ok"))
            and bool(model_command_center.get("ok"))
            and bool(research_cycle.get("ok"))
            and watchdog_exit == 0
        ),
    }
    save_report(report)
    record_heartbeat(
        "ops_maintenance",
        status="ok" if report.get("ok") else "fail",
        summary="ops maintenance sweep complete" if report.get("ok") else "ops maintenance needs attention",
        detail={
            "paperStageable": (paper_test_director.get("counts") or {}).get("stageableNow"),
            "paperScenarios": (paper_bottleneck_reducer.get("counts") or {}).get("scenarios"),
            "researchCycle": research_cycle.get("status"),
            "watchdogExit": watchdog_exit,
        },
    )
    return report


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the maintenance runner."""
    parser = argparse.ArgumentParser(description="Refresh stale desk artifacts and repair missed morning email delivery.")
    parser.add_argument("command", nargs="?", choices=("run", "status"), default="run")
    parser.add_argument("--backtest-root", default=str(default_backtest_root()))
    parser.add_argument("--sheet-name", default=DEFAULT_SHEET_NAME)
    parser.add_argument("--force-email", action="store_true", help="Send the latest snapshot even if ops status says email already sent.")
    parser.add_argument("--skip-email-repair", action="store_true", help="Refresh maintenance artifacts without sending a missed morning email.")
    parser.add_argument("--skip-outbound", action="store_true", help="Refresh maintenance artifacts without sending email or approval prompts.")
    parser.add_argument(
        "--ok-on-attention",
        action="store_true",
        help="Exit zero after a completed sweep even when the desk report still needs attention.",
    )
    parser.add_argument("--cloud-region", default=DEFAULT_CLOUD_REGION, help="Cloud region used by read-only cloud maintenance checks.")
    return parser.parse_args()


def main() -> int:
    """Run or show the latest ops maintenance sweep."""
    args = parse_args()
    if args.command == "status" and OPS_MAINTENANCE_TEXT_FILE.exists():
        print(OPS_MAINTENANCE_TEXT_FILE.read_text(encoding="utf-8"))
        latest = load_json_file(OPS_MAINTENANCE_FILE) or {}
        return 0 if latest.get("ok") else 1

    report = run_maintenance(
        backtest_root=Path(args.backtest_root).expanduser().resolve(),
        sheet_name=args.sheet_name,
        force_email=args.force_email,
        skip_email_repair=args.skip_email_repair,
        skip_outbound=args.skip_outbound,
        cloud_region=args.cloud_region,
    )
    print(maintenance_report_text(report))
    if report.get("ok") or args.ok_on_attention:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
