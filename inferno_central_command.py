from __future__ import annotations

"""Central supervisor command for the Inferno desk.

This is the single top-level operator and model entrypoint for the desk's
shared brain. It centralizes three things:

1. refresh the maintenance sweep
2. refresh the shared multi-model command center
3. summarize doctor health into one compact supervisor artifact

It stays read-only with respect to broker authority and never places trades.
"""

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from inferno_config import ROOT, default_backtest_root, local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_model_command_center import (
    ACTIVE_MISSIONS_FILE,
    MODEL_COMMAND_CENTER_FILE,
    MODEL_NOTES_FILE,
    add_mission,
    append_note,
    build_command_center,
    onboard_digest,
    parse_tags,
    update_mission,
)
from inferno_ops_maintenance import run_maintenance
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


CENTRAL_COMMAND_FILE = DATA_DIR / "inferno_central_command.json"
CENTRAL_COMMAND_TEXT_FILE = REPORTS_DIR / "central_command_latest.txt"


def run_command(args: list[str], *, timeout_seconds: int = 300) -> dict[str, Any]:
    """Run a subprocess and capture a structured result."""
    result = subprocess.run(
        args,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
        cwd=str(ROOT),
    )
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": str(result.stdout or "").strip(),
        "stderr": str(result.stderr or "").strip(),
        "command": " ".join(args),
    }


def doctor_summary() -> dict[str, Any]:
    """Collect the current doctor verdict without duplicating doctor logic."""
    result = run_command(["python3", "inferno_doctor.py"])
    output = result["stdout"] or result["stderr"]
    final_line = next(
        (line.strip() for line in reversed(output.splitlines()) if line.strip().startswith("Desk status:")),
        "Desk status: unknown",
    )
    verdict = final_line.split("Desk status:", 1)[-1].strip() if "Desk status:" in final_line else "unknown"
    return {
        "ok": result["ok"],
        "verdict": verdict,
        "detail": final_line,
        "command": result["command"],
        "returncode": result["returncode"],
    }


def render_central_command_text(payload: dict[str, Any]) -> str:
    """Render the central supervisor payload into a compact briefing."""
    maintenance = payload.get("opsMaintenance") or {}
    command_center = payload.get("modelCommandCenter") or {}
    doctor = payload.get("doctor") or {}
    metrics = (command_center.get("headlineMetrics") or {})
    lines = [
        "Inferno Central Command",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Supervisor verdict: {payload.get('verdict')}",
        "",
        "Core lanes:",
        f"- Ops maintenance: {maintenance.get('status')}",
        f"- Model command center: {command_center.get('status')} | missions {command_center.get('missionCount', 0)} | notes {command_center.get('noteCount', 0)}",
        f"- Doctor: {doctor.get('verdict')}",
        "",
        "Headline metrics:",
        f"- Live supported: {metrics.get('liveSupported', 0)}",
        f"- Live fragile: {metrics.get('liveFragile', 0)}",
        f"- Paper approval-only: {metrics.get('paperApprovalOnly', 0)}",
        f"- Promotion gap: {metrics.get('paperRemainingForPromotion', 0)}",
        "",
        "Quick files:",
        f"- {MODEL_COMMAND_CENTER_FILE}",
        f"- {ACTIVE_MISSIONS_FILE}",
        f"- {MODEL_NOTES_FILE}",
        "",
        "Recommended next move:",
        f"- {payload.get('recommendedNextMove')}",
    ]
    return "\n".join(lines).rstrip() + "\n"


def save_central_command(payload: dict[str, Any]) -> None:
    """Persist the central supervisor artifact."""
    ensure_dirs()
    atomic_write_json(CENTRAL_COMMAND_FILE, payload)
    atomic_write_text(CENTRAL_COMMAND_TEXT_FILE, render_central_command_text(payload))


