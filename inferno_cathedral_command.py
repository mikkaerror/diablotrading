#!/usr/bin/env python3
"""Inferno Command Cathedral — a read-only illuminated operating picture.

Research-only. Read-only. promotable = False.
This module NEVER touches authority, tickets, risk constants, broker state, or
any of the Codex-owned control modules. It only *reads* existing desk artifacts
and renders a single self-contained HTML page in the desk's Diablo-cathedral
visual language. Deleting its output changes nothing downstream.

Sources read (all best-effort; a missing/garbled file falls back to the last
known snapshot baked in below, so the page always renders):
  reports/model_command_center_latest.txt
  reports/risk_gate_audit_latest.txt
  reports/portfolio_correlation_latest.txt
  reports/promotion_gap_latest.txt

Usage:
  python3 inferno_cathedral_command.py                 # writes both outputs under reports/
  python3 inferno_cathedral_command.py --root .        # repo root (default ".")
  python3 inferno_cathedral_command.py --out PATH      # standalone .html (opens locally)
  python3 inferno_cathedral_command.py --artifact-out PATH  # content-only (for the Artifact tool)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Baked snapshot — the last-known-true desk state (2026-08-27 09:12 MT read).
# Every reader below overrides these in place when its source file is present.
# ---------------------------------------------------------------------------
def baked_desk() -> dict:
    return {
        "snapshot": "2026-08-27",
        "generatedMT": "2026-08-27T09:12:52-06:00",
        "renderedAt": None,
        "mission": ("Keep the earnings desk automated, testable, and safe while "
                    "building toward broker-assisted execution — without granting "
                    "unapproved authority."),
        "verdictLabel": "Research-only desk · holding at the gate",
        "verdictTone": "hold",
        "vault": {
            "nlv": 3471.05,
            "nlvSource": "TOS account statement",
            "cashHeadline": 1035.96,
            "deployableConfirmed": 0.0,
            "observedTrendPct": 244.5,
            "observedTrendAbs": 2463.48,
            "capitalVerdict": "not-ready",
            "optimization": "protect-and-prove",
            "constructionCap": [250, 500],
            "paperCap": 2000,
            "liveOptionsCap": 0,
            "autoLive": False,
            "depositAmt": 250, "depositEvery": 14, "depositNext": "2026-08-28", "deposit30": 750,
        },
        "gate": {
            "scored": 1, "target": 30, "gap": 29, "distinctEvents": 1,
            "gatesOpen": 1, "gatesTotal": 7, "promotable": False,
            "subgates": [
                {"name": "win-rate lower bound", "have": 0.0, "need": 0.42, "pass": False},
                {"name": "expectancy (lower)", "have": -1.0, "need": 0.0, "pass": False},
                {"name": "profit factor", "have": 0.0, "need": 1.25, "pass": False},
                {"name": "false-positive rate", "have": 0.9798, "need": 0.45, "pass": False, "invert": True},
                {"name": "drawdown floor (R)", "have": -1.0, "need": -6.0, "pass": True, "floor": True},
            ],
            "perStrategy": [
                {"name": "CALL_DEBIT_SPREAD", "scored": 1},
                {"name": "LONG_STRADDLE", "scored": 0},
                {"name": "LONG_STRANGLE", "scored": 0},
                {"name": "Straddle", "scored": 0},
                {"name": "Vertical Call", "scored": 0},
            ],
        },
        "seals": [
            {"name": "Live trading", "state": "SEALED", "detail": "liveTradingAllowed = False"},
            {"name": "Broker submit", "state": "SEALED", "detail": "brokerSubmitAllowed = False"},
            {"name": "Broker adapter", "state": "OFF", "detail": "BROKER_ADAPTER_MODE = OFF"},
            {"name": "Submit live order", "state": "BLOCKED", "detail": "always in blockedActions"},
            {"name": "Authority level", "state": "HALTED", "detail": "authority controller"},
        ],
        "wards": {
            "verdict": "blocked", "pass": 5, "total": 12,
            "hardFails": 2, "promotionFails": 1, "warnings": 4,
            "gates": [
                {"label": "Authority live-submit lock", "kind": "hard", "state": "pass", "note": "level halted"},
                {"label": "Live account scope", "kind": "hard", "state": "fail", "note": "suffix missing · expects 8499"},
                {"label": "Live position fragility", "kind": "hard", "state": "pass", "note": "supported 0 · fragile 0"},
                {"label": "Capital deployment preflight", "kind": "hard", "state": "fail", "note": "not-ready"},
                {"label": "Broker preview safety", "kind": "hard", "state": "pass", "note": "mode OFF"},
                {"label": "Paper evidence promotion", "kind": "promotion", "state": "fail", "note": "scored 1 · 29 to go"},
                {"label": "Paper test action path", "kind": "promotion", "state": "pass", "note": "stageable 1"},
                {"label": "Strategy lab evidence", "kind": "promotion", "state": "pass", "note": "evidence-building"},
                {"label": "Email delivery & approval capture", "kind": "delivery", "state": "warn", "note": "morning/doctor flags"},
                {"label": "Downloads & fill capture", "kind": "capture", "state": "warn", "note": "0 imported rows"},
                {"label": "TOS readonly capture", "kind": "capture", "state": "warn", "note": "manual check"},
                {"label": "Paper exit capture", "kind": "capture", "state": "warn", "note": "1 open exit to review"},
            ],
        },
        "concentration": {
            "verdict": "concentrated-by-drift",
            "headcount": 1378, "effectiveBets": 1.81, "dominantShare": 0.6611,
            "families": [
                {"name": "Long Straddle", "dir": "long-vol", "n": 911},
                {"name": "Vertical Debit", "dir": "long-equity", "n": 467},
            ],
        },
        "crowd": {
            "verdict": "normal", "signals": 1, "of": 3, "asOf": "2026-08-17",
            "reads": [
                {"name": "side-skew", "lean": "neutral", "detail": "balanced"},
                {"name": "own-side concentration", "lean": "long-vol-heavy", "detail": "911 / 1378 long-vol"},
                {"name": "family fusion", "lean": "unknown", "detail": "no closed pairs yet"},
            ],
        },
        "drawdown": {"verdict": "awaiting-closed-outcomes", "current": 0.0, "max": 0.0,
                     "ulcer": 0.0, "regime": "normal", "mult": 1.0},
        "research": {
            "mathVerify": "clean",
            "scenarioEvidence": 776, "observationsClosed": 1788, "observationsTracked": 1809,
            "calibration": "calibration-watch",
            "chainHistoryHave": 8, "chainHistoryNeed": 60, "chainDiffEvents": 3397,
            "strikeLedger": 99, "shadowTracked": 1389, "shadowClosed": 779,
            "expectedMove": "insufficient-data",
        },
        "names": ["AVGO", "MEI", "IREN", "HPE", "MRVL"],
        "freshness": [
            {"name": "Tracker snapshot", "state": "fresh", "age": "1.2h"},
            {"name": "Doctor", "state": "fresh", "age": "0.0h"},
            {"name": "Schwab account sync", "state": "fresh", "age": "0.2h", "note": "reauth required"},
            {"name": "Action pulse", "state": "fresh", "age": "1.9h"},
            {"name": "Morning email", "state": "fresh", "age": "1.2h"},
            {"name": "Live account sync", "state": "stale", "age": "136h"},
            {"name": "Schwab options tape", "state": "stale", "age": "218h"},
            {"name": "Consensus monitor", "state": "stale", "age": "10d"},
        ],
        "nextMove": ("M01 — Restore fresh Schwab account & option truth: refresh "
                     "account / options / price history, then rerun risk and capital "
                     "reports. Only restart OAuth if status says reauthorization is required."),
    }


# ---------------------------------------------------------------------------
# Best-effort readers (each wrapped so a bad file never breaks the render)
# ---------------------------------------------------------------------------
def _read(root: str, name: str) -> str | None:
    path = os.path.join(root, "reports", name)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def read_command_center(root: str, desk: dict) -> None:
    txt = _read(root, "model_command_center_latest.txt")
    if not txt:
        return
    m = re.search(r"Generated:\s*(\S+)", txt)
    if m:
        desk["generatedMT"] = m.group(1)
        desk["snapshot"] = m.group(1)[:10]
    m = re.search(r"Account NLV:\s*\$?([\d,]+\.?\d*)", txt)
    if m and _num(m.group(1)) is not None:
        desk["vault"]["nlv"] = _num(m.group(1))
    m = re.search(r"Account cash:\s*\$?([\d,]+\.?\d*)", txt)
    if m and _num(m.group(1)) is not None:
        desk["vault"]["cashHeadline"] = _num(m.group(1))
    m = re.search(r"Promotion gap:\s*(\d+)", txt)
    if m:
        desk["gate"]["gap"] = int(m.group(1))
        desk["gate"]["scored"] = max(0, desk["gate"]["target"] - int(m.group(1)))
    m = re.search(r"Risk gate hard fails:\s*(\d+)", txt)
    if m:
        desk["wards"]["hardFails"] = int(m.group(1))
    m = re.search(r"Auto live allowed:\s*(\w+)", txt)
    if m:
        desk["vault"]["autoLive"] = m.group(1).strip().lower() == "true"
    m = re.search(r"Paper top five:\s*([A-Z0-9,\s]+)", txt)
    if m:
        names = [t.strip() for t in m.group(1).split(",") if t.strip()]
        if names:
            desk["names"] = names[:6]
    m = re.search(r"Next move:\s*(.+)", txt)
    if m:
        desk["nextMove"] = m.group(1).strip()
    # Freshness panel: "- <name>: fresh|stale | <ts> | <age> old"
    fresh = []
    for line in txt.splitlines():
        fm = re.match(r"^-\s+(.+?):\s+(fresh|stale|attention|unknown)\b.*?\|\s*([\d.]+h)\s*old", line)
        if fm:
            state = "stale" if fm.group(2) in ("stale", "attention", "unknown") else "fresh"
            fresh.append({"name": fm.group(1).strip(), "state": state, "age": fm.group(3)})
    if fresh:
        desk["freshness"] = fresh[:9]


def read_risk_gate(root: str, desk: dict) -> None:
    txt = _read(root, "risk_gate_audit_latest.txt")
    if not txt:
        return
    m = re.search(r"Verdict:\s*(\S+)", txt)
    if m:
        desk["wards"]["verdict"] = m.group(1)
    m = re.search(r"Gates:\s*(\d+)/(\d+)\s*pass\s*\|\s*hard fails\s*(\d+)\s*\|\s*promotion fails\s*(\d+)\s*\|\s*warnings\s*(\d+)", txt)
    if m:
        w = desk["wards"]
        w["pass"], w["total"] = int(m.group(1)), int(m.group(2))
        w["hardFails"], w["promotionFails"], w["warnings"] = int(m.group(3)), int(m.group(4)), int(m.group(5))
    gates = []
    for line in txt.splitlines():
        gm = re.match(r"^-\s*(PASS|FAIL|WARN)\s*\[([^/\]]+)/([^\]]+)\]\s*([^:]+):?\s*(.*)$", line)
        if not gm:
            continue
        state = {"PASS": "pass", "FAIL": "fail", "WARN": "warn"}[gm.group(1)]
        note = gm.group(5).strip()
        note = re.sub(r"\s+", " ", note)[:60]
        gates.append({"label": gm.group(4).strip(), "kind": gm.group(2).strip(),
                      "state": state, "note": note})
    if gates:
        desk["wards"]["gates"] = gates


def read_correlation(root: str, desk: dict) -> None:
    txt = _read(root, "portfolio_correlation_latest.txt")
    if not txt:
        return
    c = desk["concentration"]
    m = re.search(r"Verdict:\s*(\S+)", txt)
    if m:
        c["verdict"] = m.group(1)
    m = re.search(r"Headcount:\s*(\d+)", txt)
    if m:
        c["headcount"] = int(m.group(1))
    m = re.search(r"Effective bet count:\s*([\d.]+)", txt)
    if m:
        c["effectiveBets"] = round(float(m.group(1)), 2)
    m = re.search(r"Dominant family share:\s*([\d.]+)", txt)
    if m:
        c["dominantShare"] = float(m.group(1))
    fm = re.search(r"By family:\s*(.+)", txt)
    if fm:
        fams = []
        for part in fm.group(1).split(","):
            pm = re.match(r"\s*(.+?)=(\d+)\s*$", part)
            if pm:
                fams.append({"name": pm.group(1).strip(), "n": int(pm.group(2)), "dir": ""})
        # tag direction from the "By direction" line if present
        dm = re.search(r"By direction:\s*(.+)", txt)
        dirs = {}
        if dm:
            for part in dm.group(1).split(","):
                pm = re.match(r"\s*(.+?)=(\d+)\s*$", part)
                if pm:
                    dirs[int(pm.group(2))] = pm.group(1).strip()
        for f in fams:
            f["dir"] = dirs.get(f["n"], f["dir"])
        if fams:
            c["families"] = fams


def read_promotion_gap(root: str, desk: dict) -> None:
    txt = _read(root, "promotion_gap_latest.txt")
    if not txt:
        return
    g = desk["gate"]
    m = re.search(r"Overall gates open:\s*(\d+)/(\d+)", txt)
    if m:
        g["gatesOpen"], g["gatesTotal"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"scored trades:\s*(\d+)/(\d+)\s*\(gap\s*(\d+)\)", txt)
    if m:
        g["scored"], g["target"], g["gap"] = int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.search(r"distinct events:\s*(\d+)/(\d+)", txt)
    if m:
        g["distinctEvents"] = int(m.group(1))
    m = re.search(r"Overall promotable:\s*(\w+)", txt)
    if m:
        g["promotable"] = m.group(1).strip().lower() == "true"
    per = []
    for line in txt.splitlines():
        pm = re.match(r"^-\s*([A-Za-z_ ]+):\s*\d+/7\s*\|\s*scored\s*(\d+)/(\d+)", line)
        if pm:
            per.append({"name": pm.group(1).strip(), "scored": int(pm.group(2))})
    if per:
        g["perStrategy"] = per[:6]


def build_desk(root: str) -> dict:
    desk = baked_desk()
    for reader in (read_command_center, read_risk_gate, read_correlation, read_promotion_gap):
        try:
            reader(root, desk)
        except Exception as exc:  # never let a parse error break the render
            sys.stderr.write(f"[cathedral] {reader.__name__} skipped: {exc}\n")
    desk["renderedAt"] = _dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    return desk


# ---------------------------------------------------------------------------
# Presentation — content-only body + a doctype wrapper for local opening.
# ---------------------------------------------------------------------------
HEAD_BITS = """<title>Inferno Command Cathedral</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;800&family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>__CSS__</style>"""

BODY_BITS = """<main id="app" aria-label="Inferno desk operating picture"></main>
<script>
const DESK = __DESK_JSON__;
__JS__
</script>"""

DOC_OPEN = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">')
DOC_MID = "</head><body>"
DOC_CLOSE = "</body></html>"


def render(desk: dict, standalone: bool) -> str:
    head = HEAD_BITS.replace("__CSS__", CSS)
    body = BODY_BITS.replace("__DESK_JSON__", json.dumps(desk)).replace("__JS__", JS)
    if standalone:
        return DOC_OPEN + head + DOC_MID + body + DOC_CLOSE
    return head + "\n" + body


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render the Inferno Command Cathedral (read-only).")
    ap.add_argument("--root", default=".", help="repo root that contains reports/ (default '.')")
    ap.add_argument("--out", default=None, help="standalone HTML path (default <root>/reports/cathedral_command_center.html)")
    ap.add_argument("--artifact-out", default=None, help="content-only HTML path for the Artifact tool")
    ap.add_argument("--only", choices=["standalone", "artifact"], default=None)
    args = ap.parse_args(argv)

    desk = build_desk(args.root)
    out = args.out or os.path.join(args.root, "reports", "cathedral_command_center.html")
    art = args.artifact_out or os.path.join(args.root, "reports", "cathedral_command_center.artifact.html")

    if args.only != "artifact":
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(render(desk, standalone=True))
        print(f"[cathedral] standalone -> {out}")
    if args.only != "standalone":
        os.makedirs(os.path.dirname(art) or ".", exist_ok=True)
        with open(art, "w", encoding="utf-8") as fh:
            fh.write(render(desk, standalone=False))
        print(f"[cathedral] artifact  -> {art}")
    print(f"[cathedral] NLV ${desk['vault']['nlv']:,.2f} · gate {desk['gate']['scored']}/{desk['gate']['target']}"
          f" · effective bets {desk['concentration']['effectiveBets']} of {desk['concentration']['headcount']}"
          f" · risk {desk['wards']['verdict']}")
    return 0


# CSS and JS are defined at the bottom so main() reads top-down.
CSS = r"""/* ------------------------------------------------------------------ *
 * Inferno Command Cathedral — a single, committed hellfire-cathedral  *
 * visual world. Painted explicitly so it holds on any host ground.    *
 * ------------------------------------------------------------------ */
