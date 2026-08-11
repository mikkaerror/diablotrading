# Fill-Capture Friction Mission — a `record-fill` command (for Codex)

_Filed 2026-08-11 by Claude, from live operator session._

## The problem
Recording a paperMoney fill today means the operator hand-edits
`data/inferno_tos_fill_log.csv` — 17 exact columns, tz-aware ISO timestamps,
correct `ticketId` match, and manual status transitions — then re-runs the desk.
It's error-prone and it's the friction standing between the operator and 30
scored outcomes. Reps 2–30 need to be one line, not CSV surgery.

## What to build
An operator command that records a fill against an already-seeded, operator-
routable staged ticket, without raw CSV editing:

- **Open:**  `./inferno record-fill <TICKER|ticketId> --entry <price> [--contracts N]`
  → sets `entryPrice`, `status=open`, `openedAt=now` (tz-aware), on the seeded
  fill-log row matching that `ticketId`.
- **Close:** `./inferno record-fill <TICKER|ticketId> --exit <price>`
  → sets `exitPrice`, `closedAt=now` (tz-aware), `status=closed`, then runs the
  existing fill ingest so the outcome scores.
- An interactive prompt fallback is fine if a flag is omitted.

After writing, it should run the fill ingest + re-score and print the new gate
count so the operator sees 1/30 → 2/30 without a second command.

## Hard constraints (evidence integrity — do NOT bypass)
- Write ONLY to a fill-log row whose `ticketId` matches an existing
  operator-routable / sandbox-seeded staged ticket. **Never fabricate a ticket
  or a fill.**
- The operator always supplies the **real** fill prices. This command removes
  the CSV mechanics, NOT the requirement for actual paperMoney execution facts.
- The written row MUST pass the existing fill-ingest validators (tz-aware
  timestamps, exact ticketId match, paperMoney environment, finite non-negative
  prices, chronological open/close). **Reuse those validators; do not weaken
  them.** A malformed row must fail closed exactly as today.
- Research-only. No authority, risk-constant, gate, threshold, eligible-
  universe, or approval change. `liveTradingAllowed` / `brokerSubmitAllowed`
  stay False.

## Definition of done
The operator can open and later close the seeded IREN ticket
(`1be6f96d665a730e`, BUY 40C / SELL 45C Aug 28) with two short `record-fill`
commands and zero CSV editing, and a closed fill scores toward the gate. Covered
by a test that round-trips seed → open → close → scored outcome. Full unittest
discovery, math verify, doctor, diff checks pass; commit per hygiene rules.

## Follow-on (note, not this mission)
The fuller fix is auto-*capturing* fills from thinkorswim so the operator types
nothing — that is the existing TOS-export mission (`inferno_tos_export_*`,
Claude's lane), blocked until a TOS window is open. `record-fill` is the
pragmatic, buildable-now step; TOS auto-capture is the endgame.
