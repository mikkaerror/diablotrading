from __future__ import annotations

"""Read-only thinkorswim Account Statement scraper.

This module is the fallback lane for when thinkorswim refuses to hand us a
clean export artifact. Instead of opening new windows or leaning on brittle
shortcuts, we read the already-open `Monitor > Account Statement` accessibility
tree and turn the visible account state into local JSON/text artifacts.

The scraper stays intentionally narrow:
1. verify the current TOS session is already on Account Statement
2. locate the statement scroll area that sits beside `Dump Account`
3. scrape the visible statement sections and their row descriptions
4. derive a compact live-position packet for downstream automation

It never places orders, never edits broker state, and never opens a new TOS
instance.
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any

from inferno_tos_session_probe import applescript_list, probe_tos_session, text
from inferno_tos_ui_route import route_to_account_statement
from inferno_config import local_now
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


ACCOUNT_STATEMENT_FILE = DATA_DIR / "inferno_tos_account_statement.json"
ACCOUNT_STATEMENT_LAST_GOOD_FILE = DATA_DIR / "inferno_tos_account_statement_last_good.json"
ACCOUNT_STATEMENT_TEXT_FILE = REPORTS_DIR / "tos_account_statement_latest.txt"
SECTION_TITLES = {
    "Cash & Sweep Vehicle",
    "Futures Cash Balance",
    "Forex Cash Balance",
    "Crypto # (Crypto offered by Charles Schwab Premier Bank, SSB) Cash Balance",
    "Order History",
    "Trade History",
    "Equities",
    "Options",
    "Futures",
    "Futures Options",
    "Forex",
    "Crypto # (Crypto offered by Charles Schwab Premier Bank, SSB)",
    "Others",
    "Profits and Losses",
    "Forex Account Summary",
    "Crypto # (Crypto offered by Charles Schwab Premier Bank, SSB) Account Summary",
    "Account Summary",
}


def build_child_expression(process_name: str, split_group_index: int, monitor_group_index: int, parent_index: int, attribute: str) -> str:
    """Build an AppleScript list expression for a nested statement container."""
    return (
        'tell application "System Events" to tell application process '
        f'"{process_name}" to set _items to {attribute} of every UI element of UI element {parent_index} '
        f'of UI element {monitor_group_index} of UI element {split_group_index} of window 1'
    )


def monitor_group_children(process_name: str, split_group_index: int, monitor_group_index: int) -> list[dict[str, Any]]:
    """Return the direct children of the active Monitor tab group."""
    roles = applescript_list(
        'tell application "System Events" to tell application process '
        f'"{process_name}" to set _items to role of every UI element of UI element {monitor_group_index} '
        f'of UI element {split_group_index} of window 1'
    )
    descriptions = applescript_list(
        'tell application "System Events" to tell application process '
        f'"{process_name}" to set _items to description of every UI element of UI element {monitor_group_index} '
        f'of UI element {split_group_index} of window 1'
    )
    values = applescript_list(
        'tell application "System Events" to tell application process '
        f'"{process_name}" to set _items to value of every UI element of UI element {monitor_group_index} '
        f'of UI element {split_group_index} of window 1'
    )
    count = max(len(roles), len(descriptions), len(values))
    children: list[dict[str, Any]] = []
    for index in range(count):
        role = text(roles[index] if index < len(roles) else "")
        description = text(descriptions[index] if index < len(descriptions) else "")
        value = text(values[index] if index < len(values) else "")
        children.append(
            {
                "index": index + 1,
                "role": role,
                "description": description,
                "value": value,
                "label": description or value,
            }
        )
    return children


def statement_scroll_area_index(children: list[dict[str, Any]], dump_button_index: int | None) -> int | None:
    """Find the Account Statement scroll area that follows the Dump Account button."""
    if dump_button_index:
        for item in children:
            if item.get("index", 0) > dump_button_index and item.get("role") == "AXScrollArea":
                return int(item["index"])
    for item in children:
        if item.get("role") == "AXScrollArea":
            return int(item["index"])
    return None


def scroll_area_children(
    process_name: str,
    split_group_index: int,
    monitor_group_index: int,
    scroll_area_index: int,
) -> list[dict[str, Any]]:
    """Return the direct children of the Account Statement scroll area."""
    roles = applescript_list(
        build_child_expression(process_name, split_group_index, monitor_group_index, scroll_area_index, "role")
    )
    descriptions = applescript_list(
        build_child_expression(process_name, split_group_index, monitor_group_index, scroll_area_index, "description")
    )
    values = applescript_list(
        build_child_expression(process_name, split_group_index, monitor_group_index, scroll_area_index, "value")
    )
    count = max(len(roles), len(descriptions), len(values))
    children: list[dict[str, Any]] = []
    for index in range(count):
        role = text(roles[index] if index < len(roles) else "")
        description = text(descriptions[index] if index < len(descriptions) else "")
        value = text(values[index] if index < len(values) else "")
        children.append(
            {
                "index": index + 1,
                "role": role,
                "description": description,
                "value": value,
                "label": description or value,
            }
        )
    return children


def table_rows(
    process_name: str,
    split_group_index: int,
    monitor_group_index: int,
    scroll_area_index: int,
    table_index: int,
) -> list[str]:
    """Return the row descriptions for a specific statement table."""
    expression = (
        'tell application "System Events" to tell application process '
        f'"{process_name}" to set _items to description of every UI element of UI element {table_index} '
        f'of UI element {scroll_area_index} of UI element {monitor_group_index} '
        f'of UI element {split_group_index} of window 1'
    )
    return [text(line) for line in applescript_list(expression) if text(line)]


def parse_money(value: str) -> float | None:
    """Parse a currency-like string into a float when possible."""
    raw = text(value).replace("$", "").replace(",", "")
    if not raw or raw in {"N/A", "--"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def parse_percent(value: str) -> float | None:
    """Parse a percent string such as `+0.72%` into a float."""
    raw = text(value).replace("%", "").replace(",", "")
    if not raw or raw in {"N/A", "--"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def parse_int(value: str) -> int | None:
    """Parse an integer-like quantity such as `+4` or `-3`."""
    raw = text(value).replace(",", "")
    if not raw or raw in {"N/A", "--"}:
        return None
    match = re.fullmatch(r"([+-]?\d+)", raw)
    if not match:
        return None
    return int(match.group(1))


def split_row(raw_row: str) -> list[str]:
    """Split a comma-delimited TOS row while preserving empty placeholders."""
    return [piece.strip() for piece in raw_row.split(",")]


def parse_equity_row(raw_row: str) -> dict[str, Any]:
    """Parse one visible Equities row from the statement body."""
    pieces = split_row(raw_row)
    symbol = text(pieces[0] if pieces else "")
    description = text(pieces[3] if len(pieces) > 3 else "")
    qty = parse_int(pieces[4] if len(pieces) > 4 else "")
    # The TOS accessibility row repeats some price columns; the last dollar-like
    # token is the most reliable mark value, while the last non-empty numeric
    # token before that is a usable mark price.
    numeric_tokens = [piece for piece in pieces[5:] if text(piece) not in {"", "0"}]
    mark_value = None
    mark = None
    for token in reversed(numeric_tokens):
        if token.startswith("$"):
            mark_value = parse_money(token)
            break
    for token in reversed(numeric_tokens):
        candidate = parse_money(token)
        if candidate is None:
            continue
        if mark_value is not None and abs(candidate - mark_value) < 0.0001:
            continue
        mark = candidate
        break
    if mark is None and numeric_tokens:
        mark = parse_money(numeric_tokens[-1])
    return {
        "symbol": symbol,
        "description": description,
        "qty": qty,
        "mark": mark,
        "markValue": mark_value,
        "rawRow": raw_row,
    }


def parse_profit_loss_row(raw_row: str) -> dict[str, Any]:
    """Parse one visible Profits and Losses row."""
    pieces = split_row(raw_row)
    return {
        "symbol": text(pieces[0] if pieces else ""),
        "description": text(pieces[1] if len(pieces) > 1 else ""),
        "plOpen": parse_money(pieces[2] if len(pieces) > 2 else ""),
        "plPercent": parse_percent(pieces[3] if len(pieces) > 3 else ""),
        "plDay": parse_money(pieces[4] if len(pieces) > 4 else ""),
        "plYtd": parse_money(pieces[5] if len(pieces) > 5 else ""),
        "plDiff": parse_money(pieces[6] if len(pieces) > 6 else ""),
        "markValue": parse_money(pieces[7] if len(pieces) > 7 else ""),
        "rawRow": raw_row,
    }


def parse_key_value_row(raw_row: str) -> tuple[str, str] | None:
    """Parse a simple `Label, Value` row from summary-like sections."""
    pieces = [piece.strip() for piece in raw_row.split(",") if piece.strip()]
    if len(pieces) < 2:
        return None
    # Summary rows often contain comma-formatted money values such as
    # `$2,900.81`. Join the trailing segments back together so we preserve the
    # full amount instead of truncating at the first comma.
    return pieces[0], ",".join(pieces[1:])


def build_section_snapshot(
    process_name: str,
    split_group_index: int,
    monitor_group_index: int,
    scroll_area_index: int,
    children: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a lightweight map of statement sections and their row payloads."""
    sections: dict[str, dict[str, Any]] = {}
    current_section: str | None = None
    for item in children:
        label = text(item.get("description") or item.get("value"))
        role = text(item.get("role"))
        if label in SECTION_TITLES:
            current_section = label
            sections.setdefault(current_section, {"rows": [], "tables": [], "value": None})
            continue
        if current_section and sections[current_section].get("value") is None:
            candidate_value = text(item.get("value"))
            if candidate_value and candidate_value not in {"0", "1", "missing value"}:
                sections[current_section]["value"] = candidate_value
        if role == "AXTable" and current_section:
            rows = table_rows(process_name, split_group_index, monitor_group_index, scroll_area_index, int(item["index"]))
            if rows:
                sections[current_section]["tables"].append({"index": int(item["index"]), "rows": rows})
                sections[current_section]["rows"].extend(rows)
    return sections


