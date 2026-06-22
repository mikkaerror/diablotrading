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
- **Status:** DONE — commit `d9c9dd2`. First row written `2026-06-17 $1,007.57`.

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
- **Status:** DONE — current cleanup. `TE`, `IREN`, `HIVE`, and `CLSK`
  are declared long-term holds; they remain visible in live-book review but
  no longer hard-block fresh-capital review solely from fragile short-term
  alignment.

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
- **Note 2026-06-17:** codex shipped `_freshness_label` and source-age
  labels in today.py (commits `c916113`, `5787ae1`). Overlapping but
  different — codex covers artifact staleness, this item covers
  drawdown tier. Still leverage in shipping this one.

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

### #8 — Capital flow advisor (harvest options → buy shares)
- **Owner:** claude
- **Why:** docs/CAPITAL_FLOW_POLICY.md defines the policy (Standard bands,
  $200 harvest trigger, 80% sweep, TE/IREN/HIVE/CLSK conviction list).
  This item operationalizes it: a small module that reads policy + closed
  paper outcomes + current live positions, computes the harvest
  recommendation, writes a report. Adds a `Harvest:` block to today.sh
  when the trigger fires.
- **Done signal:** `inferno_capital_flow_advisor.py` writes
  `data/inferno_capital_flow.json` and `reports/capital_flow_recommendation_latest.txt`;
  today.sh shows a `Harvest:` block when realized PnL ≥ $200 over the
  trailing 14 days.
- **Estimate:** ~150 lines. Blocked on: 30+ closed paper outcomes
  existing so realized PnL is computable. Today: 0 closed outcomes,
  so the module would correctly report "no harvest yet."
- **Note:** Even with 0 closed outcomes, shipping the module is useful
  because it surfaces "harvest trigger requires $X more realized PnL"
  in the daily report, making the goal concrete.

---

## Discipline-research backlog (from TRADING_DISCIPLINE_RESEARCH_2026-06-22.md)

These nine items distill the 2026-06-22 deep research on strategy, sizing,
positioning, taking profits, moving on quickly, and emotion. Ranked by
expected leverage. Each one is small, owned, and has a clean done signal.

### #9 — IV Rank surfaced on approval-queue candidates
- **Owner:** codex (lives in strike-side / paper-director artifacts)
- **Why:** Lane A (debit/long-vol) and Lane B (credit) should be picked with
  awareness of IV rank. Current approval queue shows readiness score but
  not IVR. Operator can't sanity-check strategy fit at decision time.
- **Done signal:** `data/inferno_approval_queue.json` items gain an
  `ivRank` field (52-week percentile from Schwab option chain); `today.sh`
  prints it next to readiness. Lane mismatch (e.g., debit pick at IVR>60)
  shows a one-line yellow flag, not a block.
- **Estimate:** ~50 lines.
- **Status:** pending. Research: see §3 of discipline doc.

### #10 — 21 DTE force-close verdict in trade-management auditor
- **Owner:** codex (owns `inferno_trade_management.py`)
- **Why:** tastytrade research across 200k+ trades shows holding past 21 DTE
  has the worst theta/gamma trade-off in the option lifecycle. Current
  time-stop only fires at DTE ≤ 2 (hard) or ≤ 3 (when flat). Adding a
  "trim at 21 DTE for Lane B credit" and "review at 21 DTE for Lane A"
  verdict captures the bulk of the evidence-backed exit edge.
- **Done signal:** trade-management auditor emits `trim-21-dte` (Lane B
  credit) and `review-21-dte` (Lane A) verdicts in addition to existing
  ladder; tests pin the threshold.
- **Estimate:** ~40 lines + tests.
- **Status:** pending. Research: see §4 of discipline doc.

### #11 — "No averaging down" rule in trade-management playbook
- **Owner:** claude (docs only)
- **Why:** 68% of retail traders who add to losing positions see losses 2.8x
  greater than initial risk. The desk has never proposed averaging down,
  but the rule needs to be a binding line in the playbook before the
  temptation arrives. Pre-commitment is the only working defense.
- **Done signal:** `docs/TRADE_MANAGEMENT_PLAYBOOK.md` gains a "Binding:
  no averaging down" section. `today.sh` shows the rule as a one-liner
  when MTM shows a position at -50% or worse.
- **Estimate:** ~10 lines doc + ~15 lines today.py.
- **Status:** pending. Research: see §5 of discipline doc.

### #12 — Tight de-risker: -2% drawdown OR 2 consecutive losses → halve cap
- **Owner:** codex (owns risk-policy / capital-scaling lane)
- **Why:** current drawdown stepper fires at 10/20/30% tiers — too wide for
  a $1,600 account where two $300 losses puts us at -38%. Research-backed
  protocol: after 2 consecutive losses OR -2% drawdown, halve the
  per-ticket cap for the next 5 tickets. Resume normal sizing when balance
  returns to peak.
