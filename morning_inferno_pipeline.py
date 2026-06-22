from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import fcntl
import google.auth
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import gspread
import numpy as np
import pandas as pd
import yfinance as yf
from oauth2client.service_account import ServiceAccountCredentials

from inferno_config import (
    AUTOMATION_ALLOWED_WEEKDAYS,
    AUTOMATION_WINDOW_END,
    AUTOMATION_WINDOW_START,
    DEFAULT_SHEET_NAME,
    LONG_TERM_QUEUE_LIMIT,
    REVIEW_QUEUE_LIMIT,
    ROOT,
    SCORE_FORMULA_COLUMNS,
    UPDATER_LABEL,
    UPDATER_SCRIPTS,
    default_backtest_root,
    in_time_window,
    local_now,
)
from inferno_execution_clerk import build_execution_queue, save_execution_queue
from inferno_heartbeat import record_heartbeat
from inferno_io import append_text, atomic_write_json, atomic_write_text
from inferno_tos_formula_math import (
    build_market_context_from_history as formula_market_context_from_history,
    build_market_context_from_row as formula_market_context_from_row,
    relative_volume_proxy as formula_relative_volume_proxy,
    support_resistance_proxy_from_row as formula_support_resistance_proxy_from_row,
    trend_descriptor_from_row as formula_trend_descriptor_from_row,
    trend_tone_from_label as formula_trend_tone_from_label,
)
from inferno_tos_custom_metrics import load_custom_metrics_by_ticker, summarize_custom_metrics
from inferno_reporting_summary import (
    build_freshness_panel,
    build_tos_visibility_summary,
    render_freshness_lines,
    render_tos_visibility_line,
)
from server import (
    APPROVAL_QUEUE_FILE,
    BRIEF_TEXT_FILE,
    DATA_DIR,
    HTML_BRIEF_FILE,
    LONG_TERM_TEXT_FILE,
    LOG_FILE,
    OPS_STATUS_FILE,
    PAPER_JOURNAL_FILE,
    REPORTS_DIR,
    SNAPSHOT_FILE,
    TICKETS_TEXT_FILE,
    ensure_dirs,
    html_from_payload,
    load_json_file,
    send_email,
    smtp_configured,
)


DEFAULT_BACKTEST_ROOT = default_backtest_root()
LOCK_FILE = DATA_DIR / "inferno_dawn.lock"
MARKET_CONTEXT_AUDIT_FILE = DATA_DIR / "inferno_market_context_audit.json"
MARKET_CONTEXT_AUDIT_TEXT_FILE = REPORTS_DIR / "market_context_audit_latest.txt"
TICKER_UNIVERSE_AUDIT_FILE = DATA_DIR / "inferno_ticker_universe_audit.json"
TICKER_UNIVERSE_AUDIT_TEXT_FILE = REPORTS_DIR / "ticker_universe_audit_latest.txt"
CONVICTION_CONFIG = {
    "min_readiness": 72,
    "min_confidence": 2,
    "max_days_until_earnings": 21,
    "require_trigger": True,
    "banned_setups": {"Avoid"},
}
UPDATER_SCRIPT_RETRIES = 3
UPDATER_SCRIPT_RETRY_DELAY_SECONDS = 8
UPDATER_COLUMN_NA_THRESHOLD = 0.82
GOOGLE_SHEETS_RETRIES = 5
GOOGLE_SHEETS_RETRY_BASE_SECONDS = 3
GOOGLE_SERVICE_ACCOUNT_ENV = "GOOGLE_SERVICE_ACCOUNT_JSON"
GOOGLE_SERVICE_ACCOUNT_B64_ENV = "GOOGLE_SERVICE_ACCOUNT_JSON_B64"
EARNINGS_DATE_LOOKAHEAD_DAYS = 370
EARNINGS_QUARTER_ROLL_DAYS = 91
UNKNOWN_EARNINGS_DAYS = 999
UPDATER_COLUMN_MAP = {
    "BC-ATRPercentandIVRANK.py": ("B", "C"),
    "P-IV RANK CHANGE.py": ("P",),
    "Q-ATRPcntZScore.py": ("Q",),
    "R-20DayATR.py": ("R",),
}
MARKET_CONTEXT_COLUMNS = ("Z", "AA", "AB", "AC", "AD", "AE")
MARKET_CONTEXT_HEADERS = (
    "$RVOL",
    "Trend",
    "Support",
    "Resistance",
    "% To Support",
    "% To Resistance",
)
TICKER_UNIVERSE_REQUIRED_HEADERS = (
    "Ticker",
    "ATR%",
    "IV Rank",
    "Next Earnings",
    "Price",
    "Days until earnings",
    "Setup Rec",
    '"Urgency"',
    "Signal Trigger",
    "Confidence (3 MAX)",
    "IV Rank Change (5-day delta)",
    "ATR% Z-Score",
    "20 Day ATR",
    "REC 1-13",
    "Rec2",
    "Value Score",
    "Momentum Score",
    "Squeeze Score",
    "Ready Score",
    "Priority",
    *MARKET_CONTEXT_HEADERS,
)
TICKER_UNIVERSE_ADVISORY_HEADERS = (
    "EPS",
    "PE",
)
ALLOWED_TREND_LABELS = {
    "Bullish",
    "Bearish",
    "Basing",
    "Neutral",
    "Uptrend",
    "Downtrend",
    "Range",
    "Breakout",
    "Breakdown",
}
HISTORY_CACHE: dict[tuple[str, str, str], pd.DataFrame] = {}


class PipelineLockActive(RuntimeError):
    pass


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key] = value


@contextmanager
def acquire_run_lock() -> Any:
    ensure_dirs()
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = LOCK_FILE.open("w", encoding="utf-8")
    try:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PipelineLockActive("another inferno pipeline run is already active") from exc
        lock_handle.write(json.dumps({"pid": os.getpid(), "startedAt": datetime.now().astimezone().isoformat()}))
        lock_handle.flush()
        yield
    finally:
        try:
            lock_handle.seek(0)
            lock_handle.truncate(0)
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        finally:
            lock_handle.close()


def already_sent_today() -> bool:
    ops_status = load_json_file(OPS_STATUS_FILE) or {}
    generated_at = str(ops_status.get("generatedAt", ""))
    today = local_now().date().isoformat()
    return generated_at.startswith(today) and ops_status.get("ok") and ops_status.get("emailSent")


def automation_skip_reason(window_start: str, window_end: str) -> str | None:
    now = local_now()
    if now.weekday() not in AUTOMATION_ALLOWED_WEEKDAYS:
        return "Skipping automated dawn cycle: Saturday automation is disabled."
    if not in_time_window(now, window_start, window_end):
        return (
            "Skipping automated dawn cycle: "
            f"{now.strftime('%H:%M')} is outside the {window_start}-{window_end} mountain-time window."
        )
    if already_sent_today():
        return "Skipping automated dawn cycle: today's market snapshot already sent successfully."
    return None


def clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def score_to_percent(value: float, ceiling: float = 2.5) -> float:
    return clamp((value / ceiling) * 100, 0, 100)


def setup_weight(setup_rec: str) -> int:
    lowered = str(setup_rec).lower()
    if "vertical" in lowered:
        return 13
    if "straddle" in lowered:
        return 11
    if "condor" in lowered:
        return 8
    if "avoid" in lowered:
        return -10
    return 0


def urgency_weight(urgency: str) -> int:
    lowered = str(urgency).lower()
    if "urgent" in lowered:
        return 18
    if "watch" in lowered:
        return 8
    if "avoid" in lowered:
        return -16
    return 0


def readiness_label(readiness: float) -> str:
    if readiness >= 72:
        return "Ready"
    if readiness >= 48:
        return "Watch"
    return "Avoid"


def number_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        parsed = float(value)
        return parsed if np.isfinite(parsed) else None
    cleaned = str(value or "").replace("$", "").replace(",", "").strip()
    if not cleaned or cleaned.upper() == "N/A" or cleaned == "#N/A":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "2026-05-01"

    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return "2026-05-01"


def parse_sheet_date(value: Any) -> date | None:
    """Parse a sheet/provider earnings date without falling back to a fake date."""
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if hasattr(value, "date") and callable(value.date):
        try:
            parsed = value.date()
            if hasattr(parsed, "year"):
                return parsed
        except Exception:  # noqa: BLE001
            pass

    text = str(value or "").strip()
    if not text or text.upper() in {"N/A", "#N/A", "NONE", "NAN", "NULL"}:
        return None

    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def format_sheet_date(value: date) -> str:
    """Use Sheets-friendly US dates to match the existing tracker style."""
    return f"{value.month}/{value.day}/{value.year}"


def roll_date_forward_quarterly(anchor: date, today: date) -> date:
    """Roll a stale earnings date forward by quarters until it is actionable again."""
    candidate = anchor
    while candidate < today:
        # Quarterly earnings are not perfectly 91 days apart, but this prevents
        # stale provider dates from creating negative timing and false urgency.
        candidate = candidate + timedelta(days=EARNINGS_QUARTER_ROLL_DAYS)
    return candidate


def normalize_earnings_candidate(value: Any) -> date | None:
    """Normalize yfinance calendar/date values into a plain date."""
    if isinstance(value, (list, tuple, set)):
        parsed_values = [normalize_earnings_candidate(item) for item in value]
        parsed_values = [item for item in parsed_values if item is not None]
        return min(parsed_values) if parsed_values else None
    return parse_sheet_date(value)


def collect_yfinance_earnings_candidates(ticker: str) -> list[tuple[date, str]]:
    """Collect possible earnings dates from yfinance without trusting one endpoint blindly."""
    candidates: list[tuple[date, str]] = []
    stock = yf.Ticker(ticker)

    try:
        calendar = stock.get_calendar()
        earnings_date = normalize_earnings_candidate(calendar.get("Earnings Date") if isinstance(calendar, dict) else None)
        if earnings_date:
            candidates.append((earnings_date, "yfinance_calendar"))
    except Exception:  # noqa: BLE001
        pass

    try:
        earnings_dates = stock.get_earnings_dates(limit=12)
        if earnings_dates is not None and not earnings_dates.empty:
            for raw_index in earnings_dates.index:
                parsed = parse_sheet_date(raw_index)
                if parsed:
                    candidates.append((parsed, "yfinance_earnings_dates"))
    except Exception:  # noqa: BLE001
        # Some yfinance builds need optional HTML parsing dependencies for this
        # endpoint. The calendar endpoint plus quarterly projection remains safe.
        pass

    return candidates


def resolve_next_earnings_date(
    ticker: str,
    existing_date: date | None,
    today: date,
) -> tuple[date | None, str]:
    """Resolve a non-negative next earnings date for one ticker."""
    candidates = collect_yfinance_earnings_candidates(ticker)
    latest_actionable_date = today + timedelta(days=EARNINGS_DATE_LOOKAHEAD_DAYS)
    future_candidates = [
        (value, source)
        for value, source in candidates
        if today <= value <= latest_actionable_date
    ]
    if future_candidates:
        return min(future_candidates, key=lambda item: item[0])

    if existing_date and existing_date >= today:
        return existing_date, "existing_future"

    stale_candidates = [value for value, _source in candidates if value < today]
    if stale_candidates:
        latest_stale = max(stale_candidates)
        return roll_date_forward_quarterly(latest_stale, today), "projected_from_stale_yfinance"

    if existing_date:
        return roll_date_forward_quarterly(existing_date, today), "projected_from_existing"

    return None, "unresolved"


def safe_days_until_earnings(next_earnings: str, raw_days: int) -> int:
    """Prevent stale negative days from entering ranking logic if sync is skipped."""
    if raw_days >= 0:
        return raw_days
    parsed = parse_sheet_date(next_earnings)
    if parsed and parsed >= local_now().date():
        return (parsed - local_now().date()).days
    return UNKNOWN_EARNINGS_DAYS


def normalize_trigger(value: Any) -> bool:
    text = str(value or "").strip()
    lowered = text.lower()
    return text == "1" or "true" in lowered or "yes" in lowered or "✅" in text


def valuation_bonus(pe: float | None) -> float:
    if pe is None or pe <= 0:
        return 0.0
    if pe <= 20:
        return 0.55
    if pe <= 35:
        return 0.35
    if pe <= 50:
        return 0.12
    return -0.18


def calculate_long_term_score(row: dict[str, Any]) -> float:
    cooled_off = clamp(1.6 - row["momentumScore"], 0.0, 1.6)
    non_chase = clamp((78 - row["readiness"]) / 30, 0.0, 1.2)
    timing = 0.45 if row["daysUntilEarnings"] >= 10 else 0.1 if row["daysUntilEarnings"] >= 5 else -0.25
    profitability = 0.35 if row["eps"] > 0 else -0.2
    trigger_bonus = 0.15 if not row["signalTrigger"] else -0.18
    setup_penalty = -0.35 if row["setupRec"] == "Avoid" else 0.0
    score = (
        row["valueScore"] * 1.9
        + row["squeezeScore"] * 1.1
        + cooled_off
        + non_chase
        + timing
        + profitability
        + valuation_bonus(row.get("pe"))
        + trigger_bonus
        + setup_penalty
    )
    return round(clamp(score, 0.0, 9.99), 2)


def build_accumulation_bias(score: float) -> dict[str, str]:
    if score >= 4.4:
        return {
            "label": "Accumulate",
            "note": "Conviction is high and the name is calm enough to buy without chasing it.",
        }
    if score >= 3.2:
        return {
            "label": "Nibble",
            "note": "The setup is worth building slowly, but the discount is not screaming yet.",
        }
    return {
        "label": "Wait For Weakness",
        "note": "You may want the name, but the price does not deserve urgency right now.",
    }


