"""Canonical Mac staging cycle, with approved D6 budget and no approval decisions."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from inferno_ledger_ownership import ROOT, require_paper_writer, approved_budget_environment

STATE = ROOT/'data/inferno_mac_paper_cycle.json'


def input_revision():
    values = []
    for name in ('latest_snapshot.json', 'inferno_approval_queue.json', 'inferno_schwab_options.json'):
        path = ROOT/'data'/name
        if not path.exists(): raise ValueError(f'Canonical staging input missing: {name}')
        values.append(hashlib.sha256(path.read_bytes()).hexdigest())
    # Variant repricing and routing upgrades must invalidate the staging cache.
    # Missing optional research remains missing; this grants no eligibility.
    for name in ('data/inferno_strategy_alternative_pricing.json', 'inferno_paper_approval_routes.py'):
        path = ROOT/name
        values.append(hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None)
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def in_dawn_window(now):
    return now.weekday() < 5 and 6 <= now.hour < 11


def publish_pending(state):
    """Retry only snapshot publication; never replay staging or approvals."""
    from inferno_config import local_now
    from inferno_io import atomic_write_json
    from inferno_canonical_paper_snapshot import publish, snapshot
    require_paper_writer('canonical snapshot retry')
    now = local_now()
    prior = state.get('publication') or {}
    retry_at = prior.get('nextRetryAt')
    if prior.get('status') in {'queued', 'publishing'} and retry_at and now < datetime.fromisoformat(retry_at):
        print(f'Canonical publication pending; retry after {retry_at}: {prior.get("error", "interrupted attempt")}')
        return 1
    failures = int(prior.get('consecutiveFailures', 0))
    delay = min(3600, 300 * 2 ** min(failures, 4))
    for attempt in range(2):
        receipt = {'status': 'publishing', 'lastAttemptAt': now.isoformat(),
                   'nextRetryAt': (now + timedelta(seconds=delay)).isoformat(),
                   'consecutiveFailures': failures}
        state['publication'] = receipt
        state['ok'] = False
        atomic_write_json(STATE, state)
        try:
            # Local comparison avoids network work when the last published facts
            # are unchanged. Inbox bookkeeping can change without staging input.
            revision = snapshot()[0]['revision']
            if prior.get('status') in {'published', 'unchanged'} and prior.get('revision') == revision:
                result = {'status': 'unchanged', 'revision': revision,
                          'lastSuccessfulAt': prior.get('lastSuccessfulAt')}
            else:
                result = publish('ohsheetohsheet-inferno-state')
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            if attempt == 0 and 'Canonical sources changed during publication' in str(exc):
                continue  # rebuild a fresh immutable snapshot once after a race
            receipt.update(status='queued', error=str(exc), consecutiveFailures=failures + 1)
            atomic_write_json(STATE, state)
            print(f'Canonical publication queued: {exc}; retry after {receipt["nextRetryAt"]}')
            return 1
        state['publication'] = {'lastSuccessfulAt': local_now().isoformat(), **result,
                                'lastCheckedAt': local_now().isoformat(),
                                'consecutiveFailures': 0}
        state['ok'] = state.get('returncode', 1) == 0
        atomic_write_json(STATE, state)
        print(json.dumps(state['publication']))
        return state.get('returncode', 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['pre-delegate','post-delegate'], default='pre-delegate')
    args = parser.parse_args()
    from inferno_config import local_now
    if not in_dawn_window(local_now()):
        print('Outside the Mac dawn window; no paper staging.')
        return 0
    require_paper_writer('Mac strike cycle')
    environment = {**os.environ, **approved_budget_environment(), 'INFERNO_DESK_HOST_ROLE': 'mac',
                   'PATH': str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', '')}
    lock_path = ROOT/'data/mac_paper_cycle.lock'; lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a') as handle:
        try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return 0
        previous = json.loads(STATE.read_text()) if STATE.exists() else {}
        revision = input_revision()
        if previous.get('inputRevision') == revision:
            print('Mac paper cycle unchanged; no duplicate staging.')
            return publish_pending(previous)
        # The regular cycle rechecks pricing, liquidity and risk. It never applies approval decisions.
        proc = subprocess.run(['/bin/zsh', str(ROOT/'run_inferno_strike_cycle.sh'), '--run-kind', 'dawn'],
                              cwd=ROOT, env=environment, timeout=540)
        from inferno_io import atomic_write_json
        from inferno_config import local_now
        state = {'generatedAt': local_now().isoformat(), 'phase': args.phase,
            'inputRevision': input_revision(), 'ok': proc.returncode == 0, 'returncode': proc.returncode,
            'owner': 'mac', 'canonicalRoot': str(ROOT), 'paperBudget': approved_budget_environment(),
            'researchOnly': True, 'brokerSubmitAllowed': False, 'liveTradingAllowed': False}
        atomic_write_json(STATE, state)
        # Publication is read-only with respect to ticket facts, even after an empty candidate cycle.
        return publish_pending(state)


if __name__ == '__main__': raise SystemExit(main())
