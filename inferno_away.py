"""Away mode: a short morning email while the operator is away. Research-only.

    python3 inferno_away.py on 2026-12-20 2026-12-28 --note "Breck trip"
    python3 inferno_away.py off        # end the current window and drop upcoming ones
    python3 inferno_away.py status

While a window is active:
  * the Desk Editor email becomes a short summary: money, alerts, loss-rule
    holdings, what the shadow experiments collected, and deposits that landed;
  * the paper delegate is paused, so no new paper tickets get staged that
    nobody is there to key (they would only expire unrun). Shadow and forward
    experiments keep collecting because they need no keying;
  * order cards, deposit cards and decisions wait for the return.
For three days after a window ends, the full email carries a welcome-back
note listing deposits that arrived while away and were not invested yet.

It never approves, stages, sizes or submits anything and never touches broker
authority or risk constants. State lives in data/inferno_away.json.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "data" / "inferno_away.json"
PLAN_FILE = ROOT / "research" / "conviction_plan_draft.json"
DEPOSIT_LOG = ROOT / "data" / "inferno_deposit_log.jsonl"
MAX_WINDOW_DAYS = 45
WELCOME_BACK_DAYS = 3


def _d(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def load(path: Path = STATE_FILE) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"windows": []}
    except (OSError, ValueError):
        return {"windows": []}


def _save(state: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _windows(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [w for w in state.get("windows") or [] if _d(w.get("start")) and _d(w.get("end"))]


def active_window(today: date, state: dict[str, Any] | None = None) -> dict[str, Any] | None:
    for w in _windows(state if state is not None else load()):
        if _d(w["start"]) <= today <= _d(w["end"]):
            return w
    return None


def just_back(today: date, state: dict[str, Any] | None = None) -> dict[str, Any] | None:
    for w in _windows(state if state is not None else load()):
        end = _d(w["end"])
        if end < today <= end + timedelta(days=WELCOME_BACK_DAYS):
            return w
    return None


def is_away(today: date | None = None, path: Path = STATE_FILE) -> bool:
    """Other jobs (approval emails, dispatchers) can ask this before nagging."""
    return active_window(today or date.today(), load(path)) is not None


def deposit_dates(start: date, end: date, plan_path: Path = PLAN_FILE) -> list[str]:
    try:
        deposit = json.loads(plan_path.read_text(encoding="utf-8")).get("deposit") or {}
    except (OSError, ValueError):
        return []
    anchor, every = _d(deposit.get("nextExpected")), int(deposit.get("everyDays") or 0)
    if not anchor or every <= 0:
        return []
    k = (start - anchor).days // every
    day = anchor + timedelta(days=k * every)
    out = []
    while day <= end:
        if day >= start:
            out.append(day.isoformat())
        day += timedelta(days=every)
    return out


def _logged_since(start: date, path: Path = DEPOSIT_LOG) -> bool:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        stamp = _d(row.get("recordedAt"))
        if stamp and stamp >= start:
            return True
    return False


def section(today: date, state_path: Path = STATE_FILE, plan_path: Path = PLAN_FILE,
            deposit_log: Path = DEPOSIT_LOG) -> dict[str, Any]:
    state = load(state_path)
    active = active_window(today, state)
    back = None if active else just_back(today, state)
    out: dict[str, Any] = {"active": active, "justBack": back, "deposits": [], "depositsPending": False}
    window = active or back
    if window:
        start = _d(window["start"])
        last = min(today, _d(window["end"]))
        out["deposits"] = deposit_dates(start, last, plan_path)
        out["depositsPending"] = bool(out["deposits"]) and not _logged_since(_d(out["deposits"][0]), deposit_log)
        back_on = _d(window["end"]) + timedelta(days=1)
        while back_on.weekday() >= 5:  # the email only goes out on weekdays
            back_on += timedelta(days=1)
        out["returnDay"] = back_on.isoformat()
    return out


def turn_on(start: date, end: date, note: str = "", today: date | None = None,
            path: Path = STATE_FILE) -> dict[str, Any]:
    today = today or date.today()
    if end < start:
        raise SystemExit("end date is before start date")
    if (end - start).days + 1 > MAX_WINDOW_DAYS:
        raise SystemExit(f"away windows are capped at {MAX_WINDOW_DAYS} days; set a second one if needed")
    if end < today:
        raise SystemExit("that window is already over")
    state = load(path)
    keep = [w for w in _windows(state) if _d(w["end"]) < start or _d(w["start"]) > end]  # drop overlaps
    window = {"start": start.isoformat(), "end": end.isoformat(), "note": note.strip(),
              "setAt": datetime.now().astimezone().isoformat()}
    state["windows"] = sorted(keep + [window], key=lambda w: w["start"])
    _save(state, path)
    return window


def turn_off(today: date | None = None, path: Path = STATE_FILE) -> dict[str, Any]:
    today = today or date.today()
    state = load(path)
    kept, ended, dropped = [], None, 0
    for w in _windows(state):
        start, end = _d(w["start"]), _d(w["end"])
        if start <= today <= end:
            ended = {**w, "end": (today - timedelta(days=1)).isoformat(), "endedEarlyAt": today.isoformat()}
            if start <= today - timedelta(days=1):
                kept.append(ended)
        elif start > today:
            dropped += 1
        else:
            kept.append(w)
    state["windows"] = kept
    _save(state, path)
    return {"endedActive": ended is not None, "droppedUpcoming": dropped}


def status_text(today: date, path: Path = STATE_FILE) -> str:
    state = load(path)
    active = active_window(today, state)
    upcoming = [w for w in _windows(state) if _d(w["start"]) > today]
    lines = []
    if active:
        lines.append(f"AWAY now through {active['end']}" + (f" ({active['note']})" if active.get("note") else ""))
    else:
        lines.append("Not away. The full morning email runs as usual.")
    for w in upcoming:
        lines.append(f"Upcoming: {w['start']} to {w['end']}" + (f" ({w['note']})" if w.get("note") else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Away mode for the Inferno morning email.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    on = sub.add_parser("on")
    on.add_argument("start")
    on.add_argument("end")
    on.add_argument("--note", default="")
    sub.add_parser("off")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    today = date.today()
    if args.cmd == "on":
        start, end = _d(args.start), _d(args.end)
        if not start or not end:
            raise SystemExit("dates must look like 2026-12-20")
        turn_on(start, end, args.note, today)
    elif args.cmd == "off":
        print(json.dumps(turn_off(today)))
    print(status_text(today))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
