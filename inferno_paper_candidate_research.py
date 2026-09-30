"""Candidate construction and research demotion; no approval or ledger writes."""
from __future__ import annotations
from datetime import datetime
import pandas as pd
from inferno_config import local_now


def answered_reason(item, shadow, family_cache=None):
    """Reuse the delegate's fixed evidence rules without invoking decisions."""
    from inferno_paper_delegate import (shadow_history, family_event_evidence,
        SHADOW_ANSWERED_MIN, SHADOW_ANSWERED_MAX_R, FAMILY_MIN_EVENTS)
    strategy = (item.get('strikePlan') or {}).get('strategy')
    history = shadow_history(shadow, item.get('ticker'), strategy)
    if history['closed'] >= SHADOW_ANSWERED_MIN and history['avgR'] is not None and history['avgR'] <= SHADOW_ANSWERED_MAX_R:
        return 'shadow-answered'
    cache = family_cache if family_cache is not None else {}
    if strategy not in cache:
        cache[strategy] = family_event_evidence(shadow, strategy)
    family = cache[strategy]
    if family['events'] >= FAMILY_MIN_EVENTS and family['ci95'] and family['ci95'][1] < 0:
        return 'family-answered'
    return None


def contract_frame(contracts, side, expiration):
    rows = []
    for c in contracts:
        if c.get('putCall') == side and c.get('expirationDate') == expiration:
            rows.append({**c, 'strike': c.get('strikePrice'), 'contractSymbol': c.get('symbol'),
                         'impliedVolatility': c.get('volatility'), 'openInterest': c.get('openInterest', 0)})
    return pd.DataFrame(rows)


def iron_fly_plan(intent, source):
    """Use the v2 constructor unchanged, at one lot and full bid/ask crossing."""
    from inferno_risk_policy import SCHWAB_OPTIONS_MAX_AGE_HOURS
    from inferno_short_premium_shadow import build_iron_fly
    from inferno_strike_selector import to_leg, build_liquidity_notes, net_greek_summary
    if not source or source.get('status') != 'ok' or source.get('quoteSessionIsRegular') is not True:
        return None, 'usable regular-session Schwab chain required'
    try:
        captured = datetime.fromisoformat(str(source.get('sourceGeneratedAt')).replace('Z', '+00:00'))
        if captured.tzinfo is None or abs((local_now() - captured).total_seconds()) > SCHWAB_OPTIONS_MAX_AGE_HOURS * 3600:
            return None, 'Schwab chain observation is stale or undated'
        earnings = datetime.fromisoformat(str(intent['nextEarnings'])[:10]).date()
        if not 1 <= (earnings - captured.date()).days <= 7:
            return None, 'earnings must be 1-7 days after capture'
        spot = float(source['underlyingPrice'])
    except (KeyError, ValueError, TypeError):
        return None, 'missing source timestamp, earnings date or underlying'
    fly, reason = build_iron_fly(source.get('contracts') or [], spot, earnings, captured.date())
    if not fly:
        return None, reason
    if fly['maxLossDollars'] <= 0:
        return None, 'nonpositive maximum loss'
    legs = []
    for name, instruction, side in [('shortCall','SELL_TO_OPEN','CALL'), ('longCall','BUY_TO_OPEN','CALL'),
                                    ('shortPut','SELL_TO_OPEN','PUT'), ('longPut','BUY_TO_OPEN','PUT')]:
        frame = contract_frame(source['contracts'], side, fly['expiration'])
        matches = frame[frame['strike'] == fly['strikes'][name]]
        if matches.empty:
            return None, 'selected leg missing from source chain'
        legs.append(to_leg(matches.iloc[0], instruction, side, fly['expiration'], spot))
    if any(not leg.symbol or leg.symbol == 'nan' for leg in legs):
        return None, 'selected leg has no contract identity'
    return {'strategy': 'SHORT_PREMIUM_DEFINED', 'structure': 'IRON_FLY', 'contracts': 1,
        'direction': 'defined-risk-premium', 'expiration': fly['expiration'],
        'legs': [leg.as_dict() for leg in legs], 'estimatedCredit': fly['entryCredit'],
        'estimatedMaxLoss': fly['maxLossDollars'], 'estimatedMaxProfit': round(fly['entryCredit'] * 100, 2),
        'lowerBreakEven': fly['atmStrike'] - fly['entryCredit'],
        'upperBreakEven': fly['atmStrike'] + fly['entryCredit'],
        'shortPremiumDefined': True, 'arm': 'SHORT_PREMIUM_DEFINED',
        'constructionSource': 'inferno_short_premium_shadow.build_iron_fly',
        'sourceGeneratedAt': source['sourceGeneratedAt'],
        'impliedMovePct': fly['impliedMovePct'], 'entryFrictionDollars': fly['entryFrictionDollars'],
        'greekSummary': net_greek_summary(legs), 'liquidityNotes': build_liquidity_notes(legs)}, ''


def fit_size_only(item, generated_at):
    """Try smaller constructions only after a size-only failure; rerun every gate."""
    from inferno_strike_selector import is_size_cap_block, vertical_call_plan
    from inferno_risk_policy import evaluate_strike_item
    verdict = item.get('riskVerdict') or {}
    blocks = verdict.get('blocks') or []
    if not blocks or not all(is_size_cap_block(b) for b in blocks):
        return item
    original = item.get('strikePlan') or {}
    candidates = []
    quantity = original.get('contracts', 1)
    if isinstance(quantity, (int, float)) and quantity > 1:
        one = dict(original, contracts=1)
        for key in ('estimatedMaxLoss', 'estimatedMaxProfit'):
            if isinstance(one.get(key), (int, float)):
                one[key] /= quantity
        candidates.append(one)
    # The existing vertical constructor already chooses the adjacent strike.
    # Reprice narrower available verticals from the SAME chain and direction.
    if original.get('strategy') == 'CALL_DEBIT_SPREAD':
        source = item.get('schwabOptions') or {}
        calls = contract_frame(source.get('contracts') or [], 'CALL', original.get('expiration'))
        if not calls.empty:
            for strike in sorted(calls['strike'].dropna().unique()):
                candidate = vertical_call_plan(item, original['expiration'], calls, long_target=strike)
                if candidate and 0 < candidate.get('width', 0) < original.get('width', 0):
                    candidates.append(candidate)
    attempts = []
    for candidate in candidates:
        if candidate.get('estimatedMaxLoss', float('inf')) >= original.get('estimatedMaxLoss', 0):
            continue
        proposed = {**item, 'strikePlan': candidate}
        check = evaluate_strike_item(proposed, strike_plan_generated_at=generated_at, mode='paper').as_dict()
        attempts.append({'maxLoss': candidate.get('estimatedMaxLoss'), 'blocks': check['blocks']})
        if check['passed'] and not candidate.get('liquidityNotes'):
            return {**proposed, 'riskVerdict': check, 'sizeFit': {'originalPlan': original, 'attempts': attempts},
                    'requiresDelegateApproval': True}
    return {**item, 'sizeFit': {'attempts': attempts, 'result': 'no smaller gate-passing construction'}}
