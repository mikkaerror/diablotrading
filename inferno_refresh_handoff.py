"""Bounded market-open refresh with a verified completion handoff to briefs.

Research-only. No ticket actions, broker submission or email delivery. A receipt
means the required artifacts were rebuilt, not that a candidate is tradable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from inferno_config import ROOT, local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_market_calendar import is_market_session
from server import DATA_DIR, REPORTS_DIR

RECEIPT_FILE = DATA_DIR / 'inferno_market_open_handoff.json'
REPORT_FILE = REPORTS_DIR / 'market_open_handoff_latest.txt'
LOCK_FILE = DATA_DIR / 'inferno_market_open_handoff.lock'
REQUIRED = ('inferno_schwab_options', 'inferno_schwab_daily_ops',
            'inferno_strategy_alternative_pricing', 'inferno_strategy_shadow_comparison',
            'inferno_paper_test_director')
COMMANDS = (
    ('oauth', ('inferno_schwab_oauth.py', 'ensure')),
    ('daily ops', ('inferno_schwab_daily_ops.py', '--quiet')),
    ('variant scanner', ('inferno_paper_variant_scanner.py', 'run')),
    ('quote coverage', ('inferno_strategy_quote_coverage.py', 'run', '--limit', '6', '--variants-per-ticker', '3')),
    ('pricing', ('inferno_strategy_alternative_pricing.py', '--limit', '6', '--variants-per-ticker', '3')),
    ('shadow comparison', ('inferno_strategy_shadow_comparison.py',)),
    ('paper research', ('inferno_paper_test_director.py', 'build')),
    ('paper blockers', ('inferno_paper_blocker_swarm.py', 'run')),
    ('scenario slate', ('inferno_paper_bottleneck_reducer.py', 'build')),
    ('scenario observations', ('inferno_scenario_evidence.py', 'build')),
    ('scenario backtest', ('inferno_scenario_backtest.py', 'build')),
    ('score archive', ('inferno_score_calibration.py', 'run')),
)


def timestamp(raw: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        return parsed if parsed.utcoffset() is not None else None
    except (ValueError, TypeError):
        return None


def read_artifacts() -> dict[str, dict]:
    result = {}
    for name in REQUIRED:
        try:
            raw = (DATA_DIR / f'{name}.json').read_bytes()
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError('artifact must be an object')
            result[name] = {'payload': payload, 'sha256': hashlib.sha256(raw).hexdigest()}
        except (OSError, ValueError):
            result[name] = {'payload': {}, 'sha256': None}
    return result


def object_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def source_payload(artifacts: dict, name: str) -> dict:
    return object_dict(object_dict(artifacts.get(name)).get('payload'))


def source_check(artifacts: dict, started: datetime, finished: datetime) -> list[str]:
    issues = []
    for name in REQUIRED:
        payload = source_payload(artifacts, name)
        generated = timestamp(payload.get('generatedAt'))
        if not object_dict(artifacts.get(name)).get('sha256'):
            issues.append(f'{name}: missing source hash')
        if generated is None or not started <= generated <= finished:
            issues.append(f'{name}: missing, old or future generation timestamp')
    options = source_payload(artifacts, 'inferno_schwab_options')
    ops = source_payload(artifacts, 'inferno_schwab_daily_ops')
    if options.get('status') != 'ok' or not isinstance(options.get('rows'), list) or not options.get('rows'):
        issues.append('option-chain source unavailable or empty')
    if ops.get('sourceStatus') != 'ok' or timestamp(ops.get('sourceGeneratedAt')) != timestamp(options.get('generatedAt')):
        issues.append('daily ops does not reference the refreshed chain source')
    pricing = source_payload(artifacts, 'inferno_strategy_alternative_pricing')
    shadow = source_payload(artifacts, 'inferno_strategy_shadow_comparison')
    if timestamp(object_dict(shadow.get('sourcePricing')).get('generatedAt')) != timestamp(pricing.get('generatedAt')):
        issues.append('shadow comparison does not reference the refreshed pricing source')
    return issues


def base_receipt(now: datetime) -> dict:
    return {'generatedAt': now.isoformat(), 'startedAt': now.isoformat(),
            'stage': 'refresh-handoff-research-only', 'researchOnly': True,
            'promotable': False, 'authorityChanged': False,
            'liveTradingAllowed': False, 'brokerSubmitAllowed': False,
            'citations': [f'{name}.json' for name in REQUIRED]}


def market_open(now: datetime) -> bool:
    eastern = now.astimezone(ZoneInfo('America/New_York'))
    return is_market_session(eastern.date()) and (9, 30) <= (eastern.hour, eastern.minute) < (16, 0)


def run_refresh(*, runner=None, clock=local_now, read_sources=read_artifacts, save=None) -> dict:
    """Run a bounded chain; command success alone never earns a ready receipt."""
    save = save or save_receipt
    started = clock()
    receipt = base_receipt(started)
    if not market_open(started):
        receipt.update(status='market-closed', reason='Outside the regular session; no market-open refresh due.')
        save(receipt)
        return receipt
    receipt.update(status='running', steps=[])
    save(receipt)
    wall_started = time.monotonic()
    deadline = wall_started + 900
    def default_runner(argv, timeout):
        result = subprocess.run([sys.executable, *argv], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return result.returncode
    runner = runner or default_runner
    for name, argv in COMMANDS:
        remaining = deadline - time.monotonic()
        try:
            if remaining <= 0:
                raise TimeoutError('refresh deadline exceeded')
            rc = runner(argv, min(180, remaining))
        except (OSError, subprocess.TimeoutExpired, TimeoutError) as exc:
            receipt.update(status='failed', reason=f'{name}: {type(exc).__name__}')
            break
        receipt['steps'].append({'name': name, 'returnCode': rc})
        if rc != 0:
            receipt.update(status='failed', reason=f'{name} exited {rc}; inspect its diagnostic report')
            break
    finished = clock()
    if receipt['status'] == 'running':
        artifacts = read_sources()
        issues = source_check(artifacts, started, finished)
        receipt.update(status='blocked' if issues else 'complete', issues=issues,
                       sources={name: {'sha256': object_dict(artifacts.get(name)).get('sha256'),
                           'generatedAt': source_payload(artifacts, name).get('generatedAt')}
                           for name in REQUIRED})
    receipt.update(generatedAt=finished.isoformat(), completedAt=finished.isoformat(),
                   elapsedSeconds=round(time.monotonic()-wall_started, 3),
                   monetaryCost=None, acceptedEvidenceProgress=0)
    save(receipt)
    return receipt


def brief_readiness(receipt: dict | None = None, *, now: datetime | None = None, artifacts: dict | None = None) -> dict:
    """Check this session's completion and unchanged dependency inputs."""
    now = now or local_now()
    if not market_open(now):
        return {'ready': False, 'status': 'market-closed', 'reason': 'No market-open briefing due.'}
    if receipt is None:
        try:
            receipt = json.loads(RECEIPT_FILE.read_text())
        except (OSError, ValueError):
            receipt = {}
    receipt = object_dict(receipt)
    completed = timestamp(receipt.get('completedAt'))
    started = timestamp(receipt.get('startedAt'))
    if receipt.get('status') != 'complete' or completed is None or started is None:
        return {'ready': False, 'status': 'awaiting-refresh', 'reason': 'A verified complete refresh receipt is required.'}
    if not started <= completed <= now or started.astimezone(now.tzinfo).date() != now.date() or (now-completed).total_seconds() > 3600:
        return {'ready': False, 'status': 'stale-refresh', 'reason': 'Refresh must be from this session and within one hour.'}
    artifacts = read_artifacts() if artifacts is None else artifacts
    issues = source_check(artifacts, started, completed)
    if receipt.get('researchOnly') is not True or any(receipt.get(key) is not False for key in ('promotable', 'authorityChanged', 'liveTradingAllowed', 'brokerSubmitAllowed')):
        issues.append('receipt authority contract invalid')
    for name in REQUIRED:
        expected = object_dict(object_dict(receipt.get('sources')).get(name)).get('sha256')
        if not expected or object_dict(artifacts.get(name)).get('sha256') != expected:
            issues.append(f'{name}: changed since completion')
    return {'ready': not issues, 'status': 'ready' if not issues else 'changed-inputs',
            'reason': '; '.join(issues) if issues else 'Research refresh completed; quote quality and trade gates remain separate.',
            'completedAt': completed.isoformat()}


