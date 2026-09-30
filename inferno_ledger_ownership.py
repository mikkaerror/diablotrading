"""Mac paper ownership boundary. Research reads never grant mutation authority."""
from __future__ import annotations
import hashlib
import json
import os
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / 'data' / 'inferno_ledger_ownership.json'
ACK_FILE = ROOT / 'coordination/operator_acks/2026-09-30_ledger_cutover.json'
PROTECTED_PATHS = (
    'data/inferno_paper_execution_ledger.json', 'data/inferno_approval_queue.json',
    'data/inferno_approval_dispatch_state.json', 'data/inferno_approval_inbox_state.json',
    'data/inferno_tos_fill_log.csv', 'data/operator_decisions.csv',
)


def is_cloud():
    return bool(os.environ.get('CLOUD_RUN_JOB') or os.environ.get('K_SERVICE') or
                os.environ.get('INFERNO_DESK_HOST_ROLE') == 'cloud-research')


def ownership():
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text())  # corruption must not silently restore authority


def require_paper_writer(action='paper mutation'):
    if is_cloud():
        raise PermissionError(f'{action}: cloud is research-only; canonical paper writer is the Mac')
    state = ownership()
    if state:
        if state.get('status') != 'active' or state.get('owner') != 'mac':
            raise PermissionError(f'{action}: paper ownership is frozen or inactive')
        if state.get('canonicalRoot') != str(ROOT) or state.get('hostname') != platform.node():
            raise PermissionError(f'{action}: not the designated canonical Mac checkout')
        if not ACK_FILE.exists() or hashlib.sha256(ACK_FILE.read_bytes()).hexdigest() != state.get('ackSha256'):
            raise PermissionError(f'{action}: missing or changed operator ownership acknowledgement')


def approved_budget_environment():
    raw = ACK_FILE.read_bytes(); ack = json.loads(raw)
    decisions = ack['decisions']
    if decisions['D5_ledgerOwner']['answer'] != 'mac' or decisions['D6_paperSingleTicketCapDollars']['answer'] != 2000:
        raise ValueError('D5/D6 acknowledgement does not authorize this cutover')
    return {'INFERNO_PAPER_TICKET_BUDGET': '2000',
            'INFERNO_PAPER_BUDGET_ACK_SHA256': hashlib.sha256(raw).hexdigest()}


# Serialize canonical local read/modify/write operations, including nested APIs.
import functools
import threading
import fcntl
_local_lock = threading.RLock()
_depth = threading.local()


def paper_writer(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        require_paper_writer(function.__name__)
        with _local_lock:
            if getattr(_depth, 'active', False):
                return function(*args, **kwargs)
            path = ROOT/'data/paper_owner.lock'
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a') as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                _depth.active = True
                try:
                    return function(*args, **kwargs)
                finally:
                    _depth.active = False
                    fcntl.flock(handle, fcntl.LOCK_UN)
    return wrapped


def cloud_research_entrypoint(function):
    """Scope CLI host mode so embedded callers/tests cannot inherit stale authority context."""
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        import sys
        active = function.__module__ == 'cloud_strike_cycle' or Path(sys.argv[0]).name == 'cloud_strike_cycle.py' or '--cloud-native' in sys.argv or is_cloud()
        if not active: return function(*args, **kwargs)
        previous = os.environ.get('INFERNO_DESK_HOST_ROLE')
        os.environ['INFERNO_DESK_HOST_ROLE'] = 'cloud-research'
        try: return function(*args, **kwargs)
        finally:
            if previous is None: os.environ.pop('INFERNO_DESK_HOST_ROLE', None)
            else: os.environ['INFERNO_DESK_HOST_ROLE'] = previous
    return wrapped
