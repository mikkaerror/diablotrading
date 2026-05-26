from __future__ import annotations

"""Registry and value capture for user-authored TOS custom metrics.

The TOS custom-column formulas themselves do not come through Schwab's API and
do not appear in a normal watchlist value export. This module gives those
metrics a first-class lane:

- a registry for the exact ThinkScript source once captured
- a CSV importer for the latest TOS-produced custom-column values
- a read-only artifact other model modules can join by ticker

It never opens TOS, clicks TOS, writes Sheets, stages orders, or touches broker
order endpoints.
"""

import argparse
import csv
import io
import json
import re
from xml.etree import ElementTree
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


TOS_CUSTOM_METRICS_FILE = DATA_DIR / "inferno_tos_custom_metrics.json"
TOS_CUSTOM_METRICS_TEXT_FILE = REPORTS_DIR / "tos_custom_metrics_latest.txt"
TOS_CUSTOM_METRIC_REGISTRY_FILE = DATA_DIR / "tos_custom_metric_registry.json"
TOS_CUSTOM_METRICS_STAGE = "tos-custom-metrics-diagnostic-only"
TOS_CUSTOM_QUOTE_CACHE_PATTERN = "custom_quotes_cache*.xml"

TICKER_HEADERS = ("ticker", "symbol", "underlying", "instrument")
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
NON_SIGNAL_HEADERS = {
    "",
    "ticker",
    "symbol",
    "underlying",
    "instrument",
    "description",
    "last",
    "mark",
    "bid",
    "ask",
    "volume",
    "open",
    "high",
    "low",
    "close",
    "change",
    "%change",
    "netchg",
}

DEFAULT_REGISTRY: list[dict[str, Any]] = [
    {
        "key": "tos_rvol",
        "displayName": "TOS RVOL",
        "aliases": ["RVOL", "$RVOL", "RelVol", "Relative Volume", "TOS RVOL"],
        "modelRole": "participation",
        "formulaStatus": "needs-thinkscript-source",
        "thinkScript": "",
        "notes": "Visible TOS column: RVOL. User-authored participation/relative-volume metric.",
    },
    {
        "key": "tos_pv52h",
        "displayName": "TOS Pv52H",
        "aliases": ["Pv52H", "PV52H", "P v52H", "Pct52H", "%52H", "Percent 52H", "Percent Vs 52H"],
        "modelRole": "52-week-high-proximity",
        "formulaStatus": "needs-thinkscript-source",
        "thinkScript": "",
        "notes": "Visible TOS column: Pv52H. Appears to encode proximity to the 52-week high; exact ThinkScript still needed.",
    },
    {
        "key": "tos_momentum",
        "displayName": "TOS Momentum",
        "aliases": ["Momentum", "MOM", "Momo", "TOS Momentum", "MOM%"],
        "modelRole": "directional-momentum",
        "formulaStatus": "needs-thinkscript-source",
        "thinkScript": "",
        "notes": "Visible TOS column: MOM. Keep separate from tracker IV-rank Momentum Score.",
    },
    {
        "key": "tos_atr_percent",
        "displayName": "TOS ATR%",
        "aliases": ["ATR%", "ATR Pct", "ATR Percent", "ATR_Pct", "TOS ATR%"],
        "modelRole": "realized-range-percent",
        "formulaStatus": "needs-thinkscript-source",
        "thinkScript": "",
        "notes": "Visible TOS column: ATR%. User-authored or TOS-derived realized range percent.",
    },
    {
        "key": "tos_strength",
        "displayName": "TOS Strength",
        "aliases": ["Strength", "STR", "Str", "Str...", "TOS Strength", "Inferno Strength"],
        "modelRole": "confirmation-strength",
        "formulaStatus": "needs-thinkscript-source",
        "thinkScript": "",
        "notes": "Visible TOS column: Str... User-authored confirmation strength metric.",
    },
    {
        "key": "tos_support_resistance_state",
        "displayName": "TOS SUP/RES",
        "aliases": ["SUP/RES *", "SUP/RES", "SUP RES", "SUP_RES", "SupRes", "Support/Resistance", "Support Resistance"],
        "modelRole": "support-resistance-state",
        "formulaStatus": "needs-thinkscript-source",
        "thinkScript": "",
        "notes": "Visible TOS column: SUP/RES *. Preserves text states like Neutral/Near support/resistance.",
    },
]

