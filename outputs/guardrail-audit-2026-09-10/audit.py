"""Frozen-input guard attribution and metric probes. No production imports/writes."""
import argparse
import ast
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FUNCTIONS = {'clamp','number','market_context_row','classify_lane',
             'valuation_risk_score','quality_score','tracker_timing_score'}
PROTECTED = ['inferno_edge_research.py','inferno_risk_policy.py','inferno_config.py',
             'inferno_capital_scaling.py','inferno_capital_allocator.py',
             'inferno_trade_evidence.py','inferno_expected_move_ledger.py',
             'inferno_authority_controller.py','inferno_score_calibration.py']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze():
    source = ROOT/'inferno_edge_research.py'
    tree = ast.parse(source.read_text())
    code = '\n\n'.join(ast.unparse(node) for node in tree.body
                       if isinstance(node,ast.FunctionDef) and node.name in FUNCTIONS)
    edge_path = ROOT/'data/inferno_edge_research.json'
    edge = json.loads(edge_path.read_text())
    snapshot = json.loads((ROOT/'data/latest_snapshot.json').read_text())
    cache = json.loads((ROOT/'data/inferno_edge_metadata_cache.json').read_text())['tickers']
    rows = []
    for row in edge['ranked']:
        slim={k:row.get(k) for k in ['ticker','category','lane','readiness',
                    'longTermScore','daysUntilEarnings','signalTrigger']}
        slim['scores']={k:row['scores'][k] for k in ['edgeScore','confirmationScore','qualityScore']}
        slim['marketContext']={'distanceToSupportPct':(row.get('marketContext') or {}).get('distanceToSupportPct')}
        rows.append(slim)
    # Public market research only; no account, ticket or position inputs.
    payload = dict(edgeGeneratedAt=edge['generatedAt'], sourceHash=sha(edge_path),
                   trackerGeneratedAt=snapshot['generatedAt'],
                   trackerTickers=sorted({r['ticker'] for r in snapshot['rows']}),
                   rows=rows, pureSource=code, protectedHashes={p:sha(ROOT/p) for p in PROTECTED},
                   peInputs={s:{k:m.get(k) for k in ['forwardPE','trailingPE','fetchedAt']}
                             for s,m in cache.items()},
                   protocol='Use saved scores unchanged; remove one Boolean gate at a time. Count admissions, not return or edge. Do not retune thresholds or change theme-score bonuses.')
    (HERE/'frozen-inputs.json').write_text(json.dumps(payload,indent=2)+'\n')


def predicates(row,lane):
    scores=row['scores']
    common={'mappedTheme':row['category']!='Unclassified'}
    def num(value,default=0):
        return float(value) if value is not None else default
    if lane=='catalyst':
        return dict(common, edge72=scores['edgeScore']>=72,
                    confirmation60=scores['confirmationScore']>=60,
                    trigger=bool(row['signalTrigger']),readiness85=num(row['readiness'])>=85,
                    earningsWithin21=num(row['daysUntilEarnings'],999)<=21)
    return dict(common,edge68=scores['edgeScore']>=68,
                longTerm65=num(row['longTermScore'])>=6.5,
                quality50=scores['qualityScore']>=50,
                supportWithin10=num((row['marketContext'] or {}).get('distanceToSupportPct'),999)<=10)


