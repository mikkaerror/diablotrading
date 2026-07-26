from __future__ import annotations

"""Install the research-only nightly optimization loop as a LaunchAgent."""

import argparse
import hashlib
import os
import plistlib
import subprocess
from pathlib import Path

from inferno_config import ROOT, backtest_python
from inferno_io import atomic_copy_file


SERVICE_LABEL = "io.diablotrading.inferno-nightly-optimize"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
LOG_DIR = Path.home() / "Library" / "Logs" / "Inferno"
SERVICE_BIN_DIR = Path.home() / ".local" / "bin"
SERVICE_WRAPPER = SERVICE_BIN_DIR / "inferno_nightly_optimize_service.sh"
SERVICE_ENTRYPOINT = SERVICE_BIN_DIR / "inferno_nightly_optimize.sh"
ENTRYPOINT = ROOT / "nightly_optimize.sh"
DEFAULT_HOUR = 18
DEFAULT_MINUTE = 30


def run_launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run launchctl for the current user domain."""
    return subprocess.run(
        ["launchctl", *args],
        text=True,
        capture_output=True,
        check=check,
    )


def user_domain() -> str:
    """Return the launchd domain for the current desktop user."""
    return f"gui/{os.getuid()}"


def plist_payload(hour: int, minute: int) -> dict:
    """Build a weekday evening schedule for the research refresh."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    intervals = [
        {"Hour": hour, "Minute": minute, "Weekday": weekday}
        for weekday in range(1, 6)
    ]
    return {
        "Label": SERVICE_LABEL,
        "ProgramArguments": [str(SERVICE_WRAPPER)],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": False,
        "StartCalendarInterval": intervals,
        "StandardOutPath": str(LOG_DIR / "inferno_nightly_optimize.stdout.log"),
        "StandardErrorPath": str(LOG_DIR / "inferno_nightly_optimize.stderr.log"),
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(Path.home()),
        },
    }


def script_sync_status() -> dict[str, str | None]:
    """Compare the reviewed source script with launchd's protected copy.

    macOS may deny a LaunchAgent access to the user's Documents folder, so the
    job intentionally executes a deployed copy in ``~/.local/bin``.  The
    checksum makes that boundary observable: a source edit is not silently
    mistaken for scheduled deployment until ``install`` refreshes the copy.
    """
    if not ENTRYPOINT.exists():
        return {"status": "source-missing", "sourceSha256": None, "deployedSha256": None}
    if not SERVICE_ENTRYPOINT.exists():
        return {"status": "deployed-copy-missing", "sourceSha256": None, "deployedSha256": None}
    try:
        source_hash = hashlib.sha256(ENTRYPOINT.read_bytes()).hexdigest()
        deployed_hash = hashlib.sha256(SERVICE_ENTRYPOINT.read_bytes()).hexdigest()
    except OSError as exc:
        return {
            "status": "sync-unreadable",
            "sourceSha256": None,
            "deployedSha256": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "status": "synced" if source_hash == deployed_hash else "drift",
        "sourceSha256": source_hash,
        "deployedSha256": deployed_hash,
    }


def ensure_wrapper() -> None:
    """Deploy the job outside Documents and write its launchd wrapper."""
    runner_python = backtest_python()
    SERVICE_BIN_DIR.mkdir(parents=True, exist_ok=True)
    atomic_copy_file(ENTRYPOINT, SERVICE_ENTRYPOINT)
    SERVICE_WRAPPER.write_text(
        "\n".join(
            [
                "#!/bin/zsh",
                "set -euo pipefail",
                f'cd "{ROOT}"',
                f'export BACKTEST_PYTHON="{runner_python}"',
                f'export INFERNO_PYTHON="{runner_python}"',
                f'export INFERNO_ROOT="{ROOT}"',
                f'export INFERNO_NIGHTLY_LOG="{LOG_DIR / "nightly_optimize_run.log"}"',
                f'exec /bin/bash "{SERVICE_ENTRYPOINT}" "$@"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    SERVICE_WRAPPER.chmod(0o755)


def install(hour: int, minute: int) -> int:
    """Install and load the nightly optimization LaunchAgent."""
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
    print(f"Installed nightly optimization LaunchAgent at {PLIST_PATH}")
    print(f"Schedule: weekdays at {hour:02d}:{minute:02d} local")
    return 0


def uninstall() -> int:
    """Unload and remove the nightly optimization LaunchAgent."""
    run_launchctl("bootout", f"{user_domain()}/{SERVICE_LABEL}", check=False)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    print("Nightly optimization LaunchAgent uninstalled.")
    return 0


def status() -> int:
    """Print launchd status and the expected plist path."""
    sync = script_sync_status()
    print(f"Script sync: {sync['status']}")
    if sync.get("error"):
        print(sync["error"])
    if sync["status"] != "synced":
        print("Run `python3 install_inferno_nightly_optimize_service.py install` to refresh the deployed copy.")
    result = run_launchctl("print", f"{user_domain()}/{SERVICE_LABEL}", check=False)
    if result.returncode == 0:
        print(result.stdout)
    else:
        print(f"Agent {SERVICE_LABEL} is not loaded.")
        print(f"Expected plist: {PLIST_PATH}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the research-only nightly optimization LaunchAgent."
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