def merge_equities_and_pnl(equity_rows: list[str], pnl_rows: list[str]) -> list[dict[str, Any]]:
    """Merge positions with P&L so we can derive cleaner trade context."""
    equities = [parse_equity_row(row) for row in equity_rows]
    pnl_by_symbol = {
        item["symbol"]: item
        for item in (parse_profit_loss_row(row) for row in pnl_rows)
        if item.get("symbol")
    }
    merged: list[dict[str, Any]] = []
    for item in equities:
        symbol = text(item.get("symbol"))
        if not symbol or symbol == "OVERALL TOTALS":
            continue
        pnl = pnl_by_symbol.get(symbol, {})
        combined = {**item, **pnl}
        qty = item.get("qty")
        mark = item.get("mark")
        pl_open = pnl.get("plOpen")
        if qty and mark is not None and pl_open is not None:
            # This gives us the entry basis without needing a dedicated export
            # file, which is especially useful when the statement grid only
            # exposes mark and P/L values directly.
            combined["derivedTradePrice"] = round(mark - (pl_open / qty), 4)
        merged.append(combined)
    return merged


def scrape_account_statement(*, route_if_needed: bool = True) -> dict[str, Any]:
    """Scrape the current open Account Statement pane into local artifacts.

    When `route_if_needed` is enabled, the scraper will safely navigate the
    already-open TOS window into `Monitor > Account Statement` before reading
    the statement tree. It still refuses to recover or relaunch the app.
    """
    ensure_dirs()
    session = probe_tos_session()
    report: dict[str, Any] = {
        "generatedAt": local_now().isoformat(),
        "ok": False,
        "message": None,
        "routeIfNeeded": route_if_needed,
        "uiRoute": None,
        "sessionSummary": session.get("summary"),
        "accountMode": session.get("accountMode"),
        "accountSuffixCandidates": session.get("accountSuffixCandidates") or [],
        "positions": [],
        "profitLoss": [],
        "accountSummary": {},
        "sections": {},
    }
    if not session.get("ok"):
        report["message"] = "live thinkorswim session probe is unavailable"
        save_account_statement_report(report)
        return report
    if route_if_needed and (session.get("currentPanel") != "Monitor" or session.get("monitorSubpanel") != "Account Statement"):
        route_report = route_to_account_statement(dry_run=False, allow_recovery=False)
        report["uiRoute"] = {
            "ok": route_report.get("ok"),
            "status": route_report.get("status"),
            "message": route_report.get("message"),
        }
        if not route_report.get("ok"):
            report["message"] = route_report.get("message") or "failed to route the existing TOS window into Account Statement"
            save_account_statement_report(report)
            return report
        session = probe_tos_session()
        report["sessionSummary"] = session.get("summary")
        report["accountMode"] = session.get("accountMode")
        report["accountSuffixCandidates"] = session.get("accountSuffixCandidates") or []
    if session.get("currentPanel") != "Monitor" or session.get("monitorSubpanel") != "Account Statement":
        report["message"] = "thinkorswim is not visibly on Monitor > Account Statement"
        save_account_statement_report(report)
        return report

    process_name = text(session.get("matchedProcessName"))
    split_group_index = int(session.get("splitGroupIndex") or 0)
    monitor_group_index = int(session.get("monitorGroupIndex") or 0)
    dump_button_index = next(
        (
            int(item.get("index"))
            for item in (session.get("labeledButtons") or [])
            if text(item.get("label")).lower() == "dump account"
        ),
        None,
    )
    if not process_name or not split_group_index or not monitor_group_index:
        report["message"] = "statement pane indices are missing from the live session probe"
        save_account_statement_report(report)
        return report

    monitor_children = monitor_group_children(process_name, split_group_index, monitor_group_index)
    scroll_area_index = statement_scroll_area_index(monitor_children, dump_button_index)
    report["statementScrollAreaIndex"] = scroll_area_index
    if not scroll_area_index:
        report["message"] = "could not locate the Account Statement scroll area"
        save_account_statement_report(report)
        return report

    statement_children = scroll_area_children(process_name, split_group_index, monitor_group_index, scroll_area_index)
    sections = build_section_snapshot(process_name, split_group_index, monitor_group_index, scroll_area_index, statement_children)
    positions = merge_equities_and_pnl(sections.get("Equities", {}).get("rows", []), sections.get("Profits and Losses", {}).get("rows", []))

    account_summary: dict[str, str] = {}
    for row in sections.get("Account Summary", {}).get("rows", []):
        parsed = parse_key_value_row(row)
        if parsed:
            account_summary[parsed[0]] = parsed[1]

    report.update(
        {
            "ok": True,
            "message": "statement scraped from the live Account Statement pane",
            "sections": sections,
            "positions": positions,
            "profitLoss": [parse_profit_loss_row(row) for row in sections.get("Profits and Losses", {}).get("rows", [])],
            "accountSummary": account_summary,
            "totalCash": sections.get("Cash & Sweep Vehicle", {}).get("value"),
            "netLiquidatingValue": account_summary.get("Net Liquidating Value"),
        }
    )
    save_account_statement_report(report)
    return report


