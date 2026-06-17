from __future__ import annotations

"""Build a compact multi-cash capital launch matrix for planning.

The regular launch check answers "can this one cash amount deploy now?" This
module keeps a small planning grid for the operator's likely funding range
without widening authority or submitting anything.
"""

import argparse
from typing import Any

from inferno_capital_launch_check import build_capital_launch_check
from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, ensure_dirs


CAPITAL_SCENARIO_MATRIX_FILE = DATA_DIR / "inferno_capital_scenario_matrix.json"
CAPITAL_SCENARIO_MATRIX_TEXT_FILE = REPORTS_DIR / "capital_scenario_matrix_latest.txt"
DEFAULT_DEPLOYABLE_CASH_VALUES = (500.0, 3000.0, 5000.0)


def number(value: Any, default: float = 0.0) -> float:
    """Parse numeric report values while tolerating display formatting."""
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value or "").replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return default


def money(value: Any) -> str:
    """Render dollars for the scenario table."""
    return f"${number(value):,.2f}"


def human_decision_symbols(decisions: list[dict[str, Any]]) -> list[str]:
    """Return the symbols that require operator attention in order."""
    symbols: list[str] = []
    for item in decisions:
        symbol = str(item.get("symbol") or "").strip().upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def scenario_row(launch_check: dict[str, Any]) -> dict[str, Any]:
    """Condense one launch-check payload into the matrix row shape."""
    readiness = launch_check.get("capitalReadiness") or {}
    guardrails = readiness.get("guardrails") or {}
    risk = launch_check.get("riskGateAudit") or {}
    live_book = launch_check.get("liveBook") or {}
    live_counts = live_book.get("counts") or {}
    decisions = live_book.get("requiredHumanDecisions") or []
    risk_summary = risk.get("summary") or {}
    return {
        "deployableCash": number(launch_check.get("deployableCash")),
        "deploymentDate": launch_check.get("deploymentDate"),
        "verdict": launch_check.get("verdict"),
        "message": launch_check.get("message"),
        "manualDeploymentAllowed": bool(launch_check.get("manualDeploymentAllowed")),
        "autoLiveAllowed": bool(launch_check.get("autoLiveAllowed")),
        "maxOptionsRisk": number(guardrails.get("maxOptionsRisk")),
        "maxStarterTicket": number(guardrails.get("maxStarterTicket")),
        "maxLongTermBuy": number(guardrails.get("maxLongTermBuy")),
        "reserveCash": number(guardrails.get("reserveCash")),
        "liveBookVerdict": live_book.get("verdict"),
        "hardBlockers": int(number(live_counts.get("hardBlockers"))),
        "warnings": int(number(live_counts.get("warnings"))),
        "riskGateVerdict": risk.get("verdict"),
        "riskGatePassed": int(number(risk_summary.get("passed"))),
        "riskGateTotal": int(number(risk_summary.get("total"))),
        "blockers": readiness.get("blockers") or [],
        "warningMessages": readiness.get("warnings") or [],
        "requiredHumanDecisionSymbols": human_decision_symbols(decisions),
    }


def matrix_verdict(rows: list[dict[str, Any]]) -> str:
    """Collapse scenario rows into one operator-facing verdict."""
    if not rows:
        return "empty"
    verdicts = {str(row.get("verdict") or "") for row in rows}
    if verdicts == {"blocked"}:
        return "all-blocked"
    if "blocked" in verdicts:
        return "mixed"
    return "ready-for-manual-review"