:root{
  color-scheme: dark;
  --void:#0b0806;         /* warm near-black ground            */
  --stone:#14100c;        /* panel stone                       */
  --stone-2:#1c1610;      /* raised stone                      */
  --stone-edge:#332619;   /* etched border                     */
  --ink:#e9dcc2;          /* parchment text                    */
  --ink-dim:#a8967a;      /* muted parchment                   */
  --ink-faint:#6f6350;    /* faint captions                    */
  --ember:#e0a63a;        /* molten gold — the one bold accent */
  --ember-hot:#f0c25a;    /* highlight of the gold             */
  --blood:#c0392b;        /* hellfire red                      */
  --blood-deep:#7d1f18;   /* deep blood                        */
  --sanct:#3fa86e;        /* verdigris — sanctified / pass     */
  --warn:#c9932f;         /* ochre — warn                      */
  --fail:#c0392b;         /* crimson — fail                    */
  --iron:#7aa6c2;         /* cold arcane iron — the seals      */
  --iron-deep:#2b3a45;
  --shadow: 0 18px 46px rgba(0,0,0,.55);
  --ring: 0 0 0 1px var(--stone-edge);
  --gap: clamp(14px, 2.2vw, 22px);
  --maxw: 1180px;
  --serif:"EB Garamond","Iowan Old Style",Georgia,"Times New Roman",serif;
  --display:"Cinzel","Trajan Pro",Georgia,serif;
  --mono:"JetBrains Mono",ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;
}
*{box-sizing:border-box;}
html{ -webkit-text-size-adjust:100%; }
body{
  margin:0;
  background:
    radial-gradient(1200px 620px at 50% -8%, #241206 0%, rgba(36,18,6,0) 60%),
    radial-gradient(900px 520px at 84% 8%, rgba(192,57,43,.14) 0%, rgba(192,57,43,0) 55%),
    radial-gradient(760px 520px at 10% 22%, rgba(224,166,58,.10) 0%, rgba(224,166,58,0) 55%),
    linear-gradient(180deg, #0d0906 0%, var(--void) 46%, #080503 100%);
  color:var(--ink);
  font-family:var(--serif);
  font-size:17px;
  line-height:1.5;
  min-height:100vh;
}
#app{ max-width:var(--maxw); margin:0 auto; padding: clamp(20px,4vw,52px) clamp(16px,3.4vw,40px) 72px; }

/* ---- type ---- */
h1,h2,h3{ font-family:var(--display); font-weight:600; letter-spacing:.02em; text-wrap:balance; margin:0; }
.eyebrow{ font-family:var(--mono); text-transform:uppercase; letter-spacing:.34em; font-size:11px; color:var(--ink-faint); }
.mono{ font-family:var(--mono); font-variant-numeric:tabular-nums; }
.num{ font-family:var(--mono); font-variant-numeric:tabular-nums; letter-spacing:-.01em; }
a{ color:var(--ember); }

/* ---- masthead ---- */
.masthead{ display:flex; flex-wrap:wrap; align-items:flex-end; gap:20px 26px; padding-bottom:22px;
  border-bottom:1px solid var(--stone-edge); margin-bottom:var(--gap);
  background:
    radial-gradient(420px 120px at 6% 120%, rgba(224,166,58,.10), rgba(224,166,58,0) 70%);
}
.crest{ width:60px; height:60px; flex:0 0 auto; filter:drop-shadow(0 0 14px rgba(224,166,58,.35)); }
.masthead .title-wrap{ flex:1 1 320px; }
.masthead h1{ font-size:clamp(29px,4.6vw,46px); font-weight:800; line-height:1.02;
  background:linear-gradient(180deg, var(--ember-hot), var(--ember) 52%, #b07c26);
  -webkit-background-clip:text; background-clip:text; color:transparent;
  text-shadow:0 1px 0 rgba(0,0,0,.4); }
.masthead .sub{ color:var(--ink-dim); font-size:15.5px; margin-top:8px; max-width:60ch; }
.stampcol{ text-align:right; display:flex; flex-direction:column; gap:6px; align-items:flex-end; }
.stampcol .big{ font-size:13px; color:var(--ink); }
.stampcol .small{ font-size:11px; color:var(--ink-faint); }

/* verdict banner */
.verdict{ display:inline-flex; align-items:center; gap:12px; margin-top:2px;
  font-family:var(--display); font-size:14px; letter-spacing:.05em; padding:9px 16px;
  border-radius:2px; border:1px solid var(--stone-edge);
  background:linear-gradient(180deg, rgba(192,57,43,.16), rgba(192,57,43,.05));
  color:var(--ember); box-shadow: inset 0 0 22px rgba(0,0,0,.4); }
.verdict .dot{ width:9px; height:9px; border-radius:50%; background:var(--ember);
  box-shadow:0 0 12px var(--ember); animation: pulse 3.4s ease-in-out infinite; }

/* ---- panels ---- */
.panel{ position:relative; background:
    linear-gradient(180deg, var(--stone-2), var(--stone));
  border:1px solid var(--stone-edge); border-radius:3px; padding:20px 20px 22px;
  box-shadow:var(--shadow), inset 0 1px 0 rgba(255,225,170,.04);
}
.panel::before{ content:""; position:absolute; inset:0; border-radius:3px; pointer-events:none;
  box-shadow: inset 0 0 0 1px rgba(255,220,160,.03), inset 0 26px 40px rgba(0,0,0,.32); }
.panel > .ph{ display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin-bottom:14px; }
.panel h2{ font-size:15px; letter-spacing:.18em; text-transform:uppercase; color:var(--ink); font-weight:600; }
.panel h2 .rune{ color:var(--ember); margin-right:9px; }
.tag{ font-family:var(--mono); font-size:10.5px; letter-spacing:.14em; text-transform:uppercase;
  padding:3px 8px; border-radius:2px; border:1px solid var(--stone-edge); color:var(--ink-dim); white-space:nowrap; }
.tag.good{ color:var(--sanct); border-color:rgba(63,168,110,.4); background:rgba(63,168,110,.08); }
.tag.bad{ color:var(--fail); border-color:rgba(192,57,43,.45); background:rgba(192,57,43,.10); }
.tag.warn{ color:var(--warn); border-color:rgba(201,147,47,.4); background:rgba(201,147,47,.08); }
.tag.iron{ color:var(--iron); border-color:rgba(122,166,194,.38); background:rgba(122,166,194,.08); }

/* ---- triptych ---- */
.triptych{ display:grid; grid-template-columns: 1fr 1.25fr 1fr; gap:var(--gap); margin-bottom:var(--gap); }
@media (max-width:900px){ .triptych{ grid-template-columns:1fr; } }

/* Vault */
.vault .nlv{ font-family:var(--mono); font-weight:600; font-size:clamp(30px,5vw,44px);
  color:var(--ember-hot); letter-spacing:-.02em; line-height:1;
  text-shadow:0 0 26px rgba(224,166,58,.25); }
.vault .nlv small{ font-size:15px; color:var(--ink-dim); font-weight:400; margin-left:6px; }
.vault .src{ font-size:12px; color:var(--ink-faint); margin-top:6px; }
.ledger{ margin-top:16px; display:grid; gap:2px; }
.ledger .row{ display:flex; justify-content:space-between; gap:12px; padding:7px 0;
  border-bottom:1px dashed rgba(51,38,25,.7); font-size:14px; }
.ledger .row:last-child{ border-bottom:0; }
.ledger .k{ color:var(--ink-dim); }
.ledger .v{ color:var(--ink); font-family:var(--mono); font-variant-numeric:tabular-nums; }
.ledger .v.warnv{ color:var(--warn); }
.ledger .v.badv{ color:var(--fail); }
.ledger .v.ironv{ color:var(--iron); }

/* Gate (centerpiece) */
.gate{ text-align:center; }
.gate .facade{ width:100%; max-width:340px; height:auto; margin:2px auto 6px; display:block; }
.gate .caption{ font-family:var(--display); font-size:19px; color:var(--ember); letter-spacing:.03em; }
.gate .caption b{ color:var(--ember-hot); }
.gate .subcap{ color:var(--ink-dim); font-size:13.5px; margin-top:4px; }
.fuel{ height:10px; border-radius:6px; background:#0d0a07; border:1px solid var(--stone-edge);
  margin:14px 4px 4px; overflow:hidden; box-shadow:inset 0 1px 3px rgba(0,0,0,.6); }
.fuel > span{ display:block; height:100%; width:0;
  background:linear-gradient(90deg, var(--blood-deep), var(--blood) 40%, var(--ember) 88%, var(--ember-hot));
  box-shadow:0 0 14px rgba(224,166,58,.5); transition:width 1.1s cubic-bezier(.2,.7,.2,1); }
.gate .binding{ margin-top:14px; font-size:13px; color:var(--ink-faint); font-style:italic; }
.perstrat{ margin-top:14px; display:flex; flex-wrap:wrap; gap:6px; justify-content:center; }
.perstrat .chip{ font-family:var(--mono); font-size:10.5px; letter-spacing:.06em; padding:3px 8px;
  border:1px solid var(--stone-edge); border-radius:2px; color:var(--ink-faint); }
.perstrat .chip.lit{ color:var(--ember); border-color:rgba(224,166,58,.4); background:rgba(224,166,58,.07); }

/* Seals */
.seals ul{ list-style:none; margin:6px 0 0; padding:0; display:grid; gap:10px; }
.seal{ display:flex; align-items:center; gap:13px; padding:11px 12px; border-radius:2px;
  border:1px solid rgba(122,166,194,.22);
  background:linear-gradient(180deg, rgba(43,58,69,.35), rgba(43,58,69,.12)); }
.seal .glyph{ width:30px; height:30px; flex:0 0 auto; display:grid; place-items:center;
  border-radius:50%; border:1px solid rgba(122,166,194,.5); color:var(--iron);
  box-shadow:0 0 14px rgba(122,166,194,.22), inset 0 0 10px rgba(122,166,194,.14);
  font-family:var(--display); font-size:15px; }
.seal .body{ flex:1 1 auto; min-width:0; }
.seal .body .n{ font-size:14.5px; color:var(--ink); }
.seal .body .d{ font-family:var(--mono); font-size:11px; color:var(--iron); letter-spacing:.02em; }
.seal .state{ font-family:var(--mono); font-size:10.5px; letter-spacing:.16em; color:var(--iron);
  border:1px solid rgba(122,166,194,.4); border-radius:2px; padding:3px 7px; }
.seals .foot{ margin-top:12px; font-size:12.5px; color:var(--ink-faint); font-style:italic; }

/* ---- ward gates grid ---- */
.wards-head{ display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center; margin-bottom:14px; }
.wards-head .counts{ display:flex; flex-wrap:wrap; gap:8px; }
.wardgrid{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
@media (max-width:900px){ .wardgrid{ grid-template-columns:repeat(2,1fr); } }
@media (max-width:520px){ .wardgrid{ grid-template-columns:1fr; } }
.ward{ position:relative; padding:12px 12px 12px 15px; border-radius:2px; background:var(--stone);
  border:1px solid var(--stone-edge); overflow:hidden; }
.ward::before{ content:""; position:absolute; left:0; top:0; bottom:0; width:4px; }
.ward.pass::before{ background:var(--sanct); box-shadow:0 0 12px rgba(63,168,110,.5); }
.ward.fail::before{ background:var(--fail); box-shadow:0 0 12px rgba(192,57,43,.55); }
.ward.warn::before{ background:var(--warn); box-shadow:0 0 12px rgba(201,147,47,.5); }
.ward .wl{ display:flex; align-items:center; gap:8px; }
.ward .glyph{ font-family:var(--display); font-size:14px; width:16px; text-align:center; }
.ward.pass .glyph{ color:var(--sanct); } .ward.fail .glyph{ color:var(--fail); } .ward.warn .glyph{ color:var(--warn); }
.ward .label{ font-size:13.5px; color:var(--ink); line-height:1.25; }
.ward .note{ font-family:var(--mono); font-size:10.5px; color:var(--ink-faint); margin-top:6px; letter-spacing:.02em; }
.ward .kind{ position:absolute; right:9px; top:9px; font-family:var(--mono); font-size:9px;
  letter-spacing:.12em; text-transform:uppercase; color:var(--ink-faint); opacity:.75; }
.ward.hard .kind{ color:var(--iron); opacity:.9; }

/* ---- lower grid ---- */
.lower{ display:grid; grid-template-columns:1.35fr 1fr; gap:var(--gap); margin-top:var(--gap); }
@media (max-width:900px){ .lower{ grid-template-columns:1fr; } }

/* reliquary / concentration */
.relic canvas{ width:100%; height:150px; display:block; border-radius:2px;
  background:radial-gradient(120% 120% at 50% 120%, rgba(224,166,58,.06), rgba(0,0,0,0)); }
.relic .bignum{ display:flex; align-items:baseline; gap:12px; margin:12px 0 2px; flex-wrap:wrap; }
.relic .bignum .eff{ font-family:var(--mono); font-weight:600; font-size:42px; color:var(--ember-hot);
  line-height:1; text-shadow:0 0 22px rgba(224,166,58,.25); }
.relic .bignum .of{ font-size:14px; color:var(--ink-dim); }
.relic .bignum .of b{ color:var(--ink); font-family:var(--mono); }
.relic .fams{ margin-top:12px; display:grid; gap:8px; }
.relic .fam{ }
.relic .fam .flabel{ display:flex; justify-content:space-between; font-size:13px; color:var(--ink-dim); margin-bottom:4px; }
.relic .fam .flabel b{ color:var(--ink); font-family:var(--mono); }
.relic .bar{ height:9px; border-radius:5px; background:#0d0a07; border:1px solid var(--stone-edge); overflow:hidden; }
.relic .bar > span{ display:block; height:100%;
  background:linear-gradient(90deg, var(--blood-deep), var(--ember)); }

/* stack of small meters */
.smallstack{ display:grid; gap:var(--gap); }
.meter-row{ display:grid; gap:10px; }
.meter{ }
.meter .ml{ display:flex; justify-content:space-between; font-size:13px; color:var(--ink-dim); margin-bottom:5px; }
.meter .ml b{ font-family:var(--mono); }
.meter .ml b.ok{ color:var(--sanct); } .meter .ml b.miss{ color:var(--fail); }
.track{ height:8px; border-radius:5px; background:#0d0a07; border:1px solid var(--stone-edge); position:relative; overflow:hidden; }
.track > .fillbar{ position:absolute; top:0; bottom:0; left:0; }
.track > .need{ position:absolute; top:-3px; bottom:-3px; width:2px; background:var(--ink-dim); opacity:.8; }
.fillbar.ok{ background:linear-gradient(90deg,#256b46,var(--sanct)); }
.fillbar.miss{ background:linear-gradient(90deg,var(--blood-deep),var(--blood)); }

/* pendulum */
.pend{ text-align:center; }
.pend svg{ width:100%; max-width:280px; height:auto; margin:2px auto 0; display:block; }
.pend .verdict-lg{ font-family:var(--display); font-size:22px; color:var(--ember); margin-top:2px; }
.pend .reads{ margin-top:12px; display:grid; gap:7px; text-align:left; }
.pend .rd{ display:flex; justify-content:space-between; gap:10px; font-size:12.5px;
  border-bottom:1px dashed rgba(51,38,25,.6); padding-bottom:6px; }
.pend .rd .lean{ font-family:var(--mono); font-size:11px; color:var(--ink-dim); }
.pend .rd .lean.hot{ color:var(--ember); }

/* watchfires (freshness) */
.torchwrap{ display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:12px; }
.torch{ display:flex; align-items:center; gap:11px; padding:10px 12px; border-radius:2px;
  background:var(--stone); border:1px solid var(--stone-edge); }
.flame{ width:16px; height:24px; flex:0 0 auto; position:relative; }
.flame i{ position:absolute; left:50%; bottom:0; transform:translateX(-50%);
  width:11px; height:18px; border-radius:50% 50% 48% 52% / 62% 62% 38% 38%;
  background:radial-gradient(circle at 50% 78%, var(--ember-hot), var(--blood) 74%, transparent 78%);
  box-shadow:0 0 12px rgba(224,166,58,.55); transform-origin:50% 90%;
  animation: flick 1.6s ease-in-out infinite; }
.torch.stale .flame i{ background:radial-gradient(circle at 50% 82%, #6a5738, #3a2c18 78%, transparent 82%);
  box-shadow:0 0 5px rgba(90,70,40,.4); animation: gutter 2.6s ease-in-out infinite; opacity:.75; }
.torch .tn{ font-size:13px; color:var(--ink); }
.torch .ta{ font-family:var(--mono); font-size:11px; }
.torch .ta{ color:var(--sanct); } .torch.stale .ta{ color:var(--warn); }
.torch .tnote{ font-family:var(--mono); font-size:9.5px; color:var(--ink-faint); }

/* names */
.namescroll{ display:flex; gap:8px; flex-wrap:wrap; margin-top:6px; }
.namescroll .nm{ font-family:var(--display); font-size:14px; letter-spacing:.06em; color:var(--ember);
  border:1px solid rgba(224,166,58,.3); border-radius:2px; padding:4px 11px;
  background:linear-gradient(180deg, rgba(224,166,58,.08), rgba(224,166,58,.02)); }

/* research strip */
.rstrip{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; }
.rcell{ padding:12px 13px; border-radius:2px; background:var(--stone); border:1px solid var(--stone-edge); }
.rcell .rv{ font-family:var(--mono); font-size:21px; color:var(--ink); font-variant-numeric:tabular-nums; }
.rcell .rk{ font-size:11px; color:var(--ink-dim); text-transform:uppercase; letter-spacing:.12em; margin-top:4px; }
.rcell.clean .rv{ color:var(--sanct); }

/* next move / covenant */
.nextmove{ margin-top:var(--gap); display:flex; gap:16px; align-items:flex-start;
  padding:18px 20px; border-radius:3px; border:1px solid rgba(224,166,58,.28);
  background:linear-gradient(180deg, rgba(224,166,58,.09), rgba(224,166,58,.02)); }
.nextmove .mk{ font-family:var(--display); color:var(--ember); font-size:13px; letter-spacing:.18em;
  text-transform:uppercase; white-space:nowrap; padding-top:2px; }
.nextmove .mv{ font-size:15px; color:var(--ink); }
.covenant{ margin-top:26px; text-align:center; color:var(--ink-faint); font-size:12.5px; font-style:italic;
  border-top:1px solid var(--stone-edge); padding-top:18px; }
.covenant b{ color:var(--iron); font-style:normal; font-family:var(--mono); font-size:11px; letter-spacing:.1em; }

/* section spacing */
.section{ margin-top:var(--gap); }
.section > h2.free{ font-size:14px; letter-spacing:.2em; text-transform:uppercase; color:var(--ink-dim);
  margin-bottom:12px; display:flex; align-items:center; gap:10px; }
.section > h2.free::after{ content:""; flex:1 1 auto; height:1px;
  background:linear-gradient(90deg,var(--stone-edge),transparent); }

/* animations */
@keyframes pulse{ 0%,100%{ opacity:1; } 50%{ opacity:.4; } }
@keyframes flick{ 0%,100%{ transform:translateX(-50%) scaleY(1) rotate(-1deg); }
  50%{ transform:translateX(-50%) scaleY(1.14) rotate(1.5deg); } }
@keyframes gutter{ 0%,100%{ transform:translateX(-50%) scaleY(.9); opacity:.6; }
  50%{ transform:translateX(-50%) scaleY(1.05); opacity:.85; } }
@keyframes emberglow{ 0%,100%{ opacity:.86; } 50%{ opacity:1; } }
.lit-anim{ animation: emberglow 3.2s ease-in-out infinite; }
:focus-visible{ outline:2px solid var(--ember); outline-offset:2px; }
@media (prefers-reduced-motion: reduce){
  *{ animation:none !important; transition:none !important; }
}
"""
JS = r"""/* Inferno Command Cathedral — render the operating picture from DESK. */
(function(){
  "use strict";
  const $ = (sel, root) => (root||document).querySelector(sel);
  const money = (n, dec=2) => "$" + Number(n||0).toLocaleString("en-US",{minimumFractionDigits:dec, maximumFractionDigits:dec});
  const esc = (s) => String(s==null?"":s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  const RUNE = {pass:"†", fail:"†", warn:"†"}; // dagger; state carried by color

  /* ---------- crest emblem ---------- */
  function crest(){
    return `<svg class="crest" viewBox="0 0 60 60" aria-hidden="true">
      <defs><linearGradient id="cg" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#f0c25a"/><stop offset="1" stop-color="#b07c26"/></linearGradient></defs>
      <path d="M30 3 L52 16 V40 Q52 54 30 58 Q8 54 8 40 V16 Z" fill="none" stroke="url(#cg)" stroke-width="2"/>
      <path d="M30 15 Q23 24 30 33 Q37 24 30 15 Z" fill="url(#cg)"/>
      <path d="M30 30 Q26 37 30 44 Q34 37 30 30 Z" fill="#c0392b"/>
      <line x1="30" y1="44" x2="30" y2="50" stroke="url(#cg)" stroke-width="2"/>
    </svg>`;
  }

  /* ---------- the gate facade ---------- */
  function gateFacade(g){
    const lit = g.scored, total = g.target;
    const x0=84, y0=126, cols=6, rows=Math.ceil(total/6);
    const areaW=172, areaH=206, cw=areaW/cols, ch=areaH/rows;
    const nichePath=(x,y,w,h)=>{
      const sh=y+7, apexX=x+w/2, apexY=y-4;
      return `M ${x} ${y+h} L ${x} ${sh} Q ${x} ${y} ${apexX-0.5} ${apexY} Q ${x+w} ${y} ${x+w} ${sh} L ${x+w} ${y+h} Z`;
    };
    let niches="";
    for(let i=0;i<total;i++){
      const col=i%cols, row=Math.floor(i/cols);
      const x=x0+col*cw+4, y=y0+row*ch+4, w=cw-8, h=ch-13;
      const on=i<lit;
      niches += `<path d="${nichePath(x,y,w,h)}" fill="${on?'url(#litgrad)':'#0c0906'}" `
        + `stroke="${on?'#f0c25a':'#2a2015'}" stroke-width="${on?1.1:0.8}" `
        + `${on?'filter="url(#glow)" class="lit-anim"':''}/>`;
    }
    const roseLit = lit>0;
    return `<svg class="facade" viewBox="0 0 340 360" role="img" aria-label="Cathedral of paper evidence: ${lit} of ${total} niches consecrated">
      <defs>
        <linearGradient id="litgrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#f6d074"/><stop offset="1" stop-color="#c0392b"/></linearGradient>
        <linearGradient id="stonegrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#241b12"/><stop offset="1" stop-color="#100b07"/></linearGradient>
        <filter id="glow" x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="2.2" result="b"/><feMerge>
          <feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      </defs>
      <!-- towers + facade body -->
      <path d="M14 350 V54 L36 34 L58 54 V350 Z" fill="url(#stonegrad)" stroke="#2a2015" stroke-width="1"/>
      <path d="M282 350 V54 L304 34 L326 54 V350 Z" fill="url(#stonegrad)" stroke="#2a2015" stroke-width="1"/>
      <path d="M64 350 V96 Q64 40 170 26 Q276 40 276 96 V350 Z" fill="url(#stonegrad)" stroke="#2a2015" stroke-width="1.2"/>
      <!-- rose window -->
      <circle cx="170" cy="80" r="28" fill="#0c0906" stroke="${roseLit?'#e0a63a':'#2a2015'}" stroke-width="1.4" ${roseLit?'filter="url(#glow)"':''}/>
      <circle cx="170" cy="80" r="12" fill="none" stroke="${roseLit?'#e0a63a':'#2a2015'}" stroke-width="1"/>
      ${[0,45,90,135].map(a=>{const r=a*Math.PI/180,dx=Math.cos(r)*28,dy=Math.sin(r)*28;
        return `<line x1="${170-dx}" y1="${80-dy}" x2="${170+dx}" y2="${80+dy}" stroke="${roseLit?'#e0a63a':'#2a2015'}" stroke-width="0.8" opacity="0.7"/>`;}).join("")}
      ${niches}
      <!-- ground -->
      <rect x="8" y="348" width="324" height="6" fill="#1a130c"/>
    </svg>`;
  }

  /* ---------- concentration reliquary canvas ---------- */
  function drawReliquary(canvas, c){
    if(!canvas) return;
    const dpr = Math.min(window.devicePixelRatio||1, 2);
    const w = canvas.clientWidth||520, h = 150;
    canvas.width = w*dpr; canvas.height = h*dpr;
    const ctx = canvas.getContext("2d"); ctx.scale(dpr,dpr);
    ctx.clearRect(0,0,w,h);
    // dim sparks = every ticket (capped for perf), split by family share
    const cap = Math.min(c.headcount, 720);
    const domShare = c.dominantShare || 0.5;
    for(let i=0;i<cap;i++){
      const x = Math.random()*w, y = Math.random()*h;
      const dom = i < cap*domShare;
      ctx.beginPath();
      ctx.arc(x,y, Math.random()*1.1+0.4, 0, Math.PI*2);
      ctx.fillStyle = dom ? "rgba(224,166,58,0.16)" : "rgba(122,166,194,0.14)";
      ctx.fill();
    }
    // bright flares = effective independent bets
    const flares = Math.max(1, Math.round(c.effectiveBets));
    for(let i=0;i<flares;i++){
      const x = w*(i+1)/(flares+1), y = h*0.52;
      const grd = ctx.createRadialGradient(x,y,1,x,y,26);
      grd.addColorStop(0,"rgba(246,208,116,0.95)");
      grd.addColorStop(0.4,"rgba(224,166,58,0.5)");
      grd.addColorStop(1,"rgba(224,166,58,0)");
      ctx.fillStyle = grd; ctx.beginPath(); ctx.arc(x,y,26,0,Math.PI*2); ctx.fill();
      ctx.fillStyle = "#fbe6ad"; ctx.beginPath(); ctx.arc(x,y,2.4,0,Math.PI*2); ctx.fill();
    }
  }

  /* ---------- crowdedness pendulum ---------- */
  function pendulum(cr){
    const pos = {"uncrowded":0.12,"normal":0.30,"crowded-watch":0.55,"consensus-extreme":0.85,"awaiting-data":0.5}[cr.verdict] ?? 0.5;
    const ang = Math.PI*(1-pos);           // pi(left)..0(right)
    const cx=140, cy=118, R=104;
    const nx=cx+Math.cos(ang)*R, ny=cy-Math.sin(ang)*R;
    return `<svg viewBox="0 0 280 140" role="img" aria-label="Crowdedness pendulum: ${esc(cr.verdict)}">
      <path d="M ${cx-R} ${cy} A ${R} ${R} 0 0 1 ${cx+R} ${cy}" fill="none" stroke="#2a2015" stroke-width="10" stroke-linecap="round"/>
      <path d="M ${cx-R} ${cy} A ${R} ${R} 0 0 1 ${cx+R} ${cy}" fill="none" stroke="url(#pg)" stroke-width="3" opacity="0.8"/>
      <defs><linearGradient id="pg" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="#3fa86e"/><stop offset="0.5" stop-color="#c9932f"/><stop offset="1" stop-color="#c0392b"/></linearGradient></defs>
      <text x="${cx-R}" y="${cy+18}" fill="#6f6350" font-size="9" font-family="JetBrains Mono, monospace">calm</text>
      <text x="${cx+R}" y="${cy+18}" fill="#6f6350" font-size="9" text-anchor="end" font-family="JetBrains Mono, monospace">extreme</text>
      <line x1="${cx}" y1="${cy}" x2="${nx}" y2="${ny}" stroke="#f0c25a" stroke-width="2.4" stroke-linecap="round" filter="url(#glow2)"/>
      <circle cx="${cx}" cy="${cy}" r="5" fill="#e0a63a"/>
      <circle cx="${nx}" cy="${ny}" r="3.4" fill="#fbe6ad"/>
      <filter id="glow2" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="1.6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </svg>`;
  }

  /* ---------- subgate meters ---------- */
  function subMeter(s){
    let frac, cls, needPos=null, valTxt, needTxt;
    const fmt=(v)=> (v==null?"—":(Math.abs(v)>=1000?Number(v).toLocaleString():String(v)));
    if(s.floor){ // higher-than-floor is good (drawdown)
      const span=Math.abs(s.need)||1; frac=Math.min(1,Math.max(0,(s.have-s.need)/span));
      cls=s.pass?"ok":"miss"; valTxt=fmt(s.have)+ (s.name.includes("(R)")?"":""); needTxt="floor "+fmt(s.need);
      needPos=0;
    } else if(s.invert){ // lower-than-cap is good (false-positive)
      frac=Math.min(1, s.need? s.have/s.need : 0); cls=s.pass?"ok":"miss";
      valTxt=(s.have*100).toFixed(0)+"%"; needTxt="cap "+(s.need*100).toFixed(0)+"%"; needPos=100;
    } else { // higher-than-need is good
      frac = s.need? Math.min(1, Math.max(0, s.have/s.need)) : (s.have>0?1:0);
      cls=s.pass?"ok":"miss";
      valTxt = (s.have%1!==0)? s.have.toFixed(2): String(s.have);
      needTxt = (s.need%1!==0)? s.need.toFixed(2): String(s.need);
      needPos = 100;
    }
    return `<div class="meter">
      <div class="ml"><span>${esc(s.name)}</span><b class="${cls==='ok'?'ok':'miss'}">${esc(valTxt)} <span style="color:var(--ink-faint)">/ ${esc(needTxt)}</span></b></div>
      <div class="track"><span class="fillbar ${cls}" style="width:${Math.round(frac*100)}%"></span>${needPos!=null?`<span class="need" style="left:${needPos}%"></span>`:""}</div>
    </div>`;
  }

  /* ---------- builders ---------- */
  function build(){
    const D = DESK, v=D.vault, g=D.gate, c=D.concentration, w=D.wards;
    const toneTag = {hold:"warn"}[D.verdictTone]||"warn";
    const capTag = v.capitalVerdict==="not-ready" ? "bad" : "good";

    let html = "";

    /* masthead */
    html += `<header class="masthead">
      ${crest()}
      <div class="title-wrap">
        <div class="eyebrow">Inferno · manual options desk</div>
        <h1>Command Cathedral</h1>
        <p class="sub">${esc(D.mission)}</p>
        <div class="verdict"><span class="dot"></span>${esc(D.verdictLabel)}</div>
      </div>
      <div class="stampcol">
        <div class="big mono">${esc(D.snapshot)}</div>
        <div class="small">desk read ${esc((D.generatedMT||"").replace("T"," ").slice(0,16))} MT</div>
        <div class="small">rendered ${esc(D.renderedAt||"")}</div>
      </div>
    </header>`;

    /* triptych */
    html += `<section class="triptych">`;

    // Vault
    html += `<div class="panel vault">
      <div class="ph"><h2><span class="rune">◈</span>The Vault</h2><span class="tag ${capTag}">${esc(v.capitalVerdict)}</span></div>
      <div class="nlv">${money(v.nlv)}<small>NLV</small></div>
      <div class="src">source · ${esc(v.nlvSource)}</div>
      <div class="ledger">
        <div class="row"><span class="k">Broker-confirmed deployable</span><span class="v ironv">${money(v.deployableConfirmed)}</span></div>
        <div class="row"><span class="k">Account cash (headline)</span><span class="v">${money(v.cashHeadline)}</span></div>
        <div class="row"><span class="k">Observed NLV trend</span><span class="v ironv">+${v.observedTrendPct}% <span style="color:var(--ink-faint)">· unattributed</span></span></div>
        <div class="row"><span class="k">Optimization posture</span><span class="v">${esc(v.optimization)}</span></div>
        <div class="row"><span class="k">Construction cap</span><span class="v">${money(v.constructionCap[0],0)}–${money(v.constructionCap[1],0)}</span></div>
        <div class="row"><span class="k">Paper cap</span><span class="v">${money(v.paperCap,0)}</span></div>
        <div class="row"><span class="k">Live options cap</span><span class="v badv">${money(v.liveOptionsCap,0)}</span></div>
        <div class="row"><span class="k">Auto-live allowed</span><span class="v ${v.autoLive?'':'badv'}">${v.autoLive?'true':'false'}</span></div>
        <div class="row"><span class="k">Next deposit</span><span class="v">${money(v.depositAmt,0)} · ${esc(v.depositNext)}</span></div>
      </div>
    </div>`;

    // Gate
    const litChips = g.perStrategy.map(p=>`<span class="chip ${p.scored>0?'lit':''}">${esc(p.name)} ${p.scored}</span>`).join("");
    html += `<div class="panel gate">
      <div class="ph"><h2><span class="rune">☨</span>The Gate</h2><span class="tag ${g.promotable?'good':'bad'}">${g.gatesOpen}/${g.gatesTotal} open</span></div>
      ${gateFacade(g)}
      <div class="caption"><b>${g.scored}</b> of ${g.target} sanctified</div>
      <div class="subcap">${g.gap} closed scored outcomes to consecrate the promotion gate</div>
      <div class="fuel"><span style="width:${Math.round(g.scored/g.target*100)}%"></span></div>
      <div class="perstrat">${litChips}</div>
      <div class="binding">The one binding constraint. Only closed paper outcomes move it — not simulation volume.</div>
    </div>`;

    // Seals
    const sealItems = D.seals.map(s=>`<li class="seal">
      <span class="glyph">✡</span>
      <span class="body"><span class="n">${esc(s.name)}</span><br><span class="d">${esc(s.detail)}</span></span>
      <span class="state">${esc(s.state)}</span>
    </li>`).join("");
    html += `<div class="panel seals">
      <div class="ph"><h2><span class="rune" style="color:var(--iron)">✡</span>The Seals</h2><span class="tag iron">cold iron</span></div>
      <ul>${sealItems}</ul>
      <div class="foot">Hard-pinned in the authority controller. No condition flips them; the desk graduates only through the 30-outcome gate plus explicit human ack.</div>
    </div>`;
    html += `</section>`;

    /* ward-gates */
    const counts = [
      `<span class="tag ${w.verdict==='blocked'?'bad':'good'}">${esc(w.verdict)}</span>`,
      `<span class="tag good">${w.pass}/${w.total} pass</span>`,
      `<span class="tag bad">${w.hardFails} hard fail${w.hardFails===1?'':'s'}</span>`,
      `<span class="tag warn">${w.warnings} warn</span>`,
    ].join("");
    const wardTiles = w.gates.map(gt=>`<div class="ward ${gt.state} ${gt.kind==='hard'?'hard':''}">
      <span class="kind">${esc(gt.kind)}</span>
      <div class="wl"><span class="glyph">†</span><span class="label">${esc(gt.label)}</span></div>
      ${gt.note?`<div class="note">${esc(gt.note)}</div>`:""}
    </div>`).join("");
    html += `<section class="section">
      <h2 class="free">Ward-gates</h2>
      <div class="wards-head"><div class="counts">${counts}</div></div>
      <div class="wardgrid">${wardTiles}</div>
    </section>`;

    /* lower row 1: reliquary + pendulum */
    html += `<section class="lower">
      <div class="panel relic">
        <div class="ph"><h2><span class="rune">⚜</span>Concentration Reliquary</h2><span class="tag ${c.verdict.includes('concentrated')?'warn':'good'}">${esc(c.verdict)}</span></div>
        <canvas aria-hidden="true"></canvas>
        <div class="bignum"><span class="eff">${Number(c.effectiveBets).toFixed(1)}</span>
          <span class="of">effective independent bets<br>across <b>${c.headcount.toLocaleString()}</b> active paper tickets</span></div>
        <div class="fams">${c.families.map(f=>{
          const pct=Math.round(f.n/c.headcount*100);
          return `<div class="fam"><div class="flabel"><span>${esc(f.name)} <span style="color:var(--ink-faint)">· ${esc(f.dir)}</span></span><b>${f.n.toLocaleString()} · ${pct}%</b></div>
            <div class="bar"><span style="width:${pct}%"></span></div></div>`;}).join("")}</div>
        <div class="binding" style="margin-top:12px;color:var(--ink-faint);font-style:italic;font-size:12.5px">Risk-unit weighted: a thousand tickets in two families count as roughly two independent bets. A research flag, never an auto-reject.</div>
      </div>
      <div class="panel pend">
        <div class="ph"><h2><span class="rune">⚖</span>Crowdedness</h2><span class="tag ${DESK.crowd.verdict==='normal'?'good':'warn'}">${DESK.crowd.signals}/${DESK.crowd.of} leaning</span></div>
        ${pendulum(DESK.crowd)}
        <div class="verdict-lg">${esc(DESK.crowd.verdict)}</div>
        <div class="reads">${DESK.crowd.reads.map(r=>`<div class="rd"><span>${esc(r.name)}</span><span class="lean ${r.lean!=='neutral'&&r.lean!=='unknown'?'hot':''}">${esc(r.lean)}${r.detail?` · ${esc(r.detail)}`:''}</span></div>`).join("")}</div>
        <div class="binding" style="margin-top:10px;color:var(--ink-faint);font-style:italic;font-size:12px">as of ${esc(DESK.crowd.asOf)} — Stein: the trade smart money agrees with is the one to size smaller.</div>
      </div>
    </section>`;

    /* lower row 2: promotion meters + sanctum */
    const r = D.research, dd = D.drawdown;
    html += `<section class="lower">
      <div class="panel">
        <div class="ph"><h2><span class="rune">☷</span>Promotion Sub-gates</h2><span class="tag ${g.promotable?'good':'bad'}">${g.promotable?'promotable':'held'}</span></div>
        <div class="meter-row">${g.subgates.map(subMeter).join("")}</div>
        <div class="binding" style="margin-top:12px;color:var(--ink-faint);font-style:italic;font-size:12px">Scores may be calibrated; the gates are never loosened to force a promotion.</div>
      </div>
      <div class="panel">
        <div class="ph"><h2><span class="rune">◉</span>The Sanctum</h2><span class="tag ${r.mathVerify==='clean'?'good':'warn'}">math ${esc(r.mathVerify)}</span></div>
        <div class="ledger" style="margin-top:2px">
          <div class="row"><span class="k">Drawdown regime</span><span class="v">${esc(dd.regime)} · x${dd.mult.toFixed(1)}</span></div>
          <div class="row"><span class="k">Current / max drawdown</span><span class="v">${dd.current.toFixed(1)}% / ${dd.max.toFixed(1)}%</span></div>
        </div>
        <div class="rstrip" style="margin-top:14px">
          <div class="rcell"><div class="rv">${r.observationsClosed.toLocaleString()}</div><div class="rk">closed observations</div></div>
          <div class="rcell"><div class="rv">${r.scenarioEvidence.toLocaleString()}</div><div class="rk">scenario evidence</div></div>
          <div class="rcell"><div class="rv">${r.chainHistoryHave}/${r.chainHistoryNeed}</div><div class="rk">chain-history days</div></div>
          <div class="rcell"><div class="rv">${r.chainDiffEvents.toLocaleString()}</div><div class="rk">chain-diff events</div></div>
          <div class="rcell"><div class="rv">${r.shadowClosed.toLocaleString()}</div><div class="rk">shadow closed</div></div>
          <div class="rcell clean"><div class="rv">${esc(r.mathVerify)}</div><div class="rk">math verify</div></div>
        </div>
      </div>
    </section>`;

    /* watchfires + focus */
    const torches = D.freshness.map(f=>`<div class="torch ${f.state==='fresh'?'':'stale'}">
      <span class="flame"><i></i></span>
      <span><span class="tn">${esc(f.name)}</span><br><span class="ta">${esc(f.age)}</span>${f.note?` <span class="tnote">· ${esc(f.note)}</span>`:''}</span>
    </div>`).join("");
    html += `<section class="section">
      <h2 class="free">Watchfires · source freshness</h2>
      <div class="torchwrap">${torches}</div>
    </section>`;

    html += `<section class="section">
      <h2 class="free">Paper focus · this cycle</h2>
      <div class="namescroll">${D.names.map(n=>`<span class="nm">${esc(n)}</span>`).join("")}</div>
    </section>`;

    /* next move */
    html += `<div class="nextmove"><span class="mk">Next move</span><span class="mv">${esc(D.nextMove)}</span></div>`;

    /* covenant */
    html += `<div class="covenant">Research-only desk. Read-only artifact. No authority, tickets, risk constants, or broker state are touched here.<br>
      <b>liveTradingAllowed = False · brokerSubmitAllowed = False · BROKER_ADAPTER_MODE = OFF</b></div>`;

    $("#app").innerHTML = html;
    drawReliquary($("#app canvas"), c);
    window.addEventListener("resize", ()=>drawReliquary($("#app canvas"), c), {passive:true});
  }

  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded", build);
  else build();
})();
"""

if __name__ == "__main__":
    raise SystemExit(main())
