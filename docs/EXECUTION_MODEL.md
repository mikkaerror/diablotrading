# Execution Model

The desk does not jump from signal to live trade. It moves through controlled
authority stages, and every stage leaves an artifact.

## Current Authority

```text
authorityLevel: paper-evidence-only
brokerSubmitAllowed: false
liveTradingAllowed: false
```

The locally configured approved live account is approved for read-only
oversight only. Real-money orders require explicit user confirmation and are
not automated.

## Execution Doctrine

1. Signal is not permission.
2. Approval is not execution.
3. Paper evidence is the promotion gate.
4. Broker surfaces are outputs, not brains.
5. Authority is computed from evidence, never granted by mood.

## Flow

```text
Tracker signal
  -> shortlist
  -> approval queue
  -> execution intent
  -> strike plan
  -> paper ledger
  -> outcome review
  -> authority manifest
  -> broker preview
```

The flow stops at the first failed gate. A failed gate is useful information,
not an error to route around.

## Roles

- Strategist: ranks names and separates earnings plays from long-term ideas.
- Approval Desk: turns candidates into explicit yes/no decisions.
- Execution Clerk: converts approved names into broker-neutral intents.
- Risk Policy: blocks stale, oversized, illiquid, or duplicated exposure.
- Paper Loop: stages, tracks, exits, and scores rehearsals.
- Broker Surface: displays or previews orders only after upstream gates pass.

## States

- `pending`: candidate exists, approval still required.
- `approval-ready`: approval, trigger, setup, and budget all pass.
- `paper-staged`: valid ticket is ready for paper rehearsal.
- `paper-blocked`: thesis may exist, but risk, quote quality, size, or setup fails.
- `review`: live position or paper result needs operator attention.
- `promotable`: evidence clears sample, expectancy, drawdown, and risk gates.

## Hard Rules

- No auto-submit until the paper evidence loop has a real track record.
- No order intent without approval or an explicit logged manual override.
- No broker automation that bypasses risk policy.
- No script should both rank names and submit real orders.
- No authority change outside the authority controller.

## Operator Commands

```bash
python3 inferno_execution_clerk.py
python3 inferno_execution_clerk.py build
python3 inferno_approval_queue.py status
./run_inferno_approval_inbox.sh
./run_inferno_strike_cycle.sh
./run_inferno_paper_evidence_loop.sh
./run_inferno_broker_preview.sh
python3 inferno_doctor.py
```

## Promotion Standard

A strategy can earn more authority only after it has:

- enough scored paper outcomes
- positive expectancy after realistic friction
- acceptable drawdown
- clean quote and liquidity behavior
- no unresolved doctor warnings
- broker preview payloads that pass validation
- tested kill switches and hard risk caps

Until then, the desk remains paper-evidence-only.