def run():
    frozen=json.loads((HERE/'frozen-inputs.json').read_text())
    ns={'Any':Any}
    exec(compile(frozen['pureSource'],'frozen-edge-functions','exec'),ns)
    rows=frozen['rows']
    assert len({r['ticker'] for r in rows})==len(rows)
    for row in rows:
        actual=ns['classify_lane'](row,row['scores'],{'category':row['category']})
        assert actual==row['lane'],(row['ticker'],actual,row['lane'])
        c=all(predicates(row,'catalyst').values()); l=all(predicates(row,'ownership').values())
        assert (actual=='Catalyst Trade Candidate')==c
        assert (actual=='Long-Term Shovel Accumulation')==(l and not c)
    ablations={}
    for lane in ['catalyst','ownership']:
        gates={r['ticker']:predicates(r,lane) for r in rows}
        baseline=sorted(t for t,g in gates.items() if all(g.values()))
        changes=[]
        for remove in next(iter(gates.values())):
            passed=sorted(t for t,g in gates.items() if all(v for k,v in g.items() if k!=remove))
            assert set(baseline)<=set(passed)
            changes.append(dict(removedGate=remove,totalPassing=len(passed),
                                added=sorted(set(passed)-set(baseline))))
        ablations[lane]=dict(baseline=baseline,oneGateRemoved=changes,
                            failedGateCounts=dict(Counter(k for g in gates.values() for k,v in g.items() if not v)))
    row=dict(readiness=95,priority=8,confidence=3,signalTrigger=True,
             daysUntilEarnings=-1,longTermScore=8,marketContext={'distanceToSupportPct':3})
    scores=dict(edgeScore=80,confirmationScore=80,qualityScore=70)
    past=ns['classify_lane'](row,scores,{'category':'AI/Compute Picks'})
    assert past=='Catalyst Trade Candidate'
    synthetic={}
    for pe in [-10,20,100]:
        synthetic[str(pe)]=ns['valuation_risk_score'](row,dict(forwardPE=pe,priceToSalesTrailing12Months=5,beta=1))
    assert synthetic['-10']==synthetic['20']>synthetic['100']
    quality=[ns['quality_score'](dict(revenueGrowth=g)) for g in [.5,2.0]]
    assert quality[0]==quality[1]
    selected={r['ticker'] for r in rows}
    negative=[]
    for ticker, m in frozen['peInputs'].items():
        effective=m['forwardPE'] or m['trailingPE']
        if effective is not None and float(effective)<0:
            negative.append(dict(ticker=ticker,effectivePE=effective,
                                 selectedIn40=ticker in selected,fetchedAt=m['fetchedAt']))
    result=dict(researchOnly=True,promotable=False,authorityChanged=False,
                sourceGeneratedAt=frozen['edgeGeneratedAt'],scored=len(rows),
                tracked=len(frozen['trackerTickers']),baselineLaneCounts=dict(Counter(r['lane'] for r in rows)),
                gateAblations=ablations,negativeEffectivePE=negative,
                negativeEarningsDays=[r['ticker'] for r in rows if r['daysUntilEarnings'] is not None and r['daysUntilEarnings']<0],
                syntheticChecks=dict(negativePEValuationScores=synthetic,
                                     pastEarningsWithOtherwisePassingInputs=past,
                                     qualityAt50And200PctGrowth=quality),
                caveats=['Gate failures overlap; removal counts are not additive.',
                         'Existing 40-name selection and scores retained, including theme-score penalty.',
                         'Cache is a current read, not proven identical to metadata used at scoring; negative-PE footprint is potential exposure.',
                         'Synthetic probes demonstrate semantics, not actual profitable missed trades.',
                         'No future outcomes, transaction costs, probability calibration or threshold optimization.'])
    (HERE/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['# Frozen guard attribution', '',f"Source: {result['sourceGeneratedAt']}; {len(rows)}/{result['tracked']} names scored.", '',
           'One gate removed at a time; all saved scores and other checks retained. Counts are research classifications, not orders or winning trades.', '']
    for lane, data in ablations.items():
        lines += [f'## {lane}', '',f"Baseline passing: {', '.join(data['baseline']) or 'none'}.", '',
                  '| Gate removed | Total passing | Newly passing names |','|---|---:|---|']
        lines += [f"| {x['removedGate']} | {x['totalPassing']} | {', '.join(x['added']) or 'none'} |" for x in data['oneGateRemoved']]
        lines += ['']
    lines += ['## Interpretation limits','',*['- '+c for c in result['caveats']],'']
    (HERE/'gate-attribution.md').write_text('\n'.join(lines))
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true')
    if parser.parse_args().freeze:
        freeze()
    run()
