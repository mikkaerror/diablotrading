from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import inferno_refresh_handoff as handoff

START = datetime.fromisoformat('2026-09-08T07:35:00-06:00')
END = START + timedelta(minutes=5)
NOW = START + timedelta(minutes=15)


def sources():
    rows = {name: {'payload': {'generatedAt': (START+timedelta(minutes=1)).isoformat()},
                   'sha256': name+'-content-hash'} for name in handoff.REQUIRED}
    rows['inferno_schwab_options']['payload'].update(status='ok', rows=[{'symbol': 'DELL', 'status': 'ok'}])
    rows['inferno_schwab_daily_ops']['payload'].update(sourceStatus='ok', sourceGeneratedAt=(START+timedelta(minutes=1)).isoformat())
    rows['inferno_strategy_shadow_comparison']['payload']['sourcePricing'] = {'generatedAt': (START+timedelta(minutes=1)).isoformat()}
    return rows


def completed(artifacts=None):
    artifacts = sources() if artifacts is None else artifacts
    return handoff.run_refresh(runner=lambda *_: 0, clock=Mock(side_effect=[START, END]),
                               read_sources=lambda: artifacts, save=lambda _: None)


class RefreshHandoffTests(unittest.TestCase):
    def test_complete_requires_all_artifacts_and_preserves_authority(self):
        receipt = completed()
        self.assertEqual(receipt['status'], 'complete')
        self.assertEqual(len(receipt['steps']), len(handoff.COMMANDS))
        self.assertEqual(receipt['acceptedEvidenceProgress'], 0)
        self.assertIsNone(receipt['monetaryCost'])
        self.assertTrue(receipt['researchOnly'])
        for field in ('promotable', 'authorityChanged', 'brokerSubmitAllowed', 'liveTradingAllowed'):
            self.assertFalse(receipt[field])
        self.assertTrue(handoff.brief_readiness(receipt, now=NOW, artifacts=sources())['ready'])

    def test_successful_commands_cannot_freshen_missing_old_or_future_inputs(self):
        for name in handoff.REQUIRED:
            for stamp in (None, (START-timedelta(minutes=1)).isoformat(), (END+timedelta(seconds=1)).isoformat()):
                with self.subTest(name=name, stamp=stamp):
                    artifacts = sources()
                    artifacts[name]['payload']['generatedAt'] = stamp
                    self.assertEqual(completed(artifacts)['status'], 'blocked')

    def test_empty_or_failed_chain_source_blocks(self):
        for value in ({'status': 'error', 'rows': [{}]}, {'status': 'ok', 'rows': []}, {'status': 'ok', 'rows': 'bad'}):
            artifacts = sources()
            artifacts['inferno_schwab_options']['payload'].update(value)
            self.assertEqual(completed(artifacts)['status'], 'blocked')

    def test_ops_must_reference_this_chain_source(self):
        artifacts = sources()
        artifacts['inferno_schwab_daily_ops']['payload']['sourceGeneratedAt'] = START.isoformat()
        self.assertEqual(completed(artifacts)['status'], 'blocked')

    def test_shadow_cannot_claim_completion_using_old_pricing(self):
        artifacts = sources()
        artifacts['inferno_strategy_shadow_comparison']['payload']['sourcePricing']['generatedAt'] = START.isoformat()
        self.assertEqual(completed(artifacts)['status'], 'blocked')

    def test_changed_dependency_hash_blocks_even_when_timestamp_unchanged(self):
        receipt = completed()
        for name in handoff.REQUIRED:
            artifacts = sources()
            artifacts[name]['sha256'] = 'changed'
            self.assertFalse(handoff.brief_readiness(receipt, now=NOW, artifacts=artifacts)['ready'])

    def test_missing_receipt_and_incomplete_or_malformed_receipts_block(self):
        for receipt in ({}, [], ['bad'], {'status': 'running'}, {'status': 'failed'}, {'status': 'blocked'}):
            self.assertFalse(handoff.brief_readiness(receipt, now=NOW, artifacts=sources())['ready'])
        for field in ('sources',):
            receipt = completed()
            receipt[field] = ['bad']
            self.assertFalse(handoff.brief_readiness(receipt, now=NOW, artifacts=sources())['ready'])

    def test_receipt_age_future_clock_and_previous_session_block(self):
        receipt = completed()
        for now in (START, END+timedelta(hours=1, seconds=1), NOW+timedelta(days=1)):
            self.assertFalse(handoff.brief_readiness(receipt, now=now, artifacts=sources())['ready'])

    def test_authority_flags_cannot_be_laundered_through_receipt(self):
        receipt = completed()
        receipt['brokerSubmitAllowed'] = True
        self.assertFalse(handoff.brief_readiness(receipt, now=NOW, artifacts=sources())['ready'])

    def test_failure_stops_downstream_and_invalidates_previous_running_receipt(self):
        saved = []
        runner = Mock(side_effect=[0, 7])
        reader = Mock()
        receipt = handoff.run_refresh(runner=runner, clock=Mock(side_effect=[START, END]),
                                     read_sources=reader, save=lambda p: saved.append(copy.deepcopy(p)))
        self.assertEqual([p['status'] for p in saved], ['running', 'failed'])
        self.assertEqual(receipt['steps'][-1]['returnCode'], 7)
        self.assertEqual(runner.call_count, 2)
        reader.assert_not_called()

    def test_timeout_is_failed_and_no_downstream_step_runs(self):
        runner = Mock(side_effect=subprocess.TimeoutExpired('daily ops', 180))
        receipt = handoff.run_refresh(runner=runner, clock=Mock(side_effect=[START, END]), save=lambda _: None)
        self.assertEqual(receipt['status'], 'failed')
        self.assertIn('TimeoutExpired', receipt['reason'])
        runner.assert_called_once()
        self.assertLessEqual(runner.call_args.args[1], 180)

    def test_holiday_weekend_preopen_and_afterclose_do_not_execute(self):
        for raw in ('2026-09-07T07:35:00-06:00', '2026-09-12T07:35:00-06:00',
                    '2026-09-08T07:29:00-06:00', '2026-09-08T14:00:00-06:00'):
            runner = Mock()
            receipt = handoff.run_refresh(runner=runner, clock=lambda: datetime.fromisoformat(raw), save=lambda _: None)
            self.assertEqual(receipt['status'], 'market-closed')
            runner.assert_not_called()

    def test_malformed_input_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(handoff, 'DATA_DIR', Path(temp)):
            for text in ('[]', '{invalid', 'null', '"bad"'):
                for name in handoff.REQUIRED:
                    (Path(temp)/f'{name}.json').write_text(text)
                self.assertEqual(completed(handoff.read_artifacts())['status'], 'blocked')

    def test_digest_labels_source_build_times_and_pre_refresh_phase(self):
        with patch.object(handoff, 'read_artifacts', return_value=sources()):
            basis = handoff.source_basis(now=START-timedelta(minutes=5))
        self.assertEqual(basis['phase'], 'pre-market-open-refresh')
        self.assertEqual(len(basis['sourceGeneratedAt']), len(handoff.REQUIRED))
        from inferno_daily_loop import daily_loop_text
        rendered = daily_loop_text({'sourceBasis': basis})
        self.assertIn('pre-market-open-refresh', rendered)
        self.assertIn('inferno_schwab_options built:', rendered)

    def test_doctor_requires_daily_completion_but_not_perpetual_one_hour_freshness(self):
        self.assertTrue(handoff.refresh_handoff_status({}, START)[0])
        self.assertFalse(handoff.refresh_handoff_status({}, NOW+timedelta(minutes=10))[0])
        self.assertTrue(handoff.refresh_handoff_status(completed(), NOW+timedelta(hours=5))[0])

    def test_guarded_morning_stops_before_any_network_or_email_on_missing_receipt(self):
        import morning_inferno_pipeline as pipeline
        with (patch('sys.argv', ['morning_inferno_pipeline.py', '--cloud-native', '--skip-updates', '--require-market-open-refresh']),
              patch.object(pipeline, 'load_env_file'),
              patch.object(pipeline, 'brief_readiness', return_value={'ready': False, 'status': 'awaiting-refresh'}),
              patch.object(pipeline, 'sync_score_formulas') as formulas,
              patch.object(pipeline, 'send_email') as email,
              patch.object(pipeline, 'send_failure_email') as failure_email):
            self.assertEqual(pipeline.main(), 2)
        formulas.assert_not_called()
        email.assert_not_called()
        failure_email.assert_not_called()

    def test_guarded_morning_refuses_competing_full_refresh(self):
        import morning_inferno_pipeline as pipeline
        with (patch('sys.argv', ['morning_inferno_pipeline.py', '--cloud-native', '--require-market-open-refresh']),
              patch.object(pipeline, 'load_env_file'), patch.object(pipeline, 'brief_readiness') as guard):
            self.assertEqual(pipeline.main(), 2)
        guard.assert_not_called()

    def test_prompt_audit_rejects_previous_unguarded_morning_flow(self):
        from inferno_central_command import _prompt_audit
        self.assertFalse(_prompt_audit('morning-conviction-brief', 'python3 morning_inferno_pipeline.py --cloud-native')['ok'])
        prompt = Path('coordination/prompts/morning_conviction_brief.md').read_text()
        self.assertTrue(_prompt_audit('morning-conviction-brief', prompt)['ok'])
        prompt = Path('coordination/prompts/market_open_refresh.md').read_text()
        self.assertTrue(_prompt_audit('inferno-market-open-options-research-refresh', prompt)['ok'])


if __name__ == '__main__':
    unittest.main()
