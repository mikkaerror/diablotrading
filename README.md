# Inferno Earnings Dashboard

A standalone infernal trading desk that turns an earnings tracker into a ranked board, morning brief engine, and monitored automation stack.

## Project map

The repo is now split into four clean layers:

- UI
  - `index.html`
  - `app.js`
  - `styles.css`
- automation
  - `morning_inferno_pipeline.py`
  - `inferno_watchdog.py`
  - `inferno_approval_queue.py`
  - `inferno_doctor.py`
  - `inferno_housekeeping.py`
  - `install_inferno_dawn_service.py`
- shared config
  - `inferno_config.py`
- docs
  - `docs/README.md`
  - `docs/RUNBOOK.md`
  - `docs/OPERATING_MODEL.md`
  - `docs/PLAYBOOK_EARNINGS.md`
  - `docs/PLAYBOOK_LONG_TERM.md`
  - `docs/CHECKLISTS.md`
  - `docs/EXECUTION_MODEL.md`
  - `docs/THINKORSWIM_AUTOMATION.md`
  - `docs/CAMPAIGN_SIMULATION.md`

## Decision lanes

The desk runs in two distinct lanes now:

- earnings conviction
  - event-driven names you may actually trade into the catalyst window
- long-term accumulation
  - conviction names you would happily own at a discount when the heat comes out of them

And now one presentation layer:

- campaign simulation
  - a quest-board and town-role overlay that turns the live desk into a Diablo-style operating loop without hiding the real trade logic
  - includes a living `Inferno Town` with clickable village districts, tavern voices, moving villagers, and loot artifacts driven by the real desk state

## Quick start

Health check:

```bash
python3 inferno_doctor.py
```

Start the local dashboard:

```bash
python3 server.py
```

Run the full live refresh + brief cycle:

```bash
./run_inferno_dawn_cycle.sh
```

Use the wrapper above instead of calling `python3 morning_inferno_pipeline.py` directly. The wrapper intentionally uses the Backtest virtual environment so Google Sheets and market-data dependencies resolve the same way they do in automation.

## Publish to GitHub

This project is set up to live in a standalone GitHub repo and publish the dashboard UI through GitHub Pages.

What gets published on Pages:

- `index.html`
- `app.js`
- `styles.css`
- `README.md`

What stays local on your machine:

- the Python automation layer
- SMTP credentials
- launchd services
- local snapshots, reports, and logs

That means the GitHub-hosted site works as a public-facing dashboard/documentation site, while the live automation desk keeps running locally.

### Create the GitHub repo

1. Create a new empty GitHub repository in your account.
2. Do not add a README or `.gitignore` on GitHub, because this repo already has them locally.
3. Copy the repo URL.

### Push this project

After the repo exists, run:

```bash
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```

### Turn on GitHub Pages

This repo includes a GitHub Actions workflow that publishes the static dashboard automatically on pushes to `main`.

After your first push:

1. Open the repo on GitHub.
2. Go to `Settings` -> `Pages`.
3. Set `Source` to `GitHub Actions`.
4. Wait for the `Deploy static dashboard to GitHub Pages` workflow to finish.

Your site URL will look like:

```text
https://<your-github-username>.github.io/<your-repo-name>/
```

### Google OAuth note for Pages

If you want the hosted site to use private Google Sheets sync too, add your GitHub Pages origin as an authorized JavaScript origin in Google Cloud alongside `http://localhost:8000`.

For this repo, that means:

- Authorized JavaScript origin: `https://mikkaerror.github.io`

If Google still throws `redirect_uri_mismatch` from the hosted site, also add the full hosted page URL to the same Web client:

- Authorized redirect URI: `https://mikkaerror.github.io/diablotrading/`

## What it does

- Turns a wide spreadsheet into four decision buckets: timing, volatility, setup, confirmation.
- Ranks names with a composite readiness score so the best opportunities float to the top.
- Lets you click into a single ticker instead of scanning across many spreadsheet columns.
- Can pull directly from a private Google Sheet with browser-only Google OAuth.
- Accepts a CSV export from your tracker so you can swap the sample data for your real sheet.
- Separates short-term earnings setups from long-term accumulation ideas.

## How to use

Run the local command server:

```bash
python3 server.py
```

Then visit `http://localhost:8000`.

This server does three jobs:

- serves the dashboard
- accepts local snapshot/brief saves from the browser
- can send the morning brief over SMTP if you configure mail settings

## Recurring morning job

Once you have forged at least one snapshot from the dashboard, you can refresh and send the latest morning brief without reopening the app:

