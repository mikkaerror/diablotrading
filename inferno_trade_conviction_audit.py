from __future__ import annotations

"""Inferno Trade Conviction Auditor — math-and-theory case per pending trade.

What it does:
    For every ready-to-execute ticket on the operator briefing (or every
    pending approval-queue item, when no briefing exists yet), build a
    one-page conviction audit. Each audit has the same fixed structure:

        1. CLAIM       — one sentence stating what the desk would be doing.
        2. PRIORS      — the numeric inputs the gates used.
        3. BULL CASE   — quantitative reasons to take the trade, each with
                         an explicit number and a citation tag
                         (see docs/THEORY_REFERENCES.md).
        4. BEAR CASE   — the strongest available counter-argument. The
                         auditor *must* produce at least one bear point;
                         if no quantitative bear exists it must say so
                         explicitly (never "fully clean").
        5. DISAGREEMENTS — signals across layers that point opposite ways
                          (e.g., tracker readiness=99 but edge=Unclassified).
                          Disagreement is information; the audit refuses to
                          paper over it.
        6. FALSIFICATION TRIGGERS — pre-committed "fold if X" clauses, so
                          the operator commits to an exit before sizing.
        7. STATE-OF-EVIDENCE — what the desk knows and does not know yet
                              (e.g., zero closed paper samples → tracker
                              readiness is *prior*, not posterior).
        8. REFERENCES  — primary literature tags + MATH.md sections + the
                         exact module that computed each input.

What it does NOT do:
    - Approve, reject, or shift any ticket.
    - Mutate the authority manifest or the live book.
    - Touch any TOS, paper, or broker surface.
    - Talk the operator into a trade. The mission is to argue the *bear*
      case at least as hard as the bull case. Conviction is earned by
      surviving honest counter-attack, not by stacking confirmations.

Strict contract: research-only, diagnostic-only, never promotable.
The artifacts written are advisory; downstream gates read them but do not
delegate authority to them.

## Why this module exists

The Ready Score and the readiness percent answer one question: *do the
gates pass?* They do not answer the more important operator question:
*should I trust my gut on this name today?*

This module sits between the briefing and the operator's decision. It
takes the briefing's "ready-to-execute" output and makes the math case
for and against each ticket *out loud*, with citations, so the operator
can decide from rigor instead of vibes. When the math case is weak, the
audit says so. When the desk has no closed paper evidence yet, the audit
labels the conviction as *prior-only* and refuses to call it posterior.

## What "disagreement" means

A disagreement is any pair of evidence layers that point in opposite
directions on conviction. The auditor uses a deterministic set of rules
(see ``_collect_disagreements``); each rule names the two layers, quotes
their numbers, and links to where to verify.

The point of surfacing disagreements is not to block trades — it is to
make sure the operator has consciously decided to override the layer that
disagrees, rather than missing it.

CLI::

    python3 inferno_trade_conviction_audit.py             # run + persist
    python3 inferno_trade_conviction_audit.py status      # show last memo
"""

import argparse
import json
from typing import Any, Iterable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


# ───────────────────────── file locations ──────────────────────────────

OPERATOR_BRIEFING_FILE = DATA_DIR / "inferno_operator_briefing.json"
DECISION_BRIEFS_FILE = DATA_DIR / "inferno_decision_briefs.json"
EDGE_RESEARCH_FILE = DATA_DIR / "inferno_edge_research.json"
EXPOSURE_ANALYTICS_FILE = DATA_DIR / "inferno_exposure_analytics.json"
EVIDENCE_STRENGTH_FILE = DATA_DIR / "inferno_evidence_strength.json"
DEVILS_ADVOCATE_FILE = DATA_DIR / "inferno_devils_advocate.json"
VOL_PREMIUM_FILE = DATA_DIR / "inferno_vol_premium.json"
REGIME_DRIFT_FILE = DATA_DIR / "inferno_regime_drift.json"
BAYESIAN_FILE = DATA_DIR / "inferno_bayesian_winrate.json"
SLATE_NORMALIZED_FILE = DATA_DIR / "inferno_slate_normalized.json"

# Phase A/B/C research-only inputs (see docs/RESEARCH_ROADMAP.md).
# Each is loaded read-only and only used to *add* bullets to the audit.
# Missing artifacts are silent no-ops — they never block the audit.
OUTCOME_ATTRIBUTION_FILE = DATA_DIR / "inferno_outcome_attribution.json"
RULE_EDGE_DECAY_FILE = DATA_DIR / "inferno_rule_edge_decay.json"
SLIPPAGE_ESTIMATOR_FILE = DATA_DIR / "inferno_slippage_estimator.json"
PORTFOLIO_CORRELATION_FILE = DATA_DIR / "inferno_portfolio_correlation.json"
DRAWDOWN_PROTOCOL_FILE = DATA_DIR / "inferno_drawdown_protocol.json"
CONSENSUS_MONITOR_FILE = DATA_DIR / "inferno_consensus_monitor.json"

CONVICTION_AUDIT_FILE = DATA_DIR / "inferno_trade_conviction_audit.json"
CONVICTION_AUDIT_TEXT_FILE = REPORTS_DIR / "trade_conviction_audit_latest.txt"

CONVICTION_AUDIT_STAGE = "trade-conviction-audit-research-only"


# ───────────────────────── thresholds (documented) ─────────────────────

# These thresholds match the existing gates so the auditor speaks the same
# language as the briefing. If a gate moves, update here and add a note in
# docs/MATH.md so the audit narrative stays honest.
READINESS_HIGH_FLOOR = 90          # "tracker is loud" — sets up the disagreement rules
READINESS_GATE = 72                # operator briefing gate (matches §18 in MATH.md)
DTE_GATE = 21                      # convexity governor cap
SECTOR_CONCENTRATION_LIMIT = 0.50  # if proposed ticker is in the dominant sector ≥ this share, flag
SETUP_CONCENTRATION_LIMIT = 0.50   # if the same setup is already ≥ this share of the slate, flag
IV_RANK_RICH = 80                  # "vol is rich" threshold for long-premium discouragement
IV_RANK_CHEAP = 30                 # "vol is cheap" threshold for short-premium discouragement
NEAR_LEVEL_PCT = 5.0               # within 5% of support/resistance = level adjacent
LOW_RVOL_FLOOR = 0.4               # below this, intra-day participation is thin
EVIDENCE_PRIOR_ONLY_SAMPLES = 30   # below this, all calls are prior-only, not posterior

# Master-trader principle thresholds (see docs/MASTER_TRADERS.md).
# These are calibrated to short-DTE options, not to PTJ's macro futures
# 5:1 floor — verticals routinely run R:R between 1:1 and 2:1 by design.
RR_BEAR_FLOOR = 1.5         # below this R:R, the audit fires a bear bullet
RR_DISAGREEMENT_FLOOR = 1.0 # below this R:R, the audit fires a disagreement (capital is being asked to take negative expectancy unless win-rate > 50%)
SIT_OUT_READINESS_FLOOR = 75      # if NO ticket meets this *and* has classified edge, advise sitting out
SIT_OUT_EDGE_REQUIRED = True      # whether sit-out also requires edge to be classified


# ───────────────────────── citation tags (single source of truth) ──────

