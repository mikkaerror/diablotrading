#!/usr/bin/env python3
"""AI / data-center basket — trend-crossing alerts (research-only).

Compares the current trend state of the tracked semiconductor & data-center names
against the last saved state and emails an alert when something actionable changes:

  - a name crosses BELOW its 200-day average  -> trim / exit signal
  - a name crosses ABOVE its 200-day average   -> re-entry signal
  - 50-day crossings                            -> early-warning (secondary)
  - zone flips (into/out of LEADER or BROKEN)

Quotes are provided as a JSON file (the scheduled task fetches them from the
connected market-data MCP and writes them here). Email uses the desk's existing
SMTP config (`.env.smtp` / SMTP_* env vars) — the same one the morning brief uses.

Boundary: research-only, decision-support. It never places a trade; it tells you
what crossed so *you* decide. Not financial advice.
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Any, Optional

from inferno_ai_basket_config import BASKET as CATS
from inferno_ai_basket_config import (
    SYMBOLS, data_contract_trusted, load_data_contract, normalize_symbol,
)
from inferno_io import atomic_write_json

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "data" / "ai_basket_alert_state.json"
ENV_SMTP = ROOT / ".env.smtp"


def _load_env_smtp() -> None:
    """Populate SMTP_* env from .env.smtp if not already set (self-sufficient)."""
    if os.environ.get("SMTP_HOST") or not ENV_SMTP.exists():
        return
    for line in ENV_SMTP.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _expected_symbols(expected_universe: list[str] | None = None) -> list[str]:
    """Return the declared universe without widening it from an input payload."""
    return list(dict.fromkeys(
        normalize_symbol(symbol)
        for symbol in (expected_universe if expected_universe is not None else SYMBOLS)
        if normalize_symbol(symbol)
    ))


def compute_state(
    quotes: list[dict], *, expected_universe: list[str] | None = None
) -> dict[str, dict]:
    """Return declared-symbol trend state from a batch quote list only."""
    expected = set(_expected_symbols(expected_universe))
    state = {}
    for q in quotes:
        if not isinstance(q, dict):
            continue
        sym = normalize_symbol(q.get("symbol"))
        if sym not in expected or sym in state:
            continue
        p = q.get("price"); a50 = q.get("priceAvg50"); a200 = q.get("priceAvg200")
        hi = q.get("yearHigh"); lo = q.get("yearLow")
        if None in (p, a50, a200):
            continue
        above200 = p > a200
        above50 = p > a50
        cross = a50 > a200
        trend = int(above200) + int(above50) + int(cross)
        offHigh = (p / hi - 1) * 100 if hi else None
        if trend == 3 and offHigh is not None and offHigh > -10:
            zone = "LEADER"
        elif trend >= 2 and above50:
            zone = "strong"
        elif trend <= 1 and not above50:
            zone = "BROKEN"
        else:
            zone = "weakening"
        state[sym] = {"above200": above200, "above50": above50,
                      "zone": zone, "price": p, "offHigh": round(offHigh, 1) if offHigh is not None else None}
    return state


def quote_input_quality(
    quotes: list[dict], *, expected_universe: list[str] | None = None
) -> tuple[dict[str, dict], dict[str, Any]]:
    """Assess whether an alert input is complete enough to update saved state."""
    expected = _expected_symbols(expected_universe)
    expected_set = set(expected)
    symbols = [
        normalize_symbol(row.get("symbol"))
        for row in quotes
        if isinstance(row, dict) and normalize_symbol(row.get("symbol"))
    ]
    duplicates = sorted(
        symbol for symbol in set(symbols)
        if symbol in expected_set and symbols.count(symbol) > 1
    )
    state = compute_state(quotes, expected_universe=expected)
    missing = sorted(expected_set - set(state))
    extras = sorted(set(symbols) - expected_set)
    return state, {
        "expectedUniverse": expected,
        "expectedCount": len(expected),
        "coverageCount": len(state),
        "missingSymbols": missing,
        "extraSymbolsIgnored": extras,
        "duplicateSymbols": duplicates,
        "signalsTrusted": bool(expected) and not missing and not duplicates,
    }


def diff_state(prev: dict, cur: dict) -> list[dict]:
    """Return actionable crossings vs the previous state."""
    events = []
    for sym, c in cur.items():
        p = prev.get(sym)
        if not p:
            continue  # new name; no prior to compare
        if p["above200"] and not c["above200"]:
            events.append({"sym": sym, "cat": CATS.get(sym, ""), "kind": "EXIT",
                           "msg": "crossed BELOW its 200-day — trim / exit signal",
                           "price": c["price"]})
        elif not p["above200"] and c["above200"]:
            events.append({"sym": sym, "cat": CATS.get(sym, ""), "kind": "REENTRY",
                           "msg": "crossed ABOVE its 200-day — re-entry signal",
                           "price": c["price"]})
        elif p["above50"] and not c["above50"]:
            events.append({"sym": sym, "cat": CATS.get(sym, ""), "kind": "WARN",
                           "msg": "lost its 50-day — early-warning (still above 200-day)",
                           "price": c["price"]})
        elif not p["above50"] and c["above50"]:
            events.append({"sym": sym, "cat": CATS.get(sym, ""), "kind": "REGAIN",
                           "msg": "reclaimed its 50-day — momentum firming",
                           "price": c["price"]})
    order = {"EXIT": 0, "REENTRY": 1, "WARN": 2, "REGAIN": 3}
    events.sort(key=lambda e: order.get(e["kind"], 9))
    return events


def render(events: list[dict], cur: dict, when: str) -> tuple[str, str]:
    if not events:
        text = f"No trend crossings since last check ({when}). Basket unchanged."
        return text, f"<p>{text}</p>"
    lines = [f"AI / data-center basket — {len(events)} trend crossing(s) as of {when}:", ""]
    for e in events:
        lines.append(f"  [{e['kind']:<7}] {e['sym']:<5} ({e['cat']}) ${e['price']:.2f} — {e['msg']}")
    lines += ["", "Reminder: decision-support, not a trade instruction. You decide.",
              "Rule of thumb: EXIT = trim/raise stop; REENTRY = candidate to add on strength."]
    text = "\n".join(lines)
    rows = "".join(
        f"<tr><td style='padding:4px 8px'><b>{e['kind']}</b></td>"
        f"<td style='padding:4px 8px'>{e['sym']}</td>"
        f"<td style='padding:4px 8px;color:#667'>{e['cat']}</td>"
        f"<td style='padding:4px 8px'>${e['price']:.2f}</td>"
        f"<td style='padding:4px 8px'>{e['msg']}</td></tr>"
        for e in events
    )
    html = (f"<h3>AI / data-center basket — {len(events)} crossing(s), {when}</h3>"
            f"<table style='border-collapse:collapse;font:14px sans-serif'>{rows}</table>"
            "<p style='color:#667;font-size:12px'>Decision-support, not a trade "
            "instruction. Not financial advice.</p>")
    return text, html


def send_email(subject: str, text: str, html: str) -> dict[str, Any]:
    _load_env_smtp()
    host = os.environ.get("SMTP_HOST", "").strip()
    port = int(os.environ.get("SMTP_PORT", "587") or 587)
    sender = os.environ.get("SMTP_FROM", "").strip()
    recipient = os.environ.get("SMTP_TO", "").strip()
    username = os.environ.get("SMTP_USERNAME", "").strip() or sender
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    use_ssl = str(os.environ.get("SMTP_USE_SSL", "false")).lower() in {"1", "true", "yes"}
    if not (host and sender and recipient):
        return {"ok": False, "reason": "SMTP not fully configured"}
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject; msg["From"] = sender; msg["To"] = recipient
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        server = smtplib.SMTP_SSL(host, port, timeout=20) if use_ssl else smtplib.SMTP(host, port, timeout=20)
        if not use_ssl:
            server.starttls()
        if password:
            server.login(username, password)
        server.sendmail(sender, [recipient], msg.as_string())
        server.quit()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "recipient": recipient}


def run(
    quotes_path: str, send: bool = False, *, data_contract: dict[str, Any] | None = None
) -> dict[str, Any]:
    quotes = json.loads(Path(quotes_path).read_text(encoding="utf-8"))
    if isinstance(quotes, dict):
        quotes = quotes.get("data") or quotes.get("quotes") or []
    cur, quality = quote_input_quality(quotes)
    contract = load_data_contract() if data_contract is None else data_contract
    quality["dataContractTrusted"] = data_contract_trusted(contract)
    quality["dataContractVerdict"] = contract.get("verdict") if isinstance(contract, dict) else None
    quality["signalsTrusted"] = bool(
        quality["signalsTrusted"] and quality["dataContractTrusted"]
    )
    prev = {}
    if STATE_FILE.exists():
        prev = json.loads(STATE_FILE.read_text(encoding="utf-8")).get("state", {})
    when = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    if not quality["signalsTrusted"]:
        text = (
            "AI / data-center basket alerts fail closed: declared inputs or their "
            f"canonical trust contract are not ready (coverage {quality['coverageCount']}/"
            f"{quality['expectedCount']}; contract trusted={quality['dataContractTrusted']}). "
            "Saved crossing state was not updated."
        )
        return {
            "events": [], "text": text,
            "emailed": {"ok": False, "reason": "not sent: input fail-closed"},
            "firstRun": not prev, "verdict": "fail-closed", **quality,
        }
    events = diff_state(prev, cur)
    text, html = render(events, cur, when)

    emailed = {"ok": False, "reason": "not sent"}
    if send and events:
        subj = f"[Basket Alert] {len(events)} crossing(s): " + ", ".join(
            f"{e['sym']}·{e['kind']}" for e in events[:4])
        emailed = send_email(subj, text, html)

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        STATE_FILE, {"updatedAt": when, "state": cur, "lastEvents": events}
    )
    return {
        "events": events, "text": text, "emailed": emailed, "firstRun": not prev,
        "verdict": "trusted", **quality,
    }


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quotes", required=True, help="path to batch-quote JSON")
    ap.add_argument("--send", action="store_true", help="email if there are crossings")
    args = ap.parse_args(argv)
    r = run(args.quotes, send=args.send)
    print(r["text"])
    if r["firstRun"]:
        print("\n(First run — baseline saved; crossings will be detected from next run.)")
    if args.send and r["events"]:
        print("\nEmail:", r["emailed"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
