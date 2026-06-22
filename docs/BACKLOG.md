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

### #9 — Volatility context on approval candidates
- **Owner:** codex
- **Why:** IV rank or percentile can provide context, but a single threshold
  cannot choose debit versus credit by itself. The candidate also needs term
  structure, event proximity, expected realized movement, and net Greeks.
- **Done signal:** approval candidates show available IV context plus an
  explicit `volatilityThesis`; missing history is labeled unknown rather than
  inferred. No automatic debit/credit block is tied to one IV threshold.
- **Estimate:** ~80 lines + tests.
- **Status:** DONE — current implementation. Approval rows now preserve IV/ATR
  context and explicitly state that IV rank alone cannot select the structure.

### #10 — DTE review trigger and cohort analysis
- **Owner:** codex
- **Why:** theta and gamma become more acute near expiration, but 21 DTE is a
  useful review hypothesis rather than a universal force-close rule.
- **Done signal:** trade management emits a `review-dte-policy` reminder and
  a report compares net R and drawdown by strategy, entry DTE, and exit DTE.
- **Estimate:** ~80 lines + tests.
- **Status:** DONE — current implementation. Trade management emits a 21-DTE
  review flag and `inferno_dte_policy_analysis.py` builds observational cohorts.

### #11 — Binding no-averaging-down rule for options
- **Owner:** claude
- **Why:** adding to a losing options trade changes the original maximum loss
  and makes thesis failure harder to recognize. A later share purchase can
  still occur, but only as a separate portfolio decision with fresh sizing.
- **Done signal:** the trade-management playbook and decision card state the
  distinction; the auditor flags increases in risk on an open losing ticket.
- **Estimate:** ~40 lines + tests.
- **Status:** DONE — `d6944e2` plus current implementation. The playbook rule is
  binding and process compliance detects overlapping losing-ticket risk adds.

### #12 — Process-breach circuit breaker
- **Owner:** codex
- **Why:** two losing outcomes can be ordinary variance. An unplanned entry,
  ignored exit, or sizing breach is direct evidence that the operating process
  failed and should halt new entries for the session.
- **Done signal:** a research-only compliance artifact records process
  breaches and emits a stop-new-entries recommendation without changing
  broker authority.
- **Estimate:** ~80 lines + tests.
- **Status:** DONE — current implementation. `inferno_process_compliance.py`
  can stop new paper entries without changing live authority.

### #13 — Precommitted decision card and journal
- **Owner:** claude
- **Why:** the desk records decisions but needs the contemporaneous thesis,
  disconfirming evidence, max loss, exit plan, confidence, and net Greeks.
  This is a process-control experiment, not a promised profit-factor boost.
- **Done signal:** no paper comparison entry is accepted without a complete
  card; the result is appended only after the pre-trade fields are frozen.
- **Estimate:** ~80 lines + tests.
- **Status:** DONE — `d6944e2` plus current implementation. Paper ledger entries
  now freeze the machine thesis, contradictions, exits, Greeks, liquidity, and
  volatility context.

### #14 — Long-vol premium-hurdle gate
- **Owner:** codex
- **Why:** the desk's 96-observation ledger has a 31.25% move-hurdle beat rate
  and -11.45 percentage points mean realized-minus-implied move. This supports
  restriction, not automatic retirement.
- **Done signal:** each long-vol candidate records implied move, forecast
  realized move, IV-change scenario, break-even, and friction; missing or
  negative edge remains shadow-only.
- **Estimate:** ~90 lines + tests.
- **Status:** DONE — current implementation. Missing or non-positive
  realized-move forecasts keep long vol shadow-only.

### #15 — Turnover and disposition-effect audit
- **Owner:** codex
- **Why:** academic evidence links heavy retail trading to lower net returns
  and documents selling winners faster than losers. The desk needs to know
  whether faster paper cycles improve evidence or merely increase activity.
- **Done signal:** a monthly report shows turnover, decisions per session,
  gross versus net R, winner/loser hold time, exit exceptions, and same-ticker
  re-entry intervals.
- **Estimate:** ~100 lines + tests.
- **Status:** DONE — current implementation. The behavior audit reports
  turnover, holding periods, journal coverage, and rapid ticker re-entry.

### #16 — Wheel feasibility shadow
- **Owner:** claude
- **Why:** cash-secured puts require capital for 100 shares, retain substantial
  downside, and would increase long exposure while the share sleeve is above
  target. The wheel is a structure to compare, not a return promise.
- **Done signal:** a shadow-only report shows assignment capital, downside
  stress, after-spread yield, covered-call opportunity cost, and comparison
  with a share limit order. No ticket staging.
- **Estimate:** ~120 lines.
- **Status:** DONE — current implementation, shadow-only. Current output is
  correctly marked stale until the Schwab options tape refreshes.

### #17 — Net-R expectancy ledger per strategy family
- **Owner:** codex (lives in performance-analytics lane)
- **Why:** raw dollars cannot compare structures with different maximum loss,
  and gross P/L hides spread/slippage. The desk has only one scored outcome,
  so all sizing conclusions remain provisional.
- **Done signal:** the report shows count, gross R, friction, net R, win rate,
  average win/loss, expectancy, drawdown, and confidence interval by family.
- **Estimate:** ~80 lines + tests.
- **Status:** DONE — current implementation. Paper and shadow remain separate,
  risk-passed and risk-failed cohorts remain separate, and modeled friction is
  labeled rather than presented as realized slippage.

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
