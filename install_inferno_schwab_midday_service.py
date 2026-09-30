"""Install the weekday 13:00 ET read-only Schwab capture on this Mac."""
from __future__ import annotations
import argparse
import os
import plistlib
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from inferno_config import ROOT, backtest_python

SERVICE_LABEL = 'io.diablotrading.inferno-schwab-midday'
PLIST_PATH = Path.home() / 'Library' / 'LaunchAgents' / f'{SERVICE_LABEL}.plist'
LOG_DIR = Path.home() / 'Library' / 'Logs' / 'Inferno'
SERVICE_WRAPPER = Path.home() / '.local' / 'bin' / 'inferno_schwab_midday_service.sh'


def local_schedule(zone_name):
    # Validate both seasons: launchd calendar entries use the machine's timezone.
    zone = ZoneInfo(zone_name)
    times = set()
    for month in range(1, 13):
        dt = datetime(2026, month, 15, 13, tzinfo=ZoneInfo('America/New_York')).astimezone(zone)
        times.add((dt.hour, dt.minute))
    if len(times) != 1:
        raise ValueError('Local timezone diverges seasonally from ET; explicit scheduler adaptation required.')
    return next(iter(times))


def machine_timezone():
    resolved = str(Path('/etc/localtime').resolve())
    if '/zoneinfo/' not in resolved:
        raise ValueError('Cannot determine the machine timezone from /etc/localtime.')
    return resolved.split('/zoneinfo/', 1)[1]


def plist_payload(zone_name):
    hour, minute = local_schedule(zone_name)
    return {'Label': SERVICE_LABEL, 'ProgramArguments': [str(SERVICE_WRAPPER)],
            'WorkingDirectory': str(ROOT), 'RunAtLoad': False,
            'StartCalendarInterval': [{'Weekday': day, 'Hour': hour, 'Minute': minute} for day in range(1, 6)],
            'StandardOutPath': str(LOG_DIR / 'inferno_schwab_midday.stdout.log'),
            'StandardErrorPath': str(LOG_DIR / 'inferno_schwab_midday.stderr.log'),
            'EnvironmentVariables': {'PATH': '/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin',
                                     'HOME': str(Path.home())}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['install', 'status', 'uninstall'])
    args = parser.parse_args()
    domain = f'gui/{os.getuid()}'
    if args.command == 'status':
        return subprocess.run(['launchctl', 'print', f'{domain}/{SERVICE_LABEL}']).returncode
    if args.command == 'uninstall':
        subprocess.run(['launchctl', 'bootout', domain, str(PLIST_PATH)], capture_output=True)
        PLIST_PATH.unlink(missing_ok=True)
        return 0
    payload = plist_payload(machine_timezone())
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    SERVICE_WRAPPER.parent.mkdir(parents=True, exist_ok=True)
    SERVICE_WRAPPER.write_text('#!/bin/zsh\nset -euo pipefail\ncd ' + shlex.quote(str(ROOT)) +
        '\nexec ' + shlex.quote(str(backtest_python())) + ' ' +
        shlex.quote(str(ROOT / 'inferno_schwab_midday_capture.py')) + ' run\n')
    SERVICE_WRAPPER.chmod(0o755)
    with PLIST_PATH.open('wb') as handle:
        plistlib.dump(payload, handle)
    subprocess.run(['launchctl', 'bootout', domain, str(PLIST_PATH)], capture_output=True)
    result = subprocess.run(['launchctl', 'bootstrap', domain, str(PLIST_PATH)], capture_output=True, text=True)
    if result.returncode:
        print(result.stderr)
        return result.returncode
    subprocess.run(['launchctl', 'enable', f'{domain}/{SERVICE_LABEL}'], check=True)
    print(f'Installed weekday 13:00 ET capture ({machine_timezone()}: {local_schedule(machine_timezone())}).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
