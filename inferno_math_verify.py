from __future__ import annotations

"""Inferno Math Verify — cross-module invariant checker.

What it does:
    Loads every math module's latest artifact and asserts that the
    mathematical invariants from ``docs/MATH.md`` hold. Reports the first
    violation per artifact along with a human-readable explanation.

    Invariants checked include:
    - Wilson lower < upper, both in [0, 1]
    - Bootstrap point estimate sits inside its CI
    - Geometric-mean composite ≤ each active component
    - Kelly fraction capped at ``MAX_KELLY_FRACTION``
    - Sum of strategy counts equals total strategy count
    - Probability fields in [0, 1]
    - p-values strictly in (0, 1]
    - Posterior credible interval bounds in [0, 1] and ordered
    - VRP discriminator: lower ≤ point ≤ upper
    - Mutual information rows sorted by NMI descending
    - Walk-forward: train + validate samples sum to total
    - Factor regression: coefficient counts, CI order, and verdict logic

What it does NOT do:
    - Trade. Modify any other artifact. Touch authority. Promote a
      strategy. This is purely a sanity check.

Strict contract: read-only across every artifact; writes only its own
diagnostic JSON / memo. Failure does not throw — it reports.

## Why this exists

The math modules each produce verdicts independently. If any module's
implementation drifts away from the documented formulas (a stale clamp,
a missing edge case, a flipped inequality), the downstream daily loop
will still print a verdict — silently wrong. This module exists to catch
those silent drifts before they accumulate.

CLI::

    python3 inferno_math_verify.py             # run + persist
    python3 inferno_math_verify.py status      # show last memo

Exit code is 1 if any invariant violation is reported.
"""

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any, Callable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


MATH_VERIFY_FILE = DATA_DIR / "inferno_math_verify.json"
MATH_VERIFY_TEXT_FILE = REPORTS_DIR / "math_verify_latest.txt"
MATH_VERIFY_STAGE = "math-verify-research-only"


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _assert(condition: bool, label: str, violations: list[str]) -> None:
    if not condition:
        violations.append(label)


def verify_theme(payload: dict[str, Any] | None) -> list[str]:
    """Cube cells: Wilson lower < upper; both in [0, 1]; mean in [lo, hi]."""
    if not payload:
        return ["theme_synthesizer artifact missing"]
    violations: list[str] = []
    edges = payload.get("edges") or []
    anti = payload.get("antiEdges") or []
    for label, cells in (("edges", edges), ("antiEdges", anti)):
        for cell in cells:
            stats = cell.get("metrics") or cell
            wr_lo = stats.get("winRateLower")
            wr_hi = stats.get("winRateUpper")
            wr = stats.get("winRate")
            mean = stats.get("expectancyMean")
            mlo = stats.get("expectancyLower")
            mhi = stats.get("expectancyUpper")
            if wr_lo is None or wr_hi is None:
                continue
            _assert(0 <= wr_lo <= wr_hi <= 1, f"theme.{label}: Wilson bounds out of [0,1] or unordered", violations)
            if isinstance(wr, (int, float)):
                _assert(wr_lo <= wr <= wr_hi or wr_lo - 1e-3 <= wr <= wr_hi + 1e-3,
                        f"theme.{label}: point WR outside Wilson CI", violations)
            if isinstance(mean, (int, float)) and isinstance(mlo, (int, float)) and isinstance(mhi, (int, float)):
                _assert(mlo <= mhi, f"theme.{label}: bootstrap CI inverted", violations)
                _assert(mlo - 1e-6 <= mean <= mhi + 1e-6,
                        f"theme.{label}: expectancy point outside bootstrap CI", violations)
    return violations


