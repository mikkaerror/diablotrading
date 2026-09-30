# Inferno Desk — Roster & Runbook

One page: who does what, when, and what to do when something breaks.
Times are Mountain. Working plan and open work: `docs/DESK_OPERATING_PLAN_2026-09-30.md`.
Rules: `docs/TRADE_MANAGEMENT_PLAYBOOK.md`, the signed Conviction Plan
(Claude Doc, ack `data/inferno_conviction_plan_ack.json`), and the preregs below.
Safety perimeter (CLAUDE.md §8): research-only, live flags off, the operator keys every order.

## 1. The roster

| Role | Who / what | When | Output |
|---|---|---|---|
| **Desk Chief** | Codex, operational authority only | 08:10 / 12:10 / 16:10 weekdays; cheap hourly observation | owned priorities, acceptance receipts, usage/cost visibility; `./inferno chief status` |
| Data engine | Mac launchd `inferno_dawn_pipeline.py` | weekdays 06:00 (+10-min safety ticks) | fresh tracker, Schwab chains, snapshot |
| Paper stager (canonical ledger owner) | `inferno_mac_paper_cycle.py` (Codex, W0) | after the dawn refresh | staged paper tickets, Mac ledger |
| Paper approver | `inferno_paper_delegate.py` (rule-based, ack-gated) | inside the mailer | approvals/rejections, logged |
| Fill clerk | `inferno_paper_order_card.py` | inside the mailer | order cards at the top of the email |
| Research views | TWR, vol edge, Capex Flow + sizing, pick scorecard | inside the mailer | reports/*_latest.txt |
| Short-premium collector | `inferno_short_premium_shadow.py` (prereg v2) | inside the mailer | iron-fly shadow records |
| Earnings Runner Campaign | `inferno_earnings_runner.py` (arms A/B/C) | inside the mailer | shadow records + scoreboard |
| Live-book risk officer | `inferno_live_book_officer.py` (signed plan rules) | inside the mailer | LIVE BOOK block |
| Deposit clerk | `inferno_deposit_card.py` | inside the mailer; shows the day before → 3 days after each deposit | "DEPOSIT DAY" card (dollar-based fractional buys you key) |
| Desk Editor | `inferno_desk_editor_mailer.py` | ~06:10 weekdays | the one morning email |
| Email watchdog | cloud task (Gmail only) | 07:20 weekdays | email only if the Desk Editor didn't arrive |
| Action pulse (legacy) | Mac launchd | ~07:05 and 13:30 | to be folded into the Desk Editor (W5) |
| Midday chain capture | Mac launchd (W4) | 11:00 (13:00 ET) weekdays | tighter-spread chain tape |
| Candidate brief (legacy) | Cowork task | 08:15 weekdays | overlaps the Desk Editor; retire at W5 |
| Verdict monitor | Cowork task | 18:00 daily | buy/sell campaign verdict log |
| Hygiene + boundary audit | Cowork task | 21:30 daily | commits stayed in bounds, stale data |
| Earnings-date checker | cloud task | Sun 16:47 | confirmed / moved dates, next 3 weeks |
| Schwab re-auth reminder | Cowork task | Sun 18:00 | the 30-second login nudge |
| Evidence scorecard | Cowork task | Sun 19:00 | x/30 pace |
| Plan reviewer | cloud task | Sun 19:38 | "Weekly review" section in the Conviction Plan doc + email |
| AI basket review | Cowork task | Mon 08:00 | basket regime/trend digest |
| Earnings analyst | cloud one-shots | 10/29 GNRC+TEL, 10/30 MPWR, 11/06 IREN, 11/13 HIVE+TE, 11/25 CLSK+CLFD, 12/01 CRDO | thesis-card verdict emails |
| Capex tape analyst | cloud one-shot | 11/02 | hyperscaler capex tape refresh |
| Engineering / risk gates | Codex | continuous, own lane | commits + model notes |
| **Operator (Mikka)** | you | see §3 | keys orders, signs decisions |

## 2. Pre-registered experiments (rules frozen before data)

| Prereg | Collector | Read-out |
|---|---|---|
| `docs/SHORT_PREMIUM_PREREG_2026-07-07.md` (v1) | none ever ran | time-box 10/05 → record "expired unrun" |
| `docs/SHORT_PREMIUM_PREREG_V2_2026-09-29.md` | `inferno_short_premium_shadow.py` | 60 events / 40 names or 2027-02-28 |
| `docs/EARNINGS_RUNNER_PREREG_2026-09-30.md` | `inferno_earnings_runner.py` | mid-Nov, then after Q4 |
| Capex Flow lane (`docs/CAPEX_FLOW_STRATEGY_2026-09-28.md`) | pick scorecard cohorts | 30/91/182-day horizons (first: 10/08) |

Changing a rule after data exists needs a new version registered before its own data.
`inferno_prereg_integrity.py` pins each prereg doc's hash and the collector's rule constants
(`research/prereg_registry.json`); any drift shows up as a HEADS UP line in the morning email.

## 3. The operator's week (about 30 minutes)

- **Weekdays, ~2 min:** read the morning email. If it shows "KEY THESE IN PAPERMONEY", key the card (limit, don't chase), then run the record command it prints.
- **Paper target:** ~3 keyed paper orders a week, which clears 30 qualified outcomes by about mid-December.
- **Earnings calls:** `cd ~/Documents/"New project" && python3 inferno_earnings_runner.py call TICKER up|down "why"`
- **Deposit days (every 14 days; next 10/09):** the email leads with a DEPOSIT DAY card: dollar amounts for SMH and the named Capex Flow pick (a 1/3 tranche if extended, the rest earmarked in cash). Place the dollar-based fractional orders after the first 30 minutes of trading, then run `python3 inferno_deposit_card.py done "what you bought"`. You buy; the desk never does.
- **Sunday, ~10 min:** re-sign into Schwab (`python3 inferno_schwab_oauth.py restart`), read the Sunday review, and answer any open decision.

## 4. When something breaks

| Symptom | What it means | Do this |
|---|---|---|
| No Desk Editor email; the 07:20 watchdog emails | Mac asleep or the dawn service is unloaded | `python3 inferno_desk_editor_mailer.py run --force`; if it repeats, `python3 install_inferno_dawn_service.py` |
| Email leads with "dawn refresh failed (exit N)" | data refresh failed; paper staging was skipped | nothing to key today; tell Claude/Codex if it happens twice |
| "Schwab login runs out in N days" / "Schwab login expired" | the 7-day refresh window | `python3 inferno_schwab_oauth.py restart` |
| "paper ledger (staging): stale" | the Mac paper cycle isn't writing | Codex (W0 owner) |
| "PIPELINE NOTES: <step> failed" | one research view didn't refresh | none; it's shown as a day old |
| Nightly audit says "POSSIBLE BOUNDARY DRIFT" | a commit loosened a safety setting | read the named commit before anything else |

## 5. Still open

Roles to fill (see the plan's "Next session" section):
1. **Monthly close:** first-Sunday-of-month returns vs SPY and SMH, per sleeve and per campaign arm.
2. **Second opinion (D2):** fund an OpenAI key or retire it.

Processes to add:
- **Year-end tax review (December):** realized and unrealized losses, e.g. TE. Take it to a tax professional; the desk won't advise.
- **Email consolidation (W5):** after 3 good mornings.
