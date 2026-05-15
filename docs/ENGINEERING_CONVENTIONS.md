# Engineering Conventions

How we build software on this desk. These conventions are the reason a new model or engineer can land in the repo and ship without breaking the safety rails.

Read this once. Reference it forever. Where a convention conflicts with code, **the convention wins and the code is the bug**.

Last updated: 2026-05-15.

## The non-negotiable safety rails

These come from `MODEL_COLLABORATION_BRIEF.md` and override every other convention below:

1. **Never place a trade without explicit user confirmation.**
2. **Only the configured approved live account is approved for read-only automation.**
3. **Do not open a new thinkorswim instance or extra TOS window.**
4. **Use the already-open TOS window only.**
5. **Paper evidence remains the promotion gate.**

If a convention or feature would let you violate one of these, the convention is wrong, not the rail.

## Module shape

Every `inferno_*.py` module follows the same shape:

```python
from __future__ import annotations

"""One-paragraph what this module is.

What it does: ...
What it does NOT do: ...
Strict contract: read-only / writes only / ...
"""

import argparse
import json
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


MY_MODULE_ARTIFACT_FILE = DATA_DIR / "inferno_my_module.json"
MY_MODULE_TEXT_FILE = REPORTS_DIR / "my_module_latest.txt"
MY_MODULE_STAGE = "my-module-research-only"


def build_my_module(...) -> dict[str, Any]:
    """Compute the payload. Pure function; never writes to disk."""
    ...


def my_module_text(payload: dict[str, Any]) -> str:
    """Render the payload into an operator-readable memo."""
    ...


def save_my_module(payload: dict[str, Any]) -> None:
    """Persist the JSON and text artifacts via the retry-safe writer."""
    ensure_dirs()
    atomic_write_json(MY_MODULE_ARTIFACT_FILE, payload)
    atomic_write_text(MY_MODULE_TEXT_FILE, my_module_text(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(...)
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "status" and MY_MODULE_TEXT_FILE.exists():
        print(MY_MODULE_TEXT_FILE.read_text(encoding="utf-8"))
        return 0
    payload = build_my_module()
    save_my_module(payload)
    print(my_module_text(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

This shape gives every module:
- a documented contract
- a pure `build_*` you can call from tests without disk
- a separate `save_*` so tests can inject paths
- a `_text` renderer that's also test-callable
- a uniform CLI with `run` / `status` subcommands

## Diagnostic vs operational modules

If the module is diagnostic (reports state without changing it), include in its payload:

```python
return {
    "stage": MY_MODULE_STAGE,
    "diagnosticOnly": True,
    "researchOnly": True,
    "promotable": False,
    ...
}
```

These three flags are the contract that says *this artifact cannot promote authority*. Tests must freeze them — if you ever flip `promotable` to `True` for a diagnostic, the test suite fails.

Operational modules (the ones that mutate the approval queue, paper ledger, or sheet) do not carry these flags and must instead implement their own operator-confirmation gate.

## Writes always use `inferno_io`

```python
# DO NOT do this:
path.write_text(json.dumps(payload), encoding="utf-8")

# DO this:
from inferno_io import atomic_write_json
atomic_write_json(path, payload)
```

`inferno_io.atomic_write_*` does temp-file + rename and retries on macOS's transient `errno 35: Resource deadlock avoided`. We learned this the hard way — concurrent writes were silently dropping artifacts.

Same for text: `atomic_write_text(path, content)`.
Append-only: `append_text(path, line)`.

## Failure isolation in chained runners

When a chained runner (like `inferno_daily_loop.py`) calls many subsystems, each must be wrapped so a single failure doesn't abort the chain:

```python
def _run_step(name, builder, *, saver=None):
    try:
        result = builder()
        if saver is not None:
            saver(result)
    except Exception as exc:
        return {"name": name, "ok": False, "status": "failed",
                "error": f"{type(exc).__name__}: {exc}"}
    return {"name": name, "ok": True, "status": "built", "summary": _extract_summary(name, result)}
```

The chain's digest reports `okCount` and `failedCount` honestly; the operator sees which step broke without losing the others.

## Lazy imports for heavy dependencies

`inferno_outcome_reviewer.py` imports `yfinance`, which is heavy and unavailable in sandboxes. If your module only *occasionally* needs the heavy dependency, lazy-import it inside the function that uses it:

```python
def _load_shadow_records() -> list[dict[str, Any]]:
    try:
        from inferno_shadow_evidence import SHADOW_EVIDENCE_FILE
    except Exception:
        return []
    ...
