# Daily Briefing — How to Get Your Summary Every Morning

You should never have to search for your daily plan. It should arrive in
your inbox at 6:00 AM, fully filtered, with your cash sized, and the
checklist included. Here's how.

## Get the briefing right now (one command)

Open Terminal, copy and paste:

```bash
cd "<repo-root>"
python3 inferno_operator_briefing.py --cash <deployable-cash>
```

That prints the briefing to your terminal **and** saves it as:

- `reports/operator_briefing_latest.txt` (plain text)
- `reports/operator_briefing_latest.html` (renders beautifully in any email client)

Open the HTML file with `open reports/operator_briefing_latest.html` and
you'll see exactly what would have been emailed to you.

## Send it to yourself by email (one command, after SMTP setup)

If you've already set up SMTP for the morning brief (you have — there's
a `.env.smtp` file), use this exact block. Do **not** use
`./run_with_smtp.sh` for the briefing — that script also tries to start
the dashboard on port 8000, so if your dashboard is already running it
will crash before exporting the credentials.

```bash
cd "<repo-root>"
set -a; source .env.smtp; set +a
python3 inferno_operator_briefing.py --cash <deployable-cash> --email
```

The `set -a; source .env.smtp; set +a` block reads your SMTP credentials
into the current shell so the Python script can see them. After running
it once in a terminal session you can rerun the briefing as many times
as you like without re-sourcing.

If `--email` succeeds you'll see `Email sent to your@address.com`. Done.

## Make it run automatically every morning

The desk already has a 6 AM LaunchAgent for the morning brief. Add the
operator briefing right after it.

### One-time setup (paste the whole block)

```bash
cd "<repo-root>"

# Create a wrapper that loads SMTP creds then sends the briefing
cat > "$HOME/.local/bin/inferno_operator_briefing_service.sh" <<'WRAP'
#!/bin/zsh
set -euo pipefail
cd "<repo-root>"
source ".env.smtp" 2>/dev/null || true
export INFERNO_OPERATOR_CASH="${INFERNO_OPERATOR_CASH:-1000}"
exec /usr/bin/python3 inferno_operator_briefing.py --email
WRAP
chmod +x "$HOME/.local/bin/inferno_operator_briefing_service.sh"

# Create the LaunchAgent — fires at 6:10 AM, 10 min after the dawn brief
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$HOME/Library/LaunchAgents/io.diablotrading.inferno-operator-briefing.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>io.diablotrading.inferno-operator-briefing</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>$HOME/.local/bin/inferno_operator_briefing_service.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>10</integer></dict>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/inferno_operator_briefing.stdout.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/inferno_operator_briefing.stderr.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/io.diablotrading.inferno-operator-briefing.plist" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/io.diablotrading.inferno-operator-briefing.plist"
echo "Installed. You'll get the briefing in your inbox at 6:10 AM every day."
```

You only do this once. After that, your inbox has a fresh briefing at
6:10 AM every morning — already filtered, sized to your configured cash,
with the seven-step checklist and exact terminal commands to follow.

## Update your cash level

When your cash changes (after winning trades, fresh deposits, etc.), just
edit one line. Open `~/.local/bin/inferno_operator_briefing_service.sh` in
TextEdit and change `1000` to your current deployable cash number. That's it.
The next 6:10 AM run uses the new value.

## What you'll see in the email

1. **Verdict** at top: `ready-to-execute` / `no-candidates` / `no-slate`.
2. **Today's plan** with cash, tickets to place, per-ticket size, total deployed.
3. **Candidate table** — ranked by Ready Score, with allocation column already filled.
4. **Conviction gates** so you can sanity-check each name.
5. **Next steps** — the exact seven commands to run, in order.
6. **Reminder** that the desk doesn't click submit. You do.

## What to do if no candidates clear the gates

The email will say `no-candidates`. Sit on cash. The market opens again
tomorrow. Conviction-less trades cost more than skipped days.

## Where the full checklist lives

`docs/TRADING_DAY_CHECKLIST.md`. The email links to it; rereading it
once a week keeps the loop tight.
