# Operator Tracker Role-Policy Template

This is a human-owned input contract for the 146-name tracker. It is optional
and is not created, edited, or applied by Inferno. Copy the empty skeleton
manually to `data/operator_tracker_role_policy.json` only when you are ready to
record your own decisions. The validator reads that file only; it never writes
it, changes tracker membership or eligibility, generates an allocation, or
creates a broker action.

Use one decision for every tracker symbol. Existing holdings are context only;
they are not implicit additions or DCA approvals. Leave unknown decisions out
until you can state a human rationale—an incomplete file stays incomplete.

```json
{
  "version": 1,
  "operator": "human-identifier",
  "updatedAt": "YYYY-MM-DDTHH:MM:SS-06:00",
  "decisions": []
}
```

Each item in `decisions` must have exactly these required meanings:

| Field | Required value |
| --- | --- |
| `ticker` | A symbol already retained in the full tracker. |
| `portfolioRole` | One of: `core compounder`, `cyclical`, `thematic satellite`, `speculative/research-only`, or `exclude-from-DCA-research`. |
| `dcaResearchInclusion` | `include-in-DCA-research` or `exclude-from-DCA-research`. This is research scope only, not an eligibility or purchase instruction. |
| `decisionAt` | ISO-8601 timestamp for the operator decision. |
| `decisionSource` | Exactly `operator`. |
| `rationale` | Brief human-authored reason and source context. |

Do not add `targetWeight`, `weights`, or any weight-like field. Target weights
remain a separate, explicitly approved human policy and this contract rejects
them by design. A valid role-policy contract still does not authorize a
purchase, DCA allocation, eligibility change, paper-ticket action, or broker
action.

Validate only with:

```bash
./inferno tracker-role-policy
```
