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
from datetime import datetime, timedelta
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
PAPER_DIRECTOR_FILE = DATA_DIR / "inferno_paper_test_director.json"
PAPER_BLOCKER_SWARM_FILE = DATA_DIR / "inferno_paper_blocker_swarm.json"
FAST_PAPER_FILE = DATA_DIR / "inferno_fast_paper_cohort.json"
PERFORMANCE_FILE = DATA_DIR / "inferno_performance_analytics.json"
STRATEGY_LAB_FILE = DATA_DIR / "inferno_strategy_lab.json"
PAPER_VELOCITY_FILE = DATA_DIR / "inferno_paper_velocity.json"
SCENARIO_EVIDENCE_FILE = DATA_DIR / "inferno_scenario_evidence.json"
UNIVERSE_CAP_FIT_FILE = DATA_DIR / "inferno_universe_cap_fit.json"

KNOWLEDGE_DIR = ROOT / "knowledge" / "agent-loop"
KNOWLEDGE_RUNS_DIR = KNOWLEDGE_DIR / "runs"
KNOWLEDGE_LESSONS_DIR = KNOWLEDGE_DIR / "lessons"
KNOWLEDGE_CURRENT_FILE = KNOWLEDGE_DIR / "Current Loop State.md"
KNOWLEDGE_BELIEFS_FILE = KNOWLEDGE_DIR / "Loop Beliefs.md"

SAFE_AUTHORITY_LEVELS = {"paper-evidence-only"}
MAX_STATE_RUNS = 30
DEFAULT_MAX_ITERATIONS = 2
DEFAULT_TIMEOUT_SECONDS = 600
DEFAULT_DUPLICATE_COOLDOWN_MINUTES = 60
MAX_ADAPTIVE_INTERVAL_MINUTES = 24 * 60

PRECHECK_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("process compliance precheck", ("python3", "inferno_process_compliance.py", "build")),
    ("authority precheck", ("python3", "inferno_authority_controller.py", "build")),
)

CYCLE_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("paper evidence harvest", ("./run_inferno_paper_evidence_harvest.sh",)),
    ("performance analytics", ("python3", "inferno_performance_analytics.py", "build")),
    ("strategy lab", ("python3", "inferno_strategy_lab.py", "build")),
    ("paper velocity", ("python3", "inferno_paper_velocity.py", "run")),
    ("universe cap-fit audit", ("python3", "inferno_universe_cap_fit.py", "run")),
    ("paper test director", ("python3", "inferno_paper_test_director.py", "build")),
    ("paper blocker swarm", ("python3", "inferno_paper_blocker_swarm.py", "run")),
    ("process compliance verification", ("python3", "inferno_process_compliance.py", "build")),
    ("authority verification", ("python3", "inferno_authority_controller.py", "build")),
)

