"""Exact-construction paper approval routing; no decisions or relaxed gates."""
from __future__ import annotations
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta

APPROVAL_REASONS = {'human approval missing', 'human approval is missing',
                    'human approval still required', 'human reviewer rejected the name'}


def event_date(item, generated_at=None):
    stamp = item.get('generatedAt') or generated_at
    event = item.get('nextEarnings') or item.get('eventDate')
    if not event:
        try:
            event = (datetime.fromisoformat(str(stamp)).date() + timedelta(days=int(item['daysUntilEarnings']))).isoformat()
        except (ValueError, TypeError, KeyError):
            event = str(stamp or '')[:10]
    return str(event)[:10]


def route_key(item, generated_at=None):
    plan = item.get('strikePlan') or {}
    identity = {'ticker': str(item.get('ticker', '')).upper(), 'event': event_date(item, generated_at),
                'strategy': plan.get('strategy'), 'expiration': plan.get('expiration'),
                'legs': plan.get('legs'), 'maxLoss': plan.get('estimatedMaxLoss'),
                'debit': plan.get('estimatedDebit'), 'credit': plan.get('estimatedCredit'),
                'family': item.get('paperVariantFamily') or plan.get('variantFamily'),
                'arm': item.get('arm')}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()


def apply_route_approval(item, queue, generated_at):
    """Only the exact priced construction can inherit its own decision."""
    result = deepcopy(item)
    key = route_key(item, generated_at)
    matches = [q for q in queue.get('items', []) if q.get('approvalRouteKey') == key]
    approved = matches[0] if len(matches) == 1 else {}
    status = approved.get('approvalStatus', 'pending')
    blocks = [b for b in result.get('intentBlocks', []) if str(b).strip().lower() not in APPROVAL_REASONS]
    if status == 'rejected':
        blocks.append('human reviewer rejected the name')
    if status != 'approved':
        blocks.append('human approval still required')
    result.update(approvalRouteKey=key, approvalToken=approved.get('approvalToken'),
                  approvalStatus=status, requiresDelegateApproval=True,
                  intentBlocks=blocks, intentStatus='blocked' if blocks else 'approval-ready')
    return result


def queue_from_entries(entries, previous, generated_at):
    """Publish candidates only; decisions survive only an identical construction."""
    from inferno_approval_queue import ensure_queue_tokens
    previous_by_key = {q.get('approvalRouteKey'): q for q in previous.get('items', []) if q.get('approvalRouteKey')}
    rows = {}
    for entry in entries:
        candidate = entry.get('approvalCandidate') or {}
        key = entry.get('approvalRouteKey')
        if not key or not candidate.get('ok') or not entry.get('legs'):
            continue
        old = previous_by_key.get(key) or {}
        rows[key] = {'ticker': entry['ticker'], 'ticketId': entry['ticketId'],
            'approvalRouteKey': key, 'approvalScope': 'exact-paper-construction',
            'strategy': entry['strategy'], 'setupRec': entry['strategy'],
            'maxLoss': entry.get('estimatedMaxLoss'), 'estimatedMaxLoss': entry.get('estimatedMaxLoss'),
            'family': entry.get('paperVariantFamily') or entry['strategy'],
            'paperVariantFamily': entry.get('paperVariantFamily'), 'arm': entry.get('arm'),
            'primaryRoute': entry['strategy'], 'daysUntilEarnings': entry.get('daysUntilEarnings'),
            'nextEarnings': event_date(candidate, entry.get('sourceStrikePlanGeneratedAt')),
            'expiration': entry.get('expiration'), 'estimatedMaxProfit': entry.get('estimatedMaxProfit'),
            'readiness': candidate.get('readiness'),
            'sourceStrikePlanGeneratedAt': entry.get('sourceStrikePlanGeneratedAt'),
            'generatedAt': old.get('generatedAt') or generated_at,
            'approvalStatus': old.get('approvalStatus') or 'pending',
            'paperOnly': True, 'liveTradingAllowed': False, 'brokerSubmitAllowed': False,
            **{k: old[k] for k in ('approvalToken', 'decisionAt', 'pendingSince', 'expirationReason') if k in old}}
    # Unpriced legacy names remain visible, but never supply a variant decision.
    tickers = {r['ticker'] for r in rows.values()}
    legacy = [q for q in previous.get('items', []) if not q.get('approvalRouteKey') and q.get('ticker') not in tickers]
    return ensure_queue_tokens({'generatedAt': generated_at, 'owner': 'mac', 'items': legacy + list(rows.values())})


def delegate_candidate(queue_item, ledger):
    """Resolve a queue item to its source entry and all unchanged entry blockers."""
    key = queue_item.get('approvalRouteKey')
    matches = [e for e in ledger.get('items', []) if e.get('approvalRouteKey') == key
               and e.get('ticketId') == queue_item.get('ticketId')]
    if len(matches) != 1:
        return None, None
    entry = matches[0]
    candidate = deepcopy(entry.get('approvalCandidate') or {})
    stamp = entry.get('sourceStrikePlanGeneratedAt')
    if route_key(candidate, stamp) != key:
        return None, None
    candidate['riskVerdict'] = {**(entry.get('riskVerdict') or {}),
                               'blocks': list(entry.get('blockReasons') or [])}
    return candidate, stamp