def accumulation_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row["valueScore"] >= 1.0:
        reasons.append("value stack is still doing real work")
    if row["squeezeScore"] >= 1.0:
        reasons.append("the name is compressed instead of euphoric")
    if row["momentumScore"] <= 0.35:
        reasons.append("the move is not already extended")
    if row["readiness"] <= 68:
        reasons.append("it is not in full chase mode")
    if row["eps"] > 0:
        reasons.append("the business is still printing earnings")
    pe = row.get("pe")
    if pe is not None and pe > 0 and pe <= 35:
        reasons.append("valuation still lives in a sane range")
    if not reasons:
        reasons.append("conviction is intact, but price heat is still restrained")
    return reasons[:3]


def enrich_row(row: dict[str, Any]) -> dict[str, Any]:
    timing_score = 16 if row["daysUntilEarnings"] <= 7 else 20 if row["daysUntilEarnings"] <= 21 else 17 if row["daysUntilEarnings"] <= 35 else 9
    trigger_score = 14 if row["signalTrigger"] else 0
    confidence_score = (row["confidence"] / 3) * 24
    iv_momentum_score = clamp(row["ivRankChange"] * 65, -8, 10)
    volatility_score = clamp((row["ivRank"] / 50) * 12 + (row["atrPercent"] / 10) * 10, 0, 20)
    score_blend = (
        score_to_percent(row["readyScore"]) * 0.28
        + score_to_percent(row["squeezeScore"]) * 0.18
        + score_to_percent(row["momentumScore"]) * 0.18
        + score_to_percent(row["valueScore"]) * 0.12
    )
    readiness = clamp(
        timing_score
        + trigger_score
        + confidence_score
        + iv_momentum_score
        + volatility_score
        + setup_weight(row["setupRec"])
        + urgency_weight(row["urgency"])
        + score_blend * 0.32,
        8,
        99,
    )

    priority_raw = row.get("priority")
    if priority_raw is None or not isinstance(priority_raw, (int, float)):
        priority_raw = row["valueScore"] + row["momentumScore"] + row["squeezeScore"] + row["readyScore"]

    row["priority"] = round(float(priority_raw), 2)
    row["readiness"] = int(round(readiness))
    row["status"] = readiness_label(readiness)
    row["longTermScore"] = calculate_long_term_score(row)
    row["accumulationBias"] = build_accumulation_bias(row["longTermScore"])
    row["discountReasons"] = accumulation_reasons(row)
    row["tosCustomSignalSummary"] = summarize_custom_metrics(row.get("tosCustomMetrics"))
    row["marketContext"] = build_market_context(row)
    return row


def gate_checks(row: dict[str, Any]) -> dict[str, bool]:
    return {
        "readiness": row["readiness"] >= CONVICTION_CONFIG["min_readiness"],
        "confidence": row["confidence"] >= CONVICTION_CONFIG["min_confidence"],
        "timing": row["daysUntilEarnings"] <= CONVICTION_CONFIG["max_days_until_earnings"],
        "trigger": row["signalTrigger"] if CONVICTION_CONFIG["require_trigger"] else True,
        "setup": row["setupRec"] not in CONVICTION_CONFIG["banned_setups"],
    }


def gate_failures(row: dict[str, Any]) -> list[str]:
    messages = {
        "readiness": "readiness below threshold",
        "confidence": "confidence too low",
        "timing": "too far from earnings",
        "trigger": "trigger not live",
        "setup": "setup blocked",
    }
    return [messages[key] for key, passed in gate_checks(row).items() if not passed]


def get_eligible_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if not gate_failures(row)]


def select_review_candidates(rows: list[dict[str, Any]], limit: int = REVIEW_QUEUE_LIMIT) -> list[dict[str, Any]]:
    return get_eligible_candidates(rows)[:limit]


def get_long_term_candidates(rows: list[dict[str, Any]], limit: int = LONG_TERM_QUEUE_LIMIT) -> list[dict[str, Any]]:
    candidates = [
        row
        for row in rows
        if row["longTermScore"] >= 2.8
        and row["valueScore"] >= 0.75
        and (row["eps"] > 0 or row["priority"] >= 3.6)
    ]
    candidates.sort(
        key=lambda row: (
            -row["longTermScore"],
            -row["valueScore"],
            row["readiness"],
            row["daysUntilEarnings"],
        )
    )
    return candidates[:limit]


def build_narrative(row: dict[str, Any]) -> str:
    if row["daysUntilEarnings"] <= 10:
        timing = "The catalyst window is almost here, so precision matters more than panic and greed."
    elif row["daysUntilEarnings"] <= 30:
        timing = "The event sits in the strike zone, where disciplined names start separating from the pretenders."
    else:
        timing = "This one is still earlier in the cycle, so it feels more like stalking prey than swinging the blade."

    signal = (
        "Your signal trigger is already active, which means the market has stopped whispering and started confessing."
        if row["signalTrigger"]
        else "The trigger has not fired yet, so this stays chained until price action proves it belongs in the arena."
    )
    setup = (
        "The setup recommendation is defensive, so treat the name like a cursed relic: study it, but do not worship it."
        if row["setupRec"] == "Avoid"
        else f"The current setup bias favors {row['setupRec'].lower()} structures."
    )
    return f"{timing} {signal} {setup}"


def build_morning_brief(rows: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    eligible = get_eligible_candidates(rows)
    long_term = get_long_term_candidates(rows)
    headline = (
        f"{eligible[0]['ticker']} leads the board at {eligible[0]['readiness']}% readiness."
        if eligible
        else "No full-conviction names passed every gate today."
    )

    lines = [
        "Morning Brief",
        headline,
        "",
        f"Total tracked: {len(rows)}",
        f"Eligible now: {len(eligible)}",
        f"Triggered names: {sum(1 for row in rows if row['signalTrigger'])}",
        "",
        "Top recommendations:",
    ]

    recommended = eligible[:REVIEW_QUEUE_LIMIT] if eligible else rows[:3]
    eligible_tickers = {row["ticker"] for row in eligible}
    for index, row in enumerate(recommended, start=1):
        failure_text = "all gates clear" if row["ticker"] in eligible_tickers else ", ".join(gate_failures(row))
        context = row.get("marketContext") or {}
        trend = context.get("trend") or {}
        confirmation = (
            f"RVOL {context.get('rvol', 'N/A')}x | "
            f"{trend.get('label', 'Neutral')} | "
            f"S {context.get('support', 'N/A')} / R {context.get('resistance', 'N/A')}"
        )
        lines.append(
            f"{index}. {row['ticker']} | {row['setupRec']} | {row['readiness']}% | {row['daysUntilEarnings']}d | "
            f"{'trigger live' if row['signalTrigger'] else 'waiting'} | {failure_text} | {confirmation}"
        )

    lines.extend(["", "Prime thesis:"])
    for row in recommended[:3]:
        lines.append(f"- {row['ticker']}: {build_narrative(row)}")

    lines.extend(["", "Long-Term Accumulation Lane:"])
    if long_term:
        for index, row in enumerate(long_term, start=1):
            reasons = "; ".join(row["discountReasons"][:2])
            lines.append(
                f"{index}. {row['ticker']} | {row['accumulationBias']['label']} | score {row['longTermScore']} | {reasons}"
            )
    else:
        lines.append("No names are cheap enough in the current stack to justify a conviction buy today.")

    lines.extend(
        [
            "",
            "Long-term rule:",
            "- Only add here if you would still want to own the name six to twelve months from now.",
        ]
    )

    return "\n".join(lines), eligible, recommended


def build_long_term_brief(rows: list[dict[str, Any]]) -> str:
    candidates = get_long_term_candidates(rows)
    lines = ["Long-Term Accumulation Lane", ""]
    if not candidates:
        lines.append("No names are cheap enough in the current stack to justify a conviction buy today.")
        return "\n".join(lines)

    for index, row in enumerate(candidates, start=1):
        reasons = "; ".join(row["discountReasons"])
        lines.append(
            f"{index}. {row['ticker']} | {row['accumulationBias']['label']} | score {row['longTermScore']} | {reasons}"
        )

    lines.extend(
        [
            "",
            "Rule:",
            "Only add here if you would still want to own the name if the market did nothing for the next six to twelve months.",
        ]
    )
    return "\n".join(lines)


def build_paper_tickets(rows: list[dict[str, Any]]) -> str:
    picks = select_review_candidates(rows)
    if not picks:
        return "No paper tickets generated. No names passed every conviction gate."

    blocks = []
    for index, row in enumerate(picks, start=1):
        blocks.append(
            "\n".join(
                [
                    f"Ticket {index}: {row['ticker']}",
                    f"Setup: {row['setupRec']}",
                    f"Readiness: {row['readiness']}%",
                    f"Timing: {row['daysUntilEarnings']} days to earnings",
                    f"Trigger: {'LIVE' if row['signalTrigger'] else 'WAIT'}",
                    f"Primary route: {row['rec1']}",
                    f"Secondary route: {row['rec2']}",
                    "Risk note: paper trade only until live execution rules are proven.",
                ]
            )
        )
    return "\n\n".join(blocks)


def make_gspread_client(backtest_root: Path) -> gspread.Client:
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    service_account_json = os.environ.get(GOOGLE_SERVICE_ACCOUNT_ENV, "").strip()
    if service_account_json:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(service_account_json), scope)
        return gspread.authorize(creds)

    service_account_json_b64 = os.environ.get(GOOGLE_SERVICE_ACCOUNT_B64_ENV, "").strip()
    if service_account_json_b64:
        decoded_json = base64.b64decode(service_account_json_b64.encode("utf-8")).decode("utf-8")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(decoded_json), scope)
        return gspread.authorize(creds)

    application_creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if application_creds_path:
        creds = ServiceAccountCredentials.from_json_keyfile_name(str(Path(application_creds_path).expanduser()), scope)
        return gspread.authorize(creds)

    creds_path = backtest_root / "gcred.json"
    if creds_path.exists():
        creds = ServiceAccountCredentials.from_json_keyfile_name(str(creds_path), scope)
        return gspread.authorize(creds)

    # Cloud Run can use its own bound service account directly, which lets us
    # avoid shipping the Sheets key JSON into the runtime when the service
    # account itself already has access to the tracker.
    ambient_creds, _project_id = google.auth.default(scopes=scope)
    return gspread.authorize(ambient_creds)


def get_sheet(backtest_root: Path, sheet_name: str):
    client = make_gspread_client(backtest_root)
    return google_sheets_call(f"open {sheet_name}", lambda: client.open(sheet_name).sheet1)


def read_sheet_table(backtest_root: Path, sheet_name: str) -> tuple[list[str], list[list[str]]]:
    """Return tracker headers and raw sheet rows for downstream audits."""
    sheet = get_sheet(backtest_root, sheet_name)
    raw_rows = google_sheets_call("read final tracker rows", lambda: sheet.get_all_values())
    if not raw_rows:
        return [], []
    headers = [header.strip() for header in raw_rows[0]]
    return headers, raw_rows[1:]


def looks_like_date(value: str) -> bool:
    text = value.strip()
    return bool(re.match(r"^\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}$", text))


def looks_like_ticker(value: str) -> bool:
    text = value.strip().upper().replace("$", "")
    if not text or looks_like_date(text):
        return False
    if "/" in text or " " in text:
        return False
    return bool(re.match(r"^[A-Z0-9\.\-\^=]{1,12}$", text))


def load_tracker_ticker_rows(sheet) -> tuple[list[str], list[str], list[bool]]:
    raw_rows = google_sheets_call("read ticker column", lambda: sheet.col_values(1)[1:])
    tickers: list[str] = []
    invalid_mask: list[bool] = []
    for entry in raw_rows:
        cleaned = str(entry).strip().replace("$", "")
        if looks_like_ticker(cleaned):
            tickers.append(cleaned.upper())
            invalid_mask.append(False)
        else:
            tickers.append(cleaned)
            invalid_mask.append(True)
    return raw_rows, tickers, invalid_mask


def sleep_for_retry(attempt: int, base_seconds: int = UPDATER_SCRIPT_RETRY_DELAY_SECONDS) -> None:
    time.sleep(min(30, base_seconds * attempt))


def google_sheets_call(operation: str, func, attempts: int = GOOGLE_SHEETS_RETRIES):
    """Run a Google Sheets operation with retry/backoff for transient disconnects.

    Google occasionally drops the HTTP connection after the updater work has
    already succeeded. Retrying at the sheet boundary keeps one flaky API call
    from killing the entire morning email.
    """
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == attempts:
                break
            sleep_for_retry(attempt, base_seconds=GOOGLE_SHEETS_RETRY_BASE_SECONDS)
    raise RuntimeError(f"Google Sheets {operation} failed after {attempts} attempts: {last_error}")


def update_sheet_range(sheet, range_name: str, values: list[list[Any]], attempts: int = 4) -> None:
    google_sheets_call(
        f"update {range_name}",
        lambda: sheet.update(range_name=range_name, values=values, value_input_option="USER_ENTERED"),
        attempts=attempts,
    )


def download_history_with_retries(
    symbol: str,
    *,
    period: str,
    interval: str = "1d",
    retries: int = 4,
) -> pd.DataFrame:
    cache_key = (symbol.upper(), period, interval)
    cached_history = HISTORY_CACHE.get(cache_key)
    if cached_history is not None:
        return cached_history.copy()

    last_error = None
    for attempt in range(retries):
        try:
            history = yf.download(
                symbol,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
                threads=False,
            )
            if history is not None and not history.empty:
                if isinstance(history.columns, pd.MultiIndex):
                    history = history.copy()
                    history.columns = history.columns.get_level_values(0)
                cleaned_history = history.dropna()
                HISTORY_CACHE[cache_key] = cleaned_history.copy()
                return cleaned_history.copy()
            last_error = RuntimeError("empty price history")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(min(8, 1.6**attempt))

    # Some watchlist names are intentionally broad or occasionally unsupported
    # by the data vendor. Return an empty but schema-stable frame so callers can
    # degrade to N/A instead of failing the entire refresh run.
    empty_history = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Adj Close", "Volume"])
    HISTORY_CACHE[cache_key] = empty_history.copy()
    return empty_history.copy()