```bash
python3 briefing_job.py
```

That job reads `data/latest_snapshot.json`, rebuilds the latest report files, and sends the email if SMTP is configured.

## Inferno dawn cycle

If you want the morning email to refresh the live tracker first, use:

```bash
./run_inferno_dawn_cycle.sh
```

That pipeline will:

- run the four Backtest jobs:
- `BC-ATRPercentandIVRANK.py`
- `P-IV RANK CHANGE.py`
- `Q-ATRPcntZScore.py`
- `R-20DayATR.py`
- read the latest `Earnings Tracker` sheet through the shared service account
- score the rows with the same conviction logic used by the dashboard
- save `data/latest_snapshot.json`
- save the latest brief and paper tickets in `reports/`
- send the morning brief if SMTP is configured

Useful flags:

```bash
./run_inferno_dawn_cycle.sh --skip-updates
./run_inferno_dawn_cycle.sh --skip-email
```

`--skip-updates` means "skip the BC/P/Q/R PyCharm jobs and just rebuild the brief from the current tracker state."

Defaults:

- Backtest root: `~/PycharmProjects/Backtest3.0`
- Backtest Python: `~/PycharmProjects/Backtest3.0/venv/bin/python`

The pipeline reads SMTP settings from the local `.env.smtp` file, so you do not need to open the dashboard first.

PyCharm does not need to be open for the report to run. The automation calls the Backtest scripts directly from disk through the Backtest virtual environment. What matters is:

- the Backtest project still exists on disk
- the `venv` still exists
- the Mac is on, plugged in, and logged in when the morning run fires

If your Backtest project lives somewhere else, set:

```bash
export BACKTEST_ROOT="/absolute/path/to/Backtest3.0"
export BACKTEST_PYTHON="/absolute/path/to/Backtest3.0/venv/bin/python"
```

Backward compatibility:

- `run_morning_inferno.sh` still works as a shim to the new canonical runner.

## Install the Sunday-through-Friday 6 AM service

To install the macOS LaunchAgent that runs the inferno dawn cycle Sunday through Friday at 6:00 AM local time:

```bash
python3 install_inferno_dawn_service.py install --hour 6 --minute 0
```

To inspect whether the service is loaded:

```bash
python3 install_inferno_dawn_service.py status
```

To remove it:

```bash
python3 install_inferno_dawn_service.py uninstall
```

The service writes logs to:

- `logs/inferno_dawn.stdout.log`
- `logs/inferno_dawn.stderr.log`

The schedule, labels, time windows, and retention defaults now live in:

- `inferno_config.py`

## Operations stack

The standalone automation now has five roles:

- `Inferno Runner`
  - runs the BC/P/Q/R PyCharm jobs
  - refreshes the tracker snapshot
  - self-heals column `R` if the external ATR job writes mostly `N/A`
  - syncs formulas in `U:Y`
  - scores the board, writes the reports, and sends the morning brief
- `Inferno Watchdog`
  - checks whether the latest morning run actually landed today
  - checks whether the email sent
  - sends a failure alert with diagnostics if the system slips
- `Approval Desk`
  - stores the top cleared review queue for paper trades and manual approvals
  - keeps the queue aligned with the same names used in the brief and tickets
- `Inferno Doctor`
  - gives one command to validate SMTP, wake schedule, launch agents, and run freshness
- `Inferno Housekeeping`
  - prunes old snapshots, report artifacts, and oversized logs

Health files:

- `data/inferno_ops_status.json`
- `data/inferno_watchdog_status.json`
- `data/inferno_approval_queue.json`
- `reports/paper_trade_journal.jsonl`

The dashboard command server exposes those through `/api/status`, and the UI shows them inside the `Automation Watch` panel.

Quick verification commands:

```bash
./run_inferno_dawn_cycle.sh --skip-updates
python3 inferno_watchdog.py
python3 inferno_approval_queue.py status
python3 inferno_doctor.py
python3 inferno_housekeeping.py --dry-run
```

That gives you a clean local doublecheck:

- the runner produces a fresh brief and status file
- the watchdog confirms the run is healthy
- the approval desk shows the current pending shortlist
- the doctor gives you one-line desk health across email, launch agents, wake schedule, and latest run freshness

## Playbooks

- [docs/PLAYBOOK_EARNINGS.md](/Users/mikkasida/Documents/New%20project/docs/PLAYBOOK_EARNINGS.md)
  - how to make earnings plays with conviction and without overthinking
