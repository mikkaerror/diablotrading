from __future__ import annotations

"""Inferno Devil's Advocate — actively try to falsify the desk's current edge.

What it does:
    For every strategy currently claiming an edge in the shadow ledger, test
    the null hypothesis ``H0: mean R-units == 0``. We use a permutation /
    sign-flip bootstrap to build a null distribution, then compute a one-sided
    p-value for the observed mean. The verdict reports — for each strategy —
    whether the observed edge survives a falsification attempt.

    The mission of this module is *not* to confirm what we already believe.
    It is to construct the strongest available counter-argument and report
    honestly whether it lands. If the counter-argument lands, the strategy
    fails the falsification gate.

What it does NOT do:
    - Mutate the authority manifest. (The controller still owns that.)
    - Promote or demote a strategy. (The lab still owns that.)
    - Touch any TOS, paper, or broker surface. Pure math.

Strict contract: research-only, diagnostic-only, never promotable. The
artifacts written are advisory; downstream gates read them but do not
delegate authority to them.

## The math

For a strategy with observed mean R-units ``m_obs`` over ``n`` samples:

1. Build the null distribution by randomly flipping the sign of each sample
   ``B`` times (default 2000). Each resample's mean ``m_b`` is one draw from
   the null distribution ``H0: mean = 0`` under the assumption that, absent
   edge, the distribution is symmetric around zero. This is the
   sign-flip bootstrap — exact under the symmetry assumption, robust under
   modest asymmetry.

2. The one-sided p-value is::

       p = (1 + |{b : m_b >= m_obs}|) / (B + 1)

   The ``+1`` numerator and ``+1`` denominator are the conventional
   exact-test correction (Phipson & Smyth 2010); they keep p strictly
   positive even when no bootstrap mean exceeds ``m_obs``.

3. Verdict ladder::

       p < 0.05  → edge-holds       (null rejected at 95% confidence)
       p < 0.20  → edge-weakens     (null not rejected, but observed effect notable)
       p >= 0.20 → edge-falsified   (counter-argument lands)
       n < MIN_FALSIFICATION_SAMPLES → insufficient (no claim either way)

The thresholds are deliberately stricter than a pure statistical test would
demand, because the goal is to be conservative *against our own beliefs*.
We would rather mark a real edge as "weakens" than promote a phantom edge
because we passed an easy test.

CLI::

    python3 inferno_devils_advocate.py             # run + persist
    python3 inferno_devils_advocate.py status      # show last memo
"""

import argparse
import json
import os
import random
from pathlib import Path
from typing import Any, Callable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_theme_synthesizer import _r_units
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


DEVILS_ADVOCATE_FILE = DATA_DIR / "inferno_devils_advocate.json"
DEVILS_ADVOCATE_TEXT_FILE = REPORTS_DIR / "devils_advocate_latest.txt"
DEVILS_ADVOCATE_STAGE = "devils-advocate-research-only"

MIN_FALSIFICATION_SAMPLES = int(os.environ.get("INFERNO_DA_MIN_SAMPLES", "8"))
BOOTSTRAP_RESAMPLES = int(os.environ.get("INFERNO_DA_BOOTSTRAP", "2000"))
BOOTSTRAP_SEED = int(os.environ.get("INFERNO_DA_SEED", "20260513"))
EDGE_HOLDS_P_MAX = 0.05
EDGE_WEAKENS_P_MAX = 0.20


# ---------------------------------------------------------------------------
# Pure math.
# ---------------------------------------------------------------------------


