from __future__ import annotations

"""Compact decision digest for the daily Strike Plan email.

The strike email used to append nine full desk reports, including every
historical blocked ticket in the paper ledger and every shadow ticket. The
operator asked for less: what can I act on today, how is the evidence doing,
and why are trades getting blocked -- in one screen.

This module is reporting-only. It reads payloads the strike cycle already
built and renders a short text digest. It never changes a gate, ticket,
approval, risk constant, or authority flag. The full reports are still written
to reports/*_latest.txt by their own modules; set INFERNO_STRIKE_EMAIL_VERBOSE=1
to get the old full appendix back in the email.
"""

import os
import re
from collections import Counter
from datetime import date, timedelta
from typing import Any, Iterable

EMAIL_DIGEST_STAGE = "email-digest-reporting-only"
VERBOSE_ENV = "INFERNO_STRIKE_EMAIL_VERBOSE"
BLOCK_WINDOW_DAYS = 7
MAX_BLOCK_REASONS = 4

# Blocks that apply to every unapproved ticket carry no information.
_UNIVERSAL_BLOCKS = (
    "human approval missing",
    "human approval still required",
    "human approval is missing",
    "execution intent is not approval-ready",
)

_REASON_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^projected daily max loss .* exceeds cap", re.I), "over daily loss cap"),
    (re.compile(r"^max loss .* exceeds single-ticket cap", re.I), "over single-ticket cap"),
    (re.compile(r"spread is wide at", re.I), "wide bid/ask spread"),
    (re.compile(r"reward/risk .* below debit-spread floor", re.I), "reward/risk below spread floor"),
    (re.compile(r"no supported strike plan for (.+)$", re.I), r"no strike plan for \1"),
    (re.compile(r"has no visible volume/open interest", re.I), "no volume/open interest"),
    (re.compile(r"diverges from Schwab underlying", re.I), "stale price vs Schwab"),
    (re.compile(r"already has an open paper ticket", re.I), "already has open ticket"),
    (re.compile(r"premium hurdle failed", re.I), "premium hurdle failed"),
)


