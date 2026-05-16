from __future__ import annotations

"""Install a launchd service that runs the operator daily-loop on a schedule.

The daily loop chains the read-only diagnostics (cadence, decision briefs,
promotion gap, threshold sensitivity, strategy replay, daily success scorecard,
command-center refresh) into one combined digest. It is safe to run
unattended: it does not place trades, change authority, or mutate the
approval queue.

The default schedule fires once per weekday at 06:30 local time (after the
dawn cycle's 06:00 fire) and again at 16:30 (after market close) so the
operator gets fresh memos for both the morning decide window and the post-close
review window.

Use the same CLI shape as the other Inferno service installers:

  install     — write the plist and launchctl bootstrap
  uninstall   — bootout and remove the plist
  status      — print the launchctl print and plist path

Read-only by default; the installer never modifies the daily-loop code or the
authority manifest.
"""

import argparse
import os
import plistlib
import subprocess
from pathlib import Path

from inferno_config import ROOT, backtest_python


SERVICE_LABEL = "io.diablotrading.inferno-daily-loop"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
LOG_DIR = ROOT / "logs"
SERVICE_BIN_DIR = Path.home() / ".local" / "bin"
SERVICE_WRAPPER = SERVICE_BIN_DIR / "inferno_daily_loop_service.sh"
ENTRYPOINT = ROOT / "inferno_daily_loop.py"


# (hour, minute) pairs in local time. Defaults aim for: 06:30 (post dawn cycle)
# and 16:30 (post market close). Both are weekday-only via Weekday key.
DEFAULT_TIMES: tuple[tuple[int, int], ...] = ((6, 30), (16, 30))


def run_launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run launchctl for the current user domain."""
    return subprocess.run(["launchctl", *args], text=True, capture_output=True, check=check)


def user_domain() -> str:
    """Return the launchd user domain."""
    return f"gui/{os.getuid()}"


def plist_payload(times: tuple[tuple[int, int], ...]) -> dict:
    """Build the LaunchAgent payload for the daily loop.

    Uses StartCalendarInterval with explicit Hour/Minute entries plus Weekday
    1-5 (Mon-Fri) so weekends stay quiet. The loop is read-only so a weekend
    fire would not be unsafe — it's just noise.
    """
    LOG_DIR.mkdir(exist_ok=True)
    stdout_path = str(LOG_DIR / "inferno_daily_loop.stdout.log")
    stderr_path = str(LOG_DIR / "inferno_daily_loop.stderr.log")

    intervals = []
    for hour, minute in times:
        for weekday in range(1, 6):  # 1=Mon ... 5=Fri
            intervals.append({"Hour": hour, "Minute": minute, "Weekday": weekday})

    return {
        "Label": SERVICE_LABEL,
        "ProgramArguments": ["/bin/zsh", str(SERVICE_WRAPPER)],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": False,
        "StartCalendarInterval": intervals,
        "StandardOutPath": stdout_path,
        "StandardErrorPath": stderr_path,
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(Path.home()),
        },
    }


def ensure_wrapper() -> None:
    """Write the wrapper script that launchd actually executes."""
    runner_python = backtest_python()
    SERVICE_BIN_DIR.mkdir(parents=True, exist_ok=True)
    SERVICE_WRAPPER.write_text(
        "\n".join(
            [
                "#!/bin/zsh",
                "set -euo pipefail",
                f'cd "{ROOT}"',
                f'export BACKTEST_PYTHON="{runner_python}"',
                f'exec "{runner_python}" "{ENTRYPOINT}" run "$@"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    SERVICE_WRAPPER.chmod(0o755)


def install(times: tuple[tuple[int, int], ...]) -> int:
    """Install and load the daily-loop LaunchAgent."""
    ensure_wrapper()
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(plist_payload(times), handle)
    # bootout first so a reinstall doesn't double-load; ignore failures.
    run_launchctl("bootout", f"{user_domain()}/{SERVICE_LABEL}", check=False)
    bootstrap = run_launchctl("bootstrap", user_domain(), str(PLIST_PATH), check=False)
    if bootstrap.returncode != 0:
        print(bootstrap.stdout)
        print(bootstrap.stderr)
        return bootstrap.returncode
    print(f"Installed daily-loop LaunchAgent at {PLIST_PATH}")
    print(f"Times (local, weekdays only): {times}")
    print(f"stdout log: {LOG_DIR / 'inferno_daily_loop.stdout.log'}")
    print(f"stderr log: {LOG_DIR / 'inferno_daily_loop.stderr.log'}")
    return 0


def uninstall() -> int:
    """Boot out the agent and remove the plist."""
    run_launchctl("bootout", f"{user_domain()}/{SERVICE_LABEL}", check=False)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    print("Daily-loop LaunchAgent uninstalled.")
    return 0


def status() -> int:
    """Print agent status and plist location."""
    result = run_launchctl("print", f"{user_domain()}/{SERVICE_LABEL}", check=False)
    if result.returncode == 0:
        print(result.stdout)
    else:
        print(f"Agent {SERVICE_LABEL} is not loaded.")
        print(f"Expected plist: {PLIST_PATH}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install the Inferno daily-loop LaunchAgent.")
    parser.add_argument("command", choices=["install", "uninstall", "status"])
    parser.add_argument(
        "--times",
        nargs="*",
        default=[f"{h:02d}:{m:02d}" for h, m in DEFAULT_TIMES],
        help="Local times (HH:MM) when the loop should fire on weekdays.",
    )
    return parser.parse_args()


def parse_times(raw: list[str]) -> tuple[tuple[int, int], ...]:
    """Parse a list of HH:MM strings into hour/minute tuples."""
    parsed: list[tuple[int, int]] = []
    for entry in raw:
        if ":" not in entry:
            raise SystemExit(f"--times entries must be HH:MM (got {entry})")
        hour_str, minute_str = entry.split(":", 1)
        parsed.append((int(hour_str), int(minute_str)))
    return tuple(parsed)


def main() -> int:
    args = parse_args()
    if args.command == "install":
        return install(parse_times(args.times))
    if args.command == "uninstall":
        return uninstall()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
