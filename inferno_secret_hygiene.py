from __future__ import annotations

"""Repository secret-hygiene audit for the Inferno desk."""

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from inferno_config import ROOT, local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


SECRET_HYGIENE_FILE = DATA_DIR / "inferno_secret_hygiene.json"
SECRET_HYGIENE_TEXT_FILE = REPORTS_DIR / "secret_hygiene_latest.txt"
GITIGNORE_FILE = ROOT / ".gitignore"

REQUIRED_GITIGNORE_PATTERNS = [
    ".env",
    ".env.smtp",
    ".env.cloud",
    "gcred.json",
    "cloud-secrets/",
    "data/",
    "reports/",
    "logs/",
    "_backups/",
    "*.bak.*",
    "*.pem",
    "*.key",
    "*.p12",
]


def text(value: Any) -> str:
    return str(value or "").strip()


def run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


def tracked_repo_files() -> list[str]:
    result = run_git("ls-files")
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def path_looks_sensitive(path: str) -> bool:
    lowered = text(path).lower()
    name = Path(lowered).name
    if lowered.startswith(("data/", "reports/", "logs/", "_backups/", "cloud-secrets/")):
        return True
    if lowered in {".env", ".env.smtp", ".env.cloud", "gcred.json"}:
        return True
    if ".bak." in name:
        return True
    return any(name.endswith(suffix) for suffix in (".pem", ".key", ".p12"))


def load_gitignore_text() -> str:
    if not GITIGNORE_FILE.exists():
        return ""
    return GITIGNORE_FILE.read_text(encoding="utf-8")


def build_secret_hygiene() -> dict[str, Any]:
    tracked = tracked_repo_files()
    tracked_sensitive = [path for path in tracked if path_looks_sensitive(path)]
    gitignore_text = load_gitignore_text()
    missing_patterns = [
        pattern for pattern in REQUIRED_GITIGNORE_PATTERNS
        if pattern not in gitignore_text
    ]
    verdict = "healthy" if not tracked_sensitive and not missing_patterns else "attention"
    message = (
        "No tracked secret-like files detected and ignore coverage looks complete."
        if verdict == "healthy"
        else "Tracked secret-like files or missing ignore patterns need cleanup."
    )
    return {
        "generatedAt": local_now().isoformat(),
        "verdict": verdict,
        "ok": verdict == "healthy",
        "message": message,
        "trackedSensitiveCount": len(tracked_sensitive),
        "trackedSensitive": tracked_sensitive[:25],
        "missingGitignorePatterns": missing_patterns,
        "requiredGitignorePatterns": REQUIRED_GITIGNORE_PATTERNS,
    }


def secret_hygiene_text(report: dict[str, Any]) -> str:
    lines = [
        "Inferno Secret Hygiene",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Verdict: {report.get('verdict')}",
        f"Message: {report.get('message')}",
        f"Tracked sensitive count: {report.get('trackedSensitiveCount', 0)}",
        "",
        "Missing .gitignore patterns:",
    ]
    missing = report.get("missingGitignorePatterns") or []
    if not missing:
        lines.append("- none")
    else:
        lines.extend(f"- {pattern}" for pattern in missing)
    lines.extend(["", "Tracked sensitive-like paths:"])
    tracked = report.get("trackedSensitive") or []
    if not tracked:
        lines.append("- none")
    else:
        lines.extend(f"- {path}" for path in tracked)
    return "\n".join(lines).rstrip() + "\n"


def save_secret_hygiene(report: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(SECRET_HYGIENE_FILE, report)
    atomic_write_text(SECRET_HYGIENE_TEXT_FILE, secret_hygiene_text(report))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit repo secret hygiene and ignore coverage.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and SECRET_HYGIENE_TEXT_FILE.exists():
        print(SECRET_HYGIENE_TEXT_FILE.read_text(encoding="utf-8"))
        latest = json.loads(SECRET_HYGIENE_FILE.read_text(encoding="utf-8")) if SECRET_HYGIENE_FILE.exists() else {}
        return 0 if latest.get("ok", True) else 1
    report = build_secret_hygiene()
    save_secret_hygiene(report)
    print(secret_hygiene_text(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
