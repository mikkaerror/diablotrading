#!/usr/bin/env python3
"""Inferno desk — one-screen "what should I do today" tool.

Reads what already exists on disk (live account sync, capital-scaling state,
paper test director slate) and prints a single plain-English screen:

  - your money right now (current NLV, change from peak)
  - today's paper candidates (if any), each as one line, with a y/n/q prompt

What it does on `y`: invokes the existing inferno_approval_queue to approve.
What it does on `n`: records the skip in data/operator_decisions.csv so we
                     keep an audit trail without nagging.
What it does on `q`: stops the loop, prints the closing summary, exits.

This is intentionally a thin entry point. It does NOT:
  - fetch fresh data (run your existing refresh scripts first)
  - mutate any ledger directly (only calls approval_queue under the hood)
  - touch authority / live trading / broker submit
  - generate any new artifact other than an append-only CSV decision log
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path

from inferno_reporting_summary import live_account_source_timestamp

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

LIVE_SYNC = DATA / "inferno_live_account_sync.json"
SCALING_STATE = DATA / "inferno_capital_scaling_state.json"
SCALING_REPORT = DATA / "inferno_capital_scaling.json"
DIRECTOR = DATA / "inferno_paper_test_director.json"
LIVE_POSITIONS = DATA / "inferno_live_position_review.json"
DECISIONS_LOG = DATA / "operator_decisions.csv"
BROKER_TRUTH_MAX_AGE_HOURS = 36.0

# Plain-English names so the prompt reads like English, not config.
PRETTY_STRATEGY = {
    "LONG_STRADDLE": "Long Straddle",
    "LONG_STRANGLE": "Long Strangle",
    "LONG_CALL": "Long Call",
    "LONG_PUT": "Long Put",
    "PUT_CREDIT_SPREAD": "Put Credit Spread",
    "CALL_CREDIT_SPREAD": "Call Credit Spread",
    "CALL_DEBIT_SPREAD": "Call Debit Spread",
    "PUT_DEBIT_SPREAD": "Put Debit Spread",
    "IRON_CONDOR": "Iron Condor",
}


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _money(value, default: str = "n/a") -> str:
    if value is None:
        return default
    try:
        f = float(value)
        return f"${f:,.2f}"
    except (TypeError, ValueError):
        return default


def _artifact_age_hours(payload: dict, *, now: _dt.datetime | None = None) -> float | None:
    """Return artifact age while handling aware and naive ISO timestamps."""
    raw = live_account_source_timestamp(payload) or str(payload.get("generatedAt") or "").strip()
    if not raw:
        return None
    try:
        generated = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    current = now or _dt.datetime.now().astimezone()
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=current.tzinfo)
    if current.tzinfo is None:
        current = current.replace(tzinfo=generated.tzinfo)
    return max(0.0, (current - generated.astimezone(current.tzinfo)).total_seconds() / 3600.0)


def _freshness_label(payload: dict, *, now: _dt.datetime | None = None) -> tuple[bool, str]:
    """Return broker-artifact freshness plus a compact age label."""
    age = _artifact_age_hours(payload, now=now)
    if age is None:
        return False, "unknown age"
    if age < 24:
        label = f"{age:.1f}h old"
    else:
        label = f"{age / 24:.1f}d old"
    return age <= BROKER_TRUTH_MAX_AGE_HOURS, label


def _strategy_label(raw: str | None) -> str:
    return PRETTY_STRATEGY.get((raw or "").upper(), raw or "Unknown")


def _max_profit_label(value) -> str:
    """Open-ended payoffs (long straddles/strangles) show as 'open-ended'."""
    if isinstance(value, str) and value.strip().lower() in {"uncapped", "open-ended"}:
        return "open-ended"
    return _money(value)


def print_money_header(*, now: _dt.datetime | None = None) -> bool:
    """One-line P/L line at the top so the operator sees the number first."""
    sync = _load_json(LIVE_SYNC)
    state = _load_json(SCALING_STATE)
    fresh, age_label = _freshness_label(sync, now=now)

    raw_nlv = sync.get("netLiquidatingValue")
    nlv = _money(raw_nlv)
    cash = _money(sync.get("totalCash"))
    peak = state.get("peakNlv")
    last = state.get("lastNlv")

    try:
        from_peak = float(raw_nlv) - float(peak) if peak and raw_nlv else None
    except (TypeError, ValueError):
        from_peak = None
    try:
        from_last = float(raw_nlv) - float(last) if last and raw_nlv else None
    except (TypeError, ValueError):
        from_last = None

    delta = ""
    if from_peak is not None and abs(from_peak) >= 0.01:
        sign = "+" if from_peak >= 0 else ""
        delta = f"  ({sign}{from_peak:,.2f} vs peak)"
    if from_last is not None and abs(from_last) >= 0.01:
        sign = "+" if from_last >= 0 else ""
        delta += f"  ({sign}{from_last:,.2f} vs last)"

    print()
    if raw_nlv is None:
        print("Money:  unavailable (no Schwab account snapshot)")
    elif fresh:
        print(f"Money:  {nlv}  cash {cash}{delta}")
    else:
        print(f"Money (last known; STALE {age_label}):  {nlv}  cash {cash}{delta}")
        print("  Refresh broker truth: ./run_inferno_schwab_account_sync.sh --json")
    print()
    return fresh


def _drawdown_banner_if_needed() -> str | None:
    """Top-of-screen warning when the drawdown stepper is past `normal`.

    BACKLOG #5. Reads the capital_scaling artifact for the stepper level
    (`normal` / `step-1-half` / `step-2-quarter` / `paused`) and returns a
    one-line banner only when the level is not `normal`. Silent at normal
    so the screen stays quiet 99% of the time.
    """
    payload = _load_json(SCALING_REPORT)
    dd = payload.get("drawdownState") or {}
    level = (dd.get("level") or "").strip().lower()
    if not level or level == "normal":
        return None
    dd_pct = dd.get("drawdownFraction")
    pct_str = f"{dd_pct * 100:.1f}%" if isinstance(dd_pct, (int, float)) else "?"
    cap_mult = dd.get("capMultiplier")
    mult_str = f"{cap_mult:.2f}x" if isinstance(cap_mult, (int, float)) else "?"
    allows = dd.get("newEntriesAllowed", True)
    if level in ("paused", "step-3-paused"):
        verb = "PAUSED — no new entries until NLV recovers above peak − 30%"
    elif level == "step-2-quarter":
        verb = f"step-2-quarter: cap × {mult_str}, new entries " + ("ok" if allows else "blocked")
    elif level == "step-1-half":
        verb = f"step-1-half: cap × {mult_str}, new entries " + ("ok" if allows else "blocked")
    else:
        verb = f"{level}: cap × {mult_str}"
    return f"⚠  Drawdown {pct_str} from peak — {verb}  (playbook §5.2)"


def _discipline_reminder_if_loss(positions: list) -> str | None:
    """Return a one-line reminder when any position is sitting at -20% or worse.

    The point isn't drama; it's the pre-committed rule. Per
    `docs/TRADE_MANAGEMENT_PLAYBOOK.md` §5.4: never average down on a losing
    position. The right action is close or roll, never add. This line exists
    so the operator sees the rule at the moment they're most tempted to
    break it (when something is bleeding).
    """
    worst_pct = None
    for p in positions or []:
        pct = p.get("plPercent")
        try:
            if pct is None:
                continue
            v = float(pct)
            if worst_pct is None or v < worst_pct:
                worst_pct = v
        except (TypeError, ValueError):
            continue
    if worst_pct is None or worst_pct > -20.0:
        return None
    return (
        "  Reminder: when a position is in loss, the options are close or "
        "roll. Never add. (playbook §5.4)"
    )


def print_holdings_section(*, now: _dt.datetime | None = None) -> None:
    """Show the legacy book in dollar terms: position value, unrealized P/L.

    The point is to keep the operator's main money story (long-term-core
    holdings) visible alongside the desk's options-trading layer. Reads
    inferno_live_position_review.json which is regenerated by the standard
    Schwab account sync.
    """
    review = _load_json(LIVE_POSITIONS)
    sync = _load_json(LIVE_SYNC)
    positions = review.get("positions") or []
    if not positions:
        return
    fresh, age_label = _freshness_label(sync or review, now=now)

    total_mv = 0.0
    total_pl = 0.0
    rows = []
    for p in positions:
        sym = p.get("symbol") or "?"
        mv = p.get("markValue")
        pl = p.get("plOpen")
        pl_pct = p.get("plPercent")
        try:
            if mv is not None:
                total_mv += float(mv)
            if pl is not None:
                total_pl += float(pl)
        except (TypeError, ValueError):
            pass
        pl_str = ""
        if pl is not None:
            try:
                pl_f = float(pl)
                sign = "+" if pl_f >= 0 else "-"
                pl_str = f"  ({sign}${abs(pl_f):,.2f} since open"
                if pl_pct is not None:
                    pct_f = float(pl_pct)
                    pct_sign = "+" if pct_f >= 0 else "-"
                    pl_str += f", {pct_sign}{abs(pct_f):.2f}%"
                pl_str += ")"
            except (TypeError, ValueError):
                pass
        rows.append(f"  {sym:<6} {_money(mv)}{pl_str}")

    print("Holdings:" if fresh else f"Holdings (last known; STALE {age_label}):")
    for r in rows:
        print(r)
    if positions:
        sign = "+" if total_pl >= 0 else "-"
        print(f"  {'─' * 6}")
        print(
            f"  total   {_money(total_mv)}  "
            f"({sign}${abs(total_pl):,.2f} unrealized)"
        )
    reminder = _discipline_reminder_if_loss(positions)
    if reminder:
        print(reminder)
    print()


def candidates_today() -> list[dict]:
    """The list the operator can act on today.

    Pulls auto-paper-selected candidates plus approval-only candidates from
    the paper test director. Returns [] when nothing is approveable today.
    """
    director = _load_json(DIRECTOR)
    auto = director.get("autoPaperSlate") or []
    approval = director.get("approvalSlate") or []
    out = []
    for item in list(auto) + list(approval):
        if item.get("approvalStatus") == "pending":
            out.append(item)
    return out


def _candidate_line(item: dict) -> str:
    ticker = item.get("ticker", "?")
    strat = _strategy_label(item.get("strategy"))
    max_loss = _money(item.get("estimatedMaxLoss"))
    max_profit = _max_profit_label(item.get("estimatedMaxProfit"))
    dte_earn = item.get("daysUntilEarnings")
    dte_str = f"{dte_earn}d to earnings" if dte_earn is not None else "earnings ?"
    return (
        f"  {ticker}  {strat}  |  "
        f"risk up to {max_loss}  |  "
        f"could make up to {max_profit}  |  "
        f"{dte_str}"
    )


def _log_decision(
    ticker: str,
    action: str,
    note: str = "",
    rationale: str = "",
    confidence: str = "",
    seconds_to_decide: str = "",
) -> None:
    """Append-only audit trail of operator decisions.

    Seven columns: timestamp, ticker, action, note, rationale, confidence,
    seconds_to_decide. rationale + confidence are the decision-journal
    fields (BACKLOG #13). seconds_to_decide is friction telemetry
    (BACKLOG #4) — wall-clock time between the candidate appearing and
    the operator pressing a key.

    Pre-existing rows (4 or 6 columns) are still readable; new rows have 7.
    """
    DECISIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    new_file = not DECISIONS_LOG.exists()
    with DECISIONS_LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(
                [
                    "timestamp",
                    "ticker",
                    "action",
                    "note",
                    "rationale",
                    "confidence",
                    "seconds_to_decide",
                ]
            )
        w.writerow(
            [
                _dt.datetime.now().isoformat(timespec="seconds"),
                ticker,
                action,
                note,
                rationale,
                confidence,
                seconds_to_decide,
            ]
        )


def _prompt_decision_journal() -> tuple[str, str]:
    """Two-field journal prompt fired only on approve.

    Keeps the prompt minimal and skippable — pressing enter on either
    leaves the field empty. The friction is intentional: pausing for 5
    seconds to articulate the thesis is the discipline; the captured text
    is the bonus.
    """
    try:
        rationale = input(
            "    one-sentence why? (enter to skip): "
        ).strip()
    except EOFError:
        rationale = ""
    try:
        confidence = input(
            "    confidence 1-10? (enter to skip): "
        ).strip()
    except EOFError:
        confidence = ""
    # accept only 1-10; silently drop garbage
    if confidence:
        try:
            n = int(confidence)
            confidence = str(n) if 1 <= n <= 10 else ""
        except ValueError:
            confidence = ""
    return rationale, confidence


def _approve_via_queue(ticker: str) -> int:
    """Call the existing approval queue. Returns the subprocess exit code."""
    return subprocess.call(
        ["python3", "inferno_approval_queue.py", "approve", ticker],
        cwd=str(ROOT),
    )


def _reject_via_queue(ticker: str) -> int:
    return subprocess.call(
        ["python3", "inferno_approval_queue.py", "reject", ticker],
        cwd=str(ROOT),
    )


def _prompt(message: str) -> str:
    """Single-character prompt that strips and lowercases."""
    try:
        return input(message).strip().lower()
    except EOFError:
        return "q"


def run_one(item: dict) -> str:
    """Show one candidate, take one decision, log it. Returns action taken.

    Friction telemetry (BACKLOG #4): wall-clock seconds between candidate
    line printed and the operator pressing a key. Long hesitation is
    signal — either the candidate is unclear, the data is missing, or the
    operator doesn't trust the surface.
    """
    ticker = item.get("ticker", "")
    print(_candidate_line(item))
    t_start = _dt.datetime.now()
    answer = _prompt("    paper-trade this? [y]es / [n]o / [s]kip / [q]uit: ")
    elapsed = f"{(_dt.datetime.now() - t_start).total_seconds():.1f}"
    if answer in ("y", "yes"):
        rationale, confidence = _prompt_decision_journal()
        rc = _approve_via_queue(ticker)
        if rc == 0:
            _log_decision(
                ticker,
                "approve",
                "via today.py",
                rationale=rationale,
                confidence=confidence,
                seconds_to_decide=elapsed,
            )
            print(f"    -> approved {ticker}")
            return "approve"
        _log_decision(
            ticker,
            "approve-failed",
            f"queue rc={rc}",
            rationale=rationale,
            confidence=confidence,
            seconds_to_decide=elapsed,
        )
        print(f"    -> approval queue returned {rc}; check inferno_approval_queue status")
        return "approve-failed"
    if answer in ("n", "no", "reject"):
        rc = _reject_via_queue(ticker)
        if rc == 0:
            _log_decision(ticker, "reject", "via today.py", seconds_to_decide=elapsed)
            print(f"    -> rejected {ticker}")
            return "reject"
        _log_decision(
            ticker, "reject-failed", f"queue rc={rc}", seconds_to_decide=elapsed
        )
        print(f"    -> rejection queue returned {rc}; check inferno_approval_queue status")
        return "reject-failed"
    if answer in ("q", "quit"):
        return "quit"
    # "s", "skip", "" -- defer, no change to queue
    _log_decision(ticker, "skip", "via today.py", seconds_to_decide=elapsed)
    print(f"    -> skipped {ticker} (will reappear tomorrow)")
    return "skip"


def _is_quiet_mode() -> bool:
    """Detect --quiet / -q flag for cron / scripted invocation.

    BACKLOG #6. Per CLAUDE.md §7 the constraint is "only one flag, and it
    only suppresses prompts" — quiet mode prints the screen (money +
    holdings + candidates summary) and exits 0 without ever calling
    `input()`. No approve / reject / skip is performed; the queue is left
    untouched. This makes today.sh safe to invoke from
    nightly_optimize.sh or any scheduled refresh that wants to capture
    "what would the morning screen look like" without operator input.
    """
    args = set(sys.argv[1:])
    return "--quiet" in args or "-q" in args


def main() -> int:
    quiet = _is_quiet_mode()
    banner = _drawdown_banner_if_needed()
    if banner:
        print(banner)
        print()
    print_money_header()
    print_holdings_section()

    items = candidates_today()
    if not items:
        director = _load_json(DIRECTOR)
        verdict = director.get("verdict") or "no-data"
        print(f"Today: no candidates to approve.  (desk verdict: {verdict})")
        print("Nothing to do.  Run your dawn cycle to refresh and try again.")
        return 0

    if quiet:
        # Cron / scripted invocation: print the candidate list, do not prompt.
        # The queue is not mutated; operator picks up changes on next
        # interactive run.
        print(f"Today: {len(items)} candidate(s) waiting on you.")
        print()
        for it in items:
            print(_candidate_line(it))
        print()
        print("Done. (--quiet: no decisions taken; run ./today.sh to act.)")
        return 0

    print(f"Today: {len(items)} candidate(s) waiting on you.")
    print()
    counts = {"approve": 0, "reject": 0, "skip": 0, "quit": 0}
    for it in items:
        action = run_one(it)
        counts[action] = counts.get(action, 0) + 1
        if action == "quit":
            break

    approved = counts.get("approve", 0)
    rejected = counts.get("reject", 0)
    skipped = counts.get("skip", 0)
    print()
    print(
        f"Done.  approved={approved}  rejected={rejected}  skipped={skipped}"
    )
    if approved:
        print("Heads up: approved paper tickets stage with the next strike cycle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