# Each tag references docs/THEORY_REFERENCES.md. If you add a citation,
# add it there first, then map it here, then use it from a rule.
CITES = {
    # core options theory
    "VRP-BK03": "Bakshi & Kapadia (2003) — long vol has negative expected payoff",
    "DIAV12": "Diavatopoulos et al. (2012) — IV crushes post-earnings; long premium needs realised > implied",
    "ANDR18": "Andrade et al. (2018) — earnings-period straddles average negative; right tail is the whole game",
    "PW79": "Patell & Wolfson (1979) — pre-earnings IV ramp",
    "BS73": "Black & Scholes (1973) — d1/d2, implied move via ATM straddle ≈ S·σ·√(T)·√(2/π)",
    # statistics
    "WIL27": "Wilson (1927) — score CI for binomial proportions (used for win-rate floor)",
    "PHIP10": "Phipson & Smyth (2010) — exact permutation p-value correction (sign-flip bootstrap)",
    "ET93": "Efron & Tibshirani (1993) — percentile bootstrap CI on the mean",
    "PAGE54": "Page (1954) — CUSUM change-point detector (regime drift)",
    # sizing
    "KEL56": "Kelly (1956) — fractional sizing; desk uses quarter-Kelly",
    "MTZ10": "MacLean, Thorp & Ziemba (2010) — fractional Kelly under parameter uncertainty",
    "RT92": "Rotando & Thorp (1992) — half-Kelly ~75% growth at ~half drawdown; estimation-error anchor",
    "THORP-VEC": "Thorp (1975) — portfolio Kelly on correlated bets; ~100 simultaneous wagers at Princeton-Newport",
    # empirical earnings frequencies
    "CBOE-72": "CBOE 10-yr S&P sample — realised < straddle-implied move in ~72% of single-name earnings",
    "BTZ09": "Bollerslev, Tauchen & Zhou (2009) — VRP predicts quarterly equity returns; single-name VRP smaller / noisier",
    # behavioural / hygiene
    "SS85": "Shefrin & Statman (1985) — disposition effect; pre-commit exits before sizing",
    "LdP-DSR": "López de Prado & Bailey — Deflated Sharpe Ratio; correct for selection bias under multiple testing",
    # timing / structure
    "THETA-CURVE": "Theta decay non-linear; 7–21 DTE window sits in the steepening part of the curve",
    "CAL-SPREAD": "Pre-earnings IV term structure typically backwardated; calendar spread captures crush w/o full VRP drag",
    # regime / Renaissance lineage
    "HAM89": "Hamilton (1989) — canonical regime-switching / HMM; same family as our CUSUM",
    "BER91": "Berlekamp at Medallion (1989–1990, via Zuckerman 2019) — Kelly-style sizing on aggregated signals",
    "ZUC19": "Zuckerman (2019) — secondary source for Renaissance culture; numbers labelled [gray] unless replicated",
    # PEAD
    "BB68": "Ball & Brown (1968) — original post-earnings announcement drift",
    "BT89": "Bernard & Thomas (1989) — PEAD persists 60+ trading days; outside our 7–21 DTE window",
    # master-trader principles (see docs/MASTER_TRADERS.md)
    "PTJ-MW89": "Tudor Jones in Market Wizards (Schwager 1989) — defense > offense; aim for 5:1 R:R so a 20% hit ratio still pays",
    "TALEB-AF12": "Taleb, Antifragile (2012) — barbell payoff structure; long convexity > picking pennies in front of the steamroller",
    "TALEB-SITG18": "Taleb, Skin in the Game (2018) — ergodicity; a sequence of +EV bets with non-zero ruin probability is a negative time-average",
    "MARKS-MIC18": "Marks, Mastering the Market Cycle (2018) — pendulum cycles; 'what the wise man does in the beginning, the fool does in the end'",
    "KLARMAN-MOS91": "Klarman, Margin of Safety (1991) — cash is a position; abstain when nothing meets the bar",
    "DRUCK-MW12": "Druckenmiller in Hedge Fund Market Wizards (Schwager 2012) — concentration on highest conviction; preservation of capital + home runs",
    "MUNGER-PCA05": "Munger, Poor Charlie's Almanack (Kaufman ed., 2005) — invert always invert; mandatory bear is the desk's daily inversion",
    "BUFFETT-BRK": "Buffett, Berkshire Hathaway letters — circle of competence; risk comes from not knowing what you're doing",
    "TURTLE-D83": "Dennis, Turtle training material (1983; Faith 2007) — system discipline beats discretionary willpower; pre-commit exits",
    # Phase A — post-trade learning (see docs/PERFORMANCE_ATTRIBUTION.md)
    "BHB-1986": "Brinson, Hood & Beebower (1986) — allocation vs selection attribution; Eckhardt comfortable-win flag",
    "ECKHARDT-MW93": "Eckhardt in The New Market Wizards (Schwager 1993) — comfortable wins are the wrong lesson; markets do not pay for what is hard",
    "ROLL-1984": "Roll (1984) — effective-spread proxy; the realised cost of a fill is bigger than the quoted spread",
    "HASBROUCK-1991": "Hasbrouck (1991) — adverse selection decomposition; spread tax compounds across the slate",
    "ALMGREN-CHRISS-2000": "Almgren & Chriss (2000) — optimal-execution framing; for retail size, temporary cost dominates",
    "MCLEAN-PONTIFF-2016": "McLean & Pontiff (2016) — post-publication factor decay; rule-edge half-life is real",
    "ADAMS-MACKAY-2007": "Adams & MacKay (2007) — Bayesian online change-point detection; cleaner than CUSUM for rule decay",
    # Phase B — portfolio construction (see docs/PORTFOLIO_CONSTRUCTION.md)
    "MARKOWITZ-1952": "Markowitz (1952) — portfolio variance with correlation cross-term; correlated positions do not diversify",
    "DALIO-HOLY-GRAIL": "Dalio Holy Grail — 15 uncorrelated streams ≈ 4× Sharpe; the effective bet count is the honest count, not the headcount",
    "GRINOLD-1989": "Grinold (1989) — Fundamental Law: IR ≈ IC · √Breadth; breadth must be *independent* bets",
    "YOUNG-1991": "Young (1991) — Calmar ratio; drawdown management is a pre-commit conversation",
    "MARTIN-1989": "Martin (1989) — Ulcer Index; depth × duration of drawdown is what stresses the operator",
    # Phase C — consensus / crowdedness (see docs/CONSENSUS_AND_CROWDEDNESS.md)
    "STEIN-2009": "Stein (2009) — limits of arbitrage when crowded; the trade smart money agrees with is the trade to size smaller",
    "LOU-POLK-2013": "Lou & Polk (2013) — comomentum; rising within-family correlation is a crowdedness warning, not a strength tell",
    "BRUNNERMEIER-NAGEL-2004": "Brunnermeier & Nagel (2004) — riding the bubble; crowdedness can persist before reversing, so pre-commit the exit",
    "KHANDANI-LO-2007": "Khandani & Lo (2007) — August 2007 quant unwind; positions sized so they don't need exit at adverse moments are the only ones worth holding",
}


# ───────────────────────── helpers ─────────────────────────────────────


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _cite(tag: str) -> str:
    """Return a compact ``[TAG: short blurb]`` string for inline use."""
    blurb = CITES.get(tag, "")
    return f"[{tag}]" if not blurb else f"[{tag}: {blurb.split(' — ', 1)[1] if ' — ' in blurb else blurb}]"


def _load_artifact(path) -> dict[str, Any]:
    return load_json_file(path) or {}


def _brief_index(briefs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(b.get("ticker") or "").upper(): b
        for b in briefs.get("briefs") or []
        if b.get("ticker")
    }


# ───────────────────────── rule set: bull, bear, disagreement ──────────


