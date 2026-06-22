# Trading Discipline Research — 2026-06-22

**Stage:** research-only
**Promotable:** False
**Authority change:** None
**Source:** ~8 web searches across academic finance, tastytrade backtests,
behavioral economics, and practitioner playbooks. Citations at the bottom.

This is a one-night deep dive on six topics the operator named: strategy,
sizing, positioning, taking profits, moving on quickly, and trading without
emotion. The goal is not to recommend tactics — it's to surface what the
evidence says, then translate it into shippable to-dos for the desk.

The big honest finding up front: the Inferno desk's existing Lane A (long-vol
debit trades around earnings) has historically negative expectancy at retail.
That's not opinion. That's the data. We need to either retire that lane or
restrict it to a much narrower setup. The MOD ticket closing at -$350 was the
expected outcome, not a fluke.

---

## 1. Strategy: where edge actually lives

### What the evidence says

**Long-vol around earnings is historically a losing strategy.** A 2024 SSRN
study of S&P 500 earnings straddles 2011-2021 found average return of +1.17%
gross of costs and **-9.07% after transaction costs**. Individual-name
backtests are worse: Apple straddles for earnings win 41% of the time with
-1.3% average annual return; Facebook 27%, Chipotle 35%. The popular
"buy-1-day-before, sell-1-day-after" variant *does* show high CAGR in
backtests but with single-week drawdowns up to 83.8% and unaccounted
slippage/commissions — i.e. not retail-friendly.

**Iron condors around earnings work only with discipline.** Tastytrade
research across 200,000+ credit spread trades: 25-30 delta short strikes
at 45 DTE, exit at 21 DTE or 50% profit, produces 70-75% win rate
unmanaged, 78-82% managed. But — and this is the catch — iron condors
*sold immediately into earnings* get blown through when the stock moves
10-20% overnight, which happens roughly 1 in 5 earnings prints. The
strategy survives because the 4 out of 5 winners are bigger than the 1
loser, but only if you manage exits.

**The 45 DTE sweet spot is real.** Tastytrade's 200k-trade dataset shows
45 DTE entry + 21 DTE exit produces the best risk-adjusted return vs 30 or
60 DTE alternatives. The mechanism is simple: 45-21 DTE is the window
where theta is high and gamma is still manageable. After 21 DTE gamma
spikes and theta decay accelerates but so does pin risk. Tastytrade calls
this the "sell theta, buy gamma" balance.

**Wheel strategy on conviction stocks is the unsexy winner for small
accounts.** Selling cash-secured puts on stocks you actually want to own
at the strike, then selling covered calls if assigned. Realistic
expectations: 1-3%/month on deployed capital (12-36% annualized), which
becomes ~1.2% on the full account at 50% cash reserve. Compounds. Doesn't
blow up. The mechanism is "get paid to be patient on names you already
like" — which is exactly what we're already doing manually on
TE/IREN/HIVE/CLSK without the premium-collection layer.

### What this means for the Inferno desk

We are running Lane A (long-vol around earnings) as one of two primary
playbooks. The data suggests Lane A is structurally negative-expectancy
unless we add specific filters (e.g., post-earnings only, when realized
vol exceeds implied; or only when IV rank is below 30 at entry).

We are *not* running a wheel lane on the conviction holds, which is the
strategy with the cleanest historical edge for a small account with
conviction names.

This is a strategy-allocation problem, not a tooling problem.

---

## 2. Sizing: how much to risk per ticket

### What the evidence says

**The 1% rule is the consensus floor.** Professional risk-per-trade is
0.5-2% of account, never more than 2%. The math: at 1% risk, you can
absorb 23 consecutive losses before a 25% drawdown (which itself requires
a 33% gain to recover). At 2% risk, 13 consecutive losses gets you to a
25% drawdown.

**De-risking after drawdown is mechanical, not discretionary.** Standard
protocol: after 2 consecutive losses *or* 2% account drawdown, cut risk to
0.5% per trade. Resume normal risk only when balance returns to prior
peak. The Inferno desk already has a 10/20/30% tiered drawdown stepper
(1.0x → 0.5x → 0.25x → 0.0x cap multipliers); the research suggests we
should add a tighter early-warning at the 2% / 2-loss boundary too. Two
losses on a $1,600 account is roughly -$300 — currently invisible to the
stepper because peak-NLV is fine.

