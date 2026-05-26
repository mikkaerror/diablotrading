from __future__ import annotations

"""Capital scaling recommender (research-only).

The desk's per-ticket dollar cap (``MAX_SINGLE_TICKET_DOLLARS``) is hand-
tuned in ``inferno_config.py``. That works at one account size and is
wrong at every other account size. This module replaces the hand-tune
with a percentage-of-NLV formula so the cap auto-tracks the live
account as it grows (or shrinks) without manual edits.

What it does:
  - Reads ``netLiquidatingValue`` from ``inferno_live_account_sync.json``.
  - Computes ``recommendedCap = clamp(NLV * pct_per_ticket, floor, ceiling)``.
  - Compares the recommendation to the cap currently enforced by the
    config layer and emits a verdict (``aligned`` / ``config-cap-too-high``
    / ``config-cap-too-low`` / ``nlv-stale`` / ``nlv-missing`` / ``ack-required``).
  - Persists the recommendation to ``data/inferno_capital_scaling.json``
    and a text summary to ``reports/capital_scaling_latest.txt``.
  - Maintains an "ack file" (``data/inferno_capital_scaling_ack.json``)
    that records the operator's accepted formula parameters. When the
    formula's recomputed cap stays within ack tolerance, callers can
    auto-apply. When it drifts beyond tolerance, fresh ack is required.

What it does NOT do:
  - Mutate ``inferno_config.py``. Constants stay declarative.
  - Touch ``liveTradingAllowed`` or ``brokerSubmitAllowed``. The safety
    perimeter in ``inferno_authority_controller.py`` continues to enforce
    those as hard-coded False.
  - Stage, approve, or submit any trade.

The intended caller is ``inferno_risk_policy.current_single_ticket_cap()``
which consults this module's artifact + ack file, with a safe fallback to
the env-var-derived constant if either is missing or stale.

Citations (light):
  - Kelly (1956) — the bet-fraction-of-bankroll framing.
  - Thorp (2006) — practical Kelly applied to options with caps + floors.
  - de Prado (2018) — risk-as-percent-of-equity is the only frame that
    survives compounding without manual rescaling.
"""

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from inferno_config import (
    MAX_DAILY_TICKET_DOLLARS,
    MAX_OPEN_PAPER_TICKETS,
    MAX_SINGLE_TICKET_DOLLARS,
    local_now,
)
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


# ─────────────────────────── files ────────────────────────────────────

LIVE_ACCOUNT_SYNC_FILE = DATA_DIR / "inferno_live_account_sync.json"
CAPITAL_SCALING_FILE = DATA_DIR / "inferno_capital_scaling.json"
CAPITAL_SCALING_TEXT_FILE = REPORTS_DIR / "capital_scaling_latest.txt"
CAPITAL_SCALING_ACK_FILE = DATA_DIR / "inferno_capital_scaling_ack.json"


# ─────────────────────────── formula parameters ───────────────────────

CAPITAL_SCALING_STAGE = "capital-scaling-research-only"

# Operator-chosen formula (recorded as the default; the ack file may
# override these if the operator runs `accept --pct 0.02` etc.).
DEFAULT_TARGET_PCT_PER_TICKET = 0.01    # 1% of NLV
DEFAULT_FLOOR_DOLLARS = 25.0            # below this, no options trade is structurally viable
DEFAULT_CEILING_DOLLARS = 2000.0        # hard ceiling regardless of NLV growth
DEFAULT_DAILY_TICKETS_RATIO = 3.0       # daily cap = 3 * single-ticket cap
DEFAULT_NLV_STALE_HOURS = 24            # NLV freshness window
DEFAULT_ACK_TOLERANCE_PCT = 0.20        # ack covers ±20% drift in computed cap
DEFAULT_DRAWDOWN_PAUSE_PCT = 0.25       # >25% drawdown from ack'd NLV triggers re-ack
DEFAULT_SCALING_BEHAVIOR = "symmetric-on-current-nlv"

# Tolerance bands for the verdict (config vs recommendation).
ALIGNED_BAND_PCT = 0.20  # within 20% counts as aligned