ARTIFACT_PATHS: dict[str, Path] = {
    "authority": AUTHORITY_FILE,
    "processCompliance": PROCESS_FILE,
    "paperEvidenceLoop": PAPER_LOOP_FILE,
    "paperDirector": PAPER_DIRECTOR_FILE,
    "paperBlockerSwarm": PAPER_BLOCKER_SWARM_FILE,
    "fastPaper": FAST_PAPER_FILE,
    "performance": PERFORMANCE_FILE,
    "strategyLab": STRATEGY_LAB_FILE,
    "paperVelocity": PAPER_VELOCITY_FILE,
    "scenarioEvidence": SCENARIO_EVIDENCE_FILE,
    "universeCapFit": UNIVERSE_CAP_FIT_FILE,
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

    paper_swarm = artifacts.get("paperBlockerSwarm") or {}
    if paper_swarm:
        if paper_swarm.get("researchOnly") is not True:
            errors.append("paper-blocker-swarm artifact lost researchOnly=true")
        if paper_swarm.get("promotable") is not False:
            errors.append("paper-blocker-swarm artifact lost promotable=false")
        if paper_swarm.get("liveTradingAllowed") is not False:
            errors.append("paper-blocker-swarm artifact lost liveTradingAllowed=false")
        if paper_swarm.get("brokerSubmitAllowed") is not False:
            errors.append("paper-blocker-swarm artifact lost brokerSubmitAllowed=false")
        if _number((paper_swarm.get("rewards") or {}).get("outcomeReward")) != 0:
            errors.append("paper-blocker-swarm outcomeReward must remain zero")

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
    paper_director = artifacts.get("paperDirector") or {}
    paper_blocker_swarm = artifacts.get("paperBlockerSwarm") or {}
    fast_paper = artifacts.get("fastPaper") or {}
    strategy_lab = artifacts.get("strategyLab") or {}
    velocity = artifacts.get("paperVelocity") or {}
    scenario_evidence = artifacts.get("scenarioEvidence") or {}
    universe_cap_fit = artifacts.get("universeCapFit") or {}
    paper_director_counts = paper_director.get("counts") or {}
    paper_swarm_counts = paper_blocker_swarm.get("counts") or {}
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
        "paperDirectorVerdict": paper_director.get("verdict"),
        "paperStageableNow": int(_number(paper_director_counts.get("stageableNow"))),
        "paperAutoSelected": int(_number(paper_director_counts.get("autoPaperSelected"))),
        "paperApprovalOnly": int(_number(paper_director_counts.get("approvalOnly"))),
        "paperHardBlocked": int(_number(paper_director_counts.get("hardBlocked"))),
        "paperBlockerSwarmVerdict": paper_blocker_swarm.get("verdict"),
        "paperBlockerSwarmDominantLane": paper_blocker_swarm.get("dominantLane"),
        "paperBlockerSwarmFixableByTooling": int(
            _number(paper_swarm_counts.get("fixableByTooling"))
        ),
        "paperBlockerSwarmMarketDataBlocked": int(
            _number(paper_swarm_counts.get("marketDataBlocked"))
        ),
        "paperBlockerSwarmFallbacks": int(
            _number(paper_swarm_counts.get("strategyFallbackSuggested"))
        ),
        "paperBlockerSwarmOutcomeReward": _number(
            (paper_blocker_swarm.get("rewards") or {}).get("outcomeReward")
        ),
        "verifiedPaperCandidates": int(_number(paper_director_counts.get("stageableNow")))
        + int(_number(paper_director_counts.get("autoPaperSelected")))
        + int(_number(paper_director_counts.get("approvalOnly"))),
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
        "capFitVerdict": universe_cap_fit.get("verdict"),
        "capFitAnyFits": int(_number((universe_cap_fit.get("counts") or {}).get("anyFits"))),
        "capFitTotal": int(_number((universe_cap_fit.get("counts") or {}).get("total"))),
        "capFitRate": universe_cap_fit.get("fitRate"),
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
    verified_candidate_delta = max(
        0,
        int(_number(after.get("verifiedPaperCandidates")))
        - int(_number(before.get("verifiedPaperCandidates"))),
    )
    paper_hard_blocked_reduction = max(
        0,
        int(_number(before.get("paperHardBlocked")))
        - int(_number(after.get("paperHardBlocked"))),
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
        + verified_candidate_delta * 50
        + min(paper_hard_blocked_reduction, 10)
        + min(blocker_reduction, 10)
    )
    return {
        "scoredPaperTicketsDelta": scored_delta,
        "remainingForPromotionReduction": remaining_reduction,
        "promotionEvidenceDelta": promotion_evidence_delta,
        "fastPaperClosedDelta": fast_closed_delta,
        "scenarioObservationsClosedDelta": scenario_closed_delta,
        "verifiedPaperCandidateDelta": verified_candidate_delta,
        "paperHardBlockedReduction": paper_hard_blocked_reduction,
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
        "paperDirectorVerdict": snapshot.get("paperDirectorVerdict"),
        "verifiedPaperCandidates": snapshot.get("verifiedPaperCandidates"),
        "paperHardBlocked": snapshot.get("paperHardBlocked"),
        "paperBlockerSwarmVerdict": snapshot.get("paperBlockerSwarmVerdict"),
        "paperBlockerSwarmDominantLane": snapshot.get("paperBlockerSwarmDominantLane"),
        "paperBlockerSwarmFixableByTooling": snapshot.get(
            "paperBlockerSwarmFixableByTooling"
        ),
        "paperBlockerSwarmMarketDataBlocked": snapshot.get(
            "paperBlockerSwarmMarketDataBlocked"
        ),
        "paperBlockerSwarmFallbacks": snapshot.get("paperBlockerSwarmFallbacks"),
        "eligibleFastPaperExits": snapshot.get("eligibleFastPaperExits"),
        "nextFastPaperExitEligibleDate": snapshot.get("nextFastPaperExitEligibleDate"),
        "scenarioObservationsClosed": snapshot.get("scenarioObservationsClosed"),
        "scenarioObservationsOpen": snapshot.get("scenarioObservationsOpen"),
        "capFitAnyFits": snapshot.get("capFitAnyFits"),
        "capFitTotal": snapshot.get("capFitTotal"),
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


def _parse_datetime(value: Any, *, fallback_tz: Any = None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    if parsed.tzinfo is None and fallback_tz is not None:
        parsed = parsed.replace(tzinfo=fallback_tz)
    return parsed


def _matching_verified_run(
    state: dict[str, Any],
    *,
    signature: str,
) -> dict[str, Any] | None:
    runs = state.get("runs") or []
    if not runs:
        return None
    last = runs[-1]
    if last.get("workSignature") != signature:
        return None
    if last.get("verificationPassed") is not True:
        return None
    return last


def _cadence_gate(
    state: dict[str, Any],
    *,
    signature: str,
    now: datetime,
    fallback_cooldown_minutes: int,
) -> dict[str, Any]:
    if fallback_cooldown_minutes <= 0:
        return {"blocked": False, "reason": None, "nextCheckAt": None}
    last = _matching_verified_run(state, signature=signature)
    if not last:
        return {"blocked": False, "reason": None, "nextCheckAt": None}

    cadence = state.get("cadence") or {}
    next_check = _parse_datetime(cadence.get("nextCheckAt"), fallback_tz=now.tzinfo)
    if next_check and now < next_check:
        return {
            "blocked": True,
            "reason": "adaptive cadence has not reached its next check",
            "nextCheckAt": next_check.isoformat(),
        }

    generated = _parse_datetime(last.get("generatedAt"), fallback_tz=now.tzinfo)
    if not generated:
        return {"blocked": False, "reason": None, "nextCheckAt": None}
    age_seconds = (now - generated).total_seconds()
    fallback_next = generated + timedelta(minutes=fallback_cooldown_minutes)
    if 0 <= age_seconds < fallback_cooldown_minutes * 60:
        return {
            "blocked": True,
            "reason": "meaningful state is unchanged inside the fallback cooldown",
            "nextCheckAt": fallback_next.isoformat(),
        }
    return {"blocked": False, "reason": None, "nextCheckAt": None}


def _prior_no_progress_streak(state: dict[str, Any]) -> int:
    streak = 0
    for run in reversed(state.get("runs") or []):
        if run.get("valueClass") in {"no-op", "maintenance", "skipped"}:
            streak += 1
        else:
            break
    return streak


def adaptive_cadence(
    prior_state: dict[str, Any],
    *,
    value_class: str,
    progress: dict[str, Any],
    generated_at: datetime,
    minimum_minutes: int,
    preserve_next_check: str | None = None,
) -> dict[str, Any]:
    """Choose the next useful check using bounded outcome-driven backoff."""
    if preserve_next_check:
        preserved = _parse_datetime(
            preserve_next_check,
            fallback_tz=generated_at.tzinfo,
        )
        if preserved and preserved > generated_at:
            interval = max(
                0,
                round((preserved - generated_at).total_seconds() / 60),
            )
            return {
                "mode": "adaptive",
                "intervalMinutes": interval,
                "nextCheckAt": preserved.isoformat(),
                "reason": "preserved current adaptive gate; skipped checks do not extend it",
                "noProgressStreak": _prior_no_progress_streak(prior_state) + 1,
            }

    prior_streak = _prior_no_progress_streak(prior_state)
    if value_class == "productive":
        interval = max(15, min(minimum_minutes, 60))
        streak = 0
        reason = "progress detected; keep a short follow-up interval"
    elif value_class == "maintenance":
        streak = prior_streak + 1
        interval = max(minimum_minutes, 60)
        reason = "maintenance completed; wait for meaningful state change"
    elif value_class in {"no-op", "skipped"}:
        streak = prior_streak + 1
        base = max(15, minimum_minutes)
        interval = min(
            MAX_ADAPTIVE_INTERVAL_MINUTES,
            base * (2 ** max(0, streak - 1)),
        )
        reason = "no accepted progress; exponentially back off repeated checks"
    elif value_class == "verification":
        streak = prior_streak
        interval = 0
        reason = "verification-only run does not change action cadence"
    else:
        streak = 0
        interval = max(240, minimum_minutes)
        reason = "blocked run; leave time for diagnosis or external state change"

    next_check = generated_at + timedelta(minutes=interval)
    eligible_raw = str(progress.get("nextFastPaperExitEligibleDate") or "")
    try:
        eligible_date = datetime.fromisoformat(eligible_raw).date()
    except ValueError:
        eligible_date = None
    if eligible_date and eligible_date > generated_at.date():
        eligibility_check = generated_at.replace(
            year=eligible_date.year,
            month=eligible_date.month,
            day=eligible_date.day,
            hour=9,
            minute=35,
            second=0,
            microsecond=0,
        )
        if eligibility_check < next_check:
            next_check = eligibility_check
            interval = max(
                0,
                round((next_check - generated_at).total_seconds() / 60),
            )
            reason += "; cap wait at the next known fast-paper eligibility"

    return {
        "mode": "adaptive",
        "intervalMinutes": interval,
        "nextCheckAt": next_check.isoformat(),
        "reason": reason,
        "noProgressStreak": streak,
    }


def _command_duration(results: list[dict[str, Any]]) -> float:
    return round(sum(_number(result.get("durationSeconds")) for result in results), 3)


def automation_governance(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate whether this automation still satisfies its design contract."""
    command_results = list(payload.get("precheckCommands") or [])
    for iteration in payload.get("iterations") or []:
        command_results.extend(iteration.get("commands") or [])
    conditions = {
        "repetitiveTask": True,
        "objectiveVerification": bool(payload.get("verification")),
        "runnableEnvironment": all(
            result.get("ok") is True for result in command_results
        ),
        "boundedResourceUse": (
            int(_number(payload.get("maxIterations"))) >= 0
            and int(_number(payload.get("timeoutSecondsPerCommand"))) >= 0
        ),
        "persistentState": True,
        "humanGateBeforeIrreversibleAction": (
            payload.get("liveTradingAllowed") is False
            and payload.get("brokerSubmitAllowed") is False
        ),
        "costTraceAvailable": payload.get("durationSeconds") is not None,
    }
    return {
        "passed": all(conditions.values()),
        "conditions": conditions,
        "permissionAudit": {
            "checkedThisRun": True,
            "authorityLevel": payload.get("authorityLevel"),
            "liveTradingAllowed": payload.get("liveTradingAllowed"),
            "brokerSubmitAllowed": payload.get("brokerSubmitAllowed"),
        },
        "wealthUrgencyCanChangeAuthority": False,
    }


def loop_economics(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure cost per accepted result without counting cheap skips as work."""
    full_runs = [
        run
        for run in runs
        if run.get("valueClass")
        in {"productive", "maintenance", "no-op", "blocked"}
    ][-10:]
    productive_runs = [
        run for run in full_runs if run.get("valueClass") == "productive"
    ]
    total_seconds = round(
        sum(_number(run.get("durationSeconds")) for run in full_runs),
        3,
    )
    accepted_points = sum(
        int(_number((run.get("progressDelta") or {}).get("acceptedProgressPoints")))
        for run in full_runs
    )
    acceptance_rate = (
        round(len(productive_runs) / len(full_runs), 4) if full_runs else None
    )
    seconds_per_productive_run = (
        round(total_seconds / len(productive_runs), 3)
        if productive_runs
        else None
    )
    seconds_per_accepted_point = (
        round(total_seconds / accepted_points, 3) if accepted_points > 0 else None
    )
    if len(full_runs) < 3:
        verdict = "insufficient-sample"
        recommendation = "Collect at least three evaluated full runs."
    elif acceptance_rate is not None and acceptance_rate >= 0.5:
        verdict = "economically-viable"
        recommendation = "Keep the current cadence and continue measuring."
    else:
        verdict = "inefficient"
        recommendation = (
            "Keep adaptive throttling active; improve eligibility detection or "
            "the evidence process before increasing run frequency."
        )
    return {
        "windowFullRuns": len(full_runs),
        "productiveFullRuns": len(productive_runs),
        "fullRunAcceptanceRate": acceptance_rate,
        "totalFullRunSeconds": total_seconds,
        "acceptedProgressPoints": accepted_points,
        "secondsPerProductiveRun": seconds_per_productive_run,
        "secondsPerAcceptedProgressPoint": seconds_per_accepted_point,
        "targetAcceptanceRate": 0.5,
        "verdict": verdict,
        "recommendation": recommendation,
    }


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
    cadence_gate = {"blocked": False, "reason": None, "nextCheckAt": None}

    if precheck.get("passed"):
        all_fresh = all(
            payload and _artifact_fresh(payload, now=started)
            for payload in precheck_artifacts.values()
        )
        cadence_gate = _cadence_gate(
            prior_state,
            signature=signature,
            now=started,
            fallback_cooldown_minutes=duplicate_cooldown_minutes,
        )
        useful_work_ready = int(
            _number(baseline_progress.get("eligibleFastPaperExits"))
        ) > 0
        if cadence_gate.get("blocked") and all_fresh and not useful_work_ready:
            verdict = "skipped-duplicate-work"
            stop_reason = str(cadence_gate.get("reason"))
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
    generated = now or local_now()
    cadence = adaptive_cadence(
        prior_state,
        value_class=value_class,
        progress=final_progress,
        generated_at=generated,
        minimum_minutes=max(0, duplicate_cooldown_minutes),
        preserve_next_check=(
            str(cadence_gate.get("nextCheckAt") or "")
            if verdict == "skipped-duplicate-work"
            else None
        ),
    )
    payload = {
        "generatedAt": generated.isoformat(),
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
        "cadence": cadence,
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
    payload["governance"] = automation_governance(payload)
    prior_runs = list(prior_state.get("runs") or [])
    payload["economics"] = loop_economics([*prior_runs, _run_summary(payload)])
    return payload


def goal_loop_text(payload: dict[str, Any]) -> str:
    """Render the latest loop outcome as an operator-readable memo."""
    verification = payload.get("verification") or {}
    progress = payload.get("progress") or {}
    delta = payload.get("progressDelta") or {}
    economics = payload.get("economics") or {}
    governance = payload.get("governance") or {}
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
        f"Next adaptive check: {(payload.get('cadence') or {}).get('nextCheckAt')}",
        f"Authority: {payload.get('authorityLevel')}",
        "Authority contract: research-only; broker submit OFF; live trading OFF",
        "",
        "Progress:",
        f"- scored paper tickets: {progress.get('scoredPaperTickets')}",
        f"- remaining for promotion: {progress.get('remainingForPromotion')}",
        f"- paper loop: {progress.get('paperLoopVerdict')}",
        f"- paper director: {progress.get('paperDirectorVerdict')} | "
        f"verified candidates {progress.get('verifiedPaperCandidates')} "
        f"(stageable {progress.get('paperStageableNow')}, "
        f"auto {progress.get('paperAutoSelected')}, "
        f"approval {progress.get('paperApprovalOnly')})",
        f"- paper blocker swarm: {progress.get('paperBlockerSwarmVerdict')} | "
        f"dominant {progress.get('paperBlockerSwarmDominantLane')} | "
        f"tooling-fixable {progress.get('paperBlockerSwarmFixableByTooling')} | "
        f"fallbacks {progress.get('paperBlockerSwarmFallbacks')} | "
        f"outcome reward {progress.get('paperBlockerSwarmOutcomeReward')}",
        f"- fast paper: {progress.get('fastPaperVerdict')}",
        f"- fast-paper closed lifetime: {progress.get('fastPaperClosedLifetime')}",
        f"- scenario observations closed: {progress.get('scenarioObservationsClosed')}",
        f"- universe cap fit: {progress.get('capFitVerdict')} | "
        f"{progress.get('capFitAnyFits')}/{progress.get('capFitTotal')} fit",
        f"- dominant blocker: {progress.get('dominantBlocker')} ({progress.get('dominantBlockerCount')})",
        f"- strategy lab: {progress.get('strategyLabVerdict')}",
        "",
        "Fixed-evaluator delta:",
        f"- promotion evidence: +{delta.get('promotionEvidenceDelta', 0)}",
        f"- verified paper candidates: +{delta.get('verifiedPaperCandidateDelta', 0)}",
        f"- fast-paper closures: +{delta.get('fastPaperClosedDelta', 0)}",
        f"- scenario closures: +{delta.get('scenarioObservationsClosedDelta', 0)}",
        f"- paper hard-blocked reduction: {delta.get('paperHardBlockedReduction', 0)}",
        f"- blocker reduction: {delta.get('dominantBlockerReduction', 0)}",
        f"- accepted progress points: {delta.get('acceptedProgressPoints', 0)}",
        "",
        "Loop economics:",
        f"- governance passed: {governance.get('passed')}",
        f"- full-run acceptance rate: {economics.get('fullRunAcceptanceRate')}",
        f"- cost per accepted progress point: {economics.get('secondsPerAcceptedProgressPoint')}",
        f"- economics verdict: {economics.get('verdict')}",
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
        "cadence": payload.get("cadence"),
        "governance": payload.get("governance"),
        "verificationPassed": (payload.get("verification") or {}).get("passed"),
    }


def consolidate_beliefs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Distill recent traces into compact claims with explicit falsifiers."""
    classified = [
        run
        for run in runs
        if run.get("valueClass")
        in {"productive", "maintenance", "no-op", "skipped", "blocked"}
    ]
    recent = classified[-10:]
    if not recent:
        return []

    promotion_gain = sum(
        int(_number((run.get("progressDelta") or {}).get("promotionEvidenceDelta")))
        for run in recent
    )
    no_progress_runs = sum(
        1
        for run in recent
        if run.get("valueClass") in {"maintenance", "no-op", "skipped"}
    )
    beliefs = [
        {
            "id": "promotion-evidence-velocity",
            "statement": (
                "Promotion evidence is stalled across the recent evaluated run window."
                if promotion_gain == 0
                else "Promotion evidence is moving in the recent evaluated run window."
            ),
            "status": "active" if promotion_gain == 0 else "challenged",
            "evidenceRuns": len(recent),
            "evidenceValue": promotion_gain,
            "falsifier": "A future run records promotionEvidenceDelta greater than zero.",
        },
        {
            "id": "invocation-efficiency",
            "statement": (
                "Most recent invocations produce no accepted progress and should remain adaptively throttled."
                if no_progress_runs * 2 >= len(recent)
                else "Recent invocation cadence is producing accepted progress often enough to avoid stronger backoff."
            ),
            "status": (
                "active" if no_progress_runs * 2 >= len(recent) else "challenged"
            ),
            "evidenceRuns": len(recent),
            "evidenceValue": no_progress_runs,
            "falsifier": "At least half of the next ten evaluated runs are productive.",
        },
    ]
    economics = loop_economics(recent)
    if economics.get("windowFullRuns", 0) >= 3:
        beliefs.append(
            {
                "id": "loop-economics",
                "statement": (
                    "The full evidence loop is below the target accepted-run rate."
                    if economics.get("verdict") == "inefficient"
                    else "The full evidence loop meets the target accepted-run rate."
                ),
                "status": (
                    "active"
                    if economics.get("verdict") == "inefficient"
                    else "supported"
                ),
                "evidenceRuns": economics.get("windowFullRuns"),
                "evidenceValue": economics.get("fullRunAcceptanceRate"),
                "falsifier": (
                    "The rolling full-run acceptance rate reaches at least 50% "
                    "with objective progress deltas."
                ),
            }
        )

    last_progress = recent[-1].get("progress") or {}
    blocker = str(last_progress.get("dominantBlocker") or "")
    blocker_streak = 0
    if blocker:
        for run in reversed(recent):
            if (run.get("progress") or {}).get("dominantBlocker") == blocker:
                blocker_streak += 1
            else:
                break
        beliefs.append(
            {
                "id": "dominant-blocker",
                "statement": f"The dominant measured blocker is {blocker}.",
                "status": "active" if blocker_streak >= 2 else "provisional",
                "evidenceRuns": blocker_streak,
                "evidenceValue": int(
                    _number(last_progress.get("dominantBlockerCount"))
                ),
                "falsifier": (
                    "The dominant blocker changes or its measured count declines "
                    "after a tested intervention."
                ),
            }
        )
    return beliefs


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
    cadence = payload.get("cadence") or prior.get("cadence") or {}
    economics = loop_economics(runs)
    return {
        "version": 6,
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
        "cadence": cadence,
        "governance": payload.get("governance") or {},
        "economics": economics,
        "beliefs": consolidate_beliefs(runs),
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
    cadence = payload.get("cadence") or {}
    economics = state.get("economics") or payload.get("economics") or {}
    governance = payload.get("governance") or {}
    frontmatter = {
        "type": "agent-loop-run",
        "generated": payload.get("generatedAt"),
        "verdict": payload.get("verdict"),
        "value_class": payload.get("valueClass"),
        "verification_passed": (payload.get("verification") or {}).get("passed"),
        "accepted_progress_points": delta.get("acceptedProgressPoints", 0),
        "promotion_evidence_delta": delta.get("promotionEvidenceDelta", 0),
        "verified_paper_candidate_delta": delta.get("verifiedPaperCandidateDelta", 0),
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
            "Links: [[Loop Optimization Principles]] · [[Loop Beliefs]] · [[Wealth Objective Boundary]] · [[Evidence Bottleneck]] · [[Authority Boundary]]",
            "",
            "## Outcome",
            "",
            f"- Verdict: **{payload.get('verdict')}**",
            f"- Value class: **{payload.get('valueClass')}**",
            f"- Stop reason: {payload.get('stopReason')}",
            f"- Accepted progress points: {delta.get('acceptedProgressPoints', 0)}",
            f"- Rolling productive-run rate: {rolling.get('productiveRunRate', 0):.0%}",
            f"- Next adaptive check: {cadence.get('nextCheckAt')}",
            f"- Governance passed: {governance.get('passed')}",
            "",
            "## Evidence delta",
            "",
            f"- Promotion evidence: +{delta.get('promotionEvidenceDelta', 0)}",
            f"- Verified paper candidates: +{delta.get('verifiedPaperCandidateDelta', 0)}",
            f"- Fast-paper closures: +{delta.get('fastPaperClosedDelta', 0)}",
            f"- Scenario closures: +{delta.get('scenarioObservationsClosedDelta', 0)}",
            f"- Paper hard-blocked reduction: {delta.get('paperHardBlockedReduction', 0)}",
            f"- Dominant blocker reduction: {delta.get('dominantBlockerReduction', 0)}",
            "",
            "## Current state",
            "",
            f"- Scored paper outcomes: {progress.get('scoredPaperTickets')}",
            f"- Remaining for promotion: {progress.get('remainingForPromotion')}",
            f"- Paper director: {progress.get('paperDirectorVerdict')} with {progress.get('verifiedPaperCandidates')} verified candidates",
            f"- Paper blocker swarm: {progress.get('paperBlockerSwarmVerdict')} | dominant lane {progress.get('paperBlockerSwarmDominantLane')} | tooling-fixable {progress.get('paperBlockerSwarmFixableByTooling')}",
            f"- Fast-paper open / closed: {progress.get('fastPaperOpen')} / {progress.get('fastPaperClosedLifetime')}",
            f"- Scenario observations open / closed: {progress.get('scenarioObservationsOpen')} / {progress.get('scenarioObservationsClosed')}",
            f"- Universe cap fit: {progress.get('capFitAnyFits')}/{progress.get('capFitTotal')} fit ({progress.get('capFitVerdict')})",
            f"- Dominant blocker: {progress.get('dominantBlocker')} ({progress.get('dominantBlockerCount')})",
            f"- Next fast-paper exit eligibility: {progress.get('nextFastPaperExitEligibleDate')}",
            "",
            "## Cost trace",
            "",
            f"- Total duration: {payload.get('durationSeconds', 0)} seconds",
            f"- Command duration: {payload.get('commandDurationSeconds', 0)} seconds",
            f"- Commands executed: {payload.get('commandsExecuted', 0)}",
            f"- Full-run acceptance rate: {economics.get('fullRunAcceptanceRate')}",
            f"- Seconds per accepted progress point: {economics.get('secondsPerAcceptedProgressPoint')}",
            f"- Economics verdict: {economics.get('verdict')}",
            "",
            "Authority remained paper-evidence-only. Live trading and broker submission remained disabled.",
            "",
        ]
    )
    return "\n".join(lines)


def _beliefs_text(state: dict[str, Any]) -> str:
    beliefs = state.get("beliefs") or []
    lines = [
        "---",
        "type: agent-loop-beliefs",
        f"updated: {_yaml_scalar(state.get('updatedAt'))}",
        f"belief_count: {len(beliefs)}",
        "tags:",
        "  - inferno",
        "  - agent-loop",
        "  - beliefs",
        "---",
        "",
        "# Loop Beliefs",
        "",
        "These claims are deterministically consolidated from recent evaluated runs. Each claim includes a condition that can falsify it.",
        "",
        "Links: [[Current Loop State]] · [[Loop Optimization Principles]] · [[Evidence Bottleneck]]",
        "",
    ]
    for belief in beliefs:
        lines.extend(
            [
                f"## {belief.get('id')}",
                "",
                f"- Status: **{belief.get('status')}**",
                f"- Claim: {belief.get('statement')}",
                f"- Evidence window: {belief.get('evidenceRuns')} run(s)",
                f"- Evidence value: {belief.get('evidenceValue')}",
                f"- Falsifier: {belief.get('falsifier')}",
                "",
            ]
        )
    if not beliefs:
        lines.extend(["No evaluated run history is available yet.", ""])
    lines.append(
        "These beliefs guide research prioritization only. They cannot change authority, risk policy, or broker state."
    )
    lines.append("")
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
    atomic_write_text(KNOWLEDGE_BELIEFS_FILE, _beliefs_text(state))

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
    payload = {
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
    payload["governance"] = automation_governance(payload)
    state = load_json_file(GOAL_LOOP_STATE_FILE) or {}
    payload["economics"] = loop_economics(
        [*(state.get("runs") or []), _run_summary(payload)]
    )
    return payload


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