def account_statement_report_text(report: dict[str, Any]) -> str:
    """Render the latest scraped account statement packet into plain text."""
    lines = [
        "Inferno thinkorswim Account Statement Scraper",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Ok: {report.get('ok')}",
        f"Message: {report.get('message')}",
        f"Session: {report.get('sessionSummary')}",
        f"Account mode: {report.get('accountMode')}",
        f"Account suffixes: {', '.join(report.get('accountSuffixCandidates') or []) or '-'}",
        f"Statement scroll area: {report.get('statementScrollAreaIndex')}",
        f"Total cash: {report.get('totalCash') or '-'}",
        f"Net liquidation value: {report.get('netLiquidatingValue') or '-'}",
        "",
        f"Positions: {len(report.get('positions') or [])}",
    ]
    for item in report.get("positions") or []:
        lines.append(
            f"- {item.get('symbol')} | qty={item.get('qty')} | mark={item.get('mark')} | "
            f"markValue={item.get('markValue')} | plOpen={item.get('plOpen')} | trade={item.get('derivedTradePrice')}"
        )
    summary = report.get("accountSummary") or {}
    if summary:
        lines.extend(["", "Account summary:"])
        for key, value in summary.items():
            lines.append(f"- {key}: {value}")
    return "\n".join(lines).rstrip() + "\n"


