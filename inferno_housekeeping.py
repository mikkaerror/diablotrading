from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
from typing import Iterable

from inferno_config import (
    DEFAULT_KEEP_BRIEFS,
    DEFAULT_KEEP_LOG_LINES,
    DEFAULT_KEEP_SNAPSHOTS,
    DEFAULT_KEEP_TICKETS,
    ROOT,
)


DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
LOGS_DIR = ROOT / "logs"
EXTERNAL_LOGS_DIR = Path.home() / "Library" / "Logs" / "Inferno"

SNAPSHOT_PATTERNS = ("snapshot-*.json",)
BRIEF_PATTERNS = ("morning-brief-*.txt", "morning-brief-*.html")
TICKET_PATTERNS = ("paper-tickets-*.txt",)
LONG_TERM_PATTERNS = ("long-term-buys-*.txt",)
LOG_FILES = ("inferno_dawn.stdout.log", "inferno_dawn.stderr.log", "inferno_watchdog.stdout.log", "inferno_watchdog.stderr.log")
CACHE_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
CACHE_SCAN_EXCLUDES = {".git", ".venv", "venv", "node_modules"}


def iter_matching_files(directory: Path, patterns: Iterable[str]) -> list[Path]:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(directory.glob(pattern))
    return sorted(matches, key=lambda path: path.stat().st_mtime, reverse=True)


def prune_files(files: list[Path], keep: int, dry_run: bool) -> list[Path]:
    doomed = files[keep:] if keep >= 0 else []
    if not dry_run:
        for path in doomed:
            path.unlink(missing_ok=True)
    return doomed


def trim_log(path: Path, keep_lines: int, dry_run: bool) -> tuple[int, int, str | None]:
    """Trim a log file while failing soft on local filesystem read issues.

    Runtime logs live outside git and can be touched by launch agents, iCloud,
    or a still-running process. Housekeeping should report those problems, not
    crash the entire cleanup pass.
    """
    if not path.exists():
        return (0, 0, None)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return (0, 0, f"{type(exc).__name__}: {exc}")
    original_count = len(lines)
    if original_count <= keep_lines:
        return (original_count, original_count, None)
    trimmed = lines[-keep_lines:] if keep_lines else []
    if not dry_run:
        try:
            content = "\n".join(trimmed) + "\n" if trimmed else ""
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return (original_count, original_count, f"{type(exc).__name__}: {exc}")
    return (original_count, len(trimmed), None)


def iter_cache_dirs(root: Path) -> list[Path]:
    """Return only rebuildable project caches, never evidence or dependency trees."""
    matches: list[Path] = []
    for current, dirnames, _filenames in os.walk(root):
        current_path = Path(current)
        cache_names = [name for name in dirnames if name in CACHE_DIR_NAMES]
        matches.extend(current_path / name for name in cache_names)
        dirnames[:] = [
            name for name in dirnames
            if name not in CACHE_SCAN_EXCLUDES and name not in CACHE_DIR_NAMES
        ]
    return sorted(matches)


def directory_bytes(path: Path) -> int:
    """Best-effort recursive byte count for a disposable cache directory."""
    total = 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                total += child.stat().st_size
    except OSError:
        return total
    return total


def prune_cache_dirs(paths: list[Path], dry_run: bool) -> tuple[int, int, list[str]]:
    """Remove rebuildable caches and report count, bytes, and soft failures."""
    reclaimed = 0
    removed = 0
    errors: list[str] = []
    for path in paths:
        reclaimed += directory_bytes(path)
        if dry_run:
            removed += 1
            continue
        try:
            shutil.rmtree(path)
            removed += 1
        except OSError as exc:
            errors.append(f"{path}: {type(exc).__name__}: {exc}")
    return removed, reclaimed, errors


