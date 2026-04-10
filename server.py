from __future__ import annotations

import json
import mimetypes
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REPORTS_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data"
SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
BRIEF_TEXT_FILE = REPORTS_DIR / "morning_brief_latest.txt"
TICKETS_TEXT_FILE = REPORTS_DIR / "paper_tickets_latest.txt"
LONG_TERM_TEXT_FILE = REPORTS_DIR / "long_term_buys_latest.txt"
HTML_BRIEF_FILE = REPORTS_DIR / "morning_brief_latest.html"
LOG_FILE = REPORTS_DIR / "brief_log.jsonl"
OPS_STATUS_FILE = DATA_DIR / "inferno_ops_status.json"
WATCHDOG_STATUS_FILE = DATA_DIR / "inferno_watchdog_status.json"
PAPER_JOURNAL_FILE = REPORTS_DIR / "paper_trade_journal.jsonl"
APPROVAL_QUEUE_FILE = DATA_DIR / "inferno_approval_queue.json"


def ensure_dirs() -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)


def smtp_settings() -> dict[str, Any]:
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "username": os.getenv("SMTP_USERNAME", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "from_addr": os.getenv("SMTP_FROM", "").strip(),
        "to_addr": os.getenv("SMTP_TO", "").strip(),
        "use_ssl": os.getenv("SMTP_USE_SSL", "").strip().lower() in {"1", "true", "yes"},
    }


def smtp_configured() -> bool:
    settings = smtp_settings()
    required = [settings["host"], settings["from_addr"], settings["to_addr"]]
    if settings["username"]:
        required.append(settings["password"])
    return all(required)


