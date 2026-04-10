from __future__ import annotations

import argparse
from pathlib import Path
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

SNAPSHOT_PATTERNS = ("snapshot-*.json",)
BRIEF_PATTERNS = ("morning-brief-*.txt", "morning-brief-*.html")
TICKET_PATTERNS = ("paper-tickets-*.txt",)
LONG_TERM_PATTERNS = ("long-term-buys-*.txt",)
LOG_FILES = ("inferno_dawn.stdout.log", "inferno_dawn.stderr.log", "inferno_watchdog.stdout.log", "inferno_watchdog.stderr.log")


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


def trim_log(path: Path, keep_lines: int, dry_run: bool) -> tuple[int, int]:
    if not path.exists():
        return (0, 0)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    original_count = len(lines)
    if original_count <= keep_lines:
        return (original_count, original_count)
    trimmed = lines[-keep_lines:]
    if not dry_run:
        path.write_text("\n".join(trimmed) + "\n", encoding="utf-8")
    return (original_count, len(trimmed))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prune old runtime artifacts so the inferno desk stays readable.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be removed without deleting anything.")
    parser.add_argument("--keep-snapshots", type=int, default=DEFAULT_KEEP_SNAPSHOTS, help="Number of historical data snapshots to keep.")
    parser.add_argument("--keep-briefs", type=int, default=DEFAULT_KEEP_BRIEFS, help="Number of historical morning brief pairs to keep.")
    parser.add_argument("--keep-tickets", type=int, default=DEFAULT_KEEP_TICKETS, help="Number of historical paper ticket files to keep.")
    parser.add_argument("--keep-long-term", type=int, default=DEFAULT_KEEP_BRIEFS, help="Number of historical long-term buy files to keep.")
    parser.add_argument("--keep-log-lines", type=int, default=DEFAULT_KEEP_LOG_LINES, help="Maximum lines to keep in each inferno log file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_lines = ["Inferno Housekeeping", f"Dry run: {'yes' if args.dry_run else 'no'}", ""]

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
        original_count, final_count = trim_log(LOGS_DIR / log_name, args.keep_log_lines, args.dry_run)
        report_lines.append(f"- {log_name}: {original_count} -> {final_count} lines")

    print("\n".join(report_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
