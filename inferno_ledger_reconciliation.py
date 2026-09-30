"""Read-only crosswalk of frozen ledgers; never chooses or writes a trade outcome."""
from __future__ import annotations
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def digest(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def identities(row):
    return {str(x) for x in [row.get('ticketId'), *(row.get('mergedDuplicateTicketIds') or [])] if x}


def terms(row):
    return (row.get('tradeDate'), row.get('ticker'), row.get('eventId'), row.get('strategy'), row.get('expiration'),
            row.get('contracts') or (row.get('paperExecution') or {}).get('contracts'),
            tuple((x.get('symbol'), x.get('instruction') or x.get('action'), x.get('ratio') or x.get('quantity', 1)) for x in row.get('legs', [])))


def reconcile(mac, cloud):
    local = mac.get('items', []); remote = cloud.get('items', []); matched = set(); rows = []
    for i, left in enumerate(local):
        ids = identities(left)
        exact = [j for j, right in enumerate(remote) if ids & identities(right)]
        semantic = [j for j, right in enumerate(remote) if terms(left) == terms(right)] if not exact else []
        matches = exact or semantic
        if not matches:
            rows.append({'classification': 'mac-only', 'macIndex': i, 'macId': left.get('ticketId'), 'macSha256': digest(left)})
        for j in matches:
            right = remote[j]; matched.add(j)
            same = left == right
            # Different lifecycle, fill or decision facts are conflicts even when contract terms agree.
            lifecycle = ('status', 'outcome', 'paperExecution', 'approvalStatus', 'importedFillKeys', 'blockReasons')
            compatible = terms(left) == terms(right) and all(left.get(k) == right.get(k) for k in lifecycle)
            kind = 'identical' if same else ('refresh-only-duplicate' if compatible else 'conflicted')
            rows.append({'classification': kind, 'match': 'ticketId-or-alias' if exact else 'semantic-terms',
                         'macIndex': i, 'cloudIndex': j, 'macId': left.get('ticketId'), 'cloudId': right.get('ticketId'),
                         'macSha256': digest(left), 'cloudSha256': digest(right),
                         'differentFields': sorted(k for k in set(left) | set(right) if left.get(k) != right.get(k))})
    rows += [{'classification': 'cloud-only', 'cloudIndex': j, 'cloudId': r.get('ticketId'), 'cloudSha256': digest(r)}
             for j, r in enumerate(remote) if j not in matched]
    return {'researchOnly': True, 'authorityChanged': False, 'liveTradingAllowed': False, 'brokerSubmitAllowed': False,
            'sourceCounts': {'mac': len(local), 'cloud': len(remote)}, 'classes': dict(Counter(r['classification'] for r in rows)),
            'rows': rows, 'canonicalDisposition': 'Mac source retained byte-for-byte; all cloud rows preserved in frozen archive only.',
            'conflictDisposition': 'Quarantined for human review; no status, fill, approval or promotion inferred.',
            'rowsImported': 0, 'qualifiedIncreaseFromMigration': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    ledger = 'data/inferno_paper_execution_ledger.json'
    report = reconcile(json.loads((args.archive/'mac'/ledger).read_text()), json.loads((args.archive/'cloud'/ledger).read_text()))
    # Queue absence is distinct from an observed empty queue.
    queues = {}
    for host in ('mac', 'cloud'):
        path = args.archive/host/'data/inferno_approval_queue.json'
        queues[host] = {'status': 'captured', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'items': json.loads(path.read_text()).get('items', [])} if path.exists() else {'status': 'missing', 'items': None}
    report['approvalCrosswalk'] = {'sources': queues, 'disposition': 'Retain exact Mac requests/tokens; missing cloud queue cannot authorize old cloud replies.'}
    (args.archive/'reconciliation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in ('sourceCounts','classes','rowsImported','qualifiedIncreaseFromMigration')}, indent=2))


if __name__ == '__main__':
    main()