def verbose_requested(env: dict[str, str] | None = None) -> bool:
    value = (env if env is not None else os.environ).get(VERBOSE_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_block_reason(reason: str) -> str | None:
    """Collapse a raw block string into a short, countable label."""
    text = str(reason or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if any(lowered.startswith(block) for block in _UNIVERSAL_BLOCKS):
        return None
    for pattern, label in _REASON_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.expand(label) if "\\" in label else label
    return text[:60]


def _as_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "-"


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "-"


def _r(value: Any) -> str:
    try:
        return f"{float(value):+.2f}R"
    except (TypeError, ValueError):
        return "-"


def _pretty_strategy(name: Any) -> str:
    return str(name or "?").replace("_", " ").lower()


def _item_blocks(item: dict[str, Any]) -> list[str]:
    verdict = item.get("riskVerdict") or {}
    raw: list[str] = []
    raw.extend(verdict.get("blocks") or [])
    raw.extend(item.get("intentBlocks") or [])
    raw.extend(item.get("blockReasons") or [])
    labels: list[str] = []
    for reason in raw:
        label = normalize_block_reason(reason)
        if label and label not in labels:
            labels.append(label)
    return labels


def today_section(plan: dict[str, Any]) -> list[str]:
    ready: list[str] = []
    waiting: list[str] = []
    passed: list[str] = []
    failed = 0
    for item in plan.get("items") or []:
        if not item.get("ok"):
            failed += 1
            continue
        strike = item.get("strikePlan") or {}
        metrics = (item.get("riskVerdict") or {}).get("metrics") or {}
        max_loss = metrics.get("maxLossDollars", strike.get("estimatedMaxLoss"))
        head = (
            f"{item.get('ticker')} {_pretty_strategy(strike.get('strategy'))} "
            f"exp {strike.get('expiration') or item.get('expiration')} | max loss {_money(max_loss)}"
        )
        dte = item.get("daysUntilEarnings")
        if dte is not None:
            head += f" | earnings {dte}d"
        blocks = _item_blocks(item)
        if blocks:
            passed.append(f"- {head} -> {', '.join(blocks[:2])}")
        elif str(item.get("approvalStatus") or "").lower() in {"pending", ""}:
            waiting.append(f"- {head}")
        else:
            ready.append(f"- {head}")

    lines = ["TODAY"]
    if ready:
        lines.append("Ready for paperMoney:")
        lines.extend(ready)
    if waiting:
        lines.append("Waiting on your approval (./inferno today):")
        lines.extend(waiting)
    if not ready and not waiting:
        lines.append("Nothing to act on today.")
    if passed:
        lines.append(f"Passed on {len(passed)}:")
        lines.extend(passed)
    if failed:
        lines.append(f"({failed} candidate(s) could not be priced)")
    return lines


def scoreboard_section(shadow: dict[str, Any], analytics: dict[str, Any] | None = None) -> list[str]:
    lines = ["EVIDENCE"]
    closed_metrics = (analytics or {}).get("closedMetrics") or (analytics or {}).get("closed") or {}
    scored = closed_metrics.get("scoredCount", closed_metrics.get("scored"))
    if scored is None:
        scored = 0
    lines.append(f"Paper outcomes scored: {scored}/30 toward promotion review")
    rows = [
        row
        for row in (shadow.get("strategies") or [])
        if (row.get("closedCount") or 0) > 0
    ]
    if rows:
        lines.append("Shadow results (research-only, what blocked trades would have done):")
        for row in sorted(rows, key=lambda r: -(r.get("closedCount") or 0)):
            lines.append(
                f"- {_pretty_strategy(row.get('strategy'))}: {row.get('closedCount')} closed | "
                f"win {_pct(row.get('winRate'))} | avg {_r(row.get('avgReturnOnRisk'))}"
            )
    return lines


def block_reason_counts(
    items: Iterable[dict[str, Any]],
    as_of: date,
    window_days: int = BLOCK_WINDOW_DAYS,
) -> tuple[int, Counter]:
    start = as_of - timedelta(days=window_days)
    counts: Counter = Counter()
    total = 0
    for item in items:
        if item.get("status") not in {"paper-blocked", "paper-rejected"}:
            continue
        traded = _as_date(item.get("tradeDate"))
        if traded is None or traded <= start or traded > as_of:
            continue
        total += 1
        for label in _item_blocks(item):
            counts[label] += 1
    return total, counts


def blocks_section(ledger: dict[str, Any], as_of: date) -> list[str]:
    total, counts = block_reason_counts(ledger.get("items") or [], as_of)
    if not total:
        return []
    reasons = ", ".join(f"{label} ({count})" for label, count in counts.most_common(MAX_BLOCK_REASONS))
    line = f"Blocked last {BLOCK_WINDOW_DAYS}d: {total} ticket(s)"
    if reasons:
        line += f" -- {reasons}"
    return ["WHY TRADES GET BLOCKED", line]


def status_section(authority: dict[str, Any], sandbox: dict[str, Any] | None = None) -> list[str]:
    decision = authority.get("decision") or {}
    line = (
        f"Authority: {decision.get('authorityLevel', '-')} | "
        f"live submit {decision.get('liveTradingAllowed', False)}"
    )
    if sandbox:
        line += f" | paperMoney stageable {sandbox.get('stageableCount', len(sandbox.get('stageable') or []))}"
    return ["DESK", line]


def build_strike_digest(
    plan: dict[str, Any],
    ledger: dict[str, Any] | None = None,
    shadow: dict[str, Any] | None = None,
    analytics: dict[str, Any] | None = None,
    authority: dict[str, Any] | None = None,
    sandbox: dict[str, Any] | None = None,
    as_of: date | None = None,
) -> str:
    """Render the one-screen strike email body. Reporting only."""
    as_of = as_of or _as_date(plan.get("generatedAt")) or date.today()
    sections = [
        [f"Inferno Strike Digest - {as_of.isoformat()}", "Paper-only. Nothing here places an order."],
        today_section(plan),
    ]
    if shadow:
        sections.append(scoreboard_section(shadow, analytics))
    if ledger:
        block_lines = blocks_section(ledger, as_of)
        if block_lines:
            sections.append(block_lines)
    if authority:
        sections.append(status_section(authority, sandbox))
    sections.append(
        [
            "Full ledger, shadow tickets and analytics: reports/*_latest.txt",
            f"(set {VERBOSE_ENV}=1 to get the long version back)",
        ]
    )
    return "\n\n".join("\n".join(section) for section in sections).rstrip() + "\n"
