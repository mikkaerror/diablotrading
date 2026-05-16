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
import tempfile
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
