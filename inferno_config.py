from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LOCAL_ENV_FILE = ROOT / ".env.inferno"
LOCAL_BIN_DIR = Path.home() / ".local" / "bin"
LOCAL_GCLOUD_BIN = LOCAL_BIN_DIR / "gcloud"


def _strip_wrapped_quotes(value: str) -> str:
    """Remove one matching layer of wrapping quotes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_point(value: str, *, default: tuple[int, int]) -> tuple[int, int]:
    """Parse a simple `x,y` point from local config text."""
    raw = (value or "").strip()
    if not raw:
        return default
    try:
        x_text, y_text = raw.split(",", 1)
        return int(x_text.strip()), int(y_text.strip())
    except Exception:
        return default


def _parse_point_list(value: str, *, default: tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]:
    """Parse a semicolon-delimited list of `x,y` coordinates.

    The desktop route helper uses a small ordered candidate list so one stale
    coordinate does not strand the whole paperMoney export lane.
    """
    raw = (value or "").strip()
    if not raw:
        return default

    points: list[tuple[int, int]] = []
    for chunk in raw.split(";"):
        point = _parse_point(chunk.strip(), default=(-1, -1))
        if point == (-1, -1):
            continue
        if point not in points:
            points.append(point)
    return tuple(points) or default


def _parse_suffixes(value: str) -> tuple[str, ...]:
    """Parse a comma-delimited account suffix allowlist."""
    pieces = []
    for chunk in (value or "").split(","):
        digits = "".join(re.findall(r"\d", chunk))
        if digits and digits not in pieces:
            pieces.append(digits)
    return tuple(pieces)


def account_suffix_allowed(suffix: str | None) -> bool:
    """Return True when a visible broker account suffix is explicitly allowed."""
    digits = "".join(re.findall(r"\d", str(suffix or "")))
    return bool(digits and digits in TOS_ALLOWED_ACCOUNT_SUFFIXES)


def approved_account_scope(default: str = "configured approved account") -> str:
    """Render the configured broker account scope without hard-coding private identifiers."""
    if not TOS_ALLOWED_ACCOUNT_SUFFIXES:
        return default
    if len(TOS_ALLOWED_ACCOUNT_SUFFIXES) == 1:
        return f"account ending {TOS_ALLOWED_ACCOUNT_SUFFIXES[0]}"
    suffixes = ", ".join(TOS_ALLOWED_ACCOUNT_SUFFIXES)
    return f"approved accounts ending in {suffixes}"


def _load_local_env_file(path: Path) -> None:
    """Load stable local automation settings without overriding shell vars."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), _strip_wrapped_quotes(value.strip()))


_load_local_env_file(LOCAL_ENV_FILE)

