# Fill-Execution SOP — how to score one clean paper outcome

_The bottleneck to the gate is this loop, done right, ~2–3×/week. Keep it on one
screen. Nothing here is a live order; paperMoney only. You approve every step._

## When to act
Only when `./inferno today` (or the 8:24am brief) shows a candidate as
**approval-ready / operator-routable** — not research-watch, not construction-watch.
If nothing's routable, there is no rep today. Do **not** force a blocked name.

## The 5 steps

**1. Approve (only if the thesis still holds).**
- `./inferno today` → press `y`, **or** `python3 inferno_approval_queue.py approve <TICKER>`
- This stages the paper ticket. It does not place anything.

**2. Key the EXACT structure into thinkorswim paperMoney.**
- Use the **already-open** TOS paperMoney window — do not spawn a new instance.
- Match the candidate exactly: ticker, strategy, both strikes, expiration, contracts.
- Work a limit near the mid; **record your actual net fill** (debit or credit).

**3. Manage and close per plan; record the close fill.**
- When you exit, note the exit net price and the close timestamp.

**4. Fill one row in the capture CSV** — `reports/paper_capture_template_latest.csv`
Columns and what goes in each:
| field | value |
|---|---|
| sessionDate | trade date, YYYY-MM-DD |
| ticketId | from the approved ticket (exact — must match) |
| ticker / strategy / expiration | from the candidate |
| environment | **paperMoney** (required — real-money rows are rejected) |
| paperAccount | your TOS paper account id |
| routeFamily | the strategy family (e.g. SHORT_PREMIUM_DEFINED) |
| orderType | NET_DEBIT / NET_CREDIT / LIMIT |
| contracts | integer count |
| entryPrice / exitPrice | your **actual** net fills (accuracy matters most here) |
| realizedPnl | leave blank if unsure — the desk **derives** it from valid entry/exit |
| status | **closed** |
| openedAt / closedAt | **tz-aware ISO**, e.g. `2026-08-11T09:45:00-06:00` |
| notes | optional |

**5. Import → it scores.**
- The exact import command is printed at the bottom of
  `reports/paper_capture_template_latest.txt`. Run it.
- Verify it counted: scored should tick **1/30 → 2/30** (`./inferno` or
  `reports/promotion_gap_latest.txt`).

## Gotchas that cause a row to NOT score (fail-closed)
- Timestamps not timezone-aware, or close before open → rejected.
- `environment` not paperMoney, or `ticketId` doesn't exactly match a staged ticket.
- Non-integer contracts, negative/blank prices.
- Remember: **fast sims and shadow closes never count.** Only this operator-paper
  path moves the gate.

## The cadence that clears it
2–3 clean rows/week → ~30 in ~10–12 weeks → then, and only then, the edge is
proven and deployable (with your ack, sized to the proof). This SOP is the whole
game now. Everything upstream is automated; this part is you.
