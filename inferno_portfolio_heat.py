from __future__ import annotations

"""Total-NLV theme heat across live shares and open paper max loss."""

import argparse
from collections import defaultdict
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_trade_evidence import max_loss_dollars
from server import DATA_DIR, REPORTS_DIR, ensure_dirs, load_json_file


ACCOUNT_FILE = DATA_DIR / "inferno_schwab_account_sync.json"
PAPER_LEDGER_FILE = DATA_DIR / "inferno_paper_execution_ledger.json"
DIRECTOR_FILE = DATA_DIR / "inferno_paper_test_director.json"
CONVICTION_FILE = DATA_DIR / "inferno_conviction_research.json"
PORTFOLIO_HEAT_FILE = DATA_DIR / "inferno_portfolio_heat.json"
PORTFOLIO_HEAT_TEXT_FILE = REPORTS_DIR / "portfolio_heat_latest.txt"
STAGE = "portfolio-heat-research-only"

KNOWN_THEME_MAP = {
    "IREN": "digital-infrastructure-miners",
    "HIVE": "digital-infrastructure-miners",
    "CLSK": "digital-infrastructure-miners",
    "TE": "power-grid-utility",
}
THEME_WATCH_PCT_NLV = 25.0
THEME_HIGH_PCT_NLV = 40.0


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _conviction_categories(payload: dict[str, Any]) -> dict[str, str]:
    index: dict[str, str] = {}
    for key in ("behemoths", "sleepers", "nearTermWinners", "bestBalanced", "ranked"):
        for row in payload.get(key) or []:
            ticker = str(row.get("ticker") or "").upper()
            category = str(row.get("category") or "").strip()
            if ticker and category:
                index.setdefault(ticker, category.lower().replace(" ", "-"))
    return index


def _theme(ticker: str, categories: dict[str, str]) -> str:
    return KNOWN_THEME_MAP.get(ticker) or categories.get(ticker) or "unclassified"