def _collect_bull(ticket: dict[str, Any], brief: dict[str, Any]) -> list[str]:
    """Return the math case *for* taking this trade.

    Each bullet is one assertion plus the number that supports it plus a
    citation tag where one exists. Never inferred from gut — always from
    an explicit input.
    """
    bull: list[str] = []
    readiness = _safe_float(ticket.get("readiness"))
    confidence = _safe_float(ticket.get("confidence"))
    dte = _safe_float(ticket.get("dte"))
    tracker = brief.get("tracker") or {}
    edge = brief.get("edge") or {}
    iv_rank = _safe_float(tracker.get("ivRank"))
    # Use the actual chosen structure from the briefing/sizing path, not the
    # tracker's first recommendation — they can disagree (the tracker may
    # suggest STRADDLE while the briefing chooses a Vertical Call for the
    # same name). The conviction audit must reason about what the trade IS,
    # not what the tracker would have proposed in isolation.
    rec1 = (ticket.get("structure") or tracker.get("rec1") or "")

    if readiness is not None and readiness >= READINESS_GATE:
        bull.append(
            f"readiness {readiness:.0f} ≥ gate {READINESS_GATE} (MATH §18 paper-bootstrap gate)"
        )
    if confidence is not None and confidence >= 2:
        bull.append(f"confidence rung {confidence:.0f} ≥ 2 (tracker conviction floor)")
    if dte is not None and 0 < dte <= DTE_GATE:
        bull.append(
            f"DTE {dte:.0f} within convexity window (≤ {DTE_GATE}); pre-earnings IV ramp is the structural reason {_cite('PW79')}"
        )
    if iv_rank is not None and iv_rank >= IV_RANK_RICH and ("STRADDLE" not in rec1.upper()):
        bull.append(
            f"IV rank {iv_rank:.0f} ≥ {IV_RANK_RICH}; rich vol *helps* short-premium / spread structures {_cite('VRP-BK03')}"
        )
    if iv_rank is not None and iv_rank <= IV_RANK_CHEAP and ("STRADDLE" in rec1.upper() or "STRANGLE" in rec1.upper()):
        bull.append(
            f"IV rank {iv_rank:.0f} ≤ {IV_RANK_CHEAP}; cheap vol *helps* long-premium structures (breakeven move is narrower)"
        )
    edge_score = _safe_float(edge.get("edgeScore"))
    if edge_score is not None and edge_score >= 70 and edge.get("lane") != "Ignore For Theme":
        bull.append(
            f"edge research score {edge_score:.1f} with lane '{edge.get('lane')}' — name has a thesis the slate already endorses"
        )
    trend = tracker.get("trend") or ""
    if trend == "Bullish" and ("CALL" in rec1.upper() or "VERTICAL" in rec1.upper()):
        bull.append("trend = Bullish and proposed structure has positive delta — directional alignment")

    if not bull:
        bull.append("no quantitative bull point survived the rule set — this is a soft setup")
    return bull


