from __future__ import annotations

"""Inferno Regime Drift — two-sided CUSUM change-point detection.

What it does:
    Detect when a strategy's R-unit stream has *changed* — either decayed
    or improved — relative to its own baseline. Operates per strategy and
    reports the first index at which the cumulative sum of deviations
    crosses an alarm threshold.

    This is the silent-killer detector. A strategy with mean R = +0.3 over
    its full sample might be at +0.6 in the first half and 0.0 in the
    second half. The mean-CI tests don't catch that; CUSUM does.

What it does NOT do:
    - Trade. Modify authority. Touch the paper ledger.

Strict contract: research-only, diagnostic-only, never promotable.

## The math

Standard Page (1954) CUSUM control chart, two-sided, applied to each
strategy's chronologically-ordered R-unit stream ``x_1, ..., x_n``.

The baseline ``μ̂`` and standard deviation ``σ̂`` come from the *first
half* of the stream (rounded down). This is the canonical "in-control"
baseline; the second half is the period under test.

For each ``t`` in the stream, accumulate two CUSUMs:

```
S⁺_t = max( 0 , S⁺_{t-1} + (x_t - μ̂ - k·σ̂) )       (upward shift)
S⁻_t = min( 0 , S⁻_{t-1} + (x_t - μ̂ + k·σ̂) )       (downward shift)
```

with ``S⁺_0 = S⁻_0 = 0``. The allowance ``k`` is half a standard
deviation (default 0.5) — the minimum shift we care to detect.

An alarm fires when ``|S| > h·σ̂``. Default alarm threshold ``h = 5``
(typical for industrial control charts). Lower ``h`` is more sensitive;
higher ``h`` is more conservative.

We report:

- ``alarmIndexPositive`` — first ``t`` at which ``S⁺_t > h·σ̂``, or ``None``
- ``alarmIndexNegative`` — first ``t`` at which ``-S⁻_t > h·σ̂``, or ``None``
- ``halfSplitIndex`` — boundary between baseline half and tested half

Verdict ladder (per strategy):

| Condition                                       | Verdict          |
|-------------------------------------------------|------------------|
| ``n < MIN_DRIFT_SAMPLES``                       | insufficient     |
| both alarms None                                | stable           |
| positive alarm in tested half                   | improving        |
| negative alarm in tested half                   | decaying         |
| both alarms in tested half                      | unstable         |
| alarm in baseline half (data already non-iid)   | baseline-noisy   |

CLI::

    python3 inferno_regime_drift.py             # run + persist
    python3 inferno_regime_drift.py status      # show last memo

References:
    Page, E. S. (1954), *Continuous Inspection Schemes*, Biometrika 41(1).
"""

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any, Callable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_theme_synthesizer import _r_units
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


REGIME_DRIFT_FILE = DATA_DIR / "inferno_regime_drift.json"
REGIME_DRIFT_TEXT_FILE = REPORTS_DIR / "regime_drift_latest.txt"
REGIME_DRIFT_STAGE = "regime-drift-research-only"

MIN_DRIFT_SAMPLES = int(os.environ.get("INFERNO_DRIFT_MIN_SAMPLES", "12"))
CUSUM_ALLOWANCE_K = float(os.environ.get("INFERNO_DRIFT_K", "0.5"))
CUSUM_ALARM_H = float(os.environ.get("INFERNO_DRIFT_H", "5.0"))


# ---------------------------------------------------------------------------
# Pure math.
# ---------------------------------------------------------------------------


def baseline_stats(samples: list[float], half_index: int) -> tuple[float, float]:
    """Return ``(mean, std)`` over ``samples[:half_index]``.

    Uses ddof=1 (unbiased). For ``half_index < 2`` the standard deviation
    defaults to 1.0 so downstream CUSUM doesn't divide by zero. This is
    a deliberately conservative choice — it makes the alarm threshold
    higher in absolute terms when the baseline is thin, biasing toward
    *not* firing a false alarm.
    """
    if half_index <= 0:
        return 0.0, 1.0
    baseline = samples[:half_index]
    n = len(baseline)
    if n == 0:
        return 0.0, 1.0
    mean = sum(baseline) / n
    if n < 2:
        return float(mean), 1.0
    variance = sum((value - mean) ** 2 for value in baseline) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 1.0
    return float(mean), float(std)


def cusum_traces(
    samples: list[float],
    *,
    mean: float,
    std: float,
    allowance: float = CUSUM_ALLOWANCE_K,
) -> tuple[list[float], list[float]]:
    """Return the running ``(S⁺, S⁻)`` series for the full stream."""
    s_pos = [0.0]
    s_neg = [0.0]
    k_sigma = allowance * std
    for value in samples:
        s_pos.append(max(0.0, s_pos[-1] + (value - mean - k_sigma)))
        s_neg.append(min(0.0, s_neg[-1] + (value - mean + k_sigma)))
    # Drop the leading zero so positions in the trace match positions in
    # the input stream.
    return s_pos[1:], s_neg[1:]