def sign_flip_p_value(
    samples: list[float],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float, int]:
    """Compute the one-sided sign-flip-bootstrap p-value for mean > 0.

    Returns ``(p_value, observed_mean, resamples_at_or_above)``.

    Edge cases:
    - ``n == 0``: returns ``(1.0, 0.0, 0)`` — vacuously cannot reject.
    - ``n == 1``: returns ``(1.0, sample, 0)`` — single observation can't
      separate signal from noise under the null model.
    - all-zero samples: returns ``(1.0, 0.0, resamples)`` — observed effect
      is exactly zero so every resample matches it; null trivially holds.
    """
    n = len(samples)
    if n == 0:
        return 1.0, 0.0, 0
    observed_mean = sum(samples) / n
    if n == 1:
        # One observation cannot distinguish from noise. Fail conservatively.
        return 1.0, float(observed_mean), 0
    rng = random.Random(seed)
    at_or_above = 0
    for _ in range(resamples):
        # Each resample flips each sample's sign with probability 0.5.
        total = 0.0
        for value in samples:
            total += value if rng.random() < 0.5 else -value
        if (total / n) >= observed_mean:
            at_or_above += 1
    # Phipson & Smyth (2010) exact-test correction.
    p = (1 + at_or_above) / (resamples + 1)
    return float(p), float(observed_mean), at_or_above


def classify_verdict(p_value: float, sample_count: int) -> str:
    """Map (p, n) to the falsification verdict ladder."""
    if sample_count < MIN_FALSIFICATION_SAMPLES:
        return "insufficient"
    if p_value < EDGE_HOLDS_P_MAX:
        return "edge-holds"
    if p_value < EDGE_WEAKENS_P_MAX:
        return "edge-weakens"
    return "edge-falsified"


# ---------------------------------------------------------------------------
# Shadow loader (replaceable in tests).
# ---------------------------------------------------------------------------


def _default_shadow_loader() -> list[dict[str, Any]]:
    """Best-effort load of the shadow evidence records."""
    candidates = (
        DATA_DIR / "inferno_shadow_evidence.json",
    )
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows = []
        if isinstance(payload, dict):
            rows = payload.get("records") or payload.get("entries") or payload.get("rows") or []
        elif isinstance(payload, list):
            rows = payload
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def group_by_strategy(records: list[dict[str, Any]]) -> dict[str, list[float]]:
    """Partition closed shadow records into per-strategy R-unit lists."""
    out: dict[str, list[float]] = {}
    for record in records:
        outcome = (record.get("outcome") or {})
        status = str(outcome.get("status") or record.get("outcomeStatus") or "").lower()
        if status != "closed":
            continue
        r = _r_units(record) if _r_units(record) is not None else _r_units(outcome)
        if r is None:
            continue
        strategy = str(record.get("strategy") or "Unknown")
        out.setdefault(strategy, []).append(float(r))
    return out


# ---------------------------------------------------------------------------
# Pure builder.
# ---------------------------------------------------------------------------


