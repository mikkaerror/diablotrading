from __future__ import annotations

"""Install a launchd service for the ops maintenance sweep.

This service is intentionally lightweight. It does not rebuild the full dawn
stack; it just keeps the surrounding ops artifacts honest during the day:
email recovery, ticker hydration, downloads watch freshness, and watchdog
refresh.
"""

import argparse
import os
import plistlib
import subprocess
from pathlib import Path

from inferno_config import LOCAL_ENV_FILE, ROOT, backtest_python


WATCH_LABEL = "io.diablotrading.inferno-ops-maintenance"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{WATCH_LABEL}.plist"
LOG_DIR = ROOT / "logs"
SERVICE_BIN_DIR = Path.home() / ".local" / "bin"
SERVICE_WRAPPER = SERVICE_BIN_DIR / "inferno_ops_maintenance_service.sh"
ENTRYPOINT = ROOT / "inferno_ops_maintenance.py"
DEFAULT_INTERVAL_SECONDS = 1800


def run_launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run launchctl for the current user domain."""
    return subprocess.run(["launchctl", *args], text=True, capture_output=True, check=check)


def user_domain() -> str:
    """Return the launchd user domain."""
    return f"gui/{os.getuid()}"


def plist_payload(interval_seconds: int) -> dict:
    """Build the LaunchAgent payload for ops maintenance."""
    LOG_DIR.mkdir(exist_ok=True)
    stdout_path = str(LOG_DIR / "inferno_ops_maintenance.stdout.log")
    stderr_path = str(LOG_DIR / "inferno_ops_maintenance.stderr.log")
    return {
        "Label": WATCH_LABEL,
        "ProgramArguments": ["/bin/zsh", str(SERVICE_WRAPPER)],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "StartInterval": interval_seconds,
        "StandardOutPath": stdout_path,
        "StandardErrorPath": stderr_path,
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(Path.home()),
        },
    }


def ensure_wrapper() -> None:
    """Write the wrapper script used by launchd."""
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


def install(interval_seconds: int) -> int:
    """Install and load the ops maintenance LaunchAgent."""
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    ensure_wrapper()
    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(plist_payload(interval_seconds), handle, sort_keys=False)
    domain = user_domain()
    run_launchctl("bootout", domain, str(PLIST_PATH), check=False)
    run_launchctl("bootstrap", domain, str(PLIST_PATH))
    run_launchctl("enable", f"{domain}/{WATCH_LABEL}")
    print(f"Installed {WATCH_LABEL}")
    print(f"LaunchAgent: {PLIST_PATH}")
    print(f"Interval: every {interval_seconds // 60} minutes")
    print(f"Local config: {LOCAL_ENV_FILE}")
    return 0


def uninstall() -> int:
    """Unload and remove the ops maintenance LaunchAgent."""
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
    parser = argparse.ArgumentParser(description="Install or inspect the inferno ops maintenance service.")
    parser.add_argument("command", nargs="?", default="status", choices=["install", "uninstall", "status"])
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    return parser.parse_args()


def main() -> int:
    """Run the installer/status CLI."""
    args = parse_args()
    if args.command == "install":
        return install(args.interval_seconds)
    if args.command == "uninstall":
        return uninstall()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
