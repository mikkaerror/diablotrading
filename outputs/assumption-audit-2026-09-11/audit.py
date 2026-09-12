"""Reproduce a frozen public-input conviction/threshold audit without writes to the desk."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from inferno_tos_formula_math import watchlist_technical_research_from_pulse

CONSTANTS = {"GIANT_TICKERS", "SLEEPER_HINTS", "CATEGORY_OVERRIDES", "CATEGORY_THEME_SCORES"}
FIELDS = ("gutCheckScore", "convictionAdjustedScore", "longTermConvictionScore", "researchAction", "evidenceGrade", "riskFlags")


def pure_source(source):
    tree = ast.parse(source)
    return "\n\n".join(ast.unparse(node) for node in tree.body if isinstance(node, ast.FunctionDef)
                       or isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in CONSTANTS for t in node.targets))


def load(source):
    namespace = {"math": math, "Counter": Counter,
                 "watchlist_technical_research_from_pulse": watchlist_technical_research_from_pulse}
    exec(compile("from __future__ import annotations\n" + source, "frozen-conviction", "exec"), namespace)
    return namespace


def finite(raw):
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        value = float(raw)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def run(frozen, revised_source):
    old, new = load(frozen["baselineSource"]), load(revised_source)
    rows = frozen["rows"]
    assert len({r["ticker"] for r in rows}) == len(rows)
    edge = {r["ticker"]: r for r in frozen["edgeRows"]}
    before = old["rank_rows"](rows, edge)
    after = new["rank_rows"](rows, edge)
    old_map, new_map = ({r["ticker"]: r for r in ranking} for ranking in (before, after))
    assert set(old_map) == set(new_map) == {r["ticker"] for r in frozen["savedScores"]}
    for saved in frozen["savedScores"]:
        for key in FIELDS:
            assert old_map[saved["ticker"]][key] == saved[key], (saved["ticker"], key, "baseline mismatch")

    changes = []
    for row in rows:
        ticker = row["ticker"]
        a, b = old_map[ticker], new_map[ticker]
        changed = {key: {"before": a[key], "after": b[key]} for key in FIELDS if a[key] != b[key]}
        if changed:
            changes.append({"ticker": ticker, "changes": changed, "inputDiagnostics": b["inputDiagnostics"]})

    def members(ranking, namespace, revised, maximum, options=False):
        return sorted(r["ticker"] for r in ranking
                      if (r["pillars"]["options"] >= 62 if options else r["signalTrigger"] and namespace["number"](r["readiness"]) >= 85)
                      and (namespace["within_earnings_window"](r, maximum) if revised
                           else namespace["number"](r["daysUntilEarnings"], 999) <= maximum))

    sections = {}
    for name, maximum, options in (("nearTerm", 30, False), ("optionsWatch", 45, True)):
        a, b = members(before, old, False, maximum, options), members(after, new, True, maximum, options)
        sections[name] = {"before": a, "after": b, "added": sorted(set(b)-set(a)), "removed": sorted(set(a)-set(b))}

    zero_contexts = []
    for row in rows:
        for key, fallback in (("rvol", "rvol"), ("atrExpansion", "atrZScore"),
                              ("distanceToSupportPct", "distanceToSupportPct"), ("distanceToResistancePct", "distanceToResistancePct")):
            raw = row["marketContext"].get(key)
            if raw is not None and not raw and finite(raw) == 0:
                zero_contexts.append({"ticker": row["ticker"], "field": key, "contextValue": raw, "fallbackValue": row.get(fallback)})

    thresholds = {}
    for name, population, field, cuts in (
        ("readiness", rows, "readiness", [60, 68, 72, 80, 85, 90]),
        ("adjustedConviction", after, "convictionAdjustedScore", [56, 62, 68, 72, 78]),
        ("ownershipConviction", after, "longTermConvictionScore", [66, 70, 72])):
        values = [v for r in population if (v := finite(r.get(field))) is not None]
        thresholds[name] = {"observed": len(values), "missingOrInvalid": len(population)-len(values),
                            "singlePredicateCounts": {str(cut): sum(v >= cut for v in values) for cut in cuts}}

    fallback_pe = []
    for row in after:
        diagnostics = row["inputDiagnostics"]
        if any(diagnostics["peUsedByFallbackPillars"].values()) and diagnostics["trackerPE"]["status"] != "meaningful":
            fallback_pe.append({"ticker": row["ticker"], "status": diagnostics["trackerPE"]["status"]})
    linked = sum(row["ticker"] in edge for row in rows)
    source_status = Counter(row["marketContext"].get("sourceStatus") or "missing" for row in rows)
    penalties = [row["ticker"] for row in rows if row["ticker"] not in edge
                 and row["ticker"] not in old["GIANT_TICKERS"] and row["ticker"] not in old["CATEGORY_OVERRIDES"]]
    return {
        "researchOnly": True, "promotable": False, "authorityChanged": False,
        "liveTradingAllowed": False, "brokerSubmitAllowed": False,
        "sourceTimes": frozen["sourceTimes"], "baselineReproduction": {"rows": len(rows), "fieldsPerRow": len(FIELDS), "allMatched": True},
        "sourceHashes": frozen["sourceHashes"], "revisedSourceHash": hashlib.sha256(revised_source.encode()).hexdigest(),
        "coverage": {"trackerRows": len(rows), "edgeLinked": linked, "noEdgeLink": len(rows)-linked,
                     "missingEdgePenaltyRows": len(penalties), "sourceStatusCounts": dict(source_status),
                     "fallbackPEStatusCounts": dict(Counter(r["status"] for r in fallback_pe))},
        "changes": changes, "changedRows": len(changes),
        "actionChanges": [r for r in changes if "researchAction" in r["changes"]],
        "actionCounts": {"before": dict(Counter(r["researchAction"] for r in before)), "after": dict(Counter(r["researchAction"] for r in after))},
        "sectionMembership": sections, "zeroContexts": zero_contexts,
        "thresholdSensitivity": thresholds,
        "rankComparison": {"beforeTop20": [r["ticker"] for r in before[:20]], "afterTop20": [r["ticker"] for r in after[:20]],
                           "top20Overlap": len({r["ticker"] for r in before[:20]} & {r["ticker"] for r in after[:20]})},
        "limitations": [
            "Frozen snapshot and saved 40-name edge linkage; no provider refresh, outcome labels or full-universe fundamentals rebuild.",
            "Single-cutoff counts are selectivity, not combined admission, profitability or optimal thresholds.",
            "P/E corrections retain the existing missing-input buckets. Those buckets remain unvalidated assumptions.",
            "Research action/list changes do not stage, approve or submit tickets; risk and authority remain downstream.",
            "Source status is a saved label, not independent freshness proof. No RVOL session-normalization repair is claimed.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seal", action="store_true", help="Freeze corrected pure source once after review")
    parser.add_argument("--verify", action="store_true", help="Compare saved results without rewriting them")
    args = parser.parse_args()
    frozen = json.loads((HERE/"frozen-inputs.json").read_text())
    source_path = HERE/"revised-source.py"
    if args.seal:
        with source_path.open("x") as target:
            target.write(pure_source((ROOT/"inferno_conviction_research.py").read_text()) + "\n")
    source = source_path.read_text()
    result = run(frozen, source)
    if args.verify:
        assert result == json.loads((HERE/"results.json").read_text()), "saved result mismatch"
    else:
        (HERE/"results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: result[k] for k in ("baselineReproduction", "coverage", "changedRows", "actionCounts", "sectionMembership", "thresholdSensitivity", "rankComparison")}, indent=2))


if __name__ == "__main__":
    main()
