"""Second read-only chain capture; never invokes paper decisions or execution."""
from __future__ import annotations
import argparse
import fcntl
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from server import DATA_DIR, REPORTS_DIR, load_json_file, SNAPSHOT_FILE

CAPTURE_FILE = DATA_DIR / 'inferno_schwab_midday_capture.json'
CAPTURE_TEXT_FILE = REPORTS_DIR / 'schwab_midday_capture_latest.txt'
MARKET_TZ = ZoneInfo('America/New_York')


def in_capture_window(now: datetime) -> bool:
    market = now.astimezone(MARKET_TZ)
    return market.weekday() < 5 and 12 * 60 + 30 <= market.hour * 60 + market.minute < 14 * 60


def save_capture(report):
    atomic_write_json(CAPTURE_FILE, report)
    atomic_write_text(CAPTURE_TEXT_FILE, json.dumps(report, indent=2) + '\n')


def run_capture(*, now=None):
    now = now or local_now()
    if not in_capture_window(now):
        return {'status': 'outside-capture-window', 'researchOnly': True}
    day = now.astimezone(MARKET_TZ).date().isoformat()
    previous = load_json_file(CAPTURE_FILE) or {}
    if previous.get('marketDate') == day and previous.get('status') == 'captured':
        return previous  # no duplicate fetches after successful completion
    report = {'generatedAt': now.isoformat(), 'marketDate': day,
              'stage': 'schwab-midday-capture-research-only', 'researchOnly': True,
              'promotable': False, 'authorityChanged': False, 'liveTradingAllowed': False,
              'brokerSubmitAllowed': False, 'status': 'running',
              'citations': ['inferno_schwab_options.json', 'inferno_short_premium_shadow.json']}
    save_capture(report)  # a crash cannot leave the previous day's success looking current
    try:
        from inferno_schwab_daily_ops import (load_schwab_env, default_symbol_universe, live_chain_report,
            build_ops_report, save_ops_report, earnings_window_symbols, schwab_symbol_limit)
        from inferno_short_premium_shadow import run as run_shadow
        load_schwab_env()
        symbols = default_symbol_universe()
        earnings = earnings_window_symbols(load_json_file(SNAPSHOT_FILE) or {}, today=now.astimezone(MARKET_TZ).date())
        chain = live_chain_report(symbols, symbol_limit=max(schwab_symbol_limit(), len(symbols)))
        save_ops_report(build_ops_report(chain, symbols=symbols))
        fetched = {r.get('symbol') for r in chain.get('rows', []) if r.get('status') == 'ok'}
        regular = {r.get('symbol') for r in chain.get('rows', []) if r.get('status') == 'ok' and r.get('quoteSessionIsRegular') is True}
        report.update(symbolsRequested=symbols, earningsWindowSymbols=earnings,
                      missingEarningsChains=sorted(set(earnings) - fetched),
                      nonRegularEarningsChains=sorted(set(earnings) - regular),
                      sourceStatus=chain.get('status'), errors=chain.get('errors') or [])
        if chain.get('status') not in {'ok', 'partial-error'}:
            raise RuntimeError(f"chain capture did not succeed: {chain.get('status')}")
        shadow = run_shadow()  # unchanged v2 capture/skip/settlement rules; shadow ledger only
        report.update(status='captured' if chain.get('status') == 'ok' else 'partial-error',
                      v2LastRun=shadow.get('lastRun'), v2Summary=shadow.get('summary'))
    except Exception as exc:
        report.update(status='failed', error=f'{type(exc).__name__}: {exc}',
                      nextAction='Inspect OAuth/chain errors; retry within the capture window.')
    save_capture(report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', choices=['run', 'status'], default='run')
    args = parser.parse_args()
    if args.command == 'status':
        print(json.dumps(load_json_file(CAPTURE_FILE) or {}, indent=2))
        return 0
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with (DATA_DIR / 'schwab_midday_capture.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Midday capture already running; skipped duplicate.')
            return 0
        report = run_capture()
    print(json.dumps(report, indent=2))
    return 1 if report.get('status') in {'failed', 'partial-error'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
