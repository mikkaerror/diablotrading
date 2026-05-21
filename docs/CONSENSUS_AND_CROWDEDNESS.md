# Consensus and Crowdedness — Phase C Research Note

Last updated: 2026-05-20.

This is the long-form research synthesis for Research Roadmap **Phase C**:
the consensus / crowdedness layer. It asks the single most-ignored
question in retail trading: **"Am I taking the trade that everyone else
is already in?"**

Read after `docs/PORTFOLIO_CONSTRUCTION.md` (Phase B). Phase B taught the
desk to see its *own* correlations; Phase C extends that lens to the
market's positioning.

This doc is research-only. No new authority is implied. Broker submit
stays OFF. The 30-closed-scored-outcomes promotion gate stays in force.

## 1. Why this matters last, not first

The desk has spent Phases A and B building the calibration loop:
post-trade learning + portfolio-level construction. Phase C is the
*sentiment / positioning* overlay. It is genuinely the highest
intellectual leverage and the lowest operational leverage — exactly the
reason it ships last:

- A small desk can extract real edge from being *contrarian to the
  crowd* on a small universe.
- The same small desk has no way to *measure* the crowd with the
  precision a $10B fund has (CFTC reports, prime-broker positioning
  decks, third-party flow data).
- Most retail crowdedness tooling is sold as alpha and is in fact noise.
  The desk's job is to extract the small set of crowdedness *signals
  available to retail* and treat the rest as theatre.

The honest framing: **Phase C produces an advisory regime read, not
trade tickets.** When the read aligns with conviction, the desk has
permission to lean. When the read contradicts conviction, the desk needs
to size down or sit out.

## 2. The literature

### Stein (2009) — limits of arbitrage when sophisticated