**Fixed-percentage beats fixed-dollar at small accounts.** Fixed-dollar is
simpler to think about but doesn't scale: $100 risk on a $10k account is
1%, on a $100k account is 0.1%. Fixed-percentage automatically compounds
your size up with the account. Our `inferno_capital_scaling.py` already
does this — but the formula is unacknowledged. Until you ack the formula
(or override it explicitly), you're operating on the static $500 config
cap, which at NLV=$1,599 is **31% of the account**. That's roughly 15x
the recommended max.

**Expectancy is the only number that matters across time.**
E = (Win% × AvgWin) - (Loss% × AvgLoss). Needs 30+ trades to mean
anything, 100+ to be reliable. We have 1 closed promotable outcome.
We are statistically in the noise. Any sizing decision we make in the
next 29 trades is provisional, period.

### What this means for the Inferno desk

Two concrete sizing actions:

1. **Pick the cap.** Either ack the $25 formula or explicitly choose a
   bigger cap with rationale. Don't drift at $500 by inertia.

2. **Add a 2% / 2-loss early de-risker** on top of the existing tiered
   stepper. This is the only sizing change that actually matters before
   we have a meaningful sample size.

---

## 3. Positioning: IV rank as the regime gate

### What the evidence says

**IV Rank > 50 favors selling premium; IV Rank < 30 favors buying.** Schwab,
tastytrade, and every options education channel converge here. The
mechanism is mean-reversion of implied vol — when current IV is high
relative to its 52-week range, it tends to compress; when low, it tends
to expand. Selling expensive premium (iron condors, credit spreads,
strangles) makes money when IV compresses. Buying cheap premium (long
calls/puts, debit spreads, calendars) makes money when IV expands.

**The 30-70 zone is decision-ambiguous.** Other signals (term structure,
event proximity, directional thesis) need to weigh in.

**Term-structure backwardation is event pricing.** When front-month IV
exceeds back-month IV, the market is pricing a near-term event (earnings,
FOMC, macro print). That's *not* a high-IV-rank tradable opportunity —
it's a binary risk window. The post-event IV crush is reliable but you
have to be the right side of the underlying move.

### What this means for the Inferno desk

Our auto-paper director currently scores tickets on "readiness" and
signal triggers. **IV rank does not appear to be a gate.** That's a
potential blind spot. AZZ and SNX are both Vertical Calls (debit
structures, long-vol exposure). If their IV rank is >50, we're paying up
for long vol when we should be selling it. We don't know without
checking.

This is a small, shippable addition: surface IV rank on every approval-
queue candidate alongside readiness, so the operator sees the
positioning context at decision time.

---

## 4. Taking profits: the 50% rule and the 80% ladder

### What the evidence says

**Credit structures: close at 50% of max profit.** Tastytrade's 4,000+
SPY put-credit-spread study is the most-cited result. Holding to
expiration looks better on paper (more theoretical profit) but
underperforms 50%-closes on annualized return because: (a) the last 50%
of profit takes the longest to capture, (b) gamma risk spikes in the
final week, (c) the capital is freed up to roll into a new position.

**Debit structures: 75-100% gain target, 50% loss stop.** The asymmetry
is wider here because debit trades are typically directional bets with
defined cost. Most practitioners ladder out: trim 50% at +50% of debit,
trim 25% more at +100%, leave a 25% runner for the asymmetric tail.

**Force-close at 21 DTE.** Tastytrade research again: holding past 21 DTE
introduces accelerating gamma and dropping theta, which is the worst
trade-off in the option lifecycle. Close at 21 DTE regardless of P/L
unless you're at the extremes of the ladder.

### What this means for the Inferno desk

We already have a trade-management auditor (`inferno_trade_management.py`)
with a Lane A debit ladder (50%/100%/200%) and a Lane B credit close-at-
50% rule. The math is right. The gap is the **21 DTE force-close**:
existing code only fires "time-stop" at DTE ≤ 2 (hard) or DTE ≤ 3 (when
flat). The research suggests a 21 DTE trim regardless of P/L for Lane B,
and a 21 DTE warning for Lane A. Small addition, big difference.