def load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def html_from_payload(payload: dict[str, Any]) -> str:
    rows = payload.get("rows", [])[:5]
    long_term_rows = payload.get("longTermRows", [])[:5]
    row_markup = "".join(
        f"""
        <tr>
          <td>{row.get("ticker", "")}</td>
          <td>{row.get("setupRec", "")}</td>
          <td>{row.get("readiness", "")}%</td>
          <td>{row.get("daysUntilEarnings", "")}d</td>
          <td>{"LIVE" if row.get("signalTrigger") else "WAIT"}</td>
        </tr>
        """
        for row in rows
    )
    long_term_markup = "".join(
        f"""
        <tr>
          <td>{row.get("ticker", "")}</td>
          <td>{row.get("accumulationBias", {}).get("label", "")}</td>
          <td>{row.get("longTermScore", "")}</td>
          <td>{row.get("valueScore", "")}</td>
          <td>{row.get("momentumScore", "")}</td>
        </tr>
        """
        for row in long_term_rows
    )
    brief = payload.get("brief", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    long_term_brief = payload.get("longTermBrief", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    long_term_section = ""
    if long_term_rows or long_term_brief:
        long_term_section = f"""
    <h2 style="color:#f0c36d;">Long-Term Accumulation</h2>
    <pre style="white-space:pre-wrap;background:#1c1611;padding:16px;border:1px solid #8b6530;">{long_term_brief}</pre>
    <table style="border-collapse:collapse;width:100%;">
      <thead>
        <tr>
          <th align="left">Ticker</th>
          <th align="left">Bias</th>
          <th align="left">Score</th>
          <th align="left">Value</th>
          <th align="left">Heat</th>
        </tr>
      </thead>
      <tbody>{long_term_markup}</tbody>
    </table>
"""
    return f"""<!DOCTYPE html>
<html lang="en">
  <body style="background:#120707;color:#f6e5d1;font-family:Georgia,serif;padding:24px;">
    <h1 style="color:#ffb074;margin:0 0 12px;">Morning Conviction Brief</h1>
    <p style="color:#b49a86;">Source: {payload.get("sourceLabel", "Unknown source")}</p>
    <pre style="white-space:pre-wrap;background:#220d0c;padding:16px;border:1px solid #7d1712;">{brief}</pre>
    <h2 style="color:#ff8d57;">Top Names</h2>
    <table style="border-collapse:collapse;width:100%;">
      <thead>
        <tr>
          <th align="left">Ticker</th>
          <th align="left">Setup</th>
          <th align="left">Readiness</th>
          <th align="left">Timing</th>
          <th align="left">Trigger</th>
        </tr>
      </thead>
      <tbody>{row_markup}</tbody>
    </table>
    {long_term_section}
  </body>
</html>"""


def send_email(payload: dict[str, Any], subject: str = "Morning Conviction Brief") -> bool:
    settings = smtp_settings()
    if not smtp_configured():
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings["from_addr"]
    message["To"] = settings["to_addr"]
    message.set_content(payload.get("brief", "Morning brief unavailable."))
    message.add_alternative(html_from_payload(payload), subtype="html")

    if settings["use_ssl"]:
        with smtplib.SMTP_SSL(settings["host"], settings["port"]) as server:
            if settings["username"]:
                server.login(settings["username"], settings["password"])
            server.send_message(message)
        return True

    with smtplib.SMTP(settings["host"], settings["port"]) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        if settings["username"]:
            server.login(settings["username"], settings["password"])
        server.send_message(message)
    return True


class CommandServerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self) -> None:
        if self.path == "/api/status":
            ensure_dirs()
            payload = {
                "ok": True,
                "smtpConfigured": smtp_configured(),
                "lastSnapshotAt": SNAPSHOT_FILE.stat().st_mtime if SNAPSHOT_FILE.exists() else None,
                "opsStatus": load_json_file(OPS_STATUS_FILE),
                "watchdogStatus": load_json_file(WATCHDOG_STATUS_FILE),
                "approvalQueue": load_json_file(APPROVAL_QUEUE_FILE),
            }
            self._write_json(payload)
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path == "/api/test-email":
            ensure_dirs()
            if not smtp_configured():
                self._write_json(
                    {
                        "ok": False,
                        "error": "SMTP is not configured yet.",
                        "smtpConfigured": False,
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                sent = send_email(
                    {
                        "brief": "SMTP test successful.\nYour local market cathedral can now deliver war briefs.",
                        "sourceLabel": "SMTP test",
                        "rows": [],
                    },
                    subject="SMTP Test From Inferno Earnings Throne",
                )
            except Exception as exc:  # noqa: BLE001
                self._write_json(
                    {
                        "ok": False,
                        "error": f"SMTP send failed: {exc}",
                        "smtpConfigured": smtp_configured(),
                    },
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return

            self._write_json(
                {
                    "ok": sent,
                    "smtpConfigured": smtp_configured(),
                    "message": "SMTP test email sent." if sent else "SMTP is not configured yet.",
                }
            )
            return

        if self.path != "/api/briefing":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown API endpoint")
            return

        ensure_dirs()
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON body")
            return

        generated_at = payload.get("generatedAt") or datetime.now().astimezone().isoformat()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        snapshot_name = f"snapshot-{timestamp}.json"
        brief_name = f"morning-brief-{timestamp}.txt"
        tickets_name = f"paper-tickets-{timestamp}.txt"
        html_name = f"morning-brief-{timestamp}.html"
        long_term_name = f"long-term-buys-{timestamp}.txt"

        snapshot_path = DATA_DIR / snapshot_name
        brief_path = REPORTS_DIR / brief_name
        tickets_path = REPORTS_DIR / tickets_name
        html_path = REPORTS_DIR / html_name
        long_term_path = REPORTS_DIR / long_term_name

        snapshot_text = json.dumps(payload, indent=2)
        brief_text = payload.get("brief", "")
        tickets_text = payload.get("tickets", "")
        long_term_text = payload.get("longTermBrief", "")
        html_text = html_from_payload(payload)

        snapshot_path.write_text(snapshot_text, encoding="utf-8")
        SNAPSHOT_FILE.write_text(snapshot_text, encoding="utf-8")
        brief_path.write_text(brief_text, encoding="utf-8")
        BRIEF_TEXT_FILE.write_text(brief_text, encoding="utf-8")
        tickets_path.write_text(tickets_text, encoding="utf-8")
        TICKETS_TEXT_FILE.write_text(tickets_text, encoding="utf-8")
        long_term_path.write_text(long_term_text, encoding="utf-8")
        LONG_TERM_TEXT_FILE.write_text(long_term_text, encoding="utf-8")
        html_path.write_text(html_text, encoding="utf-8")
        HTML_BRIEF_FILE.write_text(html_text, encoding="utf-8")

        log_entry = {
            "generatedAt": generated_at,
            "sourceLabel": payload.get("sourceLabel"),
            "eligibleTickers": payload.get("eligibleTickers", []),
            "snapshotPath": str(snapshot_path.relative_to(ROOT)),
        }
        with LOG_FILE.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(log_entry) + "\n")

        email_sent = False
        if payload.get("sendEmail"):
            try:
                email_sent = send_email(payload)
            except Exception as exc:  # noqa: BLE001
                self._write_json(
                    {
                        "ok": False,
                        "error": f"SMTP send failed: {exc}",
                        "smtpConfigured": smtp_configured(),
                        "snapshotPath": str(snapshot_path.relative_to(ROOT)),
                        "generatedAt": generated_at,
                    },
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return

        self._write_json(
            {
                "ok": True,
                "smtpConfigured": smtp_configured(),
                "emailSent": email_sent,
                "snapshotPath": str(snapshot_path.relative_to(ROOT)),
                "briefPath": str(brief_path.relative_to(ROOT)),
                "ticketsPath": str(tickets_path.relative_to(ROOT)),
                "longTermPath": str(long_term_path.relative_to(ROOT)),
                "generatedAt": generated_at,
            }
        )

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _write_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run() -> None:
    ensure_dirs()
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), CommandServerHandler)
    print(f"Command server live at http://127.0.0.1:{port}")
    print(f"Workspace root: {ROOT}")
    if smtp_configured():
        print("SMTP delivery is configured.")
    else:
        print("SMTP delivery is not configured; snapshots and briefs will still be saved locally.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down command server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
