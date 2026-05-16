from __future__ import annotations

"""Configure persistent local automation settings for Inferno export intake."""

import argparse
from pathlib import Path

from inferno_config import LOCAL_ENV_FILE, TOS_APP_PATH


DEFAULT_VALUES = {
    "DOWNLOADS_SCAN_DIR": str(Path.home() / "Downloads"),
    "DOWNLOADS_LOOKBACK_HOURS": "168",
    "DOWNLOADS_WATCH_INTERVAL_SECONDS": "600",
    "DOWNLOADS_WATCH_WINDOW_START": "06:00",
    "DOWNLOADS_WATCH_WINDOW_END": "16:30",
    "TOS_APP_PATH": str(TOS_APP_PATH),
    "TOS_EXPORT_AUTOMATION_ENABLED": "0",
    "TOS_EXPORT_SHORTCUT": "command+shift+e",
    "TOS_EXPORT_PRE_DELAY_SECONDS": "3",
    "TOS_EXPORT_POST_DELAY_SECONDS": "8",
}

ORDER = list(DEFAULT_VALUES.keys())


def load_existing(path: Path) -> dict[str, str]:
    """Load the current local automation config or the defaults."""
    data = DEFAULT_VALUES.copy()
    if not path.exists():
        return data
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def write_env(path: Path, values: dict[str, str]) -> None:
    """Persist the local Inferno automation config file."""
    lines = [
        "# Inferno local automation config",
        "# Non-secret settings only. Secrets stay in .env.smtp or Secret Manager.",
        "",
    ]
    for key in ORDER:
        lines.append(f"{key}={values[key]}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for local export/watch automation setup."""
    parser = argparse.ArgumentParser(description="Configure Inferno export/watch automation settings.")
    parser.add_argument("--enable-export", action="store_true", help="Enable experimental thinkorswim export automation")
    parser.add_argument("--disable-export", action="store_true", help="Disable experimental thinkorswim export automation")
    parser.add_argument("--shortcut", default="", help="Export shortcut, for example command+shift+e")
    parser.add_argument("--interval-seconds", type=int, default=0, help="Downloads watch polling interval")
    parser.add_argument("--pre-delay", type=float, default=-1, help="Delay before the export shortcut fires")
    parser.add_argument("--post-delay", type=float, default=-1, help="Cooldown after the export shortcut fires")
    return parser.parse_args()


def main() -> int:
    """Update the local automation config file in place."""
    args = parse_args()
    values = load_existing(LOCAL_ENV_FILE)

    if args.enable_export and args.disable_export:
        raise SystemExit("choose either --enable-export or --disable-export, not both")
    if args.enable_export:
        values["TOS_EXPORT_AUTOMATION_ENABLED"] = "1"
    if args.disable_export:
        values["TOS_EXPORT_AUTOMATION_ENABLED"] = "0"
    if args.shortcut:
        values["TOS_EXPORT_SHORTCUT"] = args.shortcut.strip()
    if args.interval_seconds > 0:
        values["DOWNLOADS_WATCH_INTERVAL_SECONDS"] = str(args.interval_seconds)
    if args.pre_delay >= 0:
        values["TOS_EXPORT_PRE_DELAY_SECONDS"] = str(args.pre_delay)
    if args.post_delay >= 0:
        values["TOS_EXPORT_POST_DELAY_SECONDS"] = str(args.post_delay)

    write_env(LOCAL_ENV_FILE, values)
    print(f"Saved local automation config to {LOCAL_ENV_FILE}")
    print(f"Export enabled: {values['TOS_EXPORT_AUTOMATION_ENABLED']}")
    print(f"Shortcut: {values['TOS_EXPORT_SHORTCUT']}")
    print(f"Watch interval seconds: {values['DOWNLOADS_WATCH_INTERVAL_SECONDS']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
