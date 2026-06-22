# Diablo Daily Model Refresh - 2026-06-22

**Stage:** research-only
**Authority change:** none
**Live trading allowed:** false

## Date clarification

The implementation work described as "yesterday" was committed between
00:39 and 01:31 Mountain Time on June 22, 2026. It was last night's session,
but the repository timestamps are June 22 rather than June 21.

## Research and implementation progress

1. Converted the market-discipline research into a source-ranked operating
   plan covering strategy selection, sizing, exits, turnover, and behavior.
2. Added a binding no-averaging-down rule and an operator decision journal.
3. Added decision cards containing thesis, contradictions, maximum loss,
   exits, net Greeks, volatility context, and liquidity.
4. Added net-R expectancy after modeled friction, separated by paper/shadow
   source and risk-passed/risk-failed construction.
5. Added observational entry/exit DTE cohorts; 21 DTE remains a review point,
   not a universal automatic exit.
6. Added turnover, winner/loser holding-time, journal, and rapid-reentry
   audits.
7. Added process-compliance, portfolio-theme heat, and wheel-feasibility
   controls.
8. Added stale Schwab-chain blocking and long-vol guards for premium, spread,
   event proximity, and account-size fit.
9. Decomposed 96 long-vol observations by ticker, time, and implied-move
   bucket. The historical edge is not admissible: excluding DELL and HPE,
   79 observations average about -0.42R; the newest 24 beat implied move 0%.
10. Exposed six positive-R/implied-move conflicts and 34 repeated-fingerprint
    excess records instead of silently deduplicating them.
11. Kept SNX and AZZ blocked because construction, freshness, size, spread,
    liquidity, and source-divergence checks do not support staging.
12. Passed 1,298 tests and pushed the work to `main` at `26866c1`.

## Current freshness

- Tracker snapshot: refreshed June 22 at 08:37 Mountain; 146 rows.
- Current eligible/review ticker: AZZ only, before fresh broker-chain review.
- Schwab account packet: failed June 22 at 07:18; old access token is expired.
- Schwab option tape: June 17; stale.
- Schwab price history: June 19; stale.
- Paper promotion evidence: 1 of 30 scored outcomes.
- Fast-paper cohort: four exits waiting on current option quotes.
- Live options maximum-loss authority: $0.

## Today's ordered action list

1. **Repair Schwab authorization once.** Run
   `python3 inferno_schwab_oauth.py restart`, complete consent once, and paste
   only the newest redirect URL.
2. **Verify token health.** Run `python3 inferno_schwab_oauth.py status`.
   Require `reauthorizationRequired: False` and a positive access-token clock.
3. **Refresh approved-account truth.** Run
   `./run_inferno_schwab_account_sync.sh --json`; verify suffix 8499, NLV,
   cash, and four holdings.
4. **Refresh the option-chain tape.** Run
   `./run_inferno_schwab_daily_ops.sh`; require fresh source time and inspect
   spread, liquidity, Greeks, and errors.
5. **Refresh daily candles.** Run
   `./run_inferno_schwab_price_history.sh --from-snapshot --limit 20`.
6. **Recompute the TOS-authored metrics from Schwab.** Run
   `./run_inferno_schwab_tos_metrics_sync.sh --from-snapshot --limit 20`.
7. **Rebuild and reconcile the tracker snapshot.** Run the morning pipeline
   with `--skip-email`; verify the Google tracker, earnings dates, prices, and
   the 146-row universe agree.
8. **Rerun formula and theory audits.** Confirm RVOL, Pv52H, momentum, ATR%,
   strength, and support/resistance values are current and correlated
   companions are not double-counted.
9. **Rebuild live-account and position review.** Recalculate weights,
   support/resistance distance, theme heat, and add/trim posture from the fresh
   account and tracker.
10. **Close the four due fast-paper observations.** Price PL, GOOG, SHLS, and
    SPXC from current executable bid/ask data; keep them exploratory and
    promotion-ineligible.
11. **Run the paper evidence harvest.** Reconcile exits, mark-to-market,
    scenario evidence, outcome attribution, and exit exceptions before adding
    replacements.
12. **Refresh expectancy and regime diagnostics.** Rebuild net-R, expected
    move, DTE, behavior, score calibration, and concentration reports.
13. **Reprice strategy alternatives.** Compare defined-risk debit, credit,
    condor, shares, and cash for current candidates; do not stage stale or
    risk-failed structures.
14. **Rebuild capital readiness.** Recalculate allocator sleeves, theme heat,
    contract affordability, reserve cash, and the live-options $0 gate from
    fresh NLV.
15. **Finish with the doctor and command center.** Run
    `python3 inferno_doctor.py` and
    `./run_inferno_model_command_center.sh`; record unresolved warnings and
    commit only durable code/docs changes.

After step 1 restores OAuth, steps 2-15 can be run as one research-only job:

```bash
./run_inferno_daily_model_refresh.sh
```

Use `./run_inferno_daily_model_refresh.sh --skip-tracker` when the tracker
snapshot has already been refreshed and only broker/model derivatives need an
update.

## Schwab conclusion

The operator should not have to refresh separately for every model component.
The desk now reuses a healthy access token, refreshes only near expiry, and
serializes refresh attempts.

A periodic full Schwab OAuth restart may still be mandatory because the broker
controls refresh-token lifetime and revocation. The achievable fix is one
explicit re-consent step when required, not repeated refreshes for account,
options, price history, and TOS metrics.
