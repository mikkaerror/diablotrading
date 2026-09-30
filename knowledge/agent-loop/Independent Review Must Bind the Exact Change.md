# Independent Review Must Bind the Exact Change

A review of a nearby diff is not review of the deployed change. Hypothesis:
exact commit, distinct agent, unique review note and operator acknowledgement
prevent accidental reuse of authority. Falsifier: an altered commit, self-review,
revoked OK or removed registry entry can pass the fixed evaluator.

Evaluator: `tests/test_inferno_boundary_audit.py`. Nightly checks never advance
a successful cursor past unresolved commits; missing history stays an error.
Do not let unattended agents edit the evaluator or manufacture its evidence.

Attribution is likewise sourced: scores do not assign position sleeves. Keep
unclassified value and immutable observation/mapping snapshots visible.

See [[FOUR_EYES_AND_SLEEVE_ATTRIBUTION]].
