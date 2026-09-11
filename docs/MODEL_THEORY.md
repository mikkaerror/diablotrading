# Model Theory

Revised September 10, 2026. See [Model Research Guidelines](MODEL_RESEARCH_GUIDELINES.md)
for the concrete review contract and initial experiment queue.

## Premise

The model should help identify profitable opportunities in the AI infrastructure
cycle. Business growth, stock mispricing and option payoff are separate claims.
Current weighted scores organize research; they are not calibrated win
probabilities. Arithmetic correctness does not establish predictive value.

Guidelines that fail their purpose should be corrected or tested against an
alternative. Research can proceed while production trading gates remain closed.

## Observe

Check source dates, units, missingness, session completeness and instrument
horizon. Old observations may support explicitly historical research, but
cannot be presented as current execution evidence. Preserve the inputs that
were actually available at prediction time.

## Form a hypothesis

Translate industry knowledge into a falsifiable claim: which supplier gains,
what changes in its economics, what investors may underestimate, and when the
change should become observable. Match the research horizon to the claim.

Do not require every longer-horizon thesis to pass an earnings-entry window.
Do not treat a category label or repeated technical input as independent proof.
Missing evidence is an uncertainty to report, not an invented negative value.

## Compare

Freeze the current baseline, challenger, target, holding period, costs and
success criterion before evaluating later outcomes. Keep event-related rows
together and prevent post-outcome information from entering the predictions.

Ask:

- Do selected stocks outperform a suitable benchmark over the declared horizon?
- Do option structures earn net value after premium, spreads and costs?
- Do added features improve results beyond a simple momentum or valuation rule?
- Which future winners were filtered out, and how many losers would loosening
  that filter also admit?
- Are improvements robust to concentration, missing observations and downside?

Legacy archive diagnostics can reveal defects without qualifying as fitting
data. A failed challenger is useful evidence; it does not justify moving its
success criterion after seeing the results.

## Validate and review

Software tests verify implementation. Empirical validation evaluates predictive
value. Paper-promotion requirements evaluate a separate authority boundary.
Neither enough rows nor one successful live trade satisfies all three.

Separate source-qualified paper outcomes, shadow simulations and operator live
results. Scores and findings cannot approve, reject, close or promote tickets.
The operator performs allowed manual actions; agents never enable live trading
or broker submission. No guideline revision changes runtime thresholds or risk
constants by itself.

## What the architecture supports

Deterministic formulas, explicit source lineage, reproducible comparisons and
fixed evaluators make decisions inspectable. They do not guarantee returns.
The research objective is to identify which measurements add predictive value,
correct those that are misdefined, and retire those that do not earn their place.
