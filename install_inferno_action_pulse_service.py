from __future__ import annotations

"""Install the twice-daily Inferno action-pulse LaunchAgent.

Default schedule:
- 07:05 local weekday open watch, after the dawn data refresh and before the
  07:30 Mountain market open
- 13:30 local weekday pre-close watch, roughly 30 minutes before equity close

The service sends email but remains read-only. It does not approve, route, or
submit trades.
"""

import argparse
import os
import plistlib
import subprocess
from pathlib import Path

from inferno_config import ROOT, backtest_python


SERVICE_LABEL = "io.diablotrading.inferno-action-pulse"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
LOG_DIR = ROOT / "logs"
SERVICE_BIN_DIR = Path.home() / ".local" / "bin"
SERVICE_WRAPPER = SERVICE_BIN_DIR / "inferno_action_pulse_service.sh"
ENTRYPOINT = ROOT / "inferno_action_pulse.py"
DEFAULT_TIMES: tuple[tuple[str, int, int], ...] = (("open", 7, 5), ("preclose", 13, 30))


def user_domain() -> str:
    """Return the launchd user domain for this Mac account."""
    return f"gui/{os.getuid()}"


def run_launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run launchctl for the current user."""
    return subprocess.run(["launchctl", *args], text=True, capture_output=True, check=check)


def parse_schedule(raw: list[str]) -> tuple[tuple[str, int, int], ...]:
    """Parse phase=HH:MM entries into launchd schedule rows."""
    if not raw:
        return DEFAULT_TIMES
    parsed: list[tuple[str, int, int]] = []
    for entry in raw:
        if "=" not in entry or ":" not in entry:
            raise SystemExit(f"--times entries must look like phase=HH:MM (got {entry})")
        phase, clock = entry.split("=", 1)
        hour_text, minute_text = clock.split(":", 1)
        if phase not in {"open", "preclose", "manual"}:
            raise SystemExit(f"unsupported phase {phase}")
        parsed.append((phase, int(hour_text), int(minute_text)))
    return tuple(parsed)


def ensure_wrapper(deployable_cash: float) -> None:
    """Write the launchd wrapper that dispatches by phase argument."""
    runner_python = backtest_python()
    SERVICE_BIN_DIR.mkdir(parents=True, exist_ok=True)
    SERVICE_WRAPPER.write_text(
        "\n".join(
            [
                "#!/bin/zsh",
                "set -euo pipefail",
                f'cd "{ROOT}"',
                f'export BACKTEST_PYTHON="{runner_python}"',
                'PHASE="${1:-manual}"',
                (
                    f'exec "{runner_python}" "{ENTRYPOINT}" '
                    f'--phase "$PHASE" --deployable-cash {deployable_cash:.2f} --send'
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    SERVICE_WRAPPER.chmod(0o755)


def plist_payload(schedule: tuple[tuple[str, int, int], ...]) -> dict:
    """Build the LaunchAgent plist payload."""
    LOG_DIR.mkdir(exist_ok=True)
    # launchd cannot pass different arguments per StartCalendarInterval entry
    # inside one plist. The wrapper infers phase from local clock: morning
    # fires are open watch, afternoon fires are pre-close watch.
    program_args = [
        "/bin/zsh",
        "-c",
        f'H="$(date +%H)"; if [ "$H" -lt 12 ]; then exec "{SERVICE_WRAPPER}" open; else exec "{SERVICE_WRAPPER}" preclose; fi',
    ]
    return {
        "Label": SERVICE_LABEL,
        "ProgramArguments": program_args,
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": False,
        "StartCalendarInterval": [
            {"Hour": hour, "Minute": minute, "Weekday": weekday}
            for _phase, hour, minute in schedule
            for weekday in range(1, 6)
        ],
        "StandardOutPath": str(LOG_DIR / "inferno_action_pulse.stdout.log"),
        "StandardErrorPath": str(LOG_DIR / "inferno_action_pulse.stderr.log"),
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(Path.home()),
        },
    }


def install(schedule: tuple[tuple[str, int, int], ...], deployable_cash: float) -> int:
    """Install and load the LaunchAgent."""
    ensure_wrapper(deployable_cash)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(plist_payload(schedule), handle)
    run_launchctl("bootout", f"{user_domain()}/{SERVICE_LABEL}", check=False)
    result = run_launchctl("bootstrap", user_domain(), str(PLIST_PATH), check=False)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        return result.returncode
    print(f"Installed action-pulse LaunchAgent at {PLIST_PATH}")
    print("Times (local weekdays): " + ", ".join(f"{phase}={hour:02d}:{minute:02d}" for phase, hour, minute in schedule))
    print(f"Deployable cash basis: ${deployable_cash:,.2f}")
    return 0


def uninstall() -> int:
    """Unload and remove the LaunchAgent."""
    run_launchctl("bootout", f"{user_domain()}/{SERVICE_LABEL}", check=False)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    print("Action-pulse LaunchAgent uninstalled.")
    return 0


def status() -> int:
    """Print LaunchAgent status."""
    result = run_launchctl("print", f"{user_domain()}/{SERVICE_LABEL}", check=False)
    if result.returncode == 0:
        print(result.stdout)
    else:
        print(f"Agent {SERVICE_LABEL} is not loaded.")
        print(f"Expected plist: {PLIST_PATH}")
    return 0


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Install the Inferno action-pulse LaunchAgent.")
    parser.add_argument("command", choices=["install", "uninstall", "status"])
    parser.add_argument(
        "--times",
        nargs="*",
        default=[],
        help="Schedule entries like open=07:05 preclose=13:30.",
    )
    parser.add_argument("--deployable-cash", type=float, default=1000.0)
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    if args.command == "install":
        return install(parse_schedule(args.times), args.deployable_cash)
    if args.command == "uninstall":
        return uninstall()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
