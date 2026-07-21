from __future__ import annotations

"""Reference-backed taxonomy coverage for the full Inferno tracker.

This is a research-data stewardship module.  It joins existing cached company
reference data to every operator-maintained tracker symbol, then derives a
conservative economic-exposure label from sector and industry.  It deliberately
does not infer portfolio roles, position weights, eligibility, or purchases.

Unknown reference data remains unknown.  That is preferable to presenting a
complete-looking diversification model based on an invented classification.
"""

import argparse
from datetime import datetime, timedelta
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


SNAPSHOT_FILE = DATA_DIR / "latest_snapshot.json"
EDGE_METADATA_CACHE_FILE = DATA_DIR / "inferno_edge_metadata_cache.json"
TICKER_METADATA_CACHE_FILE = DATA_DIR / "inferno_ticker_metadata_cache.json"
TAXONOMY_CACHE_FILE = DATA_DIR / "inferno_tracker_taxonomy_cache.json"
TRACKER_TAXONOMY_FILE = DATA_DIR / "inferno_tracker_taxonomy.json"
TRACKER_TAXONOMY_TEXT_FILE = REPORTS_DIR / "tracker_taxonomy_latest.txt"

TRACKER_TAXONOMY_STAGE = "full-tracker-taxonomy-research-only"
METADATA_CACHE_DAYS = 14
MAX_REFERENCE_REFRESH_PER_RUN = 20
REFERENCE_FAILURE_BACKOFF_HOURS = (1, 6, 24)

# A delisted or acquired symbol may no longer resolve through a live quote API
# even though its company classification remains verifiable.  These exceptions
# are deliberately small, source-labelled, and review-dated—not inferred from
# portfolio data or a theme score.  They only repair reference stewardship.
VERIFIED_REFERENCE_OVERRIDES: dict[str, dict[str, Any]] = {
    "GLDD": {
        "ticker": "GLDD",
        "shortName": "Great Lakes Dredge & Dock Corporation",
        "sector": "Industrials",
        "industry": "Engineering & Construction",
        "quoteType": "Former public operating company",
        "fetchedAt": "2026-07-21T01:42:00-06:00",
        "reviewAfter": "2027-07-21T01:42:00-06:00",
        "source": "verified-reference-override",
        "referenceEvidence": [
            {
                "publisher": "Yahoo Finance",
                "url": "https://uk.finance.yahoo.com/quote/GLDD/",
                "claim": "Company profile labels GLDD as Industrials / Engineering & Construction.",
                "accessedAt": "2026-07-21",
            },
            {
                "publisher": "Great Lakes Dredge & Dock",
                "url": "https://gldd.com/about-us",
                "claim": "Company describes GLDD as the largest U.S. provider of dredging services with a specialized dredging fleet.",
                "accessedAt": "2026-07-21",
            },
            {
                "publisher": "U.S. Securities and Exchange Commission",
                "url": "https://www.sec.gov/Archives/edgar/data/1372020/000119312526097043/gldd-20251231.htm",
                "claim": "2025 Form 10-K/A verifies the Great Lakes Dredge & Dock Corporation registrant identity.",
                "accessedAt": "2026-07-21",
            },
            {
                "publisher": "Great Lakes Dredge & Dock Investor Relations",
                "url": "https://investor.gldd.com/news-releases/news-release-details/saltchuk-welcomes-great-lakes-dredge-dock-its-family-companies",
                "claim": "April 1, 2026 release confirms Saltchuk completed the acquisition and GLDD continues as a stand-alone business unit.",
                "accessedAt": "2026-07-21",
            },
        ],
    },
}


def ticker(value: Any) -> str:
    """Normalize a symbol without changing its tracker membership."""
    return str(value or "").strip().upper()


