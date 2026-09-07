# Weak-Point Audit — 2026-09-07 (Claude session)

Operator asked for an aggressive pass over the desk's models and assumptions.
This is what was found, what was fixed this session, and what is queued for
Codex. Research-only throughout: no authority, risk constant, universe,
ticket, or broker path changed.

## 1. FIXED — the ATM reference series was the expiring/expired 0-DTE chain

`inferno_schwab_options.nearest_atm_pair` walked expirations in ascending
order and took the first one with a mid. Every scheduled snapshot lands at
16:20 MT, i.e. after the close — so on any expiration day (every Friday, and
daily for names with daily expiries) the ATM window, straddle mid, implied
move, fill-friction model, and both liquidity gates were computed on a series
that had just expired: penny quotes, 50–200% spreads, "expected move" of
0.8%.

Blast radius on the 2026-09-04 tape: 8 of 12 rows graded on the dead series;
12 of 12 failed the paper liquidity gate. Regrading the *same stored
snapshot* with a `>= 1 DTE` floor:

| symbol | before (dead series) | after (next live series) |
|---|---|---|
| ORCL | exp 09-04, spread 54%, straddle $1.27, move 0.8%, quality 48/poor, paper FAIL | exp 09-11, spread 3.4%, straddle $18.55, move 11.7%, quality 87/institutional, paper PASS |
| QCOM | exp 09-04, spread 124%, move 0.8%, paper FAIL | exp 09-11, spread 5.7%, move 4.2%, quality 75/usable, paper PASS |
| IREN | spread 56%, paper FAIL | spread 3.1%, quality 86, paper PASS |
| CLSK | spread 198%, paper FAIL | spread 16.8%, quality 61/fragile, paper PASS |
| AAOI | spread 105%, paper FAIL | spread 20.6%, near-miss on the 20% gate |

The desk's #1 candidate had been liquidity-blocked for weeks by this, and the
`paper_blocker_swarm` dutifully classified it as a real "liquidity" lane
blocker. The `liquidity_premium_matrix`, expected-move ledger, and any
research that consumed `atmImpliedMovePct` inherited the same garbage.

Change: `ATM_MIN_DTE = 1`; `nearest_atm_pair(..., min_dte=)` skips sub-floor
series and falls back to the legacy pick only when nothing qualifies, flagging
`atmSeriesFallback` / `atm-series-fallback-sub-min-dte`. New row fields:
`atmDaysToExpiration`, `atmSeriesFallback`, `atmSkippedExpirations`.

Also added an offline `--regrade` path (`regrade_row` / `regrade_report`) so a
stored tape can be re-summarized under current rules without a network call;
the snapshot's prices, contracts, and `generatedAt` are untouched and the
report carries `regradedAt` + `regradeRule`. The 09-04 tape and daily-ops
lanes were regraded this session: 3 tradable-research, 1 paper-ready, 1
manual-review, 7 avoid-chain (was 0/0/0/12).

Tests: `tests/test_inferno_schwab_options.py` +7 (dead-series exclusion,
fallback flagging, explicit `min_dte`, session classification, off-hours
labelling, regrade provenance).

## 2. FIXED — quote-session provenance

Every Schwab contract carries `quoteTimeInLong`. The tape now records
`quoteAsOf`, `quoteSession` (`regular` / `late-close` / `off-hours` /
`unknown`), `quoteSessionIsRegular`, `spreadEvidenceQuality`, and a
`<session>-quote-snapshot` flag for non-regular sessions. Gates still fail
closed; this labels *what kind of evidence* a spread verdict is.

Finding: the 16:20 MT snapshot's quotes are all stamped 16:00:0x ET — the
closing print. That is a fair spread reference (market makers have not
pulled yet), so `late-close` is acceptable evidence. The 06:45 MT snapshot
is pre-market and will carry the *previous* close's quotes.

## 3. FIXED — test rot

- My 2026-09-04 nightly trim prefixed shared steps with `shared:` and broke
  five `test_nightly_optimize` ordering tests. Tests now normalize the prefix
  and add a guard that nightly-unique steps stay unprefixed.
- `test_inferno_paper_capture_template` and `test_inferno_paper_scoring_loop`
  hard-coded `expiration: 2026-08-21`; the template correctly drops expired
  tickets, so nine tests rotted on 08-22. Fixtures now use `today + 45d`.

Suite: 1974 tests pass; math verify 0 violations; secret hygiene clean;
`git diff --check` clean.

## 4. QUEUED (Codex lane) — fail-closed modules clobber the last good artifact

Three modules replace a good artifact with an empty/failed one when their
upstream is unavailable, instead of preserving it:

