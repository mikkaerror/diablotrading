# Capital Flow Policy — Standard Bands

**Stage:** research-only, operator-binding once acked
**Updated:** 2026-06-17
**Status:** STANDARD bands selected by operator. This is the source of
truth that any future `inferno_capital_flow_advisor.py` should read.

The desk runs two engines:

- **Engine A — Options** (active trading): higher annualized return, higher
  variance, smaller capital base. Net new return per dollar deployed.
- **Engine B — Shares** (long-term accumulation): lower annualized return,
  lower variance, larger capital base. Compounding wealth base.

The policy below codifies how Engine A profits flow into Engine B over time,
and how the split between them shifts as the bankroll grows.

---

## 1. Sleeve drift table by NLV band (Standard)

As net liquidating value grows, the options sleeve shrinks as a percentage
while still growing in absolute dollars. The shares sleeve grows in both.

| NLV band         | Options | Long-term | Cash | Logic                                          |
|------------------|---------|-----------|------|------------------------------------------------|
| < $5,000         | 25%     | 50%       | 25%  | Small base; options earns its keep + reserve   |
| $5,000–$25,000   | 20%     | 60%       | 20%  | Beginning of compounding; shares takes lead    |
| $25,000–$100,000 | 15%     | 70%       | 15%  | Options dollar amount grows, % shrinks         |
| > $100,000       | 10%     | 80%       | 10%  | Shares is the engine; options is the gardener  |

**Worked example at NLV $50,000:**
- Options sleeve: $7,500 (was $0–$25k as cap budget; now serious)
- Long-term sleeve: $35,000 (compounding base)
- Cash reserve: $7,500 (drawdown buffer + opportunistic deploys)

Per-ticket cap at $7,500 options sleeve and the 1% rule (acked):
- single-ticket cap = $500 (formula floor stops below this until NLV ~$50k)
- daily new exposure cap = $1,500

At NLV $100,000:
- Options sleeve: $10,000
- Single-ticket cap: $1,000 (1% of NLV, within the formula band)
- Daily new exposure cap: $3,000

**Why the bands shrink options %:** mathematically, $500/week target at $1k
NLV requires 39%/week return (impossible). At $50k NLV requires 1%/week
return (aggressive but achievable). At $100k NLV requires 0.5%/week return
(realistic for a disciplined operator with proven edge). So the same dollar
target gets *easier* to hit as NLV grows — which means options doesn't need
to be as large a share of the book.

---

## 2. Harvest formula — options profit → share buys

**Trigger:** when **realized options PnL over the trailing 14 days ≥ $200**,
the desk surfaces a share-buy recommendation.

**Why $200:** the threshold is set to avoid churn-buying $5 worth of shares
every week. At $200+ we have enough to buy a meaningful share lot (e.g., one
share of an $80 ticker + change), and the realized profits are large enough
that ignoring them is the suboptimal choice.

**Harvest fraction: 80%.** When the trigger fires:
- 80% of realized options PnL sweeps to long-term sleeve as share buys
- 20% stays in the options sleeve as compounding capital

This preserves some of the options edge for re-investment while ensuring the
shares sleeve actually grows from successful options trading. At a 50% sweep
the options sleeve compounds slightly; at 100% sweep the options sleeve
never grows beyond the starting allocation; 80% is the band where shares
grows fast and options has room to scale up to its sleeve target.

**Distribution across conviction tickers:** equal-weight across the operator's
declared long-term-core names (§3 below), with one adjustment: if any ticker
is more than ±20% off its equal-weight target inside the shares sleeve, the
harvest buys preferentially close the gap before buying equal-weight.

**Worked example:**

Operator has realized $400 options PnL over the last 14 days. Conviction list
has 4 tickers (TE / IREN / HIVE / CLSK). The trigger fires.

- 80% of $400 = $320 swept to shares sleeve
- 20% of $400 = $80 stays in options sleeve (compounds future trades)
- $320 / 4 tickers = $80 each (equal weight default)
- If TE is already at 50% of the shares sleeve (overweight by 25%), all $320 goes to IREN/HIVE/CLSK ($107 each, rebalancing toward equal)

The recommender outputs:
```
This week: harvested $400 options PnL.
Sweep $320 to shares (80%), keep $80 in options sleeve.
Recommended buys:
    IREN  $107  (current 18%, target 25% of shares sleeve)
    HIVE  $107  (current 17%, target 25%)
    CLSK  $107  (current 15%, target 25%)
    (TE skipped this week — already overweight)
```

---

## 3. Operator conviction list

Tickers the operator has explicitly declared as long-term-core, in the
"these companies will exist for years" sense. The desk's algorithmic
long-term-shovel picks (CHKP, OTEX, DBX, etc.) are *additional* candidates,
not replacements.

