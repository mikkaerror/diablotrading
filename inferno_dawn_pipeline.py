"""Bound the complete dawn job, including provider calls outside updater jobs."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 900
FOLLOW_UP_TIMEOUT_SECONDS = 600


def follow_up_commands(argv: list[str], environ: dict[str, str] | None = None,
                       dawn_ok: bool = True) -> list[list[str]]:
    """Advisory morning jobs that run after the bounded refresh, never fatal.

    The Desk Editor email is sent from here because launchd runs this file
    directly (cloud scheduled agents cannot see the repo). The mailer has its
    own weekday window and once-a-day dedupe, so the 10-minute safety
    interval does not resend. Skipped when the caller asked for no email.
    """
    environ = os.environ if environ is None else environ
    if "--skip-email" in argv or "--cloud-native" in argv:
        return []
    if environ.get("INFERNO_DESK_EDITOR_MAIL", "1").strip().lower() in {"0", "false", "no", "off"}:
        return []
    here = Path(__file__).resolve().parent
    # The second opinion runs inside the mailer, after its once-a-day check,
    # so a paid API is never called on every 10-minute safety tick.
    mailer = [sys.executable, str(here / "inferno_desk_editor_mailer.py"), "run"]
    if not dawn_ok:
        # A failed refresh must not stage paper tickets on stale inputs, but the
        # morning email still goes out and says what failed.
        return [mailer]
    return [[sys.executable, str(here / "inferno_mac_paper_cycle.py"), "--phase", "pre-delegate"], mailer]


def run_bounded(command: list[str], *, timeout_seconds: float, env: dict[str, str] | None = None) -> int:
    """Reap a stalled job and its process group without deleting its lock file."""
    process = subprocess.Popen(command, start_new_session=True, env=env)
    try:
        return process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        return 124


def main() -> int:
    """Run the existing pipeline under a finite wall-clock budget, then advisory follow-ups."""
    from inferno_config import local_now
    from inferno_io import atomic_write_json
    from server import DATA_DIR

    timeout = float(os.environ.get("INFERNO_DAWN_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    if not 0 < timeout <= 3600:
        raise ValueError("INFERNO_DAWN_TIMEOUT_SECONDS must be positive and at most 3600")
    started = time.monotonic()
    code = run_bounded(
        [sys.executable, str(Path(__file__).with_name("morning_inferno_pipeline.py")), *sys.argv[1:]],
        timeout_seconds=timeout,
    )
    atomic_write_json(DATA_DIR / "inferno_dawn_deadline.json", {
        "generatedAt": local_now().isoformat(),
        "ok": code == 0,
        "timedOut": code == 124,
        "returncode": code,
        "timeoutSeconds": timeout,
        "durationSeconds": round(time.monotonic() - started, 3),
        "researchOnly": True,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
    })
    if code == 124:
        print(f"Dawn refresh exceeded {timeout:g}s; job stopped and lock released.", file=sys.stderr)
    follow_env = {**os.environ, "INFERNO_DAWN_EXIT_CODE": str(code)}
    for command in follow_up_commands(sys.argv[1:], dawn_ok=code == 0):
        if Path(command[1]).exists():
            try:
                run_bounded(command, timeout_seconds=FOLLOW_UP_TIMEOUT_SECONDS, env=follow_env)
            except Exception as exc:  # noqa: BLE001 - advisory only
                print(f"Follow-up {Path(command[1]).name} failed: {exc}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