# ─────────────────────────── helpers ──────────────────────────────────


def _coerce_float(value: Any) -> float | None:
    """Best-effort parse of a numeric field; tolerates ``$1,108.08`` strings."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace("$", "").replace(",", "").strip()
        try:
            v = float(cleaned)
            return v if math.isfinite(v) else None
        except ValueError:
            return None
    return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    # Tolerate trailing tz like "+00:00", "-06:00", and bare ISO.
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _hours_since(ts: datetime | None, *, now: datetime) -> float | None:
    if ts is None:
        return None
    # Normalise both ends to aware UTC if possible.
    if ts.tzinfo is None and now.tzinfo is not None:
        ts = ts.replace(tzinfo=now.tzinfo)
    if now.tzinfo is None and ts.tzinfo is not None:
        now = now.replace(tzinfo=ts.tzinfo)
    delta = now - ts
    return round(delta.total_seconds() / 3600.0, 2)


# ─────────────────────────── inputs ───────────────────────────────────


@dataclass(frozen=True)
class ScalingInputs:
    """Pure-data view of every input that goes into the formula."""

    net_liquidating_value: float | None
    nlv_source_path: str
    nlv_generated_at: str | None
    nlv_age_hours: float | None
    target_pct_per_ticket: float
    floor_dollars: float
    ceiling_dollars: float
    daily_tickets_ratio: float
    scaling_behavior: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "netLiquidatingValue": self.net_liquidating_value,
            "nlvSource": self.nlv_source_path,
            "nlvGeneratedAt": self.nlv_generated_at,
            "nlvAgeHours": self.nlv_age_hours,
            "targetPctPerTicket": self.target_pct_per_ticket,
            "floorDollars": self.floor_dollars,
            "ceilingDollars": self.ceiling_dollars,
            "dailyTicketsRatio": self.daily_tickets_ratio,
            "scalingBehavior": self.scaling_behavior,
        }


def _read_live_account(now: datetime) -> tuple[float | None, str | None, float | None]:
    """Pull (NLV, generatedAt-iso, age-hours) from the live account sync."""
    payload = load_json_file(LIVE_ACCOUNT_SYNC_FILE) or {}
    nlv = _coerce_float(payload.get("netLiquidatingValue"))
    gen_iso = payload.get("generatedAt")
    gen_dt = _parse_iso_datetime(gen_iso)
    age_hours = _hours_since(gen_dt, now=now)
    return nlv, gen_iso, age_hours


def _read_ack() -> dict[str, Any] | None:
    """Read the ack file if it exists. Returns None when no ack has been recorded."""
    return load_json_file(CAPITAL_SCALING_ACK_FILE)


def _formula_params(ack: dict[str, Any] | None) -> dict[str, float | str]:
    """The ack file may override the default formula parameters."""
    if not isinstance(ack, dict):
        return {
            "targetPctPerTicket": DEFAULT_TARGET_PCT_PER_TICKET,
            "floorDollars": DEFAULT_FLOOR_DOLLARS,
            "ceilingDollars": DEFAULT_CEILING_DOLLARS,
            "dailyTicketsRatio": DEFAULT_DAILY_TICKETS_RATIO,
            "scalingBehavior": DEFAULT_SCALING_BEHAVIOR,
        }
    return {
        "targetPctPerTicket": float(ack.get("targetPctPerTicket", DEFAULT_TARGET_PCT_PER_TICKET)),
        "floorDollars": float(ack.get("floorDollars", DEFAULT_FLOOR_DOLLARS)),
        "ceilingDollars": float(ack.get("ceilingDollars", DEFAULT_CEILING_DOLLARS)),
        "dailyTicketsRatio": float(ack.get("dailyTicketsRatio", DEFAULT_DAILY_TICKETS_RATIO)),
        "scalingBehavior": str(ack.get("scalingBehavior", DEFAULT_SCALING_BEHAVIOR)),
    }


# ─────────────────────────── core formula ─────────────────────────────


def compute_recommended_cap(
    nlv: float | None,
    *,
    target_pct: float = DEFAULT_TARGET_PCT_PER_TICKET,
    floor: float = DEFAULT_FLOOR_DOLLARS,
    ceiling: float = DEFAULT_CEILING_DOLLARS,
) -> dict[str, Any]:
    """Pure function: turn an NLV reading into a recommended per-ticket cap.

    Returns a dict with:
      ``rawComputedCap``    NLV × target_pct (uncapped)
      ``recommendedCap``    rawComputedCap clamped to [floor, ceiling]
      ``effectivePctOfNLV`` recommendedCap / NLV (may exceed target_pct when floor binds)
      ``atFloor``           True if the recommendation is the floor
      ``atCeiling``         True if the recommendation is the ceiling
    """
    if nlv is None or nlv <= 0:
        return {
            "rawComputedCap": None,
            "recommendedCap": None,
            "effectivePctOfNLV": None,
            "atFloor": False,
            "atCeiling": False,
        }
    raw = nlv * float(target_pct)
    recommended = max(float(floor), min(float(ceiling), raw))
    effective_pct = recommended / nlv if nlv > 0 else None
    return {
        "rawComputedCap": round(raw, 2),
        "recommendedCap": round(recommended, 2),
        "effectivePctOfNLV": round(effective_pct, 4) if effective_pct is not None else None,
        "atFloor": math.isclose(recommended, float(floor), abs_tol=1e-6) and raw <= float(floor),
        "atCeiling": math.isclose(recommended, float(ceiling), abs_tol=1e-6) and raw >= float(ceiling),
    }


def _verdict_from_divergence(
    *,
    nlv: float | None,
    nlv_age_hours: float | None,
    nlv_stale_hours: float,
    recommended: float | None,
    config_cap: float,
    ack: dict[str, Any] | None,
) -> tuple[str, str]:
    """Return (verdict, human-readable explanation)."""
    if nlv is None:
        return (
            "nlv-missing",
            "No netLiquidatingValue in inferno_live_account_sync.json. "
            "Run the live account sync before relying on the recommendation.",
        )
    if nlv_age_hours is not None and nlv_age_hours > nlv_stale_hours:
        return (
            "nlv-stale",
            f"NLV reading is {nlv_age_hours:.1f}h old (stale threshold {nlv_stale_hours}h). "
            "Refresh the live account sync before relying on the recommendation.",
        )
    if recommended is None:
        return ("nlv-missing", "Recommendation could not be computed (no usable NLV).")
    if config_cap <= 0:
        return (
            "config-cap-missing",
            "MAX_SINGLE_TICKET_DOLLARS is missing or non-positive in inferno_config.",
        )
    ratio = config_cap / recommended if recommended > 0 else None
    if ratio is None or recommended <= 0:
        return ("aligned", "No comparison possible; recommendation is zero.")
    if abs(ratio - 1.0) <= ALIGNED_BAND_PCT:
        return (
            "aligned",
            f"Config cap ${config_cap:.2f} is within ±{ALIGNED_BAND_PCT*100:.0f}% of the "
            f"NLV-based recommendation ${recommended:.2f}.",
        )
    if ratio > 1.0:
        if ack is None:
            return (
                "ack-required",
                f"Config cap ${config_cap:.2f} is {ratio:.1f}× the NLV-based recommendation "
                f"${recommended:.2f}. Run `python3 inferno_capital_scaling.py accept` to "
                f"opt in to the formula, OR lower MAX_SINGLE_TICKET_DOLLARS to ~${recommended:.0f}.",
            )
        return (
            "config-cap-too-high",
            f"Config cap ${config_cap:.2f} is {ratio:.1f}× the NLV-based recommendation "
            f"${recommended:.2f}. The cap is over-budget for the current account size.",
        )
    # config_cap below recommendation
    inverse = recommended / config_cap if config_cap > 0 else None
    return (
        "config-cap-too-low",
        f"Config cap ${config_cap:.2f} is {inverse:.1f}× below the NLV-based recommendation "
        f"${recommended:.2f}. Cap is leaving capacity on the table for the current account size.",
    )


def _ack_status(
    ack: dict[str, Any] | None,
    *,
    nlv: float | None,
    recommended: float | None,
) -> dict[str, Any]:
    """Describe whether the current ack covers the current recommendation."""
    if ack is None:
        return {
            "ackPresent": False,
            "ackedCap": None,
            "ackedNlv": None,
            "ackedAt": None,
            "withinAckTolerance": False,
            "drawdownTrigger": False,
            "needsFreshAck": True,
        }
    acked_cap = _coerce_float(ack.get("acceptedCap"))
    acked_nlv = _coerce_float(ack.get("acceptedNlv"))
    tolerance_pct = float(ack.get("ackTolerancePct", DEFAULT_ACK_TOLERANCE_PCT))
    drawdown_pause_pct = float(ack.get("drawdownPausePct", DEFAULT_DRAWDOWN_PAUSE_PCT))

    within_tolerance = False
    if recommended is not None and acked_cap is not None and acked_cap > 0:
        within_tolerance = abs(recommended - acked_cap) / acked_cap <= tolerance_pct

    drawdown_trigger = False
    if nlv is not None and acked_nlv is not None and acked_nlv > 0:
        # symmetric: positive number means NLV has fallen below ack'd
        drawdown_trigger = (acked_nlv - nlv) / acked_nlv >= drawdown_pause_pct

    return {
        "ackPresent": True,
        "ackedCap": acked_cap,
        "ackedNlv": acked_nlv,
        "ackedAt": ack.get("acceptedAt"),
        "ackTolerancePct": tolerance_pct,
        "drawdownPausePct": drawdown_pause_pct,
        "withinAckTolerance": within_tolerance,
        "drawdownTrigger": drawdown_trigger,
        "needsFreshAck": (not within_tolerance) or drawdown_trigger,
    }


# ─────────────────────────── public API: build + render ───────────────


def build_capital_scaling(*, now: datetime | None = None) -> dict[str, Any]:
    """Read NLV + ack, produce the recommendation artifact."""
    now = now or local_now()
    nlv, gen_iso, nlv_age = _read_live_account(now)
    ack = _read_ack()
    params = _formula_params(ack)
    target_pct = float(params["targetPctPerTicket"])
    floor = float(params["floorDollars"])
    ceiling = float(params["ceilingDollars"])
    daily_ratio = float(params["dailyTicketsRatio"])
    scaling_behavior = str(params["scalingBehavior"])

    rec = compute_recommended_cap(nlv, target_pct=target_pct, floor=floor, ceiling=ceiling)
    recommended = rec.get("recommendedCap")

    inputs = ScalingInputs(
        net_liquidating_value=nlv,
        nlv_source_path=str(LIVE_ACCOUNT_SYNC_FILE.name),
        nlv_generated_at=gen_iso,
        nlv_age_hours=nlv_age,
        target_pct_per_ticket=target_pct,
        floor_dollars=floor,
        ceiling_dollars=ceiling,
        daily_tickets_ratio=daily_ratio,
        scaling_behavior=scaling_behavior,
    )

    verdict, explanation = _verdict_from_divergence(
        nlv=nlv,
        nlv_age_hours=nlv_age,
        nlv_stale_hours=DEFAULT_NLV_STALE_HOURS,
        recommended=recommended,
        config_cap=float(MAX_SINGLE_TICKET_DOLLARS),
        ack=ack,
    )
    ack_status = _ack_status(ack, nlv=nlv, recommended=recommended)

    recommended_daily = (
        round(recommended * daily_ratio, 2) if recommended is not None else None
    )

    return {
        "generatedAt": now.isoformat(),
        "stage": CAPITAL_SCALING_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "inputs": inputs.to_payload(),
        "recommendation": {
            **rec,
            "recommendedDailyCap": recommended_daily,
        },
        "currentEnforced": {
            "singleTicketCap": float(MAX_SINGLE_TICKET_DOLLARS),
            "dailyTicketCap": float(MAX_DAILY_TICKET_DOLLARS),
            "openPaperTicketCap": int(MAX_OPEN_PAPER_TICKETS),
            "source": "inferno_config.MAX_SINGLE_TICKET_DOLLARS",
            "pctOfNLV": (
                round(float(MAX_SINGLE_TICKET_DOLLARS) / nlv, 4)
                if nlv and nlv > 0
                else None
            ),
        },
        "ack": ack_status,
        "verdict": verdict,
        "explanation": explanation,
        "citations": ["KELLY-1956", "THORP-2006", "DE-PRADO-2018"],
        "reminders": [
            "research-only: this module does not mutate inferno_config",
            "live trading authority is hard-coded False and is not affected by this module",
            "to opt into the formula run: python3 inferno_capital_scaling.py accept",
            "to change formula parameters re-run accept with --pct, --floor, --ceiling",
        ],
    }


def capital_scaling_text(payload: dict[str, Any]) -> str:
    """Render an operator-facing summary."""
    inp = payload.get("inputs") or {}
    rec = payload.get("recommendation") or {}
    enf = payload.get("currentEnforced") or {}
    ack = payload.get("ack") or {}

    def fm(x):
        if x is None:
            return "n/a"
        try:
            return f"${float(x):,.2f}"
        except Exception:
            return str(x)

    def pct(x):
        if x is None:
            return "n/a"
        try:
            return f"{float(x)*100:.2f}%"
        except Exception:
            return str(x)

    lines = [
        "Inferno Capital Scaling Recommender",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict:   {payload.get('verdict')}",
        f"  {payload.get('explanation','')}",
        "",
        "Inputs:",
        f"  Net liquidating value:   {fm(inp.get('netLiquidatingValue'))}",
        f"  NLV source:              {inp.get('nlvSource')}",
        f"  NLV generated at:        {inp.get('nlvGeneratedAt')}",
        f"  NLV age (hours):         {inp.get('nlvAgeHours')}",
        f"  Target % per ticket:     {pct(inp.get('targetPctPerTicket'))}",
        f"  Floor:                   {fm(inp.get('floorDollars'))}",
        f"  Ceiling:                 {fm(inp.get('ceilingDollars'))}",
        f"  Daily-cap ratio:         {inp.get('dailyTicketsRatio')}× single-ticket",
        f"  Scaling behavior:        {inp.get('scalingBehavior')}",
        "",
        "Recommendation:",
        f"  Raw formula (NLV × pct): {fm(rec.get('rawComputedCap'))}",
        f"  Recommended per-ticket:  {fm(rec.get('recommendedCap'))}"
        + ("  [at floor]" if rec.get('atFloor') else "")
        + ("  [at ceiling]" if rec.get('atCeiling') else ""),
        f"  Effective % of NLV:      {pct(rec.get('effectivePctOfNLV'))}",
        f"  Recommended daily cap:   {fm(rec.get('recommendedDailyCap'))}",
        "",
        "Currently enforced (inferno_config):",
        f"  Single-ticket cap:       {fm(enf.get('singleTicketCap'))}  "
        f"({pct(enf.get('pctOfNLV'))} of current NLV)",
        f"  Daily ticket cap:        {fm(enf.get('dailyTicketCap'))}",
        f"  Open paper ticket cap:   {enf.get('openPaperTicketCap')}",
        "",
        "Ack status:",
        f"  Ack present:             {ack.get('ackPresent')}",
        f"  Acked cap:               {fm(ack.get('ackedCap'))}",
        f"  Acked NLV at ack time:   {fm(ack.get('ackedNlv'))}",
        f"  Acked at:                {ack.get('ackedAt')}",
        f"  Within ack tolerance:    {ack.get('withinAckTolerance')}",
        f"  Drawdown trigger:        {ack.get('drawdownTrigger')}",
        f"  Needs fresh ack:         {ack.get('needsFreshAck')}",
        "",
        "Reminders:",
    ]
    for r in payload.get("reminders") or []:
        lines.append(f"  - {r}")
    return "\n".join(lines).rstrip() + "\n"


def save_capital_scaling(payload: dict[str, Any]) -> None:
    """Persist artifact JSON + text."""
    ensure_dirs()
    atomic_write_json(CAPITAL_SCALING_FILE, payload)
    atomic_write_text(CAPITAL_SCALING_TEXT_FILE, capital_scaling_text(payload))


# ─────────────────────────── ack flow ─────────────────────────────────


def write_ack(
    *,
    accepted_cap: float,
    accepted_nlv: float | None,
    target_pct: float,
    floor: float,
    ceiling: float,
    daily_ratio: float,
    scaling_behavior: str,
    ack_tolerance_pct: float = DEFAULT_ACK_TOLERANCE_PCT,
    drawdown_pause_pct: float = DEFAULT_DRAWDOWN_PAUSE_PCT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist the operator's accepted formula parameters as the ack file.

    Returns the ack payload that was written.
    """
    now = now or local_now()
    payload = {
        "acceptedAt": now.isoformat(),
        "acceptedCap": round(float(accepted_cap), 2),
        "acceptedNlv": round(float(accepted_nlv), 2) if accepted_nlv is not None else None,
        "targetPctPerTicket": float(target_pct),
        "floorDollars": float(floor),
        "ceilingDollars": float(ceiling),
        "dailyTicketsRatio": float(daily_ratio),
        "scalingBehavior": scaling_behavior,
        "ackTolerancePct": float(ack_tolerance_pct),
        "drawdownPausePct": float(drawdown_pause_pct),
        "note": (
            "Operator has accepted that the per-ticket cap will track current NLV "
            "via the formula above. The cap auto-applies within ackTolerancePct of "
            "the accepted cap; outside that band, fresh ack is required."
        ),
    }
    ensure_dirs()
    atomic_write_json(CAPITAL_SCALING_ACK_FILE, payload)
    return payload


