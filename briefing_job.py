from __future__ import annotations

import json

from server import (
    BRIEF_TEXT_FILE,
    HTML_BRIEF_FILE,
    LONG_TERM_TEXT_FILE,
    LOG_FILE,
    REPORTS_DIR,
    SNAPSHOT_FILE,
    TICKETS_TEXT_FILE,
    ensure_dirs,
    html_from_payload,
    send_email,
    smtp_configured,
)


def main() -> int:
    ensure_dirs()

    if not SNAPSHOT_FILE.exists():
        print("No snapshot found. Open the dashboard and forge a snapshot first.")
        return 1

    payload = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    brief_text = payload.get("brief", "")
    tickets_text = payload.get("tickets", "")
    long_term_text = payload.get("longTermBrief", "")
    html_text = html_from_payload(payload)

    BRIEF_TEXT_FILE.write_text(brief_text, encoding="utf-8")
    TICKETS_TEXT_FILE.write_text(tickets_text, encoding="utf-8")
    LONG_TERM_TEXT_FILE.write_text(long_term_text, encoding="utf-8")
    HTML_BRIEF_FILE.write_text(html_text, encoding="utf-8")

    email_sent = False
    if smtp_configured():
        email_sent = send_email(payload)

    with LOG_FILE.open("a", encoding="utf-8") as log_file:
        log_file.write(
            json.dumps(
                {
                    "job": "briefing_job",
                    "emailSent": email_sent,
                    "eligibleTickers": payload.get("eligibleTickers", []),
                }
            )
            + "\n"
        )

    print(f"Brief refreshed in {REPORTS_DIR}.")
    if email_sent:
        print("SMTP delivery sent successfully.")
    else:
        print("SMTP not configured; refreshed local artifacts only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
