from __future__ import annotations

"""Strategy lifecycle board: every lane, its stage, its evidence, its next gate.

Lopez de Prado's portfolio-oversight stages (embargo, paper, graduation,
re-allocation, decommission), applied to Inferno's lanes. Rules live in
research/strategy_lifecycle.json. Until Mikka signs them
(data/inferno_lifecycle_ack.json), triggers show as "review" flags only.
Even signed, the board never moves capital: it flags, Mikka decides.
Research-only.
"""

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RESEARCH_DIR = ROOT / "research"
RULES_FILE = RESEARCH_DIR / "strategy_lifecycle.json"
ACK_FILE = DATA_DIR / "inferno_lifecycle_ack.json"
OUTPUT_FILE = DATA_DIR / "inferno_lifecycle_board.json"
TEXT_FILE = ROOT / "reports" / "lifecycle_board_latest.txt"


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:+.1f}%"


def evaluate(lane: dict[str, Any], data: dict[str, Any], today: date) -> dict[str, Any]:
    src = lane.get("source")
    stage, evidence, flag = lane.get("stage"), "", None
    if src == "short-premium":
        s = (data.get("shortPremium") or {}).get("summary") or {}
        evidence = f"{s.get('distinctEvents', 0)}/60 events, {s.get('distinctNames', 0)}/40 names"
        verdict = s.get("verdict") or ""
        if verdict.endswith("confirmed"):
            flag = "graduation review: prereg CONFIRM reached"
        elif verdict.endswith("killed"):
            flag = "decommission review: prereg KILL"
    elif src == "runner":
        sb = ((data.get("runner") or {}).get("scoreboard") or {}).get(lane["arm"]) or {}
        closed, ex = sb.get("closed", 0), sb.get("meanExTwoBest")
        lo, hi = (sb.get("clusterCI95") or [None, None])[:2]
        evidence = f"{closed}/30 closed" + ("" if sb.get("mean") is None else f", mean {_pct(sb['mean'])}, ex-best-2 {_pct(ex)}")
        if closed >= 30 and ex is not None and ex > 0 and lo is not None and lo > 0:
            flag = "graduation review: gate met"
        elif closed >= 30 and ((ex is not None and ex <= 0) or (hi is not None and hi < 0)):
            flag = "decommission review: kill rule met"
    elif src == "lineage":
        q = ((data.get("lineage") or {}).get("promotion") or {}).get("qualifiedPaperOutcomes")
        evidence = f"{q if q is not None else '?'}/30 qualified fills"
    elif src == "scorecard":
        res = ((data.get("scorecard") or {}).get("results") or {}).get(lane["lane"]) or {}
        h91 = (res.get("horizons") or {}).get("63s") or {}
        h182 = (res.get("horizons") or {}).get("126s") or {}
        marks = res.get("openMarks") or []
        open_note = "" if not marks else f"; open mark {_pct(marks[-1].get('excessToDate'))} vs universe"
        evidence = (f"91d: {h91.get('matured', 0)} matured, excess {_pct(h91.get('meanExcessVsUniverse'))}; "
                    f"182d: {h182.get('matured', 0)} matured{open_note}")
        cut, dec = lane.get("cutBackExcess"), lane.get("decommissionExcess")
        if (h182.get("matured") or 0) >= 2 and dec is not None and (h182.get("meanExcessVsUniverse") or 0) < dec:
            flag = "decommission review: 182-day cohorts trail the universe"
        elif (h91.get("matured") or 0) >= 2 and cut is not None and (h91.get("meanExcessVsUniverse") or 0) < cut:
            flag = "cut-back review: 91-day cohorts trail the universe"
        if lane["lane"] == "capexFlow" and ((data.get("capex") or {}).get("regime") or {}).get("regime") == "cut":
            flag = "decommission review: capex tap turned to cut"
    elif src == "static":
        evidence = lane.get("record", "")
    timebox = lane.get("timebox")
    if timebox and not flag and today > date.fromisoformat(timebox) and stage == "embargo":
        flag = "decommission review: time-box passed"
    return {"label": lane["label"], "stage": stage, "evidence": evidence, "flag": flag,
            "next": lane.get("graduate") if stage in {"embargo", "paper"} else lane.get("cutBack") or lane.get("kill"),
            "kill": lane.get("kill")}


def build(data_dir: Path = DATA_DIR, research_dir: Path = RESEARCH_DIR, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    rules = _load(research_dir / "strategy_lifecycle.json")
    data = {
        "shortPremium": _load(data_dir / "inferno_short_premium_shadow.json"),
        "runner": _load(data_dir / "inferno_earnings_runner.json"),
        "lineage": _load(data_dir / "inferno_promotion_evidence_lineage.json"),
        "scorecard": _load(data_dir / "inferno_pick_scorecard.json"),
        "capex": _load(data_dir / "inferno_capex_flow.json"),
    }
    signed = bool(_load(data_dir / "inferno_lifecycle_ack.json").get("active"))
    lanes = [{"key": k, **evaluate(v, data, today)} for k, v in (rules.get("lanes") or {}).items()]
    order = {s: i for i, s in enumerate(rules.get("stages") or [])}
    lanes.sort(key=lambda r: order.get(r["stage"], 99))
    return {"generatedAt": datetime.now().astimezone().isoformat(), "stage": "lifecycle-board-research-only",
            "researchOnly": True, "liveTradingAllowed": False, "brokerSubmitAllowed": False,
            "rulesStatus": "signed" if signed else rules.get("status", "missing"), "lanes": lanes,
            "flags": [f"{r['label']}: {r['flag']}" for r in lanes if r["flag"]]}


def board_text(p: dict[str, Any]) -> str:
    tag = "" if p["rulesStatus"] == "signed" else " (rules are a DRAFT until you sign them)"
    lines = [f"Strategy lifecycle board{tag}", ""]
    for r in p["lanes"]:
        lines.append(f"- [{r['stage']}] {r['label']}: {r['evidence']}")
        if r["flag"]:
            lines.append(f"    REVIEW: {r['flag']}")
        elif r.get("next"):
            lead = "next gate" if r["stage"] in {"embargo", "paper"} else "cut back if"
            lines.append(f"    {lead}: {r['next']}")
    lines += ["", "Report only. The board flags; you decide. Nothing moves capital automatically."]
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    from inferno_io import atomic_write_json, atomic_write_text

    payload = build()
    atomic_write_json(OUTPUT_FILE, payload)
    atomic_write_text(TEXT_FILE, board_text(payload))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strategy lifecycle board (research-only).")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    args = parser.parse_args(argv)
    payload = run() if args.command == "run" else _load(OUTPUT_FILE)
    print(board_text(payload) if payload else "No lifecycle board yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