def verify_devils_advocate(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return ["devils_advocate artifact missing"]
    violations: list[str] = []
    for row in payload.get("results") or []:
        p = row.get("pValue")
        if isinstance(p, (int, float)):
            _assert(0 < p <= 1, f"devils_advocate.{row.get('strategy')}: p={p} outside (0,1]", violations)
        n = row.get("sampleSize")
        if isinstance(n, int):
            _assert(n >= 0, f"devils_advocate.{row.get('strategy')}: negative sample size", violations)
    # Counts add up.
    total = (
        (payload.get("edgesHolding") or 0)
        + (payload.get("edgesWeak") or 0)
        + (payload.get("edgesFalsified") or 0)
        + (payload.get("insufficientCount") or 0)
    )
    declared = payload.get("strategyCount") or 0
    _assert(total == declared, "devils_advocate: strategy count buckets don't sum to total", violations)
    return violations


def verify_evidence_strength(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return ["evidence_strength artifact missing"]
    violations: list[str] = []
    # Older artifacts used "strength"; newer evidence payloads expose the
    # same composite as "compositeStrength". Verify either spelling so a
    # harmless schema rename does not punch a hole in the safety net.
    strength = payload.get("strength")
    if not isinstance(strength, (int, float)):
        strength = payload.get("compositeStrength")
    if isinstance(strength, (int, float)):
        _assert(0 <= strength <= 1, f"evidence_strength: composite {strength} outside [0,1]", violations)
    components = payload.get("components") or {}
    for key, value in components.items():
        if value is None:
            continue
        if isinstance(value, (int, float)):
            _assert(0 <= value <= 1, f"evidence_strength.{key}: {value} outside [0,1]", violations)
            if isinstance(strength, (int, float)) and value < strength - 1e-6:
                # Geometric mean: composite must be ≤ each active component.
                violations.append(
                    f"evidence_strength: composite {strength:.4f} > component {key} ({value:.4f})"
                )
    return violations


def verify_kelly(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return ["kelly_sizing artifact missing"]
    violations: list[str] = []
    max_kelly = payload.get("maxKellyFraction") or 0.25
    max_daily = payload.get("maxDailyRiskUnits") or 3.0
    for row in payload.get("rows") or []:
        f_cap = row.get("kellyFractionCapped")
        if isinstance(f_cap, (int, float)):
            _assert(0 <= f_cap <= max_kelly + 1e-9,
                    f"kelly.{row.get('strategy')}: f_capped {f_cap} exceeds cap {max_kelly}", violations)
        f_con = row.get("kellyFractionConservative")
        if isinstance(f_con, (int, float)):
            _assert(f_con >= 0, f"kelly.{row.get('strategy')}: conservative Kelly negative", violations)
    total = payload.get("totalRecommendedRiskUnits")
    if isinstance(total, (int, float)):
        _assert(0 <= total <= max_daily + 1e-9, f"kelly: total {total} exceeds ceiling {max_daily}", violations)
    return violations


def verify_vol_premium(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return ["vol_premium artifact missing"]
    violations: list[str] = []
    for row in payload.get("discriminators") or []:
        point = row.get("discriminator")
        lo = row.get("lower")
        hi = row.get("upper")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
            _assert(lo <= hi, f"vol_premium.{row.get('direction')}: CI inverted", violations)
            if isinstance(point, (int, float)):
                _assert(lo - 1e-6 <= point <= hi + 1e-6,
                        f"vol_premium.{row.get('direction')}: point outside CI", violations)
    return violations


def verify_bayesian(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return ["bayesian_winrate artifact missing"]
    violations: list[str] = []
    for row in payload.get("rows") or []:
        lo = row.get("credibleLower")
        hi = row.get("credibleUpper")
        mean = row.get("posteriorMean")
        p_coin = row.get("probabilityAboveCoin")
        p_edge = row.get("probabilityAboveEdge")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
            _assert(0 <= lo <= hi <= 1, f"bayes.{row.get('strategy')}: credible interval malformed", violations)
        if isinstance(mean, (int, float)):
            _assert(0 <= mean <= 1, f"bayes.{row.get('strategy')}: posterior mean outside [0,1]", violations)
        for key, value in (("P>0.5", p_coin), ("P>edge", p_edge)):
            if isinstance(value, (int, float)):
                _assert(0 <= value <= 1, f"bayes.{row.get('strategy')}.{key}={value} outside [0,1]", violations)
        # Probability monotonicity: P(p > 0.5) >= P(p > 0.55) when edge > 0.5.
        edge_th = row.get("edgeThreshold")
        if (
            isinstance(p_coin, (int, float))
            and isinstance(p_edge, (int, float))
            and isinstance(edge_th, (int, float))
            and edge_th >= 0.5
        ):
            _assert(p_coin + 1e-2 >= p_edge,
                    f"bayes.{row.get('strategy')}: P>0.5 < P>edge but edge>=0.5", violations)
    return violations


def verify_information_gain(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return ["information_gain artifact missing"]
    violations: list[str] = []
    rows = payload.get("rows") or []
    prior_nmi = float("inf")
    for row in rows:
        nmi = row.get("normalisedMI")
        mi = row.get("miBits")
        p = row.get("permutationPValue")
        if isinstance(nmi, (int, float)):
            _assert(0 <= nmi <= 1, f"info_gain.{row.get('feature')}: NMI {nmi} outside [0,1]", violations)
            # Sorted descending.
            _assert(nmi <= prior_nmi + 1e-9, f"info_gain.{row.get('feature')}: NMI not sorted desc", violations)
            prior_nmi = nmi
        if isinstance(mi, (int, float)):
            _assert(mi >= 0, f"info_gain.{row.get('feature')}: MI is negative ({mi})", violations)
        if isinstance(p, (int, float)):
            _assert(0 < p <= 1, f"info_gain.{row.get('feature')}: p={p} outside (0,1]", violations)
    return violations


def verify_walk_forward(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return ["walk_forward artifact missing"]
    violations: list[str] = []
    for row in payload.get("rows") or []:
        n = row.get("sampleSize") or 0
        nt = row.get("trainSize") or 0
        nv = row.get("validateSize") or 0
        _assert(nt + nv == n, f"walk_forward.{row.get('strategy')}: train+validate ({nt}+{nv}) != total ({n})", violations)
        # Win rate fields in [0, 1].
        for key in ("trainWinRate", "trainWilsonLower", "validateWinRate", "validateWilsonLower"):
            value = row.get(key)
            if isinstance(value, (int, float)):
                _assert(0 <= value <= 1, f"walk_forward.{row.get('strategy')}.{key}={value} outside [0,1]", violations)
    return violations


def verify_slate_normalizer(payload: dict[str, Any] | None) -> list[str]:
    """Slate-normalizer invariants:
    - every present rank lies in [0, 100]
    - composite rank lies in [0, 100] when present
    - passing-count never exceeds slate-size
    - gate percentile lies in [0, 100]
    """
    if not payload:
        return ["slate_normalizer artifact missing"]
    violations: list[str] = []
    gate = payload.get("gatePercentile")
    if isinstance(gate, (int, float)):
        _assert(0 <= gate <= 100, f"slate_normalizer: gatePercentile {gate} outside [0,100]", violations)
    slate = payload.get("slateSize")
    passing = payload.get("passingCount")
    if isinstance(slate, int) and isinstance(passing, int):
        _assert(0 <= passing <= slate, f"slate_normalizer: passing {passing} > slate {slate}", violations)
    for r in payload.get("rows") or []:
        ticker = r.get("ticker") or "?"
        for key in ("readyRank", "valueRank", "momentumRank", "squeezeRank",
                    "ivPercentileRank", "compositeRank"):
            v = r.get(key)
            if v is None:
                continue
            if isinstance(v, (int, float)):
                _assert(0 <= v <= 100, f"slate_normalizer.{ticker}.{key}={v} outside [0,100]", violations)
    return violations


def verify_paper_bootstrap(payload: dict[str, Any] | None) -> list[str]:
    """Bootstrap invariants:
    - every proposal carries paperBootstrap=true (the gate that keeps these
      out of live promotion math)
    - score ∈ [0, 5]
    - liveQualityYet iff score == 5
    - score histogram bucket counts sum to slateSize
    - proposalCount equals len(proposals)
    """
    if not payload:
        return ["paper_bootstrap artifact missing"]
    violations: list[str] = []
    proposals = payload.get("proposals") or []
    declared_count = payload.get("proposalCount")
    if isinstance(declared_count, int):
        _assert(
            declared_count == len(proposals),
            f"paper_bootstrap: proposalCount={declared_count} but len(proposals)={len(proposals)}",
            violations,
        )
    for p in proposals:
        ticker = p.get("ticker") or "?"
        score = p.get("score")
        if isinstance(score, int):
            _assert(0 <= score <= 5, f"paper_bootstrap.{ticker}: score {score} outside [0,5]", violations)
        _assert(
            p.get("paperBootstrap") is True,
            f"paper_bootstrap.{ticker}: paperBootstrap flag must be True",
            violations,
        )
        live_quality = p.get("liveQualityYet")
        if isinstance(score, int) and isinstance(live_quality, bool):
            expected = (score == 5)
            _assert(
                live_quality == expected,
                f"paper_bootstrap.{ticker}: liveQualityYet={live_quality} but score={score}",
                violations,
            )
    histogram = payload.get("scoreHistogram") or {}
    slate_size = payload.get("slateSize")
    if histogram and isinstance(slate_size, int):
        # JSON dict keys are stringified; accept both.
        bucket_total = sum(histogram.values())
        _assert(
            bucket_total == slate_size,
            f"paper_bootstrap: histogram sum {bucket_total} != slateSize {slate_size}",
            violations,
        )
    return violations


def verify_slate_normalizer(payload: dict[str, Any] | None) -> list[str]:
    """Slate-normalizer invariants:
    - artifact remains research-only / non-promotable
    - percentile fields stay in [0, 100]
    - passingCount equals rows clearing the ready percentile gate
    - slateSize equals len(rows)
    - rows are sorted by compositeRank descending
    """
    if not payload:
        return ["slate_normalizer artifact missing"]
    violations: list[str] = []
    rows = payload.get("rows") or []
    slate_size = payload.get("slateSize")
    if isinstance(slate_size, int):
        _assert(slate_size == len(rows), f"slate_normalizer: slateSize {slate_size} != len(rows) {len(rows)}", violations)
    _assert(payload.get("researchOnly") is True, "slate_normalizer: researchOnly must be True", violations)
    _assert(payload.get("diagnosticOnly") is True, "slate_normalizer: diagnosticOnly must be True", violations)
    _assert(payload.get("promotable") is False, "slate_normalizer: promotable must be False", violations)

    passing_count = 0
    prior_composite = float("inf")
    for row in rows:
        ticker = row.get("ticker") or "?"
        if row.get("passesReadyPercentileGate"):
            passing_count += 1
        for field in ("readyRank", "valueRank", "momentumRank", "squeezeRank", "ivPercentileRank", "compositeRank"):
            value = row.get(field)
            if isinstance(value, (int, float)):
                _assert(0 <= value <= 100, f"slate_normalizer.{ticker}.{field}={value} outside [0,100]", violations)
        composite = row.get("compositeRank")
        if isinstance(composite, (int, float)):
            _assert(
                composite <= prior_composite + 1e-9,
                f"slate_normalizer.{ticker}: compositeRank not sorted descending",
                violations,
            )
            prior_composite = composite

    declared_passing = payload.get("passingCount")
    if isinstance(declared_passing, int):
        _assert(
            declared_passing == passing_count,
            f"slate_normalizer: passingCount {declared_passing} != counted {passing_count}",
            violations,
        )
    return violations


def verify_regime_drift(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return ["regime_drift artifact missing"]
    violations: list[str] = []
    h = payload.get("alarmH")
    for row in payload.get("rows") or []:
        std = row.get("baselineStd")
        threshold = row.get("alarmThreshold")
        if isinstance(std, (int, float)) and isinstance(threshold, (int, float)) and isinstance(h, (int, float)):
            expected_threshold = round(h * std, 4)
            _assert(abs(threshold - expected_threshold) <= 1e-3,
                    f"regime_drift.{row.get('strategy')}: alarm threshold doesn't equal h*σ̂", violations)
        n = row.get("sampleSize")
        half = row.get("halfSplitIndex")
        if isinstance(n, int) and isinstance(half, int):
            _assert(half == n // 2, f"regime_drift.{row.get('strategy')}: half split != n//2", violations)
        s_pos = row.get("maxPositiveCusum")
        s_neg = row.get("maxNegativeCusum")
        if isinstance(s_pos, (int, float)):
            _assert(s_pos >= 0, f"regime_drift.{row.get('strategy')}: max S+ negative", violations)
        if isinstance(s_neg, (int, float)):
            _assert(s_neg <= 0, f"regime_drift.{row.get('strategy')}: max S- positive", violations)
    return violations


def verify_factor_regression(payload: dict[str, Any] | None) -> list[str]:
    """Validate logistic-regression artifact invariants.

    This does not judge whether a factor is useful; it only makes sure the
    artifact is internally coherent before the desk reads it as evidence.
    """
    if not payload:
        return ["factor_regression artifact missing"]
    violations: list[str] = []
    coefficients = payload.get("coefficients") or []
    sample_size = payload.get("sampleSize")
    feature_count = payload.get("featureCount")
    if isinstance(sample_size, int):
        _assert(sample_size >= 0, "factor_regression: negative sample size", violations)
    if isinstance(feature_count, int):
        _assert(feature_count == len(coefficients),
                "factor_regression: featureCount does not match coefficient rows", violations)

    positive = negative = inconclusive = insufficient = 0
    for coef in coefficients:
        feature = coef.get("feature")
        beta = coef.get("coefficient")
        lo = coef.get("lower95")
        hi = coef.get("upper95")
        verdict = coef.get("verdict")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
            _assert(lo <= hi, f"factor_regression.{feature}: coefficient CI inverted", violations)
            if isinstance(beta, (int, float)):
                _assert(lo - 1e-3 <= beta <= hi + 1e-3,
                        f"factor_regression.{feature}: coefficient outside CI", violations)
            if verdict == "positive-edge":
                positive += 1
                _assert(lo > 0, f"factor_regression.{feature}: positive-edge lower95 <= 0", violations)
            elif verdict == "negative-edge":
                negative += 1
                _assert(hi < 0, f"factor_regression.{feature}: negative-edge upper95 >= 0", violations)
            elif verdict == "inconclusive":
                inconclusive += 1
                _assert(lo <= 0 <= hi,
                        f"factor_regression.{feature}: inconclusive CI does not straddle zero", violations)
            elif verdict == "insufficient":
                insufficient += 1
            else:
                violations.append(f"factor_regression.{feature}: unknown verdict {verdict!r}")

    _assert(positive == (payload.get("positiveEdgeCount") or 0),
            "factor_regression: positiveEdgeCount mismatch", violations)
    _assert(negative == (payload.get("negativeEdgeCount") or 0),
            "factor_regression: negativeEdgeCount mismatch", violations)
    _assert(inconclusive == (payload.get("inconclusiveCount") or 0),
            "factor_regression: inconclusiveCount mismatch", violations)
    _assert(insufficient == (payload.get("insufficientCount") or 0),
            "factor_regression: insufficientCount mismatch", violations)
    return violations


VERIFIERS: dict[str, tuple[str, Callable[[dict[str, Any] | None], list[str]]]] = {
    "theme": ("inferno_theme_synthesizer.json", verify_theme),
    "devilsAdvocate": ("inferno_devils_advocate.json", verify_devils_advocate),
    "evidenceStrength": ("inferno_evidence_strength.json", verify_evidence_strength),
    "kelly": ("inferno_kelly_sizing.json", verify_kelly),
    "volPremium": ("inferno_vol_premium.json", verify_vol_premium),
    "bayesian": ("inferno_bayesian_winrate.json", verify_bayesian),
    "informationGain": ("inferno_information_gain.json", verify_information_gain),
    "walkForward": ("inferno_walk_forward.json", verify_walk_forward),
    "regimeDrift": ("inferno_regime_drift.json", verify_regime_drift),
    "factorRegression": ("inferno_factor_regression.json", verify_factor_regression),
    "slateNormalizer": ("inferno_slate_normalized.json", verify_slate_normalizer),
    "paperBootstrap": ("inferno_paper_bootstrap.json", verify_paper_bootstrap),
    "slateNormalizer": ("inferno_slate_normalized.json", verify_slate_normalizer),
}


def build_math_verify(
    *,
    data_dir: Path = DATA_DIR,
    verifiers: dict[str, tuple[str, Callable[[dict[str, Any] | None], list[str]]]] | None = None,
) -> dict[str, Any]:
    """Run every registered verifier and aggregate findings."""
    verifiers = verifiers or VERIFIERS
    findings: dict[str, dict[str, Any]] = {}
    total_violations = 0
    missing_artifacts = 0
    for key, (filename, verifier) in verifiers.items():
        payload = _load(data_dir / filename)
        if payload is None:
            # Missing artifact is tracked separately — do not double-count
            # as a violation. The verifier's "artifact missing" message is
            # the only thing it returns in that branch.
            missing_artifacts += 1
            findings[key] = {
                "artifact": filename,
                "present": False,
                "violationCount": 0,
                "violations": [],
            }
            continue
        violations = verifier(payload)
        findings[key] = {
            "artifact": filename,
            "present": True,
            "violationCount": len(violations),
            "violations": violations,
        }
        total_violations += len(violations)

    if total_violations == 0 and missing_artifacts == 0:
        verdict = "clean"
        narrative = (
            f"All {len(findings)} math artifacts pass their invariants. "
            "No violations detected."
        )
    elif total_violations == 0 and missing_artifacts > 0:
        verdict = "artifacts-missing"
        missing = [k for k, v in findings.items() if not v["present"]]
        narrative = (
            f"{missing_artifacts} artifact(s) missing: {', '.join(missing)}. "
            "Run the daily loop or the relevant module to generate them."
        )
    else:
        verdict = "violations-detected"
        narrative = (
            f"{total_violations} invariant violation(s) across "
            f"{sum(1 for f in findings.values() if f['violationCount'] > 0)} module(s). "
            "Inspect findings for first-violation details per module."
        )

    return {
        "generatedAt": local_now().isoformat(),
        "stage": MATH_VERIFY_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "verdict": verdict,
        "narrative": narrative,
        "method": "cross-module-invariant-check",
        "moduleCount": len(findings),
        "totalViolations": total_violations,
        "missingArtifacts": missing_artifacts,
        "findings": findings,
        "reminders": [
            "verifier is read-only across every artifact",
            "missing artifact is not a violation — it's reported separately",
            "every invariant traces back to docs/MATH.md",
        ],
    }


def verify_text(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Math Verify (research-only)",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Method: {payload.get('method')}",
        f"Verdict: {payload.get('verdict')}",
        f"Modules checked: {payload.get('moduleCount')}  "
        f"violations: {payload.get('totalViolations')}  "
        f"missing artifacts: {payload.get('missingArtifacts')}",
        "",
        f"Narrative: {payload.get('narrative')}",
        "",
        "Per-module findings:",
    ]
    findings = payload.get("findings") or {}
    for key, finding in findings.items():
        glyph = "✓" if finding["violationCount"] == 0 and finding["present"] else "✗"
        status = "OK" if finding["violationCount"] == 0 and finding["present"] else (
            "MISSING" if not finding["present"] else f"{finding['violationCount']} violation(s)"
        )
        lines.append(f"  {glyph} {key:<22} ({finding['artifact']}) — {status}")
        for violation in finding["violations"]:
            lines.append(f"      • {violation}")
    lines.extend(["", "Reminders:"])
    for reminder in payload.get("reminders") or []:
        lines.append(f"- {reminder}")
    return "\n".join(lines).rstrip() + "\n"


def save_math_verify(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(MATH_VERIFY_FILE, payload)
    atomic_write_text(MATH_VERIFY_TEXT_FILE, verify_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Cross-module invariant verifier for every math artifact. "
            "Research-only; reads every artifact, writes only its own."
        )
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and MATH_VERIFY_TEXT_FILE.exists():
        print(MATH_VERIFY_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_math_verify()
    save_math_verify(payload)
    print(verify_text(payload))
    if payload.get("verdict") == "violations-detected":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
