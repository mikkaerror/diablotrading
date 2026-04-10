from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import gspread
import numpy as np
import pandas as pd
import yfinance as yf
from oauth2client.service_account import ServiceAccountCredentials

from inferno_config import (
    AUTOMATION_ALLOWED_WEEKDAYS,
    AUTOMATION_WINDOW_END,
    AUTOMATION_WINDOW_START,
    DEFAULT_SHEET_NAME,
    REVIEW_QUEUE_LIMIT,
    ROOT,
    SCORE_FORMULA_COLUMNS,
    UPDATER_LABEL,
    UPDATER_SCRIPTS,
    default_backtest_root,
    in_time_window,
    local_now,
)
from server import (
    APPROVAL_QUEUE_FILE,
    BRIEF_TEXT_FILE,
    HTML_BRIEF_FILE,
    LOG_FILE,
    OPS_STATUS_FILE,
    PAPER_JOURNAL_FILE,
    SNAPSHOT_FILE,
    TICKETS_TEXT_FILE,
    ensure_dirs,
    html_from_payload,
    load_json_file,
    send_email,
    smtp_configured,
)


DEFAULT_BACKTEST_ROOT = default_backtest_root()
CONVICTION_CONFIG = {
    "min_readiness": 72,
    "min_confidence": 2,
    "max_days_until_earnings": 21,
    "require_trigger": True,
    "banned_setups": {"Avoid"},
}


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key] = value


def already_sent_today() -> bool:
    ops_status = load_json_file(OPS_STATUS_FILE) or {}
    generated_at = str(ops_status.get("generatedAt", ""))
    today = local_now().date().isoformat()
    return generated_at.startswith(today) and ops_status.get("ok") and ops_status.get("emailSent")


def automation_skip_reason(window_start: str, window_end: str) -> str | None:
    now = local_now()
    if now.weekday() not in AUTOMATION_ALLOWED_WEEKDAYS:
        return "Skipping automated dawn cycle: Saturday automation is disabled."
    if not in_time_window(now, window_start, window_end):
        return (
            "Skipping automated dawn cycle: "
            f"{now.strftime('%H:%M')} is outside the {window_start}-{window_end} mountain-time window."
        )
    if already_sent_today():
        return "Skipping automated dawn cycle: today's market snapshot already sent successfully."
    return None


def clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def score_to_percent(value: float, ceiling: float = 2.5) -> float:
    return clamp((value / ceiling) * 100, 0, 100)


def setup_weight(setup_rec: str) -> int:
    lowered = str(setup_rec).lower()
    if "vertical" in lowered:
        return 13
    if "straddle" in lowered:
        return 11
    if "condor" in lowered:
        return 8
    if "avoid" in lowered:
        return -10
    return 0


def urgency_weight(urgency: str) -> int:
    lowered = str(urgency).lower()
    if "urgent" in lowered:
        return 18
    if "watch" in lowered:
        return 8
    if "avoid" in lowered:
        return -16
    return 0


def readiness_label(readiness: float) -> str:
    if readiness >= 72:
        return "Ready"
    if readiness >= 48:
        return "Watch"
    return "Avoid"


def number_or_none(value: Any) -> float | None:
    cleaned = str(value or "").replace("$", "").replace(",", "").strip()
    if not cleaned or cleaned.upper() == "N/A" or cleaned == "#N/A":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "2026-05-01"

    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return "2026-05-01"


def normalize_trigger(value: Any) -> bool:
    text = str(value or "").strip()
    lowered = text.lower()
    return text == "1" or "true" in lowered or "yes" in lowered or "✅" in text


def enrich_row(row: dict[str, Any]) -> dict[str, Any]:
    timing_score = 16 if row["daysUntilEarnings"] <= 7 else 20 if row["daysUntilEarnings"] <= 21 else 17 if row["daysUntilEarnings"] <= 35 else 9
    trigger_score = 14 if row["signalTrigger"] else 0
    confidence_score = (row["confidence"] / 3) * 24
    iv_momentum_score = clamp(row["ivRankChange"] * 65, -8, 10)
    volatility_score = clamp((row["ivRank"] / 50) * 12 + (row["atrPercent"] / 10) * 10, 0, 20)
    score_blend = (
        score_to_percent(row["readyScore"]) * 0.28
        + score_to_percent(row["squeezeScore"]) * 0.18
        + score_to_percent(row["momentumScore"]) * 0.18
        + score_to_percent(row["valueScore"]) * 0.12
    )
    readiness = clamp(
        timing_score
        + trigger_score
        + confidence_score
        + iv_momentum_score
        + volatility_score
        + setup_weight(row["setupRec"])
        + urgency_weight(row["urgency"])
        + score_blend * 0.32,
        8,
        99,
    )

    row["readiness"] = int(round(readiness))
    row["status"] = readiness_label(readiness)
    return row


