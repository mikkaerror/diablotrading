from __future__ import annotations

"""Pre-registered forward scorecard for the desk's stock picks.

The long-term accumulation lane recommends names every morning, but nothing
measured whether those names later beat the universe they were picked from.
This module freezes each day's picks *before* outcomes exist (append-only
cohorts) and scores them later on fixed horizons against two baselines:

  - the equal-weight tracker universe on the same dates (same population)
  - SPY, when the exposure-analytics close is available

Horizons are calendar-day proxies for 21 / 63 / 126 sessions (30 / 91 / 182
days), matching the proposal in docs/ASSUMPTIONS_AND_BIG_PICTURE_2026-09-12.md.
Horizons and baselines are fixed here so results cannot be tuned after the
fact. Turnover (how often the lane changes its mind) is reported too.

Research-only. Reads saved snapshots; no network, no tracker/universe edits.
"""

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

PICK_SCORECARD_STAGE = "pick-scorecard-research-only"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
COHORTS_FILE = DATA_DIR / "inferno_pick_scorecard_cohorts.jsonl"
OUTPUT_FILE = DATA_DIR / "inferno_pick_scorecard.json"
TEXT_FILE = REPORTS_DIR / "pick_scorecard_latest.txt"
HORIZONS = {"21s": 30, "63s": 91, "126s": 182}
EXIT_TOLERANCE_DAYS = 7
LANES = ("longTerm", "eventReady")


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def cohort_from_snapshot(snapshot: dict[str, Any], spy_close: float | None = None, source: str = "") -> dict[str, Any] | None:
    stamp = str(snapshot.get("generatedAt") or "")[:10]
    try:
        day = date.fromisoformat(stamp)
    except ValueError:
        return None
    prices = {}
    for row in snapshot.get("rows") or []:
        price = _num(row.get("price"))
        if row.get("ticker") and price:
            prices[row["ticker"]] = price
    if not prices:
        return None
    event_ready = sorted(
        (row for row in snapshot.get("rows") or [] if row.get("ticker") in prices
         and (row.get("setupRec") in {"Straddle", "Vertical Call"}) and (_num(row.get("readiness")) or 0) >= 90),
        key=lambda row: -(_num(row.get("priority")) or 0),
    )[:5]
    return {
        "date": day.isoformat(),
        "source": source,
        "snapshotGeneratedAt": snapshot.get("generatedAt"),
        "picks": {
            "longTerm": [t for t in (snapshot.get("longTermTickers") or []) if t in prices][:5],
            "eventReady": [row["ticker"] for row in event_ready],
        },
        "prices": prices,
        "spy": spy_close,
    }


def load_cohorts(path: Path = COHORTS_FILE) -> list[dict[str, Any]]:
    cohorts = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cohorts.append(json.loads(line))
    except (OSError, ValueError):
        return []
    seen, ordered = set(), []
    for c in cohorts:  # the first record for a day is the frozen one
        if c["date"] not in seen:
            seen.add(c["date"])
            ordered.append(c)
    return sorted(ordered, key=lambda c: c["date"])


def append_cohort(cohort: dict[str, Any], path: Path = COHORTS_FILE) -> bool:
    """Append-only; a day is frozen the first time it is recorded."""
    if any(c["date"] == cohort["date"] for c in load_cohorts(path)):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(cohort, sort_keys=True) + "\n")
    return True


def _exit_cohort(cohorts: list[dict[str, Any]], target: date) -> dict[str, Any] | None:
    best = None
    for c in cohorts:
        d = date.fromisoformat(c["date"])
        if d >= target and (d - target).days <= EXIT_TOLERANCE_DAYS:
            if best is None or d < date.fromisoformat(best["date"]):
                best = c
    return best


def _ret(entry: dict[str, float], exit_: dict[str, float], tickers: list[str]) -> float | None:
    values = [exit_[t] / entry[t] - 1.0 for t in tickers if t in entry and t in exit_]
    return mean(values) if values else None


