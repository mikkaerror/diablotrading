from __future__ import annotations

"""Install a launchd service for the watchlist autorefresh coordinator.

Fires ``inferno_watchlist_autorefresh.py`` every 5 minutes. Surveillance
mode by default — the operator must opt into ``--auto-apply`` either via
the CLI flag or by setting ``INFERNO_WATCHLIST_AUTO_APPLY=1`` in the
LaunchAgent environment (this installer accepts a ``--auto-apply`` flag
that flips that env var on for the installed service).

Mirrors the shape of ``install_inferno_ops_maintenance_service.py`` so the
operator can manage it identically.
"""

import argparse
import os
import plistlib
import subprocess
from pathlib import Path

from inferno_config import LOCAL_ENV_FILE, ROOT, backtest_python


WATCH_LABEL = "io.diablotrading.inferno-watchlist-autorefresh"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{WATCH_LABEL}.plist"
LOG_DIR = Path.home() / "Library" / "Logs" / "Inferno"
SERVICE_BIN_DIR = Path.home() / ".local" / "bin"
SERVICE_WRAPPER = SERVICE_BIN_DIR / "inferno_watchlist_autorefresh_service.sh"
ENTRYPOINT = ROOT / "inferno_watchlist_autorefresh.py"
DEFAULT_INTERVAL_SECONDS = 300  # 5 minutes — the user-requested cadence


def run_launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *args], text=True, capture_output=True, check=check)


def user_domain() -> str:
    return f"gui/{os.getuid()}"


def plist_payload(interval_seconds: int, auto_apply: bool) -> dict:
    LOG_DIR.mkdir(exist_ok=True)
    stdout_path = str(LOG_DIR / "inferno_watchlist_autorefresh.stdout.log")
    stderr_path = str(LOG_DIR / "inferno_watchlist_autorefresh.stderr.log")
    env_vars: dict[str, str] = {
        "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(Path.home()),
    }
    if auto_apply:
        env_vars["INFERNO_WATCHLIST_AUTO_APPLY"] = "1"
        env_vars["INFERNO_WATCHLIST_CONFIRM"] = "1"
    return {
        "Label": WATCH_LABEL,
        "ProgramArguments": [str(SERVICE_WRAPPER)],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "StartInterval": interval_seconds,
        "StandardOutPath": stdout_path,
        "StandardErrorPath": stderr_path,
        "EnvironmentVariables": env_vars,
    }


def ensure_wrapper(auto_apply: bool) -> None:
    runner_python = backtest_python()
    SERVICE_BIN_DIR.mkdir(parents=True, exist_ok=True)
    args_line = "--auto-apply" if auto_apply else ""
    SERVICE_WRAPPER.write_text(
        "\n".join(
            [
                "#!/bin/zsh",
                "set -euo pipefail",
                f'cd "{ROOT}"',
                f'export BACKTEST_PYTHON="{runner_python}"',
                f'exec "{runner_python}" "{ENTRYPOINT}" run {args_line} "$@"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    SERVICE_WRAPPER.chmod(0o755)


def install(interval_seconds: int, auto_apply: bool) -> int:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    ensure_wrapper(auto_apply)
    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(plist_payload(interval_seconds, auto_apply), handle, sort_keys=False)
    domain = user_domain()
    run_launchctl("bootout", domain, str(PLIST_PATH), check=False)
    run_launchctl("bootstrap", domain, str(PLIST_PATH))
    run_launchctl("enable", f"{domain}/{WATCH_LABEL}")
    print(f"Installed {WATCH_LABEL}")
    print(f"LaunchAgent: {PLIST_PATH}")
    print(f"Interval: every {interval_seconds // 60} minute(s)")
    print(f"Auto-apply: {'ON — coordinator will push deltas to the sheet' if auto_apply else 'OFF (surveillance only)'}")
    print(f"Local config: {LOCAL_ENV_FILE}")
    return 0


def uninstall() -> int:
    domain = user_domain()
    run_launchctl("bootout", domain, str(PLIST_PATH), check=False)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    print(f"Removed {WATCH_LABEL}")
    return 0


def status() -> int:
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
    parser = argparse.ArgumentParser(
        description=(
            "Install or inspect the inferno watchlist autorefresh service. "
            "Surveillance-only by default; pass --auto-apply to enable the "
            "implicit ingest confirmation gate."
        )
    )
    parser.add_argument("command", nargs="?", default="status",
                        choices=["install", "uninstall", "status"])
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--auto-apply", action="store_true",
                        help="Run the installed service with --auto-apply.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "install":
        return install(args.interval_seconds, args.auto_apply)
    if args.command == "uninstall":
        return uninstall()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
