# Full-Tracker DCA Operating Plan

**Adopted:** 2026-07-20
**Owner:** Codex, with the operator retaining all capital-allocation decisions
**Status:** Active research and systems plan; no broker authority change

## Outcome we are building toward

Run one trustworthy investment-research operating loop for the whole
operator-maintained tracker—not just a small thematic basket—so each future
deposit can be reviewed through diversification, current holdings, evidence,
and conviction. The system must make careful allocation easier; it must never
turn research output into an automatic purchase or order.

The **146-name tracker** is the broad research universe. The **30-name AI
basket** remains a monitored thematic sleeve inside that universe. It is not
the complete portfolio authority and it does not supersede the tracker.

## What automation means here

Automate repeatable evidence work; keep decisions that move money human-owned.

| Automated research operations | Human-owned decisions |
| --- | --- |
| Tracker and read-only market-data refresh | Whether, when, and how much cash to deploy |
| Full-universe scoring, taxonomy coverage, holdings joins, and concentration diagnostics | Deposit amount, allocation policy, and any actual purchase |
| Report generation, freshness checks, test execution, and duplicate-work suppression | Tracker membership and eligibility changes |
| Paper/shadow options research and evidence accounting | Paper ticket approval/rejection/close/promotion and all broker actions |

Hard boundary: `liveTradingAllowed`, `brokerSubmitAllowed`, and
`submit_live_order` stay disabled. Options candidates, paper candidates,
previews, and research ranks are never order approvals.

## Current operating truth

As of the 2026-07-20 command-center read:

- The account is read-only, with zero confirmed deployable cash.
- The current live book is concentrated in digital-infrastructure miners and
  TE; portfolio heat is high and effective theme breadth is low.
- The conviction engine retains all 146 scored tracker rows. Current research
  output has 12 long-term research-qualified rows; that is coverage, not a
  funding instruction.
- Reference taxonomy covers all 146 tracker names. `GLDD` uses a bounded,
  source-labelled verified reference because its live yfinance endpoint no
  longer supplies sector/industry data after the 2026 acquisition/delisting.
  The classification remains `Industrials / Engineering & Construction`, with
  company, SEC-registrant, and provider-profile evidence retained in the
  taxonomy artifact; it is not guessed or silently excluded.
- The AI basket is a complete 30-name research sleeve, separate from the
  broader tracker.
- The options/paper lane has a 29-outcome promotion gap. It remains an
  evidence lab and cannot compete with DCA dollars or influence live authority.
- The existing paper loop creates useful diagnostics, but technical activity is
  not counted as investment evidence unless a promotion-gate metric moves.

Generated artifacts are the source of current truth. See
`reports/model_command_center_latest.txt`, `reports/portfolio_heat_latest.txt`,
`reports/conviction_research_latest.txt`, and
`reports/paper_velocity_latest.txt` before making time-sensitive claims.

## Target architecture

```text
Operator-maintained tracker (146 names)       Read-only broker book
                 |                                      |
                 v                                      v
    Reference taxonomy (sector / industry / broad exposure)
                 |
                 v
          Full-tracker registry  <----- holdings / tracker reconciliation
                 |
                 +--> taxonomy + data-quality coverage
                 +--> full conviction ranking (research only)
                 +--> concentration / overlap diagnostics
                 |
                 v
      Operator role / DCA-inclusion review queue
                 |
                 v
      Deposit-plan decision support (future research-only build)
                 |
                 v
   Operator chooses whether to allocate; broker action remains separate

Paper/options lab ---> closed evidence / promotion gate ---> never auto-funds DCA
```

## Work plan and acceptance gates

### 1. Establish complete tracker truth — now

Build `inferno_tracker_registry.py` and its report as the canonical join of
the tracker, durable conviction ranking, and read-only holdings. It must:

- retain every tracker row;
- mirror current eligibility rather than changing it;
- show category/economic-exposure coverage and explicitly identify unknowns;
- match broker holdings to tracker names without making add/trim/exit calls;
- distinguish research qualification from portfolio fit;
- emit no target weights, dollar amounts, purchase instructions, or broker
  action.

**Gate:** all tracker rows are retained; every taxonomy gap is explicit; any
held name outside the tracker is visible.

### 2. Complete canonical taxonomy — next

The automated reference layer establishes fresh, source-labelled sector,
industry, and broad economic exposure for every tracker name it can verify.
It is deliberately not a portfolio-role or allocation policy. The remaining
operator-reviewed metadata is:

- economic exposure and sector/industry taxonomy;
- role in a portfolio (core compounder, cyclical, thematic satellite,
  speculative/research-only, or exclude-from-DCA-research);
- material factor and theme overlap;
- data-quality and evidence provenance.

