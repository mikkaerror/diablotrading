from __future__ import annotations

"""Install the bounded paper-evidence goal loop as a weekday LaunchAgent."""

import argparse
import os
import plistlib
import subprocess
from pathlib import Path

from inferno_config import ROOT, backtest_python


SERVICE_LABEL = "io.diablotrading.inferno-evidence-goal-loop"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
LOG_DIR = Path.home() / "Library" / "Logs" / "Inferno"
SERVICE_BIN_DIR = Path.home() / ".local" / "bin"
SERVICE_WRAPPER = SERVICE_BIN_DIR / "inferno_evidence_goal_loop_service.sh"
ENTRYPOINT = ROOT / "inferno_evidence_goal_loop.py"
DEFAULT_HOUR = 13
DEFAULT_MINUTE = 40


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
    """Build the weekday near-close schedule for evidence collection."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "Label": SERVICE_LABEL,
        "ProgramArguments": [str(SERVICE_WRAPPER)],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": False,
        "StartCalendarInterval": [
            {"Hour": hour, "Minute": minute, "Weekday": weekday}
            for weekday in range(1, 6)
        ],
        "StandardOutPath": str(LOG_DIR / "inferno_evidence_goal_loop.stdout.log"),
        "StandardErrorPath": str(LOG_DIR / "inferno_evidence_goal_loop.stderr.log"),
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(Path.home()),
        },
    }


def ensure_wrapper() -> None:
    runner_python = backtest_python()
    SERVICE_BIN_DIR.mkdir(parents=True, exist_ok=True)
    SERVICE_WRAPPER.write_text(
        "\n".join(
            [
                "#!/bin/zsh",
                "set -euo pipefail",
                f'cd "{ROOT}"',
                f'export BACKTEST_PYTHON="{runner_python}"',
                f'exec "{runner_python}" "{ENTRYPOINT}" run --max-iterations 2 "$@"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    SERVICE_WRAPPER.chmod(0o755)


def install(hour: int, minute: int) -> int:
    ensure_wrapper()
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(plist_payload(hour, minute), handle, sort_keys=False)
    run_launchctl("bootout", f"{user_domain()}/{SERVICE_LABEL}", check=False)
    result = run_launchctl("bootstrap", user_domain(), str(PLIST_PATH), check=False)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        return result.returncode
    print(f"Installed evidence goal-loop LaunchAgent at {PLIST_PATH}")
    print(f"Schedule: weekdays at {hour:02d}:{minute:02d} local")
    return 0


def uninstall() -> int:
    run_launchctl("bootout", f"{user_domain()}/{SERVICE_LABEL}", check=False)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    print("Evidence goal-loop LaunchAgent uninstalled.")
    return 0


def status() -> int:
    result = run_launchctl(
        "print",
        f"{user_domain()}/{SERVICE_LABEL}",
        check=False,
    )
    if result.returncode == 0:
        print(result.stdout)
    else:
        print(f"Agent {SERVICE_LABEL} is not loaded.")
        print(f"Expected plist: {PLIST_PATH}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the Inferno evidence goal-loop LaunchAgent."
    )
    parser.add_argument("command", choices=["install", "uninstall", "status"])
    parser.add_argument("--hour", type=int, default=DEFAULT_HOUR)
    parser.add_argument("--minute", type=int, default=DEFAULT_MINUTE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "install":
        if not (0 <= args.hour <= 23 and 0 <= args.minute <= 59):
            raise SystemExit("--hour must be 0..23 and --minute must be 0..59")
        return install(args.hour, args.minute)
    if args.command == "uninstall":
        return uninstall()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
