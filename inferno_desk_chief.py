"""Desk Chief: operational oversight, accountable assignments and fixed acceptance.

Trading authority is outside this role. Report construction never executes a
worker, decides a ticket, sends mail, or changes another service's schedule.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from inferno_config import ROOT, local_now
from inferno_io import atomic_write_json, atomic_write_text

STAGE = 'desk-chief-operations-only'
REGISTRY = 'coordination/desk_roles.json'
MANDATE = 'coordination/operator_acks/2026-09-30_desk_chief.json'
STATE = 'data/inferno_desk_chief_state.json'
REPORT = 'data/inferno_desk_chief.json'
TEXT = 'reports/desk_chief_latest.txt'
TERMINAL = {'done', 'completed', 'cancelled', 'canceled'}


def read(root, name):
    path = Path(root) / name
    try:
        value = json.loads(path.read_text())
        return value, None
    except (OSError, ValueError) as exc:
        return {}, f'{type(exc).__name__}: unavailable or malformed {name}'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def age_hours(stamp, now):
    try:
        when = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
        if when.tzinfo is None:
            return None
        value = (now - when).total_seconds() / 3600
        return value if value >= 0 else None
    except (TypeError, ValueError):
        return None


def verification_files(root):
    """Bind verification to executable inputs, including uncommitted source."""
    root = Path(root)
    files = set(root.glob('*.py')) | set(root.glob('*.sh')) | set(root.glob('requirements*.txt'))
    for folder, suffix in [('tests', '*.py'), ('scripts', '*.sh'), ('.github/workflows', '*.yml'), ('research', '*.json')]:
        files.update((root / folder).rglob(suffix))
    files.update(root / x for x in (REGISTRY, MANDATE,
        'data/operator_long_term_holds.json', 'outputs/position-strategy-2026-09-10/analyze.py'))
    return sorted(p for p in files if p.is_file())


def code_fingerprint(root):
    root = Path(root)
    return digest([(str(p.relative_to(root)), hashlib.sha256(p.read_bytes()).hexdigest())
                   for p in verification_files(root)])


def safety(root, now):
    mandate, error = read(root, MANDATE)
    if not isinstance(mandate, dict):
        mandate, error = {}, 'Invalid mandate shape'
    reasons = []
    if error or mandate.get('active') is not True or mandate.get('scope') != 'desk-operations-only':
        reasons.append('Operational mandate missing, invalid or inactive')
    hashes = mandate.get('protectedSources') or {}
    if not isinstance(hashes, dict):
        hashes = {}
    if not hashes:
        reasons.append('Protected-source baseline missing')
    for name, expected in hashes.items():
        path = Path(root) / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            reasons.append(f'Protected source changed: {name}')
    authority, error = read(root, 'data/inferno_authority_manifest.json')
    if not isinstance(authority, dict):
        authority, error = {}, 'Invalid authority shape'
    decision = authority.get('decision') or {}
    if not isinstance(decision, dict):
        decision = {}
    age = age_hours(authority.get('generatedAt'), now)
    if error or age is None or age > 36:
        reasons.append('Current authority evidence unavailable or stale')
    if not (decision.get('liveTradingAllowed') is False and decision.get('brokerSubmitAllowed') is False
            and decision.get('brokerAdapterMode') == 'OFF'
            and 'submit_live_order' in (decision.get('blockedActions') or {})):
        reasons.append('Research-only broker boundary not verified')
    if os.environ.get('BROKER_ADAPTER_MODE', 'OFF') != 'OFF':
        reasons.append('Runtime broker adapter is not OFF')
    return {'passed': not reasons, 'reasons': reasons, 'mandateScope': mandate.get('scope')}


def role_status(role, source, error, now, root):
    status, reason = 'verified', 'Fresh output observed; strategy success is evaluated separately'
    stamp = source.get('lastSuccessfulAt') or source.get('generatedAt')
    check = role.get('check')
    if check == 'mail':
        sent = source.get('sentByDate') or {}
        latest = max(sent, default='')
        delivery = sent.get(latest, {})
        stamp = delivery.get('sentAt')
        if delivery.get('failedSteps'):
            status, reason = 'attention', 'Delivered with failed steps: ' + ', '.join(delivery['failedSteps'])
    if role.get('dueAfter') and now.date().isoformat() < role['dueAfter'] and error:
        return 'not-due', 'First required delivery: ' + role['dueAfter'], None
    age = age_hours(stamp, now)
    if error:
        # An external task is not failed merely because it cannot write here.
        return 'unverified' if check == 'external' else 'missing', error, age
    if age is None:
        return 'unverified', 'Missing, future or timezone-free successful observation timestamp', age
    if age > role['maxAgeHours']:
        return 'stale', f'Observation exceeds operational SLA {role["maxAgeHours"]}h', age
    if source.get('ok') is False or source.get('status') in {'failed', 'error'}:
        status, reason = 'attention', 'Worker reports failure; a new timestamp is not success'
    if check == 'publication' and (source.get('publication') or {}).get('status') not in {'published', 'unchanged'}:
        status, reason = 'attention', 'Canonical publication has no successful receipt'
    if check == 'account' and (source.get('ok') is not True or source.get('brokerReadOnly') is not True):
        status, reason = 'attention', 'Read-only account sync not verified'
    if check == 'cloud' and source.get('verdict') not in {'healthy', 'ready', 'ok'}:
        status, reason = 'attention', 'Cloud audit: ' + str(source.get('verdict'))
    if check == 'efficiency' and (source.get('economics') or {}).get('verdict') == 'inefficient':
        status, reason = 'attention', 'Low accepted-progress rate; preserve existing adaptive throttling'
    if check in {'funnel', 'lineage'}:
        truth = source.get('promotionTruth') or {}
        qualified = truth.get('qualified') if isinstance(truth, dict) else None
        if (source.get('researchOnly') is not True or source.get('liveTradingAllowed') is not False
                or source.get('brokerSubmitAllowed') is not False or type(qualified) is not int
                or qualified < 0 or truth.get('source') != 'promotion-evidence-lineage'
                or source.get('integrityAttention')):
            status, reason = 'attention', 'Source-reconciled promotion truth or research boundary is unverified'
    if check == 'verification':
        if source.get('sourceFingerprint') != code_fingerprint(root) or source.get('accepted') is not True:
            status, reason = 'unverified', 'No passing Chief verification bound to the current executable sources'
    if check == 'external' and (source.get('ok') is not True or not source.get('source')):
        status, reason = 'unverified', 'External completion receipt lacks explicit successful result or source reference'
    return status, reason, age


def build_report(root=ROOT, now=None):
    root, now = Path(root), now or local_now()
    registry, registry_error = read(root, REGISTRY)
    if not isinstance(registry, dict) or not isinstance(registry.get('roles'), list):
        registry, registry_error = {}, 'Invalid or missing role registry'
    guard = safety(root, now)
    if registry_error:
        guard['passed'] = False
        guard['reasons'].append(registry_error)
    roles = []
    for role in registry.get('roles', []):
        source, error = read(root, role['artifact'])
        if not isinstance(source, dict):
            source, error = {}, 'Artifact must be a JSON object'
        status, reason, age = role_status(role, source, error, now, root)
        roles.append({**role, 'status': status, 'reason': reason, 'ageHours': age,
                      'sourceGeneratedAt': source.get('lastSuccessfulAt') or source.get('generatedAt'),
                      'sourceHash': digest(source)})
    tasks = []
    for role in roles:
        if role['status'] in {'verified', 'not-due'}:
            continue
        tasks.append({'key': 'role:' + role['id'], 'roleId': role['id'], 'owner': role['owner'],
                      'title': f"Verify {role['title']}", 'priority': 1 if role['status'] in {'missing', 'attention'} else 2,
                      'blocker': role['reason'], 'action': role.get('repairAction'),
                      'acceptance': 'Fresh role-specific successful evidence; code work also requires current-source verification',
                      'assignmentType': 'reviewed-local-worker' if role.get('repairAction') else 'owner-work-queue',
                      'workstream': role.get('workstream')})
    if not guard['passed']:
        tasks.insert(0, {'key': 'safety', 'owner': 'codex', 'title': 'Resolve Chief safety hold', 'priority': 0,
                        'blocker': '; '.join(guard['reasons']), 'action': None,
                        'acceptance': 'Operator-reviewed boundary evidence and protected sources agree'})
    missions, _ = read(root, 'coordination/active_missions.json')
    mission_rows = missions if isinstance(missions, list) else missions.get('missions', [])
    active = [{k: r.get(k) for k in ('id', 'title', 'owner', 'status', 'tags')} for r in mission_rows
              if r.get('status') not in TERMINAL]
    # Existing work is shown alongside assignments; Chief never closes someone
    # else's mission or silently creates an additional engineering worker.
    for task in tasks:
        task['relatedMissionIds'] = [m['id'] for m in active if task.get('workstream') in (m.get('tags') or [])]
    funnel, _ = read(root, 'data/inferno_paper_funnel.json')
    loop, _ = read(root, 'data/inferno_evidence_goal_loop.json')
    costs, cost_error = read(root, 'data/desk_chief_cost_observations.json')
    funnel = funnel if isinstance(funnel, dict) else {}
    loop = loop if isinstance(loop, dict) else {}
    costs = costs if isinstance(costs, dict) else {}
    cost_age = age_hours(costs.get('observedAt'), now)
    costs_ok = not cost_error and cost_age is not None and cost_age <= 36
    cloud = costs.get('cloudSpend') or {}
    cloud_age = age_hours(cloud.get('observedAt'), now) if isinstance(cloud, dict) else None
    cloud_ok = (cloud_age is not None and cloud_age <= 36 and isinstance(cloud, dict) and bool(cloud.get('provider'))
                and bool(cloud.get('billingPeriod')) and bool(cloud.get('source'))
                and cloud.get('basis') == 'actual-billed' and bool(cloud.get('currency'))
                and type(cloud.get('amount')) in (int, float)
                and math.isfinite(cloud['amount']) and cloud['amount'] >= 0)
    state, _ = read(root, STATE)
    state = state if isinstance(state, dict) else {}
    economics = loop.get('economics') or {}
    if not cloud_ok:
        tasks.append({'key': 'cost-visibility', 'owner': 'codex', 'priority': 2,
                      'title': 'Connect source-backed usage and cloud-cost receipts', 'action': None,
                      'blocker': 'Unmeasured cost is unknown, not zero',
                      'acceptance': 'Provider, observation time, billing period and actual usage/cost basis supplied'})
    if economics.get('verdict') == 'inefficient' and not any(t.get('roleId') == 'evidence-efficiency' for t in tasks):
        tasks.append({'key': 'loop-efficiency', 'owner': 'codex', 'priority': 1, 'action': None,
                      'title': 'Repair low-value evidence-loop triggers before increasing cadence',
                      'blocker': f"Acceptance rate {economics.get('fullRunAcceptanceRate')}; no-progress streak {(loop.get('cadence') or {}).get('noProgressStreak')}",
                      'acceptance': 'Fixed-evaluator before/after evidence; fewer duplicate runs with no missed due work'})
    tasks.sort(key=lambda t: (t['priority'], t['key']))
    for task in tasks:
        previous = (state.get('assignments') or {}).get(task['key'], {})
        task['workerStarted'] = (previous.get('lease') or {}).get('expiresAt', '') > now.isoformat()
        task['status'] = 'in-progress' if task['workerStarted'] else 'assigned'
    priorities = tasks[:3]
    semantic = {'safety': guard, 'roles': [(r['id'], r['status'], r['reason']) for r in roles],
                'tasks': [(t['key'], t['blocker']) for t in tasks],
                'qualified': (funnel.get('promotionTruth') or {}).get('qualified')}
    return {'generatedAt': now.isoformat(), 'stage': STAGE, 'researchOnly': True, 'promotable': False,
            'authorityChanged': False, 'liveTradingAllowed': False, 'brokerSubmitAllowed': False,
            'operationalAuthority': 'prioritize, assign, approve bounded retries and verify operational work',
            'safety': guard, 'verdict': 'safety-hold' if not guard['passed'] else 'attention' if tasks else 'ready',
            'roles': roles, 'roleCounts': dict(Counter(r['status'] for r in roles)),
            'assignments': tasks, 'topPriorities': priorities, 'activeMissions': active,
            'workstreamAcceptance': {'W1': funnel.get('dawnAcceptance') or {},
                'W4': 'Future prereg collection targets require observed evidence; no automatic completion'},
            'promotionTruth': funnel.get('promotionTruth') or {},
            'operatingMargin': {'existingEvidenceLoop': economics,
                'existingLoopCadence': loop.get('cadence') or {},
                'usageObservation': costs if costs_ok else None,
                'cloudCostKnown': bool(cloud_ok),
                'chiefCounters': state.get('counters') or {},
                'dollarsPerAcceptedOutcome': None,
                'costCaveat': 'Runtime seconds, account quota and billed dollars are different measures. Missing costs stay unknown.'},
            'meaningfulState': digest(semantic),
            'citations': [REGISTRY, MANDATE, 'docs/DESK_CHIEF_CHARTER_2026-09-30.md']}


def chief_text(report):
    lines = ['Inferno Desk Chief — operations authority', f"As of {report['generatedAt']} | {report['verdict']}",
             'Roles: ' + json.dumps(report['roleCounts'], sort_keys=True), '', 'Top priorities:']
    for t in report['topPriorities']:
        lines += [f"- P{t['priority']} | {t['owner']} | {t['title']}", f"  {t['blocker']}"]
    lines += ['', 'Operating margin:', json.dumps(report['operatingMargin'], sort_keys=True),
              '', 'Role accountability:']
    for r in report['roles']:
        lines.append(f"- {r['title']} | {r['owner']} | {r['status']} | {r['reason']}")
    lines += ['', 'Assignments are in data/inferno_desk_chief.json. An assignment is not proof a remote worker has started.',
              'Only the existing paper delegate/operator decides tickets. Capital, live orders and risk gates stay outside this mandate.']
    return '\n'.join(lines) + '\n'


def save_report(report, root=ROOT):
    atomic_write_json(Path(root) / REPORT, report)
    atomic_write_text(Path(root) / TEXT, chief_text(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['status', 'run', 'verify', 'claim'], nargs='?', default='status')
    parser.add_argument('task_key', nargs='?')
    parser.add_argument('--owner', choices=['codex', 'claude'])
    args = parser.parse_args()
    if args.command == 'claim':
        from inferno_desk_chief_runner import claim_task
        if not args.task_key or not args.owner:
            parser.error('claim requires a task key and --owner')
        print(json.dumps(claim_task(args.task_key, args.owner), indent=2))
        return 0
    if args.command == 'status':
        report = build_report()
        save_report(report)
    else:
        from inferno_desk_chief_runner import run_chief
        report = run_chief(verify_only=args.command == 'verify')
    print(chief_text(report))
    return 0 if report['safety']['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
