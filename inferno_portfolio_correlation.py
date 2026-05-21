from __future__ import annotations

"""Inferno Portfolio Correlation — concentration + effective-bet math.

What it does:
    Reads the paper + shadow ledgers and computes, for the active slate
    and (where outcomes exist) for the closed tape:
      * pairwise PnL correlation across closed tickets, grouped by
        strategy family
      * effective bet count (Herfindahl-style; 1 / Σ wᵢ²) on the active
        slate, weighted by risk units
      * per-sector / per-family / per-DTE-bucket concentration counts
      * adverse-scenario co-movement: for each active ticket, how many
        other active tickets share its family / direction / sector tag
      * a research-only verdict drawn from a small ladder
        (diversified / concentrated-by-intent / concentrated-by-drift /
        awaiting-outcomes)

What it does NOT do:
    - Approve, reject, or size any trade.
    - Block "concentrated" tickets — concentration is a warning, not a veto.
    - Promote any strategy. Research-only, diagnostic-only.

Strict contract: research-only, diagnostic-only, promotable=False.

## The math (see docs/PORTFOLIO_CONSTRUCTION.md §2, §3, §4)

Markowitz portfolio variance::

    σ²_P = Σᵢ wᵢ² σᵢ² + 2 Σᵢ<ⱼ wᵢ wⱼ σᵢ σⱼ ρᵢⱼ

Dalio Holy Grail (equal-σ streams, pairwise ρ)::

    σ²_P / σ²_individual = 1/N + (N−1)/N · ρ

Effective bet count (Grinold-Kahn Herfindahl)::

    N_eff = 1 / Σᵢ wᵢ²       where Σᵢ wᵢ = 1

Pairwise Pearson correlation (for closed PnL pairs (xᵢ, yᵢ))::

    ρ = Σ(xᵢ − x̄)(yᵢ − ȳ) / √(Σ(xᵢ − x̄)² · Σ(yᵢ − ȳ)²)

CLI::

    python3 inferno_portfolio_correlation.py             # run + persist
    python3 inferno_portfolio_correlation.py status      # show last memo
"""

import argparse
import math
from collections import Counter, defaultdict
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


# ───────────────────────── file locations ──────────────────────────────

PAPER_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
SHADOW_LEDGER_FILE = DATA_DIR / "inferno_shadow_evidence.json"

CORRELATION_FILE = DATA_DIR / "inferno_portfolio_correlation.json"
CORRELATION_TEXT_FILE = REPORTS_DIR / "portfolio_correlation_latest.txt"

CORRELATION_STAGE = "portfolio-correlation-research-only"


# ───────────────────────── thresholds ──────────────────────────────────

MIN_CLOSED_PAIRS_FOR_CORRELATION = 5  # below this, ρ is not reported
DOMINANT_FAMILY_SHARE_FLOOR = 0.50    # >50% in one family flags concentration
DRIFT_INTENT_THRESHOLD = 0.40         # above 40% needs an "intent" flag
EFFECTIVE_BREADTH_PASS_RATIO = 0.70   # N_eff / headcount >= this = diversified


# ───────────────────────── helpers (mirror Phase A) ─────────────────────


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


PNL_FIELDS = ("realizedPnl", "realised_pnl", "pnl", "outcomePnl", "outcome_pnl")
STATUS_CLOSED = {"closed", "exit", "exited", "outcome-closed", "shadow-closed"}


def _ticket_pnl(ticket: dict) -> float | None:
    for f in PNL_FIELDS:
        if f in ticket:
            v = _safe_float(ticket.get(f))
            if v is not None:
                return v
    return None


def _ticket_closed(ticket: dict) -> bool:
    if str(ticket.get("status", "")).lower() in STATUS_CLOSED:
        return True
    return _ticket_pnl(ticket) is not None


def _ticket_risk_units(ticket: dict) -> float:
    """Best-effort risk-unit weight. Falls back to estimatedMaxLoss, then to 1.0."""
    for key in ("riskUnits", "estimatedMaxLoss", "entryLimit"):
        v = _safe_float(ticket.get(key))
        if v is not None and v > 0:
            return v
    return 1.0


def _strategy_family(ticket: dict) -> str:
    """Same classifier as the slippage estimator (see docstring there)."""
    raw = str(ticket.get("strategy") or ticket.get("setupRec") or "").strip().lower()
    if not raw:
        return "Unknown"
    name = raw.replace("_", " ")
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