def _collect_bear(ticket: dict[str, Any], brief: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    """Return the strongest available counter-argument.

    The auditor is required to produce *at least one* bear point. If no
    rule fires, the auditor inserts the state-of-evidence bear (zero
    closed samples = prior-only). The point: never present a setup as
    fully clean. Conviction must survive a real counter.
    """
    bear: list[str] = []
    tracker = brief.get("tracker") or {}
    edge = brief.get("edge") or {}
    exposure = brief.get("exposure") or {}
    iv_rank = _safe_float(tracker.get("ivRank"))
    # See _collect_bull for why we prefer the ticket's chosen structure.
    rec1 = (ticket.get("structure") or tracker.get("rec1") or "").upper()
    to_resistance = _safe_float(tracker.get("distanceToResistancePct"))
    to_support = _safe_float(tracker.get("distanceToSupportPct"))
    rvol = _safe_float(tracker.get("rvol"))
    trend = tracker.get("trend") or ""

    # Variance risk premium drag on long vol
    if "STRADDLE" in rec1 or "STRANGLE" in rec1:
        bear.append(
            f"long vol fights the variance risk premium {_cite('VRP-BK03')}; "
            f"expected-value drag is structural, not idiosyncratic — and the premium is heaviest "
            f"cross-sectionally on the index, real but smaller / noisier on single names {_cite('BTZ09')}"
        )
        bear.append(
            f"earnings straddles average negative cross-sectionally {_cite('ANDR18')}; "
            f"the win comes from a small minority where realised > implied — "
            f"CBOE 10-yr S&P sample puts that minority at ~28% of events {_cite('CBOE-72')}"
        )

    # Theta acceleration bear — applies to any long-premium structure in the 7-21 DTE window
    dte = _safe_float(ticket.get("dte")) or 0
    if ("STRADDLE" in rec1 or "STRANGLE" in rec1 or "CALL" in rec1 or "PUT" in rec1) and 0 < dte <= 30:
        bear.append(
            f"DTE {dte:.0f} sits inside the non-linear theta acceleration window — "
            f"daily theta drag is roughly 3-5× the 60-DTE rate and accelerates further into the final week {_cite('THETA-CURVE')}"
        )

    # IV crush risk
    if iv_rank is not None and iv_rank >= IV_RANK_RICH and ("STRADDLE" in rec1 or "STRANGLE" in rec1):
        bear.append(
            f"IV rank {iv_rank:.0f} is rich; post-event IV crush is the modal outcome {_cite('DIAV12')} "
            f"— need realised move > implied move to break even"
        )

    # Level adjacency
    if to_resistance is not None and to_resistance < NEAR_LEVEL_PCT and ("CALL" in rec1 or "VERTICAL" in rec1):
        bear.append(
            f"distance-to-resistance {to_resistance:.2f}% < {NEAR_LEVEL_PCT}%; "
            f"directional upside has nearby overhead supply"
        )
    if to_support is not None and to_support < NEAR_LEVEL_PCT and "PUT" in rec1:
        bear.append(
            f"distance-to-support {to_support:.2f}% < {NEAR_LEVEL_PCT}%; "
            f"directional downside has nearby bid"
        )

    # Concentration
    largest_sector = exposure.get("largestSector")
    largest_share = _safe_float(exposure.get("largestSectorShare")) or 0
    ticket_sector = edge.get("sector") or tracker.get("sector")
    if largest_sector and largest_share >= SECTOR_CONCENTRATION_LIMIT and ticket_sector == largest_sector:
        bear.append(
            f"slate already {largest_share*100:.0f}% in {largest_sector} and this is also "
            f"{largest_sector}; concentration governor will demote or shrink"
        )
    setup_shares = exposure.get("setupShares") or {}
    setup_label = _structure_label_from_rec(rec1)
    same_setup_share = _safe_float(setup_shares.get(setup_label)) or 0
    if same_setup_share >= SETUP_CONCENTRATION_LIMIT:
        bear.append(
            f"setup '{setup_label}' already {same_setup_share*100:.0f}% of the slate; "
            f"the same structural risk is already loaded"
        )

    # Edge research orthogonal to thesis
    if (edge.get("category") == "Unclassified") or (edge.get("lane") == "Ignore For Theme"):
        bear.append(
            f"edge research could not classify this name into the current theme — "
            f"the tracker is loud but the thematic case is silent"
        )

    # Low participation
    if rvol is not None and rvol < LOW_RVOL_FLOOR:
        bear.append(
            f"relative-volume {rvol:.2f} below {LOW_RVOL_FLOOR}; "
            f"limited intra-day participation makes fills and exits worse"
        )

    # Vol direction mismatch
    if trend == "Bullish" and ("STRADDLE" in rec1) and iv_rank is not None and iv_rank < 40:
        bear.append(
            "directional bias (Bullish) paired with delta-neutral straddle at sub-40 IV rank — "
            "if you're directional, a vertical is cheaper exposure to the same view"
        )

    # State of evidence: this is the dominant bear right now
    evidence_samples = _safe_float(
        (evidence.get("totalSamples")
         if isinstance(evidence, dict) else None)
    ) or 0
    if evidence_samples < EVIDENCE_PRIOR_ONLY_SAMPLES:
        bear.append(
            f"desk has only {evidence_samples:.0f} closed paper samples (gate is "
            f"{EVIDENCE_PRIOR_ONLY_SAMPLES}); every conviction here is **prior-only**, "
            f"not posterior {_cite('WIL27')} {_cite('ET93')}"
        )

    # Tudor Jones — reward:risk floor. See docs/MASTER_TRADERS.md §9.
    # Below 1.5x, the operator needs a > 60% hit ratio to be net positive;
    # below 1.0x, they need a > 50% hit ratio AND the math is asymmetric
    # against them on every loss. Both are bears.
    rr = _rr_ratio(ticket)
    if rr is not None:
        if rr < RR_BEAR_FLOOR:
            bear.append(
                f"reward:risk ratio {rr:.2f} below floor {RR_BEAR_FLOOR:.2f}; "
                f"a {RR_BEAR_FLOOR:.2f}x setup needs a > {100*(1/(1+RR_BEAR_FLOOR)):.0f}% "
                f"hit ratio to be net positive — Tudor Jones aimed for 5:1 so a 20% "
                f"hit ratio still paid {_cite('PTJ-MW89')}"
            )

    # Taleb — convexity / concavity tag. See docs/MASTER_TRADERS.md §5.
    # Concave structures (credit spreads, condors, flies) collect bounded
    # premium against unbounded-direction risk — Taleb's "picking pennies
    # in front of the steamroller" pattern. They aren't blocked; they get
    # a named bullet so the operator decides with eyes open.
    convexity = _convexity_tag(rec1)
    if convexity == "concave":
        bear.append(
            f"structure '{rec1.title()}' is concave: capped credit on the upside, "
            f"tail risk on the downside — Taleb's picking-pennies-in-front-of-the-"
            f"steamroller payoff {_cite('TALEB-AF12')}. The desk's default is "
            f"convex (defined max loss + open right tail); deviating from that "
            f"orientation should be an explicit choice, not a default."
        )

    # Marks — cycle-stage bear when buying premium at the top of the IV
    # pendulum. See docs/MASTER_TRADERS.md §4. We already fire an IV-crush
    # bear at IV_RANK_RICH; this adds the cycle-stage framing alongside
    # so the operator sees the pendulum metaphor, not just the number.
    if iv_rank is not None and iv_rank >= IV_RANK_RICH and _is_long_premium(rec1):
        bear.append(
            f"IV rank {iv_rank:.0f} places us in the top quartile of the vol "
            f"pendulum and the desk is buying premium — 'what the wise man does "
            f"in the beginning, the fool does in the end' {_cite('MARKS-MIC18')}; "
            f"the early money is already paid, we are not it"
        )

    if not bear:
        bear.append(
            "no rule-based bear fired; this is *not* the same as 'safe' — it means "
            "the auditor failed to imagine the bear and the operator must construct one"
        )
    return bear


# ───────────────────────── master-trader rule helpers ─────────────────


def _convexity_tag(structure_upper: str) -> str:
    """Classify a structure as convex / concave / banned.

    See docs/MASTER_TRADERS.md §5 (Taleb). The desk prefers convex
    payoffs (defined max loss + open or asymmetric right tail) and
    flags concave payoffs (capped credit with tail exposure) for
    operator attention. Banned structures are already hard-blocked by
    inferno_blowup_guardrails G1; this helper labels them anyway so the
    audit speaks the same vocabulary as the guardrails.
    """
    s = (structure_upper or "").upper()
    # Banned — undefined-loss patterns (already enforced by G1)
    if any(p in s for p in (
        "NAKED CALL", "NAKED PUT", "SHORT STRADDLE", "SHORT STRANGLE",
        "SHORT CALL", "SHORT PUT", "UNCOVERED",
    )):
        return "banned"
    # Concave — capped credit + tail risk
    if any(p in s for p in (
        "IRON CONDOR", "CONDOR", "BUTTERFLY", "FLY",
        "CREDIT SPREAD", "CREDIT VERTICAL", "COVERED CALL",
    )):
        return "concave"
    # Default: convex — long call, long put, long straddle, long strangle,
    # debit vertical (the desk's default structure)
    return "convex"


def _rr_ratio(ticket: dict[str, Any]) -> float | None:
    """Compute the reward:risk ratio for a ticket if both legs are known.

    Looks for explicit ``maxGain`` / ``maxLoss`` first (preferred); falls
    back to ``rewardRiskRatio`` if the briefing already computed it; and
    finally tries ``target`` / ``allocation`` as a last resort. Returns
    None when no usable inputs exist.
    """
    direct = _safe_float(ticket.get("rewardRiskRatio") or ticket.get("rrRatio"))
    if direct is not None and direct > 0:
        return direct
    max_gain = _safe_float(ticket.get("maxGain") or ticket.get("targetGain"))
    max_loss = _safe_float(ticket.get("maxLoss") or ticket.get("allocation"))
    if max_gain is not None and max_loss is not None and max_loss > 0:
        return max_gain / max_loss
    return None


def _is_long_premium(rec1_upper: str) -> bool:
    """True when the structure is buying option premium (long vol).

    A long vertical (debit) is treated as long-premium because the operator
    is paying for asymmetric exposure even if delta is partial. Calendar
    spreads and diagonal spreads sit on a boundary; we treat them as
    long-premium for the cycle-stage check because the long leg dominates
    the vega exposure in the 7-21 DTE window.
    """
    s = rec1_upper or ""
    if "CONDOR" in s or "BUTTERFLY" in s or "FLY" in s:
        return False
    if "CREDIT" in s:
        return False
    if any(p in s for p in ("STRADDLE", "STRANGLE", "DEBIT", "CALENDAR", "DIAGONAL")):
        return True
    # Plain "VERTICAL CALL" / "VERTICAL PUT" / "CALL" / "PUT" — assume long
    # premium unless explicitly marked as a credit structure.
    if any(p in s for p in ("VERTICAL", "CALL", "PUT")) and "SHORT" not in s:
        return True
    return False


def _structure_label_from_rec(rec1_upper: str) -> str:
    if "STRADDLE" in rec1_upper:
        return "Straddle"
    if "STRANGLE" in rec1_upper:
        return "Strangle"
    if "VERTICAL" in rec1_upper or "CALL" in rec1_upper:
        return "Vertical Call"
    if "PUT" in rec1_upper:
        return "Vertical Put"
    return rec1_upper.title() or "Unknown"


def _collect_disagreements(ticket: dict[str, Any], brief: dict[str, Any]) -> list[str]:
    """Surface places where two evidence layers point opposite ways.

    Disagreement is *the* signal the operator must consciously override.
    These rules are deliberately stark.
    """
    out: list[str] = []
    tracker = brief.get("tracker") or {}
    edge = brief.get("edge") or {}
    exposure = brief.get("exposure") or {}
    readiness = _safe_float(ticket.get("readiness")) or 0
    iv_rank = _safe_float(tracker.get("ivRank"))
    rec1 = (ticket.get("structure") or tracker.get("rec1") or "").upper()
    trend = tracker.get("trend") or ""

    # readiness loud, edge silent
    if readiness >= READINESS_HIGH_FLOOR and (edge.get("category") == "Unclassified" or edge.get("lane") == "Ignore For Theme"):
        out.append(
            f"tracker readiness {readiness:.0f} is loud, but edge research lane is "
            f"'{edge.get('lane')}' / category '{edge.get('category')}' — "
            f"gate-pass is statistical, thesis is missing"
        )

    # readiness loud, slate already heavy in this sector
    sector = edge.get("sector")
    largest_sector = exposure.get("largestSector")
    largest_share = _safe_float(exposure.get("largestSectorShare")) or 0
    if readiness >= READINESS_HIGH_FLOOR and sector == largest_sector and largest_share >= SECTOR_CONCENTRATION_LIMIT:
        out.append(
            f"tracker says high conviction but slate is {largest_share*100:.0f}% "
            f"{largest_sector}; conviction at the ticker level disagrees with conviction at the portfolio level"
        )

    # vol direction vs structure mismatch
    if trend == "Bullish" and "STRADDLE" in rec1:
        out.append(
            f"trend tag is Bullish but proposed structure is delta-neutral straddle — "
            f"directional view and chosen expression disagree"
        )

    # rich vol + long premium
    if iv_rank is not None and iv_rank >= IV_RANK_RICH and ("STRADDLE" in rec1 or "STRANGLE" in rec1):
        out.append(
            f"IV rank {iv_rank:.0f} (rich) but proposed structure buys vol — "
            f"the IV-rank module and the structure recommendation disagree on whether vol is the right side"
        )

    # Long premium AND IV term-structure backwardation → calendar spread is the typed alternative
    if "STRADDLE" in rec1 or "STRANGLE" in rec1:
        out.append(
            f"if the only goal is to capture the IV crush, a calendar spread (short front, long back) "
            f"captures the term-structure differential without taking the full long-premium VRP drag {_cite('CAL-SPREAD')} — "
            f"a long straddle is *not* the cheapest expression of a vol-crush view"
        )

    # cheap vol + short premium (the reverse mismatch)
    if iv_rank is not None and iv_rank <= IV_RANK_CHEAP and ("CONDOR" in rec1 or "FLY" in rec1 or "BUTTERFLY" in rec1):
        out.append(
            f"IV rank {iv_rank:.0f} (cheap) but proposed structure sells vol — "
            f"premium received does not compensate the tail risk at this IV-rank"
        )

    # Tudor Jones — R:R below 1.0x is an outright disagreement: the trade
    # asks the operator to take negative expectancy unless win-rate > 50%,
    # which by construction is *not* what readiness alone proves. See
    # docs/MASTER_TRADERS.md §9.
    rr = _rr_ratio(ticket)
    if rr is not None and rr < RR_DISAGREEMENT_FLOOR:
        out.append(
            f"reward:risk ratio {rr:.2f} below the {RR_DISAGREEMENT_FLOOR:.2f} "
            f"defense-floor — even a 50% hit ratio is barely break-even, and "
            f"readiness gates measure *setup quality*, not win-rate "
            f"{_cite('PTJ-MW89')}"
        )

    return out


def _falsification_triggers(ticket: dict[str, Any], brief: dict[str, Any]) -> list[str]:
    """Return pre-committed 'fold-if-X' clauses for this trade.

    These are *not* recommendations — they are pre-commitments the
    operator should adopt *before* sizing, so the exit is decided in
    cold blood, not under loss aversion.
    """
    tracker = brief.get("tracker") or {}
    rec1 = (ticket.get("structure") or tracker.get("rec1") or "").upper()
    dte = _safe_float(ticket.get("dte")) or 0
    iv_rank = _safe_float(tracker.get("ivRank"))

    triggers: list[str] = []

    # Universal triggers
    triggers.append(
        f"fold immediately if a closed-shadow falsification verdict on the active strategy "
        f"flips to 'edges-falsified' before the trade closes {_cite('PHIP10')}"
    )
    triggers.append(
        f"fold immediately if regime-drift CUSUM tags the active strategy as 'decaying' {_cite('PAGE54')}"
    )

    # Long-premium specific
    if "STRADDLE" in rec1 or "STRANGLE" in rec1:
        midpoint_dte = max(1, int(dte / 2))
        triggers.append(
            f"if neither leg has touched +0.3R by T-{midpoint_dte} (50% of DTE consumed), "
            f"exit — theta decay accelerates from here {_cite('BS73')}"
        )
        triggers.append(
            f"if realised move at earnings < 50% of the implied move "
            f"(ATM straddle price as %S) — exit; IV crush is winning the trade {_cite('DIAV12')}"
        )
        if iv_rank is not None and iv_rank >= IV_RANK_RICH:
            triggers.append(
                f"with IV rank already {iv_rank:.0f}: if IV rank prints another +10 by close before "
                f"earnings without underlying movement, the market is paying you to fade — re-evaluate "
                f"adding short-premium overlay, not adding length {_cite('VRP-BK03')}"
            )

    # Vertical-call specific
    if "VERTICAL" in rec1 or ("CALL" in rec1 and "STRADDLE" not in rec1):
        triggers.append(
            "if the underlying closes below the short strike's midpoint for two consecutive sessions, "
            "scale to half size (delta has rolled to the wrong side of the structure)"
        )

    # PEAD honesty: our window ends before PEAD plays out; do not extend into it
    triggers.append(
        f"do not roll a long-premium ticket past its planned exit into the multi-week PEAD horizon — "
        f"that is silently changing the bet from 'realised vs implied at the event' to "
        f"'post-earnings drift' and the desk has no edge in the drift window {_cite('BT89')}"
    )

    # Disposition-effect pre-commitment
    triggers.append(
        f"commit to every exit *before* sizing; do not re-decide an exit while watching live P/L — "
        f"the disposition effect makes that re-decision systematically worse {_cite('SS85')}"
    )

    # Sample-size honesty trigger
    triggers.append(
        "if any new ticket on the slate would push slate concentration above the configured "
        "sector or setup limit, demote this ticket *first* (it has the weakest disagreement profile)"
    )
    return triggers


def _state_of_evidence(evidence: dict[str, Any], devils: dict[str, Any]) -> list[str]:
    """Describe what the desk actually knows vs. what it is asserting."""
    out: list[str] = []
    samples = int(_safe_float(evidence.get("totalSamples")) or 0)
    verdict = evidence.get("verdict") or "no-evidence"
    da_verdict = devils.get("verdict") or "no-evidence"
    da_count = int(_safe_float(devils.get("strategyCount")) or 0)

    out.append(
        f"closed paper samples = {samples}; evidence-strength verdict = '{verdict}'"
    )
    if samples < EVIDENCE_PRIOR_ONLY_SAMPLES:
        out.append(
            f"below {EVIDENCE_PRIOR_ONLY_SAMPLES} closed samples — all readiness numbers are *prior beliefs* "
            f"derived from technicals and IV; they are not posterior win probabilities {_cite('WIL27')}"
        )
    out.append(
        f"devil's advocate verdict = '{da_verdict}' across {da_count} strategies — "
        f"falsification {('has no edges to attack' if da_count == 0 else 'is active')}"
    )
    # Multi-trial / overfitting honesty — relevant whenever the slate normalizer
    # has many cells, regardless of sample count
    out.append(
        f"the slate normalizer searches many cells; any apparent edge needs the multi-trial / "
        f"selection-bias correction {_cite('LdP-DSR')} before it can be called posterior"
    )
    # Sizing-under-uncertainty anchor — the quarter-Kelly cap is sourced, not asserted
    out.append(
        f"sizing is capped at quarter-Kelly because estimation error makes full-Kelly fragile — "
        f"half-Kelly captures ~75% of growth at ~half the drawdown {_cite('RT92')}, "
        f"and quarter-Kelly is the right band when win-rate and R are *both* still estimated"
    )
    return out


def _references_for(ticket: dict[str, Any], brief: dict[str, Any]) -> list[str]:
    refs = [
        "MATH §1 Wilson interval — win-rate floors",
        "MATH §2 percentile bootstrap CI — expectancy",
        "MATH §3 sign-flip bootstrap — falsification",
        "MATH §6 conservative Kelly — sizing",
        "MATH §11 Bayesian win-rate posterior — prior-vs-posterior framing",
        "MATH §12 CUSUM regime drift — falsification trigger",
        "MATH §14 Black-Scholes primitives — implied move math",
        "MATH §18 paper-bootstrap gate — the readiness floor",
        "MATH §19 slate normalizer — percentile-rank cross-check",
        "MATH §21 trade conviction audit — this module's method",
        "docs/MODEL_THEORY.md §Observe/Hypothesise/Prove/Promote — the gate is not the trade",
        "docs/THEORY_REFERENCES.md — citations behind every tag in this audit",
        "docs/SIMONS_PRINCIPLES.md — six Renaissance primitives mapped to safety rails",
        "docs/RESEARCH_NOTES.md — running research notebook with operational consequences",
        "inferno_evidence_strength.py — the four-component composite scalar",
        "inferno_devils_advocate.py — sign-flip falsification engine",
        "inferno_vol_premium.py — direction × IV-bucket discriminator",
        "inferno_regime_drift.py — CUSUM tagging (same family as Renaissance's HMM regime detection)",
        "docs/MASTER_TRADERS.md — Druckenmiller, Soros, Dalio, Marks, Taleb, Munger, Klarman, Buffett/Graham, Tudor Jones, Turtles; principles → rules",
    ]
    return refs


def _collect_blowup_risks(ticket: dict[str, Any], brief: dict[str, Any]) -> list[str]:
    """Return the blow-up patterns this ticket would create *if* it were
    oversized or stacked. Diagnostic only — the actual blocking happens
    in inferno_blowup_guardrails. The audit's job here is to make the
    historical reason audible per trade.

    Every bullet maps to a case study in docs/BLOWUP_CASE_STUDIES.md.
    """
    out: list[str] = []
    tracker = brief.get("tracker") or {}
    edge = brief.get("edge") or {}
    exposure = brief.get("exposure") or {}
    structure = (ticket.get("structure") or "").upper()
    iv_rank = _safe_float(tracker.get("ivRank"))
    largest_share = _safe_float(exposure.get("largestSectorShare")) or 0
    largest_sector = exposure.get("largestSector")
    ticker_sector = edge.get("sector")

    # Always-loud: defined max loss check
    undefined = any(p in structure for p in (
        "NAKED CALL", "NAKED PUT", "SHORT STRADDLE", "SHORT STRANGLE",
        "SHORT CALL", "SHORT PUT", "UNCOVERED",
    ))
    if undefined:
        out.append(
            f"**HARD BLOCK** — structure '{structure}' is undefined-loss; "
            f"matches Niederhoffer 1997 and Cordier 2018 — no naked short premium, ever"
        )

    # Concentration that maps to LTCM / Hwang
    if largest_share >= 0.50 and ticker_sector == largest_sector:
        out.append(
            f"adding this ticket pushes slate concentration in {largest_sector} above "
            f"the {int(largest_share*100)}% mark; correlated blow-up shape (LTCM 1998, Hwang 2021) — "
            f"diversification is the cheap defense"
        )

    # Rich IV + buying premium = the wrong side of VRP in the wrong DTE window
    if iv_rank is not None and iv_rank >= 80 and ("STRADDLE" in structure or "STRANGLE" in structure):
        out.append(
            f"buying rich IV ({iv_rank:.0f}) on a long-premium structure is the same shape that "
            f"caught operators when vol mean-reverts faster than the underlying moves — "
            f"if you must own this view, calendar spread is cheaper exposure"
        )

    # Disposition-roll antipattern reminder
    if ("STRADDLE" in structure or "STRANGLE" in structure or "CALL" in structure or "PUT" in structure):
        out.append(
            "if this ticket loses, *close* it; do not roll it forward to avoid realising the loss "
            "(Karen Bruton 2014-2016 — the disposition-effect antipattern is one of the most common operator killers)"
        )

    # Sizing self-check
    allocation = _safe_float(ticket.get("allocation")) or 0
    if allocation > 0:
        # rough self-check; the real check is in inferno_blowup_guardrails
        out.append(
            f"per-ticket risk ${allocation:.2f} must remain ≤ quarter-Kelly of bankroll — "
            f"over-betting Kelly is asymmetrically punishing (negative long-run growth above 2× optimal) "
            f"[KEL56] [RT92]"
        )

    return out


def _ticket_family(structure: str) -> str:
    """Map a ticket's structure string to the Phase A/B family taxonomy.

    Mirrors the buckets in inferno_outcome_attribution and
    inferno_portfolio_correlation so cross-module references line up.
    """
    name = (structure or "").strip().lower().replace("_", " ")
    if not name:
        return "Unknown"
    if "straddle" in name:
        return "Long Straddle"
    if "strangle" in name:
        return "Long Strangle"
    if "iron condor" in name:
        return "Iron Condor"
    if "butterfly" in name:
        return "Butterfly"
    if "calendar" in name or "diagonal" in name:
        return "Calendar / Diagonal"
    if "credit" in name:
        return "Credit Spread"
    if "debit" in name or ("vertical" in name and "call" in name) or ("vertical" in name and "put" in name):
        return "Vertical Debit"
    if "vertical" in name:
        return "Vertical"
    return "Unknown"


def _ticket_direction(structure: str) -> str:
    """Map structure to the Phase C direction taxonomy."""
    family = _ticket_family(structure)
    if family in {"Long Straddle", "Long Strangle", "Calendar / Diagonal"}:
        return "long-vol"
    if family in {"Iron Condor", "Credit Spread"}:
        return "short-vol"
    if family in {"Vertical Debit", "Vertical"}:
        return "long-equity"
    if family == "Butterfly":
        return "neutral"
    return "unknown"


def _collect_phase_signals(
    ticket: dict[str, Any],
    *,
    phase: dict[str, Any],
) -> dict[str, list[str]]:
    """Produce Phase A/B/C bullets for one ticket.

    ``phase`` is a dict with optional keys ``outcomeAttribution``,
    ``ruleEdgeDecay``, ``slippage``, ``correlation``, ``drawdown``,
    ``consensus``. Each missing or empty artifact silently produces no
    bullets — the wiring is purely additive.

    Returns ``{"bear": [...], "disagreements": [...]}``. Sizing-flavor
    signals (drawdown advisory) become disagreements; thesis-flavor
    signals become bear bullets. Both keep their citation tags inline.
    """
    bear: list[str] = []
    disagreements: list[str] = []

    structure = str(ticket.get("structure") or "")
    family = _ticket_family(structure)
    direction = _ticket_direction(structure)

    # ── Phase A — outcome attribution: Eckhardt comfortable-win flag ──
    attribution = phase.get("outcomeAttribution") or {}
    comfortable_wins = attribution.get("comfortableWins") or []
    if comfortable_wins:
        # If any prior comfortable-win was in this same family, surface it.
        fam_hits = [
            f for f in comfortable_wins
            if str(f.get("family") or "") == family
        ]
        if fam_hits:
            bear.append(
                f"prior closed evidence flagged {len(fam_hits)} comfortable-win "
                f"trade(s) in the {family} family — winners that sat in the "
                f"slate's dominant family at high readiness. The Eckhardt rule "
                f"says the comfortable trade is usually the wrong lesson; the "
                f"bull case must stand without the consensus tailwind "
                f"{_cite('ECKHARDT-MW93')} {_cite('BHB-1986')}"
            )

    # ── Phase A — rule edge decay: any rule cited by this audit decayed? ──
    decay = phase.get("ruleEdgeDecay") or {}
    retire_candidates = decay.get("retireCandidates") or []
    if retire_candidates:
        # v1: simply name retire candidates the operator should know about.
        # A future iteration can cross-check the actual citation tags that
        # this audit will fire on this ticket.
        tag_list = ", ".join(
            f"{r.get('tag')} ({r.get('side')}, Wilson L {r.get('wilsonLower')})"
            for r in retire_candidates[:3]
        )
        bear.append(
            f"rule-edge decay flagged retire candidate(s) in closed evidence: "
            f"{tag_list}. Wilson lower bound on per-rule hit rate < 0.50 means "
            f"the rule is not statistically better than a coin flip on the "
            f"available sample {_cite('MCLEAN-PONTIFF-2016')} "
            f"{_cite('ADAMS-MACKAY-2007')}"
        )

    # ── Phase A — limit-pricing cushion + quoted spread for this family ──
    slippage = phase.get("slippage") or {}
    family_anchors = (slippage.get("familyAnchors") or {})
    anchor = family_anchors.get(family) or {}
    med_cushion = _safe_float(anchor.get("medianLimitCushionPct"))
    med_spread = _safe_float(anchor.get("medianAvgLegSpreadPct"))
    if anchor.get("verdict") == "anchored" and med_cushion is not None and med_cushion >= 0.10:
        bear.append(
            f"family anchor for {family}: median quoted-leg spread "
            f"{med_spread * 100:.1f}% (Roll-1984 effective spread proxy) "
            f"and median limit-pricing cushion {med_cushion * 100:.1f}% "
            f"across {anchor.get('ticketCount')} prior tickets. The cushion "
            f"is the strike selector's worst-case-fill conservatism — limit "
            f"orders in this family expect to cross the spread on every leg. "
            f"Check whether the thesis still clears its R:R when the fill "
            f"happens at limit rather than mid {_cite('ROLL-1984')}"
        )

    # ── Phase B — portfolio correlation: am I adding to the dominant family? ──
    correlation = phase.get("correlation") or {}
    slate_conc = correlation.get("slateConcentration") or {}
    by_family = slate_conc.get("byFamily") or {}
    headcount = int(slate_conc.get("headcount") or 0)
    eff_bet = _safe_float(slate_conc.get("effectiveBetCount")) or 0.0
    if headcount > 0:
        family_share = (by_family.get(family) or 0) / headcount
        if family_share >= 0.40:
            bear.append(
                f"slate is already {family_share * 100:.0f}% in {family} "
                f"({by_family.get(family)}/{headcount} tickets); effective bet "
                f"count is {eff_bet:.1f}. Adding this ticket grows correlated "
                f"exposure — fifteen well-researched theses do not constitute "
                f"fifteen bets {_cite('MARKOWITZ-1952')} "
                f"{_cite('DALIO-HOLY-GRAIL')} {_cite('GRINOLD-1989')}"
            )

    # ── Phase B — drawdown protocol: sizing-advisory ≠ normal ──
    drawdown = phase.get("drawdown") or {}
    sizing = drawdown.get("sizingAdvisory") or {}
    regime = str(sizing.get("regime") or "")
    multiplier = _safe_float(sizing.get("multiplier"))
    current_dd = _safe_float((drawdown.get("metrics") or {}).get("currentDrawdown"))
    if regime and regime not in {"normal", ""} and multiplier is not None:
        disagreements.append(
            f"drawdown protocol regime '{regime}' (current DD "
            f"{(current_dd or 0) * 100:.1f}%): pre-committed sizing multiplier "
            f"is {multiplier}. This is a sizing disagreement, not a thesis "
            f"disagreement — the trade may be right while the size must be cut "
            f"{_cite('YOUNG-1991')} {_cite('MARTIN-1989')}"
        )

    # ── Phase C — consensus / crowdedness ──
    consensus = phase.get("consensus") or {}
    verdict = str(consensus.get("verdict") or "")
    signals = consensus.get("signals") or []
    own_side = next(
        (s for s in signals if str(s.get("signal")) == "own-side-concentration"),
        {},
    )
    dominant_direction = str(own_side.get("dominantDirection") or "")
    if verdict in {"crowded-watch", "consensus-extreme"}:
        same_direction = dominant_direction == direction and dominant_direction != ""
        bear.append(
            f"consensus monitor verdict '{verdict}'"
            + (
                f" with own-side concentration in {dominant_direction} "
                f"(this ticket is {direction}, " + ("same direction)" if same_direction else "different direction)")
                if dominant_direction
                else ""
            )
            + f". Crowdedness predicts exit liquidity, not direction — "
            f"the trade where smart money agrees with you is the trade to "
            f"size smaller, not larger {_cite('STEIN-2009')} "
            f"{_cite('LOU-POLK-2013')} {_cite('KHANDANI-LO-2007')}"
        )

    return {"bear": bear, "disagreements": disagreements}


def _audit_ticket(
    ticket: dict[str, Any],
    *,
    brief: dict[str, Any],
    evidence: dict[str, Any],
    devils: dict[str, Any],
    phase: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce one ticket's audit block."""
    bull = _collect_bull(ticket, brief)
    bear = _collect_bear(ticket, brief, evidence)
    disagreements = _collect_disagreements(ticket, brief)
    triggers = _falsification_triggers(ticket, brief)
    soe = _state_of_evidence(evidence, devils)
    blowup_risks = _collect_blowup_risks(ticket, brief)

    # Additive Phase A/B/C signals. Missing artifacts produce no bullets,
    # so legacy callers and tests continue to see the same output.
    phase_bullets = _collect_phase_signals(ticket, phase=phase or {})
    bear = bear + phase_bullets["bear"]
    disagreements = disagreements + phase_bullets["disagreements"]

    # Conviction tag: passes gates, but math case is honest
    if disagreements or len(bear) > len(bull):
        conviction = "mixed"
    elif not bull or bull == ["no quantitative bull point survived the rule set — this is a soft setup"]:
        conviction = "weak"
    else:
        conviction = "supportable"

    return {
        "ticker": ticket.get("ticker"),
        "structure": ticket.get("structure"),
        "claim": (
            f"Open {ticket.get('structure')} on {ticket.get('ticker')} at "
            f"${ticket.get('allocation'):,.2f} risk; readiness {ticket.get('readiness')}, "
            f"confidence {ticket.get('confidence')}, DTE {ticket.get('dte')}."
        ),
        "priors": {
            "readiness": ticket.get("readiness"),
            "confidence": ticket.get("confidence"),
            "dte": ticket.get("dte"),
            "ivRank": (brief.get("tracker") or {}).get("ivRank"),
            "atrPercent": (brief.get("tracker") or {}).get("atrPercent"),
            "trend": (brief.get("tracker") or {}).get("trend"),
            "sector": (brief.get("edge") or {}).get("sector"),
            "edgeCategory": (brief.get("edge") or {}).get("category"),
            "edgeLane": (brief.get("edge") or {}).get("lane"),
        },
        "convictionTag": conviction,
        "bull": bull,
        "bear": bear,
        "disagreements": disagreements,
        "falsificationTriggers": triggers,
        "stateOfEvidence": soe,
        "blowupRisks": blowup_risks,
    }


# ───────────────────────── orchestration ───────────────────────────────


def _briefing_tickets(briefing: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize operator-briefing tickets into a uniform shape.

    Accepts the live briefing payload (``sizing.tickets``) and also the
    test-fixture shape (``candidates``) so tests can fabricate inputs
    without rebuilding a full briefing.
    """
    out = []
    raw_tickets = (
        ((briefing.get("sizing") or {}).get("tickets") or [])
        or (briefing.get("candidates") or [])
    )
    for cand in raw_tickets:
        if not cand:
            continue
        ticker = (cand.get("ticker") or "").upper()
        if not ticker:
            continue
        out.append({
            "ticker": ticker,
            "structure": cand.get("structure") or cand.get("setupRec") or cand.get("setup") or "",
            "allocation": (
                _safe_float(cand.get("allocation"))
                or _safe_float(cand.get("dollarAllocation"))
                or 0.0
            ),
            "readiness": _safe_float(cand.get("readiness")) or 0.0,
            "confidence": _safe_float(cand.get("confidence")) or 0.0,
            "dte": (
                _safe_float(cand.get("dte"))
                or _safe_float(cand.get("daysUntilEarnings"))
                or 0.0
            ),
            # R:R inputs for the PTJ rule. Carried through *as provided* —
            # absent values stay None so the rule simply doesn't fire.
            "maxGain": _safe_float(cand.get("maxGain") or cand.get("targetGain")),
            "maxLoss": _safe_float(cand.get("maxLoss")),
            "rewardRiskRatio": _safe_float(
                cand.get("rewardRiskRatio") or cand.get("rrRatio")
            ),
        })
    return out


def build_conviction_audit(
    *,
    briefing: dict[str, Any] | None = None,
    decision_briefs: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    devils: dict[str, Any] | None = None,
    vol_premium: dict[str, Any] | None = None,
    regime: dict[str, Any] | None = None,
    outcome_attribution: dict[str, Any] | None = None,
    rule_edge_decay: dict[str, Any] | None = None,
    slippage: dict[str, Any] | None = None,
    correlation: dict[str, Any] | None = None,
    drawdown: dict[str, Any] | None = None,
    consensus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the per-ticket conviction audit payload."""
    if briefing is None:
        # Briefing artifact is in-memory only; rebuild on demand. We import
        # locally to avoid a hard dependency cycle for tests that pass
        # ``briefing=...`` explicitly.
        try:
            from inferno_operator_briefing import build_briefing
            briefing = build_briefing()
        except Exception:
            briefing = _load_artifact(OPERATOR_BRIEFING_FILE)
    decision_briefs = decision_briefs if decision_briefs is not None else _load_artifact(DECISION_BRIEFS_FILE)
    evidence = evidence if evidence is not None else _load_artifact(EVIDENCE_STRENGTH_FILE)
    devils = devils if devils is not None else _load_artifact(DEVILS_ADVOCATE_FILE)
    vol_premium = vol_premium if vol_premium is not None else _load_artifact(VOL_PREMIUM_FILE)
    regime = regime if regime is not None else _load_artifact(REGIME_DRIFT_FILE)

    # Phase A/B/C signals — research-only, additive bullets only.
    outcome_attribution = (
        outcome_attribution if outcome_attribution is not None
        else _load_artifact(OUTCOME_ATTRIBUTION_FILE)
    )
    rule_edge_decay = (
        rule_edge_decay if rule_edge_decay is not None
        else _load_artifact(RULE_EDGE_DECAY_FILE)
    )
    slippage = slippage if slippage is not None else _load_artifact(SLIPPAGE_ESTIMATOR_FILE)
    correlation = (
        correlation if correlation is not None
        else _load_artifact(PORTFOLIO_CORRELATION_FILE)
    )
    drawdown = drawdown if drawdown is not None else _load_artifact(DRAWDOWN_PROTOCOL_FILE)
    consensus = consensus if consensus is not None else _load_artifact(CONSENSUS_MONITOR_FILE)
    phase_payload = {
        "outcomeAttribution": outcome_attribution,
        "ruleEdgeDecay": rule_edge_decay,
        "slippage": slippage,
        "correlation": correlation,
        "drawdown": drawdown,
        "consensus": consensus,
    }

    tickets = _briefing_tickets(briefing)
    by_ticker_brief = _brief_index(decision_briefs)

    audits = []
    for ticket in tickets:
        ticker = ticket["ticker"]
        brief = by_ticker_brief.get(ticker) or {}
        audits.append(_audit_ticket(
            ticket,
            brief=brief,
            evidence=evidence,
            devils=devils,
            phase=phase_payload,
        ))

    # Klarman — sit-out advisory. See docs/MASTER_TRADERS.md §7.
    # When no slate ticket meets a meaningful readiness threshold AND has
    # a classified edge, the audit recommends abstention. Cash is a
    # position; the desk should not talk itself into a marginal trade.
    sit_out_payload = _build_sit_out_advisory(audits, by_ticker_brief)

    reminders = [
        "diagnostic only; nothing here approves, rejects, or sizes a trade",
        "operator must read at least one bear point per ticket before sizing",
        "if the bull list is shorter than the bear list, the trade is *not* a yes",
        "below 30 closed paper samples, every readiness number is prior-only",
    ]
    if sit_out_payload["sitOut"]:
        reminders.insert(0, sit_out_payload["reminder"])

    return {
        "generatedAt": local_now().isoformat(),
        "stage": CONVICTION_AUDIT_STAGE,
        "diagnosticOnly": True,
        "researchOnly": True,
        "promotable": False,
        "briefingVerdict": briefing.get("verdict"),
        "briefingDate": briefing.get("date") or briefing.get("generatedAt"),
        "evidenceVerdict": evidence.get("verdict"),
        "devilsAdvocateVerdict": devils.get("verdict"),
        "volPremiumVerdict": vol_premium.get("verdict"),
        "regimeDriftVerdict": regime.get("verdict"),
        "outcomeAttributionVerdict": outcome_attribution.get("verdict"),
        "ruleEdgeDecayVerdict": rule_edge_decay.get("verdict"),
        "slippageVerdict": slippage.get("verdict"),
        "correlationVerdict": correlation.get("verdict"),
        "drawdownVerdict": drawdown.get("verdict"),
        "consensusVerdict": consensus.get("verdict"),
        "auditCount": len(audits),
        "audits": audits,
        "sitOutAdvisory": sit_out_payload,
        "references": _references_for({}, {}),
        "reminders": reminders,
    }


def _build_sit_out_advisory(
    audits: list[dict[str, Any]],
    briefs_by_ticker: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Klarman sit-out advisory: are any tickets actually worth the day?

    Returns a small payload the renderer surfaces to the operator. The
    rule is intentionally light — we only ask whether at least *one*
    ticket clears the readiness threshold *and* (optionally) has a
    classified edge. If not, the advisory fires.
    """
    if not audits:
        return {
            "sitOut": True,
            "reason": "no audited tickets in today's slate",
            "reminder": (
                "today is a sit-out day — no tickets to audit; cash is the position "
                f"{_cite('KLARMAN-MOS91')}"
            ),
            "qualifyingTickers": [],
            "floor": SIT_OUT_READINESS_FLOOR,
        }

    qualifying = []
    for audit in audits:
        readiness = _safe_float((audit.get("priors") or {}).get("readiness")) or 0
        if readiness < SIT_OUT_READINESS_FLOOR:
            continue
        brief = briefs_by_ticker.get(str(audit.get("ticker") or "").upper()) or {}
        edge = brief.get("edge") or {}
        if SIT_OUT_EDGE_REQUIRED:
            if (edge.get("category") in (None, "", "Unclassified")
                    or edge.get("lane") == "Ignore For Theme"):
                continue
        qualifying.append(audit.get("ticker"))

    if qualifying:
        return {
            "sitOut": False,
            "reason": (
                f"{len(qualifying)} ticket(s) clear readiness {SIT_OUT_READINESS_FLOOR} "
                f"with a classified edge"
            ),
            "reminder": None,
            "qualifyingTickers": qualifying,
            "floor": SIT_OUT_READINESS_FLOOR,
        }

    return {
        "sitOut": True,
        "reason": (
            f"no slate ticket clears readiness {SIT_OUT_READINESS_FLOOR} with a "
            f"classified edge"
        ),
        "reminder": (
            f"today is a sit-out day — no slate ticket clears readiness "
            f"{SIT_OUT_READINESS_FLOOR} with a classified edge; cash is the position "
            f"{_cite('KLARMAN-MOS91')}"
        ),
        "qualifyingTickers": [],
        "floor": SIT_OUT_READINESS_FLOOR,
    }


# ───────────────────────── rendering ───────────────────────────────────


def _bullets(prefix: str, items: Iterable[str]) -> list[str]:
    return [f"{prefix} {item}" for item in items]


def conviction_audit_text(report: dict[str, Any]) -> str:
    lines = [
        "Inferno Trade Conviction Audit (diagnostic-only)",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Stage: {report.get('stage')}",
        f"Briefing verdict: {report.get('briefingVerdict')}",
        f"Evidence strength verdict: {report.get('evidenceVerdict')}",
        f"Devil's advocate verdict: {report.get('devilsAdvocateVerdict')}",
        f"Vol premium verdict: {report.get('volPremiumVerdict')}",
        f"Regime drift verdict: {report.get('regimeDriftVerdict')}",
        f"Audited tickets: {report.get('auditCount', 0)}",
        "",
    ]

    sit_out = report.get("sitOutAdvisory") or {}
    if sit_out:
        verdict = "SIT OUT" if sit_out.get("sitOut") else "QUALIFIED"
        lines.append(f"SIT-OUT ADVISORY (Klarman): {verdict}")
        lines.append(f"  reason: {sit_out.get('reason')}")
        if sit_out.get("qualifyingTickers"):
            lines.append(
                f"  qualifying tickers: {', '.join(sit_out.get('qualifyingTickers') or [])}"
            )
        lines.append("")

    audits = report.get("audits") or []
    if not audits:
        lines.append("No ready-to-execute tickets on today's briefing — nothing to audit.")
        return "\n".join(lines).rstrip() + "\n"

    for audit in audits:
        lines.extend([
            f"=== {audit.get('ticker')}  ({audit.get('convictionTag')}) ===",
            f"Claim: {audit.get('claim')}",
            "",
            "BULL CASE:",
        ])
        lines.extend(_bullets("  + ", audit.get("bull") or []))
        lines.append("")
        lines.append("BEAR CASE:")
        lines.extend(_bullets("  - ", audit.get("bear") or []))
        lines.append("")
        lines.append("DISAGREEMENTS:")
        if not audit.get("disagreements"):
            lines.append("  · none surfaced by rule set — operator must still construct one before sizing")
        else:
            lines.extend(_bullets("  · ", audit.get("disagreements") or []))
        lines.append("")
        lines.append("FALSIFICATION TRIGGERS (pre-commit before sizing):")
        lines.extend(_bullets("  > ", audit.get("falsificationTriggers") or []))
        lines.append("")
        lines.append("STATE OF EVIDENCE:")
        lines.extend(_bullets("  · ", audit.get("stateOfEvidence") or []))
        lines.append("")
        lines.append("BLOW-UP RISKS (case-study-linked):")
        if not audit.get("blowupRisks"):
            lines.append("  ! no blow-up patterns surfaced; see reports/blowup_guardrails_latest.txt for the hard checks")
        else:
            lines.extend(_bullets("  ! ", audit.get("blowupRisks") or []))
        lines.append("")

    lines.append("REFERENCES:")
    lines.extend(_bullets("  · ", report.get("references") or []))
    lines.append("")
    lines.append("REMINDERS:")
    lines.extend(_bullets("  - ", report.get("reminders") or []))
    return "\n".join(lines).rstrip() + "\n"


# ───────────────────────── persistence ─────────────────────────────────


def save_conviction_audit(report: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(CONVICTION_AUDIT_FILE, report)
    atomic_write_text(CONVICTION_AUDIT_TEXT_FILE, conviction_audit_text(report))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Per-trade conviction auditor. Builds the math case for and "
            "against each ready-to-execute ticket on the briefing, with "
            "explicit disagreements and pre-committed falsification triggers. "
            "Research-only; cannot approve, reject, or size anything."
        )
    )
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and CONVICTION_AUDIT_TEXT_FILE.exists():
        print(CONVICTION_AUDIT_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = build_conviction_audit()
    save_conviction_audit(report)
    print(conviction_audit_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
