# thinkorswim paperMoney Sandbox

This is the safe pre-execution lane for the desk.

We do **not** route live orders from this packet. We use it to decide what may
be staged in `paperMoney`, what must stay blocked, and how to capture simulated
fills back into the evidence trail.

## Daily command

```bash
./run_inferno_tos_sandbox.sh
```

This builds a daily session packet from:

- the latest authority manifest
- the execution queue
- the broker-preview layer

## Outputs

- [data/inferno_tos_sandbox_session.json](data/inferno_tos_sandbox_session.json)
- [reports/tos_sandbox_session_latest.txt](reports/tos_sandbox_session_latest.txt)
- [data/inferno_tos_fill_log_template.csv](data/inferno_tos_fill_log_template.csv)
- [data/inferno_tos_fill_log.csv](data/inferno_tos_fill_log.csv)
- [reports/tos_fill_ingest_latest.txt](reports/tos_fill_ingest_latest.txt)

## Rules

- Confirm the account selector says `paperMoney`, not live.
- If the desktop verifier sees a live account, login-only window, or an unknown
  account mode, treat the lane as manual-check only. Do not route exports or
  attempt paper staging until the session is provably `paperMoney`.
- Stage only tickets marked `stage-in-papermoney`.
- Copy the `ticketId` from the sandbox packet into the fill log when possible.
- Respect the daily stage cap.
- Do not override risk sizing by hand.
- Do not route blocked names just because they "look good."
- Log simulated fills into the fill log so the desk can audit outcomes later.

## Import fills

Optional first step if you export into `Downloads`:

```bash
./run_inferno_downloads_manager.sh
```

That scans Downloads for supported broker-style CSVs and appends normalized rows
into the canonical Inferno fill log before ingestion.

After updating the fill log, run:

```bash
./run_inferno_tos_fill_ingest.sh
```

That updates the paper ledger and lets performance analytics learn from actual
paper exits instead of just expiration estimates.

## Why this exists

This gives us a real broker-shaped rehearsal loop before any live adapter gets
even discussed:

1. score and rank the tracker
2. build execution intents
3. build offline broker previews
4. build the authority manifest
5. build the thinkorswim paperMoney session
6. simulate fills and review outcomes

That is how we earn automation. Not by skipping the rehearsal.

## Experimental export bridge

Because there is no official paperMoney export API, true export automation is a
best-effort desktop bridge:

```bash
python3 inferno_tos_export_bridge.py run --dry-run
python3 inferno_tos_export_bridge.py run
```

It is disabled by default and only meant to fire an export shortcut inside
thinkorswim. It does not place trades. It works best if you bind a dedicated
paper-export shortcut or macro in your local setup.

The bridge now enforces a cooldown between live trigger attempts so overlapping
manual runs and background cycles cannot spam the shortcut repeatedly.

## Downloads watch loop

To poll for new exports during the day:

```bash
./run_inferno_downloads_watch.sh
```

Optional installer for a recurring LaunchAgent:

```bash
python3 install_inferno_downloads_watch_service.py status
python3 install_inferno_downloads_watch_service.py install
```
