from __future__ import annotations

"""Mac-native Desk Editor delivery.

Why this exists: cloud scheduled agents cannot reliably see the repo on the
Mac (Sep 28 and Sep 29 both emailed "couldn't reach the desk"). The Mac's
launchd dawn cycle already runs every weekday and already sends mail, so the
morning Desk Editor email is produced here, deterministically, from the same
packet the agent would have read.

Order of work (each step non-fatal; failures are listed in the email):
  1. paper delegate (the ONLY approval path; paper-only, ack-gated, audited),
     then the advisory second opinion (no-op without an API key)
  2. research views: account performance, vol edge, capex flow, pick scorecard,
     short-premium shadow (prereg v2 forward collector)
  3. build the Desk Editor packet and render desk_editor_text
  4. send once per local weekday via the existing .env.smtp settings

Reporting only. Never stages, closes, or submits anything; never touches
broker authority or risk constants.
"""

import argparse
import json
import os
import smtplib
import subprocess
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
STATE_FILE = DATA_DIR / "inferno_desk_editor_mail_state.json"
EMAIL_TEXT_FILE = REPORTS_DIR / "desk_editor_email_latest.txt"

SEND_WINDOW_START_HOUR = 6   # local; dawn service fires 06:00 Sun-Fri
SEND_WINDOW_END_HOUR = 11    # after this, a missed morning waits for tomorrow
STEP_TIMEOUT_SECONDS = 240

PIPELINE_STEPS: tuple[tuple[str, list[str]], ...] = (
    ("prereg integrity", ["inferno_prereg_integrity.py", "run"]),
    ("paper delegate", ["inferno_paper_delegate.py", "run"]),
    ("canonical paper cycle", ["inferno_mac_paper_cycle.py", "--phase", "post-delegate"]),
    ("second opinion", ["inferno_second_opinion.py", "run"]),
    ("paper order cards", ["inferno_paper_order_card.py", "run"]),
    ("fill quality", ["inferno_fill_quality.py", "run"]),
    ("account performance", ["inferno_account_performance.py", "run"]),
    ("vol edge", ["inferno_vol_edge.py", "run"]),
    ("capex flow", ["inferno_capex_flow.py", "run"]),
    ("pick scorecard", ["inferno_pick_scorecard.py", "run"]),
    ("short-premium shadow", ["inferno_short_premium_shadow.py", "run"]),
    ("live-book officer", ["inferno_live_book_officer.py", "run"]),
    ("deposit card", ["inferno_deposit_card.py", "run"]),
    ("earnings runner", ["inferno_earnings_runner.py", "run"]),
    ("lifecycle board", ["inferno_lifecycle_board.py", "run"]),
)

Runner = Callable[[list[str]], tuple[int, str]]