def _direction(ticket: dict) -> str:
    """Best-effort direction: 'long-vol' / 'short-vol' / 'long-equity' /
    'short-equity' / 'unknown'.

    Inference: families known to be long-vol (straddle, strangle, calendar)
    are long-vol; credit spreads are short-vol; vertical-debit and
    vertical-credit lean equity-directional. This is a heuristic for
    correlation warnings, not a doctrine.
    """
    family = _strategy_family(ticket)
    if family in {"Long Straddle", "Long Strangle", "Calendar / Diagonal"}:
        return "long-vol"
    if family in {"Iron Condor", "Credit Spread"}:
        return "short-vol"
    if family in {"Vertical Debit", "Vertical"}:
        return "long-equity"
    if family == "Butterfly":
        return "neutral"
    return "unknown"


def _dte_bucket(ticket: dict) -> str:
    """Bucket by days-to-expiration since the desk's nominal band is 7-21 DTE."""
    days = _safe_float(ticket.get("daysToExpiration"))
    if days is None:
        # Try parsing from the expiration date relative to today if we had to.
        return "unknown"
    if days < 7:
        return "<7"
    if days <= 14:
        return "7-14"
    if days <= 21:
        return "14-21"
    if days <= 45:
        return "21-45"
    return ">45"


# ───────────────────────── effective bet count ──────────────────────────


def effective_bet_count(weights: list[float]) -> float:
    """Herfindahl-style effective count.

    For normalized weights w with Σw = 1, N_eff = 1 / Σ wᵢ². Returns 0
    for empty input.
    """
    total = sum(max(0.0, w) for w in weights)
    if total <= 0:
        return 0.0
    norm = [w / total for w in weights]
    s = sum(w * w for w in norm)
    return 1.0 / s if s > 0 else 0.0


