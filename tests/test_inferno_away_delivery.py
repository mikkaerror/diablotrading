"""Exercise actual delivery entry points with temporary state and mocked SMTP."""
import copy
import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import inferno_away as away
import inferno_email_policy as policy
import inferno_approval_dispatch as approvals
import inferno_action_pulse as pulse
import server


class AwayDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.window = self.root / 'away.json'
        self.window.write_text(json.dumps({'windows': [
            {'start': '2026-10-20', 'end': '2026-10-28'}]}))
        self.start_patch(patch.object(policy, 'is_away',
                         side_effect=lambda today: away.is_away(today, self.window)))
        self.now = self.start_patch(patch.object(policy, 'local_now',
            return_value=datetime.fromisoformat('2026-10-22T12:00:00-06:00')))

    def start_patch(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def test_inclusive_window_and_return_with_no_state_mutation(self):
        before = self.window.read_bytes()
        for day, expected in ((19, False), (20, True), (28, True), (29, False)):
            for kind in ('approval', 'action-pulse', 'desk-chief'):
                self.assertEqual(policy.suppress_away_email(kind, today=date(2026, 10, day)), expected)
        self.assertFalse(policy.suppress_away_email('desk-editor', today=date(2026, 10, 22)))
        self.assertEqual(self.window.read_bytes(), before)

    def test_delivery_uses_denver_date_not_utc_or_payload_date(self):
        self.now.return_value = datetime.fromisoformat('2026-10-29T03:00:00+00:00')
        self.assertTrue(policy.suppress_away_email('action-pulse'))
        self.now.return_value = datetime.fromisoformat('2026-10-29T06:00:00+00:00')
        self.assertFalse(policy.suppress_away_email('action-pulse'))

    def test_approval_force_skips_without_reserving_or_marking_sent(self):
        queue = {'items': [{'ticker': 'TEST', 'approvalStatus': 'pending', 'approvalToken': 'TOKEN'}]}
        before = copy.deepcopy(queue)
        for mode in ('full', 'editor'):
            with self.subTest(mode=mode), patch.dict(os.environ, {'INFERNO_EMAIL_MODE': mode}), \
                 patch.object(approvals, 'APPROVAL_DISPATCH_STATE_FILE', self.root / 'dispatch.json'), \
                 patch.object(approvals, 'load_queue', return_value=copy.deepcopy(queue)), \
                 patch.object(approvals, 'save_report') as report_save, \
                 patch.object(approvals, 'load_env_file') as env, \
                 patch.object(approvals, 'smtp_settings') as settings, \
                 patch.object(approvals, 'build_decision_briefs') as briefs, \
                 patch.object(approvals, 'save_state') as state_save, \
                 patch.object(approvals, 'send_operator_email') as send:
                result = approvals.dispatch_pending_approval_prompts(force=True)
                self.assertEqual(result['status'], 'suppressed-away-mode')
                self.assertEqual((result['sentCount'], result['skippedCount']), (0, 1))
                self.assertTrue(result['ok'])
                report_save.assert_called_once()
                for mock in (env, settings, briefs, state_save, send):
                    mock.assert_not_called()
                self.assertFalse((self.root / 'dispatch.json').exists())
        self.assertEqual(queue, before)

    def test_approval_resumes_from_current_queue_after_early_return(self):
        queue = {'items': [{'ticker': 'TEST', 'approvalStatus': 'pending', 'approvalToken': 'TOKEN'}]}
        with patch.object(approvals, 'APPROVAL_DISPATCH_STATE_FILE', self.root / 'dispatch.json'), \
             patch.object(approvals, 'load_queue', side_effect=lambda: copy.deepcopy(queue)), \
             patch.object(approvals, 'save_report'), patch.object(approvals, 'load_env_file'), \
             patch.object(approvals, 'smtp_configured', return_value=True), \
             patch.object(approvals, 'build_decision_briefs', return_value={}), \
             patch.object(approvals, 'send_operator_email') as send:
            self.assertEqual(approvals.dispatch_pending_approval_prompts()['sentCount'], 0)
            away.turn_off(date(2026, 10, 22), self.window)
            self.assertEqual(approvals.dispatch_pending_approval_prompts()['sentCount'], 1)
            self.assertEqual(approvals.dispatch_pending_approval_prompts()['sentCount'], 0)
            send.assert_called_once()

    def test_action_failure_and_force_stay_quiet_but_report_is_saved(self):
        for mode in ('full', 'editor'):
            with self.subTest(mode=mode), patch.dict(os.environ, {'INFERNO_EMAIL_MODE': mode}), \
                 patch.object(pulse, 'ACTION_PULSE_FILE', self.root / 'pulse.json'), \
                 patch.object(pulse, 'ACTION_PULSE_TEXT_FILE', self.root / 'pulse.txt'), \
                 patch.object(pulse, 'load_env_file') as env, \
                 patch.object(pulse, 'load_state') as load, \
                 patch.object(pulse, 'save_state') as save, \
                 patch.object(pulse, 'smtp_settings') as settings:
                payload = {'phase': 'open', 'verdict': 'failed', 'generatedAt': '2026-01-01T12:00:00-07:00'}
                payload['delivery'] = pulse.send_action_pulse(payload, force=True)
                pulse.save_action_pulse(payload)
                self.assertEqual(payload['delivery'], {'attempted': False, 'sent': False,
                                                      'status': 'suppressed-away-mode'})
                self.assertIn('suppressed-away-mode', (self.root / 'pulse.json').read_text())
                for mock in (env, load, save, settings):
                    mock.assert_not_called()

    def test_action_pulse_returns_to_existing_dedupe(self):
        self.now.return_value = datetime.fromisoformat('2026-10-29T12:00:00-06:00')
        with patch.dict(os.environ, {'INFERNO_EMAIL_MODE': 'full'}), \
             patch.object(pulse, 'load_env_file'), \
             patch.object(pulse, 'load_state', return_value={'sentByKey': {'return:open': {}}}), \
             patch.object(pulse, 'sent_key', return_value='return:open'), \
             patch.object(pulse, 'smtp_settings') as settings:
            self.assertEqual(pulse.send_action_pulse({'phase': 'open'})['status'], 'already-sent')
            settings.assert_not_called()

    def test_shared_chief_and_approval_routes_skip_even_alert_subjects(self):
        with patch.object(server, 'smtp_settings') as settings:
            for subject in ('[Inferno Desk Chief] Review', '[Inferno Desk Chief] Failure alert',
                            '[Inferno Approval] TEST TOKEN'):
                self.assertFalse(server.send_email({'brief': 'test'}, subject=subject))
            settings.assert_not_called()
        with patch.dict(os.environ, {'INFERNO_EMAIL_MODE': 'full'}):
            self.assertFalse(policy.suppress_subject('[Inferno Desk] (away) Summary', {}))
            self.assertFalse(policy.suppress_subject('Inferno Watchdog Alert', {}))
        self.now.return_value = datetime.fromisoformat('2026-10-29T12:00:00-06:00')
        self.assertFalse(policy.suppress_subject('[Inferno Desk Chief] Review', {}))


if __name__ == '__main__':
    unittest.main()