def receipt_text(payload: dict) -> str:
    return ('Inferno Market-open Refresh Handoff (research only)\n\n'
            f"Generated: {payload.get('generatedAt')}\nStatus: {payload.get('status')}\n"
            f"Started: {payload.get('startedAt')}\nCompleted: {payload.get('completedAt')}\n"
            f"Reason: {payload.get('reason') or '; '.join(payload.get('issues') or []) or 'Required artifacts rebuilt'}\n"
            f"Elapsed seconds: {payload.get('elapsedSeconds')} | Monetary cost: unmeasured\n"
            'A refresh receipt grants no quote-quality, outcome or trading authority.\n')


def save_receipt(payload: dict) -> None:
    atomic_write_json(RECEIPT_FILE, payload)
    atomic_write_text(REPORT_FILE, receipt_text(payload))


def source_basis(*, now=None) -> dict:
    now = now or local_now()
    artifacts = read_artifacts()
    eastern = now.astimezone(ZoneInfo('America/New_York'))
    phase = ('closed-market' if not is_market_session(eastern.date()) else
             'pre-market-open-refresh' if (eastern.hour, eastern.minute) < (9, 35) else
             'latest-available-artifacts')
    return {'phase': phase, 'handoff': brief_readiness(now=now, artifacts=artifacts),
            'sourceGeneratedAt': {name: source_payload(artifacts, name).get('generatedAt') for name in REQUIRED},
            'note': 'Artifact timestamps are build times; individual quote quality and source age remain separate gates.'}


def refresh_handoff_status(report: dict, now: datetime) -> tuple[bool, str]:
    """Daily completion health; the one-hour send guard is a separate check."""
    eastern = now.astimezone(ZoneInfo('America/New_York'))
    if not is_market_session(eastern.date()):
        return True, 'market-closed; no refresh due'
    if (eastern.hour, eastern.minute) < (9, 55):
        return True, 'morning refresh deadline not yet due'
    report = object_dict(report)
    completed = timestamp(report.get('completedAt'))
    ok = (report.get('status') == 'complete' and completed is not None
          and completed <= now and completed.astimezone(eastern.tzinfo).date() == eastern.date())
    return ok, f"{report.get('status') or 'missing'} | completed {report.get('completedAt')} | {report.get('reason') or '; '.join(report.get('issues') or [])}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['run', 'guard'])
    args = parser.parse_args()
    if args.command == 'guard':
        payload = brief_readiness()
        print(json.dumps(payload, indent=2))
        return 0 if payload['ready'] else 2
    # POSIX lock is released by the kernel on timeout/crash; never leave a stale
    # directory lock preventing tomorrow's refresh.
    import fcntl
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Refresh already running; no second execution started.')
            return 2
        if brief_readiness()['ready']:
            print('Verified fresh refresh already complete; duplicate work suppressed.')
            return 0
        payload = run_refresh()
    print(json.dumps(payload, indent=2))
    return 0 if payload['status'] in ('complete', 'market-closed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
