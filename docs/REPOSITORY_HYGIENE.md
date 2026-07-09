# Repository Hygiene

How to keep the GitHub repo clean, safe, and useful for Codex, Claude, and the
human operator.

Last updated: 2026-05-15.

## Operating rule

The repo is the source for code, docs, tests, and deployable static assets. It
is not the vault for live trading data, credentials, account exports, or local
run artifacts.

If a file contains personal financial data, broker output, Google credentials,
SMTP credentials, generated reports, local snapshots, or logs, it stays out of
GitHub.

## Commit

- Source code: `inferno_*.py`, `server.py`, dashboard files, scripts, installers.
- Tests: `tests/test_*.py`.
- Process docs: `README.md`, `docs/*.md`, safe `.github/workflows/*.yml`.
- Examples: sanitized `.example` files only.

## Do Not Commit

- `.env`, `.env.smtp`, `.env.cloud`, or any local secret file.
- Google OAuth/service-account files: `gcred.json`, `credentials*.json`, `client_secret*.json`, `token*.json`.
- Broker/TOS exports: account statements, positions, fills, executions, screenshots.
- Generated state: `data/`, `reports/`, `logs/`, `_backups/`, local snapshots.
- Anything containing account numbers, API keys, passwords, app passwords, or private trade fills.

## Before Staging

1. Run central command and refresh the low-context handoff:

```bash
./inferno status
./inferno usage
```

2. Run the doctor:

```bash
./inferno doctor
```

3. Review the staged diff:

```bash
git diff --stat
git diff --cached --stat
```

4. Check for accidental sensitive files:

```bash
git status --short
git diff --cached --name-only
```

5. Only stage coherent groups: docs together, math together, broker/TOS tooling
together. Do not stage the entire workspace just because it is noisy.

## PR / Push Standard

Every clean GitHub update should answer:

- What changed?
- Which safety rail did this preserve or improve?
- Which test or doctor command was run?
- Does this change touch live broker authority? If yes, stop and review manually.

Suggested commit shape:

```text
<verb> <desk area>

- concise behavior change
- docs/tests updated
- safety note
```

## Current Public Surface

- `README.md` is the public landing page.
- `docs/PROJECT_STATUS.md` is the durable PM snapshot.
- `reports/model_command_center_latest.txt` is generated locally and is not committed.
- GitHub Pages should serve the dashboard shell only, not private tracker data.

## Collaboration Rule

When Codex or Claude changes the process, it should append a short note through
the command center so the next model inherits the latest context:

```bash
python3 inferno_model_command_center.py note --author codex --title "Short title" --body "What changed and why." --tags cleanup
```
