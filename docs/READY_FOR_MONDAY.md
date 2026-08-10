# Ready for Monday — the $1,000

_The honest version of "locked and loaded."_

## First, what the $1,000 actually is
It's your **base**, not next week's ammo. It grows NLV from ~$669 to ~$1,669 and
pulls your $10k date in by ~2 months — 100% certain, zero variance. That is its
real job. It does **not** go into live trades Monday, and here's why that's a
feature, not a limit:

- You're at **1 of 30** scored outcomes. Your edge is **unproven** (the buy-side
  is a documented KILL; short-premium is a promising but untested lead).
- Live trading is **hard-locked** (liveTradingAllowed / brokerSubmitAllowed =
  False) until 30 outcomes + your explicit ack.
- Deploying $1,000 into unproven live options next week is the exact ~150%-or-bust
  trap — it's how $1,000 becomes $400. Your own desk blocks it on purpose.

So "ready" ≠ ready to fire. "Ready" = **base deposited + evidence sprint started
+ operationally set**, so the $1,000 becomes deploy-*with-confidence* in ~12
weeks instead of gambled in one.

## Monday/Tuesday — do these three
**1. Land the deposit, confirm it.**
Deposit the $1,000 to the Schwab account (…8499). After it settles, verify it
shows up: `./inferno sync` then `./inferno growth-stack` — NLV should read ~$1,669
and the deposit ledger should reflect it. That's the win for the week.

**2. Start the evidence sprint (this is the real "loaded").**
Codex fixed candidate *generation*; the only bottleneck left is **you keying
paperMoney fills**. Each market session:
- `./inferno sync` → check the 8:24am candidate brief (or `./inferno today`)
- If a candidate clears the bar (reward/risk ≥ 0.50, liquid, edge, ≤ cap): approve it
- Key that exact order into thinkorswim **paperMoney**, record the fills
- Enter fills in `reports/paper_capture_template_latest.csv` → import → it scores
- **Target 2–3 clean scored outcomes / week → ~30 in ~10–12 weeks**

**3. Operational readiness checklist.**
- [ ] Schwab authorized (Sunday reauth reminder handles this; confirm `./inferno oauth`)
- [ ] `./inferno sync` clean, doctor healthy
- [ ] thinkorswim paperMoney open, using the existing window
- [ ] capture-template CSV known and ready
- [ ] clear the stale expired `MOD` ticket so the worksheet is clean

## The gate that unlocks the money
The $1,000 (and the deposits after it) sit as your growing base and fund realistic
paper sizing. It becomes **live-deployable only after 30 scored outcomes + your
ack** — and even then, sized to the *proven* edge, not $1,000 all at once. That's
not the slow path; it's the only path that doesn't hand the $1,000 back to the market.

_Illustrative mechanics, not advice. Edge unproven; real returns are volatile and
can be negative. No trade is placed for you — you approve and key every order._