def current_recommended_cap(now: datetime | None = None) -> dict[str, Any]:
    """Compact accessor used by inferno_risk_policy.

    Returns:
        {
          "recommendedCap": float | None,
          "ackedCap": float | None,
          "verdict": str,
          "shouldUseRecommendation": bool,
          "effectiveCap": float,        # what the risk policy should actually use
        }

    The risk policy should always be safe to call this; if anything is
    missing or stale, ``effectiveCap`` falls back to ``MAX_SINGLE_TICKET_DOLLARS``.
    """
    try:
        payload = build_capital_scaling(now=now)
    except Exception:
        return {
            "recommendedCap": None,
            "ackedCap": None,
            "verdict": "build-failed",
            "shouldUseRecommendation": False,
            "effectiveCap": float(MAX_SINGLE_TICKET_DOLLARS),
        }
    rec = payload.get("recommendation") or {}
    ack = payload.get("ack") or {}
    recommended = _coerce_float(rec.get("recommendedCap"))
    acked = _coerce_float(ack.get("ackedCap"))
    verdict = payload.get("verdict")

    # Use the ack'd cap when the ack covers the current recommendation; else
    # fall back to the config default. We deliberately do NOT auto-promote
    # the raw recommendation without an ack.
    if (
        ack.get("ackPresent")
        and ack.get("withinAckTolerance")
        and not ack.get("drawdownTrigger")
        and acked is not None
    ):
        effective_cap = min(acked, float(MAX_SINGLE_TICKET_DOLLARS) or float("inf"))
        # We also clamp by the recommended ceiling regardless of ack.
        ceiling = _coerce_float((payload.get("inputs") or {}).get("ceilingDollars"))
        if ceiling is not None:
            effective_cap = min(effective_cap, ceiling)
        return {
            "recommendedCap": recommended,
            "ackedCap": acked,
            "verdict": verdict,
            "shouldUseRecommendation": True,
            "effectiveCap": round(effective_cap, 2),
        }
    return {
        "recommendedCap": recommended,
        "ackedCap": acked,
        "verdict": verdict,
        "shouldUseRecommendation": False,
        "effectiveCap": float(MAX_SINGLE_TICKET_DOLLARS),
    }


