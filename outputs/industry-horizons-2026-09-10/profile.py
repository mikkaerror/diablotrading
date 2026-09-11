"""Read-only, reproducible coverage audit. Never imports production modules."""
import ast
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ASOF = datetime.fromisoformat('2026-09-10T19:46:50-06:00')
NAMES = ['latest_snapshot', 'inferno_tracker_registry', 'inferno_tracker_taxonomy',
         'inferno_edge_research', 'inferno_conviction_research', 'inferno_edge_metadata_cache']
PROTECTED = ['inferno_edge_research.py', 'inferno_conviction_research.py',
             'inferno_risk_policy.py', 'inferno_config.py', 'inferno_authority_controller.py',
             'inferno_capital_allocator.py', 'inferno_paper_execution.py',
             'inferno_score_calibration.py', 'inferno_strategy_lab.py', 'inferno_expected_move_ledger.py']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def freeze():
    # Retain research fields only. Do not archive account/holdings details.
    frozen = {'asOf': ASOF.isoformat(), 'inputHashes': {}, 'inputGeneratedAt': {},
              'protectedHashes': {f: sha(ROOT / f) for f in PROTECTED}}
    for name in NAMES:
        p = ROOT / 'data' / (name + '.json')
        d = json.loads(p.read_text())
        frozen['inputHashes'][name] = sha(p)
        frozen['inputGeneratedAt'][name] = d.get('generatedAt')
        if name == 'latest_snapshot':
            frozen[name] = {'rows': [{k: r.get(k) for k in ['ticker','readiness','longTermScore','daysUntilEarnings']} for r in d['rows']]}
        elif name == 'inferno_tracker_registry':
            frozen[name] = {'entries': [{k: r.get(k) for k in ['ticker','taxonomy']} for r in d['entries']]}
        elif name == 'inferno_edge_metadata_cache':
            frozen[name] = {'tickers': {t: {k: r.get(k) for k in ['sector','industry','source','fetchedAt','revenueGrowth']} for t,r in d['tickers'].items()}}
        elif name in ['inferno_conviction_research','inferno_edge_research']:
            frozen[name] = {'ranked': [{k:r.get(k) for k in ['ticker','category','sector','industry']} for r in d['ranked']]}
        else:
            frozen[name] = {'entries': d['entries']}
    tree = ast.parse((ROOT / 'inferno_edge_research.py').read_text())
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ['TECH_SHOVEL_CATEGORIES','INDUSTRY_CATEGORY_KEYWORDS']:
            constants[node.targets[0].id] = ast.literal_eval(node.value)
    # JSON representation of the existing taxonomy, not a new classification rule.
    for config in constants['TECH_SHOVEL_CATEGORIES'].values():
        config['tickers'] = sorted(config['tickers'])
    frozen['existingCategoryRules'] = constants
    (HERE / 'frozen-inputs.json').write_text(json.dumps(frozen, indent=2)+'\n')

def profile():
    f = json.loads((HERE / 'frozen-inputs.json').read_text())
    rows = f['latest_snapshot']['rows']
    reg = f['inferno_tracker_registry']['entries']
    edge = f['inferno_edge_research']['ranked']
    conv = f['inferno_conviction_research']['ranked']
    tax = f['inferno_tracker_taxonomy']['entries']
    cache = f['inferno_edge_metadata_cache']['tickers']
    sets = {n: {r['ticker'] for r in rs} for n,rs in [('tracker',rows),('registry',reg),('edge',edge),('conviction',conv),('taxonomy',tax)]}
    assert all(len(rs)==len(sets[n]) for n,rs in [('tracker',rows),('registry',reg),('edge',edge),('conviction',conv),('taxonomy',tax)])
    assert sets['tracker']==sets['registry']==sets['conviction']==sets['taxonomy']
    assert sets['edge'] <= sets['tracker']
    top40 = sorted(rows, key=lambda r: (-float(r.get('readiness') or 0),-float(r.get('longTermScore') or 0),float(r.get('daysUntilEarnings') if r.get('daysUntilEarnings') is not None else 999)))[:40]
    assert {r['ticker'] for r in top40} == sets['edge']
    def category(t, r):
        rules=f['existingCategoryRules']
        for name,c in rules['TECH_SHOVEL_CATEGORIES'].items():
            if t in c['tickers']: return name
        label=(str(r.get('sector',''))+' '+str(r.get('industry',''))).lower()
        for keyword,name in rules['INDUSTRY_CATEGORY_KEYWORDS']:
            if keyword in label: return name
        return 'Unclassified'
    taxmap={r['ticker']:r for r in tax}
    regmap={r['ticker']:r for r in reg}
    convmap={r['ticker']:r for r in conv}
    records=[]
    for t in sorted(sets['tracker']):
        c=cache.get(t,{})
        age=(ASOF-datetime.fromisoformat(c['fetchedAt'])).total_seconds()/86400 if c.get('fetchedAt') else None
        records.append({'ticker':t,'edgeScored':t in sets['edge'],
            'registryTheme':regmap[t]['taxonomy']['category'],'convictionTheme':convmap[t]['category'],
            'sector':taxmap[t]['sector'],'industry':taxmap[t]['industry'],
            'referenceExposure':taxmap[t]['economicExposure'],
            'existingClassifierOnReference':category(t,taxmap[t]),
            'metadataPresent':t in cache,'metadataAgeDays':round(age,2) if age is not None else None,
            'cachedRevenueGrowth':c.get('revenueGrowth')})
    result={'asOf':f['asOf'],'sourceGeneratedAt':f['inputGeneratedAt'],
       'counts':{'tracker':len(rows),'edgeScored':len(edge),'convictionScored':len(conv),
         'registryThemeMapped':sum(r['taxonomy']['category']!='Unclassified' for r in reg),
         'convictionThemeMapped':sum(r['category']!='Unclassified' for r in conv),
         'edgeThemeMapped':sum(r['category']!='Unclassified' for r in edge),
         'metadataPresent':sum(r['metadataPresent'] for r in records),
         'metadataMissing':sum(not r['metadataPresent'] for r in records),
         'metadataOlderThan14Days':sum(r['metadataAgeDays'] is not None and r['metadataAgeDays']>14 for r in records),
         'existingClassifierMappedUsingFullReference':sum(r['existingClassifierOnReference']!='Unclassified' for r in records)},
       'sectorCounts':dict(sorted(Counter(r['sector'] for r in records).items())),
       'reproducedTop40Selection':True,'uniqueTickerGrain':True,
       'caveats':['Snapshots have different generation times; registry and later conviction categories are not assumed to be synchronized.',
         'Reference taxonomy is provider metadata, not issuer-verified revenue exposure.',
         'Counterfactual labels do not change scores, risk constants, tracker eligibility or authority.',
         'Missing/stale edge metadata does not prove every downstream consumer uses it.'],
       'records':records}
    (HERE/'coverage-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='records'},indent=2))

if __name__ == '__main__':
    import sys
    if '--freeze' in sys.argv: freeze()
    profile()