def _default_runner(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            [sys.executable, *cmd], cwd=ROOT, text=True, capture_output=True,
            timeout=STEP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return proc.returncode, (tail[-1] if tail else "")


def in_send_window(now: datetime) -> bool:
    return now.weekday() < 5 and SEND_WINDOW_START_HOUR <= now.hour < SEND_WINDOW_END_HOUR


def load_state(path: Path = STATE_FILE) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def already_sent(state: dict[str, Any], now: datetime) -> bool:
    return now.date().isoformat() in (state.get("sentByDate") or {})


PAPER_STEPS = {"paper delegate", "canonical paper cycle", "paper order cards"}


def dawn_exit_code(environ: dict[str, str] | None = None) -> int:
    try:
        return int((os.environ if environ is None else environ).get("INFERNO_DAWN_EXIT_CODE", "0"))
    except ValueError:
        return 0


def run_pipeline(runner: Runner = _default_runner, dawn_code: int = 0) -> list[dict[str, Any]]:
    results = []
    if dawn_code:
        results.append({"step": "dawn refresh", "ok": False,
                        "detail": f"failed (exit {dawn_code}); paper approvals and staging skipped today, numbers may be stale"})
    for label, cmd in PIPELINE_STEPS:
        if dawn_code and label in PAPER_STEPS:
            continue
        if not (ROOT / cmd[0]).exists():
            results.append({"step": label, "ok": False, "detail": "module missing"})
            continue
        code, detail = runner(cmd)
        results.append({"step": label, "ok": code == 0, "detail": "" if code == 0 else detail[:160]})
    return results


def subject_for(payload: dict[str, Any], now: datetime) -> str:
    day = f"{now:%a %b} {now.day}"
    return f"[Inferno Desk] {day} — {payload.get('headline') or 'desk update'}"


def compose(payload: dict[str, Any], steps: list[dict[str, Any]], text_renderer: Callable[[dict[str, Any]], str]) -> str:
    body = text_renderer(payload)
    failed = [s for s in steps if not s["ok"]]
    if failed:
        notes = ["", "PIPELINE NOTES (these views may be a day old)"]
        notes += [f"- {s['step']}: {s['detail'] or 'failed'}" for s in failed]
        body = body.rstrip() + "\n" + "\n".join(notes) + "\n"
    return body


def send_email(subject: str, body: str) -> dict[str, Any]:
    from server import SMTP_ENV_FILE, load_env_file, smtp_configured, smtp_settings

    load_env_file(SMTP_ENV_FILE)
    if not smtp_configured():
        return {"sent": False, "status": "smtp-not-configured"}
    settings = smtp_settings()
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings["from_addr"]
    message["To"] = settings["to_addr"]
    message.set_content(body)
    if settings["use_ssl"]:
        with smtplib.SMTP_SSL(settings["host"], settings["port"]) as smtp:
            if settings["username"]:
                smtp.login(settings["username"], settings["password"])
            smtp.send_message(message)
    else:
        with smtplib.SMTP(settings["host"], settings["port"]) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            if settings["username"]:
                smtp.login(settings["username"], settings["password"])
            smtp.send_message(message)
    return {"sent": True, "status": "sent"}


def deliver(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Send at most one morning email, even if two runs overlap.

    Sep 30: two dawn invocations ran the mailer 13 seconds apart and both
    passed the once-a-day check before either wrote state, so the email (and
    the delegate) ran twice. A non-blocking file lock makes the second run
    back off; the state check happens again inside the lock.
    """
    if kwargs.get("dry_run"):
        return _deliver_unlocked(*args, **kwargs)
    import fcntl

    state_path = kwargs.get("state_path", STATE_FILE)
    lock_path = Path(state_path).with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "busy", "sent": False}
        try:
            return _deliver_unlocked(*args, **kwargs)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _deliver_unlocked(
    now: datetime | None = None,
    *,
    force: bool = False,
    dry_run: bool = False,
    runner: Runner = _default_runner,
    sender: Callable[[str, str], dict[str, Any]] = send_email,
    state_path: Path = STATE_FILE,
    email_path: Path = EMAIL_TEXT_FILE,
    builder: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = now or datetime.now().astimezone()
    state = load_state(state_path)
    if not force and not in_send_window(now):
        return {"status": "outside-window", "sent": False}
    if not force and already_sent(state, now):
        return {"status": "already-sent", "sent": False}

    steps = run_pipeline(runner, dawn_exit_code()) if not dry_run else []
    if builder is None:
        from inferno_desk_editor import build_desk_editor, save_desk_editor

        payload = build_desk_editor(now=now)
        save_desk_editor(payload)
    else:
        payload = builder()
    from inferno_desk_editor import desk_editor_text

    subject = subject_for(payload, now)
    body = compose(payload, steps, desk_editor_text)
    if dry_run:
        return {"status": "dry-run", "sent": False, "subject": subject, "body": body, "steps": steps}

    try:
        delivery = sender(subject, body)
    except Exception as exc:  # noqa: BLE001 - delivery must never break the dawn cycle
        delivery = {"sent": False, "status": f"send-failed: {type(exc).__name__}"}
    if delivery.get("sent"):
        email_path.parent.mkdir(parents=True, exist_ok=True)
        email_path.write_text(f"Subject: {subject}\n\n{body}", encoding="utf-8")
        state.setdefault("sentByDate", {})[now.date().isoformat()] = {
            "sentAt": now.isoformat(), "subject": subject,
            "failedSteps": [s["step"] for s in steps if not s["ok"]],
        }
        # keep the state file small
        state["sentByDate"] = dict(sorted(state["sentByDate"].items())[-30:])
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return {"status": delivery.get("status"), "sent": bool(delivery.get("sent")), "subject": subject, "steps": steps}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send the Desk Editor morning email from the Mac (reporting only).")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "preview"])
    parser.add_argument("--force", action="store_true", help="Ignore the send window and once-a-day dedupe.")
    args = parser.parse_args(argv)
    if args.command == "preview":
        result = deliver(force=True, dry_run=True)
        print(result["subject"])
        print()
        print(result["body"])
        return 0
    result = deliver(force=args.force)
    print(json.dumps({k: v for k, v in result.items() if k != "body"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
