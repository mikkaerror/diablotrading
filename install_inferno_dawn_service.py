from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LABEL = "io.diablotrading.inferno-dawn-brief"
WATCHDOG_LABEL = "io.diablotrading.inferno-watchdog"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
WATCHDOG_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{WATCHDOG_LABEL}.plist"
LOG_DIR = ROOT / "logs"
RUNNER = ROOT / "run_inferno_dawn_cycle.sh"
PIPELINE_ENTRYPOINT = ROOT / "inferno_dawn_pipeline.py"
WATCHDOG_ENTRYPOINT = ROOT / "inferno_watchdog.py"
SERVICE_BIN_DIR = Path.home() / ".local" / "bin"
SERVICE_WRAPPER = SERVICE_BIN_DIR / "inferno_dawn_cycle_service.sh"
WATCHDOG_WRAPPER = SERVICE_BIN_DIR / "inferno_watchdog_service.sh"

def default_backtest_root() -> Path:
    if os.environ.get("BACKTEST_ROOT"):
        return Path(os.environ["BACKTEST_ROOT"]).expanduser()
    return Path.home() / "PycharmProjects" / "Backtest3.0"


def backtest_python() -> Path:
    if os.environ.get("BACKTEST_PYTHON"):
        return Path(os.environ["BACKTEST_PYTHON"]).expanduser()
    return default_backtest_root() / "venv" / "bin" / "python"


def run_launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *args],
        text=True,
        capture_output=True,
        check=check,
    )


def user_domain() -> str:
    return f"gui/{os.getuid()}"


def plist_payload(hour: int, minute: int) -> dict:
    LOG_DIR.mkdir(exist_ok=True)
    stdout_path = str(LOG_DIR / "inferno_dawn.stdout.log")
    stderr_path = str(LOG_DIR / "inferno_dawn.stderr.log")
    return {
        "Label": LABEL,
        "ProgramArguments": ["/bin/zsh", str(SERVICE_WRAPPER)],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": False,
        "StartCalendarInterval": [
            {"Weekday": weekday, "Hour": hour, "Minute": minute}
            for weekday in (0, 1, 2, 3, 4, 5)
        ],
        "StandardOutPath": stdout_path,
        "StandardErrorPath": stderr_path,
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(Path.home()),
        },
    }


def watchdog_plist_payload(hour: int, minute: int) -> dict:
    LOG_DIR.mkdir(exist_ok=True)
    stdout_path = str(LOG_DIR / "inferno_watchdog.stdout.log")
    stderr_path = str(LOG_DIR / "inferno_watchdog.stderr.log")
    return {
        "Label": WATCHDOG_LABEL,
        "ProgramArguments": ["/bin/zsh", str(WATCHDOG_WRAPPER)],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": False,
        "StartCalendarInterval": [
            {"Weekday": weekday, "Hour": hour, "Minute": minute}
            for weekday in (0, 1, 2, 3, 4, 5)
        ],
        "StandardOutPath": stdout_path,
        "StandardErrorPath": stderr_path,
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(Path.home()),
        },
    }


def ensure_service_wrapper() -> None:
    runner_python = backtest_python()
    SERVICE_BIN_DIR.mkdir(parents=True, exist_ok=True)
    SERVICE_WRAPPER.write_text(
        "\n".join(
            [
                "#!/bin/zsh",
                "set -euo pipefail",
                f'cd "{ROOT}"',
                f'export BACKTEST_PYTHON="{runner_python}"',
                f'exec "{runner_python}" "{PIPELINE_ENTRYPOINT}" "$@"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    SERVICE_WRAPPER.chmod(0o755)
    WATCHDOG_WRAPPER.write_text(
        "\n".join(
            [
                "#!/bin/zsh",
                "set -euo pipefail",
                f'cd "{ROOT}"',
                f'exec "{runner_python}" "{WATCHDOG_ENTRYPOINT}" "$@"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    WATCHDOG_WRAPPER.chmod(0o755)


def install(hour: int, minute: int) -> int:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    ensure_service_wrapper()
    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(plist_payload(hour, minute), handle, sort_keys=False)
    with WATCHDOG_PLIST_PATH.open("wb") as handle:
        plistlib.dump(watchdog_plist_payload(hour, minute + 20 if minute <= 39 else 59), handle, sort_keys=False)

    domain = user_domain()
    run_launchctl("bootout", domain, str(PLIST_PATH), check=False)
    run_launchctl("bootout", domain, str(WATCHDOG_PLIST_PATH), check=False)
    run_launchctl("bootstrap", domain, str(PLIST_PATH))
    run_launchctl("bootstrap", domain, str(WATCHDOG_PLIST_PATH))
    run_launchctl("enable", f"{domain}/{LABEL}")
    run_launchctl("enable", f"{domain}/{WATCHDOG_LABEL}")

    print(f"Installed {LABEL}")
    print(f"LaunchAgent: {PLIST_PATH}")
    print(f"Schedule: Sunday through Friday at {hour:02d}:{minute:02d}")
    print(f"Runner: {SERVICE_WRAPPER}")
    print(f"Installed {WATCHDOG_LABEL}")
    print(f"Watchdog LaunchAgent: {WATCHDOG_PLIST_PATH}")
    print(f"Watchdog Runner: {WATCHDOG_WRAPPER}")
    return 0


def uninstall() -> int:
    domain = user_domain()
    run_launchctl("bootout", domain, str(PLIST_PATH), check=False)
    run_launchctl("bootout", domain, str(WATCHDOG_PLIST_PATH), check=False)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    if WATCHDOG_PLIST_PATH.exists():
        WATCHDOG_PLIST_PATH.unlink()
    print(f"Removed {LABEL}")
    print(f"Removed {WATCHDOG_LABEL}")
    return 0


def status() -> int:
    print(f"Label: {LABEL}")
    print(f"Plist: {PLIST_PATH}")
    print(f"Installed: {'yes' if PLIST_PATH.exists() else 'no'}")
    print(f"Watchdog Label: {WATCHDOG_LABEL}")
    print(f"Watchdog Plist: {WATCHDOG_PLIST_PATH}")
    print(f"Watchdog Installed: {'yes' if WATCHDOG_PLIST_PATH.exists() else 'no'}")

    if not PLIST_PATH.exists():
        return 1

    domain = user_domain()
    result = run_launchctl("print", f"{domain}/{LABEL}", check=False)
    watchdog_result = run_launchctl("print", f"{domain}/{WATCHDOG_LABEL}", check=False)
    loaded = result.returncode == 0
    watchdog_loaded = watchdog_result.returncode == 0
    print(f"Loaded: {'yes' if loaded else 'no'}")
    print(f"Watchdog Loaded: {'yes' if watchdog_loaded else 'no'}")
    if loaded:
        print("launchctl status: ok")
    else:
        stderr = result.stderr.strip() or result.stdout.strip()
        if stderr:
            print(stderr)
    if not watchdog_loaded:
        stderr = watchdog_result.stderr.strip() or watchdog_result.stdout.strip()
        if stderr:
            print(stderr)
    return 0 if loaded and watchdog_loaded else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install or inspect the Sunday-through-Friday 6 AM inferno dawn brief service.")
    parser.add_argument("command", nargs="?", default="install", choices=["install", "uninstall", "status"])
    parser.add_argument("--hour", type=int, default=6, help="24-hour local time for the Sunday-through-Friday launchd schedule")
    parser.add_argument("--minute", type=int, default=0, help="Minute of the hour for the weekday launchd schedule")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "install":
        return install(args.hour, args.minute)
    if args.command == "uninstall":
        return uninstall()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
