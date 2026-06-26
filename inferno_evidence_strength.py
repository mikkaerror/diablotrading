from __future__ import annotations

"""Inferno Evidence Strength — a single scalar for "how much do we know?"

What it does:
    Computes a composite 0.0–1.0 scalar that says how strong the desk's
    accumulated evidence is *right now*. Every component is a transparent
    probability or proportion; the composite is the geometric mean of the
    components (so any single weak component drags the whole score down,
    which is the right asymmetry).

What it does NOT do:
    - Promote a strategy. (The lab still owns that.)
    - Mutate the authority manifest. (The controller still owns that.)
    - Touch any TOS, paper, or broker surface.

Strict contract: research-only, diagnostic-only, never promotable.

## The math

Four components, each scaled to ``[0.0, 1.0]``:

1. **Sample-size strength** ``S_n = min(1.0, n_total / TARGET_SAMPLES)``
   The desk needs at least ``TARGET_SAMPLES`` closed paper outcomes before
   it can claim to know anything statistically. Below that, ``S_n < 1``.

2. **Aggregate Wilson lower bound** ``S_w = max(0, (w_lo - 0.5) / 0.5)``
   Where ``w_lo`` is the Wilson 95% lower bound on the overall paper win
   rate. ``S_w == 1`` only when ``w_lo >= 1.0``, which never happens. A
   ``w_lo`` of 0.5 (coinflip lower bound) maps to ``S_w == 0``.

3. **Expectancy lower bound** ``S_e = clamp((m_lo) / TARGET_EXPECTANCY, 0, 1)``
   Where ``m_lo`` is the bootstrap 95% lower bound on mean R-units.
   Negative or zero expectancy lower bound maps to ``S_e == 0``.

4. **Falsification survival** ``S_f = edges_holding / max(1, strategies_total)``
   The fraction of strategies that survived devil's advocate falsification
   at p<0.05. If devil's advocate hasn't been run yet, this term is
   omitted (geometric mean over the remaining three).

Composite::

    strength = (S_n * S_w * S_e * S_f) ** (1 / k)

Where ``k`` is the number of components in play. The geometric mean is
sensitive to the *worst* component — exactly what we want when deciding
whether to advance authority.

## Verdict ladder

| strength | verdict             |
|---------:|---------------------|
| >= 0.70  | strong              |
| >= 0.40  | moderate            |
| >= 0.20  | weak                |
| < 0.20   | insufficient        |
| n == 0   | no-evidence         |

A "strong" verdict does *not* promote authority. It signals that the
authority controller could *consider* promotion if its other gates also
clear. The controller still has the final word.

CLI::

    python3 inferno_evidence_strength.py            # run + persist
    python3 inferno_evidence_strength.py status     # show last memo
"""

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any, Callable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_theme_synthesizer import (
    _r_units,
    bootstrap_mean_ci,
    wilson_interval,
)
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


EVIDENCE_STRENGTH_FILE = DATA_DIR / "inferno_evidence_strength.json"
EVIDENCE_STRENGTH_TEXT_FILE = REPORTS_DIR / "evidence_strength_latest.txt"
EVIDENCE_STRENGTH_STAGE = "evidence-strength-research-only"

TARGET_SAMPLES = int(os.environ.get("INFERNO_ES_TARGET_SAMPLES", "60"))
TARGET_EXPECTANCY_R = float(os.environ.get("INFERNO_ES_TARGET_EXPECTANCY", "0.40"))
STRONG_STRENGTH = 0.70
MODERATE_STRENGTH = 0.40
WEAK_STRENGTH = 0.20


# ---------------------------------------------------------------------------
# Pure math.
# ---------------------------------------------------------------------------


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def sample_size_strength(n: int, target: int = TARGET_SAMPLES) -> float:
    """``S_n`` — how close to the target sample size are we?"""
    if target <= 0 or n <= 0:
        return 0.0
    return _clamp(n / target)


