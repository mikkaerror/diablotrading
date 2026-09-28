"""Shared exposure and input identities for non-executable research experiments."""
from __future__ import annotations
import hashlib
import json
from typing import Any
from inferno_decision_archive import identity

SHADOW_PROTOCOL = 'hold-to-expiration-intrinsic-v1'
FAST_PROTOCOL = 'next-session-quoted-liquidation-v1'


def contract_key(row: dict) -> str | None:
    key, basis = identity(row, '')
    return key if basis == 'same-contract-exposure-not-independent-event' else None


def experiment_key(row: dict, protocol: str) -> str | None:
    case = contract_key(row)
    return hashlib.sha256(f'{case}|{protocol}'.encode()).hexdigest() if case else None


def entry_features(item: dict) -> dict[str, Any]:
    """Freeze what was actually supplied; missing features stay absent/unknown."""
    options = item.get('schwabOptions') or {}
    keys = ('ivRank', 'ivRankChange', 'atrPercent', 'readiness', 'priorityScore', 'daysUntilEarnings')
    quote_keys = ('quoteAsOf', 'quoteSession', 'atmSpreadPct', 'atmWindowMedianSpreadPct',
                  'paperFillFrictionPct', 'impliedMovePct', 'avgImpliedVolatility')
    return {'version': 1, 'features': {k: item.get(k) for k in keys},
            'optionContext': {k: options.get(k) for k in quote_keys},
            'sourceGeneratedAt': item.get('generatedAt'),
            'basis': 'as supplied at experiment creation; not backfilled'}


def input_key(row: dict) -> str | None:
    """Same contracts, prices and quote observations are the same fast input.

    Generated report dates and trade dates cannot manufacture fresh evidence.
    Actual quote timestamps distinguish later independent observations.
    """
    case = contract_key(row)
    if not case:
        return None
    legs = []
    for leg in row.get('legs') or []:
        legs.append({k: leg.get(k) for k in ('symbol','instruction','quantity','bid','ask','mid','price',
                                           'quoteTime','quoteTimeInLong','tradeTime','tradeTimeInLong')})
    payload = [case, row.get('entryLimit'), row.get('underlyingPrice'),
               sorted(legs,key=lambda x: str(x['symbol'])),
               ((row.get('entryFeatureSnapshot') or {}).get('optionContext') or {}).get('quoteAsOf')]
    return hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()


def novel_fast_entries(existing: list[dict], proposed: list[dict]) -> tuple[list[dict], int]:
    seen_ids = {r.get('ticketId') for r in existing}
    seen_inputs = {input_key(r) for r in existing} - {None}
    accepted, suppressed = [], 0
    for row in proposed:
        key = input_key(row)
        if row.get('ticketId') in seen_ids or key is not None and key in seen_inputs:
            suppressed += 1
            continue
        accepted.append(row); seen_ids.add(row.get('ticketId'))
        if key: seen_inputs.add(key)
    return accepted, suppressed