def compute_true_range(history: pd.DataFrame) -> pd.Series:
    high = pd.to_numeric(history["High"], errors="coerce")
    low = pd.to_numeric(history["Low"], errors="coerce")
    close = pd.to_numeric(history["Close"], errors="coerce")
    previous_close = close.shift()
    return pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def compute_option_iv_rank(symbol: str) -> str | float:
    try:
        stock = yf.Ticker(symbol)
        expiries = stock.options
        if not expiries:
            return "N/A"
        chain = stock.option_chain(expiries[0])
        iv_series = pd.concat(
            [
                chain.calls.get("impliedVolatility", pd.Series(dtype=float)).dropna(),
                chain.puts.get("impliedVolatility", pd.Series(dtype=float)).dropna(),
            ]
        )
        if iv_series.empty:
            return "N/A"

        iv_now = float(iv_series.mean())
        iv_min = float(iv_series.min())
        iv_max = float(iv_series.max())
        spread = iv_max - iv_min
        if np.isclose(spread, 0.0):
            return 50.0
        return round(((iv_now - iv_min) / spread) * 100, 4)
    except Exception:
        return "N/A"


def compute_iv_rank_change_value(symbol: str) -> str | float:
    try:
        history = download_history_with_retries(symbol, period="6mo")
        close = pd.to_numeric(history["Close"], errors="coerce").dropna()
        if len(close) < 30:
            return "N/A"
        returns = close.pct_change().dropna()
        iv_proxy = returns.rolling(window=20).std().dropna()
        if len(iv_proxy) < 6:
            return "N/A"
        spread = float(iv_proxy.max() - iv_proxy.min())
        if np.isclose(spread, 0.0):
            return 0.0
        iv_rank = (iv_proxy - float(iv_proxy.min())) / spread
        return round(float(iv_rank.iloc[-1] - iv_rank.iloc[-6]), 4)
    except Exception:
        return "N/A"


def compute_atr_percent_zscore_value(symbol: str, lookback: int = 20) -> str | float:
    try:
        history = download_history_with_retries(symbol, period="2mo")
        if len(history) < lookback + 5:
            return "N/A"
        tr = compute_true_range(history)
        close = pd.to_numeric(history["Close"], errors="coerce")
        atr = tr.rolling(window=14).mean()
        atr_percent = (atr / close * 100).dropna()
        recent = atr_percent.tail(lookback)
        if len(recent) < lookback:
            return "N/A"
        std = float(recent.std())
        if np.isclose(std, 0.0):
            return 0.0
        return round(float((recent.iloc[-1] - recent.mean()) / std), 4)
    except Exception:
        return "N/A"


def trend_tone_from_label(label: str) -> str:
    return formula_trend_tone_from_label(label)


def relative_volume_proxy(row: dict[str, Any]) -> float:
    return formula_relative_volume_proxy(row)


def build_trend_descriptor(row: dict[str, Any]) -> dict[str, str]:
    return formula_trend_descriptor_from_row(row)


def build_support_resistance_proxy(row: dict[str, Any]) -> dict[str, float]:
    return formula_support_resistance_proxy_from_row(row)


def compute_market_context_from_history(
    history: pd.DataFrame,
    *,
    price: float | None = None,
    atr_z_score: float | None = None,
    iv_rank_change: float | None = None,
) -> dict[str, Any]:
    return formula_market_context_from_history(
        history,
        price=price,
        atr_z_score=atr_z_score,
        iv_rank_change=iv_rank_change,
    )


def compute_market_context_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    history = download_history_with_retries(str(row.get("ticker") or "").strip().upper(), period="6mo")
    return compute_market_context_from_history(
        history,
        price=number_or_none(row.get("price")),
        atr_z_score=number_or_none(row.get("atrZScore")),
        iv_rank_change=number_or_none(row.get("ivRankChange")),
    )


def build_market_context(row: dict[str, Any]) -> dict[str, Any]:
    return formula_market_context_from_row(row, unknown_earnings_days=UNKNOWN_EARNINGS_DAYS)


def sync_bc_columns(backtest_root: Path, sheet_name: str) -> dict[str, Any]:
    sheet = get_sheet(backtest_root, sheet_name)
    raw_rows, tickers, invalid_mask = load_tracker_ticker_rows(sheet)
    output: list[list[Any]] = []
    for ticker, invalid in zip(tickers, invalid_mask):
        if invalid:
            output.append(["N/A", "N/A"])
            continue
        try:
            history = download_history_with_retries(ticker, period="6mo")
            if len(history) < 15:
                output.append(["N/A", "N/A"])
                continue
            tr = compute_true_range(history)
            atr = tr.rolling(window=14).mean()
            close = pd.to_numeric(history["Close"], errors="coerce")
            atr_pct = (atr.iloc[-1] / close.iloc[-1] * 100) if not atr.empty and pd.notna(close.iloc[-1]) else None
            output.append([round(float(atr_pct), 4) if atr_pct is not None and pd.notna(atr_pct) else "N/A", compute_option_iv_rank(ticker)])
        except Exception:
            output.append(["N/A", "N/A"])
    update_sheet_range(sheet, f"B2:C{len(raw_rows) + 1}", output)
    return {"recoveredBy": "internal BC sync", "rows": len(raw_rows)}


def sync_p_column(backtest_root: Path, sheet_name: str) -> dict[str, Any]:
    sheet = get_sheet(backtest_root, sheet_name)
    raw_rows, tickers, invalid_mask = load_tracker_ticker_rows(sheet)
    values = [["N/A" if invalid else compute_iv_rank_change_value(ticker)] for ticker, invalid in zip(tickers, invalid_mask)]
    update_sheet_range(sheet, f"P2:P{len(raw_rows) + 1}", values)
    return {"recoveredBy": "internal P sync", "rows": len(raw_rows)}


def sync_q_column(backtest_root: Path, sheet_name: str) -> dict[str, Any]:
    sheet = get_sheet(backtest_root, sheet_name)
    raw_rows, tickers, invalid_mask = load_tracker_ticker_rows(sheet)
    values = [["N/A" if invalid else compute_atr_percent_zscore_value(ticker)] for ticker, invalid in zip(tickers, invalid_mask)]
    update_sheet_range(sheet, f"Q2:Q{len(raw_rows) + 1}", values)
    return {"recoveredBy": "internal Q sync", "rows": len(raw_rows)}


def sync_r_column(backtest_root: Path, sheet_name: str) -> dict[str, Any]:
    sheet = get_sheet(backtest_root, sheet_name)
    raw_rows, tickers, invalid_mask = load_tracker_ticker_rows(sheet)
    values = [["N/A" if invalid else calculate_20day_atr_fixed(ticker)] for ticker, invalid in zip(tickers, invalid_mask)]
    update_sheet_range(sheet, f"R2:R{len(raw_rows) + 1}", values)
    return {"recoveredBy": "internal R sync", "rows": len(raw_rows)}


def sync_market_context_columns(backtest_root: Path, sheet_name: str) -> dict[str, Any]:
    sheet = get_sheet(backtest_root, sheet_name)
    ensure_sheet_has_columns(sheet, column_number(MARKET_CONTEXT_COLUMNS[-1]))
    raw_rows = google_sheets_call("read market context source rows", lambda: sheet.get_all_values())
    if len(raw_rows) < 2:
        return {"recoveredBy": "internal market context sync", "rows": 0, "updated": 0, "reason": "no rows"}

    headers = [header.strip() for header in raw_rows[0]]
    index_map = {header: idx for idx, header in enumerate(headers)}

    def read(cells: list[str], header: str) -> str:
        idx = index_map.get(header)
        if idx is None or idx >= len(cells):
            return ""
        value = str(cells[idx]).strip()
        return "" if is_bad_sheet_value(value) else value

    data_rows = raw_rows[1:]
    values: list[list[Any]] = []
    updated = 0
    for cells in data_rows:
        ticker = read(cells, "Ticker").strip().upper().replace("$", "")
        if not looks_like_ticker(ticker):
            values.append(["N/A", "N/A", "N/A", "N/A", "N/A", "N/A"])
            continue

        source_row = {
            "ticker": ticker,
            "price": number_or_none(read(cells, "Price")),
            "atrZScore": number_or_none(read(cells, "ATR% Z-Score")),
            "ivRankChange": number_or_none(read(cells, "IV Rank Change (5-day delta)")),
        }
        try:
            context = compute_market_context_snapshot(source_row)
            values.append(
                [
                    context["rvol"],
                    context["trend"]["label"],
                    context["support"],
                    context["resistance"],
                    context["distanceToSupportPct"],
                    context["distanceToResistancePct"],
                ]
            )
            updated += 1
        except Exception:
            values.append(["N/A", "N/A", "N/A", "N/A", "N/A", "N/A"])

    update_sheet_range(
        sheet,
        f"{MARKET_CONTEXT_COLUMNS[0]}1:{MARKET_CONTEXT_COLUMNS[-1]}1",
        [list(MARKET_CONTEXT_HEADERS)],
    )
    update_sheet_range(
        sheet,
        f"{MARKET_CONTEXT_COLUMNS[0]}2:{MARKET_CONTEXT_COLUMNS[-1]}{len(raw_rows)}",
        values,
    )
    return {"recoveredBy": "internal market context sync", "rows": len(raw_rows) - 1, "updated": updated}


def is_bad_sheet_value(value: Any) -> bool:
    """Return True when a sheet cell shows a formula or data vendor error."""
    text = str(value or "").strip()
    return bool(text) and text.startswith("#")


def fallback_setup_recommendation(row: dict[str, Any]) -> str:
    """Choose a conservative setup fallback when the sheet formula path breaks."""
    if row.get("setupRec") and not is_bad_sheet_value(row.get("setupRec")):
        return str(row.get("setupRec")).strip() or "Watchlist"
    if row.get("signalTrigger") and row.get("daysUntilEarnings", 0) <= 21 and row.get("priority", 0) >= 3:
        trend = row.get("trend")
        tone = trend.get("tone") if isinstance(trend, dict) else ""
        if tone == "hot":
            return "Vertical Call"
        return "Straddle"
    return "Avoid"


def fallback_trigger_label(row: dict[str, Any]) -> str:
    """Choose a conservative trigger fallback when the sheet formula path breaks."""
    if row.get("signalTrigger") and not is_bad_sheet_value(row.get("signalTrigger")):
        return "✅"
    return "❌"


def repair_setup_and_trigger_columns(backtest_root: Path, sheet_name: str) -> dict[str, Any]:
    """Repair broken setup/trigger cells so unsupported symbols do not poison the row."""
    sheet = get_sheet(backtest_root, sheet_name)
    raw_rows = google_sheets_call("read setup/trigger repair rows", lambda: sheet.get_all_values())
    if len(raw_rows) < 2:
        return {"checked": True, "updated": 0, "reason": "sheet empty"}

    headers = [header.strip() for header in raw_rows[0]]
    index_map = {header: idx for idx, header in enumerate(headers)}
    required_headers = ("Ticker", "Setup Rec", "Signal Trigger")
    missing = [header for header in required_headers if header not in index_map]
    if missing:
        return {"checked": True, "updated": 0, "reason": f"missing headers: {', '.join(missing)}"}

    repaired_setup_values: list[list[Any]] = []
    repaired_trigger_values: list[list[Any]] = []
    updated = 0
    data_rows = raw_rows[1:]
    enriched_rows = read_sheet_rows_from_table(headers, data_rows)

    for cells, row in zip(data_rows, enriched_rows):
        current_setup = str(cells[index_map["Setup Rec"]]).strip() if index_map["Setup Rec"] < len(cells) else ""
        current_trigger = str(cells[index_map["Signal Trigger"]]).strip() if index_map["Signal Trigger"] < len(cells) else ""

        setup_value = current_setup if current_setup and not is_bad_sheet_value(current_setup) else fallback_setup_recommendation(row)
        trigger_value = current_trigger if current_trigger and not is_bad_sheet_value(current_trigger) else fallback_trigger_label(row)

        if setup_value != current_setup or trigger_value != current_trigger:
            updated += 1

        repaired_setup_values.append([setup_value])
        repaired_trigger_values.append([trigger_value])

    setup_column = column_letter(index_map["Setup Rec"])
    trigger_column = column_letter(index_map["Signal Trigger"])
    update_sheet_range(sheet, f"{setup_column}2:{setup_column}{len(raw_rows)}", repaired_setup_values)
    update_sheet_range(sheet, f"{trigger_column}2:{trigger_column}{len(raw_rows)}", repaired_trigger_values)

    return {
        "checked": True,
        "updated": updated,
        "rows": len(data_rows),
        "setupColumn": setup_column,
        "triggerColumn": trigger_column,
    }


def validate_updater_columns(backtest_root: Path, sheet_name: str, script_name: str) -> dict[str, Any]:
    columns = UPDATER_COLUMN_MAP.get(script_name)
    if not columns:
        return {"ok": True, "reason": "no validation mapping"}

    sheet = get_sheet(backtest_root, sheet_name)
    rows = google_sheets_call("validate updater columns", lambda: sheet.get_all_values()[1:])
    valid_rows = [cells for cells in rows if cells and looks_like_ticker(cells[0])]
    if not valid_rows:
        return {"ok": True, "reason": "no valid ticker rows"}

    per_column = []
    for column in columns:
        column_index = ord(column) - ord("A")
        na_like = 0
        for cells in valid_rows:
            value = cells[column_index].strip() if column_index < len(cells) else ""
            if not value or value.upper() in {"N/A", "#N/A"}:
                na_like += 1
        ratio = na_like / len(valid_rows)
        per_column.append({"column": column, "naRatio": round(ratio, 4), "naCount": na_like, "rowCount": len(valid_rows)})

    ok = all(column["naRatio"] < UPDATER_COLUMN_NA_THRESHOLD for column in per_column)
    return {"ok": ok, "columns": per_column}