DOWNLOADS_SCAN_DIR = Path(os.environ.get("DOWNLOADS_SCAN_DIR", str(Path.home() / "Downloads"))).expanduser()
DOWNLOADS_LOOKBACK_HOURS = int(os.environ.get("DOWNLOADS_LOOKBACK_HOURS", "168"))
DOWNLOADS_WATCH_INTERVAL_SECONDS = int(os.environ.get("DOWNLOADS_WATCH_INTERVAL_SECONDS", "600"))
DESKTOP_AUTOMATION_INTERVAL_SECONDS = int(os.environ.get("DESKTOP_AUTOMATION_INTERVAL_SECONDS", "900"))
DOWNLOADS_WATCH_WINDOW_START = os.environ.get("DOWNLOADS_WATCH_WINDOW_START", "06:00")
DOWNLOADS_WATCH_WINDOW_END = os.environ.get("DOWNLOADS_WATCH_WINDOW_END", "16:30")
DOWNLOADS_WATCH_ALLOWED_WEEKDAYS = {0, 1, 2, 3, 4}
TOS_APP_PATH = Path(os.environ.get("TOS_APP_PATH", str(Path.home() / "thinkorswim" / "thinkorswim.app"))).expanduser()
TOS_EXPORT_AUTOMATION_ENABLED = os.environ.get("TOS_EXPORT_AUTOMATION_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
TOS_BACKGROUND_EXPORT_ALLOWED = os.environ.get("TOS_BACKGROUND_EXPORT_ALLOWED", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
TOS_EXPORT_SHORTCUT = os.environ.get("TOS_EXPORT_SHORTCUT", "command+shift+e").strip()
TOS_EXPORT_PRE_DELAY_SECONDS = float(os.environ.get("TOS_EXPORT_PRE_DELAY_SECONDS", "3"))
TOS_EXPORT_POST_DELAY_SECONDS = float(os.environ.get("TOS_EXPORT_POST_DELAY_SECONDS", "8"))
TOS_EXPORT_COOLDOWN_SECONDS = int(os.environ.get("TOS_EXPORT_COOLDOWN_SECONDS", "300"))
TOS_ALLOW_LIVE_READONLY = os.environ.get("TOS_ALLOW_LIVE_READONLY", "0").strip().lower() in {"1", "true", "yes", "on"}
TOS_ALLOWED_ACCOUNT_SUFFIXES = _parse_suffixes(os.environ.get("TOS_ALLOWED_ACCOUNT_SUFFIXES", ""))
TOS_PROCESS_CANDIDATES = tuple(
    dict.fromkeys(
        candidate
        for candidate in (
            os.environ.get("TOS_PROCESS_NAME", "").strip(),
            TOS_APP_PATH.stem,
            "thinkorswim",
            "java-arm",
            "java",
        )
        if candidate
    )
)
TOS_MAIN_WINDOW_TOKEN = os.environ.get("TOS_MAIN_WINDOW_TOKEN", "Main@thinkorswim").strip()
TOS_SAFE_AUTOMATION_PANELS = tuple(
    panel.strip()
    for panel in os.environ.get("TOS_SAFE_AUTOMATION_PANELS", "Monitor,MarketWatch,Charts").split(",")
    if panel.strip()
)
TOS_UNSAFE_AUTOMATION_PANELS = tuple(
    panel.strip()
    for panel in os.environ.get("TOS_UNSAFE_AUTOMATION_PANELS", "Trade,Analyze,Scan").split(",")
    if panel.strip()
)
TOS_MONITOR_TAB_POINT = _parse_point(
    os.environ.get("TOS_MONITOR_TAB_POINT", "380,76"),
    default=(380, 76),
)
TOS_MONITOR_TAB_CANDIDATES = _parse_point_list(
    os.environ.get("TOS_MONITOR_TAB_CANDIDATES", "380,76;250,70;392,57"),
    default=(TOS_MONITOR_TAB_POINT,),
)
TOS_ACCOUNT_STATEMENT_TAB_POINT = _parse_point(
    os.environ.get("TOS_ACCOUNT_STATEMENT_TAB_POINT", "580,88"),
    default=(580, 88),
)
TOS_UI_ROUTE_STEP_DELAY_SECONDS = float(os.environ.get("TOS_UI_ROUTE_STEP_DELAY_SECONDS", "1.0"))
TOS_UI_ROUTE_RECOVERY_DELAY_SECONDS = float(os.environ.get("TOS_UI_ROUTE_RECOVERY_DELAY_SECONDS", "8.0"))
GCLOUD_BIN = os.environ.get("GCLOUD_BIN", str(LOCAL_GCLOUD_BIN)).strip()

SCHWAB_API_BASE_URL = os.environ.get("SCHWAB_API_BASE_URL", "https://api.schwabapi.com").strip().rstrip("/")
SCHWAB_AUTH_BASE_URL = os.environ.get("SCHWAB_AUTH_BASE_URL", "https://api.schwabapi.com/v1/oauth").strip().rstrip("/")
SCHWAB_CLIENT_ID = os.environ.get("SCHWAB_CLIENT_ID", "").strip()
SCHWAB_CLIENT_SECRET = os.environ.get("SCHWAB_CLIENT_SECRET", "").strip()
SCHWAB_REDIRECT_URI = os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1").strip()
SCHWAB_TOKEN_FILE = Path(
    os.environ.get("SCHWAB_TOKEN_FILE", str(ROOT / ".secrets" / "schwab_token.json"))
).expanduser()
SCHWAB_OPTIONS_ENABLED = os.environ.get("SCHWAB_OPTIONS_ENABLED", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SCHWAB_OPTIONS_TIMEOUT_SECONDS = float(os.environ.get("SCHWAB_OPTIONS_TIMEOUT_SECONDS", "20"))
SCHWAB_OPTIONS_SYMBOL_LIMIT = int(os.environ.get("SCHWAB_OPTIONS_SYMBOL_LIMIT", "12"))

LABEL = "io.diablotrading.inferno-dawn-brief"
WATCHDOG_LABEL = "io.diablotrading.inferno-watchdog"
DOWNLOADS_WATCH_LABEL = "io.diablotrading.inferno-downloads-watch"
DESKTOP_AUTOMATION_LABEL = "io.diablotrading.inferno-desktop-automation"
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
BROKER_ADAPTER_MODE = os.environ.get("BROKER_ADAPTER_MODE", "OFF").upper()
AUTO_PAPER_SELECTION_ENABLED = os.environ.get("INFERNO_AUTO_PAPER_SELECTION", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
MAX_DAILY_RISK_UNITS = 3.0
MAX_SINGLE_TRADE_RISK_UNITS = 1.0
MAX_ACTIVE_EXECUTION_INTENTS = 3
MAX_SINGLE_TICKET_DOLLARS = float(os.environ.get("MAX_SINGLE_TICKET_DOLLARS", "500"))
MAX_DAILY_TICKET_DOLLARS = float(os.environ.get("MAX_DAILY_TICKET_DOLLARS", "1500"))
MAX_OPEN_PAPER_TICKETS = int(os.environ.get("MAX_OPEN_PAPER_TICKETS", "5"))
MAX_STRIKE_PLAN_AGE_MINUTES = int(os.environ.get("MAX_STRIKE_PLAN_AGE_MINUTES", "180"))
MIN_DEBIT_SPREAD_REWARD_RISK = float(os.environ.get("MIN_DEBIT_SPREAD_REWARD_RISK", "0.50"))
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