def first_alarm_index(
    trace: list[float],
    *,
    threshold: float,
    direction: str,
) -> int | None:
    """Return first index where the trace crosses ``±threshold``."""
    if direction == "positive":
        for i, value in enumerate(trace):
            if value > threshold:
                return i
        return None
    if direction == "negative":
        for i, value in enumerate(trace):
            if -value > threshold:
                return i
        return None
    raise ValueError(f"unknown direction: {direction}")


def classify_drift(
    *,
    sample_size: int,
    half_index: int,
    alarm_pos: int | None,
    alarm_neg: int | None,
) -> str:
    if sample_size < MIN_DRIFT_SAMPLES:
        return "insufficient"
    if alarm_pos is None and alarm_neg is None:
        return "stable"
    # If either alarm fires in the baseline half, the data isn't stationary
    # to begin with. Flag it specially.
    if (alarm_pos is not None and alarm_pos < half_index) or (
        alarm_neg is not None and alarm_neg < half_index
    ):
        return "baseline-noisy"
    if alarm_pos is not None and alarm_neg is not None:
        return "unstable"
    if alarm_pos is not None:
        return "improving"
    return "decaying"


# ---------------------------------------------------------------------------
# Loader (replaceable in tests).
# ---------------------------------------------------------------------------


def _default_shadow_loader() -> list[dict[str, Any]]:
    path = DATA_DIR / "inferno_shadow_evidence.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows: list[Any] = []
    if isinstance(payload, dict):
        rows = payload.get("records") or payload.get("entries") or payload.get("rows") or []
    elif isinstance(payload, list):
        rows = payload
    return [r for r in rows if isinstance(r, dict)]


def chronologically_ordered_samples_by_strategy(
    records: list[dict[str, Any]],
) -> dict[str, list[float]]:
    """Per-strategy R-unit lists, ordered by the record's ``closedAt`` /
    ``settledAt`` / ``timestamp`` (whichever is present)."""
    by_strategy: dict[str, list[tuple[Any, float]]] = {}
    for record in records:
        outcome = record.get("outcome") or {}
        status = str(outcome.get("status") or record.get("outcomeStatus") or "").lower()
        if status != "closed":
            continue
        r = _r_units(record)
        if r is None:
            r = _r_units(outcome)
        if r is None:
            continue
        ts = (
            outcome.get("closedAt")
            or outcome.get("settledAt")
            or record.get("closedAt")
            or record.get("timestamp")
            or record.get("createdAt")
        )
        # If timestamp is missing, keep the insertion order via the list
        # length as a stable tiebreaker.
        strategy = str(record.get("strategy") or "Unknown")
        by_strategy.setdefault(strategy, []).append((ts or "", float(r)))
    out: dict[str, list[float]] = {}
    for strategy, pairs in by_strategy.items():
        pairs.sort(key=lambda p: str(p[0]))
        out[strategy] = [r for _, r in pairs]
    return out


# ---------------------------------------------------------------------------
# Pure builder.
# ---------------------------------------------------------------------------


