from __future__ import annotations

"""Ticker-universe integrity audit for the Inferno desk.

This is the guardrail for the exact moment a new ticker gets added to the
Google tracker. Instead of hoping BC/P/Q/R, score formulas, and bias columns
all hydrate cleanly, we read the live sheet and produce one honest artifact
that tells us whether the universe is ready, merely advisory, or broken.
"""

import argparse
import json
from pathlib import Path

from inferno_config import DEFAULT_SHEET_NAME, default_backtest_root
from morning_inferno_pipeline import (
    TICKER_UNIVERSE_AUDIT_FILE,
    build_ticker_universe_audit_from_sheet,
)


def parse_args() -> argparse.Namespace:
    """Parse the small CLI surface for build/status usage."""
    parser = argparse.ArgumentParser(description="Audit tracker hydration for newly added tickers.")
    parser.add_argument("command", nargs="?", choices=("build", "status"), default="build")
    parser.add_argument("--backtest-root", default=str(default_backtest_root()))
    parser.add_argument("--sheet-name", default=DEFAULT_SHEET_NAME)
    return parser.parse_args()


def print_status(audit: dict) -> None:
    """Render the most useful audit summary directly in the terminal."""
    counts = audit.get("counts") or {}
    print(f"Verdict: {audit.get('verdict')}")
    print(f"Rows: {audit.get('sheetRows', 0)} sheet / {audit.get('snapshotRows', 0)} snapshot")
    print(f"Critical issues: {counts.get('criticalIssueCount', 0)}")
    print(f"Advisory issues: {counts.get('advisoryIssueCount', 0)}")
    hydration = audit.get("hydrationNeededTickers") or []
    if hydration:
        print(f"Hydration needed: {', '.join(hydration)}")
    advisory = audit.get("advisoryTickers") or []
    if advisory:
        print(f"Advisory review: {', '.join(advisory)}")


def main() -> int:
    """Build or display the ticker-universe audit."""
    args = parse_args()
    if args.command == "status":
        if not TICKER_UNIVERSE_AUDIT_FILE.exists():
            print("Ticker universe audit missing. Run build first.")
            return 1
        audit = json.loads(TICKER_UNIVERSE_AUDIT_FILE.read_text(encoding="utf-8"))
        print_status(audit)
        return 0 if audit.get("ok") else 1

    backtest_root = Path(args.backtest_root).expanduser().resolve()
    audit = build_ticker_universe_audit_from_sheet(backtest_root, args.sheet_name)
    print_status(audit)
    return 0 if audit.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
