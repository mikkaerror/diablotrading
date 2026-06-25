# Funnel Stagnation Diagnosis — 2026-06-25

**Stage:** research-only
**Promotable:** False
**Authority change:** none

## The honest read

Account is stagnant because **the funnel produced 0 candidates today**.
Director verdict: `no-viable-paper-tests`. Approval queue: empty.
Codex's `paper_blocker_swarm` reports `no-blocked-candidates` — because
nothing arrives to be blocked, much less to be diagnosed.

The funnel isn't blocked. It's **empty at the source.**

## What the diagnostic shows

Live `inferno_funnel_diagnostic.py` run on the current 146-row universe:

```
Strategy bias verdict: premium-buy-monoculture
  premium-buy:  107 / 146 (73%)
  premium-sell:   0 / 146  (0%)
  avoid:         39 / 146 (27%)

Top setupRec values:
  Straddle:       70  (long vol)
  Vertical Call:  37  (debit, long vol)
  Avoid:          39

  Iron Condor / Credit Spread / Wheel:  ZERO
```

**The strategy lab is structurally producing only premium-buying
setups.** Carr & Wu (2009) document a *negative* variance risk premium
on equity indices — meaning premium-selling has compensated structural
edge, and premium-buying has structural disadvantage. The desk's own
net-R ledger (codex's expectancy module) confirms it:

- Shadow Long Straddle: n=96, win rate 35%, sum -R despite mean appearing positive (DELL/HPE concentration per deep-dive)
- Shadow Vertical Debit: n=49, win rate 39%, **netR -0.38**, 95% CI [-0.56, -0.20] (statistically significant loser)
- Shadow Long Straddle 7-14 DTE entry: n=36, win 56%, netR +0.86 (the only positive cohort)

The desk is generating candidates ONLY from the family the literature
and its own data say loses money on average — and even within that
family, only one narrow cohort (7-14 DTE earnings entry) shows positive
expectancy.

## What's being missed in the current universe

The diagnostic surfaces concrete candidates the strategy lab is NOT
proposing:

**Credit-spread / iron-condor candidates (IVR > 50, no nearby earnings, price < $100):** 2
- `IREN`  $55.30, IVR 50.2, dte_earn=63 — currently labeled Straddle (wrong)
- `LUNR`  $35.74, IVR 54.0, dte_earn=42 — currently labeled Straddle (wrong)

**Wheel / cash-secured-put candidates (cheap stock, IVR > 30, signal-triggered):** 7
- `CIFR`, `FLNC`, `VNET`, `MEI`, `CCOI`, `DXC`, `UUUU`

**Sweet-spot 7-14 DTE earnings entries (the one positive-EV cohort):** 1
- `AZZ` $145.87, IVR 12.9, dte_earn=13, ATR% 3.88

That's ~10 missed candidates daily — not a flood, but enough that the
desk should be producing at least 2-3 paper tests every cycle instead of zero.

## Why this is happening (best hypothesis)

The tracker's `setupRec` field is the primary decision input. Looking at
the 146 universe rows:

1. Tickers with earnings 7-30 days out → `Straddle` or `Vertical Call`
   (which the cap-fit audit shows fit only 18% and 30% of cases
   respectively, so most hard-block on cap)
2. Tickers with no nearby earnings → no setup recommendation at all,
   even when IV rank > 50 would make them obvious credit-spread
   candidates
3. There is no scanner for "high IV rank, no event" → credit-spread / iron condor
4. There is no scanner for "cheap conviction-tier, decent IV" → wheel
5. The cap-aware fallback (straddle → strangle → long single → vertical → iron condor) is missing

The cap-fit audit (BACKLOG #2) showed 100% of universe fits at least
one structure within the $500 cap. But the lab never tries the alternative
structures, so all 100% get hard-blocked or dropped silently.

## Three actions to unblock

### 1. Operator decision: scope expansion

The discipline doc (§1, premium-selling conclusion) is explicit that
credit-spread family requires defined max-loss + spread liquidity +
explicit gap-event scenario + comparison vs shares. None of that is
present today because the family doesn't get generated.

**The operator decision is:** does the desk's evidence-collection scope
include credit-spread family? If yes, codex's strategy lab should add a
credit-spread scanner. If no, the universe should be filtered to
earnings-window-only tickers and the lab's behavior remains correct.

The deep-dive doc and the discipline doc both lean toward "yes, scope
includes premium-sell" — Carr-Wu VRP is the cleanest structural edge
in retail options literature. But this is your call.

### 2. Codex lane: cap-aware structure fallback

The cap-fit audit's headline finding still applies: the strategy lab
proposes Straddle for 70 tickers but only 26 fit cap. The fallback
chain — when the preferred structure exceeds cap, try the cheaper same-
direction alternative — isn't wired. This is in scope for codex's
`paper_blocker_swarm`, but the swarm currently shows
`no-blocked-candidates` because nothing reaches it as "blocked" — it
gets dropped earlier.

The fix is in the strike selector / strategy lab itself, before the
director-level filtering. Codex coord note flag.

### 3. Wire the diagnostic into nightly_optimize

The `inferno_funnel_diagnostic.py` shipped today runs in <100ms. Adding
one line to `nightly_optimize.sh` keeps the funnel-bias check fresh
every cycle. The doctor would surface "premium-buy-monoculture" as a
WARN until the lab's generator distribution diversifies.

## What this diagnostic does NOT do

- It does NOT propose adding the 10 missed candidates to the approval
  queue. They're pattern matches, not edge proofs. The strategy lab
  needs to evaluate them properly.
- It does NOT change any gate or filter. The 146 universe rows are
  read-only inputs.
- It does NOT touch authority, broker submit, or the live book.
- It does NOT relax sizing — the cap stays at $500 (or $25 if you ack
  the formula).

## Reminders for the operator

- "More paper chances" requires either (a) expanding the family scope
  to include premium-sell setups (operator decision) or (b) wiring the
  cap-aware fallback chain so existing premium-buy candidates don't
  silently drop (codex fix).
- Lowering quality gates to push more through is the wrong move — the
  desk's own ledger shows the existing premium-buy candidates already
  have negative expected value.
- The 30-outcome promotion gate remains 1/30. Until paper outcomes
  accrue, every sizing or family decision is provisional.

## Sources

- BACKLOG #2 universe cap-fit audit (commit bd5ba6f) — 100% fit rate,
  18% straddle fit
- Codex net-R expectancy ledger — Shadow Vertical Debit n=49, netR -0.38, 95% CI [-0.56, -0.20]
- Codex DTE policy analysis — Long Straddle 7-14 DTE cohort: n=36, win 56%, netR +0.86
- [Carr & Wu (2009): Variance Risk Premiums](https://www.researchgate.net/publication/24045465_Variance_Risk_Premiums)
- [de Silva, Smith & So (2024): Losing is Optional](https://www.timdesilva.me/files/papers/losing_optional.pdf)
