# Four-eyes review and position attribution

Operator request: 2026-09-30, mission `mission-6ceb2a39`.
Implementation is research-only; no risk value, trading gate or prereg rule changes.

## Review contract

Prepare and test a policy change in an isolated checkout. Its commit message
must contain exactly one `Agent-Author: codex` or `Agent-Author: claude` trailer.
The other agent reads the full diff, fixed rules, tests and measured effects,
then appends a substantive note using the command-center `note` CLI. Include
this exact marker in the note body, replacing COMMIT with its full 40-character
SHA (the rest of the body states findings, concerns and validation):

```
[four-eyes commit=COMMIT author=codex verdict=approved]
```

The note's actual `author` must be `claude` for a Codex commit, or vice versa.
A second Codex worker is not a Claude review. A rejected or pending review does
not pass. Revisions create a new commit and require fresh evidence.

Only after Mikka explicitly approves that concrete change, record one JSON
acknowledgement in `coordination/operator_acks/`. Template (not an approval):

```json
{
  "scope": "four-eyes-change",
  "active": false,
  "operator": "Mikka",
  "authorAgent": "codex",
  "changeCommit": "FULL_COMMIT_SHA",
  "reviewNoteId": "OTHER_AGENT_NOTE_ID",
  "approvedAt": null,
  "operatorStatement": null
}
```

Use the actual dated operator statement and set active true only after consent.
Revoke by setting active false; duplicate/conflicting acknowledgements fail
closed. These local records are attestations, not cryptographic proof of who
used the keyboard. Agents must never invent either signature.

## Nightly boundary audit

`python3 inferno_boundary_audit.py` writes
`data/inferno_boundary_audit.json` and `reports/boundary_audit_latest.txt` and
exits 1 on missing evidence or incomplete history. `nightly_optimize.sh` invokes
it before refreshes; the loop preserves the failing report and exit code while
continuing unrelated research work. Doctor and command center expose its verdict.
This is an audit, not a new ticket approval or broker execution path.

The fixed prospective adoption baseline is `4c8c9d0d01ce1dacf1a09d2842f0b7b087528a85`.
Older commits are not retroactively declared reviewed. Every newer protected
commit is rechecked nightly, including intermediate changes later reverted,
side branches reachable through merges, and merge resolutions. Missing baseline
history is an error, not a clean audit. Use a full Git checkout on audit hosts.

`SAFES` in the module lists policy, authority, paper execution, promotion,
prereg and governance files; risk/authority prefixes and prereg documents are
also protected. Registered collectors/documents are discovered from **both old
and new** registry versions. Removing a registration cannot hide a collector edit.
Every touched protected file requires review, even a non-policy edit. No semantic
classifier is trusted to decide that its own code changes are harmless.

The external **Claude/Cowork 21:30 hygiene + boundary audit** remains independently
owned. Its nightly checklist is now:

1. Run `python3 -B inferno_boundary_audit.py --check` in the canonical Mac checkout
   (or a complete synced repository). This stdout-only mode writes no reports or
   bytecode. Inspect every alert and uncommitted safety path.
2. Inspect referenced peer notes and Mikka ack provenance, plus the existing
   safety diff and prereg-integrity checks. A machine pass alone is not a review.
3. Report `POSSIBLE BOUNDARY DRIFT` for missing evidence. Never add approvals or
   advance the baseline to make a run green. Leave its independent role receipt
   only after that review. The local machine audit does not forge this receipt.

The existing Cowork task `Inferno nightly hygiene` (21:30 daily) is updated
through Claude Desktop to run this stdout-only check. Folder, model, cadence and
permissions remain unchanged. No on-demand task run or notification was sent.

## Sleeve fields for Claude's monthly attribution

`inferno_live_account_sync.json.positions[]` and the downstream live position
review preserve `assetType`, `sleeve`, `sleeveStatus`, `sleeveSource`, `sleeveAsOf`
and `sleeveSourceHashes`. The existing score-based `bucket` stays separate and
never assigns an attribution sleeve.

- `options`: broker OPTION instrument or recognizable OCC option contract;
  takes precedence over the underlying's share label.
- `holds`: shares explicitly listed in `data/operator_long_term_holds.json`.
- `core`: signed plan's core vehicle, on/after signoff, or an explicit assignment.
- `conviction`: explicit, dated position assignment. A high score, model BUY or
  membership in the research universe is not an attribution assignment.

Optional `data/operator_position_sleeves.json` format for future recorded
purchases/assignments (do not invent positions or approvals to populate it):

```json
{
  "positions": [
    {"symbol": "EXAMPLE", "sleeve": "conviction", "effectiveFrom": "2026-10-01",
     "effectiveUntil": null, "source": "operator's dated purchase/attribution record"}
  ]
}
```

EffectiveUntil is exclusive. Overlapping/invalid active assignments produce
`sleeve=null, sleeveStatus=conflicted`; no assignment produces `unclassified`.
Unclassified value stays in monthly reconciliation, never silently dropped.
Cash/reserves are account balances, not security positions in these four tags.

Each successful source observation + mapping is saved by content hash under
`data/position_sleeve_history/`; identical refreshes deduplicate. Old snapshots
are retained when tags change. Start coverage at actual collection: current
hold declarations do not establish historical membership, and no pre-adoption
month is backfilled. These tags alone do not provide time-weighted returns,
realized P/L, cash-flow attribution or permission to buy/sell.