---

## 5. Moving on quickly: the sunk-cost trap

### What the evidence says

**40% of retail forex traders fall into the sunk-cost trap and lose 23%
more than those who don't.** That's a study of 5,000 traders, so the
sample is real. The mechanism is loss aversion (Kahneman/Tversky):
the pain of a -$100 loss is psychologically equivalent to the pleasure of
a +$200 gain. So we hold losers hoping they come back, and we close
winners early before they "give back" the gain. Both behaviors are
expectancy-negative.

**Averaging down on losers is empirically a disaster.** 68% of retail
traders who added to losing positions saw losses 2.8x greater than their
initial risk. The "lower your cost basis" intuition feels mathematical
but in practice you're tripling down on a thesis the market is rejecting.

**The cure is mechanical, not motivational.** Set stops when calm.
Honor them when not. The same study showed that traders using *hard*
stops (broker-level) cut sunk-cost losses by 60% vs traders using
*mental* stops (intend-to-exit-but-watch). Mental stops get re-negotiated
in real time. Hard stops don't.

### What this means for the Inferno desk

Two things:

1. **An explicit "no averaging down" rule in the playbook.** We don't have
   one. Add it as a binding line in `TRADE_MANAGEMENT_PLAYBOOK.md`. If
   the position is a loser, the response options are *close* or *roll*,
   never *add*.

2. **A "first loss is the best loss" reminder surface in `today.sh`.**
   When MTM shows a Lane A debit at -50% or a Lane B credit at -100% of
   credit, the system should not just say "verdict: stop-loss" — it
   should say "the right action is to close. The wrong action is to
   wait. The very wrong action is to add."

---

## 6. Trading without emotion: build the system, not the willpower

### What the evidence says

**Process goals beat outcome goals.** Research from sports psychology and
finance both: traders who track "did I follow my checklist?" outperform
traders who track "did I make money this week?" The reason is feedback
quality. You can follow a perfect process and still lose a week to
variance. You can break every rule and still get lucky. Process is the
only signal you can correct on.

**Pre-trade checklist trades outperform by 15-30% profit factor.** That's
the ROI of 15 seconds of preparation. The checklist itself doesn't have
to be sophisticated — entry trigger met (y/n), max-loss within sizing cap
(y/n), exit plan written down (y/n), thesis paragraph in 2 sentences,
emotional state 1-10. The act of pausing to fill it in is the value, not
the form.

**FOMO and revenge trading are universal, not personal failings.** Every
trader experiences them. The professional difference is having
pre-committed rules that don't require willpower to honor at the moment
of temptation. "Set your rules when you're calm, execute them when
you're not" — the most-cited line in the literature. The 12 of 14 Market
Wizards (Schwager 1989) who named "cut losses early" as their #1 rule
didn't have superhuman discipline; they had pre-committed rules that did
the discipline for them.

**The hot-hand fallacy is real and bidirectional.** Studies of retail
traders show belief in streaks after short runs of wins or losses, which
drives over-sizing after wins and under-sizing after losses — both
expectancy-negative. The cure is fixed-percentage sizing that ignores
the streak.

### What this means for the Inferno desk

This is where Inferno is actually *ahead* of most retail desks. The whole
architecture — research-only stage, 30-outcome promotion gate,
authority hard-coded False, today.sh as the operator surface — is a
system designed to remove emotion from the trading loop. That's the
right architecture.

The gap is the **decision journal**. We have approval/rejection logging
in `data/operator_decisions.csv` but it doesn't capture *why*. Adding
a 2-field prompt at approval time (one-sentence thesis, emotional state
1-10) would create a feedback dataset we can review monthly and learn
from. That's the missing piece.

---

## Synthesis: the actionable tips, ranked by leverage

If we shipped these in order, each one would compound the previous.

**Highest leverage (do these first):**

1. **Add IV Rank to the approval-queue surface.** One number per candidate.
   At decision time, the operator sees IVR=25 (favor debit) or IVR=65
   (favor credit) and can sanity-check the strategy choice. Lane A and
   Lane B are currently chosen by the strategy lab without an explicit
   IVR gate.

