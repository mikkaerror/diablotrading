from __future__ import annotations

"""Build the desk's research-backed market mastery action plan.

The plan translates primary-source market research into a small set of
operator rules, engineering tasks, and Browser reading assignments. It is
research-only: it cannot stage, approve, or submit an order.
"""

import argparse
from datetime import datetime
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


MARKET_MASTERY_PLAN_FILE = DATA_DIR / "inferno_market_mastery_plan.json"
MARKET_MASTERY_PLAN_TEXT_FILE = REPORTS_DIR / "market_mastery_next_actions_latest.txt"
SCHWAB_ACCOUNT_FILE = DATA_DIR / "inferno_schwab_account_sync.json"
SCHWAB_OPTIONS_FILE = DATA_DIR / "inferno_schwab_options.json"
SCHWAB_PRICE_HISTORY_FILE = DATA_DIR / "inferno_schwab_price_history.json"
PAPER_EXIT_AUDIT_FILE = DATA_DIR / "inferno_paper_exit_audit.json"
EXPECTED_MOVE_FILE = DATA_DIR / "inferno_expected_move_ledger.json"
STRATEGY_LAB_FILE = DATA_DIR / "inferno_strategy_lab.json"
SIZING_POSITIONING_TIMING_FILE = DATA_DIR / "inferno_sizing_positioning_timing.json"
EXPECTANCY_LEDGER_FILE = DATA_DIR / "inferno_expectancy_ledger.json"
DTE_POLICY_FILE = DATA_DIR / "inferno_dte_policy_analysis.json"
BEHAVIOR_AUDIT_FILE = DATA_DIR / "inferno_trading_behavior_audit.json"
PROCESS_COMPLIANCE_FILE = DATA_DIR / "inferno_process_compliance.json"
PORTFOLIO_HEAT_FILE = DATA_DIR / "inferno_portfolio_heat.json"
WHEEL_SHADOW_FILE = DATA_DIR / "inferno_wheel_shadow.json"

STAGE = "market-mastery-research-only"
FRESH_ACCOUNT_HOURS = 36.0


def number(value: Any, default: float = 0.0) -> float:
    """Coerce loose artifact values into a float."""
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value or "").replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return default


