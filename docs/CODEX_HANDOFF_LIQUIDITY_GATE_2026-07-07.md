# Codex handoff — flip the paper liquidity gate to spread-primary

- **Date:** 2026-07-07
- **From:** Claude (research lane) → **Codex** (owns `inferno_schwab_*`)
- **Lane:** this touches `inferno_schwab_options.py`, which is yours. I built the
  acceptance test but did **not** change the gate. This is the implementation ask.
- **Authority:** unchanged. Research/paper quality gate only. `liveTradingAllowed`
  / `brokerSubmitAllowed` untouched. No risk constant edits.

## Why

The campaign is stuck at 1/30 distinct events. The `thin-atm-liquidity` flag /
`atmLiquidityScore < 70` gate fires on **10 of 12** names in the live pull and
admits only IREN + CLSK — the two crypto-miners — because meme volume tightens
their quotes. The funnel is both starved and biased toward the names least like
what the straddle campaign is meant to test. Full diagnosis:
`docs/LIQUIDITY_METRIC_MISCALIBRATION_2026-07-06.md`.

## The rule to implement (paper side)

Make the ATM bid/ask **spread** the primary tradeability gate, and for PAPER
admit wide names while charging the full spread as friction (don't hard-exclude
them). Concretely, for the paper/quality gate that currently sets
`thin-atm-liquidity`:

- Use the robust window spread `atmWindowMedianSpreadPct` (fall back to
  `atmSpreadPct`) — not a single ATM strike, not raw volume.
- PAPER admit if: `spread <= 0.20` **and** `spread <= 0.25` hard-wide ceiling
  **and** `atmWindowOpenInterest >= 250`.
- LIVE (future) tighter gate: `spread <= 0.12` and same OI floor.
- Stop letting raw `volume` alone lift a wide-spread name over the line.
- Ensure the paper fill/pricing model charges the **full** ATM spread as cost so
  admitting a 15% name is honest, not a free pass.

Thresholds are my proposed defaults — tune if you have a better basis, but keep
spread primary and keep the OI floor.

## Acceptance test (already written, runnable)

`inferno_liquidity_reference_basket.py` — research-only, reads the live snapshot.

```
python3 inferno_liquidity_reference_basket.py run      # prints the verdict table
python3 inferno_liquidity_reference_basket.py assert    # exits non-zero if a
                                                        # reference-basket name fails
```

On tonight's pull it shows: current gate admits 2 (IREN, CLSK); proposed paper
gate admits 6 (adds GLW, FCX, CCI, TXN); HIVE/AZZ correctly still fail as
genuinely wide. Reference-basket (GOOG/AAPL/MSFT/SPY) was absent tonight so
acceptance was N/A — **re-run `assert` on a pull that includes them; it must
pass.** Add that as a unit test: a normal-chain GOOG/AAPL/MSFT/SPY MUST clear the
paper gate, or the gate is miscalibrated by construction.

## Definition of done

1. Paper liquidity gate is spread-primary per above; `thin-atm-liquidity` no
   longer fires on GLW/FCX/CCI/TXN-class names on normal chains.
2. Paper fill model charges the full ATM spread as friction.
3. `inferno_liquidity_reference_basket.py assert` passes on a pull containing the
   reference basket; a unit test enforces it.
4. HIVE/AZZ-class (>25% spread) still fail.
5. Full suite green; authority invariant clean; you commit in your lane.

## After you ship

The campaign funnel should start staging paper tickets on real large-caps. The
distinct-event cap + clustering (already shipped) keep the resulting evidence
independent. Then it's time + events toward the 30-event verdict per
`docs/CAMPAIGN_KILL_GATES_2026-07-06.md`.
