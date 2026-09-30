import json
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import inferno_mac_paper_cycle as cycle
import inferno_canonical_paper_snapshot as snapshots


class PublicationRecoveryTests(unittest.TestCase):
    def test_doctor_keeps_queued_and_legacy_unverified_publications_visible(self):
        from inferno_doctor import canonical_publication_status
        for state in ({'ok': True}, {'ok': False, 'publication': {'status': 'queued', 'error': 'upload'}}):
            ok, detail = canonical_publication_status(state)
            self.assertFalse(ok)
            self.assertIn('status=', detail)
        self.assertTrue(canonical_publication_status({'ok': True, 'publication': {'status': 'published'}})[0])

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        (root / 'data').mkdir()
        self.stack.enter_context(patch.object(cycle, 'ROOT', root))
        self.stack.enter_context(patch.object(cycle, 'STATE', root / 'data/state.json'))
        self.stack.enter_context(patch.object(cycle, 'require_paper_writer'))
        self.now = datetime(2026, 9, 30, 7, tzinfo=timezone(timedelta(hours=-6)))
        self.stack.enter_context(patch('inferno_config.local_now', return_value=self.now))
        self.stack.enter_context(patch.object(snapshots, 'snapshot', return_value=({'revision': 'new'}, {})))
        self.state = {'inputRevision': 'same', 'returncode': 0, 'ok': True}

    def test_changed_sources_retry_once_without_replaying_staging(self):
        with patch.object(snapshots, 'publish', side_effect=[
                RuntimeError('Canonical sources changed during publication; retry snapshot'),
                {'status': 'published', 'revision': 'new'}]) as publish:
            self.assertEqual(cycle.publish_pending(self.state), 0)
        self.assertEqual(publish.call_count, 2)
        saved = json.loads(cycle.STATE.read_text())
        self.assertTrue(saved['ok'])
        self.assertEqual(saved['publication']['revision'], 'new')

    def test_repeated_race_is_durably_queued_and_cooldown_is_visible(self):
        with patch.object(snapshots, 'publish', side_effect=RuntimeError(
                'Canonical sources changed during publication; retry snapshot')) as publish:
            self.assertEqual(cycle.publish_pending(self.state), 1)
            self.assertEqual(publish.call_count, 2)
            saved = json.loads(cycle.STATE.read_text())
            self.assertEqual(saved['publication']['status'], 'queued')
            self.assertFalse(saved['ok'])
            self.assertEqual(cycle.publish_pending(saved), 1)
            self.assertEqual(publish.call_count, 2)

    def test_same_staging_input_retries_due_publication_only(self):
        self.state['publication'] = {'status': 'queued', 'consecutiveFailures': 1,
            'nextRetryAt': (self.now - timedelta(seconds=1)).isoformat()}
        cycle.STATE.write_text(json.dumps(self.state))
        with patch('sys.argv', ['cycle']), patch.object(cycle, 'input_revision', return_value='same'), \
             patch.object(cycle, 'approved_budget_environment', return_value={}), \
             patch.object(cycle.subprocess, 'run') as staging, \
             patch.object(snapshots, 'publish', return_value={'status': 'published', 'revision': 'new'}) as publish:
            self.assertEqual(cycle.main(), 0)
            staging.assert_not_called()
            publish.assert_called_once()

    def test_unchanged_published_snapshot_avoids_network_and_preserves_success_time(self):
        self.state['publication'] = {'status': 'published', 'revision': 'new', 'lastSuccessfulAt': 'earlier'}
        with patch.object(snapshots, 'publish') as publish:
            self.assertEqual(cycle.publish_pending(self.state), 0)
            publish.assert_not_called()
        self.assertEqual(self.state['publication']['lastSuccessfulAt'], 'earlier')

    def test_interrupted_attempt_retries_after_finite_backoff(self):
        self.state['publication'] = {'status': 'publishing', 'consecutiveFailures': 2,
            'nextRetryAt': (self.now - timedelta(seconds=1)).isoformat()}
        with patch.object(snapshots, 'publish', side_effect=RuntimeError('upload unavailable')):
            self.assertEqual(cycle.publish_pending(self.state), 1)
        receipt = self.state['publication']
        self.assertEqual(receipt['consecutiveFailures'], 3)
        self.assertEqual(datetime.fromisoformat(receipt['nextRetryAt']) - self.now, timedelta(seconds=1200))

    def test_successful_publication_does_not_hide_staging_failure(self):
        self.state['returncode'] = 3
        with patch.object(snapshots, 'publish', return_value={'status': 'published', 'revision': 'new'}):
            self.assertEqual(cycle.publish_pending(self.state), 3)
        self.assertFalse(self.state['ok'])
