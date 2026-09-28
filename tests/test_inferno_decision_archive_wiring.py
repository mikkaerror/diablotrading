import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_central_command as central
import inferno_doctor as doctor
import inferno_model_command_center as center
import inferno_decision_archive as archive
import today


class ArchiveWiringTests(unittest.TestCase):
    def test_cli_forwards_history_query_without_actions(self):
        with patch('sys.argv',['inferno','archive','history','--ticker','TEST']), patch.object(central,'run_passthrough_command',return_value={'returncode':0}) as run:
            self.assertEqual(central.main(),0)
        run.assert_called_once_with(['python3','inferno_decision_archive.py','history','--ticker','TEST'],timeout_seconds=180)

    def test_doctor_rejects_stale_unsafe_or_unverified_archive(self):
        report={'stage':archive.ARCHIVE_STAGE,'generatedAt':archive.now_iso(),'verdict':'healthy',
                'researchOnly':True,'promotable':False,'authorityChanged':False,'liveTradingAllowed':False,
                'brokerSubmitAllowed':False,'integrity':{'ok':True},'counts':{}}
        self.assertTrue(doctor.decision_archive_status(report)[0])
        for change in ({'generatedAt':'2000-01-01'},{'verdict':'attention'},{'integrity':{'ok':False}},
                       {'promotable':True},{'liveTradingAllowed':True},{'brokerSubmitAllowed':True}):
            self.assertFalse(doctor.decision_archive_status({**report,**change})[0])
        self.assertFalse(doctor.decision_archive_status({})[0])

    def test_operator_log_is_captured_after_close_without_new_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'operator_decisions.csv'
            with patch.object(today,'DECISIONS_LOG',path), patch.object(archive,'code_receipt',return_value={}):
                today._log_decision('TEST','skip',note='fixture')
            row=archive.show(Path(temp)/'decision_archive',1)
            self.assertEqual(row['sourceRecord']['action'],'skip')
            self.assertEqual(row['summary']['decisionRationaleStatus'],'not-recorded')

    def test_daily_refresh_and_command_center_surface_archive(self):
        script=Path('run_inferno_daily_model_refresh.sh').read_text()
        self.assertLess(script.index('"decision archive"'),script.index('"model command center"'))
        self.assertTrue(any(r['lane']=='decision-archive' for r in center.REPORTING_MAP))
        self.assertIn('"decisionArchive": summarize_artifact(DECISION_ARCHIVE_FILE',Path('inferno_model_command_center.py').read_text())

    def test_housekeeping_patterns_do_not_delete_archive(self):
        from inferno_housekeeping import SNAPSHOT_PATTERNS, BRIEF_PATTERNS, TICKET_PATTERNS
        from fnmatch import fnmatch
        self.assertTrue(all(not fnmatch('decision_archive/archive.sqlite3',pattern) for pattern in (*SNAPSHOT_PATTERNS,*BRIEF_PATTERNS,*TICKET_PATTERNS)))

    def test_pass_reason_captured_inline_without_extra_prompt_or_approval(self):
        for answer, expected in (("s Awaiting SEC filing", "skip"), ("n Thesis invalidated", "reject")):
            with patch.object(today, '_prompt', return_value=answer) as prompt, patch.object(today, '_log_decision') as log, patch.object(today, '_reject_via_queue', return_value=0) as reject, patch.object(today, '_approve_via_queue') as approve:
                self.assertEqual(today.run_one({'ticker':'TEST'}), expected)
                self.assertEqual(log.call_args.kwargs['rationale'], answer.split(maxsplit=1)[1])
                prompt.assert_called_once()
                approve.assert_not_called()
                self.assertEqual(reject.call_count, 1 if expected == 'reject' else 0)

    def test_bare_skip_keeps_reason_unknown_and_never_mutates_queue(self):
        with patch.object(today, '_prompt', return_value='s'), patch.object(today, '_log_decision') as log, patch.object(today, '_reject_via_queue') as reject:
            self.assertEqual(today.run_one({'ticker':'TEST'}), 'skip')
            self.assertEqual(log.call_args.kwargs['rationale'], '')
            reject.assert_not_called()

    def test_doctor_detects_pending_capture_after_last_healthy_report(self):
        report={'stage':archive.ARCHIVE_STAGE,'generatedAt':archive.now_iso(),'verdict':'healthy',
                'researchOnly':True,'promotable':False,'authorityChanged':False,'liveTradingAllowed':False,
                'brokerSubmitAllowed':False,'integrity':{'ok':True},'counts':{}}
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp); (directory/'pending').mkdir()
            (directory/'pending'/'interrupted.capture').write_text('pending')
            self.assertFalse(doctor.decision_archive_status(report,directory)[0])