| Ticker | Sector / Thesis                    | Operator-declared |
|--------|------------------------------------|--------------------|
| TE     | Energy / AI-power buildout         | Yes (long-term-core) |
| IREN   | Bitcoin mining + HPC               | Yes (long-term-core) |
| HIVE   | Bitcoin mining + AI infrastructure | Yes (long-term-core) |
| CLSK   | Bitcoin mining                     | Yes (long-term-core) |

**Operator decision points (override any time):**

- Add a ticker to the conviction list → it joins the harvest distribution
- Remove a ticker → it stops receiving harvest dollars but holdings stay
- Set a per-ticker target weight inside the shares sleeve → overrides equal-weight (e.g., "I want TE to be 40% of shares sleeve, not 25%")
- Disable harvest entirely → all options profits stay in options sleeve

These decisions live in (FUTURE) `data/operator_conviction.json`; until that
file exists, the four tickers above are the default and equal-weight is the
default distribution.

---

## 4. Circuit-breakers (binding on the advisor)

The harvest recommender must respect these no matter what the sleeve table
or harvest formula say:

1. **No harvest when in drawdown ≥ 20% from peak NLV.** The capital scaling
   drawdown stepper already limits new options exposure in this state; the
   harvest follows the same discipline — don't buy shares with options
   profits while the book is recovering. Profits stay in cash.

2. **No harvest when authority is halted.** The whole desk is paused; the
   harvest pauses too.

3. **No harvest when conviction list is empty.** If the operator has cleared
   all tickers, the desk has nothing to buy — surfaces a note, doesn't
   guess.

4. **Maximum single-cycle harvest: $5,000.** Even if realized PnL is much
   higher, a single harvest cycle caps at $5k of share buys. Above that the
   operator should manually decide rather than let one big options week
   reshape the portfolio in one cycle.

---

## 5. What this policy does NOT do

- It does not place share orders. The advisor outputs recommendations; the
  operator clicks the buys.
- It does not mutate authority, the capital-scaling ack file, or any risk
  policy constant.
- It does not override the existing `inferno_capital_allocator.py` sleeve
  weights at runtime. The allocator's regime/conviction logic still drives
  the per-cycle weights; this policy is the *long-run target* that the
  weights drift toward as NLV grows.
- It does not autonomously rebalance the legacy book. If the operator chose
  to hold TE/IREN/HIVE/CLSK regardless of fragility flags, the harvest
  *adds* to those positions — it does not trim them.

---

## 6. Integration points (for the future advisor module)

When `inferno_capital_flow_advisor.py` lands (BACKLOG item, not yet shipped):

- **Read:** `data/inferno_live_account_sync.json` (current NLV), this policy
  doc's tables (parsed or constant-encoded), `data/operator_conviction.json`
  (when it exists), `data/inferno_paper_execution_ledger.json` (closed paper
  outcomes for realized PnL), and the live position review (current per-ticker
  weights inside the shares sleeve).
- **Write:** `reports/capital_flow_recommendation_latest.txt` (one screen,
  phone-readable) and `data/inferno_capital_flow.json` (the structured
  recommendation for downstream consumption).
- **Surface:** new `Harvest:` block in `./inferno today` that appears only when
  the trigger fires.
- **Don't touch:** the live broker, the capital scaling ack file, authority,
  or any code that touches actual capital deployment.

---

## 7. Operator override checklist

These are the dials the operator can turn without changing this doc:

- [ ] Conviction list contents (which tickers count as long-term-core)
- [ ] Per-ticker target weights inside the shares sleeve (default: equal)
- [ ] Harvest threshold trigger dollar amount (default: $200)
- [ ] Harvest fraction (default: 80%)
- [ ] Trailing window for realized PnL (default: 14 days)
- [ ] Single-cycle maximum harvest (default: $5,000)
- [ ] Drawdown threshold to pause harvest (default: 20%)
- [ ] NLV band cutoffs and sleeve percentages (default: §1 table)

Until the future advisor module reads from a config file, these are encoded
in the constants of this doc. Operator changes them here; advisor reads from
here; advisor surfaces them on the daily report so they stay visible.

---

## Citations

- Earlier session position-sizing reasoning lives in
  [`POSITION_SIZING_RESEARCH.md`](POSITION_SIZING_RESEARCH.md) §1-3 (Kelly /
  Vince fixed-fractional / Tharp R-multiples).
- The two-engine framing comes from the operator conversation on 2026-06-17:
  "buy shares with my options profits when the money starts piling up and I
  have to take less risk to make money at a larger scale."
- Sleeve allocation existing implementation:
  [`inferno_capital_allocator.py`](../inferno_capital_allocator.py) §41-115
  (`normalize_sleeves`, `build_sleeves`).
