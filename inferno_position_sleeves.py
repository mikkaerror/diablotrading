"""Reporting-only sleeve attribution. Never infers membership from a score."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SLEEVES = {'holds', 'core', 'conviction', 'options'}
SOURCES = ('data/operator_long_term_holds.json', 'research/conviction_plan_draft.json',
           'coordination/operator_acks/2026-09-30_conviction_plan_signoff.json',
           'data/operator_position_sleeves.json')


def load_context(root=ROOT):
    payloads, hashes = {}, {}
    for name in SOURCES:
        try:
            raw = (root / name).read_bytes()
            payloads[name] = json.loads(raw)
            hashes[name] = hashlib.sha256(raw).hexdigest()
        except (OSError, ValueError):
            payloads[name] = {}
            hashes[name] = None
    return {'holds': payloads[SOURCES[0]], 'plan': payloads[SOURCES[1]],
            'ack': payloads[SOURCES[2]], 'assignments': payloads[SOURCES[3]], 'sourceHashes': hashes}


def sleeve_tag(position, context, as_of=None):
    symbol = str(position.get('symbol') or '').strip().upper()
    asset = str(position.get('assetType') or '').upper()
    source, sleeve, status = None, None, 'unclassified'
    # Options on an operator hold belong to options, never to its share sleeve.
    if asset == 'OPTION' or re.fullmatch(r'[A-Z.]+\s*\d{6}[CP]\d{8}', symbol):
        sleeve, source = 'options', 'broker instrument type/contract symbol'
    elif symbol in {str(s).upper() for s in context.get('holds', {}).get('symbols', [])}:
        sleeve, source = 'holds', SOURCES[0]
    else:
        matching = []
        for entry in context.get('assignments', {}).get('positions', []):
            if str(entry.get('symbol', '')).upper() != symbol:
                continue
            # Explicit effective dates prevent today's reassignment being
            # silently backfilled over a historical month.
            start, end = entry.get('effectiveFrom'), entry.get('effectiveUntil')
            if not as_of or not start or str(as_of)[:10] < start:
                continue
            if end and str(as_of)[:10] >= end:
                continue
            matching.append(entry)
        if matching:
            if len(matching) == 1 and matching[0].get('sleeve') in SLEEVES and matching[0].get('source'):
                sleeve, source = matching[0]['sleeve'], matching[0]['source']
            else:
                status = 'conflicted'
        else:
            ack, plan = context.get('ack', {}), context.get('plan', {})
            if (ack.get('active') is True and ack.get('operator') == 'Mikka'
                and 'sleeveTargets' in ack.get('signed', [])
                and as_of and str(as_of)[:10] >= str(ack.get('signedAt') or '9999')[:10]
                and symbol and symbol == str(plan.get('coreVehicle') or '').upper()):
                sleeve, source = 'core', SOURCES[2] + ' / ' + SOURCES[1]
    return {'sleeve': sleeve, 'sleeveStatus': 'classified' if sleeve else status,
            'sleeveSource': source, 'sleeveAsOf': as_of,
            'sleeveSourceHashes': context.get('sourceHashes', {})}


def save_history(report, root=ROOT):
    """Preserve each distinct source observation/classification for monthly joins.

    No historical return is computed; missing fee/cash-flow data stays missing.
    Same observation and mapping deduplicates regardless of refresh timestamp.
    """
    if not report.get('ok'):
        return
    source_at = report.get('schwabAccountGeneratedAt') or report.get('statementGeneratedAt')
    if not source_at:
        return
    rows = [{key: p.get(key) for key in ('symbol', 'assetType', 'qty', 'markValue',
              'plOpen', 'sleeve', 'sleeveStatus', 'sleeveSource', 'sleeveAsOf', 'sleeveSourceHashes')}
            for p in report.get('positions', [])]
    packet = {'sourceGeneratedAt': source_at, 'accountSuffix': report.get('matchedSuffix'),
              'accountDataSource': report.get('accountDataSource'), 'evidenceType': 'live',
              'researchOnly': True, 'authorityChanged': False, 'positions': rows}
    content = json.dumps(packet, sort_keys=True, indent=2) + '\n'
    key = hashlib.sha256(content.encode()).hexdigest()
    target = root / 'data/position_sleeve_history' / (key + '.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_text() != content:
            raise ValueError('Sleeve history content mismatch')
    else:
        from inferno_io import atomic_write_text
        atomic_write_text(target, content)
