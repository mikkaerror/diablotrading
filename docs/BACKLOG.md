# Inferno Desk — Backlog

**Purpose:** the queue of small (under-100-line) shippable improvements that
either claude or codex can pick up between sessions without re-deriving
context. Items are ranked by leverage. Each one names its owner and a clear
"done" signal so progress is unambiguous.

**Rules:**
- An item must be under-100-lines of code AND require zero new architectural
  decisions. If a task needs design work, it doesn't belong here — it belongs
  in a coordination note for discussion first.
- Owner is exactly one of: `claude` / `codex` / `automation` (run by
  `nightly_optimize.sh`) / `operator` (requires explicit click).
- Mark an item `done: <commit-sha>` once shipped. Don't delete completed
  items for at least 30 days — the history is the audit trail.
- See `CLAUDE.md` §8 for the autonomous-vs-ack boundary. If an item
  crosses that line, the owner is `operator`, not `automation`.

---

## Active queue (top of stack first)

### #1 — Daily NLV + per-position snapshot to CSV
- **Owner:** automation (via nightly_optimize.sh)
- **Why:** unblocks real week-over-week and month-over-month P/L
  reporting. Today's `today.sh` shows only point-in-time NLV; no history.
- **Done signal:** `data/nlv_history.csv` has one new row per nightly run
  with columns `date, nlv, cash, per_ticker_mv...`
- **Status:** SHIPPING NOW (this session)

### #2 — Universe-cap-fit audit
- **Owner:** claude
- **Why:** current slate is 7-12 candidates daily, all hard-blocked because
  the universe has $300+ tickers that don't produce sub-$500 trades. Need
  to know: how many tickers in the current universe DO produce cap-fitting
  candidates? Is the universe the binding constraint?
- **Done signal:** `reports/universe_cap_fit_latest.txt` lists per-ticker
  approximate cost of a standard straddle/strangle and flags which fit
  the current cap.
- **Estimate:** ~80 lines.

### #3 — Long-term-hold flag in live position review
- **Owner:** codex
- **Why:** TE/IREN/HIVE/CLSK are operator-declared long-term-core. The
  while-away packet currently nags them as "hard-blocks-new-capital" which
  is correct from a risk lens but wrong for the operator's stated thesis.
  A config-driven exemption silences the nag for declared holds.
- **Done signal:** `inferno_live_book_review_packet.py` (or wherever the
  classification lives) reads a `data/operator_long_term_holds.json` list
  and suppresses the review verdict for any ticker in that list.
- **Estimate:** ~30 lines + a tiny JSON config.

### #4 — Friction telemetry in today.py
- **Owner:** claude
- **Why:** measure how long the operator stares at the screen before
  approving/rejecting/skipping a candidate. If hesitation runs >30s per
  decision, that's signal we still have a clarity problem.
- **Done signal:** `data/operator_decisions.csv` gains a `seconds_to_decide`
  column. Display is unchanged.
- **Estimate:** ~10 lines.

### #5 — Stepped drawdown banner in today.sh
- **Owner:** claude
- **Why:** when the drawdown stepper flips into `step-1-half` (>10% DD),
  the operator should see a one-line warning at the top of today.sh
  before money/holdings/candidates. Right now it's silent until you
  read the capital_scaling artifact.
- **Done signal:** today.py prints a `⚠ Drawdown banner` line at the
  very top when stepper level is not `normal`.
- **Estimate:** ~15 lines.

### #6 — `./today.sh --quiet` mode for cron
- **Owner:** claude
- **Why:** `nightly_optimize.sh` should run `today.sh` and tee its output
  to a dated file so the morning recap is always one file away. The
  current today.sh expects an interactive prompt and exits cleanly on q,
  but a quiet mode that skips prompts and just dumps the screen is the
  right primitive for cron.
- **Done signal:** `./today.sh --quiet` runs end-to-end with no prompts,
  prints money + holdings + candidates summary, exits 0.
- **Estimate:** ~10 lines. Carefully — this is the kind of flag CLAUDE.md
  §7 warns against. If we add it, the constraint is "only one flag,
  and it only suppresses prompts."

### #7 — Coordination model note on backlog progress
- **Owner:** automation (via nightly_optimize.sh)
- **Why:** at the end of every nightly run, append a single coord note
  listing which items the loop completed. Keeps both agents and the
  operator in sync without dashboard work.
- **Done signal:** `coordination/model_notes.jsonl` gains a daily
  entry from `author: automation` summarizing the nightly run.
- **Estimate:** ~15 lines.

---

## Completed (last 30 days)

(no items yet — this section will populate as the queue churns)

---

## Discussion / blocked (needs operator decision before scheduling)

### Universe rebalance toward small-mid caps
- **What:** filter the current universe to bias toward tickers with
  options chains that produce sub-$500 single-contract trades.
- **Blocker:** universe edits change what's eligible to be traded. That
  crosses the autonomous/ack line (CLAUDE.md §8). Needs explicit
  operator buy-in on the filter criteria before any code lands.
- **Operator question:** would you accept "underlying < $80 AND has
  earnings within 7-21 DTE AND has options OI ≥ 100 on ATM strikes"
  as the inclusion rule, or do you want different criteria?

### Move legacy book to a separate account
- **What:** physically separate TE/IREN/HIVE/CLSK from the trading
  account so the desk doesn't see them at all.
- **Blocker:** this is a brokerage account-level operation the
  desk can't do. Operator action.
- **Operator question:** is this worth doing this week, or fine to
  defer? The current `data/operator_long_term_holds.json` flag (item
  #3 above) achieves the same operational effect without account moves.
