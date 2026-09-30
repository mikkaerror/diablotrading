# Desk Operating Plan — 2026-09-30

Working plan for Claude and Codex. Mikka approved the direction on 2026-09-30.
Read this before picking up work; update the **Status** column and the log at
the bottom when you finish something. Safety perimeter and lanes (CLAUDE.md
§1, §8) are unchanged: nothing here touches `liveTradingAllowed`,
`brokerSubmitAllowed`, `BROKER_ADAPTER_MODE`, `submit_live_order`, or lowers
any risk constant.

## 1. Where we are (facts, 2026-09-29)

- Account: NLV $850.25, flow-adjusted TWR −26.7% since 2026-06-17 vs SPY +4.1%;
  TWR drawdown −29.4%; drawdown protocol = pause (no new live entries).
  3 live holdings are past the −20% rule.
- Promotion gate: **1/30** source-reconciled operator-paper outcomes
  (`reports/promotion_evidence_lineage_latest.txt`). The "3 scored" in
  performance analytics includes 2 intrinsic-value estimates that do not
  count. **The lineage number is the truth.**
- Paper funnel since April: 105 tickets → 96 blocked by gates → 6 rejected →
  3 staged → 3 closed → **1 qualified**. Only 6 tickets were created in
  September.
- Top block reasons (count): over single-ticket cap 49 · poor Schwab quote
  quality 28 · over daily-loss cap 27 · reward/risk below debit floor 22 ·
  thin ATM liquidity 22 · wide/untradeable ATM spreads 37.
- Most proposals are LONG_STRADDLE / CALL_DEBIT_SPREAD — the buy-premium
  program is already a KILL (`docs/DECISIVE_MOVE_EDGE_KILL_2026-07-07.md`), and
  the delegate rejects "shadow-answered" families. **The funnel mostly
  proposes structures we already know lose, at sizes that don't fit.**