def run_git_gc(root: Path, dry_run: bool) -> tuple[bool, str]:
    """Run normal Git maintenance; never use aggressive or immediate pruning."""
    if dry_run:
        return True, "would run `git gc`"
    try:
        completed = subprocess.run(
            ["git", "gc"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    detail = (completed.stderr or completed.stdout).strip()
    if completed.returncode:
        return False, detail or f"git gc exited {completed.returncode}"
    return True, detail or "complete"


def format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prune old runtime artifacts so the inferno desk stays readable.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be removed without deleting anything.")
    parser.add_argument("--keep-snapshots", type=int, default=DEFAULT_KEEP_SNAPSHOTS, help="Number of historical data snapshots to keep.")
    parser.add_argument("--keep-briefs", type=int, default=DEFAULT_KEEP_BRIEFS, help="Number of historical morning brief pairs to keep.")
    parser.add_argument("--keep-tickets", type=int, default=DEFAULT_KEEP_TICKETS, help="Number of historical paper ticket files to keep.")
    parser.add_argument("--keep-long-term", type=int, default=DEFAULT_KEEP_BRIEFS, help="Number of historical long-term buy files to keep.")
    parser.add_argument("--keep-log-lines", type=int, default=DEFAULT_KEEP_LOG_LINES, help="Maximum lines to keep in each inferno log file.")
    parser.add_argument("--include-external-logs", action="store_true", help="Also trim launch-agent logs under ~/Library/Logs/Inferno.")
    parser.add_argument("--logs-only", action="store_true", help="Trim logs without applying dated-artifact retention.")
    parser.add_argument("--prune-caches", action="store_true", help="Remove rebuildable Python/test cache directories inside the repository.")
    parser.add_argument("--git-gc", action="store_true", help="Run normal `git gc` maintenance (never aggressive or prune-now).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_lines = ["Inferno Housekeeping", f"Dry run: {'yes' if args.dry_run else 'no'}", ""]

    if args.logs_only:
        report_lines.append("Artifact pruning: skipped (logs-only mode)")
    else:
        snapshot_files = iter_matching_files(DATA_DIR, SNAPSHOT_PATTERNS)
        removed_snapshots = prune_files(snapshot_files, args.keep_snapshots, args.dry_run)
        report_lines.append(f"Snapshots kept: {min(len(snapshot_files), args.keep_snapshots)} / {len(snapshot_files)}")
        report_lines.extend([f"- remove snapshot: {path.name}" for path in removed_snapshots])

        brief_files = iter_matching_files(REPORTS_DIR, BRIEF_PATTERNS)
        removed_briefs = prune_files(brief_files, args.keep_briefs * 2, args.dry_run)
        report_lines.append(f"Brief artifacts kept: {min(len(brief_files), args.keep_briefs * 2)} / {len(brief_files)}")
        report_lines.extend([f"- remove brief artifact: {path.name}" for path in removed_briefs])

        ticket_files = iter_matching_files(REPORTS_DIR, TICKET_PATTERNS)
        removed_tickets = prune_files(ticket_files, args.keep_tickets, args.dry_run)
        report_lines.append(f"Ticket artifacts kept: {min(len(ticket_files), args.keep_tickets)} / {len(ticket_files)}")
        report_lines.extend([f"- remove ticket artifact: {path.name}" for path in removed_tickets])

        long_term_files = iter_matching_files(REPORTS_DIR, LONG_TERM_PATTERNS)
        removed_long_term = prune_files(long_term_files, args.keep_long_term, args.dry_run)
        report_lines.append(f"Long-term artifacts kept: {min(len(long_term_files), args.keep_long_term)} / {len(long_term_files)}")
        report_lines.extend([f"- remove long-term artifact: {path.name}" for path in removed_long_term])

    report_lines.append("Log trimming:")
    for log_name in LOG_FILES:
        original_count, final_count, error = trim_log(LOGS_DIR / log_name, args.keep_log_lines, args.dry_run)
        if error:
            report_lines.append(f"- {log_name}: skipped ({error})")
        else:
            report_lines.append(f"- {log_name}: {original_count} -> {final_count} lines")

    if args.include_external_logs:
        report_lines.append("External launch-agent log trimming:")
        external_logs = sorted(EXTERNAL_LOGS_DIR.glob("*.log")) if EXTERNAL_LOGS_DIR.exists() else []
        for path in external_logs:
            original_count, final_count, error = trim_log(path, args.keep_log_lines, args.dry_run)
            if error:
                report_lines.append(f"- {path.name}: skipped ({error})")
            else:
                report_lines.append(f"- {path.name}: {original_count} -> {final_count} lines")

    if args.prune_caches:
        cache_dirs = iter_cache_dirs(ROOT)
        removed, reclaimed, errors = prune_cache_dirs(cache_dirs, args.dry_run)
        verb = "would remove" if args.dry_run else "removed"
        report_lines.append(f"Rebuildable caches: {verb} {removed} directories ({format_bytes(reclaimed)})")
        report_lines.extend(f"- cache skipped: {error}" for error in errors)

    if args.git_gc:
        ok, detail = run_git_gc(ROOT, args.dry_run)
        report_lines.append(f"Git maintenance: {'ok' if ok else 'failed'} ({detail})")

    print("\n".join(report_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
