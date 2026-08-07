# Rebalance Candidate Generation

Status: active research-only pricing path; broker submit and live trading remain
disabled.

Belief: leading the pricing pass with the pre-registered short-premium arm and
re-pricing cap-busting long straddles as bounded alternatives increases valid
research coverage without changing promotion, authority, universe, or risk
policy requirements.

Evidence: `inferno_strategy_alternative_pricing.py` now places
`SHORT_PREMIUM_DEFINED` candidates before ordinary candidates. For a
paper-blocker-swarm long-straddle finding whose cap-fit estimate says the
straddle does not fit, it prices only the estimated-fit $5-wide debit,
$1-wide credit, and single-long-leg constructions. Known bullish/bearish
context suppresses the opposite directional debit or long leg; missing
direction does not invent a long-leg thesis. Each remaining attempt receives
live-chain construction, the unchanged optimizer, and
`evaluate_strike_item(..., mode="paper")`; a cap-fit estimate is not a staging
pass.

Falsifier: a fallback candidate is emitted for a straddle that fits the cap,
uses a wider debit or credit construction than declared, bypasses a quality or
risk block, changes promotion/authority/universe/risk constants, or carries a
true broker-submit or live-trading flag. Any such result is a fail-closed
safety regression.