- `inferno_schwab_options.build_report` → `save_report` writes a
  `not-configured` report with zero rows over a 12-row tape when no token is
  present (observed this session from a Linux VM without the keychain token).
- `inferno_schwab_daily_ops.live_chain_report` calls that path
  unconditionally, so `--skip-refresh` still clobbers.
- `inferno_strike_selector build` saves a `0 ok / 1 failed` plan over the
  last good plan when yfinance is unreachable.

Downstream, the command center then reads "no Schwab rows" as truth. The
SYSTEM_MAP already specifies the lifecycle contract for ledgers
(`lastAttemptAt` may advance; `lastSuccessfulAt` may not). Extend that
contract to the tapes: on a non-`ok` status with an existing multi-row
artifact, write the attempt/failure record and keep the rows.

## 5. QUEUED (Codex lane) — promotion-gap win-rate floor from n=3

`promotion_gap_latest`: payoff ratio 0.0938 from three scored trades implies a
breakeven win rate of 0.914 (+0.03 margin → 0.944 floor). A payoff estimate
from n=3 has no statistical content; the floor it implies is not a gate the
desk can ever clear or fail meaningfully. Recommend: below a minimum sample
(say 10 closed outcomes per structure), shrink the payoff ratio toward the
structure's theoretical max-profit/max-loss ratio (a $5-wide debit spread
bought at $2.75 has a 0.82 payoff, not 0.09), and label the floor
"prior-dominated" until then. The 30-count gate stays binding regardless.

## 6. QUEUED (shared) — shadow slate is still a long-vol, cap-busting monoculture

All 12 shadow scenarios are `Straddle` / `Vertical Call`, including STX at
$849 and EME at $754 against a $500 construction cap. The tracker's setup
label drives this. The cap-fit alternative audit exists but only runs for a
blocker-swarm-identified candidate. Recommend running cap-fit construction at
shadow-slate generation so shadow evidence accrues on structures the desk
could actually stage.

## 7. OBSERVED — snapshot cadence never sees a regular session

06:45 MT (pre-market) and 16:20 MT (post-close) are the only chain fetches.
With the session label in place, one regular-session snapshot (e.g. 11:30
MT) would give the gates a live-spread reference. Adding a LaunchAgent is an
operator decision; not changed here.

## 8. OBSERVED — evidence velocity is the binding constraint, and it is an operator-fill problem

0.47 closed outcomes/week → ~58 weeks to 30. 88 of 105 ledger rows expired
never-opened. With the gate fixed, candidates will reach "operator-routable"
more often, but a routable ticket only becomes evidence when a paperMoney
fill is recorded. Whether the 5 quarantined fast-paper simulations should
ever count toward the gate is an operator policy call; the promotion
lineage ledger keeps them separate today and nothing here changes that.

## Session provenance

- Codex was active concurrently in the calibration lane
  (`mission-d0ff267e`; `inferno_score_calibration.py`, shadow/scenario/paper
  entry-score snapshots). No file overlap; each agent committed by path.
- Files changed by Claude: `inferno_schwab_options.py`,
  `tests/test_inferno_schwab_options.py`, `tests/test_nightly_optimize.py`,
  `tests/test_inferno_paper_capture_template.py`,
  `tests/test_inferno_paper_scoring_loop.py`, this document,
  `coordination/` note + mission.
- Artifacts regraded from stored data (no broker call): `data/inferno_schwab_options.json`,
  `reports/schwab_options_latest.txt`, `data/inferno_schwab_daily_ops.json`,
  `reports/schwab_daily_ops_latest.txt`, `reports/paper_test_director_latest.txt`.
  The strike plan was restored to its 09-04 state after a failed refresh.

## 9. ROOT CAUSE FOUND — the recurring zero-byte `.git/index.lock`

The 2026-08-15 lock that jammed commits for three weeks was not a crash. A
Claude session linked through the desktop app runs in a Linux VM with the
repo mounted, and that mount cannot unlink files. Git creates `index.lock`
(and `HEAD.lock`, `objects/maintenance.lock`, `tmp_obj_*`) and then fails to
remove them — even a plain `git status` leaves a zero-byte `index.lock`
behind. Reproduced this session; cleaned by renaming the files into
`_to_delete/` (rename is allowed, unlink is not). `_to_delete/` is in
`.git/info/exclude`; the operator can delete it.

Rule for linked Claude sessions: after any git command, check for
`.git/*.lock` and `.git/objects/**/tmp_obj_*` and move them aside. Codex
sessions on the Mac are unaffected.

---

# Part 2 — thresholds vs. the universe we actually trade (same session)

Operator question: "we trade semis, construction, big movers, big players;
options are pricier because of the upside — are we accounting for this?"
Short answer before this pass: no. Detail below.

