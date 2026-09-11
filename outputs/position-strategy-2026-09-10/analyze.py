"""Reproduce isolated portfolio research; no broker calls or policy writes.

Inputs and generated account analysis stay under ignored data/. Daily prices
are descriptive, unadjusted provider OHLCV, not executable quotes or total returns.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / 'data/portfolio_strategy_2026_09_10'


def money(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def finite(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Nonfinite input')
    return result


def stress_size(nlv, account_loss_fraction, price_decline_fraction):
    nlv, loss, decline = map(finite, (nlv, account_loss_fraction, price_decline_fraction))
    if nlv <= 0 or not 0 < loss <= 1 or not 0 < decline <= 1:
        raise ValueError('Positive NLV and fractions in (0, 1] required')
    return nlv * loss / decline


def call_vertical(positions):
    """Only recognize one unambiguous, equal-quantity standard call vertical."""
    legs = []
    for p in positions:
        if p['assetType'] != 'OPTION':
            continue
        match = re.fullmatch(r'([A-Z]+)\s+(\d{6})C(\d{8})', p['symbol'])
        if not match:
            raise ValueError('Unrecognized option; manual reconciliation required')
        legs.append((p, match[1], match[2], int(match[3]) / 1000))
    if len(legs) != 2:
        raise ValueError('Expected exactly two option legs; no inferred netting')
    legs.sort(key=lambda x: x[3])
    lo, hi = legs
    qty = finite(lo[0]['qty'])
    if lo[1:3] != hi[1:3] or lo[3] >= hi[3] or qty <= 0 or qty != -finite(hi[0]['qty']) or qty != int(qty):
        raise ValueError('Leg identity, direction or quantity mismatch')
    debit = finite(lo[0]['derivedTradePrice']) - finite(hi[0]['derivedTradePrice'])
    width = hi[3] - lo[3]
    if not 0 < debit < width:
        raise ValueError('Not a debit call vertical')
    value = sum(finite(x[0]['markValue']) for x in legs)
    cost = debit * 100 * qty
    return dict(symbol=lo[1], expiry=lo[2], longStrike=lo[3], shortStrike=hi[3],
                quantity=int(qty), assumedMultiplier=100, debit=debit,
                initialRisk=cost, markedValue=value, markedProfit=value-cost,
                maximumPayoff=width*100*qty, maximumProfit=(width-debit)*100*qty,
                breakEven=lo[3]+debit,
                limitation='Standard unadjusted contracts assumed; marks are not a combo quote. Expiration/assignment can create stock exposure.')


def history_frame(row):
    frame = pd.DataFrame(row['candles'])
    frame['session'] = pd.to_datetime(frame['datetime'], utc=True).dt.date
    if frame.session.duplicated().any() or not frame.session.is_monotonic_increasing:
        raise ValueError('Duplicate or unordered daily sessions')
    columns = ['open', 'high', 'low', 'close', 'volume']
    if frame[columns].isna().any().any() or not all(math.isfinite(float(v)) for v in frame[columns].to_numpy().flat):
        raise ValueError('Missing or nonfinite OHLCV')
    if len(frame) < 201 or (frame[['open','high','low','close']] <= 0).any().any():
        raise ValueError('Insufficient history or nonpositive prices')
    if ((frame.high < frame[['open','close','low']].max(axis=1)) | (frame.low > frame[['open','close','high']].min(axis=1)) | (frame.volume < 0)).any():
        raise ValueError('Invalid OHLCV relationships')
    return frame.set_index('session')


def metrics(frame, benchmark):
    if not frame.index.equals(benchmark.index):
        raise ValueError('Benchmark and stock sessions differ; align explicitly before comparing')
    close = frame.close
    last = float(close.iloc[-1])
    tr = pd.concat([frame.high-frame.low, (frame.high-close.shift()).abs(),
                    (frame.low-close.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.tail(14).mean())
    means = {f'sma{n}': float(close.tail(n).mean()) for n in (20, 50, 200)}
    r63 = last / close.iloc[-64] - 1
    b63 = benchmark.close.iloc[-1] / benchmark.close.iloc[-64] - 1
    return dict(close=last, date=str(frame.index[-1]), **means, atr14=atr,
                atrPercent=atr/last*100, extension20ATR=(last-means['sma20'])/atr if atr else None,
                return63Pct=float(r63*100), relative63PctPoints=float((r63-b63)*100),
                prior20High=float(frame.high.iloc[-21:-1].max()),
                prior20Low=float(frame.low.iloc[-21:-1].min()),
                drawdown60Pct=float((last/close.tail(60).max()-1)*100),
                annualizedVol60Pct=float(close.pct_change().tail(60).std(ddof=1)*math.sqrt(252)*100))


def build(folder):
    account = json.loads((folder/'account_snapshot.json').read_text())
    history = json.loads((folder/'price_history.json').read_text())
    if account['brokerSubmitAllowed'] is not False or account['liveTradingAllowed'] is not False:
        raise ValueError('Research-only authority invariant failed')
    nlv, cash = map(finite, (account['netLiquidatingValue'], account['totalCash']))
    positions = account['positions']
    reconcile = cash + sum(finite(p['markValue']) for p in positions) - nlv
    if abs(reconcile) > .02:
        raise ValueError('Account does not reconcile within two cents')
    spread = call_vertical(positions)
    equities = [dict(symbol=p['symbol'], quantity=p['qty'], mark=p['mark'], value=p['markValue'],
                     weightPct=p['markValue']/nlv*100) for p in positions if p['assetType']=='EQUITY']
    frames = {r['symbol']: history_frame(r) for r in history['rows'] if r['status']=='ok'}
    if len(frames) != history['symbolCount'] or history.get('errors'):
        raise ValueError('Missing history rows')
    technical = {}
    for symbol, frame in frames.items():
        benchmark = 'SMH' if symbol in {'ALAB','CRDO'} else 'SPY'
        technical[symbol] = dict(benchmark=benchmark, **metrics(frame,frames[benchmark]))
    equity_value = sum(p['value'] for p in equities)
    # No probabilities; shocks start from current marks and keep cash unchanged.
    stresses = [dict(equityDeclinePct=d*100, loss=money(equity_value*d+spread['markedValue']),
                     lossPct=(equity_value*d+spread['markedValue'])/nlv*100,
                     endingNLV=money(nlv-money(equity_value*d+spread['markedValue']))) for d in (.2,.35,.5)]
    sizing = [dict(accountLossPct=r*100, stockDeclinePct=d*100,
                   positionDollars=stress_size(nlv,r,d), positionPct=r/d*100)
              for r in (.02,.05,.10) for d in (.20,.35,.50)]
    held = [p['symbol'] for p in equities]
    returns = pd.DataFrame({s:frames[s].close.pct_change() for s in held}).dropna().tail(60)
    result = dict(researchOnly=True, promotable=False, authorityChanged=False,
                  brokerSubmitAllowed=False, liveTradingAllowed=False,
                  accountAsOf=account['generatedAt'], historyFetchedAt=history['generatedAt'],
                  priceObservationDates=sorted(set(m['date'] for m in technical.values())),
                  netLiquidatingValue=nlv,cash=cash,equities=equities,spread=spread,
                  reconciliationDifference=reconcile,technical=technical,
                  stresses=stresses,illustrativeSizing=sizing,
                  correlation60=returns.corr().to_dict(),correlationSessions=len(returns),
                  inputHashes={n:hashlib.sha256((folder/n).read_bytes()).hexdigest()
                               for n in ['account_snapshot.json','price_history.json']},
                  limitations=['Daily histories end before latest account marks and ORCL earnings; no actionable entry quotes.',
                               'Price returns exclude dividends; splits/corporate actions not independently audited.',
                               'ATR uses arithmetic mean of 14 true ranges, not Wilder smoothing.',
                               '60-session correlations describe this sample; no tail-risk or predictive validation.',
                               'Sizing fractions are scenarios, not adopted risk constants or approved trade sizes.',
                               'Cash is not confirmed deployable/settled funds; scheduled deposits are not cash.'])
    (folder/'analysis.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    lines = ['# Position and timing evidence — September 10, 2026', '',
             'Research only. No approved tickets, new risk limits, or broker actions.', '',
             f"Account snapshot: {account['generatedAt']}. NLV ${nlv:,.2f}; cash ${cash:,.2f}.",
             f"History fetched {history['generatedAt']}; observations end {result['priceObservationDates']}. These are not tomorrow’s entry prices.", '',
             '| Position | Quantity | Marked value | Account weight |', '|---|---:|---:|---:|']
    lines += [f"| {p['symbol']} | {p['quantity']} | ${p['value']:.2f} | {p['weightPct']:.2f}% |" for p in equities]
    lines += [f"| {spread['symbol']} paired call spread | {spread['quantity']} | ${spread['markedValue']:.2f} | {spread['markedValue']/nlv*100:.2f}% |",
              f'| Cash | — | ${cash:.2f} | {cash/nlv*100:.2f}% |', '',
              f"The {spread['longStrike']}/{spread['shortStrike']} call spread expires September 11. Net debit ${spread['debit']:.2f}; original risk ${spread['initialRisk']:.2f} ({spread['initialRisk']/nlv*100:.2f}% of current NLV). Maximum expiration payoff ${spread['maximumPayoff']:.2f}, maximum profit ${spread['maximumProfit']:.2f}, breakeven ${spread['breakEven']:.2f}, all before fees. Marked open profit is only ${spread['markedProfit']:.2f}, not realized or executable profit.", '',
              '## Existing exposure under simultaneous stress', '',
              'These scenarios make the spread worth zero and shock all four equities together. Cash stays constant. No probability or worst-case guarantee is attached.', '',
              '| Equity decline | Additional loss from current marks | Loss / current NLV | Ending NLV |', '|---|---:|---:|---:|']
    lines += [f"| {s['equityDeclinePct']:.0f}% | ${s['loss']:.2f} | {s['lossPct']:.2f}% | ${s['endingNLV']:.2f} |" for s in stresses]
    lines += ['', '## Position-size scenarios', '',
              'Dollar position = account value × allowed scenario loss fraction ÷ assumed stock decline. This is stress sizing, not a stop-loss guarantee or an optimal allocation. Full loss of stock cost remains possible. Do not add each row: shared factor exposure consumes a shared portfolio budget.', '',
              '| Account loss budget (illustrative) | Stock decline assumption | Position value | Position / account |', '|---|---:|---:|---:|']
    lines += [f"| {s['accountLossPct']:.0f}% | {s['stockDeclinePct']:.0f}% | ${s['positionDollars']:.2f} | {s['positionPct']:.1f}% |" for s in sizing]
    lines += ['', 'A $108 spread requires $2,160 NLV to represent 5%, or $5,400 to represent 2%. Those percentages illustrate contract granularity; they are not new policy limits. A smaller premium alone does not establish a better trade.', '',
              '## Dated timing references', '',
              'SMA levels are context, not established support or purchase limits. Relative return is the 63-session price-return difference in percentage points. SPY is a broad benchmark; SMH is used for ALAB/CRDO. No dividend-adjusted or fundamental valuation claim is implied.', '',
              '| Name | Sep 9 close | SMA20 | SMA50 | SMA200 | ATR14 | 63-session return | Relative return |', '|---|---:|---:|---:|---:|---:|---:|---:|']
    lines += [f"| {s} | {m['close']:.2f} | {m['sma20']:.2f} | {m['sma50']:.2f} | {m['sma200']:.2f} | {m['atr14']:.2f} | {m['return63Pct']:.1f}% | {m['relative63PctPoints']:.1f} pp vs {m['benchmark']} |" for s,m in technical.items()]
    lines += ['', '## Correlation of held shares', '',
              f"Pearson correlation of {len(returns)} matched daily price returns, ending {returns.index[-1]}. This does not measure future downside dependence.", '',
              '| Pair | Correlation |','|---|---:|']
    lines += [f'| {a} / {b} | {returns[a].corr(returns[b]):.3f} |' for i,a in enumerate(held) for b in held[i+1:]]
    lines += ['', '## Method and limitations', '', *['- '+s for s in result['limitations']], '',
              '[Read the strategy and milestone plan](../../docs/POSITION_STRATEGY_RESEARCH_2026-09-10.md).', '']
    (folder/'evidence.md').write_text('\n'.join(lines))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, default=DEFAULT)
    args = parser.parse_args()
    result = build(args.folder)
    print(json.dumps({'status':'ok','symbols':len(result['technical']),
                      'reconciles':abs(result['reconciliationDifference']) < .02,
                      'priceObservationDates':result['priceObservationDates'],
                      'researchOnly':True,'promotable':False}))
