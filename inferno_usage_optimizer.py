from __future__ import annotations

"""Low-context usage optimizer for the Inferno desk.

The desk has grown into a real system, which means fresh model sessions can
burn a lot of context re-reading history. This module creates a compact
handoff packet that tells Codex, Claude, or the operator what to read first,
what not to paste into chat, and which single commands replace repeated manual
diagnostics.

It is read-only. It never touches broker state, approval state, or authority.
"""

import argparse
import math
from pathlib import Path
from typing import Any

from inferno_config import ROOT, local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


USAGE_OPTIMIZER_FILE = DATA_DIR / "inferno_usage_optimizer.json"
USAGE_OPTIMIZER_TEXT_FILE = REPORTS_DIR / "usage_optimizer_latest.txt"

MODEL_COMMAND_CENTER_FILE = DATA_DIR / "inferno_model_command_center.json"
CENTRAL_COMMAND_FILE = DATA_DIR / "inferno_central_command.json"
DAILY_LOOP_FILE = DATA_DIR / "inferno_daily_loop.json"

APPROX_CHARS_PER_TOKEN = 4
LEAN_HANDOFF_TOKEN_BUDGET = 4500


READ_FIRST: tuple[dict[str, str], ...] = (
    {
        "path": "reports/model_command_center_latest.txt",
        "why": "current operating truth, next actions, report map",
    },
    {
        "path": "reports/central_command_latest.txt",
        "why": "short supervisor status and recommended next move",
    },
    {
        "path": "docs/PROJECT_STATUS.md",
        "why": "stable PM summary; update only when verdict changes",
    },
    {
        "path": "docs/MODEL_COLLABORATION_BRIEF.md",
        "why": "mission, safety rails, division of labor",
    },
)

READ_IF_NEEDED: tuple[dict[str, str], ...] = (
    {
        "path": "docs/REPOSITORY_HYGIENE.md",
        "why": "how to clean, stage, and document without leaking secrets",
    },
    {
        "path": "coordination/README.md",
        "why": "how Codex and Claude coordinate without duplicating work",
    },
)

DO_NOT_PASTE: tuple[str, ...] = (
    "data/*.json unless a bug requires one exact artifact",
    "reports/*.html",
    "reports/history or generated cycle folders",
    "logs/*",
    "broker/account CSV exports",
    "screenshots unless the UI itself is the task",
    "full terminal transcripts when the final 20 lines contain the verdict",
)

ONE_COMMANDS: tuple[dict[str, str], ...] = (
    {
        "command": "./run_inferno_central_command.sh",
        "purpose": "refresh supervisor packet, ops maintenance, command center, and doctor summary",
    },
    {
        "command": "./run_inferno_central_command.sh onboard",
        "purpose": "print the smallest new-model landing packet",
    },
    {
        "command": "./run_inferno_daily_loop.sh && python3 inferno_daily_loop.py onboard",
        "purpose": "refresh deeper diagnostics when strategy context changed",
    },
    {
        "command": "python3 inferno_doctor.py",
        "purpose": "single health verdict; warning lines become work queue items",
    },
    {
        "command": "python3 inferno_math_verify.py && python3 inferno_secret_hygiene.py",
        "purpose": "formula and secret hygiene check before commits",
    },
)