```

This pattern lets tests run without the full dep stack and lets the module degrade gracefully when the dep is missing.

## Test conventions

Every module gets a test file at `tests/test_<module>.py` that freezes:

1. The `researchOnly` / `promotable` contract (for diagnostic modules).
2. The stage constant value (so external readers can grep for it).
3. The happy-path build → save → render round trip.
4. At least one failure mode per code path.
5. The text renderer contains the expected section headers.

Tests live alongside production code. They run via:

```bash
python3 -m unittest discover tests
```

The test suite is the safety net — if you can't write a test for your change, you probably don't understand the change well enough to ship it.

## Backups before risky edits

The project carries a `scripts/inferno_backup.sh` helper. Before any non-trivial edit to a module, snapshot it:

```bash
./scripts/inferno_backup.sh inferno_strike_selector.py
```

Snapshots land in `_backups/YYYY-MM-DD/<file>.<HHMMSS>` (gitignored). `_backups/` is your recovery copy when git status is mid-flight or when an automated linter goes sideways.

## Repository hygiene before GitHub pushes

Before staging a cleanup or GitHub push, read `docs/REPOSITORY_HYGIENE.md`.
The short version:

- commit source, tests, docs, and safe workflows only
- do not commit local state, broker exports, account statements, credentials, `data/`, `reports/`, or `logs/`
- stage coherent batches instead of the whole noisy workspace
- run the command center and doctor before pushing
- if a file might reveal money, identity, account access, or private fills, it stays local

## Authority and the manifest

The desk's `data/inferno_authority_manifest.json` is the source of truth for what automated systems may do. Right now it's pinned to:

```
authorityLevel: paper-evidence-only
brokerSubmitAllowed: false
liveTradingAllowed: false
```

Code that wants to elevate must go through `inferno_authority_controller.py`. Diagnostics must never bypass it. The `inferno_daily_success` scorecard's `authorityIntact` criterion catches drift; the night-prep diagnostic catches drift before the scorecard does.

## How to add a new module

1. Pick the layer in `MODULE_INDEX.md`.
2. Copy the nearest existing module's shape.
3. Write the module docstring first; the implementation often falls out of the contract.
4. Write the tests next.
5. Wire it into the daily loop (if scheduled) or a verify script step (if ad-hoc).
6. Add an entry to `MODULE_INDEX.md`.
7. Add a CLI line to `RUNBOOK.md`.
8. Refresh `PROJECT_STATUS.md` if the change shifts the desk's verdict.

This sequence keeps the docs, tests, and code in sync.

## How to change an existing module

1. Read its docstring. If the docstring is wrong, fix it first.
2. Run `python3 -m unittest tests.test_<module>` and capture the baseline.
3. Snapshot via `scripts/inferno_backup.sh`.
4. Make the change.
5. Re-run tests. They should still pass, or the test should be updated explicitly (with a comment explaining why).
6. Run the full `verify_inferno_tightening.sh` if the change is non-local.

## How to debug a verify failure

1. Look at which specific step failed (`✗ <step name> (continuing)`).
2. Read that step's report file in `reports/`.
3. If it's a chained step, run the underlying CLI directly to see the full error.
4. The new chain diagnostics (`inferno_tos_export_chain.py`, `inferno_night_prep.py`) attribute failures to specific links — read those first when applicable.

## Tone for module docstrings

Speak like a senior engineer writing a runbook for a thoughtful junior:

- Be concrete: "the cube indexes by setup × regime × sector × IV bucket × DTE bucket"
- Be honest about limits: "small sample size; treat all claims as exploratory until N >= 30"
- Repeat the contract: "read-only; never invokes the export shortcut"
- Explain the *why* once, then trust the reader

Avoid breathless hype. Avoid jargon without definition. Avoid passive voice that hides who's responsible. The goal is the next reader (model or human) understanding the module in 60 seconds.

## What we never do

- Place a trade.
- Open a new thinkorswim instance.
- Edit the authority manifest from outside `inferno_authority_controller.py`.
- Use raw `Path.write_text` for desk artifacts.
- Catch broad `Exception` without re-raising or logging.
- Ship a module without a test.
- Ship a doc-less PR.

This list is the floor, not the ceiling. When in doubt, do less.