def text(value: Any, default: str = "") -> str:
    """Normalize display text without replacing a real unknown with a guess."""
    rendered = str(value or "").strip()
    return rendered or default


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO timestamp safely for cache freshness decisions."""
    raw = text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def cache_entry_fresh(entry: dict[str, Any], *, now: datetime | None = None) -> bool:
    """Return whether a reference entry is still within the bounded refresh window."""
    fetched = parse_timestamp(entry.get("fetchedAt"))
    if fetched is None:
        return False
    current = now or local_now()
    # Versioned, manually verified references are reviewed on their explicit
    # date.  This avoids repeatedly replacing a valid historical company
    # classification with a live-provider miss after a delisting.
    review_after = parse_timestamp(entry.get("reviewAfter"))
    if review_after is not None and entry.get("source") == "verified-reference-override":
        return current <= review_after.astimezone(current.tzinfo)
    return current - fetched.astimezone(current.tzinfo) <= timedelta(days=METADATA_CACHE_DAYS)


def retry_due(entry: dict[str, Any] | None, *, now: datetime) -> bool:
    """Avoid repeatedly spending a bounded refresh on the same failed reference call."""
    if not isinstance(entry, dict):
        return True
    retry_at = parse_timestamp(entry.get("nextRetryAt"))
    return retry_at is None or now >= retry_at.astimezone(now.tzinfo)


def with_failure_backoff(entry: dict[str, Any], previous: dict[str, Any] | None, *, now: datetime) -> dict[str, Any]:
    """Record a finite retry delay for a failed lookup without hiding the missing symbol."""
    failure_count = max(0, int((previous or {}).get("failureCount") or 0)) + 1
    backoff_hours = REFERENCE_FAILURE_BACKOFF_HOURS[min(failure_count - 1, len(REFERENCE_FAILURE_BACKOFF_HOURS) - 1)]
    entry["failureCount"] = failure_count
    entry["nextRetryAt"] = (now + timedelta(hours=backoff_hours)).isoformat()
    entry["error"] = text(entry.get("error"), "reference response did not include both sector and industry")
    return entry


def complete_reference(entry: dict[str, Any] | None) -> bool:
    """Require both sector and industry before calling reference data covered."""
    if not isinstance(entry, dict):
        return False
    sector = text(entry.get("sector"), "Unknown")
    industry = text(entry.get("industry"), "Unknown")
    return sector.lower() != "unknown" and industry.lower() != "unknown"


def snapshot_symbols(snapshot: dict[str, Any]) -> list[str]:
    """Return the deduplicated tracker universe in deterministic order."""
    rows = snapshot.get("rows") if isinstance(snapshot, dict) else []
    return sorted({ticker(row.get("ticker")) for row in rows or [] if isinstance(row, dict) and ticker(row.get("ticker"))})


def cache_tickers(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalize a cache payload into a symbol-indexed metadata map."""
    rows = payload.get("tickers") if isinstance(payload, dict) else {}
    if not isinstance(rows, dict):
        return {}
    return {ticker(symbol): value for symbol, value in rows.items() if ticker(symbol) and isinstance(value, dict)}


def source_metadata(
    symbol: str,
    *,
    verified_reference_overrides: dict[str, dict[str, Any]],
    taxonomy_cache: dict[str, dict[str, Any]],
    edge_cache: dict[str, dict[str, Any]],
    ticker_cache: dict[str, dict[str, Any]],
    now: datetime,
) -> tuple[dict[str, Any] | None, str, bool]:
    """Select the strongest local reference record and label its provenance."""
    candidates = (
        (verified_reference_overrides.get(symbol), "verified-reference-override"),
        (taxonomy_cache.get(symbol), "taxonomy-cache"),
        (edge_cache.get(symbol), "edge-metadata-cache"),
        (ticker_cache.get(symbol), "ticker-metadata-cache"),
    )
    for entry, source in candidates:
        if complete_reference(entry) and cache_entry_fresh(entry, now=now):
            return entry, source, True
    for entry, source in candidates:
        if complete_reference(entry):
            return entry, source, False
    for entry, source in candidates:
        if isinstance(entry, dict):
            return entry, source, cache_entry_fresh(entry, now=now)
    return None, "missing", False