def rel(path: Path) -> str:
    """Return a repo-relative path when possible."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def estimate_tokens(text: str) -> int:
    """Approximate model tokens from character count.

    This is intentionally rough. The goal is not billing precision; it is a
    stable warning light when a handoff packet becomes too large to paste.
    """
    return int(math.ceil(len(text) / APPROX_CHARS_PER_TOKEN))


def measure_file(path: Path) -> dict[str, Any]:
    """Measure one file without raising when it is missing."""
    if not path.exists():
        return {
            "path": rel(path),
            "exists": False,
            "bytes": 0,
            "lines": 0,
            "estimatedTokens": 0,
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": rel(path),
        "exists": True,
        "bytes": len(text.encode("utf-8")),
        "lines": len(text.splitlines()),
        "estimatedTokens": estimate_tokens(text),
    }


def status_value(payload: dict[str, Any]) -> str:
    """Extract a compact status/verdict value from an artifact."""
    for key in ("verdict", "status", "level"):
        value = payload.get(key)
        if value:
            return str(value)
    if payload.get("generatedAt"):
        return "ready"
    return "missing"


def read_first_measurements() -> list[dict[str, Any]]:
    """Return measured READ_FIRST files with their rationale attached."""
    measured: list[dict[str, Any]] = []
    for item in READ_FIRST:
        measurement = measure_file(ROOT / item["path"])
        measurement["why"] = item["why"]
        measured.append(measurement)
    return measured


def read_if_needed_measurements() -> list[dict[str, Any]]:
    """Return measured optional files with their rationale attached."""
    measured: list[dict[str, Any]] = []
    for item in READ_IF_NEEDED:
        measurement = measure_file(ROOT / item["path"])
        measurement["why"] = item["why"]
        measured.append(measurement)
    return measured


def build_usage_optimizer() -> dict[str, Any]:
    """Build the low-context collaboration packet."""
    command_center = load_json_file(MODEL_COMMAND_CENTER_FILE) or {}
    central = load_json_file(CENTRAL_COMMAND_FILE) or {}
    daily_loop = load_json_file(DAILY_LOOP_FILE) or {}
    read_first = read_first_measurements()
    read_if_needed = read_if_needed_measurements()
    handoff_tokens = sum(int(item["estimatedTokens"]) for item in read_first if item["exists"])
    missing = [item["path"] for item in read_first if not item["exists"]]
    metrics = command_center.get("headlineMetrics") or {}
    next_actions = (command_center.get("nextActions") or [])[:5]

    if handoff_tokens <= LEAN_HANDOFF_TOKEN_BUDGET and not missing:
        verdict = "lean"
    elif handoff_tokens <= LEAN_HANDOFF_TOKEN_BUDGET:
        verdict = "lean-with-missing-artifacts"
    else:
        verdict = "too-large"

    return {
        "generatedAt": local_now().isoformat(),
        "verdict": verdict,
        "budget": {
            "readFirstEstimatedTokens": handoff_tokens,
            "leanBudgetTokens": LEAN_HANDOFF_TOKEN_BUDGET,
            "charsPerTokenAssumption": APPROX_CHARS_PER_TOKEN,
        },
        "systemSnapshot": {
            "commandCenter": status_value(command_center),
            "centralCommand": status_value(central),
            "dailyLoop": status_value(daily_loop),
            "autoLiveAllowed": metrics.get("autoLiveAllowed"),
            "paperRemainingForPromotion": metrics.get("paperRemainingForPromotion"),
            "riskGateHardFails": metrics.get("riskGateHardFails"),
        },
        "readFirst": read_first,
        "readIfNeeded": read_if_needed,
        "doNotPaste": list(DO_NOT_PASTE),
        "oneCommands": list(ONE_COMMANDS),
        "nextActions": next_actions,
        "operatorRules": [
            "Start new sessions with ./run_inferno_central_command.sh onboard, not a full chat transcript.",
            "Paste only the failing command plus final verdict lines unless debugging a stack trace.",
            "Use reports/model_command_center_latest.txt as truth; docs are secondary.",
            "Never place a trade or widen live authority from this packet.",
        ],
    }


def render_usage_optimizer(payload: dict[str, Any]) -> str:
    """Render the optimizer packet as a concise operator memo."""
    budget = payload.get("budget") or {}
    snapshot = payload.get("systemSnapshot") or {}
    lines = [
        "Inferno Usage Optimizer",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Read-first estimate: {budget.get('readFirstEstimatedTokens')} tokens "
        f"/ budget {budget.get('leanBudgetTokens')}",
        "",
        "System snapshot:",
        f"- Command center: {snapshot.get('commandCenter')}",
        f"- Central command: {snapshot.get('centralCommand')}",
        f"- Daily loop: {snapshot.get('dailyLoop')}",
        f"- Auto live allowed: {snapshot.get('autoLiveAllowed')}",
        f"- Paper promotion gap: {snapshot.get('paperRemainingForPromotion')}",
        f"- Risk hard fails: {snapshot.get('riskGateHardFails')}",
        "",
        "Read first, in order:",
    ]
    for item in payload.get("readFirst") or []:
        status = "ok" if item.get("exists") else "missing"
        lines.append(
            f"- {item.get('path')} [{status}, ~{item.get('estimatedTokens')} tokens] — {item.get('why')}"
        )

    lines.extend(["", "Read only if the task needs it:"])
    for item in payload.get("readIfNeeded") or []:
        status = "ok" if item.get("exists") else "missing"
        lines.append(
            f"- {item.get('path')} [{status}, ~{item.get('estimatedTokens')} tokens] — {item.get('why')}"
        )

    lines.extend(["", "Do not paste by default:"])
    for item in payload.get("doNotPaste") or []:
        lines.append(f"- {item}")

    lines.extend(["", "One-command replacements:"])
    for item in payload.get("oneCommands") or []:
        lines.append(f"- `{item.get('command')}` — {item.get('purpose')}")

    lines.extend(["", "Top next actions from command center:"])
    actions = payload.get("nextActions") or []
    if not actions:
        lines.append("- none recorded")
    for action in actions:
        lines.append(f"- {action}")

    lines.extend(["", "Operator rules:"])
    for rule in payload.get("operatorRules") or []:
        lines.append(f"- {rule}")
    return "\n".join(lines).rstrip() + "\n"


def save_usage_optimizer(payload: dict[str, Any]) -> None:
    """Persist JSON and text optimizer artifacts."""
    ensure_dirs()
    atomic_write_json(USAGE_OPTIMIZER_FILE, payload)
    atomic_write_text(USAGE_OPTIMIZER_TEXT_FILE, render_usage_optimizer(payload))


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Build a low-context handoff packet for the Inferno desk.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint."""
    args = parse_args()
    if args.command == "status" and USAGE_OPTIMIZER_TEXT_FILE.exists():
        print(USAGE_OPTIMIZER_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_usage_optimizer()
    save_usage_optimizer(payload)
    print(render_usage_optimizer(payload))
    return 0 if payload.get("verdict") != "too-large" else 1


if __name__ == "__main__":
    raise SystemExit(main())
