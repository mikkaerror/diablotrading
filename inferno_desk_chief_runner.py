"""Fixed operational dispatch for Desk Chief; no arbitrary commands or code edits."""
from __future__ import annotations
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from inferno_config import ROOT, local_now
from inferno_io import atomic_write_json, append_text
from inferno_desk_chief import (STATE, REGISTRY, MANDATE, build_report, code_fingerprint,
                               digest, read, safety, save_report, verification_files)

ACTIONS = {
    'refresh-funnel': ('inferno_paper_funnel.py',),
    'refresh-lineage': ('inferno_promotion_evidence_lineage.py',),
    'verify-code': ('inferno_deploy_preflight.py', '--profile', 'ci', '--timeout-seconds', '180'),
}
MAX_ACTIONS_PER_RUN = 1
COMMAND_TIMEOUT_SECONDS = 240
MAX_BACKOFF_MINUTES = 1440
VERIFICATION = 'data/inferno_desk_chief_verification.json'


def claim_task(key, owner, root=ROOT, now=None):
    """Lease an assigned operational task; this is not a trading permission."""
    root, now = Path(root), now or local_now()
    if not safety(root, now)['passed']:
        raise PermissionError('Chief safety hold prevents assignment claims')
    with (root / 'data/desk_chief.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state, error = read(root, STATE)
        if error:
            raise ValueError('Run Chief before claiming a task')
        task = (state.get('assignments') or {}).get(key)
        if not task or task.get('status') == 'resolved-by-observation' or task.get('owner') != owner:
            raise PermissionError('Task is not assigned to that owner')
        lease = task.get('lease') or {}
        if lease.get('expiresAt', '') > now.isoformat():
            raise PermissionError('Task already has an active lease')
        task.update(status='in-progress', workerStarted=True,
                    lease={'owner': owner, 'claimedAt': now.isoformat(),
                           'expiresAt': (now + timedelta(hours=2)).isoformat()})
        atomic_write_json(root / STATE, state)
        return task


def source_copy(root, destination):
    """A disposable source copy keeps unit tests away from the canonical ledger."""
    root, destination = Path(root), Path(destination)
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    names = {name for name in tracked if name and Path(name).parts[0] not in {'data', 'reports', 'logs', 'outputs', '.git'}}
    names.update(str(p.relative_to(root)) for p in verification_files(root))
    for name in sorted(names):
        path = root / name
        if path.is_symlink():
            raise ValueError('Verification source symlink requires review: ' + name)
        if not path.is_file() or Path(name).name.startswith('.env'):
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def execute(action, root=ROOT):
    if action not in ACTIONS:
        raise PermissionError('Chief action is not on the reviewed operational allowlist')
    root = Path(root)
    started = time.monotonic()
    before = code_fingerprint(root)
    if action == 'verify-code':
        with tempfile.TemporaryDirectory(prefix='inferno-chief-verify-') as tmp:
            source_copy(root, tmp)
            copied = code_fingerprint(tmp)
            if copied != before:
                raise ValueError('Disposable verification copy does not match current source fingerprint')
            environment = {**os.environ, 'INFERNO_DESK_HOST_ROLE': '', 'CLOUD_RUN_JOB': '', 'K_SERVICE': ''}
            proc = subprocess.run([sys.executable, *ACTIONS[action]], cwd=tmp, env=environment,
                                  capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS)
            preflight, error = read(tmp, 'data/inferno_deploy_preflight.json')
            checks = preflight.get('checks') or []
            names = {c.get('name') for c in checks if c.get('returncode') == 0}
            accepted = (proc.returncode == 0 and not error and preflight.get('verdict') == 'ready-for-ci'
                        and {'unit-tests', 'python-compile', 'secret-hygiene'}.issubset(names)
                        and all(c.get('returncode') == 0 for c in checks)
                        and before == code_fingerprint(root))
            proof = {'generatedAt': local_now().isoformat(), 'sourceFingerprint': before,
                     'accepted': accepted, 'scope': 'current-source CI verification only; no merge or deployment',
                     'returncode': proc.returncode, 'verdict': preflight.get('verdict'),
                     'checks': [{k: c.get(k) for k in ('name', 'returncode')} for c in checks],
                     'failedChecks': [{'name': c.get('name'), 'detail': str(c.get('detail', ''))[-6000:]}
                                      for c in checks if c.get('returncode') != 0],
                     'isolatedFromCanonicalData': True, 'liveTradingAllowed': False, 'brokerSubmitAllowed': False}
            atomic_write_json(root / VERIFICATION, proof)
    else:
        proc = subprocess.run([sys.executable, *ACTIONS[action]], cwd=root,
                              capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS)
    return {'action': action, 'returncode': proc.returncode,
            'seconds': round(time.monotonic() - started, 3),
            'diagnosticTail': (proc.stderr or proc.stdout or '')[-1200:]}


def run_chief(root=ROOT, now=None, *, verify_only=False, executor=execute):
    root, now = Path(root), now or local_now()
    (root / 'data').mkdir(parents=True, exist_ok=True)
    with (root / 'data/desk_chief.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            report = build_report(root, now)
            report['dispatch'] = {'status': 'already-running', 'executed': 0}
            return report
        state, state_error = read(root, STATE)
        if state_error and (root / STATE).exists():
            raise ValueError('Chief state is corrupt; preserve it for recovery instead of replaying work')
        report = build_report(root, now)
        attempts = state.setdefault('attempts', {})
        events = []
        prior_roles = {r['id']: r for r in report['roles']}
        candidates = [t for t in report['assignments'] if t.get('action') in ACTIONS]
        if verify_only:
            candidates = [t for t in candidates if t['action'] == 'verify-code']
        accepted = 0
        skipped = 0
        if report['safety']['passed']:
            for task in candidates:
                if len(events) >= MAX_ACTIONS_PER_RUN:
                    break
                lease = ((state.get('assignments') or {}).get(task['key'], {}).get('lease') or {})
                if lease.get('expiresAt', '') > now.isoformat():
                    skipped += 1
                    continue
                signature = code_fingerprint(root) if task['action'] == 'verify-code' else digest({
                    'role': prior_roles[task['roleId']]['status'],
                    'source': prior_roles[task['roleId']]['sourceHash']})
                previous = attempts.get(task['key']) or {}
                # A skip never advances the retry deadline. Unchanged failures
                # remain bounded, and a meaningful new source can unblock work.
                if previous.get('signature') == signature and now.isoformat() < previous.get('nextRetryAt', ''):
                    skipped += 1
                    continue
                if not safety(root, now)['passed']:
                    break
                streak = int(previous.get('noProgressStreak', 0)) if previous.get('signature') == signature else 0
                backoff = min(MAX_BACKOFF_MINUTES, 60 * 2 ** min(streak, 5))
                attempt = {'status': 'running', 'signature': signature, 'attemptedAt': now.isoformat(),
                           'nextRetryAt': (now + timedelta(minutes=backoff)).isoformat(), 'noProgressStreak': streak}
                attempts[task['key']] = attempt
                atomic_write_json(root / STATE, state)  # interrupted workers are not silently replayed
                started = time.monotonic()
                try:
                    result = executor(task['action'], root)
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    result = {'action': task['action'], 'returncode': 1,
                              'seconds': round(time.monotonic() - started, 3), 'diagnosticTail': str(exc)}
                after = build_report(root, max(now, local_now()))
                after_role = next(r for r in after['roles'] if r['id'] == task['roleId'])
                passed = result.get('returncode') == 0 and after_role['status'] == 'verified' and after['safety']['passed']
                accepted += int(passed)
                attempt.update(status='accepted' if passed else 'blocked',
                               noProgressStreak=0 if passed else streak + 1,
                               lastResult=result, acceptedAt=now.isoformat() if passed else None)
                event = {'at': now.isoformat(), 'taskKey': task['key'], 'owner': task['owner'],
                         'action': task['action'], 'operationalApproval': 'allowlisted-with-safety-check',
                         'accepted': passed, 'classification': 'code-verification' if task['action'] == 'verify-code' else 'report-recovery',
                         'seconds': result['seconds'], 'returncode': result['returncode'],
                         'before': prior_roles[task['roleId']]['status'], 'after': after_role['status'],
                         'valueBasis': 'Verified operational delivery; not new research evidence or promotion credit'}
                events.append(event)
                append_text(root / 'data/desk_chief_decisions.jsonl', json.dumps(event) + '\n')
                report = after
        counts = state.setdefault('counters', {'reviews': 0, 'executed': 0, 'accepted': 0, 'seconds': 0, 'suppressed': 0})
        counts['reviews'] += 1
        counts['executed'] += len(events)
        counts['accepted'] += accepted
        counts['seconds'] += sum(e['seconds'] for e in events)
        counts['suppressed'] += skipped
        current_keys = {t['key'] for t in report['assignments']}
        assignments = state.setdefault('assignments', {})
        for task in report['assignments']:
            old = assignments.get(task['key'], {})
            claimed = (old.get('lease') or {}).get('expiresAt', '') > now.isoformat()
            assignments[task['key']] = {**old, **task, 'firstSeenAt': old.get('firstSeenAt', now.isoformat()),
                                       'status': 'blocked' if not report['safety']['passed'] else 'in-progress' if claimed else 'assigned',
                                       'assignedBy': 'desk-chief', 'workerStarted': claimed}
        for key, task in assignments.items():
            if key not in current_keys:
                # Another worker may have resolved it. Credit only Chief's own
                # independently checked dispatch to Chief operating economics.
                task['status'] = 'resolved-by-observation'
        state.update(lastRunAt=now.isoformat(), meaningfulState=report['meaningfulState'])
        report['dispatch'] = {'executed': len(events), 'accepted': accepted, 'suppressed': skipped,
                              'changed': state.get('lastNotifiedState') != report['meaningfulState'], 'events': events,
                              'maxActionsPerRun': MAX_ACTIONS_PER_RUN}
        state['lastNotifiedState'] = report['meaningfulState']
        report['operatingMargin']['chief'] = {**counts,
            'acceptanceRate': counts['accepted'] / counts['executed'] if counts['executed'] else None,
            'secondsPerAcceptedDelivery': counts['seconds'] / counts['accepted'] if counts['accepted'] else None,
            'billableDollars': None, 'acceptedResearchOutcomes': 0}
        atomic_write_json(root / STATE, state)
        save_report(report, root)
        return report