2. **Add 21 DTE force-close to trade-management auditor.** Existing time-
   stop fires at DTE ≤ 2 (hard) or ≤ 3 (when flat). Research-backed
   addition: a "trim at 21 DTE regardless of P/L" verdict for Lane B
   credit, and a "review at 21 DTE" verdict for Lane A. Small code
   change, big expectancy improvement.

3. **Ban averaging down explicitly in `TRADE_MANAGEMENT_PLAYBOOK.md`.**
   One paragraph. Make it a binding rule. The desk has never proposed
   adding to a loser, but the rule needs to exist before the temptation
   arrives.

4. **Add a tighter de-risker:** after 2 consecutive losses *or* -2% drawdown
   from peak NLV, halve the per-ticket cap for the next 5 tickets.
   Currently the stepper only fires at -10% / -20% / -30%, which is too
   wide for a $1,600 account where two $250 losses puts us at -30%.

**Medium leverage:**

5. **Two-field decision journal:** add a `--rationale` and `--confidence`
   prompt to `today.sh` at approve time, writing into
   `data/operator_decisions.csv`. Reviewing the journal monthly creates a
   feedback dataset.

6. **Pre-trade checklist for paper candidates:** before a ticket goes from
   "auto-paper-selected" to "approval-queue", confirm 5 boxes: entry
   trigger, sizing within cap, exit plan, IV rank context, primary
   thesis. Currently the strategy lab does this implicitly; making it
   explicit creates a learnable artifact.

7. **Lane A retirement debate:** research says long-vol-into-earnings is
   negative expectancy on average for retail. We should either retire
   Lane A or restrict it to specific narrow setups (e.g., IVR < 25 at
   entry, only on the day-before-day-of-earnings micro-window). Until
   we have evidence Lane A is profitable on *our* desk, we shouldn't
   assume it will be.

**Low leverage but worth knowing:**

8. **Wheel lane on conviction names:** sell out-of-the-money CSPs on
   TE/IREN/HIVE/CLSK to collect premium on stocks you want anyway. This
   is the operationalized version of the harvest mechanism in
   `CAPITAL_FLOW_POLICY.md`. The earliest you can spin this up is when
   the conviction sleeve is at target weights (currently 62% vs 50%
   target, so this is on hold).

9. **Expectancy ledger:** a simple running tally per strategy family of
   win%, avg win, avg loss, expectancy. We need 30+ outcomes per family
   for it to mean anything, but starting the ledger now means we have
   real data when we hit the gate instead of summarizing from memory.

10. **45 DTE entry as default**: shift auto-paper preferred expirations
    to 35-50 DTE. Currently the strategy lab picks shorter — the
    research is unanimous that 45 DTE is the theta/gamma sweet spot for
    spreads.

---

## What this research does *not* claim

- It does not claim 10%/month is achievable. The evidence says
  1-3%/month is "very good" and 5-10%/month is top-1%-of-retail
  territory. The math is in `docs/POSITION_SIZING_RESEARCH.md`.

- It does not claim any of these rules will work on our specific desk
  until we have 30+ closed outcomes to test against.

- It does not propose changing authority, broker submit, or live trading
  flags. All of these stay False.

- It does not recommend over-riding the operator's discretion. The
  operator clicks the buttons. These are guardrails, not autopilot.

The discipline is what compounds. The tools just remove the friction.

---

## Sources