def gate_checks(row: dict[str, Any]) -> dict[str, bool]:
    return {
        "readiness": row["readiness"] >= CONVICTION_CONFIG["min_readiness"],
        "confidence": row["confidence"] >= CONVICTION_CONFIG["min_confidence"],
        "timing": row["daysUntilEarnings"] <= CONVICTION_CONFIG["max_days_until_earnings"],
        "trigger": row["signalTrigger"] if CONVICTION_CONFIG["require_trigger"] else True,
        "setup": row["setupRec"] not in CONVICTION_CONFIG["banned_setups"],
    }


def gate_failures(row: dict[str, Any]) -> list[str]:
    messages = {
        "readiness": "readiness below threshold",
        "confidence": "confidence too low",
        "timing": "too far from earnings",
        "trigger": "trigger not live",
        "setup": "setup blocked",
    }
    return [messages[key] for key, passed in gate_checks(row).items() if not passed]


def get_eligible_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if not gate_failures(row)]


def select_review_candidates(rows: list[dict[str, Any]], limit: int = REVIEW_QUEUE_LIMIT) -> list[dict[str, Any]]:
    return get_eligible_candidates(rows)[:limit]


def build_narrative(row: dict[str, Any]) -> str:
    if row["daysUntilEarnings"] <= 10:
        timing = "The catalyst window is almost here, so precision matters more than panic and greed."
    elif row["daysUntilEarnings"] <= 30:
        timing = "The event sits in the strike zone, where disciplined names start separating from the pretenders."
    else:
        timing = "This one is still earlier in the cycle, so it feels more like stalking prey than swinging the blade."

    signal = (
        "Your signal trigger is already active, which means the market has stopped whispering and started confessing."
        if row["signalTrigger"]
        else "The trigger has not fired yet, so this stays chained until price action proves it belongs in the arena."
    )
    setup = (
        "The setup recommendation is defensive, so treat the name like a cursed relic: study it, but do not worship it."
        if row["setupRec"] == "Avoid"
        else f"The current setup bias favors {row['setupRec'].lower()} structures."
    )
    return f"{timing} {signal} {setup}"


