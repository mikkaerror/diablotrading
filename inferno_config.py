from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent

LABEL = "io.diablotrading.inferno-dawn-brief"
WATCHDOG_LABEL = "io.diablotrading.inferno-watchdog"
LEGACY_LABEL = "com.mikkasida.inferno-dawn-brief"
LEGACY_WATCHDOG_LABEL = "com.mikkasida.inferno-watchdog"

DEFAULT_SHEET_NAME = "Earnings Tracker"
UPDATER_SCRIPTS = [
    "BC-ATRPercentandIVRANK.py",
    "P-IV RANK CHANGE.py",
    "Q-ATRPcntZScore.py",
    "R-20DayATR.py",
]
UPDATER_LABEL = "BC/P/Q/R PyCharm jobs"
REVIEW_QUEUE_LIMIT = 5
LONG_TERM_QUEUE_LIMIT = 5
EXECUTION_QUEUE_LIMIT = 5
SCORE_FORMULA_COLUMNS = ("U", "V", "W", "X", "Y")

BROKER_EXECUTION_SURFACE = "thinkorswim"
BROKER_API_TARGET = "Schwab Trader API"
EXECUTION_MODE = "approval-only"
MAX_DAILY_RISK_UNITS = 3.0
MAX_SINGLE_TRADE_RISK_UNITS = 1.0
MAX_ACTIVE_EXECUTION_INTENTS = 3
EXECUTION_ALLOWED_SETUPS = (
    "Vertical Call",
    "Straddle",
    "Iron Condor",
)

AUTOMATION_WINDOW_START = "05:55"
AUTOMATION_WINDOW_END = "09:00"
WATCHDOG_WINDOW_END = "09:30"
AUTOMATION_ALLOWED_WEEKDAYS = {6, 0, 1, 2, 3, 4}  # Sunday through Friday

SERVICE_HOUR = 6
SERVICE_MINUTE = 0
WAKE_HOUR = 5
WAKE_MINUTE = 58
SAFETY_INTERVAL_SECONDS = 600
WATCHDOG_INTERVAL_SECONDS = 900

DEFAULT_KEEP_SNAPSHOTS = 10
DEFAULT_KEEP_BRIEFS = 10
DEFAULT_KEEP_TICKETS = 10
DEFAULT_KEEP_LOG_LINES = 500


def default_backtest_root() -> Path:
    if os.environ.get("BACKTEST_ROOT"):
        return Path(os.environ["BACKTEST_ROOT"]).expanduser()
    return Path.home() / "PycharmProjects" / "Backtest3.0"


def backtest_python() -> Path:
    if os.environ.get("BACKTEST_PYTHON"):
        return Path(os.environ["BACKTEST_PYTHON"]).expanduser()
    return default_backtest_root() / "venv" / "bin" / "python"


def local_now() -> datetime:
    return datetime.now().astimezone()


def local_today() -> str:
    return local_now().date().isoformat()


def parse_clock_minutes(value: str) -> int:
    hour_text, minute_text = value.strip().split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid clock value: {value}")
    return hour * 60 + minute


def in_time_window(now: datetime, start: str, end: str) -> bool:
    current_minutes = now.hour * 60 + now.minute
    start_minutes = parse_clock_minutes(start)
    end_minutes = parse_clock_minutes(end)
    if start_minutes <= end_minutes:
        return start_minutes <= current_minutes <= end_minutes
    return current_minutes >= start_minutes or current_minutes <= end_minutes