def run_internal_fallback(script_name: str, backtest_root: Path, sheet_name: str) -> dict[str, Any]:
    if script_name == "BC-ATRPercentandIVRANK.py":
        return sync_bc_columns(backtest_root, sheet_name)
    if script_name == "P-IV RANK CHANGE.py":
        return sync_p_column(backtest_root, sheet_name)
    if script_name == "Q-ATRPcntZScore.py":
        return sync_q_column(backtest_root, sheet_name)
    if script_name == "R-20DayATR.py":
        return sync_r_column(backtest_root, sheet_name)
    raise RuntimeError(f"No internal fallback exists for {script_name}")


def column_number(column_name: str) -> int:
    """Convert an A1 column letter into a one-based numeric index."""
    total = 0
    for character in str(column_name or "").strip().upper():
        if not ("A" <= character <= "Z"):
            continue
        total = total * 26 + (ord(character) - 64)
    return total


def column_letter(column_index: int) -> str:
    """Convert a zero-based column index to an A1-notation column letter."""
    number = column_index + 1
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def ensure_sheet_has_columns(sheet, minimum_columns: int) -> None:
    """Expand the sheet grid before writing beyond the current column limit."""
    current_columns = int(getattr(sheet, "col_count", 0) or 0)
    if current_columns >= minimum_columns:
        return
    google_sheets_call(
        f"expand sheet to {minimum_columns} columns",
        lambda: sheet.add_cols(minimum_columns - current_columns),
    )


def sync_earnings_dates(backtest_root: Path, sheet_name: str) -> dict[str, Any]:
    """Refresh Next Earnings and Days until earnings so stale dates cannot go negative."""
    today = local_now().date()
    sheet = get_sheet(backtest_root, sheet_name)
    rows = google_sheets_call("read earnings date rows", lambda: sheet.get_all_values())
    if len(rows) < 2:
        return {"checked": True, "updated": 0, "reason": "sheet empty"}

    headers = [header.strip() for header in rows[0]]
    index_map = {header: index for index, header in enumerate(headers)}
    required_headers = ("Ticker", "Next Earnings", "Days until earnings")
    missing = [header for header in required_headers if header not in index_map]
    if missing:
        raise RuntimeError(f"Cannot sync earnings dates; missing headers: {', '.join(missing)}")

    ticker_index = index_map["Ticker"]
    date_index = index_map["Next Earnings"]
    days_index = index_map["Days until earnings"]
    date_values: list[list[Any]] = []
    days_values: list[list[Any]] = []
    summary: dict[str, Any] = {
        "checked": True,
        "updated": 0,
        "projected": 0,
        "unresolved": 0,
        "negativeBefore": 0,
        "sources": {},
    }

    for cells in rows[1:]:
        ticker = cells[ticker_index].strip().upper() if ticker_index < len(cells) else ""
        existing_text = cells[date_index].strip() if date_index < len(cells) else ""
        existing_days = cells[days_index] if days_index < len(cells) else ""
        raw_days = number_or_none(existing_days)
        if raw_days is not None and int(raw_days) < 0:
            summary["negativeBefore"] += 1

        if not ticker or not looks_like_ticker(ticker):
            date_values.append([existing_text])
            days_values.append([existing_days])
            continue

        resolved_date, source = resolve_next_earnings_date(ticker, parse_sheet_date(existing_text), today)
        summary["sources"][source] = summary["sources"].get(source, 0) + 1

        if resolved_date is None:
            # Unknown dates should not accidentally become urgent earnings plays.
            date_values.append(["N/A"])
            days_values.append([UNKNOWN_EARNINGS_DAYS])
            summary["unresolved"] += 1
            continue

        days_until = max(0, (resolved_date - today).days)
        date_values.append([format_sheet_date(resolved_date)])
        days_values.append([days_until])
        summary["updated"] += 1
        if source.startswith("projected"):
            summary["projected"] += 1

    last_row = len(rows)
    date_column = column_letter(date_index)
    days_column = column_letter(days_index)
    update_sheet_range(sheet, f"{date_column}2:{date_column}{last_row}", date_values)
    update_sheet_range(sheet, f"{days_column}2:{days_column}{last_row}", days_values)
    return summary


def sync_price_column_if_needed(backtest_root: Path, sheet_name: str) -> dict[str, Any]:
    """Repair blank or #N/A price cells from recent daily close history.

    We only intervene when the sheet price is unusable. Valid prices stay
    untouched so we do not fight any existing manual/operator workflow.
    """
    sheet = get_sheet(backtest_root, sheet_name)
    rows = google_sheets_call("read price rows", lambda: sheet.get_all_values())
    if len(rows) < 2:
        return {"checked": True, "updated": 0, "reason": "sheet empty"}

    headers = [header.strip() for header in rows[0]]
    index_map = {header: index for index, header in enumerate(headers)}
    required_headers = ("Ticker", "Price")
    missing = [header for header in required_headers if header not in index_map]
    if missing:
        raise RuntimeError(f"Cannot sync prices; missing headers: {', '.join(missing)}")

    ticker_index = index_map["Ticker"]
    price_index = index_map["Price"]
    price_values: list[list[Any]] = []
    updated = 0
    repaired_tickers: list[str] = []

    for cells in rows[1:]:
        ticker = cells[ticker_index].strip().upper() if ticker_index < len(cells) else ""
        raw_price = cells[price_index].strip() if price_index < len(cells) else ""
        parsed_price = number_or_none(raw_price)
        if ticker and (parsed_price is None or parsed_price <= 0):
            history = download_history_with_retries(ticker, period="10d")
            close = pd.to_numeric(history["Close"], errors="coerce").dropna()
            repaired_price = float(close.iloc[-1]) if not close.empty else 0.0
            if repaired_price > 0:
                price_values.append([f"${repaired_price:.2f}"])
                updated += 1
                repaired_tickers.append(ticker)
                continue
        price_values.append([raw_price])

    if updated:
        column = column_letter(price_index)
        update_sheet_range(sheet, f"{column}2:{column}{len(rows)}", price_values)
    return {
        "checked": True,
        "updated": updated,
        "repairedTickers": repaired_tickers[:20],
    }


def calculate_20day_atr_fixed(ticker: str) -> str | float:
    try:
        df = yf.Ticker(ticker).history(period="2mo", interval="1d").dropna()
        if len(df) < 22:
            return "N/A"

        df["TR"] = np.maximum(
            df["High"] - df["Low"],
            np.maximum(abs(df["High"] - df["Close"].shift()), abs(df["Low"] - df["Close"].shift())),
        )
        df["ATR_20"] = df["TR"].rolling(window=20).mean()
        latest = df["ATR_20"].iloc[-1]
        return round(float(latest), 4) if pd.notna(latest) else "N/A"
    except Exception:
        return "N/A"


def repair_r20_atr_if_needed(backtest_root: Path, sheet_name: str) -> dict[str, Any]:
    sheet = get_sheet(backtest_root, sheet_name)
    rows = google_sheets_call("read column R repair rows", lambda: sheet.get_all_values())
    if len(rows) < 2:
        return {"checked": True, "repaired": False, "reason": "sheet empty"}

    tickers: list[str] = []
    current_values: list[str] = []
    for cells in rows[1:]:
        ticker = cells[0].strip().upper() if len(cells) > 0 else ""
        if not ticker:
            continue
        tickers.append(ticker)
        current_values.append(cells[17].strip() if len(cells) > 17 else "")

    if not tickers:
        return {"checked": True, "repaired": False, "reason": "no tickers"}

    na_like = sum(1 for value in current_values if not value or value.upper() == "N/A")
    if na_like / len(current_values) < 0.8:
        return {"checked": True, "repaired": False, "reason": "column R looks populated"}

    repaired_values = [[calculate_20day_atr_fixed(ticker)] for ticker in tickers]
    update_sheet_range(sheet, f"R2:R{len(tickers) + 1}", repaired_values)
    repaired_na = sum(1 for value in repaired_values if value[0] == "N/A")
    return {
        "checked": True,
        "repaired": True,
        "reason": "column R was mostly N/A after external job",
        "rows": len(tickers),
        "naCountAfterRepair": repaired_na,
    }


def score_formula_row(row_number: int) -> list[str]:
    return [
        f'=IF($A{row_number}="","", N($O{row_number}) * (N($C{row_number})/100) * (ABS(N($Q{row_number}))+1))',
        f'=IF($A{row_number}="","", MAX(0, N($P{row_number})))',
        f'=IF($A{row_number}="","", MAX(0, -N($Q{row_number})))',
        f'=IF($A{row_number}="","", IF(AND($K{row_number}="✅",$I{row_number}<>"Avoid"), N($U{row_number}), 0))',
        f'=IF($A{row_number}="","", N($U{row_number})+N($V{row_number})+N($W{row_number})+N($X{row_number}))',
    ]


def sync_score_formulas(backtest_root: Path, sheet_name: str) -> dict[str, Any]:
    sheet = get_sheet(backtest_root, sheet_name)
    tickers = [
        ticker.strip().upper()
        for ticker in google_sheets_call("read score formula ticker column", lambda: sheet.col_values(1)[1:])
        if ticker.strip()
    ]
    if not tickers:
        return {"checked": True, "repaired": False, "reason": "no tickers"}

    last_row = len(tickers) + 1
    formula_rows = [score_formula_row(row_number) for row_number in range(2, last_row + 1)]
    update_sheet_range(
        sheet,
        f"{SCORE_FORMULA_COLUMNS[0]}2:{SCORE_FORMULA_COLUMNS[-1]}{last_row}",
        formula_rows,
    )
    return {
        "checked": True,
        "repaired": True,
        "reason": "score formulas synced",
        "rows": len(tickers),
        "columns": list(SCORE_FORMULA_COLUMNS),
    }


def read_sheet_rows_from_table(headers: list[str], raw_rows: list[list[str]]) -> list[dict[str, Any]]:
    """Convert raw tracker cells into enriched snapshot rows."""
    if not headers or not raw_rows:
        return []

    index_map = {header: idx for idx, header in enumerate(headers)}
    tos_custom_metric_lookup = load_custom_metrics_by_ticker()

    def read(cells: list[str], header: str) -> str:
        idx = index_map.get(header)
        if idx is None or idx >= len(cells):
            return ""
        return cells[idx]

    rows: list[dict[str, Any]] = []
    for cells in raw_rows:
        ticker = read(cells, "Ticker").strip().upper()
        if not ticker:
            continue
        next_earnings = parse_date(read(cells, "Next Earnings"))
        raw_days_until_earnings = int(number_or_none(read(cells, "Days until earnings")) or 0)

        row = enrich_row(
            {
                "ticker": ticker,
                "atrPercent": number_or_none(read(cells, "ATR%")) or 0.0,
                "ivRank": number_or_none(read(cells, "IV Rank")) or 0.0,
                "nextEarnings": next_earnings,
                "price": number_or_none(read(cells, "Price")) or 0.0,
                "eps": number_or_none(read(cells, "EPS")) or 0.0,
                "pe": number_or_none(read(cells, "PE")),
                "daysUntilEarnings": safe_days_until_earnings(next_earnings, raw_days_until_earnings),
                "setupRec": read(cells, "Setup Rec").strip() or "Watchlist",
                "urgency": read(cells, '"Urgency"').strip() or "Watchlist",
                "signalTrigger": normalize_trigger(read(cells, "Signal Trigger")),
                "confidence": int(number_or_none(read(cells, "Confidence (3 MAX)")) or 0),
                "ivRankChange": number_or_none(read(cells, "IV Rank Change (5-day delta)")) or 0.0,
                "atrZScore": number_or_none(read(cells, "ATR% Z-Score")) or 0.0,
                "atr20Day": number_or_none(read(cells, "20 Day ATR")),
                "rec1": read(cells, "REC 1-13").strip() or "N/A",
                "rec2": read(cells, "Rec2").strip() or "N/A",
                "valueScore": number_or_none(read(cells, "Value Score")) or 0.0,
                "momentumScore": number_or_none(read(cells, "Momentum Score")) or 0.0,
                "squeezeScore": number_or_none(read(cells, "Squeeze Score")) or 0.0,
                "readyScore": number_or_none(read(cells, "Ready Score")) or 0.0,
                "priority": number_or_none(read(cells, "Priority")),
                "rvol": number_or_none(read(cells, "$RVOL")),
                "trend": read(cells, "Trend").strip(),
                "support": number_or_none(read(cells, "Support")),
                "resistance": number_or_none(read(cells, "Resistance")),
                "distanceToSupportPct": number_or_none(read(cells, "% To Support")),
                "distanceToResistancePct": number_or_none(read(cells, "% To Resistance")),
                "tosCustomMetrics": tos_custom_metric_lookup.get(ticker, {}),
            }
        )
        rows.append(row)

    rows.sort(key=lambda item: (-item["readiness"], item["daysUntilEarnings"]))
    return rows


def read_sheet_rows(backtest_root: Path, sheet_name: str) -> list[dict[str, Any]]:
    headers, raw_rows = read_sheet_table(backtest_root, sheet_name)
    return read_sheet_rows_from_table(headers, raw_rows)


