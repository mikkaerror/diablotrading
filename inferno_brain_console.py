from __future__ import annotations

"""Inferno Brain Console — a single screen for watching the brain operate.

The desk now produces sixteen artifacts in ``reports/`` and ``data/``. Each
one is individually readable, but no single view tells the operator "here is
the brain right now, ranked by what matters." This module is that view.

The console is a **pure read** of existing artifacts:

- ``data/inferno_daily_loop.json``        — overall verdict + narrative
- ``data/inferno_approval_cadence.json``  — decide-today queue
- ``data/inferno_hypothesis_lab.json``    — top hypotheses
- ``data/inferno_hypothesis_ledger.json`` — trajectory counts
- ``data/inferno_theme_synthesizer.json`` — edge / anti-edge counts
- ``data/inferno_heartbeat.json``         — subsystem liveness
- ``data/inferno_tos_export_stability.json`` — TOS stability verdict
- ``data/inferno_skills_audit.json``      — silent / stale skills
- ``data/inferno_authority_manifest.json``— authority posture (if present)
- ``data/inferno_daily_success.json``     — scorecard

Strict contract:
- the console *never writes desk state*; the only thing it may write is
  ``reports/brain_console_latest.txt`` if --save is passed.
- when an artifact is missing or stale, the corresponding row says so
  rather than crashing.
- the same JSON shape that prints to stdout in ``--json`` mode is what
  downstream tools (e.g. an eventual HTML dashboard) should consume.

CLI:
- ``python3 inferno_brain_console.py``           — print the screen once
- ``python3 inferno_brain_console.py --watch``   — re-print every N seconds
- ``python3 inferno_brain_console.py --json``    — emit structured JSON
- ``python3 inferno_brain_console.py --save``    — also write the text
                                                   memo to reports/
"""

import argparse
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


BRAIN_CONSOLE_TEXT_FILE = REPORTS_DIR / "brain_console_latest.txt"
BRAIN_CONSOLE_STAGE = "brain-console-observation-only"

# Artifacts the console pulls from. Centralising the list lets us add new
# brain layers without touching the renderer.
ARTIFACT_PATHS: dict[str, Path] = {
    "dailyLoop": DATA_DIR / "inferno_daily_loop.json",
    "approvalCadence": DATA_DIR / "inferno_approval_cadence.json",
    "hypothesisLab": DATA_DIR / "inferno_hypothesis_lab.json",
    "hypothesisLedger": DATA_DIR / "inferno_hypothesis_ledger.json",
    "themeSynthesizer": DATA_DIR / "inferno_theme_synthesizer.json",
    "devilsAdvocate": DATA_DIR / "inferno_devils_advocate.json",
    "evidenceStrength": DATA_DIR / "inferno_evidence_strength.json",
    "kellySizing": DATA_DIR / "inferno_kelly_sizing.json",
    "volPremium": DATA_DIR / "inferno_vol_premium.json",
    "bayesianWinrate": DATA_DIR / "inferno_bayesian_winrate.json",
    "regimeDrift": DATA_DIR / "inferno_regime_drift.json",
    "informationGain": DATA_DIR / "inferno_information_gain.json",
    "walkForward": DATA_DIR / "inferno_walk_forward.json",
    "factorRegression": DATA_DIR / "inferno_factor_regression.json",
    "mathVerify": DATA_DIR / "inferno_math_verify.json",
    "heartbeat": DATA_DIR / "inferno_heartbeat.json",
    "tosStability": DATA_DIR / "inferno_tos_export_stability.json",
    "tosChain": DATA_DIR / "inferno_tos_export_chain.json",
    "nightPrep": DATA_DIR / "inferno_night_prep.json",
    "skillsAudit": DATA_DIR / "inferno_skills_audit.json",
    "dailySuccess": DATA_DIR / "inferno_daily_success.json",
    "authority": DATA_DIR / "inferno_authority_manifest.json",
}

# An artifact older than this is flagged stale. The default daily-loop cycle
# is twice per day, so 14h is comfortable for high-frequency writers. Some
# artifacts are written rarely on purpose (e.g. the authority manifest only
# refreshes when authority changes); those are excluded from staleness via
# LOW_FREQUENCY_ARTIFACTS below.
ARTIFACT_STALE_HOURS = 14.0

# Artifacts that legitimately go quiet for long stretches. We still note
# whether they exist, but we don't ring the staleness bell every day.
LOW_FREQUENCY_ARTIFACTS: frozenset[str] = frozenset({"authority", "nightPrep"})