- **Split brain (the biggest leak).** Cloud Run `diablotrading-strikes`
  (07:45 MT) stages paper tickets into its own ledger and approval queue in
  `gs://ohsheetohsheet-inferno-state` (~495 tickets, $500 cap because the
  deploy doesn't pass the paper budget). The Mac ledger has not been written
  since **2026-09-07**, and no Mac job runs `--record-ledger`. So: the paper
  delegate approves in the Mac queue, which the cloud never reads; Mac fill
  imports land in a ledger the cloud never reads; and every Mac evidence
  report (lineage 1/30, funnel) is scoring a 3-week-old snapshot. Codex
  already wrote the fix proposal: `docs/CLOUD_LOCAL_LEDGER_OWNERSHIP_2026-09-27.md`
  (Mac canonical, cloud read-only, reviewed cutover). It needs Mikka's go (D5).
- Live hypotheses: (a) defined-risk short premium around earnings — backward
  lead, prereg v2 collecting (`docs/SHORT_PREMIUM_PREREG_V2_2026-09-29.md`);
  (b) Capex Flow long-horizon shares lane — pick scorecard running; (c)
  long-term accumulation lane.

## 2. Roster

| Role | Who / where | Status |
|---|---|---|
| Data engine (dawn + nightly launchd) | Mac | working |
| Strike selector + action pulse | Mac (Codex lane) | working; proposes the wrong mix (see §1) |
| Paper delegate (rule-based approvals) | `inferno_paper_delegate.py` (Claude) | working |
| Desk Editor email + 7:20 Gmail watchdog | `inferno_desk_editor_mailer.py` via dawn (Claude) | first Mac send 2026-09-30 |
| Research views (TWR, vol edge, capex flow + sizing, pick scorecard, short-premium shadow) | Claude | working |
| Cowork watch tasks (verdict, hygiene/boundary audit, sprint scorecard, basket, Schwab reminder, candidate brief) | Cowork desktop | working |
| Capex tape analyst | scheduled 2026-11-02 | scheduled |
| Earnings analyst (thesis-card grade the morning after each report) | cloud scheduled tasks: GNRC/TEL 10/29, MPWR 10/30, IREN 11/06, HIVE/TE 11/13, CLSK/CLFD 11/25, CRDO 12/01 | scheduled (email only) |
| Earnings-date checker (confirm/moved dates, next 3 weeks) | cloud scheduled task, Sundays 16:47 MT | scheduled (email only) |
| Second opinion (ChatGPT) | no API key | vacant (decision D2) |
| **Ledger owner** (one writer for tickets, approvals, fills) | Codex | **W0 active on Mac; cloud read-only deployment verified** |
| **Funnel fixer** (propose what can pass, sized to fit) | Codex | **W1 construction/diagnostic fixes tested; five dawn sessions + boundary audit pending** |
| **Controller** (one true count, clean ledgers, CI green) | Codex + Claude | **W2 complete; hosted Inferno CI green on main** |
| **Fill clerk** (60-second order card + fill capture) | Claude | **built (W3 steps 1–3); goes live when W0 makes the Mac ledger current** |
| **Chain coverage** (earnings-window chains, midday tape) | Codex | **W4 installed at 13:00 ET; runner coverage tested; 10/13 evidence pending** |
| Live-book risk officer (report-only exit plans) | `inferno_live_book_officer.py` (Claude) | built; "if signed" rules wait for D1 |

## 3. Workstreams

Each has an owner, a definition of done, and a date. Do them in this order.

### W0 — End the split brain (Codex, start now — D5 = Mac, D6 = $2,000; due 10/03)
Implement the cutover in `docs/CLOUD_LOCAL_LEDGER_OWNERSHIP_2026-09-27.md`:
1. Freeze: snapshot both ledgers + approval queues (cloud via gcloud read, Mac
   file) with hashes; no edits to either during the cutover.
2. Reconcile read-only: union by ticketId, flag conflicts, carry provenance.
   Nothing that was a shadow/intrinsic estimate becomes a qualified outcome.
3. One writer: the Mac runs the strike cycle with `--record-ledger` after the
   dawn refresh (then the paper delegate, then the Desk Editor). The cloud
   strike job stops writing the ledger/approval queue and stops sending
   approval emails; it may keep publishing research/quotes.
4. One approval inbox/dispatcher (Mac), and the delegate's approvals stage in
   the next Mac strike cycle.
5. Paper budget parity: the operator's D6 answer decides the cap; record it
   with provenance. Do not change it without that answer.
Done when: approve (delegate or Mikka) → staged in the same ledger the Desk
Editor and lineage read → filled → qualified, on one host, with a test.

### W1 — Realign the paper funnel (Codex, due 2026-10-10)
Goal: the tickets we propose are ones that can pass the gates and test a
hypothesis that is still alive.
1. Report first: add a funnel view (proposed → blocked-by-reason → staged →
   filled → qualified, per week and per strategy) to the promotion/forward
   blocker reports. Reuse 760b6ac's blocker work.
2. Stop spending paper slots on answered families: the delegate already
   rejects them; the selector should not propose them as primaries
   (shadow-answered = ≥15 closes, avg ≤ −0.5R; family-answered = bootstrap
   95% upper < 0 at ≥30 events). Keep them in shadow.
3. Add a defined-risk short-premium paper candidate (iron fly, same
   construction as `inferno_short_premium_shadow.build_iron_fly`) for
   earnings names that pass liquidity gates, tagged
   `arm=SHORT_PREMIUM_DEFINED` so `inferno_short_premium_study.forward_record`
   picks up closes.
4. Size-to-fit: when the only block is size, try 1 lot / narrower wings /
   narrower debit width before giving up. Never raise a cap.
Done when: a week of dawn runs produces ≥ 3 gate-passing candidates on
average and the funnel report shows it. No threshold lowered (nightly
boundary audit must stay green).

### W2 — Controller (Codex primary, Claude for Desk Editor; due 2026-10-03)
1. Fix `tests.test_inferno_schwab_transaction_ledger ...matchedNetCash` (red
   on HEAD since 9256336) and get Inferno CI green on main.
2. One exported number: `promotionTruth.qualified` (lineage) consumed by
   performance analytics text, Desk Editor, strike email and doctor. Label
   intrinsic-estimate closes "estimate — no credit" everywhere.
3. `data/nlv_history.csv` got a blank NLV row on 2026-09-29 (sync blocked).
   Skip the append when NLV is missing instead of writing blanks.
4. Decision archive capture (sqlite) failed with `disk I/O error` when run
   from the Cowork VM mount: retry or queue, never silently pending.
5. Claude: Desk Editor evidence line shows the lineage count + a one-line
   funnel. (Claude — due 2026-10-01.)

### W3 — Fill clerk (Claude, due 2026-10-08)
The operator is the only one who keys an order. Make that step one screen.
1. `inferno_paper_order_card.py` (shared paper lane): for every
   `paper-staged` ticket without a fill, render the exact paperMoney order
   (legs, quantity, limit, time-in-force), the "don't chase past" price, and
   the one command to record the fill afterwards (`inferno_record_fill.py`).
2. Desk Editor puts the cards at the top when any exist.
3. Closing side: when a staged ticket's expiration or exit rule is reached,
   the card says how to close and record the closing fill (so it qualifies
   instead of becoming an intrinsic estimate).
Done when: a staged ticket goes approve → card → keyed → fill recorded →
qualified without Mikka opening any other report.

### W4 — Chain coverage for earnings season (Codex, due 2026-10-12)
Capture-list priority, in order (read-only fetches, raise the limit so they fit):
1. names reporting in 1–10 days (short-premium v2 needs 1–7; Earnings Runner
   arm A needs 3–10 and a capture on the day before the report);
2. names that reported in the last 2 trading days (arm B entries);
3. symbols with an open Earnings Runner record (exits need daily quotes);
4. tickers in `data/operator_earnings_calls.csv` (arm C);
5. everything else.
Plus a second capture 12:30–14:00 ET (the 09:35 tape has the widest spreads).
Don't touch any prereg's gates/structure/skips.
Done when: the week of 10/13 shows ≥ 10 v2 records and ≥ 10 runner-campaign records.

### W7 — Earnings Runner Campaign (Claude — built 2026-09-30)
Mikka asked to play earnings. Pre-registered in
`docs/EARNINGS_RUNNER_PREREG_2026-09-30.md`; collector
`inferno_earnings_runner.py` (arms A run-up, B runner, C Mikka's calls),
scored separately, full crossing, never estimated. Morning email carries the
scoreboard and `python3 inferno_earnings_runner.py call TICKER up|down "why"`.
Depends on W4 for coverage and on W0 before any arm can become real paper
tickets. Read-out mid-Nov.

### W5 — Email consolidation (Claude, after 3 good mornings, ~2026-10-03)
If the Mac Desk Editor lands 9/30, 10/1, 10/2: set `INFERNO_EMAIL_MODE=editor`
(routine morning/strike/pulse suppressed; failures still alert) and retire
the "paper candidate brief" Cowork task (the Desk Editor covers it).
Needs Mikka's OK in chat before flipping.

### W6 — Live-book risk officer (Claude — built 2026-09-30; enforcement after D1)
Report-only weekly hold / trim / exit review of live holdings against
`docs/TRADE_MANAGEMENT_PLAYBOOK.md` and the Conviction Plan. Never sells,
never stages. Blocked until Mikka answers D1.

## Next session — Wed 2026-09-30 (start here)

**First, check (5 min):**
1. Did the 06:00 Mac Desk Editor email arrive? It's the first run after the W0 cutover. Check that the paper ledger `lastSuccessfulAt` is today and that no "paper ledger stale" alert appears.
2. ACN reports 10/01. On 10/02, see whether Earnings Runner arm B triggered (needs ACN in the chain tape; W4 tier 2).

**Claude:**
1. **Deposit clerk:** an order card for the 10/09 deposit (SMH + the named Capex Flow pick, fractional shares, tranche rule). Real-money shares that Mikka keys himself; the desk never trades.
2. **Monthly close:** extend the Sunday review so the first Sunday of each month adds returns vs SPY/SMH, per sleeve and per campaign arm. Needs SMH/SPY in the account-performance packet.
3. **Prereg integrity check:** hash the frozen rule blocks in each prereg doc; alert in the Desk Editor if one changes without a new version.
4. **W5 email consolidation:** check on Friday 10/02. If 3 good mornings, ask Mikka to flip `INFERNO_EMAIL_MODE=editor` and retire the Cowork candidate brief.

**Codex:**
1. W1: five dawn sessions + the boundary audit to close it.
2. W2 complete: main CI is green; retain the controller checks.
3. W0 follow-up complete: ownership tests inject temporary root, receipt and acknowledgement paths; copied Mac receipts and cloud host variables cannot contaminate fixtures. The real wrong-host guard remains tested.
4. D4 complete: tested integrated history is published on main. Ship further repairs only after focused and broader checks.

**Mikka:** D2 (second opinion: fund or retire), D3 (key ~3 paper orders/week once cards appear), the cash-payment plan when the amount is known.

## 4. Calendar

| When | What |
|---|---|
| 09/30–10/03 | D5/D6 answers → W0 cutover; W2; W5 verification |
| 10/05 | Short-premium v1 time-box: record "expired unrun" in the verdict log |
| 10/05–10/12 | W1, W3, W4 |
| 10/08 | First 30-day pick-scorecard horizon (Sep 8 cohort) |
| 10/13–11/14 | Q3 earnings season: **harvest evidence, no new strategies** |
| 11/02 | Capex tape refresh (scheduled) |
| mid-Nov | Review: scorecard, v2 progress, funnel pace → decide what earns capital |

## 5. Guardrails (repeat)

- No new strategy lanes before mid-Nov review; the constraint is evidence,
  not ideas.
- Never lower a gate to make the funnel look better. Size-to-fit and better
  candidate choice only.
- Shadow and fast simulations never earn promotion credit.
- Everything research-only; operator keys every order; live flags stay False.

## 6. Decisions for Mikka

- **D1** Conviction Plan sign-off — **SIGNED 2026-09-30** (sleeves, 7% limit, deposit routing, holds no-new-money + thesis checks, options paper-only to ~$10k). Open: cash-payment plan, retirement-account core vehicle. Reviewed Sunday nights.
- **D2** Second opinion: fund an OpenAI key (cents/day) or retire it.
- **D3** Commit to keying ~3 paper orders a week once W3 cards exist
  (≈ 5 minutes each). This is what actually moves 1/30.
- **D4** Completed 2026-09-30: integrated `agent/storage-hygiene` history published to main after branch CI passed; hosted main CI passed on bf73e00.
- **D5** Approve the ledger cutover: the Mac owns paper tickets, approvals and
  fills; the cloud strike job becomes read-only research. (Recommended.)
- **D6** Paper single-ticket cap after cutover: keep the Mac's $2,000 paper
  budget, or the cloud's $500 default. (Paper only; live caps unchanged.)

## 7. Log

- 2026-09-30 Claude: plan written from funnel/lineage audit.
- 2026-09-30 Claude: W2.5 done (5305569) — Desk Editor shows lineage 1/30 as truth and a 30-day funnel.
- 2026-09-30 Claude: found the split brain (Mac ledger frozen since 09-07; cloud stages from its own GCS queue). Added W0, D5, D6. W3 (fill clerk) waits for W0 — cards are pointless against a ledger nobody stages into.
- 2026-09-30 Mikka answered: D5 = Mac owns tickets/approvals/fills; D6 = $2,000 paper single-ticket cap (paper only). Recorded in coordination/operator_acks/2026-09-30_ledger_cutover.json. W0 unblocked.

- 2026-09-30 Codex W2: normalized UTC Z timestamps for legacy Python transaction reconciliation; installed declared research dependencies in CI (the inspected main failure was missing pandas). Exported promotionTruth.qualified from lineage to analytics, strike digest and doctor; intrinsic closes labeled estimate — no credit. Missing/nonfinite NLV now skips append, preserving historical rows. SQLite indexing has bounded retries, a durable queue receipt and explicit unavailable reports; recovery indexes once without replaying decisions. Focused controller checks and 2,286-test isolated suite passed; CI-profile preflight ready-for-ci. Research-only, no caps, gates or authority changed. Main CI verification pending push/integration; Claude retains Desk Editor ownership.

- 2026-09-30 Codex W1: weekly creation-cohort funnel wired into lineage, research audit, doctor and command center. Recorded fills use paperExecution, qualification uses lineage. Answered families stay in shadow; one primary per ticker favors passing constructions. Added full-cross iron flies through the unchanged v2 constructor with SHORT_PREMIUM_DEFINED arm and delegate-only automated approval. Size-only failures can retry one lot or narrower call verticals with full policy reevaluation; mixed failures remain blocked. Dawn research observations are deduplicated and cannot stage tickets. Acceptance remains pending five real dawn sessions averaging >=3 and independent green nightly boundary audits; W0 remains a separate prerequisite for the canonical ledger. No caps, gates, universe or live authority changed.

- 2026-09-30 Codex W4: earnings dates 1–7 days out now lead the existing snapshot capture slate. The effective capture limit expands to fit every dated event and is propagated through the API adapter (no second truncation). Added a weekday 13:00 ET read-only capture service with window checks, duplicate suppression, failure receipts and doctor/command-center visibility. It calls the unchanged v2 shadow collector; gates, wings, structure and skip rules are untouched. Target remains >=10 v2 records during the week of 10/13; code/tests cannot establish future collection. Scheduler installation follows integration into the canonical Mac checkout.
- 2026-09-30 Claude: W3 built — inferno_paper_order_card.py (enter/close/expired cards with limit, don't-chase price and the exact inferno_record_fill.py command); Desk Editor leads with "KEY THESE IN PAPERMONEY" and headlines "N paper orders to key"; mailer runs it daily. Desk Editor now alerts when the paper ledger hasn't been written in 48h (currently 22 days — the W0 symptom).
- 2026-09-30 Claude: W6 built — inferno_live_book_officer.py. Binding tier now (never add under water §5.4, -20% rule, operator holds never sold by the desk); "if signed" tier from research/conviction_plan_draft.json (survival test 7%, 200-day rule, thesis checks after each earnings, deposit routing) shown but not enforced until data/inferno_conviction_plan_ack.json is active. Desk Editor gets a LIVE BOOK block; mailer runs it daily. Next thesis check: IREN 2026-11-06.
- 2026-09-30 Claude: W7 built — Earnings Runner Campaign pre-registered (0df51c2) and collecting; W4 capture priorities extended for it.
- 2026-09-30 Claude: Schwab login countdown in the Desk Editor (5fc5d77). Hired the earnings analyst (6 one-shot thesis checks) and a weekly earnings-date checker; both email only. Codex: a desk ingest of confirmed dates/timing (FMP calendar) would let the runner campaign use them directly — optional, after W0.

- 2026-09-30 Codex W0: froze idle Mac writers and cloud dawn/strike schedulers (auditor left active); captured hashes and cloud object generations under outputs/ledger-cutover-2026-09-30. Read-only crosswalk: Mac 105, cloud 496; 88 Mac-only, 7 refresh duplicates, 10 conflicts, 479 cloud-only. Mac ledger retained byte-for-byte; all cloud rows quarantined in archive, no imported outcomes. Added canonical host guards, serialized local mutation entrypoints, immutable hash-verified cloud snapshots, generation-checked publication, cloud read-only staging/approval/email behavior, and D6 budget provenance. Isolated approve -> stage -> record entry/exit -> lineage-qualified test passes on one host; 2,326-test suite green. Deployment verification follows before schedulers resume.
- 2026-09-30 Mikka signed D1 in chat; ack data/inferno_conviction_plan_ack.json (copy in coordination/operator_acks/). Live-book officer now labels those lines "plan rule" and the email routes the Oct 9 deposit. Sunday 19:38 MT plan review scheduled (appends a weekly section to the Conviction Plan doc and emails a summary).

- 2026-09-30 Codex W0 deployment verified: canonical snapshot 8e8c1055240b0367aa543bacff7f8d77258db079e663a700e50a11605adcc884 published with generation precondition; immutable cloud image sha256:903d9cfa305364eda873dd32d46ac615a85ccea9b8f923925a26430380931e1c deployed to dawn and strikes. Cloud smoke execution diablotrading-strikes-v4sqd succeeded: same snapshot, qualified=1, D6=2000, ledger mutation denied. Mac source hashes unchanged at activation; nine local services resumed, cloud schedules resumed after verification, auditor never paused. No real approvals, fills or ticket closes performed by Codex. Conflicting/cloud-only histories remain archived, not imported.

- 2026-09-30 Codex W4 extension: priority tiers now cover reports 1–10 days ahead (including T−1), reports in the last two NYSE sessions (including saved runner calendar/history when the snapshot rolls forward), open runner records, and operator-call CSV tickers; remaining coverage follows. The cap expands to the deduplicated union of tiers 1–4. Midday capture is installed at 13:00 ET / 11:00 Denver and immediately invokes both unchanged collectors so runner exits use that tape. Focused coverage/collector tests passed; future October collection targets remain unverified. W2 remains locally tested/integrated but main CI cannot be verified until GitHub write access is restored; W1 still needs the real five-session dawn target and nightly boundary audit.
- 2026-09-30 Claude (late): W0 landed (Codex). Fixed a regression from it: a failed dawn refresh now still sends the email but skips all paper steps (ee9f97c). Wrote docs/DESK_ROSTER_AND_RUNBOOK.md (roster, preregs, the operator's week, failure playbook). Next-session list added above.

- 2026-09-30 Codex W2 complete: restored Git SSH access using the existing Mac Keychain identity and a GitHub-specific persistent SSH configuration. Verified authentication without a loaded agent and a real branch push. Hosted Inferno CI passed on the integrated branch (run 36669527241), then on main at bf73e00 (run 36669637845: https://github.com/mikkaerror/diablotrading/actions/runs/36669637845). Main contains the tested W0/W2/W1/W4 implementation and integrated Claude work. W1 and W4 future evidence targets remain pending; no ticket decisions, risk settings or live/broker flags changed during this access repair.

- 2026-09-30 Codex W0 follow-up: reproduced the Cowork copied-receipt failure in the unconfigured-publisher test. Isolated all ownership fixtures with temporary root/receipt/ack paths and host environment, while adding explicit wrong-host publication refusal coverage. No production guard or authority setting changed.

- 2026-09-30 Codex W1 first-dawn inspection: observed zero gate-passing candidates; iron flies wait for regular-session quotes. Found ACN/VRT proposals mislabeled as straddles despite disjoint call/put strikes. Constructor now requires the nearest common buyable strike; no common strike means no straddle, rather than invalid break-even arithmetic. Added latest-slate blocker diagnostics by strategy, separate from frozen first-dawn observations and lineage credit. Existing gates/caps and preregs unchanged; five-session acceptance remains pending.

- 2026-09-30 Codex W0 first-morning repair: the 06:05 Desk Editor send receipt exists, but its pipeline notes report a canonical publication race (sources changed during upload); this is not a clean W5 morning. Local ledger successfully refreshed by 07:05. Publication now retries a source-change race once, persists queued/interrupted attempts with 5–60 minute backoff, and retries publication even when staging inputs are unchanged, without replaying staging/approvals. Doctor and command-center receipts expose publication status. Existing source-hash/generation checks and host authority guards remain intact.
- 2026-09-30 AM Claude: first post-cutover dawn ran clean (ledger written 07:05, Mac paper cycle ok, Desk Editor from the Mac at 06:05). Found: (1) two Desk Editor emails 13s apart + delegate ran twice — overlapping dawn invocations; fixed with a mailer file lock. (2) Pipeline note "canonical paper cycle: Canonical sources changed during publication; retry snapshot" — likely the same overlap (Codex W0 to confirm). (3) Leak: the delegate judges the approval-queue item (ACN straddle, $12,520 → reject) and never sees the cap-fit ledger variant (ACN call debit spread, $330) that is blocked only by "approval missing". Here the family rule would reject it anyway, but the delegate should evaluate approval-only-blocked ledger variants with the same rules (Claude, shared paper lane). (4) The funnel still proposes $12k–$23k long straddles (VRT, ACN): W1 not yet effective at dawn. (5) CRDO call: chain captured but leg spreads >25% at the pre-market tape; retries daily.

- 2026-09-30 Codex verification: read-only comparison at 07:21 found cloud current pointer and Mac snapshot both c5fcd59a0ff9f1d0ebb9263cf22f63a334c8701a34684d6059d56ed7f8337569, so a later scheduled publication recovered the earlier race. New durable retry receipts prevent that recovery from depending on another staging-input change. Integrated Claude mailer lock with these repairs; no extra email sent.
- 2026-09-30 Claude: deposit clerk built (inferno_deposit_card.py) — DEPOSIT DAY card from the day before to 3 days after each deposit (dollar-based fractional, per Schwab's fractional shares for most US stocks/ETFs), 1/3 tranche + cash earmark when the pick is extended, `done` logs it. Deposit date now rolls forward every 14 days.
- 2026-09-30 Claude: prereg integrity check built (inferno_prereg_integrity.py + research/prereg_registry.json): short-premium-v2 and earnings-runner-v1 pinned (doc sha256 + rule constants); drift alerts in the Desk Editor. Codex: register new versions with `python3 inferno_prereg_integrity.py register NAME` rather than editing pinned ones.