def build_morning_brief(rows: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    eligible = get_eligible_candidates(rows)
    headline = (
        f"{eligible[0]['ticker']} leads the board at {eligible[0]['readiness']}% readiness."
        if eligible
        else "No full-conviction names passed every gate today."
    )

    lines = [
        "Morning Brief",
        headline,
        "",
        f"Total tracked: {len(rows)}",
        f"Eligible now: {len(eligible)}",
        f"Triggered names: {sum(1 for row in rows if row['signalTrigger'])}",
        "",
        "Top recommendations:",
    ]

    recommended = eligible[:REVIEW_QUEUE_LIMIT] if eligible else rows[:3]
    eligible_tickers = {row["ticker"] for row in eligible}
    for index, row in enumerate(recommended, start=1):
        failure_text = "all gates clear" if row["ticker"] in eligible_tickers else ", ".join(gate_failures(row))
        lines.append(
            f"{index}. {row['ticker']} | {row['setupRec']} | {row['readiness']}% | {row['daysUntilEarnings']}d | "
            f"{'trigger live' if row['signalTrigger'] else 'waiting'} | {failure_text}"
        )

    lines.extend(["", "Prime thesis:"])
    for row in recommended[:3]:
        lines.append(f"- {row['ticker']}: {build_narrative(row)}")

    return "\n".join(lines), eligible, recommended


def build_paper_tickets(rows: list[dict[str, Any]]) -> str:
    picks = select_review_candidates(rows)
    if not picks:
        return "No paper tickets generated. No names passed every conviction gate."

    blocks = []
    for index, row in enumerate(picks, start=1):
        blocks.append(
            "\n".join(
                [
                    f"Ticket {index}: {row['ticker']}",
                    f"Setup: {row['setupRec']}",
                    f"Readiness: {row['readiness']}%",
                    f"Timing: {row['daysUntilEarnings']} days to earnings",
                    f"Trigger: {'LIVE' if row['signalTrigger'] else 'WAIT'}",
                    f"Primary route: {row['rec1']}",
                    f"Secondary route: {row['rec2']}",
                    "Risk note: paper trade only until live execution rules are proven.",
                ]
            )
        )
    return "\n\n".join(blocks)


def make_gspread_client(backtest_root: Path) -> gspread.Client:
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_path = backtest_root / "gcred.json"
    creds = ServiceAccountCredentials.from_json_keyfile_name(str(creds_path), scope)
    return gspread.authorize(creds)


def get_sheet(backtest_root: Path, sheet_name: str):
    client = make_gspread_client(backtest_root)
    return client.open(sheet_name).sheet1


def calculate_20day_atr_fixed(ticker: str) -> str | float:
    try:
        df = yf.Ticker(ticker).history(period="2mo", interval="1d").dropna()
        if len(df) < 22:
            return "N/A"

        df["TR"] = np.maximum(
            df["High"] - df["Low"],
            np.maximum(abs(df["High"] - df["Close"].shift()), abs(df["Low"] - df["Close"].shift())),
        )
        df["ATR_20"] = df["TR"].rolling(window=20).mean()
        latest = df["ATR_20"].iloc[-1]
        return round(float(latest), 4) if pd.notna(latest) else "N/A"
    except Exception:
        return "N/A"


def repair_r20_atr_if_needed(backtest_root: Path, sheet_name: str) -> dict[str, Any]:
    sheet = get_sheet(backtest_root, sheet_name)
    rows = sheet.get_all_values()
    if len(rows) < 2:
        return {"checked": True, "repaired": False, "reason": "sheet empty"}

    tickers: list[str] = []
    current_values: list[str] = []
    for cells in rows[1:]:
        ticker = cells[0].strip().upper() if len(cells) > 0 else ""
        if not ticker:
            continue
        tickers.append(ticker)
        current_values.append(cells[17].strip() if len(cells) > 17 else "")

    if not tickers:
        return {"checked": True, "repaired": False, "reason": "no tickers"}

    na_like = sum(1 for value in current_values if not value or value.upper() == "N/A")
    if na_like / len(current_values) < 0.8:
        return {"checked": True, "repaired": False, "reason": "column R looks populated"}

    repaired_values = [[calculate_20day_atr_fixed(ticker)] for ticker in tickers]
    sheet.update(f"R2:R{len(tickers) + 1}", repaired_values)
    repaired_na = sum(1 for value in repaired_values if value[0] == "N/A")
    return {
        "checked": True,
        "repaired": True,
        "reason": "column R was mostly N/A after external job",
        "rows": len(tickers),
        "naCountAfterRepair": repaired_na,
    }


def score_formula_row(row_number: int) -> list[str]:
    return [
        f'=IF($A{row_number}="","", N($O{row_number}) * (N($C{row_number})/100) * (ABS(N($Q{row_number}))+1))',
        f'=IF($A{row_number}="","", MAX(0, N($P{row_number})))',
        f'=IF($A{row_number}="","", MAX(0, -N($Q{row_number})))',
        f'=IF($A{row_number}="","", IF(AND($K{row_number}="✅",$I{row_number}<>"Avoid"), N($U{row_number}), 0))',
        f'=IF($A{row_number}="","", N($U{row_number})+N($V{row_number})+N($W{row_number})+N($X{row_number}))',
    ]


def sync_score_formulas(backtest_root: Path, sheet_name: str) -> dict[str, Any]:
    sheet = get_sheet(backtest_root, sheet_name)
    tickers = [ticker.strip().upper() for ticker in sheet.col_values(1)[1:] if ticker.strip()]
    if not tickers:
        return {"checked": True, "repaired": False, "reason": "no tickers"}

    last_row = len(tickers) + 1
    formula_rows = [score_formula_row(row_number) for row_number in range(2, last_row + 1)]
    sheet.update(
        f"{SCORE_FORMULA_COLUMNS[0]}2:{SCORE_FORMULA_COLUMNS[-1]}{last_row}",
        formula_rows,
        value_input_option="USER_ENTERED",
    )
    return {
        "checked": True,
        "repaired": True,
        "reason": "score formulas synced",
        "rows": len(tickers),
        "columns": list(SCORE_FORMULA_COLUMNS),
    }


def read_sheet_rows(backtest_root: Path, sheet_name: str) -> list[dict[str, Any]]:
    sheet = get_sheet(backtest_root, sheet_name)
    raw_rows = sheet.get_all_values()
    if len(raw_rows) < 2:
        return []

    headers = [header.strip() for header in raw_rows[0]]
    index_map = {header: idx for idx, header in enumerate(headers)}

    def read(cells: list[str], header: str) -> str:
        idx = index_map.get(header)
        if idx is None or idx >= len(cells):
            return ""
        return cells[idx]

    rows: list[dict[str, Any]] = []
    for cells in raw_rows[1:]:
        ticker = read(cells, "Ticker").strip().upper()
        if not ticker:
            continue

        row = enrich_row(
            {
                "ticker": ticker,
                "atrPercent": number_or_none(read(cells, "ATR%")) or 0.0,
                "ivRank": number_or_none(read(cells, "IV Rank")) or 0.0,
                "nextEarnings": parse_date(read(cells, "Next Earnings")),
                "price": number_or_none(read(cells, "Price")) or 0.0,
                "eps": number_or_none(read(cells, "EPS")) or 0.0,
                "pe": number_or_none(read(cells, "PE")),
                "daysUntilEarnings": int(number_or_none(read(cells, "Days until earnings")) or 0),
                "setupRec": read(cells, "Setup Rec").strip() or "Watchlist",
                "urgency": read(cells, '"Urgency"').strip() or "Watchlist",
                "signalTrigger": normalize_trigger(read(cells, "Signal Trigger")),
                "confidence": int(number_or_none(read(cells, "Confidence (3 MAX)")) or 0),
                "ivRankChange": number_or_none(read(cells, "IV Rank Change (5-day delta)")) or 0.0,
                "atrZScore": number_or_none(read(cells, "ATR% Z-Score")) or 0.0,
                "atr20Day": number_or_none(read(cells, "20 Day ATR")),
                "rec1": read(cells, "REC 1-13").strip() or "N/A",
                "rec2": read(cells, "Rec2").strip() or "N/A",
                "valueScore": number_or_none(read(cells, "Value Score")) or 0.0,
                "momentumScore": number_or_none(read(cells, "Momentum Score")) or 0.0,
                "squeezeScore": number_or_none(read(cells, "Squeeze Score")) or 0.0,
                "readyScore": number_or_none(read(cells, "Ready Score")) or 0.0,
            }
        )
        rows.append(row)

    rows.sort(key=lambda item: (-item["readiness"], item["daysUntilEarnings"]))
    return rows


def run_updaters(backtest_root: Path, python_bin: Path) -> list[dict[str, Any]]:
    results = []
    for script_name in UPDATER_SCRIPTS:
        command = [str(python_bin), script_name]
        completed = subprocess.run(
            command,
            cwd=backtest_root,
            capture_output=True,
            text=True,
        )
        results.append(
            {
                "script": script_name,
                "ok": completed.returncode == 0,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
                "returncode": completed.returncode,
            }
        )
        if completed.returncode != 0:
            raise RuntimeError(f"{script_name} failed with exit code {completed.returncode}")
    return results


def write_payload(payload: dict[str, Any]) -> None:
    ensure_dirs()
    snapshot_text = json.dumps(payload, indent=2)
    brief_text = payload["brief"]
    tickets_text = payload["tickets"]
    html_text = html_from_payload(payload)

    SNAPSHOT_FILE.write_text(snapshot_text, encoding="utf-8")
    BRIEF_TEXT_FILE.write_text(brief_text, encoding="utf-8")
    TICKETS_TEXT_FILE.write_text(tickets_text, encoding="utf-8")
    HTML_BRIEF_FILE.write_text(html_text, encoding="utf-8")


def write_ops_status(payload: dict[str, Any], updater_results: list[dict[str, Any]], email_sent: bool) -> None:
    repair_result = next((result for result in updater_results if result["script"] == "R-20DayATR self-heal"), None)
    formula_result = next((result for result in updater_results if result["script"] == "U:Y score sync"), None)
    review_tickers = payload["reviewQueueTickers"]
    journal_count = len(review_tickers)
    OPS_STATUS_FILE.write_text(
        json.dumps(
            {
                "generatedAt": payload["generatedAt"],
                "ok": True,
                "sourceLabel": payload["sourceLabel"],
                "emailSent": email_sent,
                "trackedCount": len(payload["rows"]),
                "eligibleCount": len(payload["eligibleTickers"]),
                "topTickers": payload["eligibleTickers"][:5],
                "reviewQueueTickers": review_tickers,
                "paperTradeCount": journal_count,
                "approvalQueueCount": journal_count,
                "updaterScripts": [{"script": result["script"], "ok": result["ok"]} for result in updater_results],
                "repair": json.loads(repair_result["stdout"]) if repair_result and repair_result.get("stdout") else None,
                "formulaSync": json.loads(formula_result["stdout"]) if formula_result and formula_result.get("stdout") else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def build_paper_trade_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows_by_ticker = {row["ticker"]: row for row in payload["rows"]}
    entries = []
    for index, ticker in enumerate(payload["reviewQueueTickers"], start=1):
        row = rows_by_ticker.get(ticker)
        if not row:
            continue
        entries.append(
            {
                "generatedAt": payload["generatedAt"],
                "tradeDate": payload["generatedAt"][:10],
                "rank": index,
                "ticker": row["ticker"],
                "setupRec": row["setupRec"],
                "readiness": row["readiness"],
                "daysUntilEarnings": row["daysUntilEarnings"],
                "signalTrigger": row["signalTrigger"],
                "rec1": row["rec1"],
                "rec2": row["rec2"],
                "price": row["price"],
                "valueScore": row["valueScore"],
                "momentumScore": row["momentumScore"],
                "squeezeScore": row["squeezeScore"],
                "readyScore": row["readyScore"],
                "status": "paper-open",
            }
        )
    return entries


def append_paper_trade_journal(entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    with PAPER_JOURNAL_FILE.open("a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")


def write_approval_queue(payload: dict[str, Any]) -> None:
    rows_by_ticker = {row["ticker"]: row for row in payload["rows"]}
    queue_items = []
    for ticker in payload["reviewQueueTickers"]:
        row = rows_by_ticker.get(ticker)
        if not row:
            continue
        queue_items.append(
            {
                "ticker": row["ticker"],
                "setupRec": row["setupRec"],
                "readiness": row["readiness"],
                "daysUntilEarnings": row["daysUntilEarnings"],
                "signalTrigger": row["signalTrigger"],
                "primaryRoute": row["rec1"],
                "secondaryRoute": row["rec2"],
                "approvalStatus": "pending",
                "generatedAt": payload["generatedAt"],
            }
        )
    APPROVAL_QUEUE_FILE.write_text(
        json.dumps(
            {
                "generatedAt": payload["generatedAt"],
                "count": len(queue_items),
                "items": queue_items,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def append_log(entry: dict[str, Any]) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(entry) + "\n")


def summarize(results: list[dict[str, Any]], payload: dict[str, Any], email_sent: bool) -> str:
    lines = [
        "Morning inferno pipeline complete.",
        f"Rows scored: {len(payload['rows'])}",
        f"Eligible names: {len(payload['eligibleTickers'])}",
        f"Top names: {', '.join(payload['eligibleTickers'][:5]) if payload['eligibleTickers'] else 'none'}",
        f"Email sent: {'yes' if email_sent else 'no'}",
    ]
    if results:
        lines.append("")
        lines.append(f"{UPDATER_LABEL} results:")
        for result in results:
            lines.append(f"- {result['script']}: {'ok' if result['ok'] else 'failed'}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the BC/P/Q/R PyCharm jobs, score the tracker, and send the morning brief.")
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT), help="Path to the Backtest project")
    parser.add_argument("--python-bin", default="", help="Python interpreter to use for the BC/P/Q/R PyCharm jobs")
    parser.add_argument("--sheet-name", default=DEFAULT_SHEET_NAME, help="Google Sheet name")
    parser.add_argument("--skip-updates", action="store_true", help="Do not run the BC/P/Q/R PyCharm jobs")
    parser.add_argument("--skip-email", action="store_true", help="Build the snapshot but do not send email")
    parser.add_argument(
        "--automation",
        action="store_true",
        help="Run only during the configured automation window and skip duplicate sends for the same day.",
    )
    parser.add_argument(
        "--quiet-skip",
        action="store_true",
        help="Exit silently when automation mode decides the run should be skipped.",
    )
    parser.add_argument("--window-start", default=AUTOMATION_WINDOW_START, help="Local HH:MM start for automation mode")
    parser.add_argument("--window-end", default=AUTOMATION_WINDOW_END, help="Local HH:MM end for automation mode")
    return parser.parse_args()


def main() -> int:
    load_env_file(ROOT / ".env.smtp")
    args = parse_args()
    backtest_root = Path(args.backtest_root).expanduser().resolve()
    python_bin = Path(args.python_bin).expanduser().resolve() if args.python_bin else backtest_root / "venv" / "bin" / "python"

    if args.automation:
        try:
            skip_reason = automation_skip_reason(args.window_start, args.window_end)
        except ValueError as exc:
            print(f"Automation window is invalid: {exc}", file=sys.stderr)
            return 1
        if skip_reason:
            if not args.quiet_skip:
                print(skip_reason)
            return 0

    if not backtest_root.exists():
        print(f"Backtest root not found: {backtest_root}", file=sys.stderr)
        return 1

    if not python_bin.exists():
        print(f"Python interpreter not found: {python_bin}", file=sys.stderr)
        return 1

    ensure_dirs()
    updater_results: list[dict[str, Any]] = []

    try:
        if not args.skip_updates:
            updater_results = run_updaters(backtest_root, python_bin)
            repair_summary = repair_r20_atr_if_needed(backtest_root, args.sheet_name)
            updater_results.append(
                {
                    "script": "R-20DayATR self-heal",
                    "ok": True,
                    "stdout": json.dumps(repair_summary),
                    "stderr": "",
                    "returncode": 0,
                }
            )
        formula_sync_summary = sync_score_formulas(backtest_root, args.sheet_name)
        updater_results.append(
            {
                "script": "U:Y score sync",
                "ok": True,
                "stdout": json.dumps(formula_sync_summary),
                "stderr": "",
                "returncode": 0,
            }
        )

        rows = read_sheet_rows(backtest_root, args.sheet_name)
        brief_text, eligible, _recommended = build_morning_brief(rows)
        tickets_text = build_paper_tickets(rows)
        review_candidates = select_review_candidates(rows)
        payload = {
            "generatedAt": datetime.now().astimezone().isoformat(),
            "sourceLabel": "Inferno Runner",
            "brief": brief_text,
            "tickets": tickets_text,
            "eligibleTickers": [row["ticker"] for row in eligible],
            "reviewQueueTickers": [row["ticker"] for row in review_candidates],
            "rows": rows,
        }
        write_payload(payload)

        email_sent = False
        if not args.skip_email and smtp_configured():
            email_sent = send_email(payload)

        write_ops_status(payload, updater_results, email_sent)
        append_paper_trade_journal(build_paper_trade_entries(payload))
        write_approval_queue(payload)

        append_log(
            {
                "job": "morning_inferno_pipeline",
                "generatedAt": payload["generatedAt"],
                "emailSent": email_sent,
                "eligibleTickers": payload["eligibleTickers"],
                "updaterScripts": [{"script": result["script"], "ok": result["ok"]} for result in updater_results],
            }
        )
        print(summarize(updater_results, payload, email_sent))
        return 0
    except Exception as exc:  # noqa: BLE001
        append_log(
            {
                "job": "morning_inferno_pipeline",
                "generatedAt": datetime.now().astimezone().isoformat(),
                "ok": False,
                "error": str(exc),
                "updaterScripts": [{"script": result["script"], "ok": result["ok"]} for result in updater_results],
            }
        )
        OPS_STATUS_FILE.write_text(
            json.dumps(
                {
                    "generatedAt": datetime.now().astimezone().isoformat(),
                    "ok": False,
                    "error": str(exc),
                    "updaterScripts": [{"script": result["script"], "ok": result["ok"]} for result in updater_results],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Morning inferno pipeline failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