def empirical_breakeven(samples: list[float]) -> float | None:
    """Breakeven win rate implied by the realized win/loss magnitudes.

    For a payoff of ``avg_win : avg_loss`` (both in R units), a strategy
    breaks even at a hit rate of ``avg_loss / (avg_win + avg_loss)``.

    Why this matters: the desk trades asymmetric structures (long
    straddles, debit spreads) that *win less than half the time by
    design* yet are positive expectancy. Anchoring the win-rate axis at a
    flat 0.5 coinflip silently labels every one of those "no edge". That
    is precisely the kind of assumption that costs the desk real,
    profitable setups. Anchoring at the payoff-implied breakeven removes
    that bias: a symmetric 1:1 payoff still gives 0.5, while a 3:1 winner
    breaks even at 0.25.

    Returns ``None`` when breakeven cannot be derived (the sample has no
    wins or no losses) so the caller falls back to the 0.5 default rather
    than inventing a number from one-sided data.
    """
    wins = [r for r in samples if r > 0]
    losses = [-r for r in samples if r < 0]
    if not wins or not losses:
        return None
    avg_win = sum(wins) / len(wins)
    avg_loss = sum(losses) / len(losses)
    denom = avg_win + avg_loss
    if denom <= 0:
        return None
    return _clamp(avg_loss / denom, 0.0, 0.999)


def wilson_strength(w_lower: float, breakeven: float = 0.5) -> float:
    """``S_w`` — how far above breakeven is the Wilson lower bound?

    Maps ``[breakeven, 1.0]`` to ``[0.0, 1.0]`` linearly; at or below the
    breakeven anchor it returns 0. The anchor defaults to ``0.5`` (the
    classic coinflip, preserved for backward compatibility), but
    ``build_strength`` passes the payoff-implied breakeven from
    :func:`empirical_breakeven` so asymmetric-payoff strategies are not
    penalised for an honest sub-50% hit rate.
    """
    anchor = _clamp(breakeven, 0.0, 0.999)
    if w_lower <= anchor:
        return 0.0
    return _clamp((w_lower - anchor) / (1.0 - anchor))


def expectancy_strength(m_lower: float, target: float = TARGET_EXPECTANCY_R) -> float:
    """``S_e`` — how strong is the bootstrap lower bound on mean R?"""
    if target <= 0 or m_lower <= 0:
        return 0.0
    return _clamp(m_lower / target)


def falsification_strength(edges_holding: int, strategies_total: int) -> float | None:
    """``S_f`` — fraction of strategies surviving devil's advocate.

    Returns ``None`` when there are no strategies (so the composite skips
    this term rather than collapsing to zero from missing data).
    """
    if strategies_total <= 0:
        return None
    return _clamp(edges_holding / strategies_total)


def composite_strength(components: dict[str, float | None]) -> tuple[float, list[str]]:
    """Geometric mean over the active components.

    Returns ``(strength, active_keys)``. Inactive components (``None``) are
    skipped so missing data doesn't masquerade as zero strength.
    """
    active = {k: v for k, v in components.items() if v is not None}
    if not active:
        return 0.0, []
    # Use log-mean to avoid underflow with many small components.
    total = 0.0
    for value in active.values():
        # Guard log(0) — replace with a very small floor.
        total += math.log(max(value, 1e-12))
    strength = math.exp(total / len(active))
    return _clamp(strength), sorted(active.keys())


def classify_verdict(strength: float, total_samples: int) -> str:
    if total_samples <= 0:
        return "no-evidence"
    if strength >= STRONG_STRENGTH:
        return "strong"
    if strength >= MODERATE_STRENGTH:
        return "moderate"
    if strength >= WEAK_STRENGTH:
        return "weak"
    return "insufficient"


# ---------------------------------------------------------------------------
# Loaders (replaceable in tests).
# ---------------------------------------------------------------------------


def _default_shadow_loader() -> list[dict[str, Any]]:
    """Load the shadow records — closed paper outcomes."""
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


def _default_devils_advocate_loader() -> dict[str, Any] | None:
    """Load the latest devil's-advocate payload, if present."""
    path = DATA_DIR / "inferno_devils_advocate.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        return payload
    return None


