# Priority one: metric semantics repair

The operator authorized implementing priorities in sequence on September 10.
`inferno_edge_research.py` now rejects past/invalid earnings offsets for catalyst
classification and treats nonpositive/nonfinite P/E as not meaningful or invalid.
It preserves forward/trailing/tracker provenance and exposes status in scores
and report text. Only absent P/E allows fallback; a loss forecast cannot be
hidden behind a positive trailing multiple.

The existing missing-P/E scoring bucket remains in use, with no new weight or
threshold. This is still an uncalibrated scoring convention, not an assertion
that a loss-making business is worthless. Growth clipping is unchanged.

Before edits, froze 183 public tracker rows, the metadata cache and baseline
source. Reproduce with:

```sh
PYTHONPATH=. python3 outputs/metric-semantics-2026-09-10/compare.py
python3 -m unittest tests.test_inferno_edge_research -v
```

The fixed-input comparison covers all 183 names. It lowers eight edge scores
by 3.36 points each and changes zero lane assignments. No score increases.
55 names lack cached fundamentals; their missingness is retained. This is
an implementation-impact comparison, not a reconstructed historical run or
proof of better returns. No risk constants, trading universe or authority changed.