- **Done signal:** `inferno_capital_scaling.py` adds an early-warning
  multiplier (separate from the 10/20/30 stepper); tests pin the trigger
  and recovery conditions.
- **Estimate:** ~60 lines + tests.
- **Status:** pending. Research: see §2 of discipline doc.

### #13 — Two-field decision journal on approve/reject
- **Owner:** claude
- **Why:** `data/operator_decisions.csv` currently logs decisions but not
  *why*. Adding a one-sentence rationale and 1-10 confidence prompt at
  approve/reject time creates a learnable feedback dataset for monthly
  review. Pre-trade checklist trades outperform by 15-30% profit factor
  per research; the act of pausing to articulate is the value.
- **Done signal:** `today.py` prompts for `rationale:` and `confidence:`
  fields on approve. CSV gains two columns. Display unchanged.
- **Estimate:** ~25 lines.
- **Status:** pending. Research: see §6 of discipline doc.

### #14 — Lane A retirement debate (decision item)
- **Owner:** operator (needs explicit call)
- **Why:** SSRN 2024 backtest of S&P 500 earnings straddles 2011-2021 shows
  -9% average return after transaction costs. Apple straddles: 41% win
  rate, -1.3% avg annual. Inferno desk runs long-vol-into-earnings as Lane
  A. MOD's -$350 close was expected outcome, not bad luck. Either retire
  Lane A or restrict it to specific narrow filters (IVR<25 at entry; only
  post-earnings vol-expansion plays; no day-before-earnings entries).
- **Done signal:** explicit operator decision logged in
  `coordination/model_notes.jsonl` — "retire Lane A" / "restrict Lane A
  to filter X" / "keep Lane A; willing to lose -9% avg as cost of
  optionality on tail moves."
- **Estimate:** decision only; if "restrict", ~30 lines of strategy-lab
  filter code.
- **Status:** pending operator. Research: see §1 of discipline doc.

### #15 — Default DTE preference 35-50 for auto-paper
- **Owner:** codex (owns strategy lab)
- **Why:** tastytrade 200k-trade research shows 45 DTE entry / 21 DTE exit
  is the best risk-adjusted return window across credit spreads. Current
  strategy lab picks shorter (often 7-21 DTE around earnings). Shifting
  the default preference to 35-50 DTE captures the theta/gamma sweet
  spot.
- **Done signal:** strategy lab's expiration-selection logic prefers 35-50
  DTE when no event window forces otherwise; falls back to shorter only
  when the trade-around-event filter requires it.
- **Estimate:** ~40 lines + tests.
- **Status:** pending. Research: see §4 of discipline doc.

### #16 — Wheel lane scaffold (CSP on conviction names)
- **Owner:** claude (research-only scaffold first; operator decides activation)
- **Why:** wheel strategy on conviction holds (TE/IREN/HIVE/CLSK) is the
  cleanest historical edge for a small account — 1-3%/month on deployed
  capital with no blow-up risk because you wanted the shares anyway. This
  is the operationalized harvest mechanism from CAPITAL_FLOW_POLICY but in
  reverse: instead of harvesting options profits to buy shares, you sell
  options to collect premium while you hold them.
- **Done signal:** `inferno_wheel_advisor.py` reads conviction holds, finds
  ~30 delta OTM puts at 30-45 DTE on each, computes premium-yield-on-cash
  and breakeven-vs-current-price, writes
  `reports/wheel_advisor_latest.txt`. Research-only, no orders.
- **Estimate:** ~120 lines. Blocked on: nothing technical; blocked on
  operator desire (current sleeve is at 62% conviction vs 50% target, so
  the wheel would tilt MORE long, which may be wrong now).
- **Status:** pending operator. Research: see §1 of discipline doc.

### #17 — Expectancy ledger per strategy family
- **Owner:** codex (lives in performance-analytics lane)
- **Why:** expectancy = (WinRate × AvgWin) − (LossRate × AvgLoss). Need 30+
  outcomes for meaning, 100+ for reliability. We have 1. Starting the
  ledger now means we have real data the moment we hit 30. Currently
  performance_analytics shows expectancy as `None` until counts exist —
  the addition is to break it out per strategy family (Lane A debit /
  Lane B credit / Lane B debit / wheel) so we can compare families
  separately.
- **Done signal:** `reports/expectancy_ledger_latest.txt` has per-family
  rows with the 5-tuple `count, wins, losses, avgWin, avgLoss, expectancy`.
- **Estimate:** ~50 lines.
- **Status:** pending. Research: see §2 of discipline doc.

---

## Completed (last 30 days)

- 2026-06-17 — #1 — Daily NLV + per-position snapshot to CSV — claude/d9c9dd2
- 2026-06-17 — #3 — Long-term-hold flag in live position review — codex/current cleanup
- 2026-06-17 — risk_policy test isolation fix (drawdown stepper regression) — claude/this cleanup
- 2026-06-17 — today.py source freshness labels — codex/c916113, codex/5787ae1
- 2026-06-17 — today.py stale-broker-truth labelling — codex/2bb8030

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