def aggregate_samples(records: list[dict[str, Any]]) -> tuple[list[float], int, int]:
    """Extract closed-outcome R-unit samples; returns (samples, wins, losses)."""
    samples: list[float] = []
    wins = 0
    losses = 0
    for record in records:
        outcome = (record.get("outcome") or {})
        status = str(outcome.get("status") or record.get("outcomeStatus") or "").lower()
        if status != "closed":
            continue
        r = _r_units(record)
        if r is None:
            r = _r_units(outcome)
        if r is None:
            continue
        samples.append(float(r))
        if r > 0:
            wins += 1
        elif r < 0:
            losses += 1
    return samples, wins, losses


# ---------------------------------------------------------------------------
# Pure builder.
# ---------------------------------------------------------------------------


def build_strength(
    *,
    shadow_loader: Callable[[], list[dict[str, Any]]] | None = None,
    devils_advocate_loader: Callable[[], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Compose the composite evidence strength scalar."""
    records = (shadow_loader or _default_shadow_loader)()
    samples, wins, losses = aggregate_samples(records)
    n_total = len(samples)

    if n_total == 0:
        w_lower, w_upper = 0.0, 1.0
        m_mean, m_lower, m_upper = 0.0, 0.0, 0.0
    else:
        w_lower, w_upper = wilson_interval(wins, n_total)
        m_mean, m_lower, m_upper = bootstrap_mean_ci(samples)

    da_payload = (devils_advocate_loader or _default_devils_advocate_loader)()
    if isinstance(da_payload, dict):
        edges_holding = int(da_payload.get("edgesHolding") or 0)
        strategies_total = int(da_payload.get("strategyCount") or 0)
        da_verdict = str(da_payload.get("verdict") or "unknown")
    else:
        edges_holding = 0
        strategies_total = 0
        da_verdict = "missing"

    breakeven = empirical_breakeven(samples)
    wilson_anchor = breakeven if breakeven is not None else 0.5
    s_w = wilson_strength(w_lower, wilson_anchor)
    s_e = expectancy_strength(m_lower)
    # Confirm-rescue: when the win rate clears its payoff-implied breakeven
    # *and* the bootstrap expectancy lower bound is positive, both axes agree
    # the strategy is profitable. The win-rate magnitude is noisy at realistic
    # sample sizes, so do not let it veto — via the geometric mean's weakest-
    # component behaviour — a strategy the expectancy axis already supports.
    # We never rescue when the win rate is below breakeven or expectancy is
    # non-positive, so genuine losers stay fully penalised.
    win_rate_confirms = (
        breakeven is not None and w_lower > wilson_anchor and m_lower > 0
    )
    if win_rate_confirms:
        s_w = max(s_w, s_e)

    components: dict[str, float | None] = {
        "sampleSize": sample_size_strength(n_total),
        "wilsonLower": s_w,
        "expectancyLower": s_e,
        "falsification": falsification_strength(edges_holding, strategies_total),
    }
    strength, active = composite_strength(components)
    verdict = classify_verdict(strength, n_total)

    weakest_component = None
    weakest_value = None
    for key, value in components.items():
        if value is None:
            continue
        if weakest_value is None or value < weakest_value:
            weakest_value = value
            weakest_component = key

    if verdict == "no-evidence":
        narrative = (
            "No closed paper samples on the shadow ledger. The desk has not "
            "yet produced anything statistically meaningful to evaluate."
        )
    elif verdict == "strong":
        narrative = (
            f"Composite strength {strength:.2f} clears the strong threshold "
            f"({STRONG_STRENGTH}). Authority controller may consider its other "
            f"gates. Weakest component: {weakest_component} ({weakest_value:.2f})."
        )
    elif verdict == "moderate":
        narrative = (
            f"Composite strength {strength:.2f} is in the moderate band "
            f"({MODERATE_STRENGTH}–{STRONG_STRENGTH}). Keep accumulating evidence. "
            f"Weakest component: {weakest_component} ({weakest_value:.2f})."
        )
    elif verdict == "weak":
        narrative = (
            f"Composite strength {strength:.2f} sits in the weak band "
            f"({WEAK_STRENGTH}–{MODERATE_STRENGTH}). Authority must not advance. "
            f"Weakest component: {weakest_component} ({weakest_value:.2f})."
        )
    else:
        narrative = (
            f"Composite strength {strength:.2f} is below the weak threshold "
            f"({WEAK_STRENGTH}). The desk's evidence does not yet support any "
            f"authority promotion. Weakest component: {weakest_component} ({weakest_value:.2f})."
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": EVIDENCE_STRENGTH_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "strength": round(strength, 4),
        "strongThreshold": STRONG_STRENGTH,
        "moderateThreshold": MODERATE_STRENGTH,
        "weakThreshold": WEAK_STRENGTH,
        "totalSamples": n_total,
        "wins": wins,
        "losses": losses,
        "wilsonLower": round(w_lower, 4),
        "wilsonUpper": round(w_upper, 4),
        "winRateBreakeven": round(wilson_anchor, 4),
        "winRateBreakevenSource": "payoff-implied" if breakeven is not None else "coinflip-default",
        "winRateConfirmsEdge": win_rate_confirms,
        "expectancyMean": round(m_mean, 4),
        "expectancyLower": round(m_lower, 4),
        "expectancyUpper": round(m_upper, 4),
        "components": {k: (round(v, 4) if v is not None else None) for k, v in components.items()},
        "activeComponents": active,
        "weakestComponent": weakest_component,
        "weakestValue": round(weakest_value, 4) if weakest_value is not None else None,
        "targetSamples": TARGET_SAMPLES,
        "targetExpectancyR": TARGET_EXPECTANCY_R,
        "edgesHolding": edges_holding,
        "strategiesTotal": strategies_total,
        "devilsAdvocateVerdict": da_verdict,
        "reminders": [
            "geometric mean — the weakest component caps the composite",
            "authority manifest is owned by the controller; this scalar is advisory",
            "falsification component only counts edges surviving sign-flip bootstrap",
        ],
    }


def strength_text(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Evidence Strength (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}  strength={payload.get('strength')}",
        f"Samples: {payload.get('totalSamples')}  "
        f"wins={payload.get('wins')}  "
        f"losses={payload.get('losses')}",
        f"Win-rate Wilson: [{payload.get('wilsonLower')}, {payload.get('wilsonUpper')}]",
        f"Win-rate breakeven anchor: {payload.get('winRateBreakeven')} "
        f"({payload.get('winRateBreakevenSource')}; confirms-edge={payload.get('winRateConfirmsEdge')})",
        f"Mean R bootstrap: [{payload.get('expectancyLower')}, {payload.get('expectancyMean')}, {payload.get('expectancyUpper')}]",
        f"Falsification: {payload.get('edgesHolding')}/{payload.get('strategiesTotal')} strategies hold "
        f"(devil's advocate verdict: {payload.get('devilsAdvocateVerdict')})",
        "",
        f"Narrative: {payload.get('narrative')}",
    ]
    components = payload.get("components") or {}
    if components:
        lines.extend(["", "Component scores (each scaled 0..1; geometric mean is composite):"])
        for key in ("sampleSize", "wilsonLower", "expectancyLower", "falsification"):
            value = components.get(key)
            value_str = f"{value:.4f}" if isinstance(value, (int, float)) else "n/a"
            lines.append(f"- {key}: {value_str}")
    lines.extend(["", "Thresholds:"])
    lines.append(f"- strong:       strength >= {payload.get('strongThreshold')}")
    lines.append(f"- moderate:     strength >= {payload.get('moderateThreshold')}")
    lines.append(f"- weak:         strength >= {payload.get('weakThreshold')}")
    lines.append(f"- insufficient: strength <  {payload.get('weakThreshold')}")
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_strength(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(EVIDENCE_STRENGTH_FILE, payload)
    atomic_write_text(EVIDENCE_STRENGTH_TEXT_FILE, strength_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Composite evidence strength scalar over Wilson lower bound, "
            "bootstrap expectancy lower bound, sample-size target, and "
            "devil's-advocate survival. Research-only; never promotable."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and EVIDENCE_STRENGTH_TEXT_FILE.exists():
        print(EVIDENCE_STRENGTH_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_strength()
    save_strength(payload)
    print(strength_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