def score(cohorts: list[dict[str, Any]], latest: dict[str, Any] | None = None) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for lane in LANES:
        lane_out = {}
        for label, days in HORIZONS.items():
            rows = []
            for c in cohorts:
                picks = c["picks"].get(lane) or []
                if not picks:
                    continue
                exit_c = _exit_cohort(cohorts, date.fromisoformat(c["date"]) + timedelta(days=days))
                if not exit_c:
                    continue
                pick_r = _ret(c["prices"], exit_c["prices"], picks)
                univ_r = _ret(c["prices"], exit_c["prices"], list(c["prices"]))
                spy_r = exit_c["spy"] / c["spy"] - 1.0 if c.get("spy") and exit_c.get("spy") else None
                if pick_r is None or univ_r is None:
                    continue
                rows.append({"entry": c["date"], "exit": exit_c["date"], "picks": pick_r,
                             "universe": univ_r, "spy": spy_r, "excess": pick_r - univ_r})
            lane_out[label] = {
                "matured": len(rows),
                "meanPick": round(mean(r["picks"] for r in rows), 4) if rows else None,
                "meanUniverse": round(mean(r["universe"] for r in rows), 4) if rows else None,
                "meanExcessVsUniverse": round(mean(r["excess"] for r in rows), 4) if rows else None,
                "beatUniverseRate": round(sum(r["excess"] > 0 for r in rows) / len(rows), 3) if rows else None,
                "cohorts": rows[-5:],
            }
        # open (not yet matured) marks against the latest snapshot, clearly labelled
        marks = []
        if latest:
            for c in cohorts[-10:]:
                picks = c["picks"].get(lane) or []
                if c["date"] == latest["date"] or not picks:
                    continue
                pick_r = _ret(c["prices"], latest["prices"], picks)
                univ_r = _ret(c["prices"], latest["prices"], list(c["prices"]))
                if pick_r is not None and univ_r is not None:
                    marks.append({"entry": c["date"], "picks": c["picks"][lane], "picksToDate": round(pick_r, 4),
                                  "universeToDate": round(univ_r, 4), "excessToDate": round(pick_r - univ_r, 4)})
        results[lane] = {"horizons": lane_out, "openMarks": marks}
    # turnover: share of the long-term top-5 replaced between consecutive cohorts
    changes = []
    for prev, cur in zip(cohorts, cohorts[1:]):
        a, b = set(prev["picks"].get("longTerm") or []), set(cur["picks"].get("longTerm") or [])
        if a and b:
            changes.append(len(b - a) / len(b))
    results["longTermTurnover"] = {"pairs": len(changes), "meanReplacedShare": round(mean(changes), 3) if changes else None}
    return results


def build_pick_scorecard(data_dir: Path = DATA_DIR, record: bool = True) -> dict[str, Any]:
    cohorts_path = data_dir / COHORTS_FILE.name
    latest = None
    try:
        snapshot = json.loads((data_dir / "latest_snapshot.json").read_text(encoding="utf-8"))
        spy = None
        try:
            exposure = json.loads((data_dir / "inferno_exposure_analytics.json").read_text(encoding="utf-8"))
            if str(exposure.get("generatedAt", ""))[:10] == str(snapshot.get("generatedAt", ""))[:10]:
                spy = _num((exposure.get("marketRegime") or {}).get("spyClose"))
        except (OSError, ValueError):
            pass
        latest = cohort_from_snapshot(snapshot, spy, source="data/latest_snapshot.json")
    except (OSError, ValueError):
        pass
    if record and latest:
        append_cohort(latest, cohorts_path)
    cohorts = load_cohorts(cohorts_path)
    return {
        "generatedAt": latest["snapshotGeneratedAt"] if latest else None,
        "stage": PICK_SCORECARD_STAGE,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "cohorts": len(cohorts),
        "firstCohort": cohorts[0]["date"] if cohorts else None,
        "horizonsCalendarDays": HORIZONS,
        "results": score(cohorts, latest),
        "citations": ["docs/ASSUMPTIONS_AND_BIG_PICTURE_2026-09-12.md (predeclared comparison)",
                      "docs/DESK_AUDIT_2026-09-28.md (gap M3)"],
    }


def _p(value: Any) -> str:
    return "n/a" if value is None else f"{value * 100:+.1f}%"


def pick_scorecard_text(p: dict[str, Any]) -> str:
    lines = ["Inferno Pick Scorecard (pre-registered, research-only)",
             f"Cohorts frozen: {p['cohorts']} since {p['firstCohort']}", ""]
    for lane in LANES:
        lane_out = p["results"][lane]
        lines.append(f"{lane} lane vs equal-weight tracker universe:")
        for label, h in lane_out["horizons"].items():
            if h["matured"]:
                lines.append(f"- {label}: {h['matured']} matured | picks {_p(h['meanPick'])} vs universe "
                             f"{_p(h['meanUniverse'])} | excess {_p(h['meanExcessVsUniverse'])} | beat rate {h['beatUniverseRate']}")
            else:
                lines.append(f"- {label}: no matured cohorts yet")
        for m in lane_out["openMarks"][-3:]:
            lines.append(f"  open mark {m['entry']} {','.join(m['picks'])}: {_p(m['picksToDate'])} vs universe "
                         f"{_p(m['universeToDate'])} (not a result until its horizon matures)")
        lines.append("")
    t = p["results"]["longTermTurnover"]
    lines.append(f"Long-term lane turnover: {t['meanReplacedShare']} of top-5 replaced per snapshot pair ({t['pairs']} pairs)")
    lines.append("Research only. Horizons and baselines are fixed in code; no tuning on these results.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-registered pick scorecard.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status", "seed"])
    parser.add_argument("paths", nargs="*", help="seed: point-in-time latest_snapshot.json files")
    args = parser.parse_args(argv)
    if args.command == "seed":
        for raw in args.paths:
            cohort = cohort_from_snapshot(json.loads(Path(raw).read_text(encoding="utf-8")), source=raw)
            added = bool(cohort) and append_cohort(cohort)
            print(f"{raw}: {'added ' + cohort['date'] if added else 'skipped'}")
        return 0
    payload = build_pick_scorecard(record=args.command == "run")
    if args.command == "run":
        from inferno_io import atomic_write_json, atomic_write_text

        atomic_write_json(OUTPUT_FILE, payload)
        atomic_write_text(TEXT_FILE, pick_scorecard_text(payload))
    print(pick_scorecard_text(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