def _read_json(path: Path) -> dict[str, Any] | None:
    """Return parsed JSON or ``None`` if the file is missing / unreadable."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _artifact_age_hours(path: Path, now: datetime) -> float | None:
    """Return artifact age in hours, or ``None`` when the file is missing."""
    if not path.exists():
        return None
    try:
        mtime_seconds = path.stat().st_mtime
    except OSError:
        return None
    mtime = datetime.fromtimestamp(mtime_seconds, tz=now.tzinfo)
    if mtime.tzinfo and not now.tzinfo:
        mtime = mtime.replace(tzinfo=None)
    elif now.tzinfo and not mtime.tzinfo:
        mtime = mtime.replace(tzinfo=now.tzinfo)
    delta = now - mtime
    return delta.total_seconds() / 3600.0


def _read_all_artifacts(now: datetime) -> dict[str, dict[str, Any]]:
    """Return ``{name: {"payload": ..., "ageHours": ..., "stale": bool}}``."""
    snapshot: dict[str, dict[str, Any]] = {}
    for name, path in ARTIFACT_PATHS.items():
        age = _artifact_age_hours(path, now)
        # Low-frequency artifacts never get the stale flag; they're expected
        # to sit untouched for days at a time.
        is_low_frequency = name in LOW_FREQUENCY_ARTIFACTS
        is_stale = (
            age is not None
            and age > ARTIFACT_STALE_HOURS
            and not is_low_frequency
        )
        snapshot[name] = {
            "payload": _read_json(path),
            "ageHours": round(age, 2) if age is not None else None,
            "stale": is_stale,
            "missing": age is None,
            "lowFrequency": is_low_frequency,
            "path": str(path),
        }
    return snapshot


def _safe_get(payload: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    """Defensive dotted-get over a possibly-None artifact dict."""
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current is not None else default


def build_console_state(now: datetime | None = None) -> dict[str, Any]:
    """Assemble the structured snapshot the console renders.

    The same structure is what ``--json`` emits, so downstream tools can
    consume it without re-parsing the printable view.
    """
    now = now or local_now()
    snapshot = _read_all_artifacts(now)

    daily_loop = snapshot["dailyLoop"]["payload"] or {}
    cadence = snapshot["approvalCadence"]["payload"] or {}
    hypothesis = snapshot["hypothesisLab"]["payload"] or {}
    ledger = snapshot["hypothesisLedger"]["payload"] or {}
    theme = snapshot["themeSynthesizer"]["payload"] or {}
    devils_advocate = snapshot["devilsAdvocate"]["payload"] or {}
    evidence_strength = snapshot["evidenceStrength"]["payload"] or {}
    kelly_sizing = snapshot["kellySizing"]["payload"] or {}
    vol_premium = snapshot["volPremium"]["payload"] or {}
    bayesian = snapshot["bayesianWinrate"]["payload"] or {}
    drift_payload = snapshot["regimeDrift"]["payload"] or {}
    info_gain = snapshot["informationGain"]["payload"] or {}
    walk_forward = snapshot["walkForward"]["payload"] or {}
    factor_regression = snapshot["factorRegression"]["payload"] or {}
    math_verify = snapshot["mathVerify"]["payload"] or {}
    heartbeat = snapshot["heartbeat"]["payload"] or {}
    stability = snapshot["tosStability"]["payload"] or {}
    chain_payload = snapshot["tosChain"]["payload"] or {}
    night_prep_payload = snapshot["nightPrep"]["payload"] or {}
    skills = snapshot["skillsAudit"]["payload"] or {}
    success = snapshot["dailySuccess"]["payload"] or {}
    # Authority manifest nests the live fields under `decision`; we accept
    # both the nested shape (production) and the flat shape (older tests).
    authority_payload = snapshot["authority"]["payload"] or {}
    authority = authority_payload.get("decision") or authority_payload

    decide_today_tickers = list(daily_loop.get("decideTodayTickers") or [])
    desk_verdict = (daily_loop.get("deskVerdict") or success.get("verdict") or "unknown")

    top_hypotheses_raw = hypothesis.get("topHypotheses") or []
    top_hypotheses = []
    for h in top_hypotheses_raw[:5]:
        stats = h.get("stats") or {}
        top_hypotheses.append({
            "id": h.get("id"),
            "template": h.get("template"),
            "claim": h.get("claim"),
            "testConfidence": h.get("testConfidence"),
            "winRate": stats.get("winRate"),
            "winRateLower": stats.get("winRateLower"),
            "sampleSize": stats.get("sampleSize"),
            "suggestedAction": h.get("suggestedAction"),
        })

    return {
        "generatedAt": now.isoformat(),
        "stage": BRAIN_CONSOLE_STAGE,
        "diagnosticOnly": True,
        "deskVerdict": desk_verdict,
        "authority": {
            # The production manifest names this field ``authorityLevel``;
            # accept both for backward compatibility with older fixtures.
            "level": authority.get("authorityLevel") or authority.get("level") or "unknown",
            "brokerSubmitAllowed": authority.get("brokerSubmitAllowed"),
            "liveTradingAllowed": authority.get("liveTradingAllowed"),
        },
        "decideToday": decide_today_tickers,
        "cadenceCounts": cadence.get("counts") or {},
        "narrative": daily_loop.get("narrative"),
        "topHypotheses": top_hypotheses,
        "hypothesisCounts": {
            "total": hypothesis.get("totalHypotheses", 0),
            "edges": hypothesis.get("edgeCount", 0),
            "antiEdges": hypothesis.get("antiEdgeCount", 0),
        },
        "ledgerTrajectory": ledger.get("trajectoryCounts") or {},
        "themeCells": {
            "total": theme.get("totalCells", 0),
            "sufficient": theme.get("sufficientCells", 0),
            "edges": len(theme.get("edges") or []),
            "antiEdges": len(theme.get("antiEdges") or []),
        },
        "falsification": {
            "verdict": devils_advocate.get("verdict"),
            "edgesHolding": devils_advocate.get("edgesHolding"),
            "edgesWeak": devils_advocate.get("edgesWeak"),
            "edgesFalsified": devils_advocate.get("edgesFalsified"),
            "strategyCount": devils_advocate.get("strategyCount"),
        },
        "evidenceStrength": {
            "verdict": evidence_strength.get("verdict"),
            "strength": evidence_strength.get("strength"),
            "weakestComponent": evidence_strength.get("weakestComponent"),
            "weakestValue": evidence_strength.get("weakestValue"),
            "totalSamples": evidence_strength.get("totalSamples"),
        },
        "kellySizing": {
            "verdict": kelly_sizing.get("verdict"),
            "sized": kelly_sizing.get("sizedCount"),
            "capLimited": kelly_sizing.get("capLimitedCount"),
            "marginal": kelly_sizing.get("marginalCount"),
            "totalRiskUnits": kelly_sizing.get("totalRecommendedRiskUnits"),
            "ceilingBinding": kelly_sizing.get("ceilingBinding"),
        },
        "volPremium": {
            "verdict": vol_premium.get("verdict"),
            "real": vol_premium.get("realCount"),
            "uncertain": vol_premium.get("uncertainCount"),
            "absent": vol_premium.get("absentCount"),
            "totalClosed": vol_premium.get("totalClosed"),
        },
        "bayesianWinrate": {
            "verdict": bayesian.get("verdict"),
            "strong": bayesian.get("strongCount"),
            "likely": bayesian.get("likelyCount"),
            "uncertain": bayesian.get("uncertainCount"),
            "rejected": bayesian.get("rejectedCount"),
        },
        "regimeDrift": {
            "verdict": drift_payload.get("verdict"),
            "decaying": drift_payload.get("decayingCount"),
            "unstable": drift_payload.get("unstableCount"),
            "stable": drift_payload.get("stableCount"),
            "improving": drift_payload.get("improvingCount"),
        },
        "informationGain": {
            "verdict": info_gain.get("verdict"),
            "strong": info_gain.get("strongCount"),
            "meaningful": info_gain.get("meaningfulCount"),
            "totalClosed": info_gain.get("totalClosed"),
            "topFeature": (info_gain.get("rows") or [{}])[0].get("feature"),
            "topNMI": (info_gain.get("rows") or [{}])[0].get("normalisedMI"),
        },
        "walkForward": {
            "verdict": walk_forward.get("verdict"),
            "survives": walk_forward.get("survivesCount"),
            "decays": walk_forward.get("decaysCount"),
            "reverses": walk_forward.get("reversesCount"),
            "strategyCount": walk_forward.get("strategyCount"),
        },
        "factorRegression": {
            "verdict": factor_regression.get("verdict"),
            "positive": factor_regression.get("positiveEdgeCount"),
            "negative": factor_regression.get("negativeEdgeCount"),
            "featureCount": factor_regression.get("featureCount"),
            "sampleSize": factor_regression.get("sampleSize"),
        },
        "mathVerify": {
            "verdict": math_verify.get("verdict"),
            "totalViolations": math_verify.get("totalViolations"),
            "missingArtifacts": math_verify.get("missingArtifacts"),
            "moduleCount": math_verify.get("moduleCount"),
        },
        "breathing": {
            "heartbeatVerdict": heartbeat.get("verdict"),
            "heartbeatFresh": heartbeat.get("freshCount"),
            "heartbeatTotal": heartbeat.get("totalSources"),
            "heartbeatMissingExpected": list(heartbeat.get("missingExpected") or []),
            "tosVerdict": stability.get("verdict"),
            "tosDominantFailMode": stability.get("dominantFailMode"),
            "tosChainVerdict": chain_payload.get("verdict"),
            "tosChainFirstFailure": chain_payload.get("firstFailure"),
            "skillsVerdict": skills.get("verdict"),
            "skillsCounts": skills.get("counts") or {},
            "nightPrepVerdict": night_prep_payload.get("verdict"),
            "nightPrepReadyForMorning": night_prep_payload.get("readyForMorning"),
        },
        "scorecard": {
            "verdict": success.get("verdict"),
            "passCount": success.get("passCount"),
            "totalCount": success.get("totalCount"),
        },
        "artifactFreshness": {
            name: {
                "missing": meta.get("missing"),
                "stale": meta.get("stale"),
                "ageHours": meta.get("ageHours"),
                "lowFrequency": meta.get("lowFrequency", False),
            }
            for name, meta in snapshot.items()
        },
        "reminders": [
            "observation-only; this module never mutates state",
            "rerun the daily loop to refresh underlying artifacts",
            "missing/stale flags indicate the corresponding diagnostic has not run today",
        ],
    }


def _format_authority(state: dict[str, Any]) -> str:
    authority = state.get("authority") or {}
    level = authority.get("level") or "unknown"
    broker = authority.get("brokerSubmitAllowed")
    live = authority.get("liveTradingAllowed")
    return f"{level} | brokerSubmit={broker} | liveTrading={live}"


def _format_decide(state: dict[str, Any]) -> str:
    tickers = state.get("decideToday") or []
    if not tickers:
        return "none (queue empty or no urgent names)"
    return ", ".join(tickers)


def _format_trajectory(state: dict[str, Any]) -> str:
    counts = state.get("ledgerTrajectory") or {}
    if not counts:
        return "no ledger data yet"
    keys = ("strengthening", "weakening", "stable", "new", "abandoned")
    return " | ".join(f"{key} {counts.get(key, 0)}" for key in keys)


def _format_breathing(state: dict[str, Any]) -> str:
    breathing = state.get("breathing") or {}
    parts: list[str] = []
    if breathing.get("heartbeatVerdict") is not None:
        parts.append(
            f"heartbeat {breathing.get('heartbeatVerdict')} "
            f"{breathing.get('heartbeatFresh', 0)}/{breathing.get('heartbeatTotal', 0)}"
        )
    if breathing.get("tosVerdict") is not None:
        chain_verdict = breathing.get("tosChainVerdict")
        first_failure = breathing.get("tosChainFirstFailure")
        tos_summary = f"TOS {breathing.get('tosVerdict')}"
        if chain_verdict:
            tos_summary += f" (chain: {chain_verdict}"
            if first_failure:
                tos_summary += f", break: {first_failure}"
            tos_summary += ")"
        parts.append(tos_summary)
    if breathing.get("skillsVerdict") is not None:
        counts = breathing.get("skillsCounts") or {}
        parts.append(
            f"skills {breathing.get('skillsVerdict')} "
            f"{counts.get('fresh', 0)}/{counts.get('fresh', 0) + counts.get('stale', 0) + counts.get('silent', 0)}"
        )
    if breathing.get("nightPrepVerdict") is not None:
        ready = breathing.get("nightPrepReadyForMorning")
        parts.append(
            f"night-prep {breathing.get('nightPrepVerdict')} "
            f"(ready={ready})"
        )
    return " | ".join(parts) if parts else "no breathing data yet"


def render_console(state: dict[str, Any]) -> str:
    """Render the structured state into the operator-facing screen."""
    lines: list[str] = []
    lines.append("INFERNO BRAIN CONSOLE".ljust(53) + state.get("generatedAt", ""))
    lines.append("=" * 73)
    lines.append(f"Desk verdict      : {(state.get('deskVerdict') or 'unknown').upper()}")
    scorecard = state.get("scorecard") or {}
    if scorecard.get("passCount") is not None and scorecard.get("totalCount") is not None:
        lines[-1] += f"  ({scorecard.get('passCount')}/{scorecard.get('totalCount')} scorecard criteria)"
    lines.append(f"Authority         : {_format_authority(state)}")
    lines.append(f"Decide today      : {_format_decide(state)}")
    cadence_counts = state.get("cadenceCounts") or {}
    if cadence_counts:
        lines.append(
            "Cadence queue     : "
            f"pending {cadence_counts.get('pending', 0)} | "
            f"approved {cadence_counts.get('approved', 0)} | "
            f"rejected {cadence_counts.get('rejected', 0)} | "
            f"decided-today {cadence_counts.get('decidedToday', 0)}"
        )

    lines.append("")
    lines.append(
        "TOP HYPOTHESES    "
        f"(total {(state.get('hypothesisCounts') or {}).get('total', 0)}, "
        f"edges {(state.get('hypothesisCounts') or {}).get('edges', 0)} | "
        f"anti-edges {(state.get('hypothesisCounts') or {}).get('antiEdges', 0)})"
    )
    top = state.get("topHypotheses") or []
    if not top:
        lines.append("  none yet — theme cube is still warming up")
    for hypothesis in top:
        lines.append(
            f"  {hypothesis.get('testConfidence', 0):.2f} "
            f"[{(hypothesis.get('template') or '')[:18]:<18}] "
            f"WR {hypothesis.get('winRate')} (lower {hypothesis.get('winRateLower')}) "
            f"N={hypothesis.get('sampleSize')}"
        )
        claim = hypothesis.get("claim") or ""
        if claim:
            lines.append(f"      {claim[:96]}")

    lines.append("")
    lines.append(f"LEDGER TRAJECTORY {_format_trajectory(state)}")
    theme_cells = state.get("themeCells") or {}
    lines.append(
        f"THEME CUBE        cells {theme_cells.get('total', 0)} | "
        f"sufficient {theme_cells.get('sufficient', 0)} | "
        f"edges {theme_cells.get('edges', 0)} | "
        f"anti-edges {theme_cells.get('antiEdges', 0)}"
    )
    falsification = state.get("falsification") or {}
    if falsification.get("verdict"):
        lines.append(
            f"FALSIFICATION     {falsification.get('verdict')} | "
            f"holds {falsification.get('edgesHolding', 0)} | "
            f"weak {falsification.get('edgesWeak', 0)} | "
            f"falsified {falsification.get('edgesFalsified', 0)} "
            f"(of {falsification.get('strategyCount', 0)})"
        )
    evidence = state.get("evidenceStrength") or {}
    if evidence.get("verdict"):
        weakest = evidence.get("weakestComponent")
        weakest_val = evidence.get("weakestValue")
        weakest_str = (
            f" | weakest: {weakest} ({weakest_val:.2f})"
            if weakest and isinstance(weakest_val, (int, float))
            else ""
        )
        lines.append(
            f"EVIDENCE STRENGTH {evidence.get('verdict')} | "
            f"score {evidence.get('strength', 0.0):.2f} | "
            f"N={evidence.get('totalSamples', 0)}{weakest_str}"
        )
    vrp = state.get("volPremium") or {}
    if vrp.get("verdict"):
        lines.append(
            f"VOL PREMIUM       {vrp.get('verdict')} | "
            f"real {vrp.get('real', 0)} | "
            f"uncertain {vrp.get('uncertain', 0)} | "
            f"absent {vrp.get('absent', 0)} "
            f"(of {vrp.get('totalClosed', 0)} closed)"
        )
    kelly = state.get("kellySizing") or {}
    if kelly.get("verdict"):
        total_units = kelly.get('totalRiskUnits') or 0.0
        ceiling_flag = " [CEILING BINDING]" if kelly.get("ceilingBinding") else ""
        lines.append(
            f"KELLY SIZING      {kelly.get('verdict')} | "
            f"sized {kelly.get('sized', 0)} | "
            f"cap-limited {kelly.get('capLimited', 0)} | "
            f"total {total_units:.2f}R{ceiling_flag}"
        )
    bayes = state.get("bayesianWinrate") or {}
    if bayes.get("verdict"):
        lines.append(
            f"BAYESIAN P(edge)  {bayes.get('verdict')} | "
            f"strong {bayes.get('strong', 0)} | "
            f"likely {bayes.get('likely', 0)} | "
            f"rejected {bayes.get('rejected', 0)}"
        )
    drift_state = state.get("regimeDrift") or {}
    if drift_state.get("verdict"):
        decay_flag = " [DECAY ALERT]" if (drift_state.get("decaying") or 0) > 0 else ""
        lines.append(
            f"REGIME DRIFT      {drift_state.get('verdict')} | "
            f"decaying {drift_state.get('decaying', 0)} | "
            f"unstable {drift_state.get('unstable', 0)} | "
            f"stable {drift_state.get('stable', 0)}{decay_flag}"
        )
    info = state.get("informationGain") or {}
    if info.get("verdict"):
        top = info.get("topFeature")
        nmi = info.get("topNMI")
        top_str = (
            f" | top: {top} (NMI {nmi:.2f})"
            if top and isinstance(nmi, (int, float))
            else ""
        )
        lines.append(
            f"INFORMATION GAIN  {info.get('verdict')} | "
            f"strong {info.get('strong', 0)} | "
            f"meaningful {info.get('meaningful', 0)}{top_str}"
        )
    wf_state = state.get("walkForward") or {}
    if wf_state.get("verdict"):
        reversal_flag = " [REVERSAL]" if (wf_state.get("reverses") or 0) > 0 else ""
        lines.append(
            f"WALK-FORWARD      {wf_state.get('verdict')} | "
            f"survives {wf_state.get('survives', 0)} | "
            f"decays {wf_state.get('decays', 0)} | "
            f"reverses {wf_state.get('reverses', 0)}{reversal_flag}"
        )
    fr_state = state.get("factorRegression") or {}
    if fr_state.get("verdict"):
        lines.append(
            f"FACTOR REGRESSION {fr_state.get('verdict')} | "
            f"+features {fr_state.get('positive', 0)} | "
            f"−features {fr_state.get('negative', 0)} | "
            f"N={fr_state.get('sampleSize', 0)} "
            f"({fr_state.get('featureCount', 0)} cols)"
        )
    mv_state = state.get("mathVerify") or {}
    if mv_state.get("verdict"):
        violation_flag = " [VIOLATIONS]" if (mv_state.get("totalViolations") or 0) > 0 else ""
        lines.append(
            f"MATH VERIFY       {mv_state.get('verdict')} | "
            f"modules {mv_state.get('moduleCount', 0)} | "
            f"violations {mv_state.get('totalViolations', 0)} | "
            f"missing {mv_state.get('missingArtifacts', 0)}{violation_flag}"
        )
    lines.append(f"BREATHING         {_format_breathing(state)}")

    narrative = state.get("narrative")
    if narrative:
        lines.append("")
        lines.append("LATEST NARRATIVE")
        for line in narrative.split("\n"):
            lines.append(f"  {line}")

    artifact_freshness = state.get("artifactFreshness") or {}
    stale_or_missing = [
        name for name, meta in artifact_freshness.items()
        if meta.get("stale") or meta.get("missing")
    ]
    if stale_or_missing:
        lines.append("")
        lines.append("STALE OR MISSING  " + ", ".join(stale_or_missing))

    lines.append("=" * 73)
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    """CLI: print the console once, watch it, emit JSON, or save the text."""
    parser = argparse.ArgumentParser(
        description=(
            "Render a single readable view of the brain's current state. "
            "Read-only; never mutates desk state."
        )
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of the text screen")
    parser.add_argument("--watch", action="store_true", help="Re-render every --interval seconds")
    parser.add_argument("--interval", type=float, default=30.0, help="Watch interval in seconds")
    parser.add_argument("--save", action="store_true", help="Also write the text view to reports/")
    return parser.parse_args()


def _render_once(args: argparse.Namespace) -> None:
    state = build_console_state()
    if args.json:
        print(json.dumps(state, indent=2))
    else:
        text = render_console(state)
        print(text)
        if args.save:
            ensure_dirs()
            atomic_write_text(BRAIN_CONSOLE_TEXT_FILE, text)


def main() -> int:
    args = parse_args()
    if not args.watch:
        _render_once(args)
        return 0
    try:
        while True:
            # Clear screen between renders so --watch feels like a live view.
            os.system("clear" if os.name != "nt" else "cls")
            _render_once(args)
            time.sleep(max(1.0, args.interval))
    except KeyboardInterrupt:
        print("\n(brain console stopped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