def save_account_statement_report(report: dict[str, Any]) -> None:
    """Persist the current statement scrape to local ignored artifacts.

    A failed refresh should never destroy the last good live-account packet.
    We therefore keep a separate `last_good` artifact and preserve it whenever
    the latest scrape comes back degraded.
    """
    ensure_dirs()
    ACCOUNT_STATEMENT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if report.get("ok"):
        ACCOUNT_STATEMENT_LAST_GOOD_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    else:
        previous_good = load_json_file(ACCOUNT_STATEMENT_LAST_GOOD_FILE) or load_json_file(ACCOUNT_STATEMENT_FILE)
        if previous_good and previous_good.get("ok"):
            preserved = dict(previous_good)
            preserved["_lastRefreshFailureAt"] = report.get("generatedAt")
            preserved["_lastRefreshFailure"] = report.get("message")
            ACCOUNT_STATEMENT_LAST_GOOD_FILE.write_text(json.dumps(preserved, indent=2), encoding="utf-8")
    ACCOUNT_STATEMENT_TEXT_FILE.write_text(account_statement_report_text(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the statement scraper."""
    parser = argparse.ArgumentParser(description="Scrape the visible thinkorswim Account Statement pane.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    """Run or print the latest account statement scrape."""
    args = parse_args()
    if args.command == "status" and ACCOUNT_STATEMENT_TEXT_FILE.exists():
        print(ACCOUNT_STATEMENT_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    report = scrape_account_statement()
    print(account_statement_report_text(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