def build_portfolio_heat(
    *,
    account: dict[str, Any] | None = None,
    ledger: dict[str, Any] | None = None,
    director: dict[str, Any] | None = None,
    conviction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    account = account if account is not None else (load_json_file(ACCOUNT_FILE) or {})
    ledger = ledger if ledger is not None else (load_json_file(PAPER_LEDGER_FILE) or {})
    director = director if director is not None else (load_json_file(DIRECTOR_FILE) or {})
    conviction = conviction if conviction is not None else (load_json_file(CONVICTION_FILE) or {})
    nlv = _number(account.get("netLiquidatingValue"))
    categories = _conviction_categories(conviction)
    heat: dict[str, float] = defaultdict(float)
    components = []

    for position in account.get("positions") or []:
        if str(position.get("assetType") or "EQUITY").upper() != "EQUITY":
            continue
        ticker = str(position.get("symbol") or "").upper()
        value = _number(position.get("markValue"))
        theme = _theme(ticker, categories)
        heat[theme] += value
        components.append(
            {"source": "live-equity", "ticker": ticker, "theme": theme, "riskDollars": round(value, 2)}
        )

    for item in ledger.get("items") or []:
        if (
            str(item.get("status") or "").lower() != "paper-staged"
            or str((item.get("outcome") or {}).get("status") or "").lower() != "open"
        ):
            continue
        ticker = str(item.get("ticker") or "").upper()
        risk = max_loss_dollars(item)
        theme = _theme(ticker, categories)
        heat[theme] += risk
        components.append(
            {"source": "open-paper-max-loss", "ticker": ticker, "theme": theme, "riskDollars": round(risk, 2)}
        )

    themes = []
    for theme, dollars in sorted(heat.items(), key=lambda row: row[1], reverse=True):
        pct = dollars / nlv * 100.0 if nlv > 0 else None
        level = "high" if pct is not None and pct >= THEME_HIGH_PCT_NLV else (
            "watch" if pct is not None and pct >= THEME_WATCH_PCT_NLV else "normal"
        )
        themes.append(
            {"theme": theme, "riskDollars": round(dollars, 2), "pctOfNlv": round(pct, 2) if pct is not None else None, "level": level}
        )

    denominator = sum(row["riskDollars"] for row in themes)
    effective_themes = (
        1.0 / sum((row["riskDollars"] / denominator) ** 2 for row in themes)
        if denominator > 0 and themes
        else 0.0
    )
    candidates = []
    candidate_rows = (
        list(director.get("stageableSlate") or [])
        + list(director.get("autoPaperSlate") or [])
        + list(director.get("approvalSlate") or [])
        + list(director.get("researchWatchlist") or director.get("researchWatchSlate") or [])
    )
    for item in candidate_rows:
        ticker = str(item.get("ticker") or "").upper()
        risk = _number(item.get("estimatedMaxLoss"))
        theme = _theme(ticker, categories)
        current = heat.get(theme, 0.0)
        projected_pct = (current + risk) / nlv * 100.0 if nlv > 0 else None
        candidates.append(
            {
                "ticker": ticker,
                "theme": theme,
                "incrementalMaxLoss": round(risk, 2),
                "projectedThemePctOfNlv": round(projected_pct, 2) if projected_pct is not None else None,
                "heatVerdict": (
                    "high" if projected_pct is not None and projected_pct >= THEME_HIGH_PCT_NLV
                    else "watch" if projected_pct is not None and projected_pct >= THEME_WATCH_PCT_NLV
                    else "normal"
                ),
            }
        )

    verdict = "high-theme-heat" if any(row["level"] == "high" for row in themes) else (
        "theme-watch" if any(row["level"] == "watch" for row in themes) else "normal"
    )
    return {
        "generatedAt": local_now().isoformat(),
        "stage": STAGE,
        "verdict": verdict,
        "researchOnly": True,
        "promotable": False,
        "authorityChanged": False,
        "liveTradingAllowed": False,
        "brokerSubmitAllowed": False,
        "netLiquidatingValue": nlv,
        "thresholds": {"watchPctOfNlv": THEME_WATCH_PCT_NLV, "highPctOfNlv": THEME_HIGH_PCT_NLV},
        "effectiveThemeCount": round(effective_themes, 4),
        "themes": themes,
        "components": components,
        "candidateImpacts": candidates,
        "reminders": [
            "Theme heat combines live equity market value with open paper maximum loss as a conservative exposure proxy.",
            "Different tickers can represent one economic bet; ticker count is not diversification.",
            "This report warns but does not approve, reject, or resize a trade.",
        ],
    }


def render(payload: dict[str, Any]) -> str:
    lines = [
        "Inferno Portfolio Heat",
        "",
        f"Generated: {payload.get('generatedAt')}",
        f"Verdict: {payload.get('verdict')}",
        f"NLV: ${payload.get('netLiquidatingValue', 0):,.2f}",
        f"Effective theme count: {payload.get('effectiveThemeCount')}",
        "",
        "Theme heat:",
    ]
    for row in payload.get("themes") or []:
        lines.append(
            f"- {row.get('theme')} | ${row.get('riskDollars'):,.2f} | "
            f"{row.get('pctOfNlv')}% NLV | {row.get('level')}"
        )
    lines.extend(["", "Candidate impacts:"])
    for row in payload.get("candidateImpacts") or []:
        lines.append(
            f"- {row.get('ticker')} | {row.get('theme')} | +${row.get('incrementalMaxLoss'):,.2f} | "
            f"projected {row.get('projectedThemePctOfNlv')}% | {row.get('heatVerdict')}"
        )
    if not payload.get("candidateImpacts"):
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def save(payload: dict[str, Any]) -> None:
    ensure_dirs()
    atomic_write_json(PORTFOLIO_HEAT_FILE, payload)
    atomic_write_text(PORTFOLIO_HEAT_TEXT_FILE, render(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Inferno total-NLV portfolio heat.")
    parser.add_argument("command", nargs="?", default="build", choices=["build", "status"])
    args = parser.parse_args()
    if args.command == "status" and PORTFOLIO_HEAT_TEXT_FILE.exists():
        print(PORTFOLIO_HEAT_TEXT_FILE.read_text(encoding="utf-8"), end="")
        return 0
    payload = build_portfolio_heat()
    save(payload)
    print(render(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
