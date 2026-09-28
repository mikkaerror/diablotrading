# Parent Cash and Transfer Legs Are Different Grains

The 2026-09-28 transaction audit found currency/fee items first in broker transfer
arrays. Keeping only index zero hid eight option legs. Retain every redacted leg,
but sum parent net cash once. Fees cannot be allocated across securities by guess.

Balanced contract cash requires source costs, matching signed opening/closing
quantities and valid transaction identity. It is neither a count of independent
strategy events nor complete account performance. Missing inputs stay unresolved.

Falsifier: a fixture with currency first, several legs, missing fees or repeated
parent IDs must not produce hidden legs, duplicated cash or invented profit.
Failed reads must retain older evidence with its original timestamp.
