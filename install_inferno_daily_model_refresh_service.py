from __future__ import annotations

"""Install the full research-only daily model refresh as a LaunchAgent."""

import argparse
import os
import plistlib
import subprocess
from pathlib import Path

from inferno_config import ROOT, backtest_python


SERVICE_LABEL = "io.diablotrading.inferno-daily-model-refresh"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
LOG_DIR = Path.home() / "Library" / "Logs" / "Inferno"
SERVICE_BIN_DIR = Path.home() / ".local" / "bin"
SERVICE_WRAPPER = SERVICE_BIN_DIR / "inferno_daily_model_refresh_service.sh"
SERVICE_ENTRYPOINT = SERVICE_BIN_DIR / "inferno_daily_model_refresh.sh"
ENTRYPOINT = ROOT / "run_inferno_daily_model_refresh.sh"
DEFAULT_TIMES: tuple[tuple[int, int], ...] = ((6, 45), (16, 20))


def run_launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *args], text=True, capture_output=True, check=check)


def user_domain() -> str:
    return f"gui/{os.getuid()}"


def plist_payload(times: tuple[tuple[int, int], ...]) -> dict:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    intervals = [
        {"Hour": hour, "Minute": minute, "Weekday": weekday}
        for hour, minute in times
        for weekday in range(1, 6)
    ]
    return {
        "Label": SERVICE_LABEL,
        "ProgramArguments": [str(SERVICE_WRAPPER)],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": False,
        "StartCalendarInterval": intervals,
        "StandardOutPath": str(LOG_DIR / "inferno_daily_model_refresh.stdout.log"),
        "StandardErrorPath": str(LOG_DIR / "inferno_daily_model_refresh.stderr.log"),
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(Path.home()),
        },
    }


def ensure_wrapper() -> None:
    runner_python = backtest_python()
    SERVICE_BIN_DIR.mkdir(parents=True, exist_ok=True)
    SERVICE_ENTRYPOINT.write_text(ENTRYPOINT.read_text(encoding="utf-8"), encoding="utf-8")
    SERVICE_ENTRYPOINT.chmod(0o755)
    SERVICE_WRAPPER.write_text(
        "\n".join(
            [
                "#!/bin/zsh",
                "set -euo pipefail",
                f'cd "{ROOT}"',
                f'export BACKTEST_PYTHON="{runner_python}"',
                f'export INFERNO_PYTHON="{runner_python}"',
                f'export INFERNO_ROOT="{ROOT}"',
                f'exec /bin/bash "{SERVICE_ENTRYPOINT}" "$@"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    SERVICE_WRAPPER.chmod(0o755)


def install(times: tuple[tuple[int, int], ...]) -> int:
    ensure_wrapper()
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(plist_payload(times), handle, sort_keys=False)
    domain = user_domain()
    run_launchctl("bootout", domain, str(PLIST_PATH), check=False)
    result = run_launchctl("bootstrap", domain, str(PLIST_PATH), check=False)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        return result.returncode
    run_launchctl("enable", f"{domain}/{SERVICE_LABEL}", check=False)
    print(f"Installed daily model refresh LaunchAgent at {PLIST_PATH}")
    print(f"Schedule: weekdays at {', '.join(f'{h:02d}:{m:02d}' for h, m in times)} local")
    return 0


def uninstall() -> int:
    domain = user_domain()
    run_launchctl("bootout", domain, str(PLIST_PATH), check=False)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    print("Daily model refresh LaunchAgent uninstalled.")
    return 0


def status() -> int:
    result = run_launchctl("print", f"{user_domain()}/{SERVICE_LABEL}", check=False)
    if result.returncode == 0:
        print(result.stdout)
    else:
        print(f"Agent {SERVICE_LABEL} is not loaded.")
        print(f"Expected plist: {PLIST_PATH}")
    return 0


def parse_times(raw: list[str]) -> tuple[tuple[int, int], ...]:
    parsed: list[tuple[int, int]] = []
    for entry in raw:
        if ":" not in entry:
            raise SystemExit(f"--times entries must be HH:MM (got {entry})")
        hour_str, minute_str = entry.split(":", 1)
        hour = int(hour_str)
        minute = int(minute_str)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise SystemExit("--times entries must be valid HH:MM values")
        parsed.append((hour, minute))
    return tuple(parsed)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install the full Inferno daily model refresh LaunchAgent.")
    parser.add_argument("command", choices=["install", "uninstall", "status"])
    parser.add_argument(
        "--times",
        nargs="*",
        default=[f"{hour:02d}:{minute:02d}" for hour, minute in DEFAULT_TIMES],
        help="Local weekday times (HH:MM) when the full refresh should run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "install":
        return install(parse_times(args.times))
    if args.command == "uninstall":
        return uninstall()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
