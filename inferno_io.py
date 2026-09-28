from __future__ import annotations

"""Shared file-write helpers for the Inferno desk.

This module exists to keep the automation stack calm under overlapping runs.
Several desk subsystems refresh the same family of JSON/text artifacts inside a
short maintenance window. Plain ``Path.write_text`` calls are usually fine, but
under concurrent local writes on macOS they can occasionally raise transient
errors such as ``Resource deadlock avoided``. These helpers give the desk one
reusable retry/atomic-write primitive instead of patching the symptom in every
caller.

Safety contract:
- local filesystem only
- no authority changes
- durable writes via temp-file + rename where possible
- retries only on explicitly transient filesystem errors
"""

import errno
import json
import os
import shutil
import tempfile
import sys
import time
from pathlib import Path
from typing import Any


_RETRYABLE_WRITE_ERRNOS = {
    errno.EAGAIN,
    11,  # macOS can surface "Resource deadlock avoided" with errno 11
    getattr(errno, "EDEADLK", 35),
}
_RETRYABLE_WRITE_PHRASES = (
    "resource deadlock avoided",
    "temporarily unavailable",
)


def is_retryable_write_error(exc: BaseException) -> bool:
    """Return True when ``exc`` looks like a transient local write failure."""
    if not isinstance(exc, OSError):
        return False
    if exc.errno in _RETRYABLE_WRITE_ERRNOS:
        return True
    return any(phrase in str(exc).lower() for phrase in _RETRYABLE_WRITE_PHRASES)


def _atomic_write_once(path: Path, content: str, *, encoding: str) -> None:
    """Write ``content`` to ``path`` with a same-directory temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _atomic_copy_once(source: Path, destination: Path, *, mode: int) -> None:
    """Copy ``source`` into a same-directory temp file, then replace ``destination``.

    Applying the mode before ``os.replace`` means a concurrently launched
    service observes either its previous complete executable or the new one;
    it never observes a partially copied file or a briefly non-executable
    replacement.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{destination.name}.", dir=str(destination.parent))
    try:
        with source.open("rb") as input_handle, os.fdopen(fd, "wb") as output_handle:
            shutil.copyfileobj(input_handle, output_handle)
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, destination)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _append_once(path: Path, content: str, *, encoding: str) -> None:
    """Append ``content`` to ``path`` in one open/write/close cycle."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding=encoding) as handle:
        handle.write(content)


def _run_with_retry(
    writer,
    path: Path,
    content: str,
    *,
    encoding: str,
    retries: int,
    delay_seconds: float,
) -> None:
    """Execute a write function with bounded retry on transient errors."""
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            writer(path, content, encoding=encoding)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if not is_retryable_write_error(exc) or attempt >= retries:
                raise
            # Small linear backoff is enough here; the goal is to let an
            # overlapping writer finish and then continue quietly.
            time.sleep(delay_seconds * (attempt + 1))
    if last_error is not None:
        raise last_error


def atomic_write_text(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    retries: int = 5,
    delay_seconds: float = 0.05,
) -> None:
    """Atomically write text content with bounded retry on transient failures."""
    _run_with_retry(
        _atomic_write_once,
        path,
        content,
        encoding=encoding,
        retries=retries,
        delay_seconds=delay_seconds,
    )
    archive_written_evidence(path, content.encode(encoding))


def atomic_copy_file(
    source: Path,
    destination: Path,
    *,
    mode: int = 0o755,
    retries: int = 5,
    delay_seconds: float = 0.05,
) -> None:
    """Atomically deploy a local file with bounded retry on transient errors.

    This is intentionally local-filesystem-only. It is suitable for the
    LaunchAgent entrypoint copies that must be safe to refresh while a
    scheduler may concurrently start the previous version.
    """
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            _atomic_copy_once(source, destination, mode=mode)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if not is_retryable_write_error(exc) or attempt >= retries:
                raise
            time.sleep(delay_seconds * (attempt + 1))
    if last_error is not None:
        raise last_error


def atomic_write_json(
    path: Path,
    payload: Any,
    *,
    encoding: str = "utf-8",
    indent: int = 2,
    retries: int = 5,
    delay_seconds: float = 0.05,
) -> None:
    """Atomically serialize JSON to disk with the desk's retry defaults."""
    atomic_write_text(
        path,
        json.dumps(payload, indent=indent),
        encoding=encoding,
        retries=retries,
        delay_seconds=delay_seconds,
    )


def append_text(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    retries: int = 5,
    delay_seconds: float = 0.05,
) -> None:
    """Append text with bounded retry on transient local filesystem errors."""
    _run_with_retry(
        _append_once,
        path,
        content,
        encoding=encoding,
        retries=retries,
        delay_seconds=delay_seconds,
    )


def archive_written_evidence(path: Path, raw: bytes) -> None:
    """Observe only persisted decision/evidence files; never alter writer semantics.

    Pass the bytes just written, rather than rereading a path another process
    may have replaced. A durable pending capture survives archive DB failures.
    """
    names = {
        "inferno_paper_execution_ledger.json", "inferno_shadow_evidence.json",
        "inferno_fast_paper_ledger.json", "inferno_scenario_evidence.json",
        "inferno_approval_queue.json", "inferno_strike_plan.json", "operator_decisions.csv",
        "inferno_schwab_transaction_ledger.json",
    }
    if Path(path).name not in names:
        return
    try:
        from inferno_decision_archive import capture_bytes
        capture_bytes(Path(path), raw)
    except Exception as exc:
        # The primary write already succeeded. Never retry or replay a decision.
        print(f"Decision archive capture pending/failed for {Path(path).name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        try:
            from datetime import datetime, timezone
            directory = Path(path).parent / "decision_archive"
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            event = json.dumps({"recordedAt": datetime.now(timezone.utc).isoformat(), "source": Path(path).name,
                                "error": f"{type(exc).__name__}: {exc}"}) + "\n"
            fd = os.open(directory / "capture_failures.jsonl", os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(event); handle.flush(); os.fsync(handle.fileno())
        except OSError as journal_error:
            print(f"Decision archive failure journal unavailable: {journal_error}", file=sys.stderr)
