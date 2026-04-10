from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from inferno_config import (
    LABEL,
    ROOT,
    UPDATER_LABEL,
    UPDATER_SCRIPTS,
    WATCHDOG_LABEL,
    backtest_python,
    default_backtest_root,
    local_today,
    WAKE_HOUR,
    WAKE_MINUTE,
)
from server import EXECUTION_QUEUE_FILE, LOG_FILE, OPS_STATUS_FILE, WATCHDOG_STATUS_FILE, load_json_file, smtp_configured


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


def latest_emailed_run_for_day(day: str) -> dict | None:
    if not LOG_FILE.exists():
        return None

    latest: dict | None = None
    for raw_line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        generated_at = str(payload.get("generatedAt", ""))
        if not generated_at.startswith(day):
            continue
        if not payload.get("ok", True) or not payload.get("emailSent"):
            continue
        latest = payload
    return latest


def main() -> int:
    load_env_file(SMTP_ENV_FILE)

    today = local_today()
    lines: list[str] = ["Inferno Doctor", f"Checked at: {datetime.now().astimezone().isoformat()}", ""]
    warnings = 0

    smtp_ok = smtp_configured()
    lines.append(summarize_status("SMTP", smtp_ok, "configured" if smtp_ok else "not configured"))
    if not smtp_ok:
        warnings += 1

    bt_root = default_backtest_root()
    bt_root_ok = bt_root.exists()
    lines.append(summarize_status("Backtest root", bt_root_ok, str(bt_root) if bt_root_ok else f"missing: {bt_root}"))
    if not bt_root_ok:
        warnings += 1

    bt_python = backtest_python()
    bt_python_ok = bt_python.exists()
    lines.append(summarize_status("Backtest Python", bt_python_ok, str(bt_python) if bt_python_ok else f"missing: {bt_python}"))
    if not bt_python_ok:
        warnings += 1

    missing_scripts = [script for script in UPDATER_SCRIPTS if not (bt_root / script).exists()]
    scripts_ok = not missing_scripts
    script_detail = UPDATER_LABEL if scripts_ok else f"missing: {', '.join(missing_scripts)}"
    lines.append(summarize_status("Updater scripts", scripts_ok, script_detail))
    if not scripts_ok:
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
    wake_label = f"{WAKE_HOUR:02d}:{WAKE_MINUTE:02d}"
    wake_phrase = f"wakepoweron at {WAKE_HOUR if WAKE_HOUR % 12 else 12}:{WAKE_MINUTE:02d}AM"
    wake_ok = wake_phrase in sched_text
    lines.append(summarize_status("Wake schedule", wake_ok, f"{wake_label} wake is scheduled" if wake_ok else f"{wake_label} wake not found"))
    if not wake_ok:
        warnings += 1

    custom_text = pmset_custom_text()
    ac_sleep_ok = "AC Power:" in custom_text and "sleep                15" in custom_text
    lines.append(summarize_status("AC sleep", ac_sleep_ok, "AC sleep is 15 minutes" if ac_sleep_ok else "AC sleep is not 15 minutes"))
    if not ac_sleep_ok:
        warnings += 1

    ops_status = load_json_file(OPS_STATUS_FILE) or {}
    emailed_status = latest_emailed_run_for_day(today)
    ops_reference = emailed_status or ops_status
    ops_today = str(ops_reference.get("generatedAt", "")).startswith(today)
    ops_email = bool(ops_reference.get("emailSent"))
    ops_ok = ops_today and ops_email and bool(ops_reference.get("ok", True))
    ops_detail = "fresh run and email recorded today" if ops_ok else json.dumps(
        {
            "generatedAt": ops_reference.get("generatedAt"),
            "ok": ops_reference.get("ok", True),
            "emailSent": ops_reference.get("emailSent"),
        }
    )
    lines.append(summarize_status("Morning run", ops_ok, ops_detail))
    if not ops_ok:
        warnings += 1
    else:
        lines.append(f"Top tickers: {', '.join(ops_reference.get('topTickers', [])[:5]) or 'none'}")

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

    execution_queue = load_json_file(EXECUTION_QUEUE_FILE) or {}
    execution_today = str(execution_queue.get("generatedAt", "")).startswith(today)
    execution_ok = execution_today and execution_queue.get("count") is not None
    execution_detail = (
        f"{execution_queue.get('activeReadyCount', 0)} ready / {execution_queue.get('count', 0)} staged"
        if execution_ok
        else json.dumps(
            {
                "generatedAt": execution_queue.get("generatedAt"),
                "count": execution_queue.get("count"),
            }
        )
    )
    lines.append(summarize_status("Execution desk", execution_ok, execution_detail))
    if not execution_ok:
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