def build_regime_drift(
    *,
    shadow_loader: Callable[[], list[dict[str, Any]]] | None = None,
    allowance: float = CUSUM_ALLOWANCE_K,
    alarm_h: float = CUSUM_ALARM_H,
) -> dict[str, Any]:
    """Run CUSUM drift detection on every strategy."""
    records = (shadow_loader or _default_shadow_loader)()
    streams = chronologically_ordered_samples_by_strategy(records)

    rows: list[dict[str, Any]] = []
    for strategy, samples in streams.items():
        n = len(samples)
        half_index = n // 2
        mean, std = baseline_stats(samples, half_index)
        s_pos, s_neg = cusum_traces(samples, mean=mean, std=std, allowance=allowance)
        threshold = alarm_h * std
        alarm_pos = first_alarm_index(s_pos, threshold=threshold, direction="positive")
        alarm_neg = first_alarm_index(s_neg, threshold=threshold, direction="negative")
        verdict = classify_drift(
            sample_size=n,
            half_index=half_index,
            alarm_pos=alarm_pos,
            alarm_neg=alarm_neg,
        )
        rows.append({
            "strategy": strategy,
            "sampleSize": n,
            "halfSplitIndex": half_index,
            "baselineMean": round(mean, 4),
            "baselineStd": round(std, 4),
            "alarmThreshold": round(threshold, 4),
            "alarmIndexPositive": alarm_pos,
            "alarmIndexNegative": alarm_neg,
            "maxPositiveCusum": round(max(s_pos) if s_pos else 0.0, 4),
            "maxNegativeCusum": round(min(s_neg) if s_neg else 0.0, 4),
            "verdict": verdict,
        })

    rows.sort(
        key=lambda r: (
            # Decaying first (operator most needs to see), then unstable, then improving, then stable
            {"decaying": 0, "unstable": 1, "improving": 2, "baseline-noisy": 3, "stable": 4, "insufficient": 5}.get(r["verdict"], 6),
            -r["sampleSize"], r["strategy"],
        )
    )

    decaying = [r for r in rows if r["verdict"] == "decaying"]
    unstable = [r for r in rows if r["verdict"] == "unstable"]
    improving = [r for r in rows if r["verdict"] == "improving"]
    stable = [r for r in rows if r["verdict"] == "stable"]
    baseline_noisy = [r for r in rows if r["verdict"] == "baseline-noisy"]
    insufficient = [r for r in rows if r["verdict"] == "insufficient"]

    if not rows:
        verdict = "no-evidence"
        narrative = "No closed shadow records — drift cannot be assessed."
    elif decaying:
        verdict = "decay-detected"
        names = ", ".join(r["strategy"] for r in decaying[:3])
        narrative = (
            f"{len(decaying)} strategy/strategies are decaying: {names}. "
            "Authority must hold; investigate before any promotion."
        )
    elif unstable:
        verdict = "instability"
        narrative = (
            f"{len(unstable)} strategy/strategies have both up- and down-alarms — "
            "behaviour is unstable across the stream."
        )
    elif improving and not stable:
        verdict = "improving"
        narrative = (
            f"{len(improving)} strategy/strategies show upward shifts — but no stable "
            "baseline for context. Treat carefully."
        )
    elif stable:
        verdict = "stable-with-changes"
        narrative = (
            f"{len(stable)} stable; {len(improving)} improving; {len(baseline_noisy)} "
            "baseline-noisy. No decay detected."
        ) if (improving or baseline_noisy) else (
            f"{len(stable)} strategy/strategies stable — no drift detected at h={alarm_h}σ̂."
        )
    else:
        verdict = "no-conclusive-state"
        narrative = (
            f"Mixed states across {len(rows)} strategy/strategies; see per-strategy table."
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": REGIME_DRIFT_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "method": "two-sided-cusum",
        "allowanceK": allowance,
        "alarmH": alarm_h,
        "minSamples": MIN_DRIFT_SAMPLES,
        "strategyCount": len(rows),
        "decayingCount": len(decaying),
        "unstableCount": len(unstable),
        "improvingCount": len(improving),
        "stableCount": len(stable),
        "baselineNoisyCount": len(baseline_noisy),
        "insufficientCount": len(insufficient),
        "rows": rows,
        "reminders": [
            "CUSUM uses the first half of each stream as the in-control baseline",
            "decay verdict outranks everything — investigate before any promotion",
            "h=5σ̂ is conservative; lower h for more sensitive detection",
        ],
    }


def drift_text(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Regime Drift (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Method: {payload.get('method')}  k={payload.get('allowanceK')}σ̂  h={payload.get('alarmH')}σ̂",
        f"Verdict: {payload.get('verdict')}",
        f"Strategies: {payload.get('strategyCount')}  "
        f"decaying={payload.get('decayingCount')}  "
        f"unstable={payload.get('unstableCount')}  "
        f"improving={payload.get('improvingCount')}  "
        f"stable={payload.get('stableCount')}  "
        f"baseline-noisy={payload.get('baselineNoisyCount')}  "
        f"insufficient={payload.get('insufficientCount')}",
        "",
        f"Narrative: {payload.get('narrative')}",
    ]
    rows = payload.get("rows") or []
    if rows:
        lines.extend(["", "Per-strategy CUSUM:"])
        lines.append(
            f"{'Strategy':<22} {'N':>4} {'half':>5} {'μ̂':>7} {'σ̂':>6} "
            f"{'S⁺_max':>7} {'S⁻_max':>7} {'alarm+':>7} {'alarm-':>7} {'Verdict'}"
        )
        for row in rows:
            ap = row.get("alarmIndexPositive")
            an = row.get("alarmIndexNegative")
            lines.append(
                f"{str(row['strategy'])[:22]:<22} "
                f"{row['sampleSize']:>4} "
                f"{row['halfSplitIndex']:>5} "
                f"{row['baselineMean']:>+7.3f} "
                f"{row['baselineStd']:>6.3f} "
                f"{row['maxPositiveCusum']:>7.3f} "
                f"{row['maxNegativeCusum']:>7.3f} "
                f"{str(ap) if ap is not None else '-':>7} "
                f"{str(an) if an is not None else '-':>7} "
                f"{row['verdict']}"
            )
    lines.extend(["", "Thresholds:"])
    lines.append(f"- minSamples:  n >= {payload.get('minSamples')}")
    lines.append(f"- allowance:   k = {payload.get('allowanceK')} σ̂")
    lines.append(f"- alarm:       h = {payload.get('alarmH')} σ̂")
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_regime_drift(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(REGIME_DRIFT_FILE, payload)
    atomic_write_text(REGIME_DRIFT_TEXT_FILE, drift_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Two-sided CUSUM drift detection on every strategy's R-unit stream. "
            "Research-only; never promotable."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and REGIME_DRIFT_TEXT_FILE.exists():
        print(REGIME_DRIFT_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_regime_drift()
    save_regime_drift(payload)
    print(drift_text(payload))
    if payload.get("verdict") == "decay-detected":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
