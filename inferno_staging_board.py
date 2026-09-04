#!/usr/bin/env python3
"""Inferno Staging Board — the operator's "what do I do right now to reach 30?" screen.

Research-only. Read-only. promotable = False. Stdlib only (runs anywhere).
It reads existing desk report artifacts and renders one focused board (HTML +
terminal digest) showing: progress to 30, the current chokepoint, the ordered
unblock steps, the blocked candidates and why, and the sims waiting on data.
It NEVER stages, approves, closes, scores, or routes a ticket, and touches no
authority, risk, or broker state.

Sources (best-effort; missing files fall back to the last-known snapshot):
  reports/promotion_gap_latest.txt
  reports/paper_test_director_latest.txt
  reports/paper_blocker_swarm_latest.txt
  reports/fast_paper_cohort_latest.txt
  reports/model_command_center_latest.txt
  reports/paper_evidence_loop_latest.txt

Usage:
  python3 inferno_staging_board.py                 # writes reports/staging_board.html + digest
  python3 inferno_staging_board.py --root .         # repo root (default ".")
  python3 inferno_staging_board.py --quiet          # no terminal digest
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys


def baked_board() -> dict:
    return {
        "snapshot": "2026-08-27",
        "generatedMT": "2026-08-27T09:33:48-06:00",
        "renderedAt": None,
        "gate": {"scored": 1, "target": 30, "gap": 29, "perStrategy": [
            {"name": "CALL_DEBIT_SPREAD", "scored": 1},
            {"name": "LONG_STRADDLE", "scored": 0},
            {"name": "LONG_STRANGLE", "scored": 0},
            {"name": "Straddle", "scored": 0},
            {"name": "Vertical Call", "scored": 0},
        ]},
        "status": {
            "headline": "BLOCKED ON DATA",
            "tone": "blocked",
            "reason": ("Every candidate is blocked upstream of you: the Schwab option "
                       "tape is stale and OAuth needs reauthorization, so nothing can "
                       "price, settle, or score. This is a data dam, not a workflow "
                       "problem — clear it and the queue moves."),
        },
        "funnel": [
            {"stage": "Director candidates", "n": 5, "note": "names in the review queue"},
            {"stage": "Priced / executable", "n": 0, "note": "need fresh option quotes"},
            {"stage": "Operator-routable now", "n": 0, "note": "clean, cap-fitting tickets"},
            {"stage": "Scored toward the gate", "n": 1, "note": "closed + scored paper outcomes"},
        ],
        "dam": {"source": "Schwab options tape", "ageH": 218.0, "oauth": "reauthorization-required",
                "waitingQuotes": True},
        "blocked": [
            {"tkr": "DELL", "strat": "LONG_STRADDLE", "cause": "research-tooling",
             "lanes": ["premium_hurdle", "capital_fit"], "alt": "5-wide debit / 1-wide credit"},
            {"tkr": "AGX", "strat": "LONG_STRADDLE", "cause": "data-refresh",
             "lanes": ["data_freshness", "liquidity", "premium_hurdle", "capital_fit"], "alt": "5-wide debit / 1-wide credit"},
            {"tkr": "IREN", "strat": "LONG_STRADDLE", "cause": "data-refresh",
             "lanes": ["data_freshness", "strike_construction", "premium_hurdle"], "alt": "5-wide debit / 1-wide credit"},
            {"tkr": "CIEN", "strat": "LONG_STRADDLE", "cause": "data-refresh",
             "lanes": ["data_freshness", "liquidity", "premium_hurdle", "capital_fit"], "alt": "5-wide debit / 1-wide credit"},
        ],
        "waitingSims": {
            "open": 5, "maxLoss": 1418.0,
            "note": "research sandbox — promotion-credit OFF, so these do NOT count toward the 30",
            "settleBlock": "current option quotes unavailable",
            "names": [
                {"t": "AVGO", "s": "CALL_DEBIT_SPREAD", "ml": 320.0},
                {"t": "MTN", "s": "CALL_DEBIT_SPREAD", "ml": 270.0},
                {"t": "SMR", "s": "LONG_STRADDLE", "ml": 333.0},
                {"t": "DXC", "s": "CALL_DEBIT_SPREAD", "ml": 40.0},
                {"t": "PL", "s": "LONG_STRADDLE", "ml": 455.0},
            ],
        },
        "steps": [
            {"n": 1, "who": "YOU", "state": "now", "title": "Reauthorize Schwab",
             "detail": "./inferno oauth auth-url → sign in → ./inferno oauth exchange \"<redirect URL>\""},
            {"n": 2, "who": "RUNNER", "state": "next", "title": "Refresh the data",
             "detail": "./run_inferno_refresh.sh  (daily-ops + account sync + full model refresh)"},
            {"n": 3, "who": "DESK", "state": "auto", "title": "Director re-prices; capped variants surface",
             "detail": "the 4 blocked names re-price; cap-fit alternatives (5-wide debit / 1-wide credit) become routable"},
            {"n": 4, "who": "YOU", "state": "goal", "title": "Route → execute → record → close → score",
             "detail": "route clean names to paperMoney, then ./inferno paper-capture to log real fills"},
        ],
        "routableNow": 0,
        "freshness": [
            {"name": "Schwab options tape", "state": "stale", "age": "218h"},
            {"name": "Schwab account sync", "state": "stale", "age": "0.2h", "note": "reauth required"},
            {"name": "Live account sync", "state": "stale", "age": "136h"},
            {"name": "Tracker snapshot", "state": "fresh", "age": "1.2h"},
            {"name": "Paper director", "state": "fresh", "age": "0.4h"},
            {"name": "Doctor", "state": "fresh", "age": "0.0h"},
        ],
    }


# --------------------------- readers (best-effort) ---------------------------
def _read(root, name):
    try:
        with open(os.path.join(root, "reports", name), "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def read_promotion(root, b):
    txt = _read(root, "promotion_gap_latest.txt")
    if not txt:
        return
    m = re.search(r"scored trades:\s*(\d+)/(\d+)\s*\(gap\s*(\d+)\)", txt)
    if m:
        b["gate"]["scored"], b["gate"]["target"], b["gate"]["gap"] = int(m.group(1)), int(m.group(2)), int(m.group(3))
    per = []
    for line in txt.splitlines():
        pm = re.match(r"^-\s*([A-Za-z_ ]+):\s*\d+/7\s*\|\s*scored\s*(\d+)/(\d+)", line)
        if pm:
            per.append({"name": pm.group(1).strip(), "scored": int(pm.group(2))})
    if per:
        b["gate"]["perStrategy"] = per[:6]


def read_director(root, b):
    txt = _read(root, "paper_test_director_latest.txt")
    if not txt:
        return
    def g(pat, default=None):
        m = re.search(pat, txt)
        return int(m.group(1)) if m else default
    cand = g(r"total candidates:\s*(\d+)")
    execu = g(r"executable in paper workflow:\s*(\d+)")
    routable = g(r"operator-routable now:\s*(\d+)")
    scored = g(r"scored tickets:\s*(\d+)")
    if cand is not None:
        b["funnel"][0]["n"] = cand
    if execu is not None:
        b["funnel"][1]["n"] = execu
    if routable is not None:
        b["funnel"][2]["n"] = routable
        b["routableNow"] = routable
    if scored is not None:
        b["funnel"][3]["n"] = scored
    m = re.search(r"Generated:\s*(\S+)", txt)
    if m:
        b["generatedMT"] = m.group(1)
        b["snapshot"] = m.group(1)[:10]


def read_blocker(root, b):
    txt = _read(root, "paper_blocker_swarm_latest.txt")
    if not txt:
        return
    blocked = []
    lines = txt.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^-\s*([A-Z.]{1,6})\s*\|\s*([A-Z_]+)\s*\|\s*([a-z-]+)\s*\|\s*lanes\s*(.+)$", line)
        if not m:
            continue
        lanes = [x.strip() for x in m.group(4).split(",") if x.strip()]
        alt = ""
        for j in range(i + 1, min(i + 4, len(lines))):
            am = re.search(r"cap-fit bounded alternatives:\s*(.+)$", lines[j])
            if am:
                alt = am.group(1).strip().replace(" spread", "")
                break
        blocked.append({"tkr": m.group(1), "strat": m.group(2), "cause": m.group(3),
                        "lanes": lanes, "alt": alt or "5-wide debit / 1-wide credit"})
    if blocked:
        b["blocked"] = blocked[:8]


def read_fast_paper(root, b):
    txt = _read(root, "fast_paper_cohort_latest.txt")
    if not txt:
        return
    ws = b["waitingSims"]
    m = re.search(r"open now:\s*(\d+)", txt)
    if m:
        ws["open"] = int(m.group(1))
    m = re.search(r"open max loss:\s*\$([\d,]+\.?\d*)", txt)
    if m:
        ws["maxLoss"] = float(m.group(1).replace(",", ""))
    names = []
    in_slate = False
    for line in txt.splitlines():
        if line.startswith("Open isolated-simulation slate"):
            in_slate = True
            continue
        if in_slate:
            sm = re.match(r"^-\s*([A-Z.]{1,6})\s*\|\s*([A-Z_]+)\s*\|.*?max loss\s*\$([\d,]+\.?\d*)", line)
            if sm:
                names.append({"t": sm.group(1), "s": sm.group(2), "ml": float(sm.group(3).replace(",", ""))})
            elif line.strip() == "" or not line.startswith("-"):
                if names:
                    break
    if names:
        ws["names"] = names[:8]


def read_command_center(root, b):
    txt = _read(root, "model_command_center_latest.txt")
    if not txt:
        return
    fresh = []
    for line in txt.splitlines():
        fm = re.match(r"^-\s+(.+?):\s+(fresh|stale|attention|unknown)\b.*?\|\s*([\d.]+h)\s*old", line)
        if fm:
            state = "fresh" if fm.group(2) == "fresh" else "stale"
            item = {"name": fm.group(1).strip(), "state": state, "age": fm.group(3)}
            fresh.append(item)
            if "options tape" in item["name"].lower():
                try:
                    b["dam"]["ageH"] = float(item["age"].rstrip("h"))
                except ValueError:
                    pass
    if fresh:
        # keep the stale ones first (they are what matters here), then a few fresh
        stale = [f for f in fresh if f["state"] == "stale"]
        freshi = [f for f in fresh if f["state"] == "fresh"]
        b["freshness"] = (stale + freshi)[:8]
    if re.search(r"reauthorization-required", txt):
        b["dam"]["oauth"] = "reauthorization-required"
    else:
        b["dam"]["oauth"] = "ok"


def build_board(root):
    b = baked_board()
    for reader in (read_promotion, read_director, read_blocker, read_fast_paper, read_command_center):
        try:
            reader(root, b)
        except Exception as exc:
            sys.stderr.write(f"[staging-board] {reader.__name__} skipped: {exc}\n")
    # derive headline/tone from live signals
    routable = b["routableNow"]
    reauth = b["dam"].get("oauth") == "reauthorization-required"
    tape_age = b["dam"].get("ageH") or 0
    stale = tape_age > 24
    if routable > 0:
        b["status"] = {"headline": f"{routable} READY TO ROUTE", "tone": "ready",
                       "reason": "Clean, cap-fitting tickets are available. Route them to paperMoney and record real fills."}
        for i in (0, 1, 2):
            b["steps"][i]["state"] = "done"
        b["steps"][3]["state"] = "now"
    elif reauth:
        b["status"] = {"headline": "REAUTHORIZE SCHWAB", "tone": "blocked",
                       "reason": "The Schwab token needs reauthorization before anything can price. Run ./reauth.sh."}
        b["steps"][0]["state"] = "now"
    elif stale:
        b["status"] = {"headline": "BLOCKED ON DATA", "tone": "blocked",
                       "reason": f"The Schwab option tape is {tape_age:.0f}h stale. Run ./run_inferno_refresh.sh to pull fresh chains."}
        b["steps"][0]["state"] = "done"; b["steps"][1]["state"] = "now"
    else:
        b["status"] = {"headline": "DATA FRESH · RE-PRICING", "tone": "wait",
                       "reason": ("Reauth and refresh are done — the option chains are fresh. The paper director "
                                  "re-prices against them on the next dawn cycle (or run ./inferno sync now). Clean, "
                                  "cap-fitting candidates surface best during market hours.")}
        b["steps"][0]["state"] = "done"; b["steps"][1]["state"] = "done"; b["steps"][2]["state"] = "now"
    b["renderedAt"] = _dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    return b


# --------------------------- terminal digest ---------------------------
def digest(b):
    g = b["gate"]
    out = []
    out.append("")
    out.append("  INFERNO STAGING BOARD  ·  path to 30")
    out.append("  " + "-" * 46)
    out.append(f"  Gate:     {g['scored']}/{g['target']} scored   ({g['gap']} to go)")
    out.append(f"  Status:   {b['status']['headline']}")
    out.append(f"  Routable now: {b['routableNow']}")
    out.append("")
    out.append("  Funnel:")
    for f in b["funnel"]:
        out.append(f"    {f['n']:>3}  {f['stage']}")
    out.append("")
    out.append("  Next steps:")
    for s in b["steps"]:
        mark = {"done": "[x]", "now": "[>]", "next": "[ ]", "auto": "[~]", "goal": "[ ]"}.get(s["state"], "[ ]")
        out.append(f"    {mark} {s['n']}. ({s['who']}) {s['title']}")
        out.append(f"          {s['detail']}")
    out.append("")
    out.append(f"  Data dam: {b['dam']['source']} {b['dam']['ageH']:.0f}h stale · OAuth {b['dam']['oauth']}")
    out.append(f"  Waiting sims: {b['waitingSims']['open']} open (${b['waitingSims']['maxLoss']:,.0f} max loss) — research only, no gate credit")
    out.append("")
    return "\n".join(out)


# --------------------------- render ---------------------------
def render(b, standalone):
    head = HEAD.replace("__CSS__", CSS)
    body = BODY.replace("__BOARD_JSON__", json.dumps(b)).replace("__JS__", JS)
    if standalone:
        return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                + head + "</head><body>" + body + "</body></html>")
    return head + "\n" + body


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render the Inferno Staging Board (read-only).")
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default=None)
    ap.add_argument("--artifact-out", default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    b = build_board(args.root)
    out = args.out or os.path.join(args.root, "reports", "staging_board.html")
    art = args.artifact_out or os.path.join(args.root, "reports", "staging_board.artifact.html")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render(b, True))
    with open(art, "w", encoding="utf-8") as fh:
        fh.write(render(b, False))
    if not args.quiet:
        print(digest(b))
    print(f"[staging-board] {out}  ·  gate {b['gate']['scored']}/{b['gate']['target']}  ·  routable {b['routableNow']}  ·  {b['status']['headline']}")
    return 0


HEAD = """<title>Inferno Staging Board</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;800&family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>__CSS__</style>"""

BODY = """<main id="app" aria-label="Inferno staging board"></main>
<script>
const BOARD = __BOARD_JSON__;
__JS__
</script>"""

CSS = r"""/* Inferno Staging Board — sibling of the Command Cathedral. Single committed
 * hellfire-cathedral world; painted explicitly so it holds on any host ground. */