def build_capital_scenario_matrix(
    *,
    deployable_cash_values: list[float] | None = None,
    for_date: str | None = None,
    refresh_live_sync: bool = False,
) -> dict[str, Any]:
    """Build and persist the multi-scenario launch matrix."""
    ensure_dirs()
    cash_values = deployable_cash_values or list(DEFAULT_DEPLOYABLE_CASH_VALUES)
    rows: list[dict[str, Any]] = []
    for index, cash in enumerate(cash_values):
        launch_check = build_capital_launch_check(
            deployable_cash=cash,
            for_date=for_date,
            refresh_live_sync=refresh_live_sync and index == 0,
        )
        rows.append(scenario_row(launch_check))

    payload = {
        "generatedAt": local_now().isoformat(),
        "stage": "capital-scenario-matrix",
        "verdict": matrix_verdict(rows),
        "scenarioCount": len(rows),
        "deploymentDate": for_date or (rows[0].get("deploymentDate") if rows else None),
        "scenarios": rows,
        "operatorRule": (
            "Planning only. No broker submit, no live order, and no authority "
            "promotion without explicit user confirmation."
        ),
    }
    save_capital_scenario_matrix(payload)
    return payload


def render_capital_scenario_matrix(payload: dict[str, Any]) -> str:
    """Render the scenario matrix for operator review."""
    lines = [
        "Inferno Capital Scenario Matrix",
        "=" * 32,
        f"Generated: {payload.get('generatedAt')}",
        f"Deployment date: {payload.get('deploymentDate') or '-'}",
        f"Verdict: {payload.get('verdict')}",
        f"Operator rule: {payload.get('operatorRule')}",
        "",
        "Scenarios:",
    ]
    for row in payload.get("scenarios") or []:
        symbols = ", ".join(row.get("requiredHumanDecisionSymbols") or []) or "-"
        lines.append(
            "- "
            f"{money(row.get('deployableCash'))}: {row.get('verdict')} | "
            f"options risk {money(row.get('maxOptionsRisk'))} | "
            f"starter {money(row.get('maxStarterTicket'))} | "
            f"long-term {money(row.get('maxLongTermBuy'))} | "
            f"reserve {money(row.get('reserveCash'))} | "
            f"live blockers {row.get('hardBlockers')} | "
            f"warnings {row.get('warnings')} | "
            f"risk gates {row.get('riskGatePassed')}/{row.get('riskGateTotal')} | "
            f"decisions {symbols}"
        )

    lines.extend(["", "Blockers by scenario:"])
    for row in payload.get("scenarios") or []:
        blockers = row.get("blockers") or []
        if not blockers:
            lines.append(f"- {money(row.get('deployableCash'))}: none")
            continue
        lines.append(f"- {money(row.get('deployableCash'))}:")
        lines.extend(f"  - {item}" for item in blockers)

    lines.extend(["", "Warnings by scenario:"])
    for row in payload.get("scenarios") or []:
        warnings = row.get("warningMessages") or []
        if not warnings:
            lines.append(f"- {money(row.get('deployableCash'))}: none")
            continue
        lines.append(f"- {money(row.get('deployableCash'))}:")
        lines.extend(f"  - {item}" for item in warnings)
    return "\n".join(lines).rstrip() + "\n"


def save_capital_scenario_matrix(payload: dict[str, Any]) -> None:
    """Persist JSON and text copies of the matrix."""
    atomic_write_json(CAPITAL_SCENARIO_MATRIX_FILE, payload)
    atomic_write_text(CAPITAL_SCENARIO_MATRIX_TEXT_FILE, render_capital_scenario_matrix(payload))


def parse_cash_values(values: list[str]) -> list[float]:
    """Parse CLI cash values."""
    if not values:
        return list(DEFAULT_DEPLOYABLE_CASH_VALUES)
    return [float(value.replace("$", "").replace(",", "")) for value in values]


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Build the Inferno capital scenario matrix.")
    parser.add_argument(
        "--deployable-cash",
        nargs="*",
        default=[],
        help="Cash scenarios to test. Defaults to 500 3000 5000.",
    )
    parser.add_argument("--for-date", default=None, help="Deployment date to stamp in the matrix.")
    parser.add_argument("--refresh-live-sync", action="store_true", help="Refresh live sync before the first scenario.")
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    payload = build_capital_scenario_matrix(
        deployable_cash_values=parse_cash_values(args.deployable_cash),
        for_date=args.for_date,
        refresh_live_sync=args.refresh_live_sync,
    )
    print(render_capital_scenario_matrix(payload))
    return 0 if payload.get("verdict") != "all-blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