In his 2009 presidential address ("Sophisticated Investors and Market
Efficiency"), Jeremy Stein formalized why even smart money sometimes
can't bring prices to fair value: when too many sophisticated traders
crowd into the same arbitrage, their *combined leverage* becomes a
risk-management problem, and a small adverse move triggers
synchronized unwind. The crowded arbitrage is fragile precisely because
its participants are sophisticated.

The retail-options implication is subtler. The desk is *not* the
sophisticated arbitrageur. But it *is* the marginal liquidity
participant whenever it takes the same side as a crowded sophisticated
trade. Stein's insight reduces to: **the trade where smart money agrees
with you is the trade you should size smaller, not larger.**

### Brunnermeier-Nagel (2004) — riding the bubble

Brunnermeier and Nagel's "Hedge Funds and the Technology Bubble"
documented that the smartest funds in the late 1990s were *long the
bubble*, then exited in time. The lesson is not "the crowd is always
wrong" — it's "the crowd can be right for a long time, and the only
durable defense is a pre-committed exit." For an options desk, that
pre-commitment lives in the drawdown protocol (Phase B §5) and in the
crowdedness regime classifier (this doc).

### Lou-Polk (2013) — Comomentum

Dong Lou and Christopher Polk introduced **comomentum**: a measure of
*excess correlation* among momentum-strategy stocks beyond their
fundamental similarity. When comomentum is high, momentum returns
subsequently *reverse* — not because the original signal was wrong, but
because too many participants were chasing it. The same logic applies
to options: when too many tickets concentrate in the same family +
direction + IV regime, the crowd's own activity has bid up the price of
that trade beyond its fair value.

The signal: **rising cross-asset correlation inside a strategy family
is a crowdedness warning, not a strength confirmation.**

### Khandani-Lo (2007) — August 2007 quant crisis

The cleanest empirical illustration of crowdedness collapse: in early
August 2007, quantitative equity funds running similar long/short factor
strategies experienced multi-sigma losses simultaneously, because they
were unwinding the same positions to meet margin calls in unrelated
books. The trades themselves had been mediocre but liquid; the *exit*
was the problem.

For our scale ($500 ticket, manual options), the takeaway is not "watch
out for quant-crisis-scale unwinds." The takeaway is structural:
**positions sized so they don't need to be unwound at adverse moments
are the only positions worth holding.** A correctly-sized $500 ticket
never participates in the unwind. An incorrectly-sized one does.

### Asness / Frazzini / Israel / Moskowitz — factor crowding research

The AQR series (multiple papers, 2014-2019) on whether factor returns
are decaying due to crowding produced two enduring conclusions:

1. **Some factors decay** when crowded (size, value when over-arbitraged
   in the 2000s).
2. **Some don't** (quality, low-volatility) because the structural
   reasons they work are not behavioral.

The options-desk analog: durable edges have a *behavioral* foundation
the crowd cannot eliminate. The desk's Master Traders citations — PTJ
R:R discipline, Klarman SIT-OUT, Marks pendulum, Taleb steamroller —
are the behavioral-foundation reminders the auditor uses for exactly
this reason.

### Soros reflexivity (covered in MASTER_TRADERS)

Reflexivity is Phase C's deepest layer. When market participants act on
their belief, their action changes the system. Crowdedness is the
material form of reflexivity: many participants leaning the same way
*creates* the conditions for a reversal. The Schwab edge bridge's
"side-skew lean" field (`put-rich` / `call-rich` / `balanced`) is a
first-pass reflexivity sensor.

## 3. What retail can actually measure

This is the operating section. The honest list of crowdedness signals
*available to a $500-ticket manual desk*:

| Signal | Source | Caveat |
|---|---|---|
| **Side-skew lean** (put-rich / call-rich) | Schwab chain `sideStats` | Already shipped. Cross-sectional, no history needed. |
| **OI concentration at specific strikes** | Schwab chain | Per-ticker. Big OI walls at round-number strikes are positioning footprints. |
| **Single-name implied vol vs sector ETF implied vol** | Schwab chain (two pulls) | Anchors below 1.0 = single name is *less* anxious than sector; above 1.5 = idiosyncratic crowdedness. |
| **Cross-name correlation regime** | `inferno_portfolio_correlation.py` family pairwise ρ | When two normally-uncorrelated families spike to ρ > 0.7, the market is treating them as one trade. |
| **Movers feed concentration** | Schwab `/movers` (not yet wired) | When the top-10 daily movers share a sector, that sector is the day's consensus trade. |
| **VIX term-structure regime** | Schwab quotes on VIX futures (not yet wired) | Steep contango = complacency; backwardation = panic. The desk's earnings plays sit inside this regime. |
| **Slate concentration vs daily-mover concentration** | Cross-join of `inferno_portfolio_correlation.py` and the movers feed | Are the desk's tickets in the same sector as the day's movers? That's the desk *being part of* a crowded trade. |
| **Reflexivity score** (composite) | Several of the above + a small linear blend | Single number, advisory only. |

What retail can **not** measure (and should not pretend to):

- Hedge fund positioning by name.
- True dark-pool flow.
- Institutional desk inventory.
- Real-time CFTC CoT (lags by days; usable as a coarse weekly read but
  not for daily tickets).
- "Smart money vs dumb money" flow (the products that sell this are
  reselling delayed CBOE prints; spend nothing here).

## 4. Verdict ladder

The desk's Phase C verdict should be a small ladder, parallel in style
to Phase B's:

- **uncrowded** — Multiple consensus signals are neutral. The slate's
  thesis can be taken at full discretion (subject to all other gates).
- **normal** — Some signals lean one way, others the opposite. Default.
- **crowded-watch** — Two or more signals lean the same way as the
  desk's slate. Operator should consciously acknowledge the
  alignment before sizing up.
- **consensus-extreme** — Three or more signals lean the same way as
  the desk's slate AND that lean is in the upper/lower decile of recent
  history. The Marks pendulum has swung; the desk should consider
  contrarian framing or smaller size.
- **awaiting-data** — Insufficient signal coverage to score (e.g.,
  Schwab not configured, no slate yet).

The ladder is advisory. The risk policy still owns the actual gate.

## 5. What we build — `inferno_consensus_monitor.py`

A single research-only module that:

1. Reads `data/inferno_schwab_edge_signals.json` for side-skew lean.
2. Reads `data/inferno_portfolio_correlation.json` for slate
   concentration (own-side) and family pairwise ρ when available.
3. Computes a small set of per-signal classifications.
4. Aggregates into the five-tier verdict ladder above.
5. Surfaces per-signal reasoning so the operator can see *why* the
   verdict landed where it did.

Out of scope for v1 (explicitly named as "not built yet" in the
artifact):

- `/movers` integration (needs movers feed adapter)
- Sector-ETF vs single-name vol comparison (needs paired chain pulls)
- VIX term-structure overlay (needs cross-asset adapter)
- News-sentiment polarity (would need a separate MCP / data source)

These are listed honestly so the next session knows what to build.

## 6. Success criteria

Phase C is shipped when:

- `inferno_consensus_monitor.py` runs cleanly against current data,
  emits a research-only verdict on the five-tier ladder, and is wired
  into the command center.
- ≥20 contract tests cover the verdict ladder, per-signal
  classifications, and empty-data path.
- `docs/PROJECT_STATUS.md` row for Phase C is added.
- Coordination note dropped.
- Authority unchanged. Broker submit OFF.

## 7. Anti-goals

- **No auto-rejection of tickets on a crowdedness verdict.** The
  operator may have a deliberate consensus-aligned thesis
  (Brunnermeier-Nagel-style "ride the bubble until the exit"). The
  module flags; it does not block.
- **No third-party "smart money" data feeds.** Not because they're
  illegal, but because the retail-priced ones are noise.
- **No "AI sentiment score" black-box.** A small, calibrated linear
  blend on signals we actually understand beats any black box at this
  scale.

## 8. How Phases A + B + C compose

The three phases produce three complementary readings on every closed
outcome:

| Phase | Reading | What it tells the desk |
|---|---|---|
| A | Outcome attribution + rule decay + slippage | "What did we learn from this specific outcome?" |
| B | Correlation + drawdown protocol | "Did this outcome diversify the book, or pile risk?" |
| C | Consensus / crowdedness | "Were we taking a contrarian or a consensus trade when we entered?" |

Closing the loop: a *consensus* trade that *won* under *poor effective
breadth* and *high family correlation* is the textbook recipe for
overconfidence. Without Phase C, the operator only sees the win.
With Phase C, the operator sees the win AND that the win was
consensus-aligned, narrow-breadth, and correlated — which is the
information needed to *not* size up the same setup next time.

## Citations

Primary references (added to `docs/THEORY_REFERENCES.md`):

- **STEIN-2009** — Stein, "Presidential Address: Sophisticated
  Investors and Market Efficiency," J. Finance 64(4)
- **BRUNNERMEIER-NAGEL-2004** — "Hedge Funds and the Technology
  Bubble," J. Finance 59(5)
- **LOU-POLK-2013** — Lou & Polk, "Comomentum: Inferring Arbitrage
  Activity from Return Correlations," working paper / Review of
  Financial Studies
- **KHANDANI-LO-2007** — "What Happened to the Quants in August 2007?,"
  J. Investment Management 5(4)
- **ASNESS-FRAZZINI-ISRAEL-MOSKOWITZ-2014** — AQR working paper series
  on factor crowding
- **SOROS-REFLEXIVITY** — already cited; see THEORY_REFERENCES

New citation tags to add when Phase C ships: STEIN-2009,
BRUNNERMEIER-NAGEL-2004, LOU-POLK-2013, KHANDANI-LO-2007,
ASNESS-FRAZZINI-ISRAEL-MOSKOWITZ-2014.

## Operating principle

> The trade everyone else is in is, by definition, the trade that has
> the most participants needing to sell in the same direction at the
> same time when the regime changes. Crowdedness is not a forecast of
> direction; it is a forecast of exit liquidity.