def build_central_command(
    *,
    backtest_root: Path,
    sheet_name: str,
    cloud_region: str,
    force_email: bool = False,
) -> dict[str, Any]:
    """Run the central supervisor refresh and persist the result."""
    maintenance = run_maintenance(
        backtest_root=backtest_root,
        sheet_name=sheet_name,
        force_email=force_email,
        cloud_region=cloud_region,
    )
    command_center = build_command_center()
    doctor = doctor_summary()

    headline_metrics = command_center.get("headlineMetrics") or {}
    next_actions = command_center.get("nextActions") or []
    payload = {
        "generatedAt": local_now().isoformat(),
        "verdict": "healthy" if maintenance.get("ok") and doctor.get("ok") else "attention",
        "opsMaintenance": {
            "ok": bool(maintenance.get("ok")),
            "status": "healthy" if maintenance.get("ok") else "attention",
            "generatedAt": maintenance.get("generatedAt"),
        },
        "modelCommandCenter": {
            "ok": True,
            "status": "ready",
            "generatedAt": command_center.get("generatedAt"),
            "missionCount": len(command_center.get("activeMissions") or []),
            "noteCount": len(command_center.get("recentNotes") or []),
            "headlineMetrics": headline_metrics,
        },
        "doctor": doctor,
        "recommendedNextMove": next_actions[0] if next_actions else "Review reports/model_command_center_latest.txt",
        "shortcutCommands": [
            'cd "<repo-root>"',
            "./run_inferno_central_command.sh",
            "./run_inferno_model_command_center.sh onboard",
            "python3 inferno_doctor.py",
        ],
    }
    save_central_command(payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser for the central supervisor command."""
    parser = argparse.ArgumentParser(description="Central supervisor command for the Inferno desk.")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("run")
    subparsers.add_parser("status")
    subparsers.add_parser("onboard")

    note_parser = subparsers.add_parser("note")
    note_parser.add_argument("--author", required=True)
    note_parser.add_argument("--title", required=True)
    note_parser.add_argument("--body", required=True)
    note_parser.add_argument("--priority", default="normal")
    note_parser.add_argument("--tags", default="")

    mission_add = subparsers.add_parser("mission-add")
    mission_add.add_argument("--title", required=True)
    mission_add.add_argument("--body", required=True)
    mission_add.add_argument("--owner", default="shared")
    mission_add.add_argument("--status", default="pending")
    mission_add.add_argument("--priority", default="normal")
    mission_add.add_argument("--tags", default="")

    mission_update = subparsers.add_parser("mission-update")
    mission_update.add_argument("--id", required=True)
    mission_update.add_argument("--title")
    mission_update.add_argument("--body")
    mission_update.add_argument("--owner")
    mission_update.add_argument("--status")
    mission_update.add_argument("--priority")
    mission_update.add_argument("--tags")

    parser.add_argument("--backtest-root", default=str(default_backtest_root()))
    parser.add_argument("--sheet-name", default="Earnings Tracker")
    parser.add_argument("--cloud-region", default="us-central1")
    parser.add_argument("--force-email", action="store_true")
    return parser


def main() -> int:
    """Run the central command CLI."""
    parser = build_parser()
    args = parser.parse_args()
    command = args.command or "run"

    if command == "run":
        payload = build_central_command(
            backtest_root=Path(args.backtest_root).expanduser().resolve(),
            sheet_name=args.sheet_name,
            cloud_region=args.cloud_region,
            force_email=args.force_email,
        )
        print(render_central_command_text(payload))
        return 0 if payload.get("verdict") == "healthy" else 1

    if command == "status":
        if CENTRAL_COMMAND_TEXT_FILE.exists():
            print(CENTRAL_COMMAND_TEXT_FILE.read_text(encoding="utf-8"))
            latest = load_json_file(CENTRAL_COMMAND_FILE) or {}
            return 0 if latest.get("verdict") == "healthy" else 1
        payload = build_central_command(
            backtest_root=Path(args.backtest_root).expanduser().resolve(),
            sheet_name=args.sheet_name,
            cloud_region=args.cloud_region,
            force_email=args.force_email,
        )
        print(render_central_command_text(payload))
        return 0 if payload.get("verdict") == "healthy" else 1

    if command == "onboard":
        payload = build_command_center()
        print(onboard_digest(payload))
        return 0

    if command == "note":
        note = append_note(
            author=args.author,
            title=args.title,
            body=args.body,
            priority=args.priority,
            tags=parse_tags(args.tags),
        )
        payload = build_central_command(
            backtest_root=Path(args.backtest_root).expanduser().resolve(),
            sheet_name=args.sheet_name,
            cloud_region=args.cloud_region,
            force_email=args.force_email,
        )
        print(json.dumps({"note": note, "centralCommandGeneratedAt": payload.get("generatedAt")}, indent=2))
        return 0

    if command == "mission-add":
        mission = add_mission(
            title=args.title,
            body=args.body,
            owner=args.owner,
            status=args.status,
            priority=args.priority,
            tags=parse_tags(args.tags),
        )
        payload = build_central_command(
            backtest_root=Path(args.backtest_root).expanduser().resolve(),
            sheet_name=args.sheet_name,
            cloud_region=args.cloud_region,
            force_email=args.force_email,
        )
        print(json.dumps({"mission": mission, "centralCommandGeneratedAt": payload.get("generatedAt")}, indent=2))
        return 0

    if command == "mission-update":
        mission = update_mission(
            args.id,
            title=args.title,
            body=args.body,
            owner=args.owner,
            status=args.status,
            priority=args.priority,
            tags=parse_tags(args.tags) if args.tags is not None else None,
        )
        payload = build_central_command(
            backtest_root=Path(args.backtest_root).expanduser().resolve(),
            sheet_name=args.sheet_name,
            cloud_region=args.cloud_region,
            force_email=args.force_email,
        )
        print(json.dumps({"mission": mission, "centralCommandGeneratedAt": payload.get("generatedAt")}, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