# ─────────────────────────── CLI ──────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inferno capital scaling recommender (research-only)")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="Compute + persist the recommendation (default).")
    sub.add_parser("status", help="Print the last cached recommendation.")
    accept = sub.add_parser(
        "accept",
        help="Opt in to the NLV-percentage formula. Writes data/inferno_capital_scaling_ack.json.",
    )
    accept.add_argument("--pct", type=float, default=DEFAULT_TARGET_PCT_PER_TICKET, help="Target % per ticket (default 0.01 = 1%).")
    accept.add_argument("--floor", type=float, default=DEFAULT_FLOOR_DOLLARS, help="Floor in dollars (default 25).")
    accept.add_argument("--ceiling", type=float, default=DEFAULT_CEILING_DOLLARS, help="Ceiling in dollars (default 2000).")
    accept.add_argument(
        "--daily-ratio",
        type=float,
        default=DEFAULT_DAILY_TICKETS_RATIO,
        help="Daily cap = ratio × single-ticket cap (default 3).",
    )
    accept.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_ACK_TOLERANCE_PCT,
        help="Ack tolerance: auto-apply within ±this fraction (default 0.20).",
    )
    accept.add_argument(
        "--drawdown",
        type=float,
        default=DEFAULT_DRAWDOWN_PAUSE_PCT,
        help="Drawdown pause threshold (default 0.25).",
    )
    accept.add_argument(
        "--scaling",
        default=DEFAULT_SCALING_BEHAVIOR,
        choices=("symmetric-on-current-nlv", "ratchet-up-only", "trailing-30d-avg"),
        help="Scaling behavior selector.",
    )
    sub.add_parser("revoke", help="Delete the ack file. Future cap defaults back to inferno_config.")
    if not list(sub.choices):  # pragma: no cover
        pass
    args = parser.parse_args()
    if not args.command:
        args.command = "run"
    return args


