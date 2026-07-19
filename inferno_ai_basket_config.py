#!/usr/bin/env python3
"""Read the fixed AI-basket universe contract without widening membership."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
UNIVERSE_FILE = ROOT / "research" / "ai_basket_universe.json"
DATA_CONTRACT_FILE = ROOT / "data" / "inferno_ai_basket_data_contract.json"
BENCHMARK = "SMH"


def load_basket(path: Path = UNIVERSE_FILE) -> dict[str, str]:
    """Return only symbols explicitly declared by the tracked universe artifact."""
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    declared = payload.get("expectedUniverse")
    records = payload.get("records")
    if not isinstance(declared, list) or not isinstance(records, list):
        return {}
    categories = {
        str(row.get("symbol") or "").strip().upper(): str(row.get("cat") or "").strip()
        for row in records
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }
    basket: dict[str, str] = {}
    for value in declared:
        symbol = str(value or "").strip().upper()
        if symbol and symbol in categories and symbol not in basket:
            basket[symbol] = categories[symbol]
    return basket


BASKET = load_basket()
SYMBOLS = list(BASKET)


def normalize_symbol(value: object) -> str:
    """Normalize a ticker-like value without inventing basket membership."""
    return str(value or "").strip().upper()


def load_data_contract(path: Path = DATA_CONTRACT_FILE) -> dict[str, Any]:
    """Read the canonical basket-input trust verdict, failing closed on error."""
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def data_contract_trusted(payload: dict[str, Any] | None = None) -> bool:
    """Return true only for an explicit canonical full-input trust verdict."""
    contract = load_data_contract() if payload is None else payload
    return bool(isinstance(contract, dict) and contract.get("signalsTrusted") is True)

# Factor buckets — coarse groupings of the fine-grained categories, so the
# desk can read single-factor concentration. Kept here as the single source of
# truth shared by the weekly review and the live tracker artifact.
COMPLEX_CATEGORIES = {
    "Compute", "Networking Si", "Server OEM", "Power/Cooling", "Optical",
    "Networking", "DC Operator", "Storage", "Semi Test",
}
SOFTWARE_CATEGORIES = {"Hyperscaler", "Cloud Rails", "Security"}


def category(symbol: str) -> str:
    """Return the category for a declared symbol, or blank for an outsider."""
    return BASKET.get(str(symbol or "").strip().upper(), "")


def factor_bucket(cat: str) -> str:
    """Map a fine category to its coarse factor bucket."""
    c = str(cat or "").strip()
    if c in COMPLEX_CATEGORIES:
        return "AI-capex hardware complex"
    if c in SOFTWARE_CATEGORIES:
        return "Software / hyperscaler"
    return "Industrials / bearings"