**Profit targets / 50% rule:**
- [tastytrade: Close at Profit Percent Order](https://support.tastytrade.com/support/s/solutions/articles/43000435423)
- [SJ Options: Tastytrade Credit Spreads 11-Year Backtest](https://www.sjoptions.com/tastytrade-credit-spreads-do-they-work/)
- [JournalPlus: Put Credit Spread Strategy Guide](https://journalplus.co/strategies/put-credit-spread/)
- [Option Alpha: Exiting Trades](https://optionalpha.com/members/answer-vault/exiting-trades)

**Stop losses / cutting losers:**
- [Elm Wealth: Cut Losses Early, Let Profits Run](https://elmwealth.com/cut-losses-early-let-profits-run/)
- [Theta Profits: Stop-Loss on Credit Spreads](https://www.thetaprofits.com/stop-loss-on-credit-spreads-in-0dte-options-trading/)
- [Option Alpha: 10 Backtested Option Stop-Loss Strategies](https://optionalpha.com/podcast/stop-loss-strategies-for-options)
- [Lux Algo: Sunk Cost Fallacy in Trading](https://www.luxalgo.com/blog/sunk-cost-fallacy-in-trading-explained/)
- [Quantified Strategies: Sunk Cost Fallacy](https://www.quantifiedstrategies.com/sunk-cost-fallacy-in-trading/)

**IV rank / regime:**
- [Schwab: Using Implied Volatility Percentiles](https://www.schwab.com/learn/story/using-implied-volatility-percentiles)
- [TradingBlock: IV Rank vs IV Percentile](https://www.tradingblock.com/blog/iv-rank-vs-iv-percentile)
- [The Option Premium: High IV vs Low IV for the Wheel](https://www.theoptionpremium.com/p/high-iv-vs-low-iv-wheel-strategy)
- [FlashAlpha: Volatility Term Structure, Contango, Backwardation](https://flashalpha.com/articles/volatility-term-structure-contango-backwardation-events)

**Earnings strategies:**
- [SSRN: 17-Year Backtest of Straddles around S&P 500 Earnings](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4832160)
- [Option Alpha: Long Straddle Earnings Backtest](https://optionalpha.com/podcast/long-straddle-earnings-option-strategy)
- [BSIC: Straddling into Earnings Part II](https://bsic.it/straddling-outside-and-into-earnings-part-ii-2/)
- [ApexVol: Iron Condor Win Rate Stats](https://apexvol.com/strategies/iron-condor)
- [TradeStation: Iron Condor Earnings Volatility Strategy](https://www.tradestation.com/insights/2026/02/13/iron-condor-earnings-volatility-strategy/)

**Psychology and discipline:**
- [WealthBee: Emotional Discipline Checklist](https://wealthbee.io/learn/trading-journal-emotional-discipline-checklist/)
- [PrimeXCapital: FOMO and Disciplined Plans](https://primexcapital.com/en/blogs/trading-psychology-conquering-fomo-emotional-bias-disciplined-plan)
- [BingX: Trading Psychology and Rational Decisions](https://bingx.com/en/learn/article/what-is-trading-psychology-how-to-control-emotional-trading)
- [Skeptical Inquirer: Gambler's Fallacy and the Hot Hand](https://skepticalinquirer.org/exclusive/a-closer-look-at-the-gamblers-fallacy-and-the-hot-hand/)

**Sizing / expectancy:**
- [Traders Second Brain: Risk Per Trade 1% vs 2%](https://traderssecondbrain.com/guides/risk-per-trade-guide)
- [EdgeFlo: De-Risk After Drawdown](https://www.edgeflo.com/blog/de-risk-after-drawdown)
- [CME Group: The 2% Rule](https://www.cmegroup.com/education/courses/trade-and-risk-management/the-2-percent-rule)
- [HeyGotTrade: Expectancy Math](https://www.heygotrade.com/en/blog/what-is-expectancy-in-trading/)

**Wheel strategy / sweet spot:**
- [Schwab: Three Things About the Wheel Strategy](https://www.schwab.com/learn/story/three-things-to-know-about-wheel-strategy)
- [Options Cafe: Wheel Strategy with $5,000](https://options.cafe/blog/wheel-strategy-small-account/)
- [Quant Wheel: Wheel Strategy Complete Guide](https://quantwheel.com/learn/wheel-strategy/)
- [Days to Expiry: Best DTE for Credit Spreads](https://www.daystoexpiry.com/blog/best-dte-for-credit-spreads-a-data-driven-comparison-of-30-45-and-60-day-trades)
- [Traders Reserve: 45 DTE Sweet Spot](https://tradersreserve.com/45-dte-the-sweet-spot-for-options/)

**Rolling and adjustments:**
- [Option Alpha: Beginner's Guide to Rolling Options](https://optionalpha.com/learn/rolling-options)
- [TradeStation: Rolling Options Key Points](https://www.tradestation.com/insights/2025/10/29/rolling-options-key-points/)
- [Options Trading IQ: When to Roll Covered Calls](https://optionstradingiq.com/when-to-roll-covered-calls/)