# ───────────────────────── pairwise correlation ─────────────────────────


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation. Returns None on degenerate (constant) inputs."""
    n = len(xs)
    if n < 2 or len(ys) != n:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    var_x = sum((xs[i] - mean_x) ** 2 for i in range(n))
    var_y = sum((ys[i] - mean_y) ** 2 for i in range(n))
    if var_x <= 0 or var_y <= 0:
        return None
    return cov / math.sqrt(var_x * var_y)


def _family_pairwise_correlations(closed_tickets: list[dict]) -> dict[str, Any]:
    """Cross-family Pearson correlation of mean PnL per "day" bucket.

    Day buckets here use the ticket's createdAt date (best-effort string
    prefix). We compute family-day mean PnL, then correlate every
    family-pair series. Pairs with fewer than
    MIN_CLOSED_PAIRS_FOR_CORRELATION shared days produce None.
    """
    by_family_day: dict[tuple[str, str], list[float]] = defaultdict(list)
    for t in closed_tickets:
        pnl = _ticket_pnl(t)
        if pnl is None:
            continue
        family = _strategy_family(t)
        day = str(t.get("createdAt") or t.get("tradeDate") or "")[:10]
        if not day:
            continue
        by_family_day[(family, day)].append(pnl)

    family_day_mean: dict[str, dict[str, float]] = defaultdict(dict)
    for (family, day), pnls in by_family_day.items():
        family_day_mean[family][day] = sum(pnls) / len(pnls)

    families = sorted(family_day_mean.keys())
    pairs: list[dict[str, Any]] = []
    for i, fa in enumerate(families):
        for fb in families[i + 1:]:
            shared_days = sorted(set(family_day_mean[fa]) & set(family_day_mean[fb]))
            xs = [family_day_mean[fa][d] for d in shared_days]
            ys = [family_day_mean[fb][d] for d in shared_days]
            n = len(shared_days)
            rho = pearson(xs, ys) if n >= MIN_CLOSED_PAIRS_FOR_CORRELATION else None
            pairs.append(
                {
                    "familyA": fa,
                    "familyB": fb,
                    "sharedDays": n,
                    "correlation": round(rho, 4) if rho is not None else None,
                    "note": "insufficient-data" if rho is None else (
                        "high-correlation" if rho > 0.7
                        else "low-correlation" if rho < 0.3
                        else "moderate"
                    ),
                }
            )
    return {"families": families, "pairs": pairs}


# ───────────────────────── active-slate concentration ───────────────────


def _slate_concentration(active: list[dict]) -> dict[str, Any]:
    """Per-family / per-direction / per-DTE-bucket headcounts + risk weight."""
    if not active:
        return {
            "headcount": 0,
            "byFamily": {},
            "byDirection": {},
            "byDteBucket": {},
            "byTicker": {},
            "riskWeightedByFamily": {},
            "dominantFamilyShare": 0.0,
            "effectiveBetCount": 0.0,
            "effectiveBreadthRatio": 0.0,
        }
    by_family = Counter(_strategy_family(t) for t in active)
    by_direction = Counter(_direction(t) for t in active)
    by_dte = Counter(_dte_bucket(t) for t in active)
    by_ticker = Counter(str(t.get("ticker") or "?") for t in active)

    weights_by_family: dict[str, float] = defaultdict(float)
    for t in active:
        weights_by_family[_strategy_family(t)] += _ticket_risk_units(t)

    risk_weights = list(weights_by_family.values())
    n_eff = effective_bet_count(risk_weights)
    breadth_ratio = round(n_eff / len(active), 4) if active else 0.0

    headcount = sum(by_family.values())
    dominant_family_share = (
        round(by_family.most_common(1)[0][1] / headcount, 4) if headcount else 0.0
    )
    return {
        "headcount": headcount,
        "byFamily": dict(by_family),
        "byDirection": dict(by_direction),
        "byDteBucket": dict(by_dte),
        "byTicker": dict(by_ticker.most_common(15)),
        "riskWeightedByFamily": {
            k: round(v, 4) for k, v in weights_by_family.items()
        },
        "dominantFamilyShare": dominant_family_share,
        "effectiveBetCount": round(n_eff, 4),
        "effectiveBreadthRatio": breadth_ratio,
    }


def _ticket_overlap_counts(active: list[dict]) -> list[dict[str, Any]]:
    """For each active ticket, how many *other* slate tickets share its
    family / direction / sector tag? Used as the adverse-scenario read."""
    out: list[dict[str, Any]] = []
    families = [_strategy_family(t) for t in active]
    directions = [_direction(t) for t in active]
    for i, t in enumerate(active):
        fam = families[i]
        dir_ = directions[i]
        ticker = str(t.get("ticker") or "?")
        out.append(
            {
                "ticker": ticker,
                "ticketId": t.get("ticketId"),
                "family": fam,
                "direction": dir_,
                "sameFamilyCount": sum(1 for j, f in enumerate(families) if j != i and f == fam),
                "sameDirectionCount": sum(
                    1 for j, d in enumerate(directions) if j != i and d == dir_
                ),
            }
        )
    return out


# ───────────────────────── ingestion ────────────────────────────────────


def _load_tickets() -> tuple[list[dict], list[dict]]:
    """Return (active, closed) ticket lists from paper + shadow ledgers.

    "Active" = not closed and not paper-blocked.
    "Closed" = anything with a closed status or a non-None PnL.
    """
    active: list[dict] = []
    closed: list[dict] = []
    for path in (PAPER_LEDGER_FILE, SHADOW_LEDGER_FILE):
        payload = load_json_file(path)
        if not isinstance(payload, dict):
            continue
        items = payload.get("items") or []
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            if _ticket_closed(it):
                closed.append(it)
            else:
                status = str(it.get("status") or "").lower()
                if "blocked" not in status and "rejected" not in status:
                    active.append(it)
    return active, closed


# ───────────────────────── builder ──────────────────────────────────────


def build_portfolio_correlation(now: Any | None = None) -> dict[str, Any]:
    active, closed = _load_tickets()
    concentration = _slate_concentration(active)
    overlaps = _ticket_overlap_counts(active)
    correlations = _family_pairwise_correlations(closed)

    # Verdict ladder
    if not closed and not active:
        verdict = "awaiting-outcomes"
    elif active:
        dominant_share = concentration["dominantFamilyShare"]
        breadth_ratio = concentration["effectiveBreadthRatio"]
        if dominant_share >= DOMINANT_FAMILY_SHARE_FLOOR:
            # Concentrated. Without an "intent" flag stored upstream we
            # default to drift; the operator can override via a coordination
            # note marking the concentration deliberate.
            verdict = "concentrated-by-drift"
        elif dominant_share >= DRIFT_INTENT_THRESHOLD:
            verdict = "concentration-watch"
        elif breadth_ratio >= EFFECTIVE_BREADTH_PASS_RATIO:
            verdict = "diversified"
        else:
            verdict = "thin-diversification"
    else:
        verdict = "awaiting-outcomes"

    payload = {
        "version": 1,
        "stage": CORRELATION_STAGE,
        "promotable": False,
        "researchOnly": True,
        "authorityChanged": False,
        "generatedAt": str(now or local_now()),
        "verdict": verdict,
        "counts": {
            "active": len(active),
            "closed": len(closed),
        },
        "thresholds": {
            "minClosedPairsForCorrelation": MIN_CLOSED_PAIRS_FOR_CORRELATION,
            "dominantFamilyShareFloor": DOMINANT_FAMILY_SHARE_FLOOR,
            "driftIntentThreshold": DRIFT_INTENT_THRESHOLD,
            "effectiveBreadthPassRatio": EFFECTIVE_BREADTH_PASS_RATIO,
        },
        "slateConcentration": concentration,
        "perTicketOverlap": overlaps,
        "familyCorrelations": correlations,
        "reminders": [
            "Concentration warnings are research-only; the operator may have a "
            "deliberate concentration thesis. Do not auto-reject tickets here.",
            "Pairwise correlations require ≥5 shared days; thin pairs return "
            "'insufficient-data' rather than a number.",
            "Effective bet count uses risk-unit weights, not headcount — five "
            "tickets all in one family count as roughly one independent bet.",
        ],
        "citations": [
            "MARKOWITZ-1952",
            "DALIO-HOLY-GRAIL",
            "GRINOLD-1989",
            "GRINOLD-KAHN-2000",
            "KACPERCZYK-SIALM-ZHENG-2005",
        ],
    }
    return payload


def save_portfolio_correlation(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(CORRELATION_FILE, payload)
    atomic_write_text(CORRELATION_TEXT_FILE, portfolio_correlation_text(payload))


# ───────────────────────── rendering ────────────────────────────────────


def portfolio_correlation_text(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Inferno Portfolio Correlation (research-only)")
    lines.append("")
    lines.append(f"Generated: {payload.get('generatedAt')}")
    lines.append(f"Stage:     {payload.get('stage')}")
    lines.append(f"Verdict:   {payload.get('verdict')}")
    counts = payload.get("counts") or {}
    lines.append(
        f"Active: {counts.get('active', 0)}  closed: {counts.get('closed', 0)}"
    )
    lines.append("")
    conc = payload.get("slateConcentration") or {}
    if conc.get("headcount"):
        lines.append("ACTIVE SLATE CONCENTRATION")
        lines.append("--------------------------")
        lines.append(f"  Headcount: {conc.get('headcount')}")
        lines.append(f"  Effective bet count: {conc.get('effectiveBetCount')}")
        lines.append(f"  Effective breadth ratio: {conc.get('effectiveBreadthRatio')}")
        lines.append(f"  Dominant family share: {conc.get('dominantFamilyShare')}")
        lines.append("")
        for key, label in (
            ("byFamily", "By family"),
            ("byDirection", "By direction"),
            ("byDteBucket", "By DTE bucket"),
        ):
            bucket = conc.get(key) or {}
            if bucket:
                line = ", ".join(f"{k}={v}" for k, v in sorted(bucket.items(), key=lambda kv: -kv[1]))
                lines.append(f"  {label}: {line}")
        lines.append("")

    corr = payload.get("familyCorrelations") or {}
    pairs = corr.get("pairs") or []
    if pairs:
        lines.append("CROSS-FAMILY CORRELATIONS")
        lines.append("-------------------------")
        for p in pairs:
            rho = p.get("correlation")
            rho_txt = f"{rho:+.3f}" if isinstance(rho, (int, float)) else "  -  "
            lines.append(
                f"  {p['familyA'][:20]:<20} ↔ {p['familyB'][:20]:<20} "
                f"n={p['sharedDays']:>2}  ρ={rho_txt}  {p['note']}"
            )
        lines.append("")

    overlap = payload.get("perTicketOverlap") or []
    if overlap:
        lines.append("PER-TICKET OVERLAP (first 12)")
        lines.append("-----------------------------")
        for r in overlap[:12]:
            lines.append(
                f"  {r['ticker']:<8} family={r['family']:<22} "
                f"dir={r['direction']:<12} sameFamily={r['sameFamilyCount']:>2}  "
                f"sameDir={r['sameDirectionCount']:>2}"
            )
        lines.append("")

    lines.append("Reminders:")
    for item in payload.get("reminders") or []:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


# ───────────────────────── CLI ──────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Research-only portfolio correlation + concentration. "
            "See docs/PORTFOLIO_CONSTRUCTION.md."
        )
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=("run", "status"),
        help="run = build + persist; status = print last artifact.",
    )
    args = parser.parse_args(argv)

    if args.command == "status":
        existing = load_json_file(CORRELATION_FILE) or {}
        print(portfolio_correlation_text(existing))
        return 0

    payload = build_portfolio_correlation()
    save_portfolio_correlation(payload)
    print(portfolio_correlation_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
