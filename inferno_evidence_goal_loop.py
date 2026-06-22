from __future__ import annotations

"""Bounded, stateful automation loop for the Inferno paper-evidence lane.

The loop applies the production pattern described in the linked automation
article: a scheduled heartbeat, reusable desk rules, persistent state, a
separate verification pass, and explicit stop conditions.

Strict contract:
- research-only and non-promotable
- may refresh data and mutate isolated paper/shadow evidence artifacts
- never approves/rejects tickets or changes the eligible universe
- never submits broker orders or widens live authority
- stops on authority drift, process breaches, no progress, timeout, or the
  configured iteration cap
"""

import argparse
import hashlib
import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from inferno_config import ROOT, local_now
from inferno_doctor import in_current_service_cycle
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


GOAL_LOOP_FILE = DATA_DIR / "inferno_evidence_goal_loop.json"
GOAL_LOOP_STATE_FILE = DATA_DIR / "inferno_evidence_goal_loop_state.json"
GOAL_LOOP_TEXT_FILE = REPORTS_DIR / "evidence_goal_loop_latest.txt"
GOAL_LOOP_STAGE = "paper-evidence-goal-loop-research-only"

AUTHORITY_FILE = DATA_DIR / "inferno_authority_manifest.json"
PROCESS_FILE = DATA_DIR / "inferno_process_compliance.json"
PAPER_LOOP_FILE = DATA_DIR / "inferno_paper_evidence_loop.json"
FAST_PAPER_FILE = DATA_DIR / "inferno_fast_paper_cohort.json"
PERFORMANCE_FILE = DATA_DIR / "inferno_performance_analytics.json"
STRATEGY_LAB_FILE = DATA_DIR / "inferno_strategy_lab.json"
PAPER_VELOCITY_FILE = DATA_DIR / "inferno_paper_velocity.json"
SCENARIO_EVIDENCE_FILE = DATA_DIR / "inferno_scenario_evidence.json"

KNOWLEDGE_DIR = ROOT / "knowledge" / "agent-loop"
KNOWLEDGE_RUNS_DIR = KNOWLEDGE_DIR / "runs"
KNOWLEDGE_LESSONS_DIR = KNOWLEDGE_DIR / "lessons"
KNOWLEDGE_CURRENT_FILE = KNOWLEDGE_DIR / "Current Loop State.md"

SAFE_AUTHORITY_LEVELS = {"paper-evidence-only"}
MAX_STATE_RUNS = 30
DEFAULT_MAX_ITERATIONS = 2
DEFAULT_TIMEOUT_SECONDS = 600
DEFAULT_DUPLICATE_COOLDOWN_MINUTES = 60

PRECHECK_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("process compliance precheck", ("python3", "inferno_process_compliance.py", "build")),
    ("authority precheck", ("python3", "inferno_authority_controller.py", "build")),
)

CYCLE_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("paper evidence harvest", ("./run_inferno_paper_evidence_harvest.sh",)),
    ("performance analytics", ("python3", "inferno_performance_analytics.py", "build")),
    ("strategy lab", ("python3", "inferno_strategy_lab.py", "build")),
    ("paper velocity", ("python3", "inferno_paper_velocity.py", "run")),
    ("process compliance verification", ("python3", "inferno_process_compliance.py", "build")),
    ("authority verification", ("python3", "inferno_authority_controller.py", "build")),
)

ARTIFACT_PATHS: dict[str, Path] = {
    "authority": AUTHORITY_FILE,
    "processCompliance": PROCESS_FILE,
    "paperEvidenceLoop": PAPER_LOOP_FILE,
    "fastPaper": FAST_PAPER_FILE,
    "performance": PERFORMANCE_FILE,
    "strategyLab": STRATEGY_LAB_FILE,
    "paperVelocity": PAPER_VELOCITY_FILE,
    "scenarioEvidence": SCENARIO_EVIDENCE_FILE,
}


def _tail(value: str, limit: int = 4000) -> str:
    """Keep command diagnostics useful without making the state file unbounded."""
    return value[-limit:]


