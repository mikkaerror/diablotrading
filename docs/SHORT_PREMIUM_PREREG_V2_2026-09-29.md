# Short-premium forward test — pre-registration v2

- **Registered:** 2026-09-29, before any v2 record exists. Research-only.
- **Supersedes the collection method of:** `docs/SHORT_PREMIUM_PREREG_2026-07-07.md` (v1).
- **Collector:** `inferno_short_premium_shadow.py` → `data/inferno_short_premium_shadow.json`,
  `reports/short_premium_shadow_latest.txt`.

## Why a v2, stated plainly

v1 asked for 60 forward events over 40 names by 2026-10-05. Nothing on the desk
ever generated a short-premium record: the strike selector only builds long
straddles and call debit spreads, and the Schwab chain capture is limited to 12
symbols. v1 therefore reaches its time-box at **0/60 events**. That is a process
failure, not evidence for or against the hypothesis, and it is recorded as
**v1: expired unrun** — not as a KILL of the idea, and not as support.

The backward lead is unchanged and still only a lead: on the 2026-09-29 rerun
(n=65 events / 50 names, conservative 3R cap) mean net-R ex-two-best was +0.149
with a name-clustered CI of [0.007, 0.36], but wing credit was not modeled.

## What changes (method only)

| | v1 | v2 |
|---|---|---|
| Source of records | operator paper fills (none ever arrived) | automatic shadow records from real Schwab chains |
| Structure | "short strangle / iron condor with wings" | **iron fly**: sell the ATM straddle, buy wings 2 implied moves out each side — the defined-risk version of exactly the payoff the backward study modeled |
| Entry | pre-earnings | 1–7 days before earnings, regular-session quotes only, first expiry after earnings, ≤ 21 DTE |
| Friction | full bid/ask | unchanged: **shorts at the bid, wings at the ask** (full crossing). A mid-fill figure is reported for context only and never used by a gate |
| Settlement | real close | exact expiration-day close, intrinsic (same proxy the shadow ledger uses) |
| Sizing | ≤ 4% of risk per name | equal risk per event: net-R = P&L / max loss |
| Skips | — | credit ≤ 0 after crossing, max loss > 4× credit, short-leg spread > 50%, chain doesn't reach wings. Every skip is logged per event: if friction is what stops the trade, that is a finding |
| Time-box | 2026-10-05 | **2027-02-28** (covers the Q3 and Q4 2026 earnings seasons) |

## Gates (unchanged from v1)

CONFIRM (all): ≥ 40 names · ≥ 60 events · mean net-R ex-two-best > +0.10 ·
name-clustered 95% CI low > 0 · worst-2-name share of losses < 40% · no name > 4% of risk.

KILL (any): ≥ 60 events with CI crossing zero · ex-two-best mean ≤ 0 at ≥ 60 events ·
worst-2 share ≥ 40% at ≥ 40 names · time-box reached without 40 names / 60 events.

## What a CONFIRM would and would not mean

Shadow records are not fills. A v2 CONFIRM only opens an operator-paper
confirmation phase (real paperMoney fills of the same structure, scored the same
way). No authority, broker, or risk-constant change is contemplated at any
outcome.

## Known limitations (binding)

- Capture timing: the chain tape is taken near the open, when spreads are widest.
  Full crossing at that moment is the harshest reasonable fill. Better capture
  timing is an input fix (see Codex mission), not a gate change.
- Breadth depends on the chain capture covering earnings-window names. Until the
  capture widens beyond 12 symbols, v2 cannot reach 40 names in time.
- Hold-to-expiration intrinsic ignores early assignment and pin risk.
- No thresholds, structure, or skip rules may change after the first record.
  Any change needs a v3 registered before its own data.
