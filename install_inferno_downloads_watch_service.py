from __future__ import annotations

"""Install a launchd service for the Downloads watch loop.

This service is intentionally separate from the dawn-cycle runner. It polls
for new broker exports during the trading day. Fresh TOS exports remain
manual/supervised by default so launchd cannot keep foregrounding the broker
app.
"""

import argparse
import os
import plistlib
import subprocess
from pathlib import Path

from inferno_config import (
    DOWNLOADS_WATCH_LABEL,
    DOWNLOADS_WATCH_INTERVAL_SECONDS,
    LOCAL_ENV_FILE,
    ROOT,
    TOS_EXPORT_AUTOMATION_ENABLED,
    backtest_python,
)


WATCH_LABEL = DOWNLOADS_WATCH_LABEL
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{WATCH_LABEL}.plist"
LOG_DIR = ROOT / "logs"
SERVICE_BIN_DIR = Path.home() / ".local" / "bin"
SERVICE_WRAPPER = SERVICE_BIN_DIR / "inferno_downloads_watch_service.sh"
ENTRYPOINT = ROOT / "inferno_downloads_watch.py"


def run_launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run launchctl for the current user domain."""
    return subprocess.run(["launchctl", *args], text=True, capture_output=True, check=check)


def user_domain() -> str:
    """Return the launchd user domain."""
    return f"gui/{os.getuid()}"


def plist_payload(export_first: bool) -> dict:
    """Build the LaunchAgent payload."""
    LOG_DIR.mkdir(exist_ok=True)
    stdout_path = str(LOG_DIR / "inferno_downloads_watch.stdout.log")
    stderr_path = str(LOG_DIR / "inferno_downloads_watch.stderr.log")
    arguments = ["/bin/zsh", str(SERVICE_WRAPPER)]
    if export_first:
        arguments.append("--export-first")
    return {
        "Label": WATCH_LABEL,
        "ProgramArguments": arguments,
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "StartInterval": DOWNLOADS_WATCH_INTERVAL_SECONDS,
        "StandardOutPath": stdout_path,
        "StandardErrorPath": stderr_path,
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(Path.home()),
        },
    }


def ensure_wrapper(export_first: bool) -> None:
    """Write the wrapper script used by launchd."""
    runner_python = backtest_python()
    SERVICE_BIN_DIR.mkdir(parents=True, exist_ok=True)
    extra = "--export-first " if export_first else ""
    SERVICE_WRAPPER.write_text(
        "\n".join(
            [
                "#!/bin/zsh",
                "set -euo pipefail",
                f'cd "{ROOT}"',
                f'export BACKTEST_PYTHON="{runner_python}"',
                f'exec "{runner_python}" "{ENTRYPOINT}" run --automation {extra}"$@"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    SERVICE_WRAPPER.chmod(0o755)


def install(export_first: bool) -> int:
    """Install and load the Downloads watch LaunchAgent."""
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    ensure_wrapper(export_first)
    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(plist_payload(export_first), handle, sort_keys=False)
    domain = user_domain()
    run_launchctl("bootout", domain, str(PLIST_PATH), check=False)
    run_launchctl("bootstrap", domain, str(PLIST_PATH))
    run_launchctl("enable", f"{domain}/{WATCH_LABEL}")
    print(f"Installed {WATCH_LABEL}")
    print(f"LaunchAgent: {PLIST_PATH}")
    print(f"Interval: every {DOWNLOADS_WATCH_INTERVAL_SECONDS // 60} minutes")
    print(f"Export bridge requested: {export_first}")
    print(f"TOS export automation enabled in config: {TOS_EXPORT_AUTOMATION_ENABLED}")
    print(f"Local config: {LOCAL_ENV_FILE}")
    return 0


def uninstall() -> int:
    """Unload and remove the Downloads watch LaunchAgent."""
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
    parser = argparse.ArgumentParser(description="Install or inspect the inferno Downloads watch service.")
    parser.add_argument("command", nargs="?", default="status", choices=["install", "uninstall", "status"])
    parser.add_argument(
        "--export-first",
        action="store_true",
        help=(
            "Request the export bridge before each scan. Background export still "
            "fails closed unless TOS_BACKGROUND_EXPORT_ALLOWED=1 is set."
        ),
    )
    return parser.parse_args()


def main() -> int:
    """Run the installer/status CLI."""
    args = parse_args()
    if args.command == "install":
        return install(args.export_first)
    if args.command == "uninstall":
        return uninstall()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