def run_command(
    name: str,
    argv: tuple[str, ...],
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Run one isolated loop command and capture a bounded diagnostic."""
    started = local_now()
    monotonic_started = time.monotonic()
    try:
        completed = subprocess.run(
            list(argv),
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "name": name,
            "argv": list(argv),
            "startedAt": started.isoformat(),
            "finishedAt": local_now().isoformat(),
            "durationSeconds": round(time.monotonic() - monotonic_started, 3),
            "ok": completed.returncode == 0,
            "returnCode": completed.returncode,
            "stdoutTail": _tail(completed.stdout),
            "stderrTail": _tail(completed.stderr),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "argv": list(argv),
            "startedAt": started.isoformat(),
            "finishedAt": local_now().isoformat(),
            "durationSeconds": round(time.monotonic() - monotonic_started, 3),
            "ok": False,
            "returnCode": None,
            "timedOut": True,
            "stdoutTail": _tail(str(exc.stdout or "")),
            "stderrTail": _tail(str(exc.stderr or "")),
        }
    except OSError as exc:
        return {
            "name": name,
            "argv": list(argv),
            "startedAt": started.isoformat(),
            "finishedAt": local_now().isoformat(),
            "durationSeconds": round(time.monotonic() - monotonic_started, 3),
            "ok": False,
            "returnCode": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def load_artifacts() -> dict[str, dict[str, Any]]:
    """Load the exact artifact set used by the independent verifier."""
    return {
        name: load_json_file(path) or {}
        for name, path in ARTIFACT_PATHS.items()
    }


def authority_boundary_errors(authority: dict[str, Any]) -> list[str]:
    """Return hard safety violations in the authority manifest."""
    decision = authority.get("decision") or {}
    errors: list[str] = []
    if not authority:
        return ["authority manifest missing"]
    if decision.get("liveTradingAllowed") is not False:
        errors.append("liveTradingAllowed is not hard-false")
    if decision.get("brokerSubmitAllowed") is not False:
        errors.append("brokerSubmitAllowed is not hard-false")
    level = str(decision.get("authorityLevel") or "")
    if level not in SAFE_AUTHORITY_LEVELS:
        errors.append(f"authority level {level or 'missing'} is not unattended paper scope")
    if "submit_live_order" in set(decision.get("allowedActions") or []):
        errors.append("submit_live_order appeared in allowed actions")
    return errors


def process_boundary_errors(process: dict[str, Any]) -> list[str]:
    """Return hard process-gate violations for new simulated entries."""
    if not process:
        return ["process compliance artifact missing"]
    if process.get("newPaperEntriesAllowed") is not True:
        return ["process compliance stopped new paper entries"]
    if int((process.get("counts") or {}).get("hardBreaches") or 0) > 0:
        return ["process compliance reports hard breaches"]
    return []


def verify_precheck(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Verify the authority and process boundary before evidence mutation."""
    errors = authority_boundary_errors(artifacts.get("authority") or {})
    errors.extend(process_boundary_errors(artifacts.get("processCompliance") or {}))
    return {
        "passed": not errors,
        "errors": errors,
        "authorityIntact": not authority_boundary_errors(artifacts.get("authority") or {}),
        "paperEntryGateOpen": not process_boundary_errors(
            artifacts.get("processCompliance") or {}
        ),
    }


def _artifact_fresh(payload: dict[str, Any], *, now: datetime) -> bool:
    return in_current_service_cycle(
        str(payload.get("generatedAt") or ""),
        now=now,
    )


def verify_cycle(
    artifacts: dict[str, dict[str, Any]],
    command_results: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Independently verify a completed iteration against objective gates."""
    current = now or local_now()
    errors = authority_boundary_errors(artifacts.get("authority") or {})
    errors.extend(process_boundary_errors(artifacts.get("processCompliance") or {}))

    failed_commands = [
        result.get("name")
        for result in command_results
        if result.get("ok") is not True
    ]
    if failed_commands:
        errors.append(f"commands failed: {', '.join(str(item) for item in failed_commands)}")

    stale_or_missing = [
        name
        for name, payload in artifacts.items()
        if not payload or not _artifact_fresh(payload, now=current)
    ]
    if stale_or_missing:
        errors.append(f"artifacts stale or missing: {', '.join(stale_or_missing)}")

    fast_paper = artifacts.get("fastPaper") or {}
    if fast_paper:
        if fast_paper.get("researchOnly") is not True:
            errors.append("fast-paper artifact lost researchOnly=true")
        if fast_paper.get("promotable") is not False:
            errors.append("fast-paper artifact lost promotable=false")
        if fast_paper.get("liveTradingAllowed") is not False:
            errors.append("fast-paper artifact lost liveTradingAllowed=false")
        if fast_paper.get("brokerSubmitAllowed") is not False:
            errors.append("fast-paper artifact lost brokerSubmitAllowed=false")

    return {
        "passed": not errors,
        "errors": errors,
        "failedCommands": failed_commands,
        "staleOrMissingArtifacts": stale_or_missing,
        "authorityIntact": not authority_boundary_errors(artifacts.get("authority") or {}),
        "paperEntryGateOpen": not process_boundary_errors(
            artifacts.get("processCompliance") or {}
        ),
    }


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dominant_blocker(performance: dict[str, Any]) -> tuple[str | None, int]:
    categories = performance.get("blockReasonCategories") or {}
    ranked = sorted(
        (
            (str(name), int(_number((details or {}).get("count"))))
            for name, details in categories.items()
        ),
        key=lambda item: (-item[1], item[0]),
    )
    return ranked[0] if ranked else (None, 0)


def progress_snapshot(
    artifacts: dict[str, dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Extract the small state vector that determines whether the loop moved."""
    current = now or local_now()
    performance = artifacts.get("performance") or {}
    paper_loop = artifacts.get("paperEvidenceLoop") or {}
    fast_paper = artifacts.get("fastPaper") or {}
    strategy_lab = artifacts.get("strategyLab") or {}
    velocity = artifacts.get("paperVelocity") or {}
    scenario_evidence = artifacts.get("scenarioEvidence") or {}
    fast_counts = fast_paper.get("counts") or {}
    scenario_counts = scenario_evidence.get("counts") or {}
    dominant_blocker, dominant_blocker_count = _dominant_blocker(performance)
    exit_dates = sorted(
        str(item.get("exitEligibleDate"))
        for item in fast_paper.get("openSlate") or []
        if item.get("exitEligibleDate")
    )
    eligible_fast_exits = sum(
        1 for exit_date in exit_dates if exit_date <= current.date().isoformat()
    )
    return {
        "scoredPaperTickets": int(
            ((performance.get("closedMetrics") or {}).get("scoredCount")) or 0
        ),
        "remainingForPromotion": int(
            ((paper_loop.get("counts") or {}).get("remainingForPromotion")) or 0
        ),
        "paperLoopVerdict": paper_loop.get("verdict"),
        "fastPaperVerdict": fast_paper.get("verdict"),
        "fastPaperCounts": fast_counts,
        "fastPaperClosedLifetime": int(
            _number(fast_counts.get("closedLifetime", fast_counts.get("lifetimeClosed")))
        ),
        "fastPaperOpen": int(_number(fast_counts.get("open"))),
        "eligibleFastPaperExits": eligible_fast_exits,
        "nextFastPaperExitEligibleDate": exit_dates[0] if exit_dates else None,
        "scenarioObservationsClosed": int(_number(scenario_counts.get("closed"))),
        "scenarioObservationsOpen": int(_number(scenario_counts.get("open"))),
        "strategyLabVerdict": (strategy_lab.get("deskVerdict") or {}).get("level"),
        "weeklyCloseRate": (velocity.get("velocity") or {}).get("weeklyRate30dWindow"),
        "projectedWeeksToPromotion": (velocity.get("velocity") or {}).get(
            "projectedWeeksToPromotion"
        ),
        "dominantBlocker": dominant_blocker,
        "dominantBlockerCount": dominant_blocker_count,
    }


def progress_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Score only outcome changes that a fixed evaluator can verify."""
    scored_delta = int(_number(after.get("scoredPaperTickets"))) - int(
        _number(before.get("scoredPaperTickets"))
    )
    remaining_reduction = int(_number(before.get("remainingForPromotion"))) - int(
        _number(after.get("remainingForPromotion"))
    )
    promotion_evidence_delta = max(0, scored_delta, remaining_reduction)
    fast_closed_delta = max(
        0,
        int(_number(after.get("fastPaperClosedLifetime")))
        - int(_number(before.get("fastPaperClosedLifetime"))),
    )
    scenario_closed_delta = max(
        0,
        int(_number(after.get("scenarioObservationsClosed")))
        - int(_number(before.get("scenarioObservationsClosed"))),
    )
    blocker_reduction = 0
    if (
        before.get("dominantBlocker")
        and before.get("dominantBlocker") == after.get("dominantBlocker")
    ):
        blocker_reduction = max(
            0,
            int(_number(before.get("dominantBlockerCount")))
            - int(_number(after.get("dominantBlockerCount"))),
        )
    weekly_rate_delta = round(
        _number(after.get("weeklyCloseRate")) - _number(before.get("weeklyCloseRate")),
        4,
    )
    accepted_points = (
        promotion_evidence_delta * 100
        + fast_closed_delta * 25
        + min(scenario_closed_delta, 10)
        + min(blocker_reduction, 10)
    )
    return {
        "scoredPaperTicketsDelta": scored_delta,
        "remainingForPromotionReduction": remaining_reduction,
        "promotionEvidenceDelta": promotion_evidence_delta,
        "fastPaperClosedDelta": fast_closed_delta,
        "scenarioObservationsClosedDelta": scenario_closed_delta,
        "dominantBlockerReduction": blocker_reduction,
        "weeklyCloseRateDelta": weekly_rate_delta,
        "acceptedProgressPoints": accepted_points,
    }


def work_signature(snapshot: dict[str, Any], *, now: datetime | None = None) -> str:
    """Hash only state that can create new useful work for the next cycle."""
    current = now or local_now()
    payload = {
        "localDate": current.date().isoformat(),
        "scoredPaperTickets": snapshot.get("scoredPaperTickets"),
        "remainingForPromotion": snapshot.get("remainingForPromotion"),
        "fastPaperVerdict": snapshot.get("fastPaperVerdict"),
        "fastPaperClosedLifetime": snapshot.get("fastPaperClosedLifetime"),
        "fastPaperOpen": snapshot.get("fastPaperOpen"),
        "eligibleFastPaperExits": snapshot.get("eligibleFastPaperExits"),
        "nextFastPaperExitEligibleDate": snapshot.get("nextFastPaperExitEligibleDate"),
        "scenarioObservationsClosed": snapshot.get("scenarioObservationsClosed"),
        "scenarioObservationsOpen": snapshot.get("scenarioObservationsOpen"),
        "dominantBlocker": snapshot.get("dominantBlocker"),
        "dominantBlockerCount": snapshot.get("dominantBlockerCount"),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _artifact_repairs(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
    *,
    now: datetime,
) -> list[str]:
    return [
        name
        for name in ARTIFACT_PATHS
        if (
            not before.get(name)
            or not _artifact_fresh(before.get(name) or {}, now=now)
        )
        and after.get(name)
        and _artifact_fresh(after.get(name) or {}, now=now)
    ]


def classify_value(
    verification: dict[str, Any],
    delta: dict[str, Any],
    repairs: list[str],
) -> str:
    if verification.get("passed") is not True:
        return "blocked"
    if int(_number(delta.get("acceptedProgressPoints"))) > 0:
        return "productive"
    if repairs:
        return "maintenance"
    return "no-op"


def progress_fingerprint(
    artifacts: dict[str, dict[str, Any]],
    verification: dict[str, Any],
) -> str:
    """Hash the progress vector plus verifier failures for no-progress stops."""
    payload = {
        "progress": progress_snapshot(artifacts),
        "errors": sorted(str(item) for item in verification.get("errors") or []),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _run_commands(
    specs: tuple[tuple[str, tuple[str, ...]], ...],
    *,
    timeout_seconds: int,
    command_runner: Callable[..., dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        command_runner(name, argv, timeout_seconds=timeout_seconds)
        for name, argv in specs
    ]


def _recent_duplicate_run(
    state: dict[str, Any],
    *,
    signature: str,
    now: datetime,
    cooldown_minutes: int,
) -> bool:
    if cooldown_minutes <= 0:
        return False
    runs = state.get("runs") or []
    if not runs:
        return False
    last = runs[-1]
    if last.get("workSignature") != signature:
        return False
    if last.get("verificationPassed") is not True:
        return False
    generated_raw = str(last.get("generatedAt") or "")
    try:
        generated = datetime.fromisoformat(generated_raw)
    except ValueError:
        return False
    if generated.tzinfo is None and now.tzinfo is not None:
        generated = generated.replace(tzinfo=now.tzinfo)
    age_seconds = (now - generated).total_seconds()
    return 0 <= age_seconds < cooldown_minutes * 60


def _command_duration(results: list[dict[str, Any]]) -> float:
    return round(sum(_number(result.get("durationSeconds")) for result in results), 3)


def build_goal_loop(
    *,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    duplicate_cooldown_minutes: int = DEFAULT_DUPLICATE_COOLDOWN_MINUTES,
    command_runner: Callable[..., dict[str, Any]] = run_command,
    artifact_loader: Callable[[], dict[str, dict[str, Any]]] = load_artifacts,
    state_loader: Callable[[], dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run the bounded evidence loop and return its complete audit payload."""
    started = now or local_now()
    monotonic_started = time.monotonic()
    load_state = state_loader or (lambda: load_json_file(GOAL_LOOP_STATE_FILE) or {})
    prior_state = load_state()
    precheck_commands = _run_commands(
        PRECHECK_COMMANDS,
        timeout_seconds=timeout_seconds,
        command_runner=command_runner,
    )
    precheck_artifacts = artifact_loader()
    precheck = verify_precheck(precheck_artifacts)
    precheck_failures = [
        result.get("name")
        for result in precheck_commands
        if result.get("ok") is not True
    ]
    if precheck_failures:
        precheck["errors"].append(
            f"precheck commands failed: {', '.join(str(item) for item in precheck_failures)}"
        )
        precheck["passed"] = False

    iterations: list[dict[str, Any]] = []
    verdict = "blocked-safety"
    stop_reason = "precheck failed"
    last_fingerprint: str | None = None
    final_artifacts = precheck_artifacts
    final_verification = precheck
    baseline_progress = progress_snapshot(precheck_artifacts, now=started)
    final_progress = baseline_progress
    delta = progress_delta(baseline_progress, final_progress)
    repairs: list[str] = []
    value_class = "blocked"
    signature = work_signature(baseline_progress, now=started)

    if precheck.get("passed"):
        all_fresh = all(
            payload and _artifact_fresh(payload, now=started)
            for payload in precheck_artifacts.values()
        )
        duplicate = _recent_duplicate_run(
            prior_state,
            signature=signature,
            now=started,
            cooldown_minutes=duplicate_cooldown_minutes,
        )
        useful_work_ready = int(
            _number(baseline_progress.get("eligibleFastPaperExits"))
        ) > 0
        if duplicate and all_fresh and not useful_work_ready:
            verdict = "skipped-duplicate-work"
            stop_reason = (
                "meaningful state is unchanged inside the duplicate-work cooldown"
            )
            value_class = "skipped"
            final_verification = verify_cycle(precheck_artifacts, [], now=started)
        else:
            verdict = "stopped-iteration-cap"
            stop_reason = f"reached {max_iterations} iteration(s)"
            for iteration_number in range(1, max(1, max_iterations) + 1):
                results = _run_commands(
                    CYCLE_COMMANDS,
                    timeout_seconds=timeout_seconds,
                    command_runner=command_runner,
                )
                artifacts = artifact_loader()
                verification = verify_cycle(artifacts, results, now=started)
                fingerprint = progress_fingerprint(artifacts, verification)
                progress = progress_snapshot(artifacts, now=started)
                iteration_delta = progress_delta(baseline_progress, progress)
                iteration_repairs = _artifact_repairs(
                    precheck_artifacts,
                    artifacts,
                    now=started,
                )
                iteration_value = classify_value(
                    verification,
                    iteration_delta,
                    iteration_repairs,
                )
                iterations.append(
                    {
                        "iteration": iteration_number,
                        "commands": results,
                        "commandDurationSeconds": _command_duration(results),
                        "verification": verification,
                        "progress": progress,
                        "progressDelta": iteration_delta,
                        "artifactRepairs": iteration_repairs,
                        "valueClass": iteration_value,
                        "fingerprint": fingerprint,
                    }
                )
                final_artifacts = artifacts
                final_verification = verification
                final_progress = progress
                delta = iteration_delta
                repairs = iteration_repairs
                value_class = iteration_value
                signature = work_signature(progress, now=started)
                if verification.get("passed"):
                    verdict = iteration_value
                    if iteration_value == "productive":
                        stop_reason = (
                            "fixed evaluator accepted measurable evidence progress"
                        )
                    elif iteration_value == "maintenance":
                        stop_reason = (
                            "artifact freshness was restored without accepted evidence progress"
                        )
                    else:
                        stop_reason = (
                            "cycle was safe and fresh but produced no accepted progress"
                        )
                    break
                if fingerprint == last_fingerprint:
                    verdict = "stopped-no-progress"
                    stop_reason = (
                        "two consecutive failed iterations produced identical state"
                    )
                    break
                last_fingerprint = fingerprint

    decision = (final_artifacts.get("authority") or {}).get("decision") or {}
    all_command_results = list(precheck_commands)
    for iteration in iterations:
        all_command_results.extend(iteration.get("commands") or [])
    duration_seconds = round(time.monotonic() - monotonic_started, 3)
    return {
        "generatedAt": (now or local_now()).isoformat(),
        "startedAt": started.isoformat(),
        "stage": GOAL_LOOP_STAGE,
        "verdict": verdict,
        "valueClass": value_class,
        "stopReason": stop_reason,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "goal": "Complete a fresh paper-evidence cycle while preserving process and authority gates.",
        "maxIterations": max(1, max_iterations),
        "timeoutSecondsPerCommand": timeout_seconds,
        "duplicateCooldownMinutes": max(0, duplicate_cooldown_minutes),
        "durationSeconds": duration_seconds,
        "commandDurationSeconds": _command_duration(all_command_results),
        "commandsExecuted": len(all_command_results),
        "precheckCommands": precheck_commands,
        "precheck": precheck,
        "iterations": iterations,
        "iterationCount": len(iterations),
        "verification": final_verification,
        "baselineProgress": baseline_progress,
        "progress": final_progress,
        "progressDelta": delta,
        "artifactRepairs": repairs,
        "workSignature": signature,
        "authorityLevel": decision.get("authorityLevel"),
        "nextAction": (
            "Continue the scheduled evidence cadence."
            if verdict == "productive"
            else (
                "Wait for new market eligibility or evidence state before repeating."
                if verdict in {"maintenance", "no-op", "skipped-duplicate-work"}
                else "Inspect verifier errors; the loop stopped without widening authority."
            )
        ),
    }


def goal_loop_text(payload: dict[str, Any]) -> str:
    """Render the latest loop outcome as an operator-readable memo."""
    verification = payload.get("verification") or {}
    progress = payload.get("progress") or {}
    delta = payload.get("progressDelta") or {}
    lines = [
        "Inferno Evidence Goal Loop",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Value class: {payload.get('valueClass')}",
        f"Stop reason: {payload.get('stopReason')}",
        f"Iterations: {payload.get('iterationCount')} / {payload.get('maxIterations')}",
        f"Duration: {payload.get('durationSeconds', 0)}s",
        f"Commands executed: {payload.get('commandsExecuted', 0)}",
        f"Authority: {payload.get('authorityLevel')}",
        "Authority contract: research-only; broker submit OFF; live trading OFF",
        "",
        "Progress:",
        f"- scored paper tickets: {progress.get('scoredPaperTickets')}",
        f"- remaining for promotion: {progress.get('remainingForPromotion')}",
        f"- paper loop: {progress.get('paperLoopVerdict')}",
        f"- fast paper: {progress.get('fastPaperVerdict')}",
        f"- fast-paper closed lifetime: {progress.get('fastPaperClosedLifetime')}",
        f"- scenario observations closed: {progress.get('scenarioObservationsClosed')}",
        f"- dominant blocker: {progress.get('dominantBlocker')} ({progress.get('dominantBlockerCount')})",
        f"- strategy lab: {progress.get('strategyLabVerdict')}",
        "",
        "Fixed-evaluator delta:",
        f"- promotion evidence: +{delta.get('promotionEvidenceDelta', 0)}",
        f"- fast-paper closures: +{delta.get('fastPaperClosedDelta', 0)}",
        f"- scenario closures: +{delta.get('scenarioObservationsClosedDelta', 0)}",
        f"- blocker reduction: {delta.get('dominantBlockerReduction', 0)}",
        f"- accepted progress points: {delta.get('acceptedProgressPoints', 0)}",
        "",
        "Verifier:",
        f"- passed: {verification.get('passed')}",
        f"- authority intact: {verification.get('authorityIntact')}",
        f"- paper entry gate open: {verification.get('paperEntryGateOpen')}",
    ]
    errors = verification.get("errors") or []
    lines.append("- errors:")
    lines.extend(f"  - {error}" for error in errors)
    if not errors:
        lines.append("  - none")
    lines.extend(["", f"Next action: {payload.get('nextAction')}"])
    return "\n".join(lines).rstrip() + "\n"


def _run_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "generatedAt": payload.get("generatedAt"),
        "verdict": payload.get("verdict"),
        "valueClass": payload.get("valueClass"),
        "stopReason": payload.get("stopReason"),
        "iterationCount": payload.get("iterationCount"),
        "durationSeconds": payload.get("durationSeconds"),
        "commandDurationSeconds": payload.get("commandDurationSeconds"),
        "commandsExecuted": payload.get("commandsExecuted"),
        "progress": payload.get("progress"),
        "progressDelta": payload.get("progressDelta"),
        "artifactRepairs": payload.get("artifactRepairs"),
        "workSignature": payload.get("workSignature"),
        "verificationPassed": (payload.get("verification") or {}).get("passed"),
    }


def _update_state(
    payload: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a bounded run summary so future cycles retain compact state."""
    prior = existing if existing is not None else load_json_file(GOAL_LOOP_STATE_FILE) or {}
    runs = list(prior.get("runs") or [])
    runs.append(_run_summary(payload))
    runs = runs[-MAX_STATE_RUNS:]
    classified_runs = [
        run
        for run in runs
        if run.get("valueClass")
        in {"productive", "maintenance", "no-op", "skipped", "verification", "blocked"}
    ]
    rolling = classified_runs[-10:]
    productive_runs = sum(
        1 for run in rolling if run.get("valueClass") == "productive"
    )
    consecutive_no_progress = 0
    for run in reversed(runs):
        if run.get("valueClass") in {"no-op", "maintenance", "skipped"}:
            consecutive_no_progress += 1
        else:
            break
    dominant = (payload.get("progress") or {}).get("dominantBlocker")
    repeated_blocker_runs = 0
    if dominant:
        for run in reversed(runs):
            if (run.get("progress") or {}).get("dominantBlocker") == dominant:
                repeated_blocker_runs += 1
            else:
                break
    return {
        "version": 2,
        "updatedAt": payload.get("generatedAt"),
        "lastVerdict": payload.get("verdict"),
        "lastValueClass": payload.get("valueClass"),
        "lastStopReason": payload.get("stopReason"),
        "rolling10": {
            "runs": len(rolling),
            "productiveRuns": productive_runs,
            "productiveRunRate": round(productive_runs / len(rolling), 4)
            if rolling
            else 0.0,
            "consecutiveNoProgressRuns": consecutive_no_progress,
        },
        "repeatedBlocker": {
            "name": dominant,
            "consecutiveRuns": repeated_blocker_runs,
        },
        "runs": runs,
    }


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def _knowledge_run_text(payload: dict[str, Any], state: dict[str, Any]) -> str:
    progress = payload.get("progress") or {}
    delta = payload.get("progressDelta") or {}
    rolling = state.get("rolling10") or {}
    frontmatter = {
        "type": "agent-loop-run",
        "generated": payload.get("generatedAt"),
        "verdict": payload.get("verdict"),
        "value_class": payload.get("valueClass"),
        "verification_passed": (payload.get("verification") or {}).get("passed"),
        "accepted_progress_points": delta.get("acceptedProgressPoints", 0),
        "promotion_evidence_delta": delta.get("promotionEvidenceDelta", 0),
        "duration_seconds": payload.get("durationSeconds", 0),
        "commands_executed": payload.get("commandsExecuted", 0),
        "dominant_blocker": progress.get("dominantBlocker"),
        "remaining_for_promotion": progress.get("remainingForPromotion"),
        "research_only": True,
        "live_trading_allowed": False,
    }
    lines = ["---"]
    lines.extend(f"{key}: {_yaml_scalar(value)}" for key, value in frontmatter.items())
    lines.extend(
        [
            "tags:",
            "  - inferno",
            "  - agent-loop",
            "  - research-only",
            "---",
            "",
            f"# Agent loop run — {payload.get('generatedAt')}",
            "",
            "Links: [[Loop Optimization Principles]] · [[Evidence Bottleneck]] · [[Authority Boundary]]",
            "",
            "## Outcome",
            "",
            f"- Verdict: **{payload.get('verdict')}**",
            f"- Value class: **{payload.get('valueClass')}**",
            f"- Stop reason: {payload.get('stopReason')}",
            f"- Accepted progress points: {delta.get('acceptedProgressPoints', 0)}",
            f"- Rolling productive-run rate: {rolling.get('productiveRunRate', 0):.0%}",
            "",
            "## Evidence delta",
            "",
            f"- Promotion evidence: +{delta.get('promotionEvidenceDelta', 0)}",
            f"- Fast-paper closures: +{delta.get('fastPaperClosedDelta', 0)}",
            f"- Scenario closures: +{delta.get('scenarioObservationsClosedDelta', 0)}",
            f"- Dominant blocker reduction: {delta.get('dominantBlockerReduction', 0)}",
            "",
            "## Current state",
            "",
            f"- Scored paper outcomes: {progress.get('scoredPaperTickets')}",
            f"- Remaining for promotion: {progress.get('remainingForPromotion')}",
            f"- Fast-paper open / closed: {progress.get('fastPaperOpen')} / {progress.get('fastPaperClosedLifetime')}",
            f"- Scenario observations open / closed: {progress.get('scenarioObservationsOpen')} / {progress.get('scenarioObservationsClosed')}",
            f"- Dominant blocker: {progress.get('dominantBlocker')} ({progress.get('dominantBlockerCount')})",
            f"- Next fast-paper exit eligibility: {progress.get('nextFastPaperExitEligibleDate')}",
            "",
            "## Cost trace",
            "",
            f"- Total duration: {payload.get('durationSeconds', 0)} seconds",
            f"- Command duration: {payload.get('commandDurationSeconds', 0)} seconds",
            f"- Commands executed: {payload.get('commandsExecuted', 0)}",
            "",
            "Authority remained paper-evidence-only. Live trading and broker submission remained disabled.",
            "",
        ]
    )
    return "\n".join(lines)


def _lesson_guidance(blocker: str) -> str:
    guidance = {
        "approval-missing": (
            "Do not route around human approval. Concentrate unattended work on "
            "fast-paper and scenario evidence, and keep operator decisions on `./today.sh`."
        ),
        "size-cap-violation": (
            "Reject oversize structures before expensive downstream evaluation and "
            "prefer bounded-risk alternatives that fit existing policy."
        ),
        "wide-spread": (
            "Treat liquidity as an early candidate gate; avoid repeatedly pricing "
            "contracts that cannot satisfy the spread threshold."
        ),
        "reward-risk-floor": (
            "Move reward/risk screening earlier so invalid structures do not consume "
            "the rest of the evaluation loop."
        ),
    }
    return guidance.get(
        blocker,
        "Keep this blocker explicit in the evaluator and only change the loop when a tested intervention reduces its measured count.",
    )


def _save_knowledge(payload: dict[str, Any], state: dict[str, Any]) -> None:
    KNOWLEDGE_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    KNOWLEDGE_LESSONS_DIR.mkdir(parents=True, exist_ok=True)
    generated = str(payload.get("generatedAt") or "unknown")
    slug = re.sub(r"[^0-9A-Za-z._-]+", "-", generated).strip("-")
    run_text = _knowledge_run_text(payload, state)
    atomic_write_text(KNOWLEDGE_RUNS_DIR / f"{slug}.md", run_text)
    atomic_write_text(KNOWLEDGE_CURRENT_FILE, run_text)

    repeated = state.get("repeatedBlocker") or {}
    blocker = str(repeated.get("name") or "")
    count = int(_number(repeated.get("consecutiveRuns")))
    if blocker and count >= 2:
        lesson = "\n".join(
            [
                "---",
                "type: agent-loop-lesson",
                f"blocker: {_yaml_scalar(blocker)}",
                f"consecutive_runs: {count}",
                f"updated: {_yaml_scalar(payload.get('generatedAt'))}",
                "status: active",
                "tags:",
                "  - inferno",
                "  - agent-loop",
                "  - lesson",
                "---",
                "",
                f"# Repeated blocker — {blocker}",
                "",
                "Links: [[Current Loop State]] · [[Evidence Bottleneck]] · [[Loop Optimization Principles]]",
                "",
                f"Observed as the dominant blocker for **{count} consecutive runs**.",
                "",
                "## Durable guidance",
                "",
                _lesson_guidance(blocker),
                "",
                "This note is generated from deterministic run state. It is not authority to change risk policy or submit orders.",
                "",
            ]
        )
        atomic_write_text(KNOWLEDGE_LESSONS_DIR / f"{blocker}.md", lesson)


def save_goal_loop(payload: dict[str, Any]) -> None:
    """Persist the loop result, bounded state, and text report."""
    ensure_dirs()
    existing_state = load_json_file(GOAL_LOOP_STATE_FILE) or {}
    state = _update_state(payload, existing=existing_state)
    atomic_write_json(GOAL_LOOP_FILE, payload)
    atomic_write_json(GOAL_LOOP_STATE_FILE, state)
    atomic_write_text(GOAL_LOOP_TEXT_FILE, goal_loop_text(payload))
    _save_knowledge(payload, state)


def build_verification_only() -> dict[str, Any]:
    """Run the verifier without triggering any evidence mutation."""
    started = local_now()
    artifacts = load_artifacts()
    verification = verify_cycle(artifacts, [], now=started)
    decision = (artifacts.get("authority") or {}).get("decision") or {}
    progress = progress_snapshot(artifacts, now=started)
    delta = progress_delta(progress, progress)
    return {
        "generatedAt": local_now().isoformat(),
        "startedAt": started.isoformat(),
        "stage": GOAL_LOOP_STAGE,
        "verdict": "verify-clean" if verification.get("passed") else "verify-blocked",
        "valueClass": "verification" if verification.get("passed") else "blocked",
        "stopReason": "verification-only command",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "goal": "Verify the existing paper-evidence state without running actions.",
        "maxIterations": 0,
        "timeoutSecondsPerCommand": 0,
        "duplicateCooldownMinutes": 0,
        "durationSeconds": 0.0,
        "commandDurationSeconds": 0.0,
        "commandsExecuted": 0,
        "precheckCommands": [],
        "precheck": verify_precheck(artifacts),
        "iterations": [],
        "iterationCount": 0,
        "verification": verification,
        "baselineProgress": progress,
        "progress": progress,
        "progressDelta": delta,
        "artifactRepairs": [],
        "workSignature": work_signature(progress, now=started),
        "authorityLevel": decision.get("authorityLevel"),
        "nextAction": (
            "Existing loop state is clean."
            if verification.get("passed")
            else "Inspect verifier errors; no actions were run."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the bounded Inferno paper-evidence goal loop."
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "verify", "status"],
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=DEFAULT_MAX_ITERATIONS,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--duplicate-cooldown-minutes",
        type=int,
        default=DEFAULT_DUPLICATE_COOLDOWN_MINUTES,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        if GOAL_LOOP_TEXT_FILE.exists():
            print(GOAL_LOOP_TEXT_FILE.read_text(encoding="utf-8"), end="")
            return 0
        print("(no cached evidence goal-loop report)")
        return 1

    if args.command == "verify":
        payload = build_verification_only()
    else:
        payload = build_goal_loop(
            max_iterations=max(1, args.max_iterations),
            timeout_seconds=max(1, args.timeout_seconds),
            duplicate_cooldown_minutes=max(0, args.duplicate_cooldown_minutes),
        )
    save_goal_loop(payload)
    # Refresh after saving so the command center reads this run, not the prior
    # goal-loop artifact. This is reporting-only and cannot change the verdict.
    run_command(
        "command center refresh",
        ("python3", "inferno_model_command_center.py", "build"),
        timeout_seconds=max(1, args.timeout_seconds),
    )
    print(goal_loop_text(payload), end="")
    healthy_verdicts = {
        "productive",
        "maintenance",
        "no-op",
        "skipped-duplicate-work",
        "verify-clean",
    }
    return 0 if payload.get("verdict") in healthy_verdicts else 2


if __name__ == "__main__":
    raise SystemExit(main())
