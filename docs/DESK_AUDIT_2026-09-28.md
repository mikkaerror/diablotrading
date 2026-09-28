# Desk audit: knowledge, returns, measurement, assumptions, strategy

Review: September 28, 2026 (Claude, shared research lane, operator-requested).
Research only. No risk constant, broker authority, universe or live-book change.
Builds on, and does not repeat, `ASSUMPTIONS_AND_BIG_PICTURE_2026-09-12.md`
(score provenance and overlap) and `INFERNO_FINAL_FINDINGS_2026-07-09.md`
(long-vol kill, account-scale economics).

## The central judgment

The desk measures *activity* very well (1,500+ shadow tickets, 160 reports,
2,190 tests) and *outcomes* poorly. Three numbers the operator most needs were
missing or wrong: the account's real return, whether the stock picks beat
their own universe, and how many independent experiments the evidence
actually contains. Meanwhile the candidate generator keeps proposing the two
structures its own evidence rates negative, and the one structure with positive
backward evidence (defined-risk short premium) has no route to paper.

## Scorecard (what the numbers actually say)

| Measure | Value | Source |
|---|---|---|
| Account time-weighted return, 2026-06-17 → 09-25 | **−26.7%** | `inferno_account_performance.py` (new) |
| SPY, same window | **+4.1%** | FMP EOD anchors 740.96 → 771.35 |
| Money-weighted P/L (net of +$185 flows) | −$318 | same |
| Drawdown from flow-adjusted high-water | −29.4% now (max −47.6%) | same |
| Drawdown stepper's stored peak | $3,516.60 — **not in NLV history** (max recorded $1,669.91) | peak-integrity check |
| Equity sleeve (IREN, HIVE, CLSK, TE) | 100% of holdings, −38% | `data/nlv_history.csv` |
| Shadow long straddles | 738 rows = **105 events**, event mean −0.13R, 95% CI [−0.27, +0.02] | event-level bootstrap |
| Shadow call debit spreads | 283 rows = **47 events**, −0.58R, CI [−0.73, −0.40] | same |
| Implied vs realised move (long vol) | 27.4% vs 10.3%; beat rate 21.5% (65 events) | expected-move ledger |
| Defined-risk short premium (backward) | +0.20R, CI [0.007, 0.36], 65 events; wing cost not modelled | short-premium study |
| Short premium forward paper records | **0 / 60** | same |
| Scored paper trades | 3 (1 source-reconciled) / 30 | strategy lab |
| Readiness distribution | 87% of rows score 90–100 | score calibration |
| Long-term lane top-5 turnover | 100% replaced between Sep 8 and Sep 28 snapshots | pick scorecard (new) |

## Gaps, best practice, action

### Returns and measurement

| ID | Gap | Best practice | Action | Owner / status |
|---|---|---|---|---|
| M1 | No flow-adjusted return; NLV mixes deposits with results | GIPS-style time-weighted return; money-weighted P/L alongside; always vs a benchmark | `inferno_account_performance.py`, SPY benchmark file appended daily, shown in Desk Editor | Claude — **done** |
| M2 | Drawdown stepper measures from an outlier $3,516.60 peak; deposits can also "heal" drawdown | High-water mark on the TWR index, with outlier rejection | Peak-integrity flag published; stepper should consume `twrDrawdownCurrent` (−29.4% ⇒ step-2 band, not pause) | Codex — mission (capital lane, needs operator ack) |
| M3 | Stock picks never scored against anything | Pre-registered, append-only forward test vs the same universe | `inferno_pick_scorecard.py`: frozen daily cohorts, 21/63/126-session horizons, equal-weight universe + SPY baselines, turnover | Claude — **done**; first 21-session result ≈ Oct 8 |
| M4 | Evidence counted in rows, not independent events (up to 27 rows per event) | Cluster by event; bootstrap at the cluster level | Delegate policy uses event-level bootstrap; reports should too | Claude (delegate) **done**; Codex — expectancy/counterfactual reports |
| M5 | All shadow outcomes scored hold-to-expiry at intrinsic value; the playbook exits earlier | Score the rule you would trade; report both | Score shadow/paper under playbook exits (post-event next-open, take-profit tiers, time stop) alongside hold-to-expiry | Codex — mission |
| M6 | Features not stored at entry: ivRank 0/1025, implied move 0/1025 | Snapshot every decision input at entry | Store ivRank, IV, implied move, DTE, readiness on each record; counterfactual "iv-cheap" filter currently tests nothing | Codex — mission |
| M7 | Friction for fills is modelled, not measured | Record actual paperMoney fills vs mid; calibrate slippage | Existing fill-ingest path; start logging every paperMoney fill | Operator habit + existing tooling |

