from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

import inferno_desk_editor_mailer as mailer
import inferno_dawn_pipeline as dawn

MT = timezone(timedelta(hours=-6))


def payload() -> dict:
    return {
        "headline": "1 decision today",
        "money": {"nlv": 845.85, "cash": 249.33, "peakNlv": None, "fromPeakPct": None,
                  "ageHours": 5.0, "fresh": True, "performance": None,
                  "drawdownLevel": None, "newLiveEntriesAllowed": None},
        "decisions": [], "delegated": [], "positions": {"live": [], "paperActions": []},
        "evidence": {"scoredPaper": 3, "promotionSample": 30, "shadow": []},
        "capexFlow": None, "alerts": [], "longTerm": [],
    }


class MailerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state.json"
        self.email = Path(self.tmp.name) / "email.txt"
        self.sent = []

    def tearDown(self):
        self.tmp.cleanup()

    def _deliver(self, now, **kw):
        return mailer.deliver(
            now, runner=lambda cmd: (0, ""), sender=lambda s, b: self.sent.append((s, b)) or {"sent": True, "status": "sent"},
            state_path=self.state, email_path=self.email, builder=payload, **kw,
        )

    def test_window_weekday_morning_only(self):
        self.assertTrue(mailer.in_send_window(datetime(2026, 9, 30, 6, 5, tzinfo=MT)))
        self.assertFalse(mailer.in_send_window(datetime(2026, 9, 30, 5, 59, tzinfo=MT)))
        self.assertFalse(mailer.in_send_window(datetime(2026, 9, 30, 11, 0, tzinfo=MT)))
        self.assertFalse(mailer.in_send_window(datetime(2026, 10, 4, 7, 0, tzinfo=MT)))  # Sunday

    def test_sends_once_per_day(self):
        now = datetime(2026, 9, 30, 6, 10, tzinfo=MT)
        first = self._deliver(now)
        second = self._deliver(now.replace(minute=20))
        self.assertTrue(first["sent"])
        self.assertEqual(second["status"], "already-sent")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][0], "[Inferno Desk] Wed Sep 30 — 1 decision today")
        self.assertIn("Subject: [Inferno Desk]", self.email.read_text())
        self.assertIn("2026-09-30", json.loads(self.state.read_text())["sentByDate"])

    def test_outside_window_is_noop(self):
        result = self._deliver(datetime(2026, 9, 30, 22, 0, tzinfo=MT))
        self.assertEqual(result["status"], "outside-window")
        self.assertEqual(self.sent, [])

    def test_failed_steps_are_listed_not_fatal(self):
        now = datetime(2026, 9, 30, 6, 10, tzinfo=MT)
        result = mailer.deliver(
            now, runner=lambda cmd: (1, "boom") if "inferno_vol_edge.py" in cmd else (0, ""),
            sender=lambda s, b: self.sent.append((s, b)) or {"sent": True, "status": "sent"},
            state_path=self.state, email_path=self.email, builder=payload,
        )
        self.assertTrue(result["sent"])
        self.assertIn("PIPELINE NOTES", self.sent[0][1])
        self.assertIn("vol edge: boom", self.sent[0][1])

    def test_send_failure_does_not_mark_sent(self):
        def bad(subject, body):
            raise OSError("smtp down")
        now = datetime(2026, 9, 30, 6, 10, tzinfo=MT)
        result = mailer.deliver(now, runner=lambda cmd: (0, ""), sender=bad,
                                state_path=self.state, email_path=self.email, builder=payload)
        self.assertFalse(result["sent"])
        self.assertTrue(result["status"].startswith("send-failed"))
        self.assertFalse(self.state.exists())

    def test_delegate_runs_first_and_is_only_approval_step(self):
        labels = [label for label, _ in mailer.PIPELINE_STEPS]
        self.assertEqual(labels[0], "paper delegate")
        self.assertIn("second opinion", labels)  # behind the once-a-day check
        cmds = " ".join(" ".join(cmd) for _, cmd in mailer.PIPELINE_STEPS)
        for forbidden in ("today.py", "run_inferno", "schwab", "approve", "stage"):
            self.assertNotIn(forbidden, cmds)

    def test_dry_run_sends_nothing(self):
        result = self._deliver(datetime(2026, 9, 30, 6, 10, tzinfo=MT), dry_run=True)
        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(self.sent, [])
        self.assertFalse(self.state.exists())


class DawnFollowUpTests(unittest.TestCase):
    def test_follow_ups_run_by_default(self):
        names = [Path(cmd[1]).name for cmd in dawn.follow_up_commands(["--automation"], {})]
        self.assertEqual(names, ["inferno_desk_editor_mailer.py"])

    def test_skip_email_and_cloud_and_env_disable(self):
        self.assertEqual(dawn.follow_up_commands(["--skip-email"], {}), [])
        self.assertEqual(dawn.follow_up_commands(["--cloud-native"], {}), [])
        self.assertEqual(dawn.follow_up_commands([], {"INFERNO_DESK_EDITOR_MAIL": "0"}), [])


if __name__ == "__main__":
    unittest.main()
