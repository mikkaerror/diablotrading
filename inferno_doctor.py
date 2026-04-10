from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from server import OPS_STATUS_FILE, ROOT, WATCHDOG_STATUS_FILE, load_json_file, smtp_configured


LABEL = "io.diablotrading.inferno-dawn-brief"
WATCHDOG_LABEL = "io.diablotrading.inferno-watchdog"
SMTP_ENV_FILE = ROOT / ".env.smtp"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key] = value


def local_today() -> str:
    return datetime.now().astimezone().date().isoformat()


def run_command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def launch_agent_loaded(label: str) -> bool:
    domain = f"gui/{os.getuid()}/{label}"
    return run_command("launchctl", "print", domain).returncode == 0


def pmset_sched_text() -> str:
    return run_command("pmset", "-g", "sched").stdout


def pmset_custom_text() -> str:
    return run_command("pmset", "-g", "custom").stdout


def summarize_status(name: str, ok: bool, detail: str) -> str:
    marker = "PASS" if ok else "WARN"
    return f"[{marker}] {name}: {detail}"


def main() -> int:
    load_env_file(SMTP_ENV_FILE)

    today = local_today()
    lines: list[str] = ["Inferno Doctor", f"Checked at: {datetime.now().astimezone().isoformat()}", ""]
    warnings = 0

    smtp_ok = smtp_configured()
    lines.append(summarize_status("SMTP", smtp_ok, "configured" if smtp_ok else "not configured"))
    if not smtp_ok:
        warnings += 1

    dawn_loaded = launch_agent_loaded(LABEL)
    lines.append(summarize_status("Dawn agent", dawn_loaded, "loaded" if dawn_loaded else "not loaded"))
    if not dawn_loaded:
        warnings += 1

    watchdog_loaded = launch_agent_loaded(WATCHDOG_LABEL)
    lines.append(summarize_status("Watchdog agent", watchdog_loaded, "loaded" if watchdog_loaded else "not loaded"))
    if not watchdog_loaded:
        warnings += 1

    sched_text = pmset_sched_text()
    wake_ok = "wakepoweron at 5:58AM" in sched_text
    lines.append(summarize_status("Wake schedule", wake_ok, "5:58 AM wake is scheduled" if wake_ok else "5:58 AM wake not found"))
    if not wake_ok:
        warnings += 1

    custom_text = pmset_custom_text()
    ac_sleep_ok = "AC Power:" in custom_text and "sleep                15" in custom_text
    lines.append(summarize_status("AC sleep", ac_sleep_ok, "AC sleep is 15 minutes" if ac_sleep_ok else "AC sleep is not 15 minutes"))
    if not ac_sleep_ok:
        warnings += 1

    ops_status = load_json_file(OPS_STATUS_FILE) or {}
    ops_today = str(ops_status.get("generatedAt", "")).startswith(today)
    ops_email = bool(ops_status.get("emailSent"))
    ops_ok = ops_today and ops_email and bool(ops_status.get("ok"))
    ops_detail = "fresh run and email recorded today" if ops_ok else json.dumps(
        {
            "generatedAt": ops_status.get("generatedAt"),
            "ok": ops_status.get("ok"),
            "emailSent": ops_status.get("emailSent"),
        }
    )
    lines.append(summarize_status("Morning run", ops_ok, ops_detail))
    if not ops_ok:
        warnings += 1

    watchdog_status = load_json_file(WATCHDOG_STATUS_FILE) or {}
    watchdog_today = str(watchdog_status.get("checkedAt", "")).startswith(today)
    watchdog_ok = watchdog_today and bool(watchdog_status.get("ok"))
    watchdog_detail = "watchdog checked in cleanly today" if watchdog_ok else json.dumps(
        {
            "checkedAt": watchdog_status.get("checkedAt"),
            "ok": watchdog_status.get("ok"),
            "reasons": watchdog_status.get("reasons"),
        }
    )
    lines.append(summarize_status("Watchdog status", watchdog_ok, watchdog_detail))
    if not watchdog_ok:
        warnings += 1

    lines.append("")
    if warnings == 0:
        lines.append("Desk status: healthy")
    else:
        lines.append(f"Desk status: {warnings} item(s) need attention")

    print("\n".join(lines))
    return 0 if warnings == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