Unknown is a valid value. The system must not fabricate classifications simply
to make a dashboard look complete.

`./inferno tracker-role-review` now creates the full 146-name review queue.
It surfaces the four existing operator-declared long-term holdings as context
only; those declarations do not approve new additions, portfolio roles,
DCA-inclusion, or target weights.

`./inferno tracker-role-policy` is the next read-only governance layer. It
looks only for the optional human-owned
`data/operator_tracker_role_policy.json` and validates its coverage against
every retained tracker name. Its empty starting point is documented in
`docs/OPERATOR_TRACKER_ROLE_POLICY_TEMPLATE.md`; Inferno never creates or edits
that input. The contract rejects target weights so a future human allocation
policy remains a separate authority source.

`./inferno tracker-role-policy-packet` adds a complementary blank 146-row
worksheet in JSON and CSV. It carries the queue's source-labelled reference,
hold, and research context while leaving the role, DCA-research inclusion,
date, source, and rationale cells empty for every name. It is not policy input
and has no import path: completing it cannot change an operator decision,
tracker membership, eligibility, tickets, broker state, or authority. A human
must manually prepare the separately owned policy file before the contract
will read it. The packet contains no target-weight field.

**Gate:** with source-labelled references covered, have the operator record a
portfolio-role and DCA-research decision for every retained row using the blank
packet and then validate the manually created policy file. This is a metadata
and governance gate, not an eligibility change, target-weight policy, or
purchase instruction.

### 3. Build deposit-sized DCA decision support — after taxonomy

Create one research-only daily/deposit decision surface. For an explicit,
operator-entered amount of broker-confirmed cash, it will show:

- current holding concentration and overlap;
- research candidates by tier, source quality, and exposure contribution;
- a proposed diversified *research allocation* that is capped by the
  operator-approved policy;
- a reserve / stand-aside outcome whenever data, diversity, or evidence is
  inadequate;
- a decision log that records the operator's actual choice separately.

It must not place, stage, approve, reject, close, or submit anything. It must
not treat planned deposits, paper P/L, cash changes, or NLV changes as proven
deployable capital.

**Gate:** no DCA calculation runs against unconfirmed cash; no proposal can
silently modify eligibility, risk constants, sleeves, or the broker book.

### 4. Simplify the options evidence lab — parallel maintenance

Keep the options lane independent from accumulation work. Its measurable
success condition is not job count; it is progress toward 30 closed,
promotion-quality paper outcomes. Reporting must distinguish:

- auto-paper research candidates;
- operator-routable paper candidates;
- scenarios and fast simulations that have no promotion credit;
- actual closed, scored paper evidence.

**Gate:** every dashboard uses the same semantic fields, especially
`operatorRoutablePaper` rather than legacy combined counts.

### 5. Operate by one honest daily brief

The command center should eventually show only the decisions and bottlenecks
that matter:

1. broker truth and confirmed cash;
2. current concentration and tracker/holding reconciliation;
3. full-tracker coverage and any missing taxonomy;
4. deposit-plan research when cash is confirmed;
5. paper-evidence gate movement, separately.

A scheduled job that refreshed stale data or found no new evidence should say
so plainly. It must not claim productive progress merely because it ran.

## Success measures

| Measure | Productive result | Not progress |
| --- | --- | --- |
| Tracker coverage | 100% retained, joined, and taxonomy-accounted | A top-N digest hiding the rest |
| Holdings reconciliation | Every broker holding matched or explicitly flagged | Treating watchlist membership as ownership |
| DCA construction | Deposit-sized, diversified research proposal after confirmed cash | A rank becoming an automatic buy |
| Concentration | Measurable diversification impact against the existing book | More names with the same economic exposure |
| Paper lab | Closed scored outcomes reduce the 30-outcome gap | Simulation volume or report volume alone |
| Automation quality | Fresh source lineage and accepted gate movement | Successful commands with no measurable delta |

## Immediate implementation sequence

1. Ship the full-tracker registry and test its research-only boundary.
2. Generate the first coverage report and inventory missing taxonomy.
3. Reconcile its holdings join with the separate basket/holdings work already
   in the repository; do not overwrite that work.
4. Review the source-labelled taxonomy coverage, resolve explicit source gaps,
   and define the operator-controlled role/diversification policy.
5. Only then design the deposit-plan allocation policy and its explicit
   user-input contract.

## Non-goals

- Creating an ETF or enabling fractional broker automation.
- Changing the eligible universe or risk constants.
- Recommending or executing trades from a score alone.
- Folding paper/shadow P&L into real capital or inferring realized options
  profit from cash changes.
- Allowing the options lab to pull capital away from the long-term accumulation
  process before it earns evidence-based authority.
