from __future__ import annotations

"""Bounded, read-only supplemental Schwab option coverage for strategy research.

The primary Schwab options tape follows the desk's normal priority universe.
This lane only fills a small, explicitly recorded subset of missing chains that
the research-only strategy-pricing pass has already requested.  It never
changes the primary tape, execution queues, paper tickets, or trading
authority.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_schwab_daily_ops import load_schwab_env
from inferno_schwab_options import SCHWAB_OPTIONS_FILE, build_report
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


STRATEGY_QUOTE_COVERAGE_FILE = DATA_DIR / "inferno_strategy_quote_coverage.json"
STRATEGY_QUOTE_COVERAGE_TEXT_FILE = REPORTS_DIR / "strategy_quote_coverage_latest.txt"
STRATEGY_QUOTE_COVERAGE_STAGE = "strategy-quote-coverage-research-only"
DEFAULT_LIMIT = 6
SUPPLEMENTAL_CHAIN_SOURCE = "schwab-options-supplemental"


def text(value: Any) -> str:
    """Normalize artifact strings without trusting display fields."""
    return str(value or "").strip()


def norm(value: Any) -> str:
    """Normalize tickers for set membership and report lookup."""
    return text(value).upper()


def report_index(report: dict[str, Any] | None, *, chain_source: str | None = None) -> dict[str, dict[str, Any]]:
    """Index normalized option rows while retaining report-level provenance."""
    if not isinstance(report, dict):
        return {}
    rows = report.get("rows") or []
    if not isinstance(rows, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = norm(row.get("symbol"))
        if not symbol:
            continue
        indexed[symbol] = {
            **row,
            "sourceGeneratedAt": report.get("generatedAt"),
            "sourceStatus": report.get("status"),
            "researchOnly": report.get("researchOnly", True),
            **({"chainSource": chain_source} if chain_source else {}),
        }
    return indexed


def has_usable_contracts(row: dict[str, Any] | None) -> bool:
    """Return whether a normalized chain has contracts suitable for pricing."""
    return bool(isinstance(row, dict) and isinstance(row.get("contracts"), list) and row.get("contracts"))


def candidate_tickers(
    scorer: dict[str, Any] | None,
    paper_variant_scanner: dict[str, Any] | None,
    *,
    limit: int,
    variants_per_ticker: int,
) -> tuple[list[str], int]:
    """Return the pricing slate's ticker order without adding any new universe.

    The import is intentionally local: strategy pricing consumes this module's
    saved tape, while this refresh asks the pricing module only for its existing
    candidate selection policy.
    """
    from inferno_strategy_alternative_pricing import source_candidates

    rows = source_candidates(
        scorer or {},
        limit=limit,
        variants_per_ticker=variants_per_ticker,
        paper_variant_scanner=paper_variant_scanner,
    )
    tickers: list[str] = []
    seen: set[str] = set()
    for row in rows:
        ticker = norm(row.get("ticker"))
        if ticker and ticker not in seen:
            seen.add(ticker)
            tickers.append(ticker)
    return tickers, len(rows)


def build_strategy_quote_coverage(
    *,
    scorer: dict[str, Any] | None = None,
    paper_variant_scanner: dict[str, Any] | None = None,
    primary_report: dict[str, Any] | None = None,
    limit: int = DEFAULT_LIMIT,
    variants_per_ticker: int = 3,
    supplemental_limit: int = DEFAULT_LIMIT,
    report_builder: Callable[[list[str]], dict[str, Any]] = build_report,
    environment_loader: Callable[[], dict[str, str]] = load_schwab_env,
) -> dict[str, Any]:
    """Fetch only missing option chains required by the existing pricing slate."""
    ensure_dirs()
    if scorer is None or paper_variant_scanner is None:
        from inferno_strategy_alternative_pricing import (
            PAPER_VARIANT_SCANNER_FILE,
            STRATEGY_ALTERNATIVE_SCORER_FILE,
        )

        scorer = scorer if scorer is not None else (load_json_file(STRATEGY_ALTERNATIVE_SCORER_FILE) or {})
        paper_variant_scanner = (
            paper_variant_scanner
            if paper_variant_scanner is not None
            else (load_json_file(PAPER_VARIANT_SCANNER_FILE) or {})
        )
    primary_report = primary_report if primary_report is not None else (load_json_file(SCHWAB_OPTIONS_FILE) or {})
    primary_index = report_index(primary_report)
    tickers, candidate_count = candidate_tickers(
        scorer,
        paper_variant_scanner,
        limit=max(0, limit),
        variants_per_ticker=max(1, variants_per_ticker),
    )
    missing_tickers = [ticker for ticker in tickers if not has_usable_contracts(primary_index.get(ticker))]
    requested_limit = max(0, supplemental_limit)
    targets = missing_tickers[:requested_limit]
    # Match the primary daily adapter: `.env.schwab` is local process setup,
    # not a changed setting.  It also mirrors its read-only constants into the
    # already imported option adapter before any network call.
    if targets:
        environment_loader()
    supplemental = report_builder(targets) if targets else {
        "generatedAt": local_now().isoformat(),
        "stage": "schwab-options-read-only",
        "status": "no-gap",
        "configured": bool(primary_report.get("configured")) if isinstance(primary_report, dict) else False,
        "symbolCount": 0,
        "rows": [],
        "errors": [],
        "researchOnly": True,
        "authorityChanged": False,
    }
    supplemental = supplemental if isinstance(supplemental, dict) else {}
    generated_at = local_now().isoformat()
    return {
        "generatedAt": generated_at,
        "stage": STRATEGY_QUOTE_COVERAGE_STAGE,
        "status": supplemental.get("status") or ("no-gap" if not targets else "error"),
        "researchOnly": True,
        "diagnosticOnly": True,
        "promotable": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "authorityChanged": False,
        "chainSource": SUPPLEMENTAL_CHAIN_SOURCE,
        "sourceLineage": {
            "primaryOptionsGeneratedAt": primary_report.get("generatedAt") if isinstance(primary_report, dict) else None,
            "primaryOptionsStatus": primary_report.get("status") if isinstance(primary_report, dict) else None,
            "candidatePolicy": "strategy-alternative-pricing/source-candidates",
            "supplementalStage": supplemental.get("stage"),
            "supplementalGeneratedAt": supplemental.get("generatedAt"),
        },
        "counts": {
            "pricingCandidateRows": candidate_count,
            "pricingCandidateTickers": len(tickers),
            "primaryCoveredTickers": sum(1 for ticker in tickers if has_usable_contracts(primary_index.get(ticker))),
            "missingTickerGroups": len(missing_tickers),
            "requestedSupplementalLimit": requested_limit,
            "requestedSupplementalTickers": len(targets),
            "capturedSupplementalTickers": len(supplemental.get("rows") or []),
            "supplementalErrors": len(supplemental.get("errors") or []),
        },
        "candidateTickers": tickers,
        "targets": targets,
        "rows": supplemental.get("rows") or [],
        "errors": supplemental.get("errors") or [],
        "reminders": [
            "read-only market-data lane; no account or order endpoints",
            "the primary options tape is not overwritten by supplemental coverage",
            "supplemental chains support research pricing only and do not grant paper or live authority",
        ],
    }


def load_supplemental_schwab_options_index(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load only authority-safe supplemental chains for pricing enrichment."""
    source = path or STRATEGY_QUOTE_COVERAGE_FILE
    if not source.exists():
        return {}
    try:
        report = json.loads(source.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if (
        not isinstance(report, dict)
        or report.get("stage") != STRATEGY_QUOTE_COVERAGE_STAGE
        or report.get("researchOnly") is not True
        or report.get("promotable") is not False
        or report.get("authorityChanged") is not False
        or report.get("brokerSubmitAllowed") is not False
        or report.get("liveTradingAllowed") is not False
    ):
        return {}
    return report_index(report, chain_source=SUPPLEMENTAL_CHAIN_SOURCE)


def strategy_quote_coverage_text(payload: dict[str, Any]) -> str:
    """Render an auditable compact coverage memo."""
    counts = payload.get("counts") or {}
    lines = [
        "Inferno Strategy Quote Coverage",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Stage: {payload.get('stage')}",
        f"Status: {payload.get('status')}",
        "Authority: research-only; promotable=False; liveTradingAllowed=False",
        "",
        "Coverage:",
        f"- pricing candidate rows/tickers: {counts.get('pricingCandidateRows', 0)} / {counts.get('pricingCandidateTickers', 0)}",
        f"- primary tape covered: {counts.get('primaryCoveredTickers', 0)}",
        f"- missing ticker groups: {counts.get('missingTickerGroups', 0)}",
        f"- requested supplemental: {counts.get('requestedSupplementalTickers', 0)} of {counts.get('requestedSupplementalLimit', 0)} cap",
        f"- captured/errors: {counts.get('capturedSupplementalTickers', 0)} / {counts.get('supplementalErrors', 0)}",
        f"- targets: {', '.join(payload.get('targets') or []) or 'none'}",
    ]
    if payload.get("errors"):
        lines.extend(["", "Errors:"])
        lines.extend(f"- {item.get('symbol')}: {item.get('error')}" for item in payload["errors"])
    lines.extend(["", "Reminders:"])
    lines.extend(f"- {item}" for item in payload.get("reminders") or [])
    return "\n".join(lines) + "\n"


def save_strategy_quote_coverage(payload: dict[str, Any]) -> None:
    """Persist supplemental coverage separately from the core options tape."""
    ensure_dirs()
    atomic_write_json(STRATEGY_QUOTE_COVERAGE_FILE, payload)
    atomic_write_text(STRATEGY_QUOTE_COVERAGE_TEXT_FILE, strategy_quote_coverage_text(payload))


def parse_args() -> argparse.Namespace:
    """Parse the bounded coverage command line."""
    parser = argparse.ArgumentParser(description="Refresh bounded supplemental Schwab quote coverage.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status"])
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Core pricing ticker-group limit.")
    parser.add_argument("--variants-per-ticker", type=int, default=3, help="Core pricing variant limit.")
    parser.add_argument(
        "--supplemental-limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Maximum missing ticker groups to fetch; the primary tape remains unchanged.",
    )
    return parser.parse_args()


def main() -> int:
    """Run or display the research-only supplemental quote-coverage lane."""
    args = parse_args()
    if args.command == "status" and STRATEGY_QUOTE_COVERAGE_TEXT_FILE.exists():
        print(STRATEGY_QUOTE_COVERAGE_TEXT_FILE.read_text(encoding="utf-8"), end="")
        return 0
    payload = build_strategy_quote_coverage(
        limit=args.limit,
        variants_per_ticker=args.variants_per_ticker,
        supplemental_limit=args.supplemental_limit,
    )
    save_strategy_quote_coverage(payload)
    print(strategy_quote_coverage_text(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