VISIBLE_TOS_METRIC_KEYS = (
    "tos_rvol",
    "tos_pv52h",
    "tos_momentum",
    "tos_atr_percent",
    "tos_strength",
    "tos_support_resistance_state",
)


def text(value: Any) -> str:
    """Normalize display text."""
    return str(value or "").strip()


def number(value: Any) -> float | None:
    """Parse loose numeric values while preserving raw strings elsewhere."""
    raw = text(value).replace("$", "").replace(",", "").replace("%", "")
    if not raw or raw.upper() in {"N/A", "NAN", "--", "NONE"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def slug(value: str) -> str:
    """Create a stable metric key from a TOS column header."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", text(value).lower()).strip("_")
    return cleaned or "unnamed_metric"


def normalize_ticker(value: Any) -> str:
    """Normalize a ticker-like value."""
    candidate = text(value).upper().lstrip("$")
    return candidate if TICKER_PATTERN.match(candidate) else ""


def load_registry(path: Path = TOS_CUSTOM_METRIC_REGISTRY_FILE) -> list[dict[str, Any]]:
    """Load the custom metric registry or return the starter registry."""
    if not path.exists():
        return [dict(item) for item in DEFAULT_REGISTRY]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return [dict(item) for item in DEFAULT_REGISTRY]
    raw_metrics = payload.get("metrics") if isinstance(payload, dict) else payload
    if not isinstance(raw_metrics, list):
        return [dict(item) for item in DEFAULT_REGISTRY]
    metrics: list[dict[str, Any]] = []
    for item in raw_metrics:
        if isinstance(item, dict) and text(item.get("key")):
            metrics.append(dict(item))
    return merge_registry_defaults(metrics or [dict(item) for item in DEFAULT_REGISTRY])


def merge_registry_defaults(registry: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve user-edited registry items while adding newly known defaults."""
    by_key = {text(item.get("key")): dict(item) for item in registry if text(item.get("key"))}
    merged: list[dict[str, Any]] = []
    for default in DEFAULT_REGISTRY:
        key = text(default.get("key"))
        if key in by_key:
            item = {**default, **by_key[key]}
            aliases = []
            for alias in [*(default.get("aliases") or []), *(by_key[key].get("aliases") or [])]:
                if alias not in aliases:
                    aliases.append(alias)
            item["aliases"] = aliases
            merged.append(item)
        else:
            merged.append(dict(default))
    extra_keys = {text(item.get("key")) for item in merged}
    for item in registry:
        key = text(item.get("key"))
        if key and key not in extra_keys:
            merged.append(dict(item))
    return merged


def registry_payload(registry: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build a user-editable registry payload."""
    return {
        "generatedAt": local_now().isoformat(),
        "stage": "tos-custom-metric-registry-template",
        "instructions": [
            "Paste exact ThinkScript into the thinkScript field for each metric.",
            "Add aliases exactly as they appear in TOS CSV headers.",
            "Do not put credentials or account identifiers in this file.",
        ],
        "metrics": registry or DEFAULT_REGISTRY,
    }


def alias_lookup(registry: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map normalized aliases to registry entries."""
    lookup: dict[str, dict[str, Any]] = {}
    for metric in registry:
        aliases = [metric.get("displayName"), metric.get("key"), *(metric.get("aliases") or [])]
        for alias in aliases:
            normalized = slug(str(alias or ""))
            if normalized and normalized not in lookup:
                lookup[normalized] = metric
    return lookup


def source_cache_candidates(root: Path | None = None) -> list[Path]:
    """Return likely current TOS custom quote cache files."""
    tos_root = root or (Path.home() / "thinkorswim")
    if not tos_root.exists():
        return []
    candidates = [
        path
        for path in tos_root.glob(TOS_CUSTOM_QUOTE_CACHE_PATTERN)
        if path.is_file()
    ]
    return sorted(candidates, key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)


def discover_tos_custom_quote_sources(paths: list[Path] | None = None) -> list[dict[str, Any]]:
    """Read TOS custom quote formulas from local cache XML files."""
    candidates = paths if paths is not None else source_cache_candidates()
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in candidates:
        if not path.exists():
            continue
        try:
            root = ElementTree.parse(path).getroot()
        except Exception:  # noqa: BLE001
            continue
        for node in root.findall(".//CUSTOM_QUOTES_CACHE/*"):
            name = text(node.attrib.get("NAME"))
            code = text(node.attrib.get("CODE"))
            if not name or not code:
                continue
            key = slug(name)
            if key in seen:
                continue
            seen.add(key)
            sources.append(
                {
                    "sourceName": name,
                    "sourceKey": key,
                    "thinkScript": code,
                    "sourcePath": str(path),
                    "sourceIndex": node.attrib.get("INDEX"),
                    "aggregationPeriod": node.attrib.get("AGG_PERIOD"),
                    "priceType": node.attrib.get("PRICE_TYPE"),
                    "version": node.attrib.get("VERSION"),
                }
            )
    return sources


def registry_with_tos_sources(
    registry: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge locally discovered TOS custom quote formulas into the registry."""
    merged = merge_registry_defaults(registry)
    lookup = alias_lookup(merged)
    by_key = {text(item.get("key")): dict(item) for item in merged if text(item.get("key"))}

    for source in sources:
        source_name = text(source.get("sourceName"))
        matched = lookup.get(slug(source_name))
        key = text(matched.get("key")) if matched else f"tos_{slug(source_name)}"
        item = by_key.get(key, {
            "key": key,
            "displayName": f"TOS {source_name}",
            "aliases": [source_name],
            "modelRole": "unclassified-custom-tos-quote",
            "notes": "Discovered from local TOS custom quote cache; model role needs review.",
        })
        aliases = list(item.get("aliases") or [])
        if source_name and source_name not in aliases:
            aliases.append(source_name)
        item.update(
            {
                "aliases": aliases,
                "formulaStatus": "captured-from-tos-cache",
                "thinkScript": source.get("thinkScript") or "",
                "tosSource": {
                    "sourceName": source_name,
                    "sourcePath": source.get("sourcePath"),
                    "sourceIndex": source.get("sourceIndex"),
                    "aggregationPeriod": source.get("aggregationPeriod"),
                    "priceType": source.get("priceType"),
                    "version": source.get("version"),
                },
            }
        )
        by_key[key] = item

    ordered_keys = [text(item.get("key")) for item in merged if text(item.get("key"))]
    ordered = [by_key[key] for key in ordered_keys if key in by_key]
    for key, item in by_key.items():
        if key not in ordered_keys:
            ordered.append(item)
    return ordered


def ticker_header(headers: list[str]) -> str | None:
    """Pick the ticker column header from a CSV."""
    for header in headers:
        if slug(header) in TICKER_HEADERS:
            return header
    return headers[0] if headers else None


def read_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Read a CSV file into dict rows and headers."""
    raw = path.read_text(encoding="utf-8", errors="ignore")
    sample = raw[:2048]
    dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
    reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
    headers = [header for header in (reader.fieldnames or []) if header is not None]
    return [{key: value for key, value in row.items() if key is not None} for row in reader], headers


def metric_cell(raw_value: Any, *, header: str, registry_entry: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize one metric cell."""
    parsed = number(raw_value)
    return {
        "raw": text(raw_value),
        "value": parsed,
        "sourceColumn": header,
        "registryKey": registry_entry.get("key") if registry_entry else None,
        "displayName": registry_entry.get("displayName") if registry_entry else header,
        "modelRole": registry_entry.get("modelRole") if registry_entry else "unmapped-custom-tos-column",
        "formulaStatus": registry_entry.get("formulaStatus") if registry_entry else "unregistered-column",
        "hasThinkScript": bool(text((registry_entry or {}).get("thinkScript"))),
    }


def values_from_csv(path: Path, registry: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse a TOS value-export CSV into ticker-keyed custom metrics."""
    rows, headers = read_csv_rows(path)
    header = ticker_header(headers)
    lookup = alias_lookup(registry)
    by_ticker: dict[str, dict[str, Any]] = {}
    unmapped_columns: set[str] = set()
    mapped_columns: set[str] = set()

    for row in rows:
        ticker = normalize_ticker(row.get(header)) if header else ""
        if not ticker and headers:
            ticker = normalize_ticker(row.get(headers[0]))
        if not ticker:
            continue
        metrics: dict[str, Any] = {}
        for column in headers:
            column_key = slug(column)
            if column == header or column_key in NON_SIGNAL_HEADERS:
                continue
            raw_value = row.get(column)
            if text(raw_value) == "":
                continue
            registry_entry = lookup.get(column_key)
            metric_key = registry_entry.get("key") if registry_entry else f"tos_{column_key}"
            metrics[metric_key] = metric_cell(raw_value, header=column, registry_entry=registry_entry)
            if registry_entry:
                mapped_columns.add(column)
            else:
                unmapped_columns.add(column)
        if metrics:
            by_ticker[ticker] = metrics

    return {
        "sourceProvider": "tos-csv-export",
        "sourceCsv": str(path),
        "sourceHistoryArtifact": None,
        "csvHeaders": headers,
        "tickerHeader": header,
        "tickerCount": len(by_ticker),
        "metricValueCount": sum(len(metrics) for metrics in by_ticker.values()),
        "mappedColumns": sorted(mapped_columns),
        "unmappedColumns": sorted(unmapped_columns),
        "byTicker": by_ticker,
    }


def raw_from_mirror_cell(metric_key: str, cell: dict[str, Any]) -> str:
    """Render a Schwab-derived TOS mirror cell like a watchlist value."""
    if metric_key == "tos_support_resistance_state":
        return text(cell.get("label"))
    value = cell.get("value")
    if value is None:
        return ""
    suffix = "%" if metric_key == "tos_atr_percent" else ""
    return f"{value}{suffix}"


def value_from_mirror_cell(metric_key: str, cell: dict[str, Any]) -> float | None:
    """Return the numeric model value from a TOS mirror cell."""
    if metric_key == "tos_support_resistance_state":
        return None
    return number(cell.get("value"))


def metric_cell_from_schwab_mirror(
    metric_key: str,
    mirror_cell: dict[str, Any],
    *,
    registry_entry: dict[str, Any] | None,
) -> dict[str, Any]:
    """Normalize a Schwab-derived formula mirror as a custom metric cell."""
    display_name = registry_entry.get("displayName") if registry_entry else metric_key
    return {
        "raw": raw_from_mirror_cell(metric_key, mirror_cell),
        "value": value_from_mirror_cell(metric_key, mirror_cell),
        "sourceColumn": display_name,
        "registryKey": registry_entry.get("key") if registry_entry else metric_key,
        "displayName": display_name,
        "modelRole": registry_entry.get("modelRole") if registry_entry else "schwab-derived-tos-mirror",
        "formulaStatus": "recomputed-from-schwab-price-history",
        "hasThinkScript": bool(text(mirror_cell.get("thinkScript"))),
        "thinkScript": mirror_cell.get("thinkScript") or "",
        "source": "schwab-price-history",
        "color": mirror_cell.get("color"),
    }


def values_from_schwab_history_report(
    report: dict[str, Any],
    registry: list[dict[str, Any]],
) -> dict[str, Any]:
    """Convert Schwab price-history mirrors into ticker-keyed custom metrics."""
    registry_by_key = {text(item.get("key")): item for item in registry if text(item.get("key"))}
    by_ticker: dict[str, dict[str, Any]] = {}
    mapped_columns: set[str] = set()
    missing_symbols: list[str] = []

    for row in report.get("rows") or []:
        if not isinstance(row, dict):
            continue
        ticker = normalize_ticker(row.get("symbol"))
        mirror = row.get("tosCustomFormulaMirror") if isinstance(row.get("tosCustomFormulaMirror"), dict) else {}
        if not ticker or not mirror:
            if ticker:
                missing_symbols.append(ticker)
            continue
        metrics: dict[str, Any] = {}
        for metric_key in VISIBLE_TOS_METRIC_KEYS:
            mirror_cell = mirror.get(metric_key)
            if not isinstance(mirror_cell, dict):
                continue
            raw = raw_from_mirror_cell(metric_key, mirror_cell)
            value = value_from_mirror_cell(metric_key, mirror_cell)
            if raw == "" and value is None:
                continue
            registry_entry = registry_by_key.get(metric_key)
            metrics[metric_key] = metric_cell_from_schwab_mirror(
                metric_key,
                mirror_cell,
                registry_entry=registry_entry,
            )
            mapped_columns.add((registry_entry or {}).get("displayName") or metric_key)
        if metrics:
            by_ticker[ticker] = metrics

    return {
        "sourceProvider": "schwab-price-history",
        "sourceCsv": None,
        "sourceHistoryArtifact": str(report.get("artifact") or "data/inferno_schwab_price_history.json"),
        "historyStatus": report.get("status"),
        "historyGeneratedAt": report.get("generatedAt"),
        "csvHeaders": [],
        "tickerHeader": "symbol",
        "tickerCount": len(by_ticker),
        "metricValueCount": sum(len(metrics) for metrics in by_ticker.values()),
        "mappedColumns": sorted(mapped_columns),
        "unmappedColumns": [],
        "missingSymbols": sorted(set(missing_symbols)),
        "byTicker": by_ticker,
    }


def build_custom_metrics_report(
    *,
    values_csv: Path | None = None,
    schwab_history_report: dict[str, Any] | None = None,
    registry_path: Path = TOS_CUSTOM_METRIC_REGISTRY_FILE,
) -> dict[str, Any]:
    """Build the custom metrics artifact."""
    registry = load_registry(registry_path)
    if values_csv:
        values = values_from_csv(values_csv, registry)
    elif schwab_history_report is not None:
        values = values_from_schwab_history_report(schwab_history_report, registry)
    else:
        values = {
            "sourceProvider": None,
            "sourceCsv": None,
            "sourceHistoryArtifact": None,
            "csvHeaders": [],
            "tickerHeader": None,
            "tickerCount": 0,
            "metricValueCount": 0,
            "mappedColumns": [],
            "unmappedColumns": [],
            "byTicker": {},
        }
    value_formula_keys = {
        metric_key
        for metrics in (values.get("byTicker") or {}).values()
        if isinstance(metrics, dict)
        for metric_key, cell in metrics.items()
        if isinstance(cell, dict) and cell.get("hasThinkScript")
    }
    missing_formula_metrics = [
        metric.get("key")
        for metric in registry
        if text(metric.get("key")) not in value_formula_keys
        and (not text(metric.get("thinkScript")) or text(metric.get("formulaStatus")) == "needs-thinkscript-source")
    ]
    captured_formula_metrics = [
        metric.get("key")
        for metric in registry
        if text(metric.get("thinkScript")) and text(metric.get("formulaStatus")) != "needs-thinkscript-source"
    ]
    if values["metricValueCount"] and not missing_formula_metrics and not values["unmappedColumns"]:
        verdict = "custom-metrics-accounted"
    elif values["metricValueCount"]:
        verdict = "custom-values-captured-needs-formulas"
    else:
        verdict = "needs-tos-custom-export"

    return {
        "generatedAt": local_now().isoformat(),
        "stage": TOS_CUSTOM_METRICS_STAGE,
        "authority": {
            "readOnly": True,
            "touchesTos": False,
            "touchesBroker": False,
            "touchesBrokerMarketData": values.get("sourceProvider") == "schwab-price-history",
            "touchesSheets": False,
            "stagesTrades": False,
        },
        "registryPath": str(registry_path),
        "registryMetricCount": len(registry),
        "missingFormulaMetrics": missing_formula_metrics,
        "capturedFormulaMetrics": captured_formula_metrics,
        "values": values,
        "verdict": verdict,
        "nextActions": custom_metric_actions(values, missing_formula_metrics),
        "registry": registry,
    }


def load_custom_metrics_by_ticker(path: Path = TOS_CUSTOM_METRICS_FILE) -> dict[str, dict[str, Any]]:
    """Load latest captured TOS custom metric values keyed by ticker."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    values = payload.get("values") if isinstance(payload, dict) else {}
    by_ticker = values.get("byTicker") if isinstance(values, dict) else {}
    if not isinstance(by_ticker, dict):
        return {}
    cleaned: dict[str, dict[str, Any]] = {}
    for ticker, metrics in by_ticker.items():
        normalized = normalize_ticker(ticker)
        if normalized and isinstance(metrics, dict):
            cleaned[normalized] = metrics
    return cleaned


def metric_value(metrics: dict[str, Any], key: str) -> float | None:
    """Read a parsed numeric metric value by key."""
    cell = metrics.get(key) if isinstance(metrics, dict) else None
    if isinstance(cell, dict):
        return number(cell.get("value") if cell.get("value") is not None else cell.get("raw"))
    return None


def metric_raw(metrics: dict[str, Any], key: str) -> str | None:
    """Read a raw metric display value by key."""
    cell = metrics.get(key) if isinstance(metrics, dict) else None
    if isinstance(cell, dict):
        raw = text(cell.get("raw"))
        return raw or None
    return None


def rvol_band(value: float | None) -> str:
    """Bucket TOS RVOL values for display, not gating."""
    if value is None:
        return "unknown"
    if value >= 2.0:
        return "surge"
    if value >= 1.4:
        return "active"
    if value >= 1.0:
        return "normal"
    if value >= 0.7:
        return "quiet"
    return "thin"


def strength_band(value: float | None) -> str:
    """Bucket observed TOS strength values for display, not gating."""
    if value is None:
        return "unknown"
    if value >= 80:
        return "strong"
    if value >= 60:
        return "constructive"
    if value >= 40:
        return "neutral"
    return "weak"


def summarize_custom_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
    """Build a conservative feature summary from captured TOS values."""
    metrics = metrics or {}
    rvol = metric_value(metrics, "tos_rvol")
    pv52h = metric_value(metrics, "tos_pv52h")
    momentum = metric_value(metrics, "tos_momentum")
    atr_percent = metric_value(metrics, "tos_atr_percent")
    strength = metric_value(metrics, "tos_strength")
    support_resistance = metric_raw(metrics, "tos_support_resistance_state")
    return {
        "sourceStatus": "captured" if metrics else "missing",
        "observedOnly": True,
        "formulaReproduced": all(
            bool((cell or {}).get("hasThinkScript"))
            for cell in metrics.values()
            if isinstance(cell, dict)
        ) if metrics else False,
        "rvol": rvol,
        "rvolBand": rvol_band(rvol),
        "pv52h": pv52h,
        "near52WeekHigh": bool(pv52h is not None and pv52h >= 90),
        "momentum": momentum,
        "momentumSign": "positive" if momentum is not None and momentum > 0 else "negative" if momentum is not None and momentum < 0 else "flat-or-unknown",
        "atrPercent": atr_percent,
        "strength": strength,
        "strengthBand": strength_band(strength),
        "supportResistanceState": support_resistance,
    }


def custom_metric_actions(values: dict[str, Any], missing_formula_metrics: list[str]) -> list[str]:
    """Return concrete next actions for the operator/model."""
    actions: list[str] = []
    if not values.get("metricValueCount"):
        actions.append("Run ./run_inferno_schwab_tos_metrics_sync.sh --from-snapshot to recompute OHLCV-derived TOS metrics from Schwab history.")
        actions.append("If Schwab history is unavailable, export the TOS watchlist/custom quote columns to CSV and run this module with --values-csv.")
    if values.get("sourceProvider") == "schwab-price-history" and values.get("historyStatus") in {"disabled", "not-configured"}:
        actions.append("Enable Schwab market-data env settings and refresh OAuth before relying on auto-synced metrics.")
    if missing_formula_metrics:
        actions.append("Paste exact ThinkScript source into data/tos_custom_metric_registry.json for the missing metrics.")
    if values.get("unmappedColumns"):
        actions.append("Add aliases/model roles for unmapped TOS columns in the custom metric registry.")
    if not actions:
        actions.append("Join values.byTicker into scoring research and add formula-level regression tests.")
    return actions


def custom_metrics_text(payload: dict[str, Any]) -> str:
    """Render the custom metrics artifact."""
    values = payload.get("values") or {}
    authority_line = (
        "Authority: read-only Schwab market-data diagnostic; no TOS UI, account/order broker endpoints, Sheet, queue, or staging writes."
        if values.get("sourceProvider") == "schwab-price-history"
        else "Authority: read-only diagnostic; no TOS UI, broker, Sheet, queue, or staging writes."
    )
    lines = [
        "# TOS Custom Metrics",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"Registry: {payload.get('registryPath')}",
        f"Registry metrics: {payload.get('registryMetricCount')}",
        f"Source provider: {values.get('sourceProvider') or 'none'}",
        f"Source CSV: {values.get('sourceCsv') or 'none'}",
        f"Source history: {values.get('sourceHistoryArtifact') or 'none'}",
        f"History status: {values.get('historyStatus') or 'n/a'}",
        f"Tickers with values: {values.get('tickerCount', 0)}",
        f"Metric values captured: {values.get('metricValueCount', 0)}",
        "",
        authority_line,
    ]
    if payload.get("missingFormulaMetrics"):
        lines.extend(["", "Formula source still needed:"])
        for key in payload.get("missingFormulaMetrics") or []:
            lines.append(f"- {key}")
    if payload.get("capturedFormulaMetrics"):
        lines.extend(["", "Formula source captured:"])
        for key in payload.get("capturedFormulaMetrics") or []:
            lines.append(f"- {key}")
    if values.get("mappedColumns"):
        lines.extend(["", "Mapped TOS columns:"])
        for column in values.get("mappedColumns") or []:
            lines.append(f"- {column}")
    if values.get("unmappedColumns"):
        lines.extend(["", "Unmapped TOS columns preserved but not interpreted:"])
        for column in values.get("unmappedColumns") or []:
            lines.append(f"- {column}")
    by_ticker = values.get("byTicker") or {}
    if by_ticker:
        lines.extend(["", "Sample captured values:"])
        for ticker, metrics in list(by_ticker.items())[:8]:
            rendered = ", ".join(
                f"{cell.get('displayName')}: {cell.get('raw')}"
                for cell in list(metrics.values())[:5]
                if isinstance(cell, dict)
            )
            lines.append(f"- {ticker}: {rendered}")
    lines.extend(["", "Next actions:"])
    for action in payload.get("nextActions") or []:
        lines.append(f"- {action}")
    return "\n".join(lines).rstrip() + "\n"


def save_custom_metrics(payload: dict[str, Any]) -> None:
    """Persist custom metrics artifacts."""
    ensure_dirs()
    atomic_write_json(TOS_CUSTOM_METRICS_FILE, payload)
    atomic_write_text(TOS_CUSTOM_METRICS_TEXT_FILE, custom_metrics_text(payload))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--values-csv", help="Path to a TOS watchlist/custom quote CSV export")
    parser.add_argument("--schwab-history-json", help="Path to a Schwab price-history report to convert into TOS custom metrics")
    parser.add_argument("--registry", default=str(TOS_CUSTOM_METRIC_REGISTRY_FILE), help="Metric registry JSON path")
    parser.add_argument("--init-registry", action="store_true", help="Write starter registry JSON if it does not exist")
    parser.add_argument("--pull-formulas-from-cache", action="store_true", help="Import ThinkScript formulas from local TOS custom quote cache XML")
    parser.add_argument("--json", action="store_true", help="Print JSON summary instead of text memo")
    args = parser.parse_args(argv)

    registry_path = Path(args.registry)
    if args.init_registry or args.pull_formulas_from_cache:
        ensure_dirs()
        registry = load_registry(registry_path)
        if args.pull_formulas_from_cache:
            registry = registry_with_tos_sources(registry, discover_tos_custom_quote_sources())
        atomic_write_json(registry_path, registry_payload(registry))

    schwab_history_report = None
    if args.schwab_history_json:
        try:
            schwab_history_report = json.loads(Path(args.schwab_history_json).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"Unable to load --schwab-history-json: {type(exc).__name__}: {exc}") from exc

    payload = build_custom_metrics_report(
        values_csv=Path(args.values_csv) if args.values_csv else None,
        schwab_history_report=schwab_history_report,
        registry_path=registry_path,
    )
    save_custom_metrics(payload)
    if args.json:
        print(
            json.dumps(
                {
                    "verdict": payload.get("verdict"),
                    "metricValueCount": (payload.get("values") or {}).get("metricValueCount"),
                    "tickerCount": (payload.get("values") or {}).get("tickerCount"),
                    "sourceProvider": (payload.get("values") or {}).get("sourceProvider"),
                    "missingFormulaMetrics": payload.get("missingFormulaMetrics"),
                    "capturedFormulaMetrics": payload.get("capturedFormulaMetrics"),
                    "artifact": str(TOS_CUSTOM_METRICS_FILE),
                    "report": str(TOS_CUSTOM_METRICS_TEXT_FILE),
                },
                indent=2,
            )
        )
    else:
        print(custom_metrics_text(payload), end="")
    return 0 if payload.get("verdict") != "needs-tos-custom-export" else 2


if __name__ == "__main__":
    raise SystemExit(main())
