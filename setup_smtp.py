from __future__ import annotations

import getpass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env.smtp"


def prompt(default: str, label: str) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def main() -> int:
    print("SMTP setup wizard")
    print("This writes local settings to .env.smtp for the dashboard command server.")
    print("")

    smtp_host = prompt("smtp.gmail.com", "SMTP host")
    smtp_port = prompt("587", "SMTP port")
    smtp_from = prompt("", "Sender email")
    smtp_to = prompt("", "Recipient email")
    smtp_username = prompt(smtp_from, "SMTP username")
    smtp_password = getpass.getpass("SMTP app password: ").strip()
    smtp_use_ssl = prompt("false", "Use SSL true/false").lower()

    # Gmail shows app passwords in groups with spaces for readability.
    # Normalize that format so users can paste the value directly.
    if "gmail.com" in smtp_host.lower():
        smtp_password = "".join(smtp_password.split())

    if not smtp_from or not smtp_to or not smtp_password:
        print("Sender, recipient, and app password are required.")
        return 1

    ENV_FILE.write_text(
        "\n".join(
            [
                f"SMTP_HOST={smtp_host}",
                f"SMTP_PORT={smtp_port}",
                f"SMTP_FROM={smtp_from}",
                f"SMTP_TO={smtp_to}",
                f"SMTP_USERNAME={smtp_username}",
                f"SMTP_PASSWORD={smtp_password}",
                f"SMTP_USE_SSL={smtp_use_ssl}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print("")
    print(f"Saved SMTP settings to {ENV_FILE}")
    print("Next:")
    print("1. Run ./run_with_smtp.sh")
    print("2. Open http://localhost:8000")
    print("3. Click Forge Snapshot")
    print("4. Click Send SMTP Brief")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