def run_script_with_retries(script_name: str, backtest_root: Path, python_bin: Path) -> tuple[subprocess.CompletedProcess[str], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    final_result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, UPDATER_SCRIPT_RETRIES + 1):
        completed = subprocess.run(
            [str(python_bin), script_name],
            cwd=backtest_root,
            capture_output=True,
            text=True,
        )
        final_result = completed
        attempts.append(
            {
                "attempt": attempt,
                "returncode": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
        )
        if completed.returncode == 0:
            return completed, attempts
        if attempt < UPDATER_SCRIPT_RETRIES:
            sleep_for_retry(attempt)
    assert final_result is not None
    return final_result, attempts


def run_updaters(backtest_root: Path, python_bin: Path, sheet_name: str) -> list[dict[str, Any]]:
    results = []
    for script_name in UPDATER_SCRIPTS:
        completed, attempts = run_script_with_retries(script_name, backtest_root, python_bin)
        validation = validate_updater_columns(backtest_root, sheet_name, script_name) if completed.returncode == 0 else {"ok": False, "reason": "script did not exit cleanly"}
        recovered = False
        fallback_summary = None

        if completed.returncode != 0 or not validation.get("ok", True):
            fallback_summary = run_internal_fallback(script_name, backtest_root, sheet_name)
            post_fallback_validation = validate_updater_columns(backtest_root, sheet_name, script_name)
            if not post_fallback_validation.get("ok", True):
                results.append(
                    {
                        "script": script_name,
                        "ok": False,
                        "stdout": completed.stdout.strip(),
                        "stderr": completed.stderr.strip(),
                        "returncode": completed.returncode,
                        "attempts": attempts,
                        "validation": validation,
                        "fallback": fallback_summary,
                        "postFallbackValidation": post_fallback_validation,
                    }
                )
                raise RuntimeError(f"{script_name} failed validation after retries and fallback")
            validation = post_fallback_validation
            recovered = True

        results.append(
            {
                "script": script_name,
                "ok": True,
                "stdout": completed.stdout.strip() if not recovered else json.dumps(fallback_summary),
                "stderr": completed.stderr.strip(),
                "returncode": 0 if recovered else completed.returncode,
                "attempts": attempts,
                "validation": validation,
                "recovered": recovered,
                "fallback": fallback_summary,
            }
        )
    return results


def run_internal_updaters(backtest_root: Path, sheet_name: str) -> list[dict[str, Any]]:
    """Refresh BC/P/Q/R using in-process logic for cloud runners.

    The local Mac runner can still execute the original Backtest/PyCharm files,
    but Cloud Run Jobs will not have that folder. These internal syncs are the
    portable path that lets Google Cloud own the 6 AM update without a laptop.
    """
    results: list[dict[str, Any]] = []
    for script_name in UPDATER_SCRIPTS:
        try:
            fallback_summary = run_internal_fallback(script_name, backtest_root, sheet_name)
            validation = validate_updater_columns(backtest_root, sheet_name, script_name)
            if not validation.get("ok", True):
                raise RuntimeError(f"{script_name} failed cloud-native validation: {validation}")
            results.append(
                {
                    "script": script_name,
                    "ok": True,
                    "stdout": json.dumps(fallback_summary),
                    "stderr": "",
                    "returncode": 0,
                    "attempts": [],
                    "validation": validation,
                    "recovered": True,
                    "fallback": fallback_summary,
                    "runner": "internal",
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "script": script_name,
                    "ok": False,
                    "stdout": "",
                    "stderr": str(exc),
                    "returncode": 1,
                    "attempts": [],
                    "recovered": False,
                    "runner": "internal",
                }
            )
            raise
    return results


def build_market_context_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize confirmation-metric coverage for the active snapshot."""
    total_rows = len(rows)
    populated_rows = 0
    aligned_rows = 0
    bullish_rows = 0
    bearish_rows = 0
    missing_tickers: list[str] = []
    unavailable_tickers: list[str] = []
    rvol_values: list[float] = []

    for row in rows:
        context = row.get("marketContext") or {}
        source_status = str(context.get("sourceStatus") or "").strip().lower()
        if source_status == "unavailable":
            unavailable_tickers.append(str(row.get("ticker") or "UNKNOWN"))
            populated_rows += 1
            continue
        trend = context.get("trend") or {}
        rvol = number_or_none(context.get("rvol"))
        support = number_or_none(context.get("support"))
        resistance = number_or_none(context.get("resistance"))
        trend_label = str(trend.get("label") or row.get("trend") or "").strip()
        if rvol is not None and support is not None and resistance is not None and trend_label:
            populated_rows += 1
            rvol_values.append(rvol)
        else:
            missing_tickers.append(str(row.get("ticker") or "UNKNOWN"))

        alignment_label = str(context.get("alignmentLabel") or "")
        if alignment_label == "Aligned":
            aligned_rows += 1
        if trend_label in {"Bullish", "Uptrend"}:
            bullish_rows += 1
        elif trend_label in {"Bearish", "Downtrend"}:
            bearish_rows += 1

    population_ratio = round((populated_rows / total_rows), 4) if total_rows else 0.0
    average_rvol = round(sum(rvol_values) / len(rvol_values), 2) if rvol_values else None
    top_missing = missing_tickers[:10]
    return {
        "generatedAt": local_now().isoformat(),
        "ok": total_rows > 0 and populated_rows == total_rows,
        "totalRows": total_rows,
        "populatedRows": populated_rows,
        "populationRatio": population_ratio,
        "alignedRows": aligned_rows,
        "bullishRows": bullish_rows,
        "bearishRows": bearish_rows,
        "averageRvol": average_rvol,
        "missingTickers": top_missing,
        "unavailableTickers": unavailable_tickers[:10],
    }


def market_context_audit_text(audit: dict[str, Any]) -> str:
    """Render a plain-text audit report for operator review."""
    lines = [
        "Market Context Audit",
        "",
        f"Generated: {audit.get('generatedAt')}",
        f"Rows: {audit.get('populatedRows')} populated / {audit.get('totalRows')} total",
        f"Coverage: {round(float(audit.get('populationRatio') or 0) * 100, 2)}%",
        f"Aligned rows: {audit.get('alignedRows')}",
        f"Bullish trends: {audit.get('bullishRows')} | Bearish trends: {audit.get('bearishRows')}",
        f"Average RVOL: {audit.get('averageRvol') if audit.get('averageRvol') is not None else 'N/A'}",
    ]
    missing = audit.get("missingTickers") or []
    if missing:
        lines.extend(["", "Missing tickers:", ", ".join(missing)])
    unavailable = audit.get("unavailableTickers") or []
    if unavailable:
        lines.extend(["", "Unavailable tickers (vendor gap):", ", ".join(unavailable)])
    return "\n".join(lines).rstrip() + "\n"


def write_market_context_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Persist confirmation-metric audit artifacts for doctor/watchdog checks."""
    ensure_dirs()
    audit = build_market_context_audit(rows)
    atomic_write_json(MARKET_CONTEXT_AUDIT_FILE, audit)
    atomic_write_text(MARKET_CONTEXT_AUDIT_TEXT_FILE, market_context_audit_text(audit))
    return audit


def build_ticker_universe_audit(
    headers: list[str],
    raw_rows: list[list[str]],
    enriched_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize tracker hydration quality so new ticker additions cannot silently drift."""
    header_index = {header.strip(): idx for idx, header in enumerate(headers)}

    def read(cells: list[str], header: str) -> str:
        idx = header_index.get(header)
        if idx is None or idx >= len(cells):
            return ""
        return str(cells[idx] or "").strip()

    def issue_record(ticker: str, fields: list[str], *, detail: str | None = None) -> dict[str, Any]:
        record: dict[str, Any] = {"ticker": ticker, "fields": fields}
        if detail:
            record["detail"] = detail
        return record

    required_headers_missing = [header for header in TICKER_UNIVERSE_REQUIRED_HEADERS if header not in header_index]
    advisory_headers_missing = [header for header in TICKER_UNIVERSE_ADVISORY_HEADERS if header not in header_index]

    duplicate_counter: dict[str, int] = {}
    blank_ticker_rows = 0
    missing_core_rows: list[dict[str, Any]] = []
    missing_score_rows: list[dict[str, Any]] = []
    missing_market_context_rows: list[dict[str, Any]] = []
    missing_long_term_rows: list[dict[str, Any]] = []
    invalid_price_rows: list[dict[str, Any]] = []
    invalid_earnings_rows: list[dict[str, Any]] = []
    unknown_earnings_rows: list[dict[str, Any]] = []
    invalid_level_rows: list[dict[str, Any]] = []
    invalid_trend_rows: list[dict[str, Any]] = []
    unsupported_tickers: list[str] = []
    raw_tickers: list[str] = []

    score_headers = ["Value Score", "Momentum Score", "Squeeze Score", "Ready Score", "Priority"]

    for cells in raw_rows:
        ticker = read(cells, "Ticker").upper()
        if not ticker:
            blank_ticker_rows += 1
            continue

        raw_tickers.append(ticker)
        duplicate_counter[ticker] = duplicate_counter.get(ticker, 0) + 1

        missing_core = [
            header
            for header in (
                "ATR%",
                "IV Rank",
                "Next Earnings",
                "Price",
                "Days until earnings",
                "Setup Rec",
                '"Urgency"',
                "Signal Trigger",
                "Confidence (3 MAX)",
                "IV Rank Change (5-day delta)",
                "ATR% Z-Score",
                "20 Day ATR",
                "REC 1-13",
                "Rec2",
            )
            if not read(cells, header)
        ]
        if missing_core:
            missing_core_rows.append(issue_record(ticker, missing_core))

        missing_scores = [header for header in score_headers if not read(cells, header)]
        if missing_scores:
            missing_score_rows.append(issue_record(ticker, missing_scores))

        missing_market_context = [header for header in MARKET_CONTEXT_HEADERS if not read(cells, header)]
        if missing_market_context:
            missing_market_context_rows.append(issue_record(ticker, missing_market_context))

        missing_long_term = [header for header in TICKER_UNIVERSE_ADVISORY_HEADERS if not read(cells, header)]
        if missing_long_term:
            missing_long_term_rows.append(issue_record(ticker, missing_long_term))

        price = number_or_none(read(cells, "Price"))
        if price is None or price <= 0:
            invalid_price_rows.append(issue_record(ticker, ["Price"], detail=read(cells, "Price") or "blank"))

        next_earnings = parse_sheet_date(read(cells, "Next Earnings"))
        days_until_earnings = number_or_none(read(cells, "Days until earnings"))
        if next_earnings is None or days_until_earnings is None or days_until_earnings < 0:
            invalid_earnings_rows.append(
                issue_record(
                    ticker,
                    ["Next Earnings", "Days until earnings"],
                    detail=f"{read(cells, 'Next Earnings') or 'blank'} / {read(cells, 'Days until earnings') or 'blank'}",
                )
            )
        elif int(days_until_earnings) == UNKNOWN_EARNINGS_DAYS:
            unknown_earnings_rows.append(
                issue_record(
                    ticker,
                    ["Days until earnings"],
                    detail=str(int(days_until_earnings)),
                )
            )

        support = number_or_none(read(cells, "Support"))
        resistance = number_or_none(read(cells, "Resistance"))
        if support is not None and resistance is not None and resistance <= support:
            invalid_level_rows.append(
                issue_record(
                    ticker,
                    ["Support", "Resistance"],
                    detail=f"{support} / {resistance}",
                )
            )

        trend_label = read(cells, "Trend")
        if trend_label and trend_label not in ALLOWED_TREND_LABELS:
            invalid_trend_rows.append(issue_record(ticker, ["Trend"], detail=trend_label))

        vendor_gap = (
            (price is None or price <= 0)
            and (next_earnings is None or int(days_until_earnings or UNKNOWN_EARNINGS_DAYS) >= UNKNOWN_EARNINGS_DAYS)
            and read(cells, "Setup Rec") in {"", "Avoid"}
            and not read(cells, "Signal Trigger")
            and trend_label in {"", "N/A"}
        )
        if vendor_gap:
            unsupported_tickers.append(ticker)

    duplicate_tickers = sorted([ticker for ticker, count in duplicate_counter.items() if count > 1])
    raw_ticker_set = set(raw_tickers)
    enriched_ticker_set = {str(row.get("ticker") or "").upper() for row in enriched_rows if row.get("ticker")}
    snapshot_missing_tickers = sorted(raw_ticker_set - enriched_ticker_set)

    hydration_needed_tickers = sorted(
        {
            *duplicate_tickers,
            *[item["ticker"] for item in missing_core_rows],
            *[item["ticker"] for item in missing_score_rows],
            *[item["ticker"] for item in missing_market_context_rows],
            *[item["ticker"] for item in invalid_price_rows if item["ticker"] not in unsupported_tickers],
            *[item["ticker"] for item in invalid_earnings_rows if item["ticker"] not in unsupported_tickers],
            *[item["ticker"] for item in invalid_level_rows if item["ticker"] not in unsupported_tickers],
            *[ticker for ticker in snapshot_missing_tickers if ticker not in unsupported_tickers],
        }
    )
    advisory_tickers = sorted(
        {
            *[item["ticker"] for item in missing_long_term_rows],
            *[item["ticker"] for item in unknown_earnings_rows],
            *[item["ticker"] for item in invalid_trend_rows],
        }
    )

    critical_issue_count = (
        len(required_headers_missing)
        + len(duplicate_tickers)
        + len([ticker for ticker in snapshot_missing_tickers if ticker not in unsupported_tickers])
        + len(missing_core_rows)
        + len(missing_score_rows)
        + len([item for item in missing_market_context_rows if item["ticker"] not in unsupported_tickers])
        + len([item for item in invalid_price_rows if item["ticker"] not in unsupported_tickers])
        + len([item for item in invalid_earnings_rows if item["ticker"] not in unsupported_tickers])
        + len([item for item in invalid_level_rows if item["ticker"] not in unsupported_tickers])
    )
    advisory_issue_count = (
        len(advisory_headers_missing)
        + len(missing_long_term_rows)
        + len(unknown_earnings_rows)
        + len(invalid_trend_rows)
        + blank_ticker_rows
    )
    verdict = "healthy" if critical_issue_count == 0 and advisory_issue_count == 0 else (
        "healthy-with-advisories" if critical_issue_count == 0 else "attention"
    )

    return {
        "generatedAt": local_now().isoformat(),
        "ok": critical_issue_count == 0,
        "verdict": verdict,
        "totalRows": len(raw_rows),
        "nonBlankTickerRows": len(raw_tickers),
        "uniqueTickers": len(raw_ticker_set),
        "sheetRows": len(raw_tickers),
        "snapshotRows": len(enriched_rows),
        "unsupportedTickers": unsupported_tickers,
        "headerHealth": {
            "requiredHeadersMissing": required_headers_missing,
            "advisoryHeadersMissing": advisory_headers_missing,
        },
        "counts": {
            "duplicateTickers": len(duplicate_tickers),
            "snapshotMissingTickers": len(snapshot_missing_tickers),
            "missingCoreRows": len(missing_core_rows),
            "missingScoreRows": len(missing_score_rows),
            "missingMarketContextRows": len(missing_market_context_rows),
            "missingLongTermRows": len(missing_long_term_rows),
            "invalidPriceRows": len(invalid_price_rows),
            "invalidEarningsRows": len(invalid_earnings_rows),
            "unknownEarningsRows": len(unknown_earnings_rows),
            "invalidLevelRows": len(invalid_level_rows),
            "invalidTrendRows": len(invalid_trend_rows),
            "blankTickerRows": blank_ticker_rows,
            "criticalIssueCount": critical_issue_count,
            "advisoryIssueCount": advisory_issue_count,
        },
        "hydrationNeededTickers": hydration_needed_tickers[:20],
        "advisoryTickers": advisory_tickers[:20],
        "issues": {
            "duplicateTickers": duplicate_tickers[:20],
            "snapshotMissingTickers": snapshot_missing_tickers[:20],
            "missingCoreRows": missing_core_rows[:20],
            "missingScoreRows": missing_score_rows[:20],
            "missingMarketContextRows": missing_market_context_rows[:20],
            "missingLongTermRows": missing_long_term_rows[:20],
            "invalidPriceRows": invalid_price_rows[:20],
            "invalidEarningsRows": invalid_earnings_rows[:20],
            "unknownEarningsRows": unknown_earnings_rows[:20],
            "invalidLevelRows": invalid_level_rows[:20],
            "invalidTrendRows": invalid_trend_rows[:20],
            "unsupportedTickers": unsupported_tickers[:20],
        },
    }


def ticker_universe_audit_text(audit: dict[str, Any]) -> str:
    """Render a plain-text tracker hydration report for operator review."""
    counts = audit.get("counts") or {}
    header_health = audit.get("headerHealth") or {}
    lines = [
        "Ticker Universe Audit",
        "",
        f"Generated: {audit.get('generatedAt')}",
        f"Verdict: {audit.get('verdict')}",
        f"Rows: {audit.get('sheetRows', 0)} sheet / {audit.get('snapshotRows', 0)} snapshot",
        f"Critical issues: {counts.get('criticalIssueCount', 0)}",
        f"Advisory issues: {counts.get('advisoryIssueCount', 0)}",
    ]
    required_headers_missing = header_health.get("requiredHeadersMissing") or []
    advisory_headers_missing = header_health.get("advisoryHeadersMissing") or []
    if required_headers_missing:
        lines.extend(["", "Missing required headers:", ", ".join(required_headers_missing)])
    if advisory_headers_missing:
        lines.extend(["", "Missing advisory headers:", ", ".join(advisory_headers_missing)])
    if audit.get("hydrationNeededTickers"):
        lines.extend(["", "Hydration needed:", ", ".join(audit.get("hydrationNeededTickers") or [])])
    if audit.get("advisoryTickers"):
        lines.extend(["", "Advisory review:", ", ".join(audit.get("advisoryTickers") or [])])
    if audit.get("unsupportedTickers"):
        lines.extend(["", "Unavailable tickers (vendor gap):", ", ".join(audit.get("unsupportedTickers") or [])])
    return "\n".join(lines).rstrip() + "\n"


def write_ticker_universe_audit(
    headers: list[str],
    raw_rows: list[list[str]],
    enriched_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist tracker-hydration artifacts so new sheet additions get checked automatically."""
    ensure_dirs()
    audit = build_ticker_universe_audit(headers, raw_rows, enriched_rows)
    atomic_write_json(TICKER_UNIVERSE_AUDIT_FILE, audit)
    atomic_write_text(TICKER_UNIVERSE_AUDIT_TEXT_FILE, ticker_universe_audit_text(audit))
    return audit


def build_ticker_universe_audit_from_sheet(backtest_root: Path, sheet_name: str) -> dict[str, Any]:
    """Read the live tracker and emit a hydration audit without mutating the sheet."""
    headers, raw_rows = read_sheet_table(backtest_root, sheet_name)
    enriched_rows = read_sheet_rows_from_table(headers, raw_rows)
    return write_ticker_universe_audit(headers, raw_rows, enriched_rows)


def write_payload(payload: dict[str, Any]) -> None:
    ensure_dirs()
    brief_text = payload["brief"]
    tickets_text = payload["tickets"]
    long_term_text = payload["longTermBrief"]
    html_text = html_from_payload(payload)

    atomic_write_json(SNAPSHOT_FILE, payload)
    atomic_write_text(BRIEF_TEXT_FILE, brief_text)
    atomic_write_text(TICKETS_TEXT_FILE, tickets_text)
    atomic_write_text(LONG_TERM_TEXT_FILE, long_term_text)
    atomic_write_text(HTML_BRIEF_FILE, html_text)
    write_market_context_audit(payload.get("rows", []))


def write_ops_status(payload: dict[str, Any], updater_results: list[dict[str, Any]], email_sent: bool, email_error: str | None = None) -> None:
    repair_result = next((result for result in updater_results if result["script"] == "R-20DayATR self-heal"), None)
    formula_result = next((result for result in updater_results if result["script"] == "U:Y score sync"), None)
    review_tickers = payload["reviewQueueTickers"]
    journal_count = len(review_tickers)
    execution_queue = payload.get("executionQueue", {})
    atomic_write_json(
        OPS_STATUS_FILE,
        {
            "generatedAt": payload["generatedAt"],
            "ok": True,
            "sourceLabel": payload["sourceLabel"],
            "emailSent": email_sent,
            "emailError": email_error,
            "trackedCount": len(payload["rows"]),
            "eligibleCount": len(payload["eligibleTickers"]),
            "topTickers": payload["eligibleTickers"][:5],
            "reviewQueueTickers": review_tickers,
            "longTermTickers": payload["longTermTickers"],
            "paperTradeCount": journal_count,
            "approvalQueueCount": journal_count,
            "executionReadyCount": execution_queue.get("activeReadyCount", 0),
            "executionRiskUnits": execution_queue.get("stagedRiskUnits", 0),
            "updaterScripts": [
                {
                    "script": result["script"],
                    "ok": result["ok"],
                    "recovered": result.get("recovered", False),
                }
                for result in updater_results
            ],
            "repair": json.loads(repair_result["stdout"]) if repair_result and repair_result.get("stdout") else None,
            "formulaSync": json.loads(formula_result["stdout"]) if formula_result and formula_result.get("stdout") else None,
        },
    )
    try:
        record_heartbeat(
            "dawn_cycle",
            status="ok" if email_sent else "warn",
            summary="morning pipeline completed" if email_sent else "morning pipeline completed without email",
            detail={
                "eligibleCount": len(payload["eligibleTickers"]),
                "topTickers": payload["eligibleTickers"][:5],
                "emailSent": email_sent,
            },
        )
    except Exception:  # noqa: BLE001
        # Heartbeat is diagnostic only; it must never break the morning brief.
        pass


def build_paper_trade_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows_by_ticker = {row["ticker"]: row for row in payload["rows"]}
    entries = []
    for index, ticker in enumerate(payload["reviewQueueTickers"], start=1):
        row = rows_by_ticker.get(ticker)
        if not row:
            continue
        entries.append(
            {
                "generatedAt": payload["generatedAt"],
                "tradeDate": payload["generatedAt"][:10],
                "rank": index,
                "ticker": row["ticker"],
                "setupRec": row["setupRec"],
                "readiness": row["readiness"],
                "daysUntilEarnings": row["daysUntilEarnings"],
                "signalTrigger": row["signalTrigger"],
                "rec1": row["rec1"],
                "rec2": row["rec2"],
                "price": row["price"],
                "valueScore": row["valueScore"],
                "momentumScore": row["momentumScore"],
                "squeezeScore": row["squeezeScore"],
                "readyScore": row["readyScore"],
                "status": "paper-open",
            }
        )
    return entries


def append_paper_trade_journal(entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    append_text(PAPER_JOURNAL_FILE, "".join(json.dumps(entry) + "\n" for entry in entries))


def build_approval_queue(payload: dict[str, Any]) -> dict[str, Any]:
    from inferno_approval_queue import ensure_queue_tokens

    rows_by_ticker = {row["ticker"]: row for row in payload["rows"]}
    queue_items = []
    for ticker in payload["reviewQueueTickers"]:
        row = rows_by_ticker.get(ticker)
        if not row:
            continue
        queue_items.append(
            {
                "ticker": row["ticker"],
                "setupRec": row["setupRec"],
                "readiness": row["readiness"],
                "daysUntilEarnings": row["daysUntilEarnings"],
                "signalTrigger": row["signalTrigger"],
                "primaryRoute": row["rec1"],
                "secondaryRoute": row["rec2"],
                "ivRank": row.get("ivRank"),
                "ivRankChange": row.get("ivRankChange"),
                "atrPercent": row.get("atrPercent"),
                "volatilityThesis": (
                    "Context only: compare implied volatility, expected movement, term structure, "
                    "and strategy Greeks; IV rank alone does not choose debit versus credit."
                ),
                "approvalStatus": "pending",
                "generatedAt": payload["generatedAt"],
            }
        )
    return ensure_queue_tokens(
        {
            "generatedAt": payload["generatedAt"],
            "count": len(queue_items),
            "items": queue_items,
        }
    )


def write_approval_queue(payload: dict[str, Any]) -> dict[str, Any]:
    queue = build_approval_queue(payload)
    atomic_write_json(APPROVAL_QUEUE_FILE, queue)
    return queue


def append_log(entry: dict[str, Any]) -> None:
    append_text(LOG_FILE, json.dumps(entry) + "\n")


def send_failure_email(error_message: str, updater_results: list[dict[str, Any]]) -> bool:
    if not smtp_configured():
        return False

    lines = [
        "Inferno Runner Failure",
        "",
        "The morning updater stack did not complete cleanly.",
        f"Error: {error_message}",
        "",
        "Updater diagnostics:",
    ]
    if updater_results:
        for result in updater_results:
            attempts = result.get("attempts", [])
            attempt_summary = ", ".join(
                f"try {attempt['attempt']} => {attempt['returncode']}" for attempt in attempts
            ) or "no attempts recorded"
            recovered = "yes" if result.get("recovered") else "no"
            lines.append(f"- {result['script']}: recovered={recovered}; attempts: {attempt_summary}")
    else:
        lines.append("- no updater results were recorded before the failure")

    payload = {
        "brief": "\n".join(lines),
        "sourceLabel": "Inferno Runner Failure",
        "rows": [],
        "longTermRows": [],
        "executionQueue": {},
    }
    return send_email(payload, subject="Inferno Runner Failure")


def build_risk_desk_addendum(payload: dict[str, Any]) -> str:
    """Render the automation risk checks into the morning brief text."""
    lines: list[str] = []
    outcome_review = payload.get("outcomeReview")
    if outcome_review:
        if outcome_review.get("error"):
            lines.append(f"Outcome review: warning - {outcome_review['error']}")
        else:
            lines.append(
                f"Outcome review: {outcome_review.get('reviewed', 0)} reviewed / "
                f"{outcome_review.get('closed', 0)} closed"
            )

    shadow_evidence = payload.get("shadowEvidence")
    if shadow_evidence:
        if shadow_evidence.get("error"):
            lines.append(f"Shadow evidence: warning - {shadow_evidence['error']}")
        else:
            overall = shadow_evidence.get("overall") or {}
            last_run = shadow_evidence.get("lastRun") or {}
            lines.append(
                f"Shadow evidence: {overall.get('trackedCount', 0)} tracked / "
                f"{overall.get('closedCount', 0)} closed | "
                f"{last_run.get('reviewed', 0)} reviewed today"
            )
            lines.append("Shadow evidence is research-only and cannot unlock broker submission.")

    performance_analytics = payload.get("performanceAnalytics")
    if performance_analytics:
        if performance_analytics.get("error"):
            lines.append(f"Performance analytics: warning - {performance_analytics['error']}")
        else:
            verdict = performance_analytics.get("deskVerdict") or {}
            lines.append(f"Performance analytics: {verdict.get('level')} - {verdict.get('message')}")

    strategy_lab = payload.get("strategyLab")
    if strategy_lab:
        if strategy_lab.get("error"):
            lines.append(f"Strategy lab: warning - {strategy_lab['error']}")
        else:
            verdict = strategy_lab.get("deskVerdict") or {}
            overall = strategy_lab.get("overall") or {}
            confidence = overall.get("expectancyPerRiskConfidence") or {}
            lines.append(f"Strategy lab: {verdict.get('level')} - {verdict.get('message')}")
            lines.append(
                f"Strategy edge lower bound: {confidence.get('lower')} R | "
                f"risk cap {overall.get('riskUnitCap')}"
            )

    exposure_analytics = payload.get("exposureAnalytics")
    if exposure_analytics:
        if exposure_analytics.get("error"):
            lines.append(f"Exposure analytics: warning - {exposure_analytics['error']}")
        else:
            verdict = exposure_analytics.get("verdict") or {}
            regime = exposure_analytics.get("marketRegime") or {}
            lines.append(f"Exposure analytics: {verdict.get('level')} - {verdict.get('message')}")
            lines.append(
                f"Market regime: {regime.get('regime')} | "
                f"VIX {regime.get('vix')} | SPY vol20 {regime.get('spyRealizedVol20')}"
            )

    edge_research = payload.get("edgeResearch")
    if edge_research:
        if edge_research.get("error"):
            lines.append(f"Edge radar: warning - {edge_research['error']}")
        else:
            catalyst = ", ".join(edge_research.get("topCatalystTickers", [])[:5]) or "none"
            accumulation = ", ".join(edge_research.get("topLongTermTickers", [])[:5]) or "none"
            lines.append(f"Edge radar catalysts: {catalyst}")
            lines.append(f"Edge radar long-term shovels: {accumulation}")

    authority_manifest = payload.get("authorityManifest")
    if authority_manifest:
        if authority_manifest.get("error"):
            lines.append(f"Authority manifest: warning - {authority_manifest['error']}")
        else:
            decision = authority_manifest.get("decision") or {}
            lines.append(
                f"Automation authority: {decision.get('authorityLevel')} | "
                f"live submit {decision.get('brokerSubmitAllowed')}"
            )

    freshness_panel = build_freshness_panel()
    tos_visibility = build_tos_visibility_summary()
    lines.append("Next-week operating status:")
    lines.append(f"TOS: {render_tos_visibility_line(tos_visibility)}")
    lines.extend(render_freshness_lines(freshness_panel))
    lines.append("Allowed action: research, alerts, paper evidence, and manually confirmed orders only; broker submit remains False.")

    downloads_manager = payload.get("downloadsManager")
    if downloads_manager:
        if downloads_manager.get("error"):
            lines.append(f"downloads manager: warning - {downloads_manager['error']}")
        else:
            lines.append(
                f"downloads manager: {downloads_manager.get('importedFiles', 0)} files | "
                f"{downloads_manager.get('importedRows', 0)} rows | "
                f"{downloads_manager.get('quarantinedFiles', 0)} quarantined"
            )

    fill_ingest = payload.get("fillIngest")
    if fill_ingest:
        if fill_ingest.get("error"):
            lines.append(f"paper fill ingest: warning - {fill_ingest['error']}")
        else:
            lines.append(
                f"paper fill ingest: {fill_ingest.get('importedRows', 0)} imported | "
                f"{fill_ingest.get('closedRows', 0)} closed | "
                f"{fill_ingest.get('unmatchedCount', 0)} unmatched"
            )

    tos_sandbox = payload.get("tosSandbox")
    if tos_sandbox:
        if tos_sandbox.get("error"):
            lines.append(f"paperMoney sandbox: warning - {tos_sandbox['error']}")
        else:
            lines.append(
                f"paperMoney sandbox: ready {tos_sandbox.get('sandboxReady')} | "
                f"stageable {tos_sandbox.get('stageableCount', 0)}"
            )

    if not lines:
        return ""
    return "\n\nRISK DESK ADDENDUM\n" + "\n".join(lines)


def summarize(results: list[dict[str, Any]], payload: dict[str, Any], email_sent: bool, email_error: str | None = None) -> str:
    lines = [
        "Morning inferno pipeline complete.",
        f"Rows scored: {len(payload['rows'])}",
        f"Eligible names: {len(payload['eligibleTickers'])}",
        f"Top names: {', '.join(payload['eligibleTickers'][:5]) if payload['eligibleTickers'] else 'none'}",
        f"Long-term names: {', '.join(payload['longTermTickers'][:5]) if payload['longTermTickers'] else 'none'}",
        f"Execution ready: {payload['executionQueue']['activeReadyCount']} intents / {payload['executionQueue']['dailyRiskBudget']} risk units",
        f"Email sent: {'yes' if email_sent else 'no'}",
    ]
    outcome_review = payload.get("outcomeReview")
    if outcome_review:
        if outcome_review.get("error"):
            lines.append(f"Outcome review: warning - {outcome_review['error']}")
        else:
            lines.append(
                f"Outcome review: {outcome_review.get('reviewed', 0)} reviewed / "
                f"{outcome_review.get('closed', 0)} closed"
            )
    shadow_evidence = payload.get("shadowEvidence")
    if shadow_evidence:
        if shadow_evidence.get("error"):
            lines.append(f"Shadow evidence: warning - {shadow_evidence['error']}")
        else:
            overall = shadow_evidence.get("overall") or {}
            lines.append(
                f"Shadow evidence: {overall.get('trackedCount', 0)} tracked | "
                f"{overall.get('closedCount', 0)} closed | avg R {overall.get('avgReturnOnRisk')}"
            )
    performance_analytics = payload.get("performanceAnalytics")
    if performance_analytics:
        if performance_analytics.get("error"):
            lines.append(f"Performance analytics: warning - {performance_analytics['error']}")
        else:
            verdict = performance_analytics.get("deskVerdict") or {}
            lines.append(f"Performance analytics: {verdict.get('level')} - {verdict.get('message')}")
    strategy_lab = payload.get("strategyLab")
    if strategy_lab:
        if strategy_lab.get("error"):
            lines.append(f"Strategy lab: warning - {strategy_lab['error']}")
        else:
            verdict = strategy_lab.get("deskVerdict") or {}
            overall = strategy_lab.get("overall") or {}
            confidence = overall.get("expectancyPerRiskConfidence") or {}
            lines.append(
                f"Strategy lab: {verdict.get('level')} | "
                f"edge lower {confidence.get('lower')} R | cap {overall.get('riskUnitCap')}"
            )
    exposure_analytics = payload.get("exposureAnalytics")
    if exposure_analytics:
        if exposure_analytics.get("error"):
            lines.append(f"Exposure analytics: warning - {exposure_analytics['error']}")
        else:
            verdict = exposure_analytics.get("verdict") or {}
            regime = exposure_analytics.get("marketRegime") or {}
            lines.append(f"Exposure analytics: {verdict.get('level')} - {verdict.get('message')}")
            lines.append(f"Market regime: {regime.get('regime')}")
    edge_research = payload.get("edgeResearch")
    if edge_research:
        if edge_research.get("error"):
            lines.append(f"Edge radar: warning - {edge_research['error']}")
        else:
            lines.append(
                "Edge radar: catalysts "
                f"{', '.join(edge_research.get('topCatalystTickers', [])[:5]) or 'none'} | "
                "long-term "
                f"{', '.join(edge_research.get('topLongTermTickers', [])[:5]) or 'none'}"
            )
    authority_manifest = payload.get("authorityManifest")
    if authority_manifest:
        if authority_manifest.get("error"):
            lines.append(f"Authority manifest: warning - {authority_manifest['error']}")
        else:
            decision = authority_manifest.get("decision") or {}
            lines.append(
                f"Automation authority: {decision.get('authorityLevel')} | "
                f"broker submit {decision.get('brokerSubmitAllowed')}"
            )
    downloads_manager = payload.get("downloadsManager")
    if downloads_manager:
        if downloads_manager.get("error"):
            lines.append(f"downloads manager: warning - {downloads_manager['error']}")
        else:
            lines.append(
                f"downloads manager: {downloads_manager.get('importedFiles', 0)} files | "
                f"{downloads_manager.get('importedRows', 0)} rows"
            )
    fill_ingest = payload.get("fillIngest")
    if fill_ingest:
        if fill_ingest.get("error"):
            lines.append(f"paper fill ingest: warning - {fill_ingest['error']}")
        else:
            lines.append(
                f"paper fill ingest: {fill_ingest.get('importedRows', 0)} imported | "
                f"{fill_ingest.get('closedRows', 0)} closed"
            )
    tos_sandbox = payload.get("tosSandbox")
    if tos_sandbox:
        if tos_sandbox.get("error"):
            lines.append(f"paperMoney sandbox: warning - {tos_sandbox['error']}")
        else:
            lines.append(
                f"paperMoney sandbox: ready {tos_sandbox.get('sandboxReady')} | "
                f"stageable {tos_sandbox.get('stageableCount', 0)}"
            )
    if email_error:
        lines.append(f"Email error: {email_error}")
    if results:
        lines.append("")
        lines.append(f"{UPDATER_LABEL} results:")
        for result in results:
            status = "ok"
            if result.get("recovered"):
                status = "recovered"
            elif not result["ok"]:
                status = "failed"
            lines.append(f"- {result['script']}: {status}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the BC/P/Q/R PyCharm jobs, score the tracker, and send the morning brief.")
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT), help="Path to the Backtest project")
    parser.add_argument("--python-bin", default="", help="Python interpreter to use for the BC/P/Q/R PyCharm jobs")
    parser.add_argument("--sheet-name", default=DEFAULT_SHEET_NAME, help="Google Sheet name")
    parser.add_argument(
        "--cloud-native",
        action="store_true",
        help="Use in-process updater logic and environment/secret credentials instead of a local Backtest project.",
    )
    parser.add_argument(
        "--internal-updates",
        action="store_true",
        help="Use built-in BC/P/Q/R syncs instead of launching external Backtest scripts.",
    )
    parser.add_argument("--skip-updates", action="store_true", help="Do not run the BC/P/Q/R PyCharm jobs")
    parser.add_argument("--skip-email", action="store_true", help="Build the snapshot but do not send email")
    parser.add_argument(
        "--automation",
        action="store_true",
        help="Run only during the configured automation window and skip duplicate sends for the same day.",
    )
    parser.add_argument(
        "--quiet-skip",
        action="store_true",
        help="Exit silently when automation mode decides the run should be skipped.",
    )
    parser.add_argument("--window-start", default=AUTOMATION_WINDOW_START, help="Local HH:MM start for automation mode")
    parser.add_argument("--window-end", default=AUTOMATION_WINDOW_END, help="Local HH:MM end for automation mode")
    return parser.parse_args()


def main() -> int:
    load_env_file(ROOT / ".env.smtp")
    args = parse_args()
    backtest_root = Path(args.backtest_root).expanduser().resolve()
    python_bin = Path(args.python_bin).expanduser().resolve() if args.python_bin else backtest_root / "venv" / "bin" / "python"
    use_internal_updates = args.cloud_native or args.internal_updates

    if args.automation:
        try:
            skip_reason = automation_skip_reason(args.window_start, args.window_end)
        except ValueError as exc:
            print(f"Automation window is invalid: {exc}", file=sys.stderr)
            return 1
        if skip_reason:
            if not args.quiet_skip:
                print(skip_reason)
            return 0

    if not args.cloud_native and not backtest_root.exists():
        print(f"Backtest root not found: {backtest_root}", file=sys.stderr)
        return 1

    if not use_internal_updates and not python_bin.exists():
        print(f"Python interpreter not found: {python_bin}", file=sys.stderr)
        return 1

    ensure_dirs()
    updater_results: list[dict[str, Any]] = []
    cloud_state_restore: dict[str, Any] | None = None
    if args.cloud_native:
        try:
            from inferno_cloud_state import restore_cloud_artifacts

            cloud_state_restore = restore_cloud_artifacts()
        except Exception as exc:  # noqa: BLE001
            cloud_state_restore = {"ok": False, "errors": [str(exc)]}

    try:
        with acquire_run_lock():
            if not args.skip_updates:
                earnings_sync_summary = sync_earnings_dates(backtest_root, args.sheet_name)
                updater_results.append(
                    {
                        "script": "D/H earnings date sync",
                        "ok": True,
                        "stdout": json.dumps(earnings_sync_summary),
                        "stderr": "",
                        "returncode": 0,
                    }
                )
                if use_internal_updates:
                    updater_results.extend(run_internal_updaters(backtest_root, args.sheet_name))
                else:
                    updater_results.extend(run_updaters(backtest_root, python_bin, args.sheet_name))
                repair_summary = repair_r20_atr_if_needed(backtest_root, args.sheet_name)
                updater_results.append(
                    {
                        "script": "R-20DayATR self-heal",
                        "ok": True,
                        "stdout": json.dumps(repair_summary),
                        "stderr": "",
                        "returncode": 0,
                    }
                )
                price_sync_summary = sync_price_column_if_needed(backtest_root, args.sheet_name)
                updater_results.append(
                    {
                        "script": "E price self-heal",
                        "ok": True,
                        "stdout": json.dumps(price_sync_summary),
                        "stderr": "",
                        "returncode": 0,
                    }
                )
            formula_sync_summary = sync_score_formulas(backtest_root, args.sheet_name)
            updater_results.append(
                {
                    "script": "U:Y score sync",
                    "ok": True,
                    "stdout": json.dumps(formula_sync_summary),
                    "stderr": "",
                    "returncode": 0,
                }
            )
            market_context_summary = sync_market_context_columns(backtest_root, args.sheet_name)
            updater_results.append(
                {
                    "script": "Z:AE market context sync",
                    "ok": True,
                    "stdout": json.dumps(market_context_summary),
                    "stderr": "",
                    "returncode": 0,
                }
            )
            setup_trigger_repair_summary = repair_setup_and_trigger_columns(backtest_root, args.sheet_name)
            updater_results.append(
                {
                    "script": "I/K setup-trigger repair",
                    "ok": True,
                    "stdout": json.dumps(setup_trigger_repair_summary),
                    "stderr": "",
                    "returncode": 0,
                }
            )

            headers, raw_sheet_rows = read_sheet_table(backtest_root, args.sheet_name)
            rows = read_sheet_rows_from_table(headers, raw_sheet_rows)
            brief_text, eligible, _recommended = build_morning_brief(rows)
            long_term_text = build_long_term_brief(rows)
            tickets_text = build_paper_tickets(rows)
            review_candidates = select_review_candidates(rows)
            long_term_candidates = get_long_term_candidates(rows)
            payload = {
                "generatedAt": datetime.now().astimezone().isoformat(),
                "sourceLabel": "Inferno Runner",
                "brief": brief_text,
                "tickets": tickets_text,
                "longTermBrief": long_term_text,
                "eligibleTickers": [row["ticker"] for row in eligible],
                "reviewQueueTickers": [row["ticker"] for row in review_candidates],
                "longTermTickers": [row["ticker"] for row in long_term_candidates],
                "longTermRows": long_term_candidates,
                "rows": rows,
            }
            if cloud_state_restore is not None:
                payload["cloudStateRestore"] = cloud_state_restore
            approval_queue = write_approval_queue(payload)
            execution_queue = build_execution_queue(payload, approval_queue)
            save_execution_queue(execution_queue)
            payload["approvalQueue"] = approval_queue
            payload["executionQueue"] = execution_queue
            # Authority reads the latest snapshot from disk, so write a fresh
            # base snapshot before downstream risk artifacts ask for it.
            write_payload(payload)
            ticker_universe_audit = write_ticker_universe_audit(headers, raw_sheet_rows, rows)
            payload["tickerUniverseAudit"] = ticker_universe_audit
            try:
                from inferno_downloads_manager import import_downloads

                downloads_report = import_downloads()
                payload["downloadsManager"] = {
                    "importedFiles": downloads_report.get("importedFiles", 0),
                    "importedRows": downloads_report.get("importedRows", 0),
                    "quarantinedFiles": downloads_report.get("quarantinedFiles", 0),
                }
            except Exception as exc:  # noqa: BLE001
                payload["downloadsManager"] = {"error": str(exc)}
            try:
                from inferno_tos_fill_ingest import ingest_fill_log

                fill_ingest = ingest_fill_log()
                payload["fillIngest"] = {
                    "importedRows": fill_ingest.get("importedRows", 0),
                    "closedRows": fill_ingest.get("closedRows", 0),
                    "openedRows": fill_ingest.get("openedRows", 0),
                    "unmatchedCount": len(fill_ingest.get("unmatchedRows") or []),
                }
            except Exception as exc:  # noqa: BLE001
                payload["fillIngest"] = {"error": str(exc)}
            try:
                from inferno_outcome_reviewer import review_ledger

                outcome_review = review_ledger()
                payload["outcomeReview"] = {
                    "reviewed": outcome_review.get("reviewed", 0),
                    "closed": outcome_review.get("closed", 0),
                    "open": outcome_review.get("open", 0),
                }
            except Exception as exc:  # noqa: BLE001
                payload["outcomeReview"] = {"error": str(exc)}
            try:
                from inferno_shadow_evidence import review_shadow_evidence, save_shadow_evidence

                shadow_evidence = review_shadow_evidence()
                save_shadow_evidence(shadow_evidence)
                payload["shadowEvidence"] = {
                    "overall": shadow_evidence.get("overall"),
                    "researchVerdict": shadow_evidence.get("researchVerdict"),
                    "lastRun": shadow_evidence.get("lastRun"),
                }
            except Exception as exc:  # noqa: BLE001
                payload["shadowEvidence"] = {"error": str(exc)}
            try:
                from inferno_performance_analytics import build_performance_analytics, save_performance_analytics

                performance_analytics = build_performance_analytics()
                save_performance_analytics(performance_analytics)
                payload["performanceAnalytics"] = {
                    "count": performance_analytics.get("count", 0),
                    "deskVerdict": performance_analytics.get("deskVerdict"),
                    "closedMetrics": performance_analytics.get("closedMetrics"),
                }
            except Exception as exc:  # noqa: BLE001
                payload["performanceAnalytics"] = {"error": str(exc)}
            try:
                from inferno_strategy_lab import build_strategy_lab, save_strategy_lab

                strategy_lab = build_strategy_lab()
                save_strategy_lab(strategy_lab)
                payload["strategyLab"] = {
                    "deskVerdict": strategy_lab.get("deskVerdict"),
                    "overall": strategy_lab.get("overall"),
                    "promotionCandidates": strategy_lab.get("promotionCandidates", []),
                    "cooldownStrategies": strategy_lab.get("cooldownStrategies", []),
                }
            except Exception as exc:  # noqa: BLE001
                payload["strategyLab"] = {"error": str(exc)}
            try:
                from inferno_exposure_analytics import build_exposure_analytics, save_exposure_analytics

                exposure_analytics = build_exposure_analytics()
                save_exposure_analytics(exposure_analytics)
                payload["exposureAnalytics"] = {
                    "tickerCount": exposure_analytics.get("tickerCount", 0),
                    "verdict": exposure_analytics.get("verdict"),
                    "marketRegime": exposure_analytics.get("marketRegime"),
                    "largestSector": (exposure_analytics.get("sectorExposure") or {}).get("largestSector"),
                    "largestSetup": (exposure_analytics.get("setupExposure") or {}).get("largestSetup"),
                }
            except Exception as exc:  # noqa: BLE001
                payload["exposureAnalytics"] = {"error": str(exc)}
            try:
                from inferno_edge_research import build_edge_research, save_edge_research

                edge_research = build_edge_research(rows=payload["rows"])
                save_edge_research(edge_research)
                payload["edgeResearch"] = {
                    "topCatalystTickers": [item.get("ticker") for item in edge_research.get("topCatalystTrades", [])],
                    "topLongTermTickers": [item.get("ticker") for item in edge_research.get("topLongTermShovels", [])],
                    "watchlistTickers": [item.get("ticker") for item in edge_research.get("researchWatchlist", [])],
                    "scoredRows": edge_research.get("scoredRows", 0),
                }
            except Exception as exc:  # noqa: BLE001
                payload["edgeResearch"] = {"error": str(exc)}
            try:
                from inferno_authority_controller import build_authority_manifest, save_authority_manifest

                authority_manifest = build_authority_manifest()
                save_authority_manifest(authority_manifest)
                payload["authorityManifest"] = {
                    "decision": authority_manifest.get("decision"),
                    "evidence": authority_manifest.get("evidence"),
                }
            except Exception as exc:  # noqa: BLE001
                payload["authorityManifest"] = {"error": str(exc)}
            try:
                from inferno_capital_allocator import build_capital_allocator, save_capital_allocator

                capital_allocator = build_capital_allocator()
                save_capital_allocator(capital_allocator)
                payload["capitalAllocator"] = {
                    "sleeves": capital_allocator.get("sleeves"),
                    "verdict": capital_allocator.get("verdict"),
                    "optionsBudgetDollars": (capital_allocator.get("optionsLane") or {}).get("dailyBudgetDollars"),
                    "topOptionTickers": [
                        item.get("ticker")
                        for item in (capital_allocator.get("optionsLane") or {}).get("topCandidates", [])
                    ],
                    "topLongTermTickers": [
                        item.get("ticker")
                        for item in (capital_allocator.get("longTermLane") or {}).get("topCandidates", [])
                    ],
                }
            except Exception as exc:  # noqa: BLE001
                payload["capitalAllocator"] = {"error": str(exc)}
            try:
                from inferno_data_readiness_audit import run_audit

                data_readiness_audit = run_audit()
                payload["dataReadinessAudit"] = {
                    "verdict": data_readiness_audit.get("verdict"),
                    "dailyPrepReady": data_readiness_audit.get("dailyPrepReady"),
                    "researchReady": data_readiness_audit.get("researchReady"),
                    "brokerExecutionReady": data_readiness_audit.get("brokerExecutionReady"),
                    "manualExecutionRequired": data_readiness_audit.get("manualExecutionRequired"),
                }
            except Exception as exc:  # noqa: BLE001
                payload["dataReadinessAudit"] = {"error": str(exc)}
            try:
                from inferno_tos_sandbox import build_tos_sandbox_session, save_tos_sandbox_session

                tos_sandbox = build_tos_sandbox_session()
                save_tos_sandbox_session(tos_sandbox)
                payload["tosSandbox"] = {
                    "sandboxReady": tos_sandbox.get("sandboxReady"),
                    "stageableCount": tos_sandbox.get("stageableCount", 0),
                    "stageableTickers": [ticket.get("ticker") for ticket in tos_sandbox.get("stageableTickets", [])],
                }
            except Exception as exc:  # noqa: BLE001
                payload["tosSandbox"] = {"error": str(exc)}
            from inferno_approval_queue import approval_reply_section

            payload["brief"] += build_risk_desk_addendum(payload)
            payload["brief"] += approval_reply_section(approval_queue)
            write_payload(payload)

            email_sent = False
            email_error = None
            approval_dispatch = {"ok": True, "status": "skipped"}
            if not args.skip_email and smtp_configured():
                try:
                    email_sent = send_email(payload)
                except Exception as exc:  # noqa: BLE001
                    email_error = str(exc)
                else:
                    try:
                        from inferno_approval_dispatch import dispatch_pending_approval_prompts

                        approval_dispatch = dispatch_pending_approval_prompts()
                    except Exception as exc:  # noqa: BLE001
                        approval_dispatch = {"ok": False, "status": "dispatch-failed", "error": str(exc)}

            payload["approvalDispatch"] = approval_dispatch
            write_ops_status(payload, updater_results, email_sent, email_error=email_error)
            append_paper_trade_journal(build_paper_trade_entries(payload))
            if args.cloud_native:
                try:
                    from inferno_cloud_state import persist_cloud_artifacts

                    payload["cloudStatePersist"] = persist_cloud_artifacts()
                except Exception as exc:  # noqa: BLE001
                    payload["cloudStatePersist"] = {"ok": False, "errors": [str(exc)]}

            append_log(
                {
                    "job": "morning_inferno_pipeline",
                    "generatedAt": payload["generatedAt"],
                    "ok": True,
                    "emailSent": email_sent,
                    "emailError": email_error,
                    "eligibleTickers": payload["eligibleTickers"],
                    "longTermTickers": payload["longTermTickers"],
                    "executionReadyCount": execution_queue["activeReadyCount"],
                    "outcomeReview": payload.get("outcomeReview"),
                    "shadowEvidence": payload.get("shadowEvidence"),
                    "performanceAnalytics": payload.get("performanceAnalytics"),
                    "strategyLab": payload.get("strategyLab"),
                    "exposureAnalytics": payload.get("exposureAnalytics"),
                    "edgeResearch": payload.get("edgeResearch"),
                    "authorityManifest": payload.get("authorityManifest"),
                    "downloadsManager": payload.get("downloadsManager"),
                    "fillIngest": payload.get("fillIngest"),
                    "tosSandbox": payload.get("tosSandbox"),
                    "cloudStateRestore": payload.get("cloudStateRestore"),
                    "cloudStatePersist": payload.get("cloudStatePersist"),
                    "updaterScripts": [
                        {
                            "script": result["script"],
                            "ok": result["ok"],
                            "recovered": result.get("recovered", False),
                        }
                        for result in updater_results
                    ],
                }
            )
            print(summarize(updater_results, payload, email_sent, email_error=email_error))
            return 0
    except PipelineLockActive as exc:
        if args.automation:
            if not args.quiet_skip:
                print(str(exc))
            return 0
        print(f"Morning inferno pipeline skipped: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        failure_email_sent = False
        try:
            failure_email_sent = send_failure_email(str(exc), updater_results)
        except Exception:  # noqa: BLE001
            failure_email_sent = False
        append_log(
            {
                "job": "morning_inferno_pipeline",
                "generatedAt": datetime.now().astimezone().isoformat(),
                "ok": False,
                "error": str(exc),
                "failureEmailSent": failure_email_sent,
                "updaterScripts": [{"script": result["script"], "ok": result["ok"]} for result in updater_results],
            }
        )
        atomic_write_json(
            OPS_STATUS_FILE,
            {
                "generatedAt": datetime.now().astimezone().isoformat(),
                "ok": False,
                "error": str(exc),
                "failureEmailSent": failure_email_sent,
                "updaterScripts": [
                    {
                        "script": result["script"],
                        "ok": result["ok"],
                        "recovered": result.get("recovered", False),
                    }
                    for result in updater_results
                ],
            },
        )
        try:
            record_heartbeat(
                "dawn_cycle",
                status="fail",
                summary=f"morning pipeline failed: {exc}",
                detail={"failureEmailSent": failure_email_sent},
            )
        except Exception:  # noqa: BLE001
            pass
        print(f"Morning inferno pipeline failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

# =============================================================================
# DIABLO TRADING – SEND MORNING BRIEF (Added by Senior Engineer – 2026-04-15)
# =============================================================================
def send_morning_brief() -> dict:
    """
    Main entry point for morning brief.
    Sends the latest forged snapshot email and returns status.

    This helper is intentionally separate from the full dawn cycle. Use it for
    manual resend checks after the tracker has already been refreshed.
    """
    from inferno_config import local_now
    from server import send_email, smtp_configured

    print("[DIABLO] Inferno Dispatch - Morning Brief Initiated")

    if not smtp_configured():
        print("[DIABLO] SMTP not configured. Skipping email.")
        return {"status": "skipped", "sent": False, "reason": "smtp_not_configured"}

    try:
        from server import load_json_file, SNAPSHOT_FILE

        payload = load_json_file(SNAPSHOT_FILE) or {}
        rows = payload.get("rows", [])
        if not isinstance(payload, dict) or not rows:
            print("[DIABLO] No snapshot data available for brief.")
            return {"status": "no_data", "sent": False}

        # Rebuild the headline text from the saved rows so manual resends still
        # reflect the latest scoring logic without touching the sheet again.
        brief_text, shortlist, _recommended = build_morning_brief(rows)
        from inferno_approval_queue import approval_reply_section, load_queue

        approval_queue = load_queue()
        payload["approvalQueue"] = approval_queue
        payload["brief"] = brief_text
        payload["brief"] += build_risk_desk_addendum(payload)
        payload["brief"] += approval_reply_section(approval_queue)
        subject = f"[DIABLO TRADING] Hell Market Morning Brief – {local_now().strftime('%Y-%m-%d')}"
        success = send_email(payload, subject=subject)

        if success:
            print("[DIABLO] Morning brief sealed in blood and delivered.")
            return {"status": "sent", "sent": True, "shortlist_count": len(shortlist)}
        print("[DIABLO] Failed to send morning brief email.")
        return {"status": "email_failed", "sent": False}

    except Exception as e:
        print(f"[DIABLO] Critical failure in morning brief: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        send_failure_email(str(e), [])
        return {"status": "error", "sent": False, "error": str(e)}
