# Pre-Vegas Decisions

**Date:** 2026-05-26 (Tuesday evening)
**Vegas window:** you're leaving 2026-05-27 (Wednesday). Aging-out tickets expire **2026-05-29 (Friday)** which falls inside your trip.
**Authority state:** halted; broker submit OFF; liveTradingAllowed False. None of these decisions change that.
**NLV right now:** $1,081.60

You have three decisions worth resolving tonight so you leave with a clean book. Each one is a single CLI command. None of them place a live trade; they are research/discipline decisions about how the paper-evidence and capital-scaling machinery behaves while you're away.

---

## Decision 1 — Capital-scaling formula: ack or revoke?

**Current state:** the `inferno_capital_scaling.py` recommender is running and saying `ack-required`. The config cap is `$500`, the formula recommends `$25` (1% of NLV with floor binding), so they're 20× apart and the cap stays at `$500` until you opt in.

**What "ack" does:** writes `data/inferno_capital_scaling_ack.json` recording your acceptance of the formula (1% / $25 floor / $2000 ceiling / symmetric / ±20% tolerance / 25% drawdown pause). After ack, the cap auto-tracks NLV both up and down within ±20% drift. Fresh ack only required on big drift, drawdown, or formula-parameter changes.

**What "revoke" does:** removes the ack file (if one existed; there isn't one yet) and leaves `$500` as the enforced cap. The recommender keeps running advisory-only and the verdict stays `ack-required` each cycle.

**Recommendation: ack with the default 1% formula.** Reason: the $500 hand-tuned cap is structurally too large for $1,082 NLV (it's 46% of net liquidating value — a single full loss would be a ~46% drawdown). Acking the formula immediately tightens the operational cap to $25 at the floor, matching the position-sizing research note. The cap will grow back toward $500 organically as NLV crosses ~$50,000.

**Commands:**

```bash
# Recommended:
python3 inferno_capital_scaling.py accept

# To leave it advisory (no ack):
# (do nothing; current state)

# To change parameters at ack time, e.g. 2% rule:
python3 inferno_capital_scaling.py accept --pct 0.02

# To later remove the ack and revert to env-var default:
python3 inferno_capital_scaling.py revoke
```

---

## Decision 2 — The 4 aging-out DELL/MRVL straddles

**Current state:** four `paperOnly + approvalStatus=pending` LONG_STRADDLE tickets expire 2026-05-29 (Friday). They've been sitting since prior cycles. Tickets and IDs:

| Ticker | Strategy | Expiration | Days left | ticketId |
|---|---|---|---|---|
| DELL | LONG_STRADDLE | 2026-05-29 | 4 | `37318dfcd58781a8` |
| MRVL | LONG_STRADDLE | 2026-05-29 | 4 | `c1df034a5839a223` |
| MRVL | LONG_STRADDLE | 2026-05-29 | 4 | `29e262df81fea521` |
| DELL | LONG_STRADDLE | 2026-05-29 | 4 | `6855db9a00d4e84e` |

If untouched they become zombies #43-46 (current zombieCount: 42).

**Why they were never approveable:** these are `LONG_STRADDLE` constructions on $300+ tickers. From yesterday's worked math, the full-ATM straddle costs were $3-13k max loss, vastly over the $500 per-ticket cap, and beyond the structural reach of a $1,082 NLV account. The risk gate correctly refused them.

**Recommendation: reject all four.** Reason: they cannot be approved under the current risk policy regardless of what you do; the only difference between "reject now" and "leave them" is whether the zombie counter ticks up to 46 on Friday.

**Commands:**

```bash
# Recommended — reject each:
python3 inferno_approval_queue.py reject DELL
python3 inferno_approval_queue.py reject MRVL

# (The approval queue rejects by ticker, so both DELL tickets get cleared
#  by one DELL reject, and both MRVL tickets by one MRVL reject. If the
#  queue is per-ticketId instead, the commands surface the right IDs.)
```

If you want to preserve them as shadow-evidence-only (no approval needed, no zombie status): they'll auto-shadow-track via `inferno_shadow_evidence.json`. Either way, the live paper ledger entries should be resolved.

---

## Decision 3 — The PL Long Strangle (active auto-paper candidate)

**Current state:** PL ticker, LONG_STRANGLE (cap-aware variant of the rejected long-straddle), `estimatedMaxLoss=$500` exactly, paper-only, `riskVerdict.passed=True`, auto-paper-selected. Sitting at `approvalStatus=pending`.

**Why it matters:** this is the only live ticket the strategy generator has produced that fits every gate. Approving it is the cheapest way to get a single paper-staged trade into the system, get it to outcome-closed at some future point, and start moving the 30-outcome promotion gate from 0/30.

**The honest math caveat from yesterday's worksheet:** at current Schwab quotes the PL setup had a naïve negative single-shot EV of about −$48 (137% IV, low probability of finishing above breakeven). This isn't a "good trade" in isolation — it's *the only trade that fits the cap on today's slate*, and approving it generates evidence about whether your strategy generator's selection mechanism produces edge over the base-rate negative expectancy.

**Three reasonable answers, no clean winner:**

- **Approve** — get one paper trade running, accept the −$48 expected single-shot to learn whether the selection mechanism beats base rate.
- **Reject** — preserve the small bankroll for a setup that has positive prior EV; wait for the strategy generator to surface one.
- **Leave pending** — same as reject in practice, except the ticket continues to count against the auto-paper slate's "approval needed" status until the strike cycle ages it out.

**My read** (not a recommendation, just the framing): on a $1,082 bankroll, the cost of one paper-staged trade is zero capital and one slot of operator attention. The benefit is evidence. The cost of *not* approving anything is staying at 0/30 indefinitely and never knowing whether the desk's selection edge is real. I'd lean toward approve for the evidence value, but the math doesn't compel it.

**Commands:**

```bash
# Approve PL to paper-stage:
python3 inferno_approval_queue.py approve PL

# Reject PL:
python3 inferno_approval_queue.py reject PL

# Or, look at the full ticket first:
python3 inferno_paper_test_director.py status
```

---

## What's happening overnight while you sleep

Claude (this session) is building these, all research-only, all behind the same authority halt:

1. **`inferno_paper_mark_to_market.py`** — refreshes Schwab quotes on every open paper ticket each cycle, computes current spread mid, persists it to the ledger. Unblocks every price-triggered playbook rule.
2. **`inferno_trade_management.py`** — daily auditor that walks open positions and emits per-position recommended action (`hold`, `take-profit-1`, `stop-loss`, `time-stop`, `pre-event-exit`) based on the trade-management playbook. Outputs a phone-readable report card.
3. **Peak-NLV tracker** — small addition to the scaling module so the drawdown circuit-breaker has data.
4. **`reports/while_away_latest.txt`** — one artifact aggregating Schwab account truth, live-book blockers, formula/double-count cautions, shadow comparisons, and travel-mode action rules. Phone-readable. Build it with `./run_inferno_while_away_packet.sh`, glance at it once a day in Vegas, ignore the rest.

None of this touches authority. The desk does not place a single trade while you're away.

---

## What is NOT happening while you're away

For absolute clarity:

- **No live submission.** `liveTradingAllowed=False` is hard-coded.
- **No paper auto-approval.** The desk surfaces auto-paper *candidates* (like PL) but does not approve them on your behalf.
- **No cap auto-adjustment without ack.** If you don't ack the formula, the cap stays $500.
- **No closing of existing paper positions on your behalf.** The trade-management auditor recommends; you click.
- **No new module wired into the live broker.** The Schwab adapter is read-only quote pulls only.

If you come back from Vegas and the account moved, the only explanations are: a paper trade you approved before leaving naturally closed via reconciliation, OR none of the above happened and the desk is exactly where you left it.

---

## TL;DR — the three commands

```bash
# Decision 1 (recommended):
python3 inferno_capital_scaling.py accept

# Decision 2 (recommended):
python3 inferno_approval_queue.py reject DELL
python3 inferno_approval_queue.py reject MRVL

# Decision 3 (your call — leaning approve for evidence value):
python3 inferno_approval_queue.py approve PL
```

Run those three commands tonight, then refresh the away packet:

```bash
./run_inferno_while_away_packet.sh
```

Sleep, fly to Vegas. The system runs research-only behind you and surfaces decisions to `reports/while_away_latest.txt`. You read that one file, ignore the rest, enjoy the pool.
