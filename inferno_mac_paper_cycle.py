"""Canonical Mac staging cycle, with approved D6 budget and no approval decisions."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from inferno_ledger_ownership import ROOT, require_paper_writer, approved_budget_environment

STATE = ROOT/'data/inferno_mac_paper_cycle.json'


def input_revision():
    values = []
    for name in ('latest_snapshot.json', 'inferno_approval_queue.json', 'inferno_schwab_options.json'):
        path = ROOT/'data'/name
        if not path.exists(): raise ValueError(f'Canonical staging input missing: {name}')
        values.append(hashlib.sha256(path.read_bytes()).hexdigest())
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def in_dawn_window(now):
    return now.weekday() < 5 and 6 <= now.hour < 11


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
            return 0
        # The regular cycle rechecks pricing, liquidity and risk. It never applies approval decisions.
        proc = subprocess.run(['/bin/zsh', str(ROOT/'run_inferno_strike_cycle.sh'), '--run-kind', 'dawn'],
                              cwd=ROOT, env=environment, timeout=540)
        from inferno_io import atomic_write_json
        from inferno_config import local_now
        atomic_write_json(STATE, {'generatedAt': local_now().isoformat(), 'phase': args.phase,
            'inputRevision': input_revision(), 'ok': proc.returncode == 0, 'returncode': proc.returncode,
            'owner': 'mac', 'canonicalRoot': str(ROOT), 'paperBudget': approved_budget_environment(),
            'researchOnly': True, 'brokerSubmitAllowed': False, 'liveTradingAllowed': False})
        # Publication is read-only with respect to ticket facts, even after an empty candidate cycle.
        from inferno_canonical_paper_snapshot import publish
        print(json.dumps(publish('ohsheetohsheet-inferno-state')))
        return proc.returncode


if __name__ == '__main__': raise SystemExit(main())
