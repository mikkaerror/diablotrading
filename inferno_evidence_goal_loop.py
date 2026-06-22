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
import subprocess
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

SAFE_AUTHORITY_LEVELS = {"paper-evidence-only"}
MAX_STATE_RUNS = 30
DEFAULT_MAX_ITERATIONS = 2
DEFAULT_TIMEOUT_SECONDS = 600

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


def progress_snapshot(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Extract the small state vector that determines whether the loop moved."""
    performance = artifacts.get("performance") or {}
    paper_loop = artifacts.get("paperEvidenceLoop") or {}
    fast_paper = artifacts.get("fastPaper") or {}
    strategy_lab = artifacts.get("strategyLab") or {}
    velocity = artifacts.get("paperVelocity") or {}
    return {
        "scoredPaperTickets": int(
            ((performance.get("closedMetrics") or {}).get("scoredCount")) or 0
        ),
        "remainingForPromotion": int(
            ((paper_loop.get("counts") or {}).get("remainingForPromotion")) or 0
        ),
        "paperLoopVerdict": paper_loop.get("verdict"),
        "fastPaperVerdict": fast_paper.get("verdict"),
        "fastPaperCounts": fast_paper.get("counts") or {},
        "strategyLabVerdict": (strategy_lab.get("deskVerdict") or {}).get("level"),
        "weeklyCloseRate": (velocity.get("velocity") or {}).get("weeklyRate30dWindow"),
    }


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


def build_goal_loop(
    *,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    command_runner: Callable[..., dict[str, Any]] = run_command,
    artifact_loader: Callable[[], dict[str, dict[str, Any]]] = load_artifacts,
) -> dict[str, Any]:
    """Run the bounded evidence loop and return its complete audit payload."""
    started = local_now()
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

    if precheck.get("passed"):
        verdict = "stopped-iteration-cap"
        stop_reason = f"reached {max_iterations} iteration(s)"
        for iteration_number in range(1, max(1, max_iterations) + 1):
            results = _run_commands(
                CYCLE_COMMANDS,
                timeout_seconds=timeout_seconds,
                command_runner=command_runner,
            )
            artifacts = artifact_loader()
            verification = verify_cycle(artifacts, results)
            fingerprint = progress_fingerprint(artifacts, verification)
            progress = progress_snapshot(artifacts)
            iterations.append(
                {
                    "iteration": iteration_number,
                    "commands": results,
                    "verification": verification,
                    "progress": progress,
                    "fingerprint": fingerprint,
                }
            )
            final_artifacts = artifacts
            final_verification = verification
            if verification.get("passed"):
                verdict = "cycle-complete"
                stop_reason = "all objective verifier gates passed"
                break
            if fingerprint == last_fingerprint:
                verdict = "stopped-no-progress"
                stop_reason = "two consecutive failed iterations produced identical state"
                break
            last_fingerprint = fingerprint

    decision = (final_artifacts.get("authority") or {}).get("decision") or {}
    return {
        "generatedAt": local_now().isoformat(),
        "startedAt": started.isoformat(),
        "stage": GOAL_LOOP_STAGE,
        "verdict": verdict,
        "stopReason": stop_reason,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "goal": "Complete a fresh paper-evidence cycle while preserving process and authority gates.",
        "maxIterations": max(1, max_iterations),
        "timeoutSecondsPerCommand": timeout_seconds,
        "precheckCommands": precheck_commands,
        "precheck": precheck,
        "iterations": iterations,
        "iterationCount": len(iterations),
        "verification": final_verification,
        "progress": progress_snapshot(final_artifacts),
        "authorityLevel": decision.get("authorityLevel"),
        "nextAction": (
            "Wait for the next scheduled cycle."
            if verdict == "cycle-complete"
            else "Inspect verifier errors; the loop stopped without widening authority."
        ),
    }


def goal_loop_text(payload: dict[str, Any]) -> str:
    """Render the latest loop outcome as an operator-readable memo."""
    verification = payload.get("verification") or {}
    progress = payload.get("progress") or {}
    lines = [
        "Inferno Evidence Goal Loop",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Stop reason: {payload.get('stopReason')}",
        f"Iterations: {payload.get('iterationCount')} / {payload.get('maxIterations')}",
        f"Authority: {payload.get('authorityLevel')}",
        "Authority contract: research-only; broker submit OFF; live trading OFF",
        "",
        "Progress:",
        f"- scored paper tickets: {progress.get('scoredPaperTickets')}",
        f"- remaining for promotion: {progress.get('remainingForPromotion')}",
        f"- paper loop: {progress.get('paperLoopVerdict')}",
        f"- fast paper: {progress.get('fastPaperVerdict')}",
        f"- strategy lab: {progress.get('strategyLabVerdict')}",
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


def _update_state(payload: dict[str, Any]) -> dict[str, Any]:
    """Append a bounded run summary so future cycles retain compact state."""
    existing = load_json_file(GOAL_LOOP_STATE_FILE) or {}
    runs = list(existing.get("runs") or [])
    runs.append(
        {
            "generatedAt": payload.get("generatedAt"),
            "verdict": payload.get("verdict"),
            "stopReason": payload.get("stopReason"),
            "iterationCount": payload.get("iterationCount"),
            "progress": payload.get("progress"),
            "verificationPassed": (payload.get("verification") or {}).get("passed"),
        }
    )
    return {
        "version": 1,
        "updatedAt": payload.get("generatedAt"),
        "lastVerdict": payload.get("verdict"),
        "lastStopReason": payload.get("stopReason"),
        "runs": runs[-MAX_STATE_RUNS:],
    }


def save_goal_loop(payload: dict[str, Any]) -> None:
    """Persist the loop result, bounded state, and text report."""
    ensure_dirs()
    atomic_write_json(GOAL_LOOP_FILE, payload)
    atomic_write_json(GOAL_LOOP_STATE_FILE, _update_state(payload))
    atomic_write_text(GOAL_LOOP_TEXT_FILE, goal_loop_text(payload))


def build_verification_only() -> dict[str, Any]:
    """Run the verifier without triggering any evidence mutation."""
    artifacts = load_artifacts()
    verification = verify_cycle(artifacts, [])
    decision = (artifacts.get("authority") or {}).get("decision") or {}
    return {
        "generatedAt": local_now().isoformat(),
        "startedAt": local_now().isoformat(),
        "stage": GOAL_LOOP_STAGE,
        "verdict": "verify-clean" if verification.get("passed") else "verify-blocked",
        "stopReason": "verification-only command",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "goal": "Verify the existing paper-evidence state without running actions.",
        "maxIterations": 0,
        "timeoutSecondsPerCommand": 0,
        "precheckCommands": [],
        "precheck": verify_precheck(artifacts),
        "iterations": [],
        "iterationCount": 0,
        "verification": verification,
        "progress": progress_snapshot(artifacts),
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
    return 0 if payload.get("verdict") in {"cycle-complete", "verify-clean"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
