from __future__ import annotations

"""Install a launchd service for the guarded desktop automation coordinator.

This service is the local broker-adjacent orchestrator. It verifies the
thinkorswim lane, ingests already-exported files, and rebuilds the daily
paperMoney sandbox on a repeating interval during the operator session.
Fresh TOS exports remain manual/supervised by default so launchd cannot keep
foregrounding the broker app.
"""

import argparse
import os
import plistlib
import subprocess
from pathlib import Path

from inferno_config import (
    DESKTOP_AUTOMATION_INTERVAL_SECONDS,
    DESKTOP_AUTOMATION_LABEL,
    LOCAL_ENV_FILE,
    ROOT,
    backtest_python,
)


WATCH_LABEL = DESKTOP_AUTOMATION_LABEL
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{WATCH_LABEL}.plist"
LOG_DIR = Path.home() / "Library" / "Logs" / "Inferno"
SERVICE_BIN_DIR = Path.home() / ".local" / "bin"
SERVICE_WRAPPER = SERVICE_BIN_DIR / "inferno_desktop_automation_service.sh"
ENTRYPOINT = ROOT / "inferno_desktop_automation.py"


def run_launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run launchctl for the current user domain."""
    return subprocess.run(["launchctl", *args], text=True, capture_output=True, check=check)


def user_domain() -> str:
    """Return the launchd user domain."""
    return f"gui/{os.getuid()}"


def plist_payload(export_first: bool, require_tos_running: bool) -> dict:
    """Build the LaunchAgent payload for the desktop coordinator."""
    LOG_DIR.mkdir(exist_ok=True)
    stdout_path = str(LOG_DIR / "inferno_desktop_automation.stdout.log")
    stderr_path = str(LOG_DIR / "inferno_desktop_automation.stderr.log")
    return {
        "Label": WATCH_LABEL,
        "ProgramArguments": [str(SERVICE_WRAPPER)],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "StartInterval": DESKTOP_AUTOMATION_INTERVAL_SECONDS,
        "StandardOutPath": stdout_path,
        "StandardErrorPath": stderr_path,
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(Path.home()),
        },
    }


def ensure_wrapper(export_first: bool, require_tos_running: bool) -> None:
    """Write the wrapper script used by launchd."""
    runner_python = backtest_python()
    SERVICE_BIN_DIR.mkdir(parents=True, exist_ok=True)
    export_flag = "--export-first " if export_first else ""
    tos_flag = "--require-tos-running " if require_tos_running else ""
    SERVICE_WRAPPER.write_text(
        "\n".join(
            [
                "#!/bin/zsh",
                "set -euo pipefail",
                f'cd "{ROOT}"',
                f'export BACKTEST_PYTHON="{runner_python}"',
                f'exec "{runner_python}" "{ENTRYPOINT}" run --automation --ok-on-blocked {export_flag}{tos_flag}"$@"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    SERVICE_WRAPPER.chmod(0o755)


def install(export_first: bool, require_tos_running: bool) -> int:
    """Install and load the desktop automation LaunchAgent."""
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    ensure_wrapper(export_first, require_tos_running)
    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(plist_payload(export_first, require_tos_running), handle, sort_keys=False)
    domain = user_domain()
    run_launchctl("bootout", domain, str(PLIST_PATH), check=False)
    run_launchctl("bootstrap", domain, str(PLIST_PATH))
    run_launchctl("enable", f"{domain}/{WATCH_LABEL}")
    print(f"Installed {WATCH_LABEL}")
    print(f"LaunchAgent: {PLIST_PATH}")
    print(f"Interval: every {DESKTOP_AUTOMATION_INTERVAL_SECONDS // 60} minutes")
    print(f"Export bridge requested: {export_first}")
    print(f"Require thinkorswim running: {require_tos_running}")
    print(f"Local config: {LOCAL_ENV_FILE}")
    return 0


def uninstall() -> int:
    """Unload and remove the desktop automation LaunchAgent."""
    domain = user_domain()
    run_launchctl("bootout", domain, str(PLIST_PATH), check=False)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    print(f"Removed {WATCH_LABEL}")
    return 0


def status() -> int:
    """Show LaunchAgent status."""
    print(f"Label: {WATCH_LABEL}")
    print(f"Plist: {PLIST_PATH}")
    print(f"Installed: {'yes' if PLIST_PATH.exists() else 'no'}")
    if not PLIST_PATH.exists():
        return 1
    result = run_launchctl("print", f"{user_domain()}/{WATCH_LABEL}", check=False)
    loaded = result.returncode == 0
    print(f"Loaded: {'yes' if loaded else 'no'}")
    if not loaded:
        stderr = result.stderr.strip() or result.stdout.strip()
        if stderr:
            print(stderr)
    return 0 if loaded else 1


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the service installer."""
    parser = argparse.ArgumentParser(description="Install or inspect the inferno desktop automation service.")
    parser.add_argument("command", nargs="?", default="status", choices=["install", "uninstall", "status"])
    parser.add_argument(
        "--export-first",
        action="store_true",
        help=(
            "Request the export bridge before each local cycle. Background export still "
            "fails closed unless TOS_BACKGROUND_EXPORT_ALLOWED=1 is set."
        ),
    )
    parser.add_argument(
        "--require-tos-running",
        action="store_true",
        help="Only run the local cycle when thinkorswim is already open",
    )
    return parser.parse_args()


def main() -> int:
    """Run the installer/status CLI."""
    args = parse_args()
    if args.command == "install":
        return install(args.export_first, args.require_tos_running)
    if args.command == "uninstall":
        return uninstall()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