- [docs/PLAYBOOK_LONG_TERM.md](/Users/mikkasida/Documents/New%20project/docs/PLAYBOOK_LONG_TERM.md)
  - how to accumulate long-term conviction names when the price cools off
- [docs/CHECKLISTS.md](/Users/mikkasida/Documents/New%20project/docs/CHECKLISTS.md)
  - fast daily and pre-trade checklists so the desk stays mechanical
- [docs/EXECUTION_MODEL.md](/Users/mikkasida/Documents/New%20project/docs/EXECUTION_MODEL.md)
  - how the approval desk turns names into broker-safe execution intents
- [docs/THINKORSWIM_AUTOMATION.md](/Users/mikkasida/Documents/New%20project/docs/THINKORSWIM_AUTOMATION.md)
  - the safest path from signal engine to thinkorswim-assisted execution
- housekeeping shows what stale artifacts can be pruned before the repo gets messy

## Operating model

If you want the higher-level process flow, role ownership, and roadmap for turning this into a true small trading agency, read:

- [docs/README.md](/Users/mikkasida/Documents/New%20project/docs/README.md)
- [docs/RUNBOOK.md](/Users/mikkasida/Documents/New%20project/docs/RUNBOOK.md)
- [docs/OPERATING_MODEL.md](/Users/mikkasida/Documents/New%20project/docs/OPERATING_MODEL.md)

### Approval desk

Inspect the current approval queue:

```bash
python3 inferno_approval_queue.py status
```

Approve or reject a name:

```bash
python3 inferno_approval_queue.py approve SBAC
python3 inferno_approval_queue.py reject GE
```

Reset the queue back to all pending:

```bash
python3 inferno_approval_queue.py reset
```

## Private Google Sheets sync

Paste a Google Sheets URL and your Google OAuth Web Client ID into the dashboard, then press `Authorize Google + Sync`.

This is the safest straightforward setup for a personal dashboard because:

- your sheet stays restricted
- the app only asks for `spreadsheets.readonly`
- there is no backend and no refresh token storage
- Google access stays in the browser session

### What you need in Google Cloud

1. Create or use a Google Cloud project.
2. Enable the Google Sheets API.
3. Create an OAuth client ID for a `Web application`.
4. Add your local origin, for example `http://localhost:8000`, under authorized JavaScript origins.
5. Paste that client ID into the dashboard.

You do not need to make the sheet public.

The public repo does not include any default private sheet URL. Add your own link locally in the dashboard UI.

### SMTP delivery

If you want the `Send SMTP Brief` button to actually email the report, set these environment variables before running `server.py`:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_FROM`
- `SMTP_TO`

Optional:

- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_USE_SSL`

If SMTP is not configured, the dashboard still saves snapshots and report artifacts locally in:

- `data/latest_snapshot.json`
- `reports/morning_brief_latest.txt`
- `reports/morning_brief_latest.html`
- `reports/paper_tickets_latest.txt`

### Quick SMTP setup

The easiest path is to use a dedicated sender mailbox and an app password.

1. Run the setup wizard:

```bash
python3 setup_smtp.py
```

2. Start the app with:

```bash
chmod +x run_with_smtp.sh
./run_with_smtp.sh
```

3. Open the dashboard and click `Test SMTP`

For Gmail, the usual values are:

- `SMTP_HOST=smtp.gmail.com`
- `SMTP_PORT=587`
- `SMTP_USE_SSL=false`

Use a Gmail app password, not your normal account password.

### Optional fallback

The dashboard still includes a public-sheet sync button if you ever decide to use a viewer-shared sheet, but it is no longer required.

## CSV columns expected

The importer is designed around these spreadsheet headers:

- `Ticker`
- `ATR%`
- `IV Rank`
- `Next Earnings`
- `Price`
- `EPS`
- `PE`
- `Days until earnings`
- `Setup Rec`
- `"Urgency"`
- `Signal Trigger`
- `Confidence (3 MAX)`
- `IV Rank Change (5-day delta)`
- `ATR% Z-Score`
- `20 Day ATR`
- `REC 1-13`
- `Rec2`
- `Value Score`
- `Momentum Score`
- `Squeeze Score`
- `Ready Score`
- `Priority`

## Suggested tracker simplification

If you want the dashboard to stay readable, think about your sheet in two layers:

1. Raw inputs
   - ticker, price, earnings date, days until earnings
   - ATR%, IV Rank, IV Rank delta, ATR z-score
   - setup rec, Rec1, Rec2, signal trigger, confidence
2. Derived scores
   - value, momentum, squeeze, ready, priority, composite readiness

That split helps you avoid treating every column like it deserves equal visual weight.