## 10. FIXED (descriptive rebase) — the premium hurdle judged event moves against a *daily* range

`inferno_expected_move_ledger.premium_hurdle` divided the event-implied move
by trailing daily ATR% and called ≤1.25× "reasonable", >3.0× "extreme"
(−20 rank points). An earnings gap is normally a multiple of a daily range,
so the ladder demoted the desk's own universe by construction: ORCL at
11.97% implied / 3.9% ATR = 3.05× → "extreme", score 64.4 → 44.4.

Evidence (new `inferno_event_move_calibration.py`, from the local Schwab
price-history tape, 20 names / 68 volume-confirmed large-move days):

| | p25 | median | p75 | p90 |
|---|---|---|---|---|
| realized 1-day move | 9.3% | 14.2% | 17.7% | 24.7% |
| move ÷ daily ATR | 1.64× | 2.13× | 3.00× | 4.09× |

82% of those days exceed the old "reasonable" ceiling; 25% exceed "extreme".

Codex review caveat, accepted: this sample is outcome-selected (largest
moves of the year, some non-earnings) and one-day horizon versus a
days-to-expiration implied move, so it overstates typical event moves and
inflates implied/realized ratios. Therefore:

- The ATR ladder is rebased to **2.0 / 3.0 / 4.0** (reasonable / stretch /
  hard; extreme above) — at or below the tail-selected quantiles — and
  labelled a descriptive rebase, not a fitted calibration. Legacy label is
  reported alongside (`legacyPremiumHurdleLabel`).
- A per-name historical basis (`implied ÷ name's median realized earnings
  move`, ladder 1.0 / 1.3 / 1.6) is used **only** when the row comes from a
  curated earnings backfill (`inferno_earnings_history_import.py`). Inferred
  tail history is shown as `descriptiveTailMedianMovePct` and never sets the
  label.
- ORCL today: "hard" (−12) instead of "extreme" (−20); pressure 52.4.

The calibration artifact is refreshed nightly (`nightly_optimize.sh`,
nightly-unique step), read by doctor and the command center, and carries a
`biasDisclosure` block. Filling `data/earnings_history_template.csv` with
real earnings dates and pre-print implied moves is the single highest-value
data task for the hurdle; the importer already exists.

## 11. OBSERVED — the same tape says long premium into these prints has not paid

The ledger's 11 closed long-straddle shadow records beat the breakeven move
9.1% of the time (edge −9.7%, mean R −0.36). Fixing the hurdle removes an
unfair demotion of high-beta names; it does not mean paying the straddle is
right. The defined-risk and `SHORT_PREMIUM_DEFINED` arms exist for exactly
this, and the richness signal (`inferno_earnings_richness_signal.py`) is
empty until §10's backfill lands.

## 12. FIXED (label) / OPERATOR (fix) — the chain strike window stops short of the expected move

`SCHWAB_OPTIONS_STRIKE_COUNT=24` (env-overridable) fetches ±12 strikes.
ORCL 2026-09-04: window ±10.6% of spot on the weekly vs 11.7% implied;
on $750+ names with $5 strikes the window is ~±7% against 13–19% realized
moves. Strike selection cannot see the strikes the event calls for. The
tape now reports `chainStrikeWindowPct` / `strikeWindowCoversImpliedMove`
and flags `strike-window-below-implied-move`. Fix is operator config:
`SCHWAB_OPTIONS_STRIKE_COUNT=64` in `.env.inferno` (payload ~2.5×; a
`fromDate`/`toDate` bound to 0–75 DTE in the adapter would pay for it —
Codex lane, mission filed).

## 13. QUEUED (Codex) — cap-fit widths are absolute dollars

`CAP_FIT_DEBIT_MAX_WIDTH = 5.0`, `CAP_FIT_CREDIT_MAX_WIDTH = 1.0` in
`inferno_strategy_alternative_pricing.py`. On STX ($849) a $5-wide spread is
0.6% of spot against a 13–19% event move; on CCOI ($10) it is 50%. Widths
should be expressed in expected-move units (e.g. ≤ 0.5 × implied move $)
and then capped by the ticket band. Related: `MAX_SINGLE_TICKET_DOLLARS=500`
is operator-owned; on big players it forces structures that are too narrow
to express the thesis. If the cap stays, the honest research answer is fewer
names, not narrower spreads — a recommender, not a constant edit.

## 14. OBSERVED — bucket labels are tuned for a calmer universe

`expected_move_bucket`: quiet <3%, normal <6%, hot <10%, "inferno" ≥10%.
The universe median realized move is ~14%, so most names read "inferno"
by construction; today that only produces a warning. Cosmetic, left alone.