def age_hours(value: Any, now: datetime) -> float | None:
    """Return the age of an ISO timestamp in hours."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    return max(0.0, (now - parsed.astimezone(now.tzinfo)).total_seconds() / 3600.0)


def explicit_oauth_block(*payloads: dict[str, Any]) -> bool:
    """Return True when a source explicitly reports an OAuth/authorization block."""
    needles = ("oauth", "auth", "unauthorized", "reauthorization")
    for payload in payloads:
        values = [
            payload.get("status"),
            payload.get("sourceStatus"),
            payload.get("verdict"),
            payload.get("message"),
            payload.get("error"),
        ]
        haystack = " ".join(str(value or "").lower() for value in values)
        if any(needle in haystack for needle in needles):
            return True
    return False


def broker_truth_status(
    *,
    broker_data_fresh: bool,
    account: dict[str, Any],
    options: dict[str, Any],
    price_history: dict[str, Any],
) -> str:
    """Classify the broker-data action without blaming OAuth for stale tape."""
    if broker_data_fresh:
        return "ready"
    if explicit_oauth_block(account, options, price_history):
        return "blocked-on-oauth"
    return "refresh-needed"


def load_inputs() -> dict[str, dict[str, Any]]:
    """Load the small canonical artifact set used by this plan."""
    return {
        "schwabAccount": load_json_file(SCHWAB_ACCOUNT_FILE) or {},
        "schwabOptions": load_json_file(SCHWAB_OPTIONS_FILE) or {},
        "schwabPriceHistory": load_json_file(SCHWAB_PRICE_HISTORY_FILE) or {},
        "paperExitAudit": load_json_file(PAPER_EXIT_AUDIT_FILE) or {},
        "expectedMove": load_json_file(EXPECTED_MOVE_FILE) or {},
        "strategyLab": load_json_file(STRATEGY_LAB_FILE) or {},
        "sizing": load_json_file(SIZING_POSITIONING_TIMING_FILE) or {},
        "expectancy": load_json_file(EXPECTANCY_LEDGER_FILE) or {},
        "dtePolicy": load_json_file(DTE_POLICY_FILE) or {},
        "behavior": load_json_file(BEHAVIOR_AUDIT_FILE) or {},
        "processCompliance": load_json_file(PROCESS_COMPLIANCE_FILE) or {},
        "portfolioHeat": load_json_file(PORTFOLIO_HEAT_FILE) or {},
        "wheelShadow": load_json_file(WHEEL_SHADOW_FILE) or {},
    }


def browser_curriculum() -> list[dict[str, str]]:
    """Return the source-ranked Browser learning queue."""
    return [
        {
            "id": "B01",
            "priority": "P0",
            "topic": "Exit plans and net Greeks",
            "sourceType": "industry-education",
            "url": "https://www.optionseducation.org/news/may-office-hours-faqs",
            "question": "Why can correct direction still lose, and why must spreads be managed on net Greeks?",
            "deliverable": "Add max loss, profit objective, time stop, and net Delta/Gamma/Theta/Vega to every paper decision card.",
        },
        {
            "id": "B02",
            "priority": "P0",
            "topic": "Long-vol hurdle",
            "sourceType": "industry-education",
            "url": "https://www.optionseducation.org/strategies/all-strategies/long-straddle",
            "question": "What combination of underlying move, time decay, and volatility change must a long straddle overcome?",
            "deliverable": "Require an expected-move hurdle and an IV-change scenario before admitting long-vol paper trades.",
        },
        {
            "id": "B03",
            "priority": "P0",
            "topic": "Concentration",
            "sourceType": "regulatory-education",
            "url": "https://www.finra.org/investors/insights/concentration-risk",
            "question": "How can several tickers still represent one correlated AI/compute/miner risk bet?",
            "deliverable": "Measure portfolio heat by theme and correlation, not ticker count alone.",
        },
        {
            "id": "B04",
            "priority": "P1",
            "topic": "Risk capacity versus willingness",
            "sourceType": "regulatory-education",
            "url": "https://www.finra.org/investors/insights/know-your-risk-tolerance",
            "question": "How is willingness to take risk different from the financial ability to absorb loss?",
            "deliverable": "Keep account-level loss capacity separate from conviction and emotional comfort.",
        },
        {
            "id": "B05",
            "priority": "P1",
            "topic": "Turnover and overtrading",
            "sourceType": "peer-reviewed-academic",
            "url": "https://faculty.haas.berkeley.edu/odean/papers%20current%20versions/individual_investor_performance_final.pdf",
            "question": "What performance penalty did the most active households pay after trading costs?",
            "deliverable": "Track turnover, decisions per day, and net expectancy after spread/slippage before increasing trade frequency.",
        },
        {
            "id": "B06",
            "priority": "P1",
            "topic": "Disposition effect",
            "sourceType": "peer-reviewed-academic",
            "url": "https://faculty.haas.berkeley.edu/odean/papers%20current%20versions/areinvestorsreluctant.pdf",
            "question": "Are we realizing winners faster than losers without evidence that the losers deserve more time?",
            "deliverable": "Audit hold time and exit-rule compliance separately for winners and losers.",
        },
        {
            "id": "B07",
            "priority": "P2",
            "topic": "Options strategy benchmarks",
            "sourceType": "benchmark-provider",
            "url": "https://www.cboe.com/us/indices/benchmark_indices/",
            "question": "How do rule-based buy-write, put-write, condor, collar, and protection benchmarks differ?",
            "deliverable": "Choose the correct benchmark for each paper strategy family instead of comparing every structure with long stock.",
        },
        {
            "id": "B08",
            "priority": "P2",
            "topic": "Sizing under estimation error",
            "sourceType": "academic",
            "url": "https://www.stat.berkeley.edu/~aldous/157/Papers/Good_Bad_Kelly.pdf",
            "question": "Why can full Kelly be dangerously aggressive when edge estimates are uncertain?",
            "deliverable": "Do not activate Kelly sizing before a credible sample; later test fractional Kelly with hard portfolio caps.",
        },
    ]


def build_plan(
    inputs: dict[str, dict[str, Any]] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the current market mastery plan."""
    source = inputs or load_inputs()
    current = now or local_now()
    account = source.get("schwabAccount") or {}
    options = source.get("schwabOptions") or {}
    price_history = source.get("schwabPriceHistory") or {}
    paper_exit = source.get("paperExitAudit") or {}
    expected_move = source.get("expectedMove") or {}
    strategy_lab = source.get("strategyLab") or {}
    sizing = source.get("sizing") or {}
    expectancy = source.get("expectancy") or {}
    dte_policy = source.get("dtePolicy") or {}
    behavior = source.get("behavior") or {}
    process_compliance = source.get("processCompliance") or {}
    portfolio_heat = source.get("portfolioHeat") or {}
    wheel_shadow = source.get("wheelShadow") or {}

    account_age = age_hours(account.get("generatedAt"), current)
    options_age = age_hours(options.get("generatedAt"), current)
    price_history_age = age_hours(price_history.get("generatedAt"), current)
    account_fresh = bool(
        account.get("sourceStatus") == "ok"
        and account_age is not None
        and account_age <= FRESH_ACCOUNT_HOURS
    )
    options_fresh = bool(
        options.get("status") == "ok"
        and options_age is not None
        and options_age <= FRESH_ACCOUNT_HOURS
    )
    price_history_fresh = bool(
        price_history.get("status") == "ok"
        and price_history_age is not None
        and price_history_age <= FRESH_ACCOUNT_HOURS
    )
    broker_data_fresh = account_fresh and options_fresh and price_history_fresh
    exit_counts = paper_exit.get("counts") or {}
    expected_counts = expected_move.get("counts") or {}
    expected_overall = expected_move.get("overall") or {}
    strategy_overall = strategy_lab.get("overall") or {}
    sizing_current = sizing.get("currentSleeves") or {}
    sizing_options = sizing.get("optionsSizing") or {}

    closed_long_vol = int(number(expected_counts.get("closedLongVolRecords")))
    long_vol_beat_rate = number(expected_overall.get("beatRate"))
    long_vol_move_edge = number(expected_overall.get("meanMoveEdgePct"))
    scored_outcomes = int(number(strategy_overall.get("scoredCount")))
    close_now = int(number(exit_counts.get("closeNow")))
    review_today = int(number(exit_counts.get("reviewToday")))

    tasks = [
        {
            "id": "M01",
            "priority": "P0",
            "category": "data",
            "title": "Restore fresh Schwab account and option truth",
            "status": broker_truth_status(
                broker_data_fresh=broker_data_fresh,
                account=account,
                options=options,
                price_history=price_history,
            ),
            "why": "Sizing and timing decisions are invalid when account, quote, or option-chain inputs are stale.",
            "action": "Refresh account/options/price history, then rerun risk and capital reports; only restart OAuth if status says reauthorization is required.",
            "doneWhen": (
                f"Account, options, and price-history artifacts are each <= "
                f"{FRESH_ACCOUNT_HOURS:.0f} hours old with healthy source status."
            ),
        },
        {
            "id": "M02",
            "priority": "P0",
            "category": "evidence",
            "title": "Close and score due paper positions before opening replacements",
            "status": "action-now" if close_now or review_today else "clear",
            "why": "Open simulations do not become evidence until exits are priced, reconciled, and scored.",
            "action": f"Resolve {close_now} close-now and {review_today} review-today paper positions using executable bid/ask marks.",
            "doneWhen": "No due exits remain and every closed ticket has realized R and slippage.",
        },
        {
            "id": "M03",
            "priority": "P0",
            "category": "strategy",
            "title": "Gate long volatility on an explicit premium hurdle",
            "status": (
                "implemented-guarding"
                if (expected_move.get("regimeDiagnostics") or expectancy)
                else "action-now" if closed_long_vol and long_vol_move_edge < 0
                else "collect-data"
            ),
            "why": (
                f"The desk has {closed_long_vol} long-vol observations; beat rate is "
                f"{long_vol_beat_rate:.1%} and mean realized-minus-implied move is {long_vol_move_edge:.2f}%."
            ),
            "action": "Admit long vol only when the thesis explains why realized movement or IV expansion should exceed premium, decay, and spread friction.",
            "doneWhen": "Each long-vol candidate records implied move, forecast realized move, IV scenario, break-even, and rejection reason.",
        },
        {
            "id": "M04",
            "priority": "P0",
            "category": "discipline",
            "title": "Create a precommitted trade decision card",
            "status": "implemented" if process_compliance else "build-next",
            "why": "OIC guidance supports defining profit and maximum-loss exits before entry; the card also makes process auditable.",
            "action": "Store thesis, disconfirming evidence, max loss, profit plan, time stop, net Greeks, liquidity, and no-trade reason.",
            "doneWhen": "No paper ticket can enter the comparison cohort without a complete card.",
        },
        {
            "id": "M05",
            "priority": "P1",
            "category": "portfolio",
            "title": "Budget correlated portfolio heat",
            "status": "implemented-watch" if portfolio_heat else (
                "action-now" if number(sizing_current.get("equityPct")) > 0.5 else "monitor"
            ),
            "why": "Different AI, compute, power, and crypto-miner tickers can fail together even when position count looks diversified.",
            "action": "Cap new exposure by theme, correlation cluster, total NLV, and worst-case loss rather than by ticker count.",
            "doneWhen": "Every candidate shows incremental theme heat and portfolio max-loss contribution.",
        },
        {
            "id": "M06",
            "priority": "P1",
            "category": "measurement",
            "title": "Normalize outcomes in R and include friction",
            "status": "implemented" if expectancy else "build-next",
            "why": f"Only {scored_outcomes} strategy outcome(s) currently count toward promotion evidence.",
            "action": "Report entry risk, gross R, spread/slippage, net R, hold time, and strategy family for every close.",
            "doneWhen": "Strategy-family expectancy and drawdown can be compared on the same risk scale.",
        },
        {
            "id": "M07",
            "priority": "P1",
            "category": "behavior",
            "title": "Add turnover and disposition-effect audits",
            "status": "implemented-watch" if behavior else "build-next",
            "why": "Academic evidence links heavy retail trading to lower net returns and documents selling winners faster than losers.",
            "action": "Track turnover, trades per session, winner/loser hold time, rule exceptions, and immediate same-ticker re-entry.",
            "doneWhen": "The monthly review can distinguish edge from activity and disciplined exits from loss avoidance.",
        },
        {
            "id": "M08",
            "priority": "P1",
            "category": "experimentation",
            "title": "Run DTE and exit-policy cohorts instead of hard-coding folklore",
            "status": "implemented-research" if dte_policy else "research",
            "why": "Thirty-to-45 DTE and 21-DTE exits are useful practitioner hypotheses, not universal laws across every structure and regime.",
            "action": "Compare matched cohorts by strategy, entry DTE, exit DTE, profit target, stop, IV regime, and event proximity.",
            "doneWhen": "The desk adopts a rule only after net-R and drawdown evidence beats the alternative.",
        },
        {
            "id": "M09",
            "priority": "P2",
            "category": "strategy",
            "title": "Keep the wheel as a shadow feasibility study",
            "status": "implemented-shadow-only" if wheel_shadow else "shadow-only",
            "why": "Cash-secured puts require 100-share capital, retain substantial downside, and would add long exposure while the equity sleeve is already above target.",
            "action": "Measure assignment capital, yield after spread, downside at stress prices, and opportunity cost without staging.",
            "doneWhen": "The structure fits account capital and portfolio targets and beats a share-limit-order comparison after friction.",
        },
    ]

    next_actions = [
        f"{task['id']}: {task['title']} - {task['action']}"
        for task in tasks
        if task["status"] in {"blocked-on-oauth", "refresh-needed", "action-now", "build-next"}
    ][:6]

    return {
        "generatedAt": current.isoformat(),
        "stage": STAGE,
        "verdict": "research-plan-ready",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "deskSnapshot": {
            "schwabAccountAgeHours": round(account_age, 2) if account_age is not None else None,
            "schwabAccountFresh": account_fresh,
            "schwabOptionsAgeHours": round(options_age, 2) if options_age is not None else None,
            "schwabOptionsFresh": options_fresh,
            "schwabPriceHistoryAgeHours": (
                round(price_history_age, 2) if price_history_age is not None else None
            ),
            "schwabPriceHistoryFresh": price_history_fresh,
            "schwabBrokerDataFresh": broker_data_fresh,
            "netLiquidatingValue": number(account.get("netLiquidatingValue")),
            "cash": number(account.get("totalCash")),
            "equityPct": number(sizing_current.get("equityPct")),
            "liveOptionsMaxLoss": number(sizing_options.get("liveMaxLossDollars")),
            "scoredStrategyOutcomes": scored_outcomes,
            "closedLongVolObservations": closed_long_vol,
            "longVolExpectedMoveBeatRate": long_vol_beat_rate,
            "longVolMeanMoveEdgePct": long_vol_move_edge,
            "expectancyVerdict": expectancy.get("verdict"),
            "dtePolicyVerdict": dte_policy.get("verdict"),
            "behaviorVerdict": behavior.get("verdict"),
            "processComplianceVerdict": process_compliance.get("verdict"),
            "portfolioHeatVerdict": portfolio_heat.get("verdict"),
            "wheelShadowVerdict": wheel_shadow.get("verdict"),
        },
        "operatingRules": [
            "No live options risk until the strategy evidence gate promotes it.",
            "Size from total NLV and correlated portfolio heat, never from available cash alone.",
            "Every trade must define max loss, invalidation, profit plan, and time stop before entry.",
            "Do not add to a losing options trade. A later share purchase must be a separate portfolio decision.",
            "Treat IV rank, DTE, and profit targets as context or testable policies, not universal signals.",
            "After an unplanned trade, size breach, or ignored exit, stop new entries for the session and journal the process failure.",
            "Judge decisions in net R after spreads and slippage; do not let raw dollar P/L set the next trade's size.",
            "Cash is a valid position when the edge, price, data freshness, or portfolio fit is missing.",
        ],
        "claimCorrections": [
            "IV rank above or below a single threshold does not by itself choose debit versus credit; realized-vol expectations, skew, term structure, direction, and event risk also matter.",
            "A 21-DTE exit is a cohort hypothesis, not a universal force-close rule.",
            "The wheel is a stock-acquisition and covered-call process, not a guaranteed small-account edge or a reliable monthly-return target.",
            "A fixed 1-3% monthly return assumption is not suitable for planning or sizing.",
            "Two consecutive losses do not prove the edge changed; de-risking should respond to drawdown, model uncertainty, or process breaches under a predefined policy.",
            "Checklist and journaling claims should be evaluated as process controls unless supported by desk-specific outcome data.",
        ],
        "tasks": tasks,
        "browserNextToDo": browser_curriculum(),
        "nextActions": next_actions,
        "operatorRule": "Research and paper evidence only. No item authorizes a live trade or broker submission.",
    }


