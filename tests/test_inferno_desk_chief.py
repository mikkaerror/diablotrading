import copy
import hashlib
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import inferno_desk_chief as chief
import inferno_desk_chief_runner as runner

NOW = datetime(2026, 9, 30, 14, tzinfo=timezone.utc)


class DeskChiefTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.dict(os.environ, {'BROKER_ADAPTER_MODE': 'OFF'}))
        self.stack.enter_context(patch.object(runner, 'local_now', return_value=NOW))
        self.write('guard.py', 'GUARD = False\n', raw=True)
        self.write(chief.MANDATE, {'active': True, 'scope': 'desk-operations-only',
                                  'protectedSources': {'guard.py': hashlib.sha256(b'GUARD = False\n').hexdigest()}})
        self.write('data/inferno_authority_manifest.json', {'generatedAt': NOW.isoformat(), 'decision': {
            'liveTradingAllowed': False, 'brokerSubmitAllowed': False, 'brokerAdapterMode': 'OFF',
            'blockedActions': {'submit_live_order': []}}})
        self.role = {'id': 'funnel', 'title': 'Funnel', 'owner': 'codex', 'artifact': 'data/funnel.json',
                     'maxAgeHours': 36, 'check': 'artifact', 'repairAction': 'refresh-funnel'}
        self.write(chief.REGISTRY, {'roles': [self.role]})
        self.write('coordination/active_missions.json', [
            {'id': 'done', 'status': 'completed'}, {'id': 'also-done', 'status': 'done'},
            {'id': 'active', 'status': 'in-progress', 'owner': 'claude'}])

    def write(self, name, value, raw=False):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value if raw else json.dumps(value))

    def repair(self, action, root):
        self.write('data/funnel.json', {'generatedAt': NOW.isoformat(), 'ok': True})
        return {'returncode': 0, 'seconds': 1, 'action': action}

    def test_missing_evidence_creates_owned_assignment_and_never_counts_completed_missions(self):
        result = chief.build_report(self.root, NOW)
        self.assertTrue(result['safety']['passed'])
        task = next(t for t in result['assignments'] if t['key'] == 'role:funnel')
        self.assertEqual(task['owner'], 'codex')
        self.assertEqual([m['id'] for m in result['activeMissions']], ['active'])
        self.assertFalse(result['liveTradingAllowed'])
        self.assertFalse(result['brokerSubmitAllowed'])
        self.assertIsNone(result['operatingMargin']['dollarsPerAcceptedOutcome'])

    def test_zero_exit_without_fixed_acceptance_is_not_progress_and_skip_keeps_deadline(self):
        with patch.object(runner, 'execute'):
            result = runner.run_chief(self.root, NOW, executor=lambda *_: {'returncode': 0, 'seconds': 2})
        self.assertEqual(result['dispatch']['accepted'], 0)
        prior = json.loads((self.root / chief.STATE).read_text())
        deadline = prior['attempts']['role:funnel']['nextRetryAt']
        calls = []
        second = runner.run_chief(self.root, NOW + timedelta(minutes=5), executor=lambda *_: calls.append(1))
        self.assertEqual(calls, [])
        self.assertEqual(second['dispatch']['suppressed'], 1)
        self.assertEqual(json.loads((self.root / chief.STATE).read_text())['attempts']['role:funnel']['nextRetryAt'], deadline)

    def test_successful_repair_is_accepted_once_and_never_promoted_to_research_evidence(self):
        result = runner.run_chief(self.root, NOW, executor=self.repair)
        self.assertEqual(result['dispatch']['accepted'], 1)
        self.assertEqual(result['operatingMargin']['chief']['acceptedResearchOutcomes'], 0)
        with patch.object(runner, 'execute') as execute:
            second = runner.run_chief(self.root, NOW, executor=execute)
            execute.assert_not_called()
        self.assertEqual(second['operatingMargin']['chief']['executed'], 1)

    def test_safety_hold_blocks_all_dispatch_even_if_worker_is_due(self):
        self.write('guard.py', 'GUARD = True\n', raw=True)
        calls = []
        report = runner.run_chief(self.root, NOW, executor=lambda *_: calls.append(1))
        self.assertEqual(calls, [])
        self.assertEqual(report['verdict'], 'safety-hold')
        self.assertIn('Protected source changed', report['safety']['reasons'][0])

    def test_expired_or_unknown_authority_and_runtime_broker_mode_fail_closed(self):
        self.write('data/inferno_authority_manifest.json', {'generatedAt': (NOW-timedelta(days=3)).isoformat()})
        self.assertFalse(chief.safety(self.root, NOW)['passed'])
        with patch.dict(os.environ, {'BROKER_ADAPTER_MODE': 'LIVE'}):
            self.assertIn('Runtime broker adapter is not OFF', chief.safety(self.root, NOW)['reasons'])

    def test_unknown_action_cannot_execute_arbitrary_command(self):
        with patch.object(runner.subprocess, 'run') as run:
            with self.assertRaises(PermissionError):
                runner.execute('approve-paper-ticket; send-email', self.root)
            run.assert_not_called()

    def test_external_missing_receipt_is_unverified_not_failure_and_future_role_not_due(self):
        external = {**self.role, 'check': 'external', 'dueAfter': '2026-10-29'}
        self.assertEqual(chief.role_status(external, {}, 'missing', NOW, self.root)[0], 'not-due')
        external.pop('dueAfter')
        self.assertEqual(chief.role_status(external, {}, 'missing', NOW, self.root)[0], 'unverified')

    def test_fresh_failure_and_future_timestamp_do_not_pass(self):
        for source in ({'generatedAt': NOW.isoformat(), 'ok': False},
                       {'generatedAt': (NOW+timedelta(hours=1)).isoformat(), 'ok': True}):
            self.assertNotEqual(chief.role_status(self.role, source, None, NOW, self.root)[0], 'verified')

    def test_current_source_fingerprint_required_for_accepting_engineering_work(self):
        role = {**self.role, 'check': 'verification'}
        proof = {'generatedAt': NOW.isoformat(), 'accepted': True,
                 'sourceFingerprint': chief.code_fingerprint(self.root)}
        self.assertEqual(chief.role_status(role, proof, None, NOW, self.root)[0], 'verified')
        self.write('changed.py', 'different = True\n', raw=True)
        self.assertEqual(chief.role_status(role, proof, None, NOW, self.root)[0], 'unverified')

    def test_claim_prevents_duplicate_worker_and_enforces_assignee(self):
        runner.run_chief(self.root, NOW, executor=lambda *_: {'returncode': 1, 'seconds': 1})
        with self.assertRaises(PermissionError): runner.claim_task('role:funnel', 'claude', self.root, NOW)
        claimed = runner.claim_task('role:funnel', 'codex', self.root, NOW)
        self.assertEqual(claimed['status'], 'in-progress')
        with self.assertRaises(PermissionError): runner.claim_task('role:funnel', 'codex', self.root, NOW)
        with patch.object(runner, 'execute') as execute:
            runner.run_chief(self.root, NOW+timedelta(minutes=61), executor=execute)
            execute.assert_not_called()

    def test_corrupt_state_stops_instead_of_replaying_work(self):
        self.write(chief.STATE, '{', raw=True)
        with self.assertRaises(ValueError): runner.run_chief(self.root, NOW, executor=self.repair)

    def test_stale_clock_does_not_generate_a_new_meaningful_state_every_review(self):
        self.write('data/funnel.json', {'generatedAt': (NOW-timedelta(days=3)).isoformat()})
        first = chief.build_report(self.root, NOW)
        second = chief.build_report(self.root, NOW+timedelta(hours=1))
        self.assertEqual(first['meaningfulState'], second['meaningfulState'])

    def test_source_copy_includes_untracked_checks_but_excludes_private_data(self):
        self.write('scripts/check.sh', '#!/bin/sh\ntrue\n', raw=True)
        self.write('data/private.json', {'private': True})
        self.write('data/operator_long_term_holds.json', {'fixturePolicy': True})
        self.write('outputs/position-strategy-2026-09-10/analyze.py', 'fixed = True\n', raw=True)
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner.subprocess, 'check_output', return_value=b'guard.py\0data/private.json\0'):
            runner.source_copy(self.root, tmp)
            self.assertEqual(chief.code_fingerprint(self.root), chief.code_fingerprint(tmp))
            self.assertFalse((Path(tmp) / 'data/private.json').exists())
            self.assertTrue((Path(tmp) / 'data/operator_long_term_holds.json').is_file())
            self.assertTrue((Path(tmp) / 'outputs/position-strategy-2026-09-10/analyze.py').is_file())

    def test_timestamp_without_lineage_truth_is_not_accepted(self):
        role = {**self.role, 'check': 'lineage'}
        source = {'generatedAt': NOW.isoformat(), 'researchOnly': True}
        self.assertEqual(chief.role_status(role, source, None, NOW, self.root)[0], 'attention')
        source.update(liveTradingAllowed=False, brokerSubmitAllowed=False,
                      promotionTruth={'qualified': 1, 'source': 'promotion-evidence-lineage'})
        self.assertEqual(chief.role_status(role, source, None, NOW, self.root)[0], 'verified')
        source['integrityAttention'] = ['unreconciled close']
        self.assertEqual(chief.role_status(role, source, None, NOW, self.root)[0], 'attention')

    def test_cloud_cost_requires_actual_billing_provenance(self):
        cost = {'observedAt': NOW.isoformat(), 'cloudSpend': 0}
        self.write('data/desk_chief_cost_observations.json', cost)
        self.assertFalse(chief.build_report(self.root, NOW)['operatingMargin']['cloudCostKnown'])
        cost['cloudSpend'] = {'observedAt': NOW.isoformat(), 'provider': 'test-provider', 'billingPeriod': '2026-09',
                             'source': 'fixture-billing-export', 'currency': 'USD',
                             'basis': 'actual-billed', 'amount': 0}
        self.write('data/desk_chief_cost_observations.json', cost)
        self.assertTrue(chief.build_report(self.root, NOW)['operatingMargin']['cloudCostKnown'])
        cost['cloudSpend']['observedAt'] = (NOW-timedelta(days=3)).isoformat()
        self.write('data/desk_chief_cost_observations.json', cost)
        self.assertFalse(chief.build_report(self.root, NOW)['operatingMargin']['cloudCostKnown'])
        cost['cloudSpend']['basis'] = 'estimate'
        self.write('data/desk_chief_cost_observations.json', cost)
        self.assertFalse(chief.build_report(self.root, NOW)['operatingMargin']['cloudCostKnown'])

    def test_one_action_budget_and_persistent_cost_counters(self):
        self.write(chief.REGISTRY, {'roles': [self.role, {**self.role, 'id': 'second'}]})
        calls = []
        def worker(*args):
            calls.append(args)
            return {'returncode': 1, 'seconds': 2}
        report = runner.run_chief(self.root, NOW, executor=worker)
        self.assertEqual(len(calls), 1)
        self.assertEqual(report['dispatch']['executed'], 1)
        self.assertEqual(chief.build_report(self.root, NOW)['operatingMargin']['chiefCounters']['seconds'], 2)

    def test_cli_routes_and_doctor_detects_safety_hold(self):
        from inferno_central_command import build_parser
        from inferno_doctor import desk_chief_status
        parsed = build_parser().parse_args(['chief', 'claim', 'role:funnel', '--owner', 'codex'])
        self.assertEqual(parsed.chief_args, ['claim', 'role:funnel', '--owner', 'codex'])
        report = chief.build_report(self.root, NOW)
        with patch('inferno_doctor.recent_or_today', return_value=True):
            self.assertTrue(desk_chief_status(report)[0])
            report['safety']['passed'] = False
            self.assertFalse(desk_chief_status(report)[0])

    def test_verification_diagnostics_retain_stderr_when_fixtures_print(self):
        from inferno_deploy_preflight import run_check
        with patch('inferno_deploy_preflight.run_command', return_value={
            'ok': False, 'returncode': 1, 'stdout': 'fixture output',
            'stderr': 'FAILED: actual assertion', 'command': 'unit-tests'}):
            check = run_check('unit-tests', ['python3'])
        self.assertIn('actual assertion', check['detail'])
        self.assertIn('fixture output', check['detail'])
