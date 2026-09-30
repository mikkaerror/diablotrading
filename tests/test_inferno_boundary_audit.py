import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from inferno_boundary_audit import build_boundary_audit, review_status


class BoundaryAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        self.write('inferno_config.py', 'CAP = 500\n')
        self.commit('Initial fixture')
        self.base = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True, stderr=subprocess.PIPE)

    def write(self, path, value):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value)

    def commit(self, title='Change\n\nAgent-Author: codex'):
        self.git('add', '.')
        self.git('commit', '-qm', title)
        return self.git('rev-parse', 'HEAD').strip()

    def evidence(self, commit, reviewer='claude'):
        note = {'id': 'review-1', 'author': reviewer, 'createdAt': '2026-09-30T15:00:00Z',
                'body': f'[four-eyes commit={commit} author=codex verdict=approved] Reviewed full diff, tests and unchanged live boundary.'}
        ack = {'scope': 'four-eyes-change', 'active': True, 'operator': 'Mikka',
               'changeCommit': commit, 'authorAgent': 'codex', 'reviewNoteId': 'review-1',
               'approvedAt': '2026-09-30T15:01:00Z', 'operatorStatement': 'OK for this exact change.'}
        self.write('coordination/model_notes.jsonl', json.dumps(note) + '\n')
        self.write('coordination/operator_acks/change.json', json.dumps(ack))
        return note, ack

    def test_exact_peer_and_operator_evidence_required_and_rechecked(self):
        self.write('inferno_config.py', 'CAP = 600\n')
        commit = self.commit()
        self.assertFalse(build_boundary_audit(self.root, base=self.base)['ok'])
        self.evidence(commit)
        report = build_boundary_audit(self.root, base=self.base)
        self.assertTrue(report['ok'], report)
        self.write('README.md', 'unrelated later commit')
        self.commit('Docs')
        self.assertTrue(build_boundary_audit(self.root, base=self.base)['ok'])
        (self.root / 'coordination/operator_acks/change.json').unlink()
        self.assertFalse(build_boundary_audit(self.root, base=self.base)['ok'])

    def test_self_review_reused_note_revoked_wrong_commit_and_missing_ack(self):
        commit = 'a' * 40
        note, ack = self.evidence(commit)
        for changes in ({'active': False}, {'active': 'true'}, {'operator': 'codex'},
                        {'changeCommit': 'b' * 40}, {'reviewNoteId': 'wrong'}, {'operatorStatement': ''}):
            with self.subTest(changes=changes):
                self.assertFalse(review_status(commit, 'codex', [note], [{**ack, **changes}])['passed'])
        self.assertFalse(review_status(commit, 'codex', [{**note, 'author': 'codex'}], [ack])['passed'])
        self.assertFalse(review_status(commit, 'codex', [note, note], [ack])['passed'])
        self.assertFalse(review_status(commit, None, [note], [ack])['passed'])
        self.assertFalse(review_status(commit, 'codex', [note], [ack, {**ack, 'active': False}])['passed'])

    def test_unknown_history_and_dirty_files_fail_closed(self):
        self.assertFalse(build_boundary_audit(self.root, base='f' * 40)['ok'])
        self.write('inferno_config.py', 'CAP = 1000\n')
        report = build_boundary_audit(self.root, base=self.base)
        self.assertIn('inferno_config.py', report['uncommittedSafetyPaths'])
        self.assertFalse(report['ok'])

    def test_registry_and_registered_collector_are_protected_even_after_removal(self):
        registry = {'experiments': {'new': {'doc': 'docs/NEW.md', 'module': 'new_collector'}}}
        self.write('research/prereg_registry.json', json.dumps(registry))
        self.write('new_collector.py', 'RULE = 1\n')
        self.write('docs/NEW.md', 'Frozen')
        first = self.commit()
        report = build_boundary_audit(self.root, base=self.base)
        self.assertIn('new_collector.py', report['commits'][0]['paths'])
        self.evidence(first)
        self.write('research/prereg_registry.json', '{"experiments": {}}')
        self.write('new_collector.py', 'RULE = 2\n')
        self.commit()
        report = build_boundary_audit(self.root, base=self.base)
        self.assertIn('new_collector.py', report['commits'][-1]['paths'])
        self.assertFalse(report['ok'])

    def test_unreviewed_intermediate_change_cannot_be_hidden_by_revert(self):
        self.write('inferno_config.py', 'CAP = 600\n')
        self.commit()
        self.write('inferno_config.py', 'CAP = 500\n')
        self.commit()
        report = build_boundary_audit(self.root, base=self.base)
        self.assertEqual(len(report['commits']), 2)
        self.assertFalse(report['ok'])

    def test_docs_only_and_malformed_records(self):
        self.write('README.md', 'Docs')
        self.commit('Docs')
        self.assertTrue(build_boundary_audit(self.root, base=self.base)['ok'])
        self.write('coordination/model_notes.jsonl', '{broken')
        self.assertFalse(build_boundary_audit(self.root, base=self.base)['ok'])

    def test_stdout_only_mode_writes_no_report_or_bytecode(self):
        script = Path(__file__).resolve().parents[1] / 'inferno_boundary_audit.py'
        result = subprocess.run(['python3', '-B', str(script), '--root', str(self.root), '--check'],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)  # adoption history absent in fixture
        self.assertIn('Audit incomplete', result.stdout)
        self.assertFalse((self.root / 'data').exists())
        self.assertFalse((self.root / 'reports').exists())

    def test_legacy_safety_list_is_covered(self):
        from inferno_boundary_audit import protected
        for name in ('inferno_config.py', 'inferno_authority_controller.py', 'inferno_risk_policy.py',
                     'inferno_math_config.py', 'inferno_ticket_cap_policy.py', 'research/prereg_registry.json'):
            self.assertTrue(protected(name), name)