def render_plan(payload: dict[str, Any]) -> str:
    """Render the action plan as a concise operator report."""
    snapshot = payload.get("deskSnapshot") or {}
    lines = [
        "Inferno Market Mastery - Browser Next Actions",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Verdict: {payload.get('verdict')}",
        "",
        "Desk evidence:",
        (
            "- Schwab account: "
            f"{snapshot.get('schwabAccountFresh')} | age hours: "
            f"{snapshot.get('schwabAccountAgeHours')}"
        ),
        (
            "- Schwab options: "
            f"{snapshot.get('schwabOptionsFresh')} | age hours: "
            f"{snapshot.get('schwabOptionsAgeHours')}"
        ),
        (
            "- Schwab price history: "
            f"{snapshot.get('schwabPriceHistoryFresh')} | age hours: "
            f"{snapshot.get('schwabPriceHistoryAgeHours')}"
        ),
        f"- NLV / cash: ${snapshot.get('netLiquidatingValue', 0):,.2f} / ${snapshot.get('cash', 0):,.2f}",
        f"- Equity sleeve: {snapshot.get('equityPct', 0):.2%}",
        f"- Live options max loss: ${snapshot.get('liveOptionsMaxLoss', 0):,.2f}",
        f"- Scored strategy outcomes: {snapshot.get('scoredStrategyOutcomes', 0)}",
        (
            "- Long-vol evidence: "
            f"{snapshot.get('closedLongVolObservations', 0)} observations | "
            f"move beat {snapshot.get('longVolExpectedMoveBeatRate', 0):.1%} | "
            f"mean move edge {snapshot.get('longVolMeanMoveEdgePct', 0):+.2f}%"
        ),
        "",
        "Operating rules:",
    ]
    lines.extend(f"- {rule}" for rule in payload.get("operatingRules") or [])
    lines.extend(["", "Next action register:"])
    for task in payload.get("tasks") or []:
        lines.extend(
            [
                f"- {task.get('id')} | {task.get('priority')} | {task.get('status')} | {task.get('title')}",
                f"  Why: {task.get('why')}",
                f"  Do: {task.get('action')}",
                f"  Done: {task.get('doneWhen')}",
            ]
        )
    lines.extend(["", "Claims corrected or downgraded:"])
    lines.extend(f"- {item}" for item in payload.get("claimCorrections") or [])
    lines.extend(["", "Browser learning queue:"])
    for item in payload.get("browserNextToDo") or []:
        lines.extend(
            [
                f"- {item.get('id')} | {item.get('priority')} | {item.get('topic')}",
                f"  Read: {item.get('url')}",
                f"  Question: {item.get('question')}",
                f"  Desk deliverable: {item.get('deliverable')}",
            ]
        )
    lines.extend(["", f"Operator rule: {payload.get('operatorRule')}"])
    return "\n".join(lines).rstrip() + "\n"


def save_plan(payload: dict[str, Any]) -> None:
    """Persist the JSON and text plan artifacts."""
    ensure_dirs()
    atomic_write_json(MARKET_MASTERY_PLAN_FILE, payload)
    atomic_write_text(MARKET_MASTERY_PLAN_TEXT_FILE, render_plan(payload))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the Inferno market mastery plan.")
    parser.add_argument("--quiet", action="store_true", help="Write artifacts without printing the report.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = build_plan()
    save_plan(payload)
    if not args.quiet:
        print(render_plan(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