def fetch_reference_metadata(symbol: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Fetch bounded company reference fields; failures remain explicit and safe."""
    current = now or local_now()
    metadata = {
        "ticker": symbol,
        "shortName": symbol,
        "sector": "Unknown",
        "industry": "Unknown",
        "quoteType": "Unknown",
        "fetchedAt": current.isoformat(),
        "source": "fallback",
    }
    try:
        import yfinance as yf  # Lazy: taxonomy inspection remains testable offline.

        info = yf.Ticker(symbol).get_info()
        metadata.update(
            {
                "shortName": text(info.get("shortName"), symbol),
                "sector": text(info.get("sector"), "Unknown"),
                "industry": text(info.get("industry"), "Unknown"),
                "quoteType": text(info.get("quoteType"), "Unknown"),
                "source": "yfinance",
            }
        )
    except Exception as exc:  # noqa: BLE001 - a single reference miss must not halt the tracker.
        metadata["error"] = f"{type(exc).__name__}: {exc}"
    return metadata


def economic_exposure(sector: str, industry: str) -> str:
    """Map standard reference fields to a broad, non-investment economic exposure."""
    combined = f"{sector} {industry}".lower()
    industry_rules = (
        ("semiconductor", "semiconductors and equipment"),
        ("software", "enterprise software and data infrastructure"),
        ("information technology services", "IT services and digital transformation"),
        ("communication equipment", "networking and communications hardware"),
        ("computer hardware", "compute, storage, and systems hardware"),
        ("electronic components", "electronic components and connectivity"),
        ("scientific & technical instruments", "measurement, test, and technical equipment"),
        ("electrical equipment", "electrification equipment and grid infrastructure"),
        ("engineering & construction", "infrastructure construction and services"),
        ("aerospace & defense", "aerospace and defense"),
        ("utilities -", "electric power and utilities"),
        ("solar", "renewable power equipment and generation"),
        ("reit", "real-estate infrastructure"),
        ("capital markets", "digital-asset and capital-markets exposure"),
        ("copper", "industrial materials and copper"),
        ("uranium", "nuclear fuel and uranium"),
        ("medical", "healthcare products and services"),
        ("internet content", "internet platforms and advertising"),
        ("internet retail", "internet commerce"),
        ("home improvement", "consumer home-improvement retail"),
        ("auto", "consumer automotive"),
    )
    for needle, label in industry_rules:
        if needle in combined:
            return label
    sector_rules = {
        "Technology": "technology and digital infrastructure",
        "Industrials": "industrials and infrastructure",
        "Utilities": "electric power and utilities",
        "Real Estate": "real-estate infrastructure",
        "Financial Services": "financial services",
        "Basic Materials": "materials and natural resources",
        "Healthcare": "healthcare",
        "Consumer Cyclical": "consumer cyclicals",
        "Communication Services": "communications and internet platforms",
        "Energy": "energy",
    }
    return sector_rules.get(sector, "Unclassified")


def taxonomy_entry(symbol: str, metadata: dict[str, Any] | None, *, source: str, fresh: bool) -> dict[str, Any]:
    """Build one source-transparent taxonomy record without portfolio instructions."""
    metadata = metadata or {}
    sector = text(metadata.get("sector"), "Unknown")
    industry = text(metadata.get("industry"), "Unknown")
    covered = sector != "Unknown" and industry != "Unknown"
    return {
        "ticker": symbol,
        "companyName": text(metadata.get("shortName"), symbol),
        "sector": sector,
        "industry": industry,
        "economicExposure": economic_exposure(sector, industry) if covered else "Unclassified",
        "referenceStatus": "reference-covered" if covered else "reference-missing",
        "referenceSource": f"{source}/{text(metadata.get('source'), 'unknown')}",
        "referenceFresh": fresh,
        "referenceAsOf": metadata.get("fetchedAt"),
        "referenceReviewAfter": metadata.get("reviewAfter"),
        "referenceEvidence": list(metadata.get("referenceEvidence") or []),
        "portfolioRole": "not-defined-by-reference-data",
        "portfolioRoleStatus": "requires-operator-policy",
    }


def build_tracker_taxonomy(
    *,
    snapshot: dict[str, Any] | None = None,
    taxonomy_cache_payload: dict[str, Any] | None = None,
    edge_cache_payload: dict[str, Any] | None = None,
    ticker_cache_payload: dict[str, Any] | None = None,
    verified_reference_overrides: dict[str, dict[str, Any]] | None = None,
    refresh_missing: bool = True,
    max_refresh: int = MAX_REFERENCE_REFRESH_PER_RUN,
    now: datetime | None = None,
    fetcher: Any = fetch_reference_metadata,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build taxonomy coverage and return an updated owned reference cache."""
    current = now or local_now()
    snapshot = snapshot if snapshot is not None else (load_json_file(SNAPSHOT_FILE) or {})
    taxonomy_cache_payload = taxonomy_cache_payload if taxonomy_cache_payload is not None else (load_json_file(TAXONOMY_CACHE_FILE) or {"tickers": {}})
    edge_cache_payload = edge_cache_payload if edge_cache_payload is not None else (load_json_file(EDGE_METADATA_CACHE_FILE) or {"tickers": {}})
    ticker_cache_payload = ticker_cache_payload if ticker_cache_payload is not None else (load_json_file(TICKER_METADATA_CACHE_FILE) or {"tickers": {}})

    taxonomy_cache = cache_tickers(taxonomy_cache_payload)
    edge_cache = cache_tickers(edge_cache_payload)
    ticker_cache = cache_tickers(ticker_cache_payload)
    verified_reference_overrides = verified_reference_overrides if verified_reference_overrides is not None else VERIFIED_REFERENCE_OVERRIDES
    refreshed_symbols: list[str] = []
    refresh_failures: list[str] = []
    deferred_symbols: list[str] = []
    entries: list[dict[str, Any]] = []

    for symbol in snapshot_symbols(snapshot):
        metadata, source, fresh = source_metadata(
            symbol,
            verified_reference_overrides=verified_reference_overrides,
            taxonomy_cache=taxonomy_cache,
            edge_cache=edge_cache,
            ticker_cache=ticker_cache,
            now=current,
        )
        needs_refresh = not complete_reference(metadata) or not fresh
        if refresh_missing and needs_refresh and not retry_due(taxonomy_cache.get(symbol), now=current):
            deferred_symbols.append(symbol)
        elif refresh_missing and needs_refresh and len(refreshed_symbols) < max(0, max_refresh):
            fetched = fetcher(symbol, now=current)
            if not complete_reference(fetched):
                fetched = with_failure_backoff(fetched, taxonomy_cache.get(symbol), now=current)
            taxonomy_cache[symbol] = fetched
            metadata, source, fresh = fetched, "taxonomy-cache", True
            refreshed_symbols.append(symbol)
            if not complete_reference(fetched):
                refresh_failures.append(symbol)
        entries.append(taxonomy_entry(symbol, metadata, source=source, fresh=fresh))

    entries.sort(key=lambda item: item["ticker"])
    covered = [item for item in entries if item["referenceStatus"] == "reference-covered"]
    missing = [item["ticker"] for item in entries if item["referenceStatus"] != "reference-covered"]
    stale = [item["ticker"] for item in covered if not item["referenceFresh"]]
    verified = [item["ticker"] for item in entries if item["referenceSource"].startswith("verified-reference-override/")]
    by_sector: dict[str, int] = {}
    by_exposure: dict[str, int] = {}
    for entry in covered:
        by_sector[entry["sector"]] = by_sector.get(entry["sector"], 0) + 1
        by_exposure[entry["economicExposure"]] = by_exposure.get(entry["economicExposure"], 0) + 1
    reference_complete = len(covered) == len(entries) and bool(entries)
    report = {
        "generatedAt": current.isoformat(),
        "stage": TRACKER_TAXONOMY_STAGE,
        "verdict": "reference-coverage-complete" if reference_complete else "reference-coverage-incomplete",
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "brokerSubmitAllowed": False,
        "liveTradingAllowed": False,
        "purpose": "Reference-backed sector, industry, and economic-exposure coverage for the full tracker.",
        "authorityBoundary": {
            "trackerMembershipChanged": False,
            "eligibilityChanged": False,
            "riskConstantsChanged": False,
            "portfolioRolesProduced": False,
            "targetWeightsProduced": False,
            "brokerActionProduced": False,
        },
        "coverage": {
            "trackedRows": len(entries),
            "referenceCoveredRows": len(covered),
            "referenceMissingRows": len(missing),
            "referenceComplete": reference_complete,
            "staleReferenceRows": len(stale),
            "verifiedReferenceRows": len(verified),
            "verifiedReferenceSymbols": verified,
            "missingSymbols": missing,
            "staleSymbols": stale,
            "bySector": dict(sorted(by_sector.items())),
            "byEconomicExposure": dict(sorted(by_exposure.items())),
            "portfolioRolePolicyCoverage": 0,
        },
        "refresh": {
            "enabled": refresh_missing,
            "maxPerRun": max_refresh,
            "refreshedSymbols": refreshed_symbols,
            "refreshFailures": refresh_failures,
            "deferredSymbols": deferred_symbols,
        },
        "nextBuildGate": {
            "referenceCoverageReady": reference_complete,
            "readyForDcaWeights": False,
            "requirements": [
                "Resolve any missing reference-data symbol without guessing.",
                "Define an operator-approved portfolio-role and diversification policy separately from sector and industry data.",
                "Keep target weights and broker action outside this reference-data layer.",
            ],
        },
        "entries": entries,
        "citations": [
            "data/latest_snapshot.json",
            "data/inferno_edge_metadata_cache.json",
            "data/inferno_ticker_metadata_cache.json",
            "data/inferno_tracker_taxonomy_cache.json",
            "Verified GLDD reference evidence: https://uk.finance.yahoo.com/quote/GLDD/",
            "Verified GLDD operating-company profile: https://gldd.com/about-us",
            "Verified GLDD registrant identity: https://www.sec.gov/Archives/edgar/data/1372020/000119312526097043/gldd-20251231.htm",
            "Verified GLDD acquisition status: https://investor.gldd.com/news-releases/news-release-details/saltchuk-welcomes-great-lakes-dredge-dock-its-family-companies",
        ],
    }
    return report, {"tickers": taxonomy_cache}


def tracker_taxonomy_text(report: dict[str, Any]) -> str:
    """Render the reference-data coverage report for review."""
    coverage = report.get("coverage") or {}
    refresh = report.get("refresh") or {}
    lines = [
        "Inferno Full-Tracker Taxonomy (research-only)",
        "",
        f"Generated: {report.get('generatedAt')}",
        f"Verdict: {report.get('verdict')}",
        f"Reference coverage: {coverage.get('referenceCoveredRows', 0)}/{coverage.get('trackedRows', 0)}",
        f"Missing: {coverage.get('referenceMissingRows', 0)} | stale: {coverage.get('staleReferenceRows', 0)}",
        f"Verified static references: {coverage.get('verifiedReferenceRows', 0)}",
        f"Bounded refresh: {len(refresh.get('refreshedSymbols') or [])}/{refresh.get('maxPerRun', 0)} symbol(s)",
        f"Deferred retry: {len(refresh.get('deferredSymbols') or [])} symbol(s)",
        "",
        "Sector coverage",
    ]
    for sector, count in (coverage.get("bySector") or {}).items():
        lines.append(f"- {sector}: {count}")
    lines.extend(["", "Economic-exposure coverage"])
    for exposure, count in (coverage.get("byEconomicExposure") or {}).items():
        lines.append(f"- {exposure}: {count}")
    lines.extend(["", "Missing reference symbols"])
    lines.extend(f"- {symbol}" for symbol in coverage.get("missingSymbols") or ["none"])
    lines.extend(["", "Verified source-labelled reference symbols"])
    lines.extend(f"- {symbol}" for symbol in coverage.get("verifiedReferenceSymbols") or ["none"])
    lines.extend(["", "DCA weights gate"])
    for requirement in (report.get("nextBuildGate") or {}).get("requirements") or []:
        lines.append(f"- {requirement}")
    lines.extend(
        [
            "",
            "This reference-data artifact does not define portfolio roles, target weights, eligibility,",
            "or purchases. It never changes broker authority or submits an order.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def save_tracker_taxonomy(report: dict[str, Any], cache: dict[str, Any]) -> None:
    """Persist only this module's outputs and its owned reference cache."""
    ensure_dirs()
    atomic_write_json(TAXONOMY_CACHE_FILE, cache)
    atomic_write_json(TRACKER_TAXONOMY_FILE, report)
    atomic_write_text(TRACKER_TAXONOMY_TEXT_FILE, tracker_taxonomy_text(report))


def parse_args() -> argparse.Namespace:
    """Expose run/status and bounded reference-refresh controls."""
    parser = argparse.ArgumentParser(description="Build reference-backed taxonomy coverage for the full tracker.")
    parser.add_argument("action", nargs="?", choices=("run", "status"), default="run")
    parser.add_argument("--no-refresh-missing", action="store_true")
    parser.add_argument("--max-refresh", type=int, default=MAX_REFERENCE_REFRESH_PER_RUN)
    return parser.parse_args()


def main() -> int:
    """Run or display the taxonomy artifact."""
    args = parse_args()
    if args.action == "status":
        report = load_json_file(TRACKER_TAXONOMY_FILE) or {}
        if not report:
            report, _ = build_tracker_taxonomy(refresh_missing=False)
    else:
        report, cache = build_tracker_taxonomy(
            refresh_missing=not args.no_refresh_missing,
            max_refresh=args.max_refresh,
        )
        save_tracker_taxonomy(report, cache)
    print(tracker_taxonomy_text(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
