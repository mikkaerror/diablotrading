# Inferno Runbook

This is the "what do I do when something feels off?" guide for the desk.

## Daily Defaults

### Start the local dashboard

```bash
python3 server.py
```

If you change backend files like `server.py`, `inferno_execution_clerk.py`, or the morning runner, stop and restart this command so the dashboard is not serving stale process logic.

Then open:

- `http://localhost:8000`

### Check the desk in one command

```bash
python3 inferno_doctor.py
```

What it verifies:

- SMTP is configured
- the dawn and watchdog agents are loaded
- the 5:58 AM wake is scheduled
- the Mac is not falling asleep too aggressively on AC
- today’s run and watchdog status are fresh

## Manual Commands

### Rebuild and send the live brief

```bash
./run_inferno_dawn_cycle.sh
```

Do not use bare system Python for this step unless that interpreter already has the Backtest dependencies installed. The wrapper is the safe operator path because it runs through the Backtest virtual environment.

### Rebuild without rerunning BC/P/Q/R

```bash
./run_inferno_dawn_cycle.sh --skip-updates
```

### Rebuild without sending email

```bash
./run_inferno_dawn_cycle.sh --skip-email
```

### Check watchdog health

```bash
python3 inferno_watchdog.py
```

### Check the approval queue

```bash
python3 inferno_approval_queue.py status
```

### Check the execution desk

```bash
python3 inferno_execution_clerk.py
```

### Approve or reject a live name

```bash
python3 inferno_approval_queue.py approve TICKER
python3 inferno_approval_queue.py reject TICKER
python3 inferno_approval_queue.py reset
```

The dashboard now exposes these same approval actions directly inside the `Order Intent Desk`, which is the preferred operator flow.

Once a name becomes `approval-ready`, use the desk's `Copy Ticket` action to grab the broker-review blueprint before routing anything inside thinkorswim.

### Prune old artifacts

```bash
python3 inferno_housekeeping.py --dry-run
python3 inferno_housekeeping.py
```

## Where The Important Files Live

### Health and state

- [data/inferno_ops_status.json](/Users/mikkasida/Documents/New%20project/data/inferno_ops_status.json)
- [data/inferno_watchdog_status.json](/Users/mikkasida/Documents/New%20project/data/inferno_watchdog_status.json)
- [data/inferno_approval_queue.json](/Users/mikkasida/Documents/New%20project/data/inferno_approval_queue.json)
- [data/inferno_execution_queue.json](/Users/mikkasida/Documents/New%20project/data/inferno_execution_queue.json)
- [data/latest_snapshot.json](/Users/mikkasida/Documents/New%20project/data/latest_snapshot.json)

### Human-readable outputs

- [reports/morning_brief_latest.txt](/Users/mikkasida/Documents/New%20project/reports/morning_brief_latest.txt)
- [reports/morning_brief_latest.html](/Users/mikkasida/Documents/New%20project/reports/morning_brief_latest.html)
- [reports/paper_tickets_latest.txt](/Users/mikkasida/Documents/New%20project/reports/paper_tickets_latest.txt)
- [reports/long_term_buys_latest.txt](/Users/mikkasida/Documents/New%20project/reports/long_term_buys_latest.txt)
- [reports/execution_desk_latest.txt](/Users/mikkasida/Documents/New%20project/reports/execution_desk_latest.txt)

### Logs

- [logs/inferno_dawn.stdout.log](/Users/mikkasida/Documents/New%20project/logs/inferno_dawn.stdout.log)
- [logs/inferno_dawn.stderr.log](/Users/mikkasida/Documents/New%20project/logs/inferno_dawn.stderr.log)
- [logs/inferno_watchdog.stdout.log](/Users/mikkasida/Documents/New%20project/logs/inferno_watchdog.stdout.log)
- [logs/inferno_watchdog.stderr.log](/Users/mikkasida/Documents/New%20project/logs/inferno_watchdog.stderr.log)

## If The Brief Is Missing

Run this first:

```bash
python3 inferno_doctor.py
```

Then check:

1. Did today’s run happen?
   - open [data/inferno_ops_status.json](/Users/mikkasida/Documents/New%20project/data/inferno_ops_status.json)
2. Did the watchdog rescue it?
   - open [data/inferno_watchdog_status.json](/Users/mikkasida/Documents/New%20project/data/inferno_watchdog_status.json)
3. Did the updater jobs fail?
   - open [logs/inferno_dawn.stderr.log](/Users/mikkasida/Documents/New%20project/logs/inferno_dawn.stderr.log)
4. Is the latest local brief still stale?
   - open [reports/morning_brief_latest.txt](/Users/mikkasida/Documents/New%20project/reports/morning_brief_latest.txt)

If you need a same-day recovery:

```bash
./run_inferno_dawn_cycle.sh
```

## If The Dashboard Looks Right But Email Did Not Arrive

Check:

```bash
python3 inferno_doctor.py
```

Then verify:

- `.env.smtp` still exists locally
- `emailSent` is `true` in [data/inferno_ops_status.json](/Users/mikkasida/Documents/New%20project/data/inferno_ops_status.json)
- the SMTP account still accepts the app password

If needed, send a fresh brief manually:

```bash
./run_inferno_dawn_cycle.sh
```

## PyCharm Clarifier

You do not need PyCharm open for the desk to run.

The automation uses:

- the Backtest project files on disk
- the Backtest virtual environment Python
- the script filenames listed in the runner

What you do need:

- the project path still exists
- the `venv` still exists
- the Mac is awake or able to wake
- the Mac user session is logged in

## If The Sheet Or Scores Look Broken

The runner already tries to self-heal two common breakpoints:

- column `R` ATR repair
- columns `U:Y` score formula sync

If you want to force a rebuild:

```bash
./run_inferno_dawn_cycle.sh --skip-email
```

Then inspect:

- [data/inferno_ops_status.json](/Users/mikkasida/Documents/New%20project/data/inferno_ops_status.json)
- [reports/morning_brief_latest.txt](/Users/mikkasida/Documents/New%20project/reports/morning_brief_latest.txt)

## Labels And Roles

These are the names that matter:

- `Inferno Runner`
  - refreshes and sends
- `Inferno Watchdog`
  - verifies and rescues
- `Approval Desk`
  - stages decisions
- `Inferno Doctor`
  - gives a fast health answer
- `Inferno Housekeeping`
  - keeps runtime artifacts under control

## Suggested Weekly Hygiene

### Once a week

```bash
python3 inferno_housekeeping.py
python3 inferno_doctor.py
```

### Once a month

- review false positives
- review missed winners
- clean up threshold drift
- decide whether the approval rules earned more autonomy
