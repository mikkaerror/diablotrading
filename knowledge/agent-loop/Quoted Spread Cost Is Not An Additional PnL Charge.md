# Quoted Spread Cost Is Not An Additional PnL Charge

The Sep 30 frozen comparison reproduced 2.93x quoted/model friction in five paper
call spreads, yet every quoted paper entry already used natural price. A better
quote-cost formula does not justify charging entry cost twice. Scenario backtest
also ignores the friction field and consumes saved outcome R directly.

Rule: identify midpoint, natural, actual-fill or intrinsic P/L basis before
subtracting transaction costs. Preserve explicit fees and unknown exit quotes.
Never revise historical outcomes or prereg rules through a reporting refresh.

Evidence: [[FRICTION_MODEL_PROPOSAL_2026-09-30]], frozen manifest and seven
`tests/test_friction_proposal.py` regressions. Falsifier: natural entry double
charged, actual fills rescored, or a friction-only patch changes no intended net
scorecard but is called a completed economics repair.
