"""Frozen-input friction diagnosis, never a production friction implementation.

Run from repo root with python3 -m research.friction_proposal --inputs ... --output ...
The literal challenger is a sensitivity, not a recommendation to double-charge
entry costs that the source entryLimit already includes.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from inferno_paper_execution import friction_crossings_for_exit_rule
from inferno_trade_evidence import normalized_outcome
from inferno_scenario_backtest import build_scenario_backtest, stats_block


def finite(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def leg_cost(ticket):
    legs = ticket.get('legs') or []
    if not legs:
        return {'ok': False, 'reason': 'missing-legs'}
    half = mid = natural = 0.0
    implicit = 0
    for leg in legs:
        bid, ask = finite(leg.get('bid')), finite(leg.get('ask'))
        qty = finite(leg.get('quantity', 1))
        multiplier = finite(leg.get('multiplier', 100))
        instruction = str(leg.get('instruction', '')).upper()
        if bid is None or ask is None or bid < 0 or ask < bid:
            return {'ok': False, 'reason': 'missing-or-invalid-quote'}
        if qty is None or qty <= 0 or qty != int(qty) or multiplier != 100:
            return {'ok': False, 'reason': 'unsupported-quantity-or-multiplier'}
        if not instruction.startswith(('BUY', 'SELL')):
            return {'ok': False, 'reason': 'unknown-leg-direction'}
        implicit += 'quantity' not in leg
        sign = 1 if instruction.startswith('BUY') else -1
        half += (ask - bid) / 2 * 100 * qty
        mid += sign * (bid + ask) / 2 * qty
        natural += (ask if sign == 1 else -bid) * qty
    credit = ticket.get('entryCostType') == 'credit'
    return {'ok': True, 'halfSpreadDollars': round(half, 4),
            'mid': round(-mid if credit else mid, 4),
            'natural': round(-natural if credit else natural, 4),
            'quantityDefaultedLegs': implicit}


def diagnose(ticket, source):
    quote = leg_cost(ticket)
    saved_crossings = finite(ticket.get('paperFrictionCrossings'))
    crossings = saved_crossings if saved_crossings is not None else friction_crossings_for_exit_rule(
        ticket.get('exitRule') or ticket.get('campaignExitRule'))
    if crossings not in (1, 2):
        quote = {'ok': False, 'reason': 'unsupported-crossing-count'}
    entry = finite(ticket.get('entryLimit'))
    row = {'source': source, 'ticketId': ticket.get('ticketId'), 'ticker': ticket.get('ticker'),
           'strategy': ticket.get('strategy'), 'tradeDate': ticket.get('tradeDate'),
           'expiration': ticket.get('expiration'), 'closed': (ticket.get('outcome') or {}).get('status') == 'closed',
           'recordedExecution': bool(ticket.get('paperExecution')),
           'quote': quote, 'crossings': crossings, 'crossingsInferred': saved_crossings is None,
           'modeledPerCrossing': finite(ticket.get('estimatedSpreadFrictionPerCrossingDollars')),
           'eventKey': ticket.get('eventId') or f"proxy:{ticket.get('ticker')}:{ticket.get('expiration')}"}
    if not quote['ok']:
        return row
    row['entryAtNatural'] = entry is not None and abs(entry - quote['natural']) <= 0.00011
    row['entryAtMid'] = entry is not None and abs(entry - quote['mid']) <= 0.00011
    old = row['modeledPerCrossing']
    row['halfSpreadToModeled'] = quote['halfSpreadDollars'] / old if old and old > 0 else None
    if row['closed'] and not row['recordedExecution']:
        baseline = normalized_outcome(ticket)
        proposed_total = round(quote['halfSpreadDollars'] * crossings, 4)
        # Reuse the actual downstream evaluator with a copy. Explicit outcome
        # costs still take precedence and are never overwritten.
        changed = {**ticket, 'estimatedTotalSpreadFrictionDollars': proposed_total}
        proposed = normalized_outcome(changed)
        saved_r = finite((ticket.get('outcome') or {}).get('estimatedReturnOnRisk'))
        comparable = baseline['grossR'] is not None and proposed['netREstimate'] is not None
        consistent = saved_r is None or (comparable and abs(saved_r - baseline['grossR']) <= 0.0001)
        row.update(scoreComparable=bool(comparable and consistent), baseline=baseline, literalChallenger=proposed,
                   proposedCampaignCost=proposed_total,
                   isDebitSpread='DEBIT' in str(ticket.get('strategy', '')).upper()
                                 and 'SPREAD' in str(ticket.get('strategy', '')).upper())
        row['rawWinnerSurvivesLiteralCharge'] = (
            baseline['grossPnlDollars'] is not None and baseline['grossPnlDollars'] > 0
            and proposed['netPnlEstimateDollars'] is not None and proposed['netPnlEstimateDollars'] > 0)
    return row


def build(paper, shadow, reducer, scenario):
    sources = {'paper': paper, 'shadow': shadow}
    rows = [diagnose(t, source) for source, payload in sources.items() for t in payload.get('items', [])]
    profiles, summaries = {}, []
    for source, payload in sources.items():
        group = [r for r in rows if r['source'] == source]
        ids = Counter(r['ticketId'] for r in group)
        profiles[source] = {'rows': len(group), 'sourceGeneratedAt': payload.get('generatedAt'),
                            'sourceLastSuccessfulAt': payload.get('lastSuccessfulAt'),
                            'duplicateTicketIds': sum(n > 1 for n in ids.values()),
                            'missingTicketIds': ids.get(None, 0),
                            'closed': sum(r['closed'] for r in group),
                            'completeValidLegQuotes': sum(r['quote']['ok'] for r in group),
                            'quoteFailures': dict(Counter(r['quote'].get('reason') for r in group if not r['quote']['ok'])),
                            'entryAtNatural': sum(bool(r.get('entryAtNatural')) for r in group),
                            'actualExecutionsExcluded': sum(r['recordedExecution'] for r in group)}
        for strategy in sorted({str(r['strategy']) for r in group}):
            same = [r for r in group if str(r['strategy']) == strategy]
            compared = [r for r in same if r.get('halfSpreadToModeled') is not None]
            scored = [r for r in same if r.get('scoreComparable') and ids[r['ticketId']] == 1 and r['ticketId']]
            event_groups = defaultdict(list)
            for r in scored:
                if r['literalChallenger']['netREstimate'] is not None:
                    event_groups[r['eventKey']].append(r['literalChallenger']['netREstimate'])
            summaries.append({'source': source, 'strategy': strategy, 'rows': len(same),
                              'costComparableRows': len(compared),
                              'medianHalfSpreadToModeled': round(statistics.median(r['halfSpreadToModeled'] for r in compared), 4) if compared else None,
                              'closedEstimatesWithQuotes': sum(bool(r.get('baseline')) for r in same),
                              'invalidRiskOrInconsistentReturn': sum(bool(r.get('baseline')) and not r.get('scoreComparable', False) for r in same),
                              'scoredEstimates': len(scored),
                              'entryAtNatural': sum(bool(r.get('entryAtNatural')) for r in same),
                              'raw': stats_block([r['baseline']['grossR'] for r in scored if r['baseline']['grossR'] is not None]),
                              'currentNormalized': stats_block([r['baseline']['netREstimate'] for r in scored if r['baseline']['netREstimate'] is not None]),
                              'literalChargeSensitivity': stats_block([r['literalChallenger']['netREstimate'] for r in scored if r['literalChallenger']['netREstimate'] is not None]),
                              'eventOrProxyGroupSensitivity': stats_block([statistics.mean(v) for v in event_groups.values()]),
                              'proxyGroups': sum(k.startswith('proxy:') for k in event_groups),
                              'rawWinnersSurviving': sum(r['rawWinnerSurvivesLiteralCharge'] for r in scored)})
    baseline = build_scenario_backtest(reducer=reducer, paper_ledger=paper, shadow_ledger=shadow, scenario_evidence=scenario)
    field_only = copy.deepcopy(sources)
    sensitivity = copy.deepcopy(sources)
    for source in sources:
        counts = Counter(t.get('ticketId') for t in sources[source].get('items', []))
        by_id = {r['ticketId']: r for r in rows if r['source'] == source and counts[r['ticketId']] == 1 and r['ticketId']}
        for changed in field_only[source].get('items', []):
            row = by_id.get(changed.get('ticketId'), {})
            if row.get('baseline'):
                changed['estimatedTotalSpreadFrictionDollars'] = row['proposedCampaignCost']
        for changed in sensitivity[source].get('items', []):
            row = by_id.get(changed.get('ticketId'), {})
            if row.get('scoreComparable'):
                changed['outcome'] = {**changed['outcome'], 'estimatedPnl': row['literalChallenger']['netPnlEstimateDollars'],
                                      'estimatedReturnOnRisk': row['literalChallenger']['netREstimate']}
    field_test = build_scenario_backtest(reducer=reducer, paper_ledger=field_only['paper'], shadow_ledger=field_only['shadow'], scenario_evidence=scenario)
    stress = build_scenario_backtest(reducer=reducer, paper_ledger=sensitivity['paper'], shadow_ledger=sensitivity['shadow'], scenario_evidence=scenario)
    return {'researchOnly': True, 'promotable': False, 'authorityChanged': False,
            'liveTradingAllowed': False, 'brokerSubmitAllowed': False,
            'adoptionRecommendation': 'Do not adopt literal extra entry charge; resolve P/L basis and missing exit quotes first.',
            'profiles': profiles, 'strategies': summaries,
            'fieldOnlyBacktestUnchanged': baseline['scorecards'] == field_test['scorecards'],
            'backtestBaseline': baseline, 'backtestLiteralCostSensitivity': stress,
            'rows': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.inputs.parent / 'manifest.json').read_text())
    def read(name):
        raw = (args.inputs / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == manifest['data/' + name]['sha256'], name
        return json.loads(raw)
    result = build(read('inferno_paper_execution_ledger.json'), read('inferno_shadow_evidence.json'),
                   read('inferno_paper_bottleneck_reducer.json'), read('inferno_scenario_evidence.json'))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'comparison.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k in {'profiles', 'strategies', 'fieldOnlyBacktestUnchanged'}}, indent=2))


if __name__ == '__main__':
    main()
