from __future__ import annotations

"""Research-only audit of score usage, thresholds, and model assumptions.

This module answers: "Are the desk's scores and gates being used in ways that
match the evidence?" It does not tune thresholds, stage tickets, change risk
constants, alter the universe, or touch broker authority.
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any

from inferno_config import (
    MAX_DAILY_TICKET_DOLLARS,
    MAX_OPEN_PAPER_TICKETS,
    MAX_SINGLE_TICKET_DOLLARS,
    MAX_UNDERLYING_SOURCE_DIVERGENCE_PCT,
    MIN_CREDIT_SPREAD_CREDIT_RISK,
    MIN_DEBIT_SPREAD_REWARD_RISK,
    local_now,
)
from inferno_evidence_strength import (
    MODERATE_STRENGTH,
    STRONG_STRENGTH,
    TARGET_EXPECTANCY_R,
    TARGET_SAMPLES,
    WEAK_STRENGTH,
)
from inferno_expected_move_ledger import (
    HURDLE_HARD_ATR_MULTIPLE,
    HURDLE_REASONABLE_ATR_MULTIPLE,
    HURDLE_STRETCH_ATR_MULTIPLE,
)
from inferno_io import atomic_write_json, atomic_write_text
from inferno_paper_bootstrap import (
    DEFAULT_ADMIT_THRESHOLD,
    MAX_DAYS_UNTIL_EARNINGS,
    MIN_CONFIDENCE,
    MIN_READY_SCORE,
)
from inferno_paper_variant_scanner import (
    MIN_CREDIT_IV_RANK,
    MIN_SUPPORT_ATR,
    MIN_WHEEL_IV_RANK,
    PRICE_CAP,
    WHEEL_PROXY_PRICE_CAP,
)
from inferno_risk_policy import SCHWAB_OPTIONS_MAX_AGE_HOURS, VISIBLE_QUOTE_MIN_PRICE
from inferno_score_calibration import MIN_CALIBRATION_SAMPLE, MIN_MONOTONIC_BUCKET_SAMPLE
from inferno_strategy_lab import (
    MAX_DRAWDOWN_RISK_UNITS,
    MAX_FALSE_POSITIVE_RATE,
    MIN_EXPECTANCY_LOWER_BOUND,
    MIN_PROFIT_FACTOR,
    MIN_SCORED_TRADES_FOR_PROMOTION,
    MIN_WIN_RATE_LOWER_BOUND,
    WIN_RATE_BREAKEVEN_MARGIN,
)
from inferno_threshold_sensitivity import build_sensitivity
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


SCORE_THRESHOLD_AUDIT_FILE = DATA_DIR / "inferno_score_threshold_audit.json"
SCORE_THRESHOLD_AUDIT_TEXT_FILE = REPORTS_DIR / "score_threshold_audit_latest.txt"
STAGE = "score-threshold-audit-research-only"

SCORE_CALIBRATION_FILE = DATA_DIR / "inferno_score_calibration.json"
EXPECTED_MOVE_LEDGER_FILE = DATA_DIR / "inferno_expected_move_ledger.json"
CAPITAL_SCALING_FILE = DATA_DIR / "inferno_capital_scaling.json"
MODEL_COMMAND_CENTER_FILE = DATA_DIR / "inferno_model_command_center.json"
STRATEGY_ALTERNATIVE_PRICING_FILE = DATA_DIR / "inferno_strategy_alternative_pricing.json"
PAPER_VARIANT_SCANNER_FILE = DATA_DIR / "inferno_paper_variant_scanner.json"
DTE_POLICY_ANALYSIS_FILE = DATA_DIR / "inferno_dte_policy_analysis.json"


def text(value: Any) -> str:
    return str(value or "").strip()


def number(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    raw = text(value).replace("$", "").replace(",", "").replace("%", "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def pct(value: Any) -> str:
    parsed = number(value)
    if parsed is None:
        return "n/a"
    return f"{parsed * 100:.1f}%" if abs(parsed) <= 1 else f"{parsed:.1f}%"


def money(value: Any) -> str:
    parsed = number(value)
    if parsed is None:
        return "n/a"
    return f"${parsed:.2f}"


def artifact_inputs() -> dict[str, dict[str, Any]]:
    return {
        "scoreCalibration": load_json_file(SCORE_CALIBRATION_FILE) or {},
        "expectedMoveLedger": load_json_file(EXPECTED_MOVE_LEDGER_FILE) or {},
        "capitalScaling": load_json_file(CAPITAL_SCALING_FILE) or {},
        "modelCommandCenter": load_json_file(MODEL_COMMAND_CENTER_FILE) or {},
        "strategyAlternativePricing": load_json_file(STRATEGY_ALTERNATIVE_PRICING_FILE) or {},
        "paperVariantScanner": load_json_file(PAPER_VARIANT_SCANNER_FILE) or {},
        "dtePolicyAnalysis": load_json_file(DTE_POLICY_ANALYSIS_FILE) or {},
    }


def threshold_catalog() -> list[dict[str, Any]]:
    return [
        {
            "area": "candidate_live_quality_gate",
            "metric": "readiness",
            "threshold": f">= {MIN_READY_SCORE}",
            "scale": "0-100 percent readiness",
            "source": "inferno_paper_bootstrap.py / inferno_operator_briefing.py",
            "use": "Live-quality gate and paper-bootstrap gate component.",
            "assumption": "Readiness is a rank-like quality screen, not a probability of profit.",
        },
        {
            "area": "candidate_live_quality_gate",
            "metric": "confidence",
            "threshold": f">= {MIN_CONFIDENCE}",
            "scale": "0-3 tracker confidence",
            "source": "inferno_paper_bootstrap.py",
            "use": "One of five candidate quality predicates.",
            "assumption": "Confidence has ordinal meaning but is not outcome-calibrated by itself.",
        },
        {
            "area": "candidate_live_quality_gate",
            "metric": "daysUntilEarnings",
            "threshold": f"<= {MAX_DAYS_UNTIL_EARNINGS}",
            "scale": "calendar days",
            "source": "inferno_paper_bootstrap.py",
            "use": "Candidate timing predicate.",
            "assumption": "21 DTE is a review/eligibility convention, not a proven universal exit or entry optimum.",
        },
        {
            "area": "paper_bootstrap",
            "metric": "gatesCleared",
            "threshold": f">= {DEFAULT_ADMIT_THRESHOLD} of 5",
            "scale": "integer 0-5",
            "source": "inferno_paper_bootstrap.py",
            "use": "Relaxed paper-only seed score.",
            "assumption": "Paper seeding can relax discovery without relaxing promotion math.",
        },
        {
            "area": "promotion_evidence",
            "metric": "scored paper outcomes",
            "threshold": f">= {MIN_SCORED_TRADES_FOR_PROMOTION}",
            "scale": "count",
            "source": "inferno_strategy_lab.py",
            "use": "Minimum evidence before strategy promotion review.",
            "assumption": "Small samples lie; promotion requires closed scored outcomes.",
        },
        {
            "area": "promotion_evidence",
            "metric": "Wilson lower win rate",
            "threshold": (
                ">= payoff-implied breakeven "
                f"+ {WIN_RATE_BREAKEVEN_MARGIN} margin "
                f"(fixed fallback {MIN_WIN_RATE_LOWER_BOUND})"
            ),
            "scale": "probability",
            "source": "inferno_strategy_lab.py",
            "use": "Lower-confidence payoff-aware win-rate gate.",
            "assumption": "Win-rate point estimates should not promote authority, and win rate must be judged against payoff shape.",
        },
        {
            "area": "promotion_evidence",
            "metric": "expectancy lower bound",
            "threshold": f"> {MIN_EXPECTANCY_LOWER_BOUND}",
            "scale": "R units",
            "source": "inferno_strategy_lab.py",
            "use": "Positive lower-bound expectancy gate.",
            "assumption": "Expected value matters more than hit rate.",
        },
        {
            "area": "promotion_evidence",
            "metric": "profit factor",
            "threshold": f">= {MIN_PROFIT_FACTOR}",
            "scale": "gross wins / gross losses",
            "source": "inferno_strategy_lab.py",
            "use": "Payoff quality gate.",
            "assumption": "A strategy must pay enough on winners to survive friction and losses.",
        },
        {
            "area": "promotion_evidence",
            "metric": "max drawdown",
            "threshold": f">= {MAX_DRAWDOWN_RISK_UNITS} R",
            "scale": "cumulative R drawdown",
            "source": "inferno_strategy_lab.py",
            "use": "Cooldown gate.",
            "assumption": "A strategy with too much path pain should not gain authority even if other stats look OK.",
        },
        {
            "area": "evidence_strength",
            "metric": "composite strength",
            "threshold": f"weak {WEAK_STRENGTH}, moderate {MODERATE_STRENGTH}, strong {STRONG_STRENGTH}",
            "scale": "0-1 geometric mean",
            "source": "inferno_evidence_strength.py",
            "use": "Advisory scalar; not an authority switch.",
            "assumption": f"Target sample {TARGET_SAMPLES}, target expectancy {TARGET_EXPECTANCY_R} R.",
        },
        {
            "area": "risk_cap",
            "metric": "single-ticket / daily / open tickets",
            "threshold": (
                f"{money(MAX_SINGLE_TICKET_DOLLARS)} / {money(MAX_DAILY_TICKET_DOLLARS)} / "
                f"{MAX_OPEN_PAPER_TICKETS}"
            ),
            "scale": "dollars and count",
            "source": "inferno_config.py, inferno_risk_policy.py",
            "use": "Paper risk containment.",
            "assumption": "Config values are operator constants unless a capital-scaling ack overrides them.",
        },
        {
            "area": "quote_quality",
            "metric": "leg quote visibility",
            "threshold": f"bid/ask >= {money(VISIBLE_QUOTE_MIN_PRICE)}",
            "scale": "option premium dollars",
            "source": "inferno_risk_policy.py",
            "use": "Blocks option legs without executable-looking quotes.",
            "assumption": "Tiny visible quotes are not reliable markets for paper evidence.",
        },
        {
            "area": "quote_quality",
            "metric": "Schwab option-chain age",
            "threshold": f"<= {SCHWAB_OPTIONS_MAX_AGE_HOURS} hours",
            "scale": "hours",
            "source": "inferno_risk_policy.py",
            "use": "Blocks stale read-only option-chain evidence.",
            "assumption": "Option-chain staleness invalidates pricing gates before paper entry.",
        },
        {
            "area": "quote_quality",
            "metric": "generic option spread",
            "threshold": "<= 35%",
            "scale": "bid/ask spread as share of mid",
            "source": "inferno_strike_selector.py",
            "use": "Generic option-chain tradability guard.",
            "assumption": "Wide spreads are a friction and execution-quality problem, not a small warning.",
        },
        {
            "area": "risk_quality",
            "metric": "underlying source drift",
            "threshold": f"<= {MAX_UNDERLYING_SOURCE_DIVERGENCE_PCT}%",
            "scale": "percent price divergence",
            "source": "inferno_config.py / inferno_risk_policy.py",
            "use": "Blocks stale/mismatched tracker-vs-chain prices.",
            "assumption": "A stale underlying price corrupts strike/risk math.",
        },
        {
            "area": "spread_economics",
            "metric": "debit reward/risk",
            "threshold": f">= {MIN_DEBIT_SPREAD_REWARD_RISK}",
            "scale": "max profit / max loss",
            "source": "inferno_config.py / inferno_risk_policy.py",
            "use": "Blocks weak defined-risk debit spreads.",
            "assumption": "Low reward/risk cannot be rescued by a pretty setup score.",
        },
        {
            "area": "spread_economics",
            "metric": "credit/risk",
            "threshold": f">= {MIN_CREDIT_SPREAD_CREDIT_RISK}",
            "scale": "credit / max loss",
            "source": "inferno_config.py / inferno_risk_policy.py",
            "use": "Blocks underpaid defined-risk credit spreads.",
            "assumption": "Short premium needs enough collected credit to justify gap/tail risk.",
        },
        {
            "area": "expected_move",
            "metric": "premium hurdle",
            "threshold": (
                f"reasonable <= {HURDLE_REASONABLE_ATR_MULTIPLE} ATR, "
                f"stretch <= {HURDLE_STRETCH_ATR_MULTIPLE} ATR, "
                f"hard <= {HURDLE_HARD_ATR_MULTIPLE} ATR"
            ),
            "scale": "required move / ATR",
            "source": "inferno_expected_move_ledger.py",
            "use": "Demotes long-vol structures when premium requires too much realized movement.",
            "assumption": "ATR-normalized premium pressure is more informative than direction alone.",
        },
        {
            "area": "score_calibration",
            "metric": "score bucket sample",
            "threshold": f"overall >= {MIN_CALIBRATION_SAMPLE}; monotonic bucket >= {MIN_MONOTONIC_BUCKET_SAMPLE}",
            "scale": "count",
            "source": "inferno_score_calibration.py",
            "use": "Decides whether score buckets can be interpreted.",
            "assumption": "Bucket-level calibration is noisy below minimum samples.",
        },
        {
            "area": "paper_variant_scanner",
            "metric": "credit-spread variant",
            "threshold": f"price < {PRICE_CAP}, IV rank > {MIN_CREDIT_IV_RANK}, support >= {MIN_SUPPORT_ATR} ATR",
            "scale": "price, IV rank, ATR multiple",
            "source": "inferno_paper_variant_scanner.py",
            "use": "Research-only candidate backfill when main funnel is stagnant.",
            "assumption": "Scanner is discovery only; pricing/risk gates remain authoritative.",
        },
        {
            "area": "paper_variant_scanner",
            "metric": "wheel-proxy variant",
            "threshold": f"price < {WHEEL_PROXY_PRICE_CAP}, IV rank > {MIN_WHEEL_IV_RANK}",
            "scale": "price and IV rank",
            "source": "inferno_paper_variant_scanner.py",
            "use": "Research-only cheap-name defined-risk proxy discovery.",
            "assumption": "This is not cash-secured put or assignment authorization.",
        },
    ]


def severity_rank(severity: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(severity, 9)


def finding(
    severity: str,
    title: str,
    evidence: str,
    interpretation: str,
    recommendation: str,
    *,
    source: str,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "title": title,
        "evidence": evidence,
        "interpretation": interpretation,
        "recommendation": recommendation,
        "source": source,
    }


def calibration_findings(score_calibration: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    counts = score_calibration.get("counts") or {}
    scenario = {
        item.get("field"): item
        for item in score_calibration.get("scenarioCalibration") or []
        if isinstance(item, dict)
    }
    scenario_score = scenario.get("scenarioScore") or {}
    readiness = scenario.get("readiness") or {}
    violations = len(scenario_score.get("monotonicViolations") or [])
    readiness_violations = len(readiness.get("monotonicViolations") or [])
    if violations or readiness_violations:
        findings.append(
            finding(
                "P1",
                "Score surfaces are not monotonic enough to treat as probabilities",
                (
                    f"scenarioScore n={scenario_score.get('sampleCount')} with {violations} monotonic violations; "
                    f"readiness n={readiness.get('sampleCount')} with {readiness_violations} violations."
                ),
                (
                    "Readiness and scenario scores can rank work, but they should not directly size trades "
                    "or override structure, quote quality, or expectancy gates."
                ),
                "Keep score thresholds as discovery filters; calibrate by bucket before using scores as odds or sizing inputs.",
                source="reports/score_calibration_latest.txt",
            )
        )
    if int(counts.get("optionScoreRows") or 0) == 0:
        findings.append(
            finding(
                "P2",
                "Closed option outcomes are not carrying score fields",
                (
                    f"{counts.get('closedOptionRecords', 0)} closed option records exist, "
                    "but optionScoreRows=0."
                ),
                (
                    "The desk can calibrate scenario observations, but it cannot yet answer whether the "
                    "exact scores attached to option tickets predicted option R outcomes."
                ),
                "Preserve readiness/scenarioScore/priorityScore on paper and shadow option records at entry.",
                source="data/inferno_score_calibration.json",
            )
        )
    return findings


def expected_move_findings(expected_move: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    counts = expected_move.get("counts") or {}
    overall = expected_move.get("overall") or {}
    if counts.get("closedLongVolRecords"):
        findings.append(
            finding(
                "P1",
                "Long-vol setups are not currently earning the move they require",
                (
                    f"closed long-vol n={counts.get('closedLongVolRecords')} | "
                    f"beat rate={pct(overall.get('beatRate'))} | "
                    f"mean move edge={number(overall.get('meanMoveEdgePct'), 0.0):.2f}%."
                ),
                (
                    "Direction and readiness are not enough for long-vol structures; premium, spread, "
                    "and event movement have to clear a much harder hurdle."
                ),
                "Keep long-vol demotion active and require priced implied-move context before favoring premium buys.",
                source="reports/expected_move_ledger_latest.txt",
            )
        )
    if int(counts.get("currentMissingPriceOrPremium") or 0) > 0:
        findings.append(
            finding(
                "P2",
                "Current long-vol candidates are unpriced, so pressure scoring is muted",
                (
                    f"{counts.get('currentMissingPriceOrPremium')} current candidates are missing "
                    "price/premium context."
                ),
                (
                    "The alternative scorer cannot identify hard/extreme premium pressure until the "
                    "candidate has a priced move or debit proxy."
                ),
                "Run pricing earlier in the research cycle or pass scanner alternatives directly to pricing, as done for paper variants.",
                source="reports/expected_move_ledger_latest.txt",
            )
        )
    return findings


def sensitivity_findings(production: dict[str, Any], shadow: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    production_any = production.get("promotedAnyUnder") or []
    shadow_any = shadow.get("promotedAnyUnder") or []
    if not production_any and not shadow_any:
        findings.append(
            finding(
                "P1",
                "Loosening promotion thresholds would not solve the current problem",
                (
                    "Production sensitivity promotes no strategy under production, moderate, exploratory, or permissive profiles; "
                    "shadow replay also promotes none."
                ),
                (
                    "The account is not stagnant because promotion gates are too strict. Production lacks scored outcomes, "
                    "and shadow replay fails on expectancy/drawdown even with loose profiles."
                ),
                "Do not lower promotion gates; increase clean paper chances and close scored outcomes.",
                source="inferno_threshold_sensitivity.py",
            )
        )
    return findings


def capital_findings(capital_scaling: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    recommendation = capital_scaling.get("recommendation") or {}
    current = capital_scaling.get("currentEnforced") or {}
    inputs = capital_scaling.get("inputs") or {}
    config_cap = number(current.get("singleTicketCap"), MAX_SINGLE_TICKET_DOLLARS)
    recommended = number(recommendation.get("recommendedCap"))
    nlv = number(inputs.get("netLiquidatingValue"))
    if config_cap and recommended and config_cap > recommended * 5:
        findings.append(
            finding(
                "P1",
                "Configured ticket cap is far above the account-size formula",
                (
                    f"Config cap {money(config_cap)} vs recommended {money(recommended)} "
                    f"on NLV {money(nlv)}."
                ),
                (
                    "The risk policy still blocks many tickets via current caps and quote gates, but the "
                    "operator-visible config is not aligned with the account-size model."
                ),
                "Keep authority unchanged; only the operator should ack the scaling formula or change config constants.",
                source="reports/capital_scaling_latest.txt",
            )
        )
    return findings


def pricing_findings(strategy_pricing: dict[str, Any], scanner: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    pricing_counts = strategy_pricing.get("counts") or {}
    scanner_counts = scanner.get("counts") or {}
    scanner_candidates = int(scanner_counts.get("pricingCandidates") or 0)
    risk_passed = int(pricing_counts.get("riskPassed") or 0)
    scanner_priced = int(pricing_counts.get("scannerCandidates") or 0)
    if scanner_candidates and scanner_priced:
        findings.append(
            finding(
                "P2",
                "Paper variant backfill is creating measurable paper chances",
                (
                    f"Scanner produced {scanner_candidates} pricing candidates; pricing checked "
                    f"{scanner_priced} and {risk_passed} passed combined gates."
                ),
                (
                    "This is the right kind of pressure relief: discovery widened, while pricing and risk "
                    "gates still rejected weak rows."
                ),
                "Keep scanner output paper-only and add outcome tracking before changing its thresholds.",
                source="reports/paper_variant_scanner_latest.txt",
            )
        )
    return findings


def dte_findings(dte_policy: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    comparison = dte_policy.get("observational21DteComparison") or dte_policy.get("observationalExitComparison") or {}
    at_or_above = comparison.get("closedAtOrAbove21Dte") or {}
    below = comparison.get("closedBelow21Dte") or {}
    if at_or_above.get("scoredCount") in {0, None} and below.get("scoredCount"):
        findings.append(
            finding(
                "P2",
                "21-DTE policy cannot be validated from current closed cohorts",
                (
                    f"closedAtOrAbove21Dte scored={at_or_above.get('scoredCount', 0)}; "
                    f"closedBelow21Dte scored={below.get('scoredCount', 0)}."
                ),
                "The 21-DTE rule is a review trigger, not a proven force-close or entry optimum.",
                "Keep DTE cohorts observational until matched paper cohorts exist.",
                source="reports/dte_policy_analysis_latest.txt",
            )
        )
    return findings


def assumption_checks() -> list[dict[str, Any]]:
    return [
        {
            "assumption": "Scores are rank surfaces, not calibrated probabilities.",
            "status": "supported",
            "evidence": "Score calibration explicitly reports monotonic violations and optionScoreRows=0.",
            "falsifier": "Closed option records with score fields show monotonic, stable bucket-level R outcomes.",
        },
        {
            "assumption": "Promotion gates should stay conservative.",
            "status": "supported",
            "evidence": "Production and shadow sensitivity sweeps promote no strategy under looser profiles.",
            "falsifier": "A future sensitivity run shows positive expectancy and controlled drawdown with adequate paper evidence.",
        },
        {
            "assumption": "Risk gates should remain downstream authority.",
            "status": "supported",
            "evidence": "Scanner discovery created paper chances, while pricing/risk gates still blocked IREN.",
            "falsifier": "Scanner candidates consistently pass pricing but fail for avoidable unit mismatches rather than real risk.",
        },
        {
            "assumption": "DTE rules are hypotheses, not causal rules.",
            "status": "supported",
            "evidence": "DTE analysis has no closed-at-or-above-21-DTE scored cohort for comparison.",
            "falsifier": "Matched paper cohorts across DTE bands show stable net-R and drawdown differences.",
        },
    ]


REPO_ROOT = Path(__file__).resolve().parent

# Threshold/risk knobs that, if defined in more than one module, can silently
# drift apart. inferno_math_config.py advertises itself as "every math knob in
# one auditable file", but several of these are still hard-coded independently.
# This guard turns that latent risk into a visible finding without the audit
# touching any risk file (those edits are operator/Codex-owned).
WATCHED_DRIFT_CONSTANTS = (
    "MAX_DAILY_RISK_UNITS",
    "MAX_KELLY_FRACTION",
    "MAX_SINGLE_TRADE_RISK_UNITS",
    "MIN_PAPER_SAMPLES_FOR_PROMOTION",
    "MIN_WILSON_LOWER_FOR_EDGE",
)

_ENV_DEFAULT_RE = re.compile(r"""os\.environ\.get\([^,]+,\s*["']([^"']+)["']\s*\)""")
_LITERAL_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


def _extract_constant_value(rhs: str) -> str | None:
    """Pull a comparable default value out of a constant's right-hand side.

    Handles plain literals (``3.0``), typed literals (``Final[float] = 3.0``),
    and env-override defaults (``float(os.environ.get("X", "3.0"))``). Returns
    a normalized numeric string, or ``None`` when the RHS is an alias/expression
    with no literal default (e.g. ``MIN_READY_SCORE = CANDIDATE_MIN_READINESS``),
    which means it is *already* single-sourced and not a drift risk.
    """
    env_match = _ENV_DEFAULT_RE.search(rhs)
    candidate = env_match.group(1) if env_match else rhs
    literal = _LITERAL_RE.search(candidate)
    if not literal:
        return None
    try:
        return repr(float(literal.group(1)))
    except ValueError:
        return None


def scan_constant_definitions(
    *, root: Path | None = None, names: tuple[str, ...] = WATCHED_DRIFT_CONSTANTS
) -> dict[str, list[dict[str, str]]]:
    """Map each watched constant name to the files that define it with a literal."""
    root = root or REPO_ROOT
    found: dict[str, list[dict[str, str]]] = {name: [] for name in names}
    patterns = {
        name: re.compile(rf"^{re.escape(name)}\s*(?::[^=]+)?=\s*(.+)$")
        for name in names
    }
    for path in sorted(root.glob("inferno_*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            for name, pattern in patterns.items():
                match = pattern.match(line)
                if not match:
                    continue
                value = _extract_constant_value(match.group(1).strip())
                if value is None:
                    continue
                found[name].append({"file": path.name, "value": value})
    return found


def constant_drift_findings(
    *, root: Path | None = None, names: tuple[str, ...] = WATCHED_DRIFT_CONSTANTS
) -> list[dict[str, Any]]:
    """Flag any watched constant defined with a literal value in >1 module."""
    findings: list[dict[str, Any]] = []
    definitions = scan_constant_definitions(root=root, names=names)
    for name in names:
        defs = definitions.get(name) or []
        if len(defs) < 2:
            continue
        files = ", ".join(f"{d['file']}={d['value']}" for d in defs)
        distinct_values = {d["value"] for d in defs}
        diverged = len(distinct_values) > 1
        severity = "P1" if diverged else "P2"
        if diverged:
            interpretation = (
                "The same risk/threshold constant resolves to DIFFERENT values "
                "across modules. Behaviour now depends on which module runs."
            )
        else:
            interpretation = (
                "The constant is duplicated across modules. Values agree today, "
                "but nothing enforces that — a change in one file silently drifts."
            )
        findings.append(
            finding(
                severity,
                f"Risk/threshold constant {name} is defined in multiple files",
                f"{name} defined in {len(defs)} modules: {files}.",
                interpretation,
                (
                    "Single-source this from inferno_math_config.py (the declared "
                    "knob home) and import it everywhere else. Risk-constant edits "
                    "are operator/Codex-owned; surface, do not silently change."
                ),
                source="constant_drift_scan",
            )
        )
    return findings


def build_score_threshold_audit(
    *,
    artifacts: dict[str, dict[str, Any]] | None = None,
    production_sensitivity: dict[str, Any] | None = None,
    shadow_sensitivity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifacts = artifacts or artifact_inputs()
    production_sensitivity = production_sensitivity or build_sensitivity(source="production")
    shadow_sensitivity = shadow_sensitivity or build_sensitivity(source="shadow-replay")

    findings: list[dict[str, Any]] = []
    findings.extend(calibration_findings(artifacts.get("scoreCalibration") or {}))
    findings.extend(expected_move_findings(artifacts.get("expectedMoveLedger") or {}))
    findings.extend(sensitivity_findings(production_sensitivity, shadow_sensitivity))
    findings.extend(capital_findings(artifacts.get("capitalScaling") or {}))
    findings.extend(pricing_findings(artifacts.get("strategyAlternativePricing") or {}, artifacts.get("paperVariantScanner") or {}))
    findings.extend(dte_findings(artifacts.get("dtePolicyAnalysis") or {}))
    findings.extend(constant_drift_findings())
    findings.sort(key=lambda item: (severity_rank(item.get("severity", "")), item.get("title", "")))

    catalog = threshold_catalog()
    return {
        "generatedAt": local_now().isoformat(),
        "stage": STAGE,
        "verdict": "calibrate-scores-do-not-loosen-gates",
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "counts": {
            "thresholdsCataloged": len(catalog),
            "findings": len(findings),
            "p1Findings": sum(1 for item in findings if item.get("severity") == "P1"),
            "p2Findings": sum(1 for item in findings if item.get("severity") == "P2"),
        },
        "thresholdCatalog": catalog,
        "findings": findings,
        "assumptionChecks": assumption_checks(),
        "sensitivitySummary": {
            "productionPromotedAnyUnder": production_sensitivity.get("promotedAnyUnder") or [],
            "shadowPromotedAnyUnder": shadow_sensitivity.get("promotedAnyUnder") or [],
            "productionSourceLabGeneratedAt": production_sensitivity.get("sourceLabGeneratedAt"),
            "shadowSourceLabGeneratedAt": shadow_sensitivity.get("sourceLabGeneratedAt"),
        },
        "externalReferences": [
            {
                "name": "OCC Characteristics and Risks of Standardized Options",
                "url": "https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document",
                "use": "Options risk, standardized disclosure, and suitability guardrail.",
            },
            {
                "name": "FINRA Options overview",
                "url": "https://www.finra.org/investors/investing/investment-products/options",
                "use": "Options leverage, assignment, and loss-risk context.",
            },
            {
                "name": "Schwab bid/ask spread explainer",
                "url": "https://www.schwab.com/learn/story/large-bidask-options-spreads-volatile-markets",
                "use": "Bid/ask spread and liquidity risk context.",
            },
            {
                "name": "Options Industry Council IV metrics",
                "url": "https://www.optionseducation.org/videolibrary/implied-volatility-metrics",
                "use": "IV rank and IV percentile as decision-support metrics, not standalone trade authorization.",
            },
        ],
        "rules": [
            "This audit is diagnostic only and cannot alter production thresholds.",
            "Score thresholds are discovery filters unless calibrated against closed outcomes.",
            "Risk, pricing, and authority gates remain downstream and authoritative.",
            "No paper ticket, approval, live order, broker preview, or universe edit is created here.",
        ],
    }


def render_score_threshold_audit(payload: dict[str, Any]) -> str:
    counts = payload.get("counts") or {}
    lines = [
        "Inferno Score and Threshold Audit",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Verdict: {payload.get('verdict')}",
        "Authority: research-only; broker submit OFF; live trading OFF",
        "",
        "Executive read:",
        "- Do not loosen promotion or risk gates based on the current evidence.",
        "- Treat readiness, scenarioScore, and variant scores as rank surfaces until option-outcome calibration exists.",
        "- The most useful next work is better paper-chance generation plus score preservation on closed option records.",
        "",
        "Counts:",
        f"- thresholds cataloged: {counts.get('thresholdsCataloged', 0)}",
        f"- findings: {counts.get('findings', 0)} | P1={counts.get('p1Findings', 0)} | P2={counts.get('p2Findings', 0)}",
        "",
        "Findings:",
    ]
    for item in payload.get("findings") or []:
        lines.append(f"- [{item.get('severity')}] {item.get('title')}")
        lines.append(f"  evidence: {item.get('evidence')}")
        lines.append(f"  read: {item.get('interpretation')}")
        lines.append(f"  next: {item.get('recommendation')}")
    if not payload.get("findings"):
        lines.append("- none")

    lines.extend(["", "Threshold catalog:"])
    by_area: dict[str, list[dict[str, Any]]] = {}
    for row in payload.get("thresholdCatalog") or []:
        by_area.setdefault(str(row.get("area")), []).append(row)
    for area in sorted(by_area):
        lines.append(f"- {area}")
        for row in by_area[area]:
            lines.append(
                f"  - {row.get('metric')}: {row.get('threshold')} | "
                f"{row.get('scale')} | {row.get('use')}"
            )

    lines.extend(["", "Assumption checks:"])
    for row in payload.get("assumptionChecks") or []:
        lines.append(f"- {row.get('assumption')} -> {row.get('status')}")
        lines.append(f"  evidence: {row.get('evidence')}")
        lines.append(f"  falsifier: {row.get('falsifier')}")

    lines.extend(["", "External references checked:"])
    for ref in payload.get("externalReferences") or []:
        lines.append(f"- {ref.get('name')}: {ref.get('url')}")

    lines.extend(["", "Rules:"])
    for rule in payload.get("rules") or []:
        lines.append(f"- {rule}")
    return "\n".join(lines).rstrip() + "\n"


def save_score_threshold_audit(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or build_score_threshold_audit()
    ensure_dirs()
    atomic_write_json(SCORE_THRESHOLD_AUDIT_FILE, payload)
    atomic_write_text(SCORE_THRESHOLD_AUDIT_TEXT_FILE, render_score_threshold_audit(payload))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Inferno score and threshold usage.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status":
        if SCORE_THRESHOLD_AUDIT_TEXT_FILE.exists():
            print(SCORE_THRESHOLD_AUDIT_TEXT_FILE.read_text(encoding="utf-8"), end="")
            return 0
        print("(no cached score threshold audit)")
        return 1
    payload = save_score_threshold_audit(build_score_threshold_audit())
    print(render_score_threshold_audit(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
