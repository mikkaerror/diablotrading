"""Offline full-universe comparison using fixed public research inputs."""
import ast
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from inferno_tos_formula_math import watchlist_technical_research_from_pulse

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
FUNCTIONS={'clamp','number','category_for_ticker','market_context_row','confirmation_score',
           'watchlist_technical_research','tracker_timing_score','quality_score',
           'valuation_risk_score','edge_score','classify_lane',
           'earnings_timing_context','valuation_pe_context'}

def load(source):
    tree=ast.parse(source)
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in FUNCTIONS
           or isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in
             {'TECH_SHOVEL_CATEGORIES','INDUSTRY_CATEGORY_KEYWORDS'} for t in n.targets)]
    ns={'Any':Any,'math':math,'watchlist_technical_research_from_pulse':watchlist_technical_research_from_pulse}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'isolated-edge-source','exec'),ns)
    return ns

def run():
    frozen=json.loads((HERE/'frozen-inputs.json').read_text())
    baseline=load(frozen['baselineSource'])
    revised=load((ROOT/'inferno_edge_research.py').read_text())
    rows=[]
    for row in frozen['rows']:
        metadata=frozen['cache']['tickers'].get(row['ticker'],{})
        category=baseline['category_for_ticker'](row['ticker'],metadata)
        old=baseline['edge_score'](row,metadata,category)
        new=revised['edge_score'](row,metadata,category)
        old_lane=baseline['classify_lane'](row,old,category)
        new_lane=revised['classify_lane'](row,new,category)
        assert new['edgeScore']<=old['edgeScore'],row['ticker']
        rows.append(dict(ticker=row['ticker'],metadataAvailable=bool(metadata),
                         oldEdge=old['edgeScore'],newEdge=new['edgeScore'],
                         oldLane=old_lane,newLane=new_lane,
                         pe=new['valuationInputs']['pe'],earnings=new['earningsTiming']))
    report=dict(researchOnly=True,promotable=False,authorityChanged=False,
                sourceAsOf=frozen['generatedAt'],count=len(rows),
                metadataMissing=sum(not r['metadataAvailable'] for r in rows),
                changedScores=[r for r in rows if r['oldEdge']!=r['newEdge']],
                changedLanes=[r for r in rows if r['oldLane']!=r['newLane']],
                before=dict(Counter(r['oldLane'] for r in rows)),
                after=dict(Counter(r['newLane'] for r in rows)),rows=rows,
                caveat='Fixed cache/row comparison, not historical reconstruction or fresh fundamentals. Missing metadata stays absent. Full-universe scoring here does not change production selection or eligibility.')
    (HERE/'impact.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},indent=2))

if __name__=='__main__':run()