def build_falsification(
    *,
    shadow_loader: Callable[[], list[dict[str, Any]]] | None = None,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Run falsification across every strategy with closed samples."""
    records = (shadow_loader or _default_shadow_loader)()
    by_strategy = group_by_strategy(records)

    results: list[dict[str, Any]] = []
    for strategy, samples in by_strategy.items():
        p, mean, at_or_above = sign_flip_p_value(samples, resamples=resamples, seed=seed)
        verdict = classify_verdict(p, len(samples))
        results.append({
            "strategy": strategy,
            "sampleSize": len(samples),
            "observedMean": round(mean, 4),
            "pValue": round(p, 4),
            "resamplesAtOrAbove": at_or_above,
            "verdict": verdict,
        })
    results.sort(key=lambda row: (
        # Highest sample-size, most-significant first so the operator sees
        # the strongest claims at the top.
        -row["sampleSize"], row["pValue"], row["strategy"],
    ))

    holds = [r for r in results if r["verdict"] == "edge-holds"]
    weakens = [r for r in results if r["verdict"] == "edge-weakens"]
    falsified = [r for r in results if r["verdict"] == "edge-falsified"]
    insufficient = [r for r in results if r["verdict"] == "insufficient"]

    if not results:
        verdict = "no-evidence"
        narrative = (
            "No closed shadow records yet — falsification cannot run. The desk has "
            "nothing to attack."
        )
    elif holds:
        verdict = "edges-survive"
        narrative = (
            f"{len(holds)} strategy/strategies survived sign-flip falsification at "
            f"p<{EDGE_HOLDS_P_MAX}. {len(weakens)} weakens, {len(falsified)} falsified, "
            f"{len(insufficient)} insufficient."
        )
    elif weakens:
        verdict = "edges-weak"
        narrative = (
            f"No strategy cleared p<{EDGE_HOLDS_P_MAX}. {len(weakens)} held weakly, "
            f"{len(falsified)} were falsified, {len(insufficient)} have insufficient sample."
        )
    elif falsified:
        verdict = "edges-falsified"
        narrative = (
            f"Every strategy with sufficient sample was falsified at p>={EDGE_WEAKENS_P_MAX}. "
            "The counter-argument lands. Authority must not advance."
        )
    else:
        verdict = "all-insufficient"
        narrative = (
            f"Every strategy has fewer than {MIN_FALSIFICATION_SAMPLES} closed samples. "
            "Falsification cannot run yet — keep building paper evidence."
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": DEVILS_ADVOCATE_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "method": "sign-flip-bootstrap",
        "bootstrapResamples": resamples,
        "minFalsificationSamples": MIN_FALSIFICATION_SAMPLES,
        "edgeHoldsPMax": EDGE_HOLDS_P_MAX,
        "edgeWeakensPMax": EDGE_WEAKENS_P_MAX,
        "strategyCount": len(results),
        "edgesHolding": len(holds),
        "edgesWeak": len(weakens),
        "edgesFalsified": len(falsified),
        "insufficientCount": len(insufficient),
        "results": results,
        "reminders": [
            "verdict is advisory; authority manifest is owned by the controller",
            "sign-flip bootstrap assumes approximate symmetry around H0",
            "thresholds are stricter than standard frequentist tests by design",
        ],
    }


def falsification_text(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Devil's Advocate (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Method: {payload.get('method')}  resamples={payload.get('bootstrapResamples')}",
        f"Verdict: {payload.get('verdict')}",
        f"Strategies: {payload.get('strategyCount')}  "
        f"holds={payload.get('edgesHolding')}  "
        f"weak={payload.get('edgesWeak')}  "
        f"falsified={payload.get('edgesFalsified')}  "
        f"insufficient={payload.get('insufficientCount')}",
        "",
        f"Narrative: {payload.get('narrative')}",
    ]
    results = payload.get("results") or []
    if results:
        lines.extend(["", "Per-strategy falsification:"])
        lines.append(f"{'Strategy':<26} {'N':>4} {'mean R':>8} {'p-value':>9} {'Verdict'}")
        for row in results:
            lines.append(
                f"{str(row.get('strategy'))[:26]:<26} "
                f"{row.get('sampleSize'):>4} "
                f"{row.get('observedMean'):>+8.4f} "
                f"{row.get('pValue'):>9.4f} "
                f"{row.get('verdict')}"
            )
    lines.extend(["", "Thresholds:"])
    lines.append(f"- edge-holds:     p < {payload.get('edgeHoldsPMax')}")
    lines.append(f"- edge-weakens:   p < {payload.get('edgeWeakensPMax')}")
    lines.append(f"- edge-falsified: p >= {payload.get('edgeWeakensPMax')}")
    lines.append(f"- insufficient:   n < {payload.get('minFalsificationSamples')}")
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_falsification(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(DEVILS_ADVOCATE_FILE, payload)
    atomic_write_text(DEVILS_ADVOCATE_TEXT_FILE, falsification_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Attempt to falsify every claimed edge in the shadow ledger via "
            "sign-flip bootstrap. Research-only; never promotable."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and DEVILS_ADVOCATE_TEXT_FILE.exists():
        print(DEVILS_ADVOCATE_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_falsification()
    save_falsification(payload)
    print(falsification_text(payload))
    # Non-zero exit when falsification lands hard — the desk's edges did not survive.
    if payload.get("verdict") == "edges-falsified":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