:root{
  color-scheme: dark;
  --void:#0b0806; --stone:#14100c; --stone-2:#1c1610; --stone-edge:#332619;
  --ink:#e9dcc2; --ink-dim:#a8967a; --ink-faint:#6f6350;
  --ember:#e0a63a; --ember-hot:#f0c25a; --blood:#c0392b; --blood-deep:#7d1f18;
  --sanct:#3fa86e; --warn:#c9932f; --fail:#c0392b; --iron:#7aa6c2; --iron-deep:#2b3a45;
  --shadow:0 18px 46px rgba(0,0,0,.55); --gap:clamp(14px,2.2vw,22px); --maxw:1120px;
  --serif:"EB Garamond","Iowan Old Style",Georgia,serif;
  --display:"Cinzel","Trajan Pro",Georgia,serif;
  --mono:"JetBrains Mono",ui-monospace,Menlo,Consolas,monospace;
}
*{box-sizing:border-box;}
body{ margin:0; min-height:100vh; color:var(--ink); font-family:var(--serif); font-size:17px; line-height:1.5;
  background:
    radial-gradient(1100px 560px at 50% -8%, #241206 0%, rgba(36,18,6,0) 60%),
    radial-gradient(820px 460px at 88% 6%, rgba(192,57,43,.13) 0%, rgba(192,57,43,0) 55%),
    linear-gradient(180deg,#0d0906 0%, var(--void) 46%, #080503 100%); }
#app{ max-width:var(--maxw); margin:0 auto; padding:clamp(20px,4vw,48px) clamp(16px,3.4vw,40px) 72px; }
h1,h2,h3{ font-family:var(--display); font-weight:600; letter-spacing:.02em; margin:0; text-wrap:balance; }
.eyebrow{ font-family:var(--mono); text-transform:uppercase; letter-spacing:.32em; font-size:11px; color:var(--ink-faint); }
.mono{ font-family:var(--mono); font-variant-numeric:tabular-nums; }

/* masthead */
.masthead{ display:flex; flex-wrap:wrap; align-items:center; gap:18px 26px; padding-bottom:20px;
  border-bottom:1px solid var(--stone-edge); margin-bottom:var(--gap); }
.masthead .tw{ flex:1 1 300px; }
.masthead h1{ font-size:clamp(28px,4.4vw,42px); font-weight:800; line-height:1.02;
  background:linear-gradient(180deg,var(--ember-hot),var(--ember) 52%,#b07c26);
  -webkit-background-clip:text; background-clip:text; color:transparent; }
.statuschip{ display:inline-flex; align-items:center; gap:11px; font-family:var(--display); font-size:15px;
  letter-spacing:.05em; padding:10px 18px; border-radius:2px; border:1px solid var(--stone-edge);
  box-shadow:inset 0 0 22px rgba(0,0,0,.4); }
.statuschip .dot{ width:10px; height:10px; border-radius:50%; }
.statuschip.blocked{ color:var(--fail); background:linear-gradient(180deg,rgba(192,57,43,.18),rgba(192,57,43,.05)); }
.statuschip.blocked .dot{ background:var(--fail); box-shadow:0 0 12px var(--fail); animation:pulse 2.6s ease-in-out infinite; }
.statuschip.ready{ color:var(--sanct); background:linear-gradient(180deg,rgba(63,168,110,.16),rgba(63,168,110,.05)); }
.statuschip.ready .dot{ background:var(--sanct); box-shadow:0 0 12px var(--sanct); }
.statuschip.wait{ color:var(--warn); background:linear-gradient(180deg,rgba(201,147,47,.14),rgba(201,147,47,.05)); }
.statuschip.wait .dot{ background:var(--warn); box-shadow:0 0 12px var(--warn); }

/* gate mini */
.gatemini{ text-align:right; min-width:180px; }
.gatemini .big{ font-family:var(--mono); font-weight:600; font-size:30px; color:var(--ember-hot); line-height:1;
  text-shadow:0 0 22px rgba(224,166,58,.22); }
.gatemini .big small{ font-size:14px; color:var(--ink-dim); }
.gatemini .fuel{ height:8px; border-radius:5px; background:#0d0a07; border:1px solid var(--stone-edge); margin-top:8px; overflow:hidden; }
.gatemini .fuel>span{ display:block; height:100%;
  background:linear-gradient(90deg,var(--blood-deep),var(--blood) 40%,var(--ember) 90%,var(--ember-hot));
  box-shadow:0 0 12px rgba(224,166,58,.5); }
.gatemini .gcap{ font-size:11px; color:var(--ink-faint); margin-top:5px; }

/* panels */
.panel{ position:relative; background:linear-gradient(180deg,var(--stone-2),var(--stone));
  border:1px solid var(--stone-edge); border-radius:3px; padding:20px; box-shadow:var(--shadow); }
.panel h2{ font-size:14px; letter-spacing:.18em; text-transform:uppercase; color:var(--ink); font-weight:600; margin-bottom:6px; }
.panel h2 .rune{ color:var(--ember); margin-right:8px; }
.tag{ font-family:var(--mono); font-size:10px; letter-spacing:.12em; text-transform:uppercase; padding:3px 8px;
  border-radius:2px; border:1px solid var(--stone-edge); color:var(--ink-dim); }
.tag.bad{ color:var(--fail); border-color:rgba(192,57,43,.45); background:rgba(192,57,43,.10); }
.tag.good{ color:var(--sanct); border-color:rgba(63,168,110,.4); background:rgba(63,168,110,.08); }

/* THE DAM hero */
.dam{ margin-bottom:var(--gap); }
.dam .reason{ font-size:16px; color:var(--ink); max-width:78ch; margin:2px 0 20px; }
.dam .reason b{ color:var(--ember); }
.path{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }
@media (max-width:820px){ .path{ grid-template-columns:1fr 1fr; } }
@media (max-width:520px){ .path{ grid-template-columns:1fr; } }
.step{ position:relative; padding:15px 15px 15px 16px; border-radius:2px; background:var(--stone);
  border:1px solid var(--stone-edge); overflow:hidden; }
.step::before{ content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--ink-faint); }
.step.now::before{ background:var(--ember); box-shadow:0 0 14px rgba(224,166,58,.6); }
.step.done::before{ background:var(--sanct); }
.step.goal::before{ background:var(--iron); }
.step.now{ border-color:rgba(224,166,58,.4); background:linear-gradient(180deg,rgba(224,166,58,.08),var(--stone)); }
.step .sn{ display:flex; align-items:center; gap:9px; margin-bottom:8px; }
.step .num{ font-family:var(--display); font-size:16px; color:var(--ember); width:24px; height:24px; border-radius:50%;
  border:1px solid var(--stone-edge); display:grid; place-items:center; flex:0 0 auto; }
.step.now .num{ color:var(--ember-hot); border-color:rgba(224,166,58,.5); }
.step.done .num{ color:var(--sanct); border-color:rgba(63,168,110,.5); }
.step .who{ font-family:var(--mono); font-size:9px; letter-spacing:.14em; padding:2px 7px; border-radius:2px;
  border:1px solid var(--stone-edge); color:var(--ink-dim); }
.step.now .who{ color:var(--ember); border-color:rgba(224,166,58,.4); }
.step .who.you{ color:var(--iron); border-color:rgba(122,166,194,.4); }
.step .title{ font-size:14.5px; color:var(--ink); font-family:var(--display); letter-spacing:.01em; }
.step .cmd{ font-family:var(--mono); font-size:11px; color:var(--ink-faint); margin-top:8px; line-height:1.5;
  word-break:break-word; }
.step .cmd b{ color:var(--ember); }

/* main grid */
.grid2{ display:grid; grid-template-columns:1.15fr 1fr; gap:var(--gap); }
@media (max-width:860px){ .grid2{ grid-template-columns:1fr; } }
.section{ margin-top:var(--gap); }

/* funnel */
.funnel{ display:grid; gap:12px; margin-top:6px; }
.frow{ }
.frow .fl{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:5px; }
.frow .fl .fs{ font-size:14px; color:var(--ink-dim); }
.frow .fl .fs .fnote{ color:var(--ink-faint); font-size:12px; font-style:italic; margin-left:6px; }
.frow .fl .fn{ font-family:var(--mono); font-size:20px; color:var(--ink); font-variant-numeric:tabular-nums; }
.fbar{ height:16px; border-radius:3px; background:#0d0a07; border:1px solid var(--stone-edge); overflow:hidden; }
.fbar>span{ display:block; height:100%; min-width:2px;
  background:linear-gradient(90deg,var(--blood-deep),var(--ember)); transition:width .9s cubic-bezier(.2,.7,.2,1); }
.frow.zero .fbar>span{ background:linear-gradient(90deg,#3a2c18,#5a4526); }
.frow.zero .fn{ color:var(--fail); }
.frow.goal .fbar>span{ background:linear-gradient(90deg,#256b46,var(--sanct)); }
.frow.goal .fn{ color:var(--sanct); }
.funnel .drop{ font-size:12.5px; color:var(--ink-faint); font-style:italic; margin-top:4px; }

/* blocked candidates */
.blk{ display:grid; gap:9px; margin-top:6px; }
.bc{ padding:11px 13px; border-radius:2px; background:var(--stone); border:1px solid var(--stone-edge); }
.bc .top{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.bc .tkr{ font-family:var(--display); font-size:16px; color:var(--ember); letter-spacing:.04em; }
.bc .strat{ font-family:var(--mono); font-size:10px; color:var(--ink-dim); }
.bc .cause{ margin-left:auto; font-family:var(--mono); font-size:9.5px; letter-spacing:.1em; text-transform:uppercase;
  color:var(--warn); border:1px solid rgba(201,147,47,.35); padding:2px 7px; border-radius:2px; }
.bc .lanes{ margin-top:8px; display:flex; flex-wrap:wrap; gap:5px; }
.bc .lane{ font-family:var(--mono); font-size:9.5px; color:var(--fail); border:1px solid rgba(192,57,43,.3);
  background:rgba(192,57,43,.07); padding:2px 6px; border-radius:2px; }
.bc .alt{ margin-top:8px; font-size:12.5px; color:var(--ink-dim); }
.bc .alt b{ color:var(--sanct); font-family:var(--mono); font-size:11.5px; }

/* waiting sims */
.sims{ display:grid; gap:7px; margin-top:6px; }
.sim{ display:flex; align-items:center; gap:10px; padding:8px 11px; border-radius:2px; background:var(--stone);
  border:1px solid var(--stone-edge); }
.sim .t{ font-family:var(--display); font-size:14px; color:var(--ink); width:52px; }
.sim .s{ font-family:var(--mono); font-size:10px; color:var(--ink-faint); flex:1 1 auto; }
.sim .ml{ font-family:var(--mono); font-size:12px; color:var(--ink-dim); }
.simnote{ margin-top:10px; font-size:12px; color:var(--warn); font-style:italic; border-top:1px dashed var(--stone-edge); padding-top:9px; }
.simhead{ display:flex; justify-content:space-between; align-items:baseline; }
.simhead .tot{ font-family:var(--mono); font-size:12px; color:var(--ink-dim); }

/* per-strategy + torches */
.chips{ display:flex; flex-wrap:wrap; gap:7px; margin-top:6px; }
.chip{ font-family:var(--mono); font-size:11px; letter-spacing:.04em; padding:4px 10px; border-radius:2px;
  border:1px solid var(--stone-edge); color:var(--ink-faint); }
.chip.lit{ color:var(--ember); border-color:rgba(224,166,58,.4); background:rgba(224,166,58,.07); }
.torchwrap{ display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:10px; margin-top:6px; }
.torch{ display:flex; align-items:center; gap:10px; padding:9px 11px; border-radius:2px; background:var(--stone); border:1px solid var(--stone-edge); }
.flame{ width:14px; height:22px; position:relative; flex:0 0 auto; }
.flame i{ position:absolute; left:50%; bottom:0; transform:translateX(-50%); width:10px; height:16px;
  border-radius:50% 50% 48% 52%/62% 62% 38% 38%;
  background:radial-gradient(circle at 50% 78%,var(--ember-hot),var(--blood) 74%,transparent 78%);
  box-shadow:0 0 10px rgba(224,166,58,.5); animation:flick 1.6s ease-in-out infinite; }
.torch.stale .flame i{ background:radial-gradient(circle at 50% 82%,#6a5738,#3a2c18 78%,transparent 82%);
  box-shadow:0 0 4px rgba(90,70,40,.4); opacity:.7; animation:gutter 2.6s ease-in-out infinite; }
.torch .tn{ font-size:12.5px; color:var(--ink); }
.torch .ta{ font-family:var(--mono); font-size:11px; color:var(--sanct); }
.torch.stale .ta{ color:var(--warn); }
.torch .tnote{ font-family:var(--mono); font-size:9px; color:var(--ink-faint); }

.h2free{ font-size:13px; letter-spacing:.2em; text-transform:uppercase; color:var(--ink-dim); margin-bottom:12px;
  display:flex; align-items:center; gap:10px; font-family:var(--display); }
.h2free::after{ content:""; flex:1 1 auto; height:1px; background:linear-gradient(90deg,var(--stone-edge),transparent); }
.covenant{ margin-top:26px; text-align:center; color:var(--ink-faint); font-size:12px; font-style:italic;
  border-top:1px solid var(--stone-edge); padding-top:16px; }
.covenant b{ color:var(--iron); font-style:normal; font-family:var(--mono); font-size:10.5px; letter-spacing:.08em; }
.stamp{ font-family:var(--mono); font-size:10.5px; color:var(--ink-faint); }

@keyframes pulse{ 0%,100%{opacity:1;} 50%{opacity:.35;} }
@keyframes flick{ 0%,100%{transform:translateX(-50%) scaleY(1) rotate(-1deg);} 50%{transform:translateX(-50%) scaleY(1.14) rotate(1.5deg);} }
@keyframes gutter{ 0%,100%{transform:translateX(-50%) scaleY(.9); opacity:.6;} 50%{transform:translateX(-50%) scaleY(1.05); opacity:.85;} }
:focus-visible{ outline:2px solid var(--ember); outline-offset:2px; }
@media (prefers-reduced-motion:reduce){ *{ animation:none!important; transition:none!important; } }
"""
JS = r"""/* Inferno Staging Board — render the path to 30 from BOARD. */
(function(){
  "use strict";
  const $ = (s,r)=>(r||document).querySelector(s);
  const esc = s => String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  const money = n => "$"+Number(n||0).toLocaleString("en-US",{maximumFractionDigits:0});

  function build(){
    const B = BOARD, g = B.gate;
    let h = "";

    /* masthead */
    h += `<header class="masthead">
      <div class="tw">
        <div class="eyebrow">Inferno · path to 30</div>
        <h1>Staging Board</h1>
      </div>
      <div class="statuschip ${esc(B.status.tone)}"><span class="dot"></span>${esc(B.status.headline)}</div>
      <div class="gatemini">
        <div class="big">${g.scored}<small>/${g.target}</small></div>
        <div class="fuel"><span style="width:${Math.round(g.scored/g.target*100)}%"></span></div>
        <div class="gcap">${g.gap} closed scored outcomes to go</div>
      </div>
    </header>`;

    /* THE DAM hero */
    const stepCards = B.steps.map(s=>{
      const youCls = s.who==="YOU" ? "you" : "";
      const cmd = esc(s.detail).replace(/(\.\/[\w.-]+|`[^`]+`)/g, "<b>$1</b>");
      return `<div class="step ${esc(s.state)}">
        <div class="sn"><span class="num">${s.n}</span><span class="who ${youCls}">${esc(s.who)}</span></div>
        <div class="title">${esc(s.title)}</div>
        <div class="cmd">${cmd}</div>
      </div>`;
    }).join("");
    h += `<div class="panel dam">
      <h2><span class="rune">⛧</span>The dam · why you're stuck &amp; how it clears</h2>
      <p class="reason">${esc(B.status.reason)}</p>
      <div class="path">${stepCards}</div>
    </div>`;

    /* funnel + waiting sims */
    const maxN = Math.max(...B.funnel.map(f=>f.n), 1);
    const funnelRows = B.funnel.map((f,i)=>{
      const zero = f.n===0, goal = i===B.funnel.length-1;
      const cls = goal ? "goal" : (zero ? "zero" : "");
      return `<div class="frow ${cls}">
        <div class="fl"><span class="fs">${esc(f.stage)}<span class="fnote">${esc(f.note||"")}</span></span><span class="fn">${f.n}</span></div>
        <div class="fbar"><span style="width:${Math.max(2, Math.round(f.n/maxN*100))}%"></span></div>
      </div>`;
    }).join("");
    const ws = B.waitingSims;
    const simRows = ws.names.map(n=>`<div class="sim"><span class="t">${esc(n.t)}</span><span class="s">${esc(n.s)}</span><span class="ml">${money(n.ml)} max loss</span></div>`).join("");
    h += `<section class="grid2">
      <div class="panel">
        <h2><span class="rune">▼</span>The funnel · where names die</h2>
        ${funnelRows}
        <div class="drop">The middle of this funnel fills only when the director re-prices fresh chains into clean, cap-fitting tickets. Fresh data is the prerequisite, not the finish line.</div>
      </div>
      <div class="panel">
        <div class="simhead"><h2><span class="rune">⧗</span>Sims waiting on quotes</h2><span class="tot">${ws.open} open · ${money(ws.maxLoss)}</span></div>
        <div class="sims">${simRows}</div>
        <div class="simnote">${esc(ws.note)}. They can't settle right now — <span class="mono">${esc(ws.settleBlock)}</span>.</div>
      </div>
    </section>`;

    /* blocked candidates */
    const bcCards = B.blocked.map(b=>`<div class="bc">
      <div class="top"><span class="tkr">${esc(b.tkr)}</span><span class="strat">${esc(b.strat)}</span><span class="cause">${esc(b.cause)}</span></div>
      <div class="lanes">${b.lanes.map(l=>`<span class="lane">${esc(l)}</span>`).join("")}</div>
      <div class="alt">cap-fit route → <b>${esc(b.alt)}</b></div>
    </div>`).join("");
    h += `<section class="section">
      <h2 class="h2free">Blocked candidates · all fixable by the refresh</h2>
      <div class="blk" style="grid-template-columns:repeat(auto-fill,minmax(240px,1fr));display:grid">${bcCards}</div>
    </section>`;

    /* per-strategy + torches */
    const chips = g.perStrategy.map(p=>`<span class="chip ${p.scored>0?'lit':''}">${esc(p.name)} ${p.scored}/30</span>`).join("");
    const torches = B.freshness.map(f=>`<div class="torch ${f.state==='fresh'?'':'stale'}">
      <span class="flame"><i></i></span>
      <span><span class="tn">${esc(f.name)}</span><br><span class="ta">${esc(f.age)}</span>${f.note?` <span class="tnote">· ${esc(f.note)}</span>`:''}</span>
    </div>`).join("");
    h += `<section class="grid2">
      <div class="panel"><h2><span class="rune">☷</span>Gate progress by strategy</h2><div class="chips">${chips}</div>
        <div class="drop" style="margin-top:12px">Each strategy family clears its own 30. Spread the closed outcomes; don't pile them all in one family.</div></div>
      <div class="panel"><h2><span class="rune">✶</span>Watchfires</h2><div class="torchwrap">${torches}</div></div>
    </section>`;

    /* covenant */
    h += `<div class="covenant">Read-only board. It stages nothing, scores nothing, and touches no authority, risk, or broker state.<br>
      <b>research-only · promotion moves only on closed scored paper outcomes</b><br>
      <span class="stamp">desk read ${esc((B.generatedMT||'').replace('T',' ').slice(0,16))} · rendered ${esc(B.renderedAt||'')}</span></div>`;

    $("#app").innerHTML = h;
  }

  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded", build);
  else build();
})();
"""

if __name__ == "__main__":
    raise SystemExit(main())
