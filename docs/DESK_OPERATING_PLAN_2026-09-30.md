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
| Second opinion (ChatGPT) | no API key | vacant (decision D2) |
| **Funnel fixer** (propose what can pass, sized to fit) | Codex | **open — W1** |
| **Controller** (one true count, clean ledgers, CI green) | Codex + Claude | **open — W2** |
| **Fill clerk** (60-second order card + fill capture) | Claude | **open — W3** |
| **Chain coverage** (earnings-window chains, midday tape) | Codex | **open — W4, due 10/12** |
| Live-book risk officer (report-only exit plans) | Claude | open — W6, blocked on D1 |

## 3. Workstreams

Each has an owner, a definition of done, and a date. Do them in this order.

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

### W4 — Chain coverage for short-premium v2 (Codex, due 2026-10-12)
Already filed as a mission. Earnings-window names (1–7 days out) first in
the capture list, limit raised so they fit, plus a second capture
12:30–14:00 ET. Read-only fetches. Don't touch v2 gates/structure/skips.
Done when: the week of 10/13 shows ≥ 10 v2 records captured.

### W5 — Email consolidation (Claude, after 3 good mornings, ~2026-10-03)
If the Mac Desk Editor lands 9/30, 10/1, 10/2: set `INFERNO_EMAIL_MODE=editor`
(routine morning/strike/pulse suppressed; failures still alert) and retire
the "paper candidate brief" Cowork task (the Desk Editor covers it).
Needs Mikka's OK in chat before flipping.

### W6 — Live-book risk officer (Claude, after D1)
Report-only weekly hold / trim / exit review of live holdings against
`docs/TRADE_MANAGEMENT_PLAYBOOK.md` and the Conviction Plan. Never sells,
never stages. Blocked until Mikka answers D1.

## 4. Calendar

| When | What |
|---|---|
| 09/30–10/03 | W2, W5 verification, Desk Editor lineage count |
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

- **D1** Conviction Plan sign-off (live-book rules for the −20% names).
- **D2** Second opinion: fund an OpenAI key (cents/day) or retire it.
- **D3** Commit to keying ~3 paper orders a week once W3 cards exist
  (≈ 5 minutes each). This is what actually moves 1/30.
- **D4** Merge `agent/storage-hygiene` → main and push once CI is green.

## 7. Log

- 2026-09-30 Claude: plan written from funnel/lineage audit.
