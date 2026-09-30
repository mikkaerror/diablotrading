import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import inferno_schwab_daily_ops as ops
import inferno_schwab_options as options
import inferno_schwab_midday_capture as midday
import install_inferno_schwab_midday_service as service

NOW = datetime(2026, 10, 13, 17, tzinfo=timezone.utc)


class ChainCoverageTests(unittest.TestCase):
    def test_dated_earnings_first_and_all_fit_above_legacy_limit(self):
        rows = [{'ticker': f'E{i:02}', 'nextEarnings': '2026-10-14'} for i in range(15)]
        rows += [{'ticker': 'OLD', 'nextEarnings': '2026-10-12', 'daysUntilEarnings': 1},
                 {'ticker': 'TODAY', 'nextEarnings': '2026-10-13'},
                 {'ticker': 'LATE', 'nextEarnings': '2026-10-21'},
                 {'ticker': 'UNDATED', 'daysUntilEarnings': 1}]
        sources = {ops.SNAPSHOT_FILE: {'rows': rows}, ops.LIVE_ACCOUNT_SYNC_FILE: {'positions': [{'symbol': 'HELD'}]}}
        with patch.object(ops, 'local_now', return_value=NOW), patch.object(ops, 'load_json_file', side_effect=lambda p: sources.get(p, {})):
            symbols = ops.default_symbol_universe(limit=12)
        self.assertEqual(symbols, [f'E{i:02}' for i in range(15)] + ['LATE', 'OLD'])
        with patch.object(options, 'load_schwab_access_token', return_value=None), patch.object(options, 'summarize_chain', side_effect=lambda s, p: {'symbol': s}):
            report = options.build_report(symbols, fixture_payloads={s: {} for s in symbols}, symbol_limit=len(symbols))
        self.assertEqual(len(report['rows']), 17)
        self.assertEqual(report['captureSymbolLimit'], 17)
        self.assertTrue(report['researchOnly'])

    def test_default_limit_still_applies_without_explicit_coverage_expansion(self):
        with patch.object(options, 'SCHWAB_OPTIONS_SYMBOL_LIMIT', 2), patch.object(options, 'load_schwab_access_token', return_value=None), patch.object(options, 'summarize_chain', side_effect=lambda s, p: {'symbol': s}):
            report = options.build_report(['A', 'B', 'C'], fixture_payloads={'A': {}, 'B': {}, 'C': {}})
        self.assertEqual(report['symbolCount'], 2)

    def test_window_and_schedule_cover_winter_and_summer(self):
        self.assertEqual(service.local_schedule('America/Denver'), (11, 0))
        for month in (1, 7):
            # 13:00 New York remains 11:00 Denver in both seasons.
            now = datetime(2026, month, 13, 13, tzinfo=midday.MARKET_TZ)
            self.assertTrue(midday.in_capture_window(now))
        self.assertFalse(midday.in_capture_window(datetime(2026, 10, 13, 14, tzinfo=midday.MARKET_TZ)))
        self.assertFalse(midday.in_capture_window(datetime(2026, 10, 17, 13, tzinfo=midday.MARKET_TZ)))
        payload = service.plist_payload('America/Denver')
        self.assertFalse(payload['RunAtLoad'])
        self.assertEqual(len(payload['StartCalendarInterval']), 5)

    def test_outside_window_never_fetches(self):
        with patch.object(ops, 'live_chain_report') as fetch:
            report = midday.run_capture(now=datetime(2026, 10, 13, 20, tzinfo=timezone.utc))
        fetch.assert_not_called()
        self.assertEqual(report['status'], 'outside-capture-window')

    def test_capture_receipt_and_duplicate_suppression_without_paper_actions(self):
        chain = {'status': 'ok', 'rows': [{'symbol': 'XYZ', 'status': 'ok', 'quoteSessionIsRegular': True}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(midday, 'CAPTURE_FILE', Path(tmp) / 'capture.json'), patch.object(midday, 'CAPTURE_TEXT_FILE', Path(tmp) / 'capture.txt'), patch.object(ops, 'load_schwab_env'), patch.object(ops, 'default_symbol_universe', return_value=['XYZ']), patch.object(ops, 'live_chain_report', return_value=chain) as fetch, patch.object(ops, 'save_ops_report'), patch('inferno_short_premium_shadow.run', return_value={'lastRun': {'added': 1}, 'summary': {}}) as shadow, patch('inferno_earnings_runner.run', return_value={'lastRun': {}, 'scoreboard': {}}) as runner:
            result = midday.run_capture(now=NOW)
            again = midday.run_capture(now=NOW)
        self.assertEqual(result['status'], 'captured')
        self.assertEqual(again, result)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(shadow.call_count, 1)
        self.assertEqual(runner.call_count, 1)
        self.assertFalse(result['liveTradingAllowed'])
        self.assertFalse(result['brokerSubmitAllowed'])

    def test_failure_is_persisted_and_shadow_not_run(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(midday, 'CAPTURE_FILE', Path(tmp) / 'capture.json'), patch.object(midday, 'CAPTURE_TEXT_FILE', Path(tmp) / 'capture.txt'), patch.object(ops, 'load_schwab_env'), patch.object(ops, 'default_symbol_universe', return_value=['XYZ']), patch.object(ops, 'live_chain_report', side_effect=RuntimeError('token expired')), patch('inferno_short_premium_shadow.run') as shadow, patch('inferno_earnings_runner.run', return_value={'lastRun': {}, 'scoreboard': {}}) as runner:
            result = midday.run_capture(now=NOW)
            saved = midday.load_json_file(midday.CAPTURE_FILE)
        self.assertEqual(saved['status'], 'failed')
        self.assertIn('token expired', result['error'])
        shadow.assert_not_called()

    def test_doctor_rejects_stale_success_receipt(self):
        from inferno_doctor import schwab_midday_capture_status
        self.assertFalse(schwab_midday_capture_status({'status': 'captured', 'marketDate': '2026-10-12'}, now=NOW)[0])
        self.assertTrue(schwab_midday_capture_status({'status': 'captured', 'marketDate': '2026-10-13'}, now=NOW)[0])

    def test_four_coverage_tiers_deduplicate_and_keep_previous_reports(self):
        snapshot={'rows':[{'ticker':'TOMORROW','nextEarnings':'2026-10-14'},
                          {'ticker':'DAY10','nextEarnings':'2026-10-23'},
                          {'ticker':'DAY11','nextEarnings':'2026-10-24'},
                          {'ticker':'NEWDATE','nextEarnings':'2027-01-01'}]}
        runner={'calendar':{'NEWDATE':{'earnings':'2026-10-12'}},
                'reported':{'FRIDAY|2026-10-09':{'earnings':'2026-10-09'}},
                'records':[{'ticker':'OPEN','status':'open'},{'ticker':'CLOSED','status':'closed'},
                           {'ticker':'TOMORROW','status':'open'}]}
        tiers=ops.capture_priority_tiers(snapshot,runner,[{'ticker':'CALL'},{'ticker':'OPEN'}],today=date(2026,10,13))
        self.assertEqual(tiers['reporting1to10Days'],['TOMORROW','DAY10'])
        self.assertEqual(tiers['reportedLast2Sessions'],['NEWDATE','FRIDAY'])
        self.assertEqual(tiers['openRunnerRecords'],['OPEN'])
        self.assertEqual(tiers['operatorCalls'],['CALL'])

    def test_recent_reporting_window_uses_market_holidays(self):
        rows=[{'ticker':'FRIDAY','nextEarnings':'2026-09-04'},
              {'ticker':'THURSDAY','nextEarnings':'2026-09-03'}]
        tiers=ops.capture_priority_tiers({'rows':rows},{},[],today=date(2026,9,8))
        self.assertEqual(tiers['reportedLast2Sessions'],['FRIDAY','THURSDAY'])
