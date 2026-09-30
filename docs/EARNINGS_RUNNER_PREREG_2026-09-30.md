# Earnings Runner Campaign — pre-registration

- **Registered:** 2026-09-30, before any record exists. Research-only, paper/shadow.
- **Asked for by:** Mikka ("I want to play earnings ... time these options plays
  correctly on the days they don't jump ... catch some runners").
- **Collector:** `inferno_earnings_runner.py` → `data/inferno_earnings_runner.json`,
  `reports/earnings_runner_latest.txt`. Morning email shows the scoreboard.

## Why three arms

The desk's own evidence says holding long premium *through* the report loses
(738 shadow closes, −0.15R; call debit spreads −0.64R). Two ways of playing
earnings avoid that and have some outside support, and the operator's own
timing deserves its own scoreboard:

| Arm | Idea | Outside evidence |
|---|---|---|
| **A · Run-up** | Buy before the report, sell before the announcement. Never hold through. | Gao, Xing & Zhang (JFQA): ATM straddles held into the announcement earned 2.3–3% before costs; thin after costs. |
| **B · Runner** | After a gap that holds, buy a debit spread in the gap's direction while IV is crushed. | Classic post-earnings drift has largely faded outside microcaps (Martineau 2022; Subrahmanyam 2025). The case here is cheap post-report options, not a proven drift. |
| **C · Mikka's calls** | Mikka tags ticker + direction; the desk builds the defined-risk ticket. | None — this arm *is* the test of his timing. |

## Rules (fixed; any change needs a v2 registered before its data)

**Universe:** names in `latest_snapshot.json` with a Schwab chain in the tape
that day. Liquidity: every long leg's spread ≤ 25% of mid, short legs ≤ 50%.

**Arm A — Run-up**
- Window: 3–10 calendar days before the earnings date.
- Quiet-day entry: the last daily move is smaller than half the name's ATR%.
- Structure: long ATM straddle in the first expiration after earnings, ≤ 21 DTE.
  Paid at the ask.
- Exit: the last chain capture strictly before the earnings date (target T−1),
  sold at the bid. Never held through the report.
- One record per `TICKER|earningsDate`.

**Arm B — Runner**
- Trigger: the earnings date has passed; the move from the close before the
  report to the first close after it (t−1 → t+1) is at least
  max(0.75 × pre-report implied move, 5%), and the t+1 close is in the top third
  (up-gap) or bottom third (down-gap) of that day's range — the gap *held*.
- Entry: first chain capture 1–2 trading days after the report.
- Structure: debit spread in the gap's direction, expiration nearest 35 DTE
  (21–60), long ATM, short the first strike ≥ one pre-report implied move away
  (min 5%). Long at the ask, short at the bid.
- Exit: +50% of the debit at natural prices, or after 10 trading days at
  natural prices, or intrinsic at expiration — whichever comes first.

**Arm C — Mikka's calls**
- Mikka records `python3 inferno_earnings_runner.py call TICKER up|down "why"`.
- Structure, entry pricing and exits: same as Arm B, entered at the next chain
  capture of that name. Scored on its own board, never pooled with A or B.

**Scoring (all arms):** return on debit = (exit − entry) / entry, full crossing
both ways. Report per arm: events, win rate, mean, median, mean excluding the
two best names, and a name-clustered bootstrap 95% CI. A record with no exit
quote is **unscored**, never estimated.

**Read-out:** after the Q3 season (review mid-Nov) and again after Q4. An arm
earns a move to operator-paper tickets only if, after ≥ 30 events, its
ex-two-best mean is > 0 and its clustered CI low is > 0. Live options remain
paused under the drawdown protocol regardless; no authority or risk constant
changes here.

## Known limitations

- Chain coverage: the tape covers 12 symbols until Codex's W4 widens it
  (earnings window, reported-yesterday names, open campaign positions,
  Mikka's calls). Until then the arms record few events.
- Shadow records are not fills. When W0 lands, arms that pass read-out become
  real paper tickets with order cards.
- BMO/AMC timing is unknown; t−1 → t+1 covers both.