### Assumptions

| ID | Assumption | Evidence | Action |
|---|---|---|---|
| A1 | High readiness means a better trade | 87% of rows at 90–100; buckets non-monotonic | Re-express readiness as a percentile within each day's universe before any threshold use (Codex) |
| A2 | Long-term score ranks names | 8 names tie at the 9.99 cap; top-5 fully churns in 3 weeks | Remove the hard cap or break ties by a documented rule; scorecard now measures it |
| A3 | Paper evidence transfers to live | Paper cap $2,000 vs live formula cap $277 (0.317×NLV); a $1,510 straddle is 177% of NLV | Tag each paper ticket with live-feasibility; prefer structures that fit the live cap |
| A4 | Two ledgers describe one desk | Cloud ~495 tickets vs Mac 105 | Mac is canonical (Codex doc 2026-09-27); approvals are local-only |

### Strategy

| ID | Finding | Action |
|---|---|---|
| S1 | The idea generator is structurally long-vol: tracker `setupRec` is Straddle for 70 names, Vertical Call for 35. Both families are negative on the desk's own evidence (debit spreads decisively). | Delegate now auto-rejects a family whose event-level 95% upper bound is below zero (call debit spreads today). Changing the tracker's default setup is a universe/tracker edit: **operator decision**. |
| S2 | The only positive backward signal (defined-risk short premium, +0.20R) has no path to paper: 0/60 forward records. | Route cap-fitting defined-risk condors / put-credit spreads from the construction watchlist into paper tickets under the same gates (Codex, strategy lane). This is the highest-value research experiment on the desk. |
| S3 | Long straddles are *probably* negative but not proven at the event level (CI crosses zero). The literature's exception is "implied cheap vs history", which the desk cannot test (M6). | Keep paper-testing long vol only where the ticker's own evidence is positive; store IV features so the exception becomes testable. |
| S4 | July economics: the strategy cannot pay for its data below a $5–10k account. | An incoming cash payment changes this input. Decide the split before it lands (Codex mission: cash-landing recommender, operator ack). |

### Portfolio and operations

| ID | Finding | Action |
|---|---|---|
| P1 | Holdings are four correlated miners/energy names (100% of equity, −38%) and none is in the desk's own long-term lane. | Measurement only: the Desk Editor shows them daily with the never-add rule. Any rebalance is the operator's call. |
| O1 | 202 modules, 160 reports; 33 skills silent and 26 stale. | Retire or archive silent modules (Codex, artifact lifecycle). Fewer, trusted numbers beat more numbers. |
| O2 | Shadow volume grows ~1 ticket per candidate per day with no new information. | Cap shadow inserts to one per event per structure (Codex). |

## What was applied today

- `inferno_account_performance.py` + tests: TWR, money-weighted P/L, TWR
  drawdown, SPY comparison, peak integrity. Seeded `data/inferno_benchmark_prices.csv`
  (FMP anchors) and `data/inferno_external_flows.csv` (two pre-ledger flows,
  marked *inferred*).
- `inferno_pick_scorecard.py` + tests: pre-registered cohorts (seeded with the
  Sep 8 point-in-time snapshot), fixed horizons and baselines, turnover.
- `inferno_paper_delegate.py`: new `family-answered` rule at the event level.
- Desk Editor shows the flow-adjusted return vs SPY and hides the unsupported
  peak; the 07:20 agent runs performance and scorecard before writing.

## Falsifiers (what would change these conclusions)

- M2: a broker statement showing NLV near $3,516 on 2026-08-15.
- S1/S3: long-straddle event-level CI moving above zero with stored IV features.
- S2: the first 30 forward short-premium paper events with a negative clustered mean.
- M3: picks beating the equal-weight universe at 63 sessions across ≥10 cohorts.
