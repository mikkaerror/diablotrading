from __future__ import annotations

"""Pre-registration integrity: frozen rules must not change silently.

Each registered experiment pins (1) the sha256 of its prereg doc and (2) the
values of the collector constants that implement its rules. Any drift shows
up as an alert in the Desk Editor. Changing a rule is allowed only by
registering a new version (new doc, new registry entry) before its data.

Registry: research/prereg_registry.json. `python3 inferno_prereg_integrity.py
register NAME` pins an entry (for new versions only). Research-only.
"""

import argparse
import hashlib
import importlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REGISTRY_FILE = ROOT / "research" / "prereg_registry.json"
OUTPUT_FILE = ROOT / "data" / "inferno_prereg_integrity.json"

EXPERIMENTS: dict[str, dict[str, Any]] = {
    "short-premium-v2": {
        "doc": "docs/SHORT_PREMIUM_PREREG_V2_2026-09-29.md",
        "module": "inferno_short_premium_shadow",
        "constants": ["MIN_DAYS_TO_EARNINGS", "MAX_DAYS_TO_EARNINGS", "MAX_DTE", "WING_MULTIPLE_OF_MOVE",
                      "MAX_LOSS_TO_CREDIT", "MAX_LEG_SPREAD_PCT", "V2_TIMEBOX_END"],
    },
    "earnings-runner-v1": {
        "doc": "docs/EARNINGS_RUNNER_PREREG_2026-09-30.md",
        "module": "inferno_earnings_runner",
        "constants": ["RUNUP_MIN_DAYS", "RUNUP_MAX_DAYS", "RUNUP_MAX_DTE", "QUIET_ATR_FRACTION",
                      "GAP_IM_FRACTION", "GAP_MIN", "SPREAD_DTE_TARGET", "SPREAD_DTE_MIN", "SPREAD_DTE_MAX",
                      "TAKE_PROFIT", "MAX_HOLD_TRADING_DAYS", "LONG_LEG_MAX_SPREAD", "SHORT_LEG_MAX_SPREAD"],
    },
}


def doc_sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def constant_values(module_name: str, names: list[str]) -> dict[str, str]:
    module = importlib.import_module(module_name)
    return {n: repr(getattr(module, n, None)) for n in names}


def fingerprint(name: str, root: Path = ROOT) -> dict[str, Any]:
    spec = EXPERIMENTS[name]
    return {"doc": spec["doc"], "docSha256": doc_sha(root / spec["doc"]),
            "module": spec["module"], "constants": constant_values(spec["module"], spec["constants"])}


def check(registry: dict[str, Any], current: dict[str, dict[str, Any]]) -> list[str]:
    alerts = []
    for name, pinned in registry.get("experiments", {}).items():
        now = current.get(name)
        if now is None:
            alerts.append(f"prereg {name}: no longer tracked")
            continue
        if pinned.get("docSha256") != now.get("docSha256"):
            alerts.append(f"prereg {name}: {pinned['doc']} changed since registration")
        changed = [k for k, v in (pinned.get("constants") or {}).items() if now["constants"].get(k) != v]
        if changed:
            alerts.append(f"prereg {name}: frozen rule constants changed ({', '.join(changed)})")
    return alerts


def run() -> dict[str, Any]:
    from inferno_io import atomic_write_json

    registry = json.loads(REGISTRY_FILE.read_text(encoding="utf-8")) if REGISTRY_FILE.exists() else {}
    current = {name: fingerprint(name) for name in EXPERIMENTS}
    alerts = check(registry, current)
    payload = {"generatedAt": datetime.now().astimezone().isoformat(), "stage": "prereg-integrity-research-only",
               "researchOnly": True, "alerts": alerts, "tracked": sorted(registry.get("experiments", {}))}
    atomic_write_json(OUTPUT_FILE, payload)
    return payload


def register(name: str) -> None:
    registry = json.loads(REGISTRY_FILE.read_text(encoding="utf-8")) if REGISTRY_FILE.exists() else {"experiments": {}}
    if name in registry["experiments"]:
        raise SystemExit(f"{name} is already registered; register a new version instead of re-pinning.")
    registry["experiments"][name] = {**fingerprint(name), "registeredAt": datetime.now().astimezone().isoformat()}
    REGISTRY_FILE.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-registration integrity check (research-only).")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "register"])
    parser.add_argument("name", nargs="?")
    args = parser.parse_args(argv)
    if args.command == "register":
        register(args.name)
        print(f"Registered {args.name}.")
        return 0
    payload = run()
    print("\n".join(payload["alerts"]) or f"All {len(payload['tracked'])} pre-registrations intact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