def main() -> int:
    args = parse_args()
    if args.command == "status":
        if CAPITAL_SCALING_TEXT_FILE.exists():
            print(CAPITAL_SCALING_TEXT_FILE.read_text(encoding="utf-8"))
            return 0
        print("(no cached capital_scaling report)")
        return 0
    if args.command == "revoke":
        if CAPITAL_SCALING_ACK_FILE.exists():
            CAPITAL_SCALING_ACK_FILE.unlink()
            print(f"Removed ack file at {CAPITAL_SCALING_ACK_FILE}")
        else:
            print("No ack file to remove.")
        # Re-run to surface the new state.
        args.command = "run"
    if args.command == "accept":
        # Compute the current recommendation, then write an ack pinned to it.
        payload = build_capital_scaling()
        rec = payload.get("recommendation") or {}
        inputs = payload.get("inputs") or {}
        recommended = _coerce_float(rec.get("recommendedCap"))
        nlv = _coerce_float(inputs.get("netLiquidatingValue"))
        if recommended is None:
            print(
                "Cannot accept: no recommendation available. "
                "Run `python3 inferno_live_account_sync.py` first."
            )
            return 1
        ack = write_ack(
            accepted_cap=recommended,
            accepted_nlv=nlv,
            target_pct=args.pct,
            floor=args.floor,
            ceiling=args.ceiling,
            daily_ratio=args.daily_ratio,
            scaling_behavior=args.scaling,
            ack_tolerance_pct=args.tolerance,
            drawdown_pause_pct=args.drawdown,
        )
        print(
            f"Accepted cap ${ack['acceptedCap']:.2f} at NLV {ack['acceptedNlv']} "
            f"with formula pct={ack['targetPctPerTicket']}, floor=${ack['floorDollars']:.0f}, "
            f"ceiling=${ack['ceilingDollars']:.0f}, tolerance=±{ack['ackTolerancePct']*100:.0f}%."
        )
        # Re-run so the saved artifact reflects the new ack state.
        args.command = "run"
    if args.command == "run":
        payload = build_capital_scaling()
        save_capital_scaling(payload)
        print(capital_scaling_text(payload))
        return 0
    print(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
