"""Read-only weekly paper funnel; observations are never ticket decisions."""
from __future__ import annotations
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, load_json_file

FUNNEL_STAGE = 'paper-funnel-research-only'
FUNNEL_FILE = DATA_DIR / 'inferno_paper_funnel.json'
RUNS_FILE = DATA_DIR / 'paper_funnel_runs.jsonl'
TEXT_FILE = REPORTS_DIR / 'paper_funnel_latest.txt'


def week_of(value):
    try:
        d = date.fromisoformat(str(value)[:10])
        return (d - timedelta(days=d.weekday())).isoformat()
    except ValueError:
        return 'undated'


def weekly_funnel(ledger, lineage):
    """Cohort by creation week; stages are observed lifetime stages, not flows."""
    qualified = {r['recordId'] for r in lineage.get('records', [])
                 if r.get('promotionEligible') and r.get('source') == 'paper-execution-ledger'}
    groups = defaultdict(list)
    seen = set()
    for i, row in enumerate(ledger.get('items', [])):
        identity = row.get('ticketId') or f'missing-id-{i}'
        if identity in seen:
            continue
        seen.add(identity)
        groups[(week_of(row.get('createdAt') or row.get('tradeDate')), row.get('strategy') or 'unknown')].append(row)
    output = []
    for (week, strategy), rows in sorted(groups.items()):
        reasons = Counter()
        for row in rows:
            reasons.update(set(row.get('blockReasons') or []))
        output.append({'week': week, 'strategy': strategy, 'proposed': len(rows),
            'blocked': sum(r.get('status') == 'paper-blocked' for r in rows),
            'blockedByReason': dict(reasons),
            'rejected': sum(r.get('status') == 'paper-rejected' for r in rows),
            'staged': sum(r.get('status') == 'paper-staged' for r in rows),
            'filled': sum(bool((r.get('paperExecution') or {}).get('openedAt')) and
                          (r.get('paperExecution') or {}).get('entryPrice') is not None for r in rows),
            'qualified': sum(r.get('ticketId') in qualified for r in rows)})
    return output


def observe_run(plan, path=None):
    """Persist each source run once; only explicitly tagged dawn runs can qualify."""
    path = path or RUNS_FILE
    stamp = plan.get('generatedAt')
    if not stamp:
        return
    prior = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    if any(r.get('generatedAt') == stamp for r in prior):
        return
    rows = plan.get('items', [])
    passing = [r for r in rows if r.get('ok') and not r.get('concentrationDemoted') and
               not r.get('shadowOnly') and (r.get('riskVerdict') or {}).get('passed') and
               not (r.get('strikePlan') or {}).get('liquidityNotes') and
               not [b for b in r.get('intentBlocks', []) if 'approval' not in b.lower()]]
    record = {'generatedAt': stamp, 'runKind': plan.get('runKind', 'manual'),
              'proposed': len(rows), 'gatePassing': len(passing),
              'byStrategy': dict(Counter((r.get('strikePlan') or {}).get('strategy', 'unknown') for r in passing)),
              'researchOnly': True}
    from inferno_io import append_text
    append_text(path, json.dumps(record) + '\n')


def dawn_acceptance(runs, *, today=None):
    """Require five recorded weekdays; reruns cannot inflate the daily mean."""
    today = today or local_now().date()
    days = []
    cursor = today - timedelta(days=1)
    while len(days) < 5:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    by_day = {}
    for run in sorted(runs, key=lambda r: r.get('generatedAt', '')):
        day = str(run.get('generatedAt', ''))[:10]
        if run.get('runKind') == 'dawn' and day in days:
            by_day.setdefault(day, run)  # first completed capture; no best-of-day selection
    counts = {day: by_day[day]['gatePassing'] if day in by_day else None for day in sorted(days)}
    complete = len(by_day) == 5
    average = sum(counts.values()) / 5 if complete else None
    return {'sessions': counts, 'observedSessions': len(by_day), 'averageGatePassing': average,
            'candidateTargetMet': complete and average >= 3,
            'boundaryAuditRequired': True, 'done': False,
            'reason': 'Nightly boundary audit must be independently verified; missing sessions are unknown.'}


def build_paper_funnel():
    from inferno_promotion_evidence_lineage import build_promotion_evidence_lineage
    ledger = load_json_file(DATA_DIR / 'inferno_paper_execution_ledger.json') or {}
    lineage = build_promotion_evidence_lineage(paper_ledger=ledger, fast_ledger={}, shadow_evidence={})
    runs = [json.loads(line) for line in RUNS_FILE.read_text().splitlines()] if RUNS_FILE.exists() else []
    return {'stage': FUNNEL_STAGE, 'generatedAt': local_now().isoformat(), 'researchOnly': True, 'promotable': False,
            'authorityChanged': False, 'brokerSubmitAllowed': False, 'liveTradingAllowed': False,
            'citations': ['inferno_paper_execution_ledger.json', 'inferno_promotion_evidence_lineage.py', 'paper_funnel_runs.jsonl'],
            'weeks': weekly_funnel(ledger, lineage), 'promotionTruth': lineage['promotionTruth'],
            'dawnAcceptance': dawn_acceptance(runs),
            'limits': ['Creation-week cohorts, not a reconstructed transition log. Block reasons can overlap.',
                       'Only recorded fills and lineage qualification count; intrinsic closes earn no credit.']}


def funnel_text(report):
    lines = ['Inferno weekly paper funnel (research-only)', f"Generated: {report['generatedAt']}",
             'Creation week | strategy | proposed -> blocked -> staged -> filled -> qualified']
    for row in report['weeks']:
        lines.append(f"{row['week']} | {row['strategy']} | " + ' -> '.join(str(row[k]) for k in ('proposed','blocked','staged','filled','qualified')))
        lines.append('  blockers (overlap): ' + json.dumps(row['blockedByReason'], sort_keys=True))
    lines += ['Dawn acceptance: ' + json.dumps(report['dawnAcceptance']), *report['limits']]
    return '\n'.join(lines) + '\n'


def save_paper_funnel(report):
    atomic_write_json(FUNNEL_FILE, report)
    atomic_write_text(TEXT_FILE, funnel_text(report))


def main():
    report = build_paper_funnel()
    save_paper_funnel(report)
    print(funnel_text(report))


if __name__ == '__main__':
    main()
