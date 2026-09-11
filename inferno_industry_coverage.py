"""Full-universe research coverage, independent of score and trading gates."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text

ROOT=Path(__file__).resolve().parent
REPORT=ROOT/'data/inferno_industry_coverage.json'
TEXT=ROOT/'reports/industry_coverage_latest.txt'
ROLES=ROOT/'research/industry_roles.json'


def build_industry_coverage(snapshot, taxonomy, roles, *, now=None):
    now=now or local_now()
    symbols=sorted({str(r.get('ticker') or '').strip().upper() for r in snapshot.get('rows',[]) if r.get('ticker')})
    entries={r['ticker']:r for r in taxonomy.get('entries',[])}
    rows=[]
    for ticker in symbols:
        ref=entries.get(ticker,{})
        override=roles.get(ticker)
        covered=bool(ref.get('industry') and ref.get('sector'))
        row=dict(ticker=ticker,companyName=ref.get('companyName') or ticker,
                 sector=ref.get('sector'),industry=ref.get('industry'),
                 economicRole=ref.get('economicExposure') if covered else 'unresolved',
                 evidenceLevel='provider-reference' if covered else 'unresolved',
                 referenceSource=ref.get('referenceSource'),referenceAsOf=ref.get('referenceAsOf'),
                 referenceFresh=ref.get('referenceFresh') is True,
                 sourceUrl=None,issuerReviewDue=True,
                 researchHorizon='establish company-specific operating and valuation milestones',
                 watchMetrics=['confirm business mix','funding and margins','valuation and next catalyst'],
                 limitation='Broad reference label; issuer-specific revenue exposure is not verified.')
        if override:
            due=now.date().isoformat()>override['reviewAfter']
            row.update(economicRole=override['role'],evidenceLevel='issuer-linked-research',
                       sourceUrl=override['sourceUrl'],roleReviewedAt=override['reviewedAt'],
                       roleReviewAfter=override['reviewAfter'],issuerReviewDue=due,
                       researchHorizon=override['horizon'],watchMetrics=override['watchMetrics'],
                       limitation='Research interpretation of cited issuer evidence; verify subsequent changes and current valuation.'
                                  if not due else 'Issuer role review overdue; dated evidence must be revisited.')
        rows.append(row)
    assert len(rows)==len(symbols)
    return dict(generatedAt=now.isoformat(),stage='full-industry-coverage-research-only',
                verdict='coverage-visible' if rows else 'missing-tracker',researchOnly=True,
                promotable=False,authorityChanged=False,brokerSubmitAllowed=False,liveTradingAllowed=False,
                gateInput=False,trackedRows=len(symbols),coveredRows=len(rows),
                sourceTrackerAsOf=snapshot.get('generatedAt'),sourceTaxonomyAsOf=taxonomy.get('generatedAt'),
                evidenceCounts=dict(Counter(r['evidenceLevel'] for r in rows)),
                issuerReviewDue=sum(r['issuerReviewDue'] for r in rows),
                staleOrMissingReference=sum(not r['referenceFresh'] for r in rows),rows=rows,
                caveats=['No top-N selection; every tracker symbol is retained.',
                         'Provider coverage is not issuer verification or proven AI revenue exposure.',
                         'Research roles do not alter legacy themes, scores, operator roles, eligible universe or positions.'])


def industry_coverage_text(report):
    lines=['Inferno Full Industry Coverage — research only','',
           f"Generated: {report['generatedAt']}",
           f"Tracker source: {report['sourceTrackerAsOf']} | reference source: {report['sourceTaxonomyAsOf']}",
           f"Visible: {report['coveredRows']}/{report['trackedRows']} | evidence: {report['evidenceCounts']}",
           f"Company-specific reviews due: {report['issuerReviewDue']}",'']
    for row in report['rows']:
        lines += [f"{row['ticker']} — {row['economicRole']} [{row['evidenceLevel']}]",
                  f"  Horizon: {row['researchHorizon']}. Watch: {', '.join(row['watchMetrics'])}.",
                  f"  Evidence: {row['sourceUrl'] or row['referenceSource'] or 'missing'}; reference as of {row['referenceAsOf']}.",
                  f"  {row['limitation']}"]
    return '\n'.join(lines+['',*report['caveats'],''])


def save_industry_coverage(report):
    atomic_write_json(REPORT,report)
    atomic_write_text(TEXT,industry_coverage_text(report))


def main():
    snapshot=json.loads((ROOT/'data/latest_snapshot.json').read_text())
    taxonomy=json.loads((ROOT/'data/inferno_tracker_taxonomy.json').read_text())
    config=json.loads(ROLES.read_text())
    if config.get('researchOnly') is not True or config.get('gateInput') is not False:
        raise ValueError('Research-only role configuration required')
    report=build_industry_coverage(snapshot,taxonomy,config['roles'])
    save_industry_coverage(report)
    print(json.dumps({k:report[k] for k in ['verdict','trackedRows','coveredRows','evidenceCounts','issuerReviewDue','gateInput']}))


if __name__=='__main__':main()
