import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import inferno_away as away
import inferno_desk_editor_mailer as mailer


class AwayWindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state = self.tmp / "away.json"
        self.plan = self.tmp / "plan.json"
        self.plan.write_text(json.dumps({"deposit": {"amount": 250, "everyDays": 14, "nextExpected": "2026-10-09"}}))
        self.log = self.tmp / "deposit_log.jsonl"

    def on(self, start, end, today=date(2026, 10, 1)):
        return away.turn_on(date.fromisoformat(start), date.fromisoformat(end), "trip", today, self.state)

    def test_active_and_just_back(self):
        self.on("2026-10-20", "2026-10-28")
        st = away.load(self.state)
        self.assertIsNone(away.active_window(date(2026, 10, 19), st))
        self.assertIsNotNone(away.active_window(date(2026, 10, 20), st))
        self.assertIsNotNone(away.active_window(date(2026, 10, 28), st))
        self.assertIsNotNone(away.just_back(date(2026, 10, 31), st))
        self.assertIsNone(away.just_back(date(2026, 11, 1), st))
        self.assertTrue(away.is_away(date(2026, 10, 22), self.state))

    def test_rejects_bad_windows(self):
        with self.assertRaises(SystemExit):
            self.on("2026-10-28", "2026-10-20")
        with self.assertRaises(SystemExit):
            self.on("2026-10-01", "2026-12-31")
        with self.assertRaises(SystemExit):
            self.on("2026-09-01", "2026-09-05")

    def test_new_window_replaces_overlap(self):
        self.on("2026-10-20", "2026-10-28")
        self.on("2026-10-25", "2026-11-02")
        self.on("2026-12-20", "2026-12-28")
        starts = [w["start"] for w in away.load(self.state)["windows"]]
        self.assertEqual(starts, ["2026-10-25", "2026-12-20"])

    def test_off_ends_active_and_drops_upcoming(self):
        self.on("2026-10-20", "2026-10-28")
        self.on("2026-12-20", "2026-12-28")
        result = away.turn_off(date(2026, 10, 22), self.state)
        self.assertEqual(result, {"endedActive": True, "droppedUpcoming": 1})
        st = away.load(self.state)
        self.assertIsNone(away.active_window(date(2026, 10, 22), st))
        self.assertEqual(st["windows"][0]["end"], "2026-10-21")

    def test_deposits_and_pending(self):
        self.assertEqual(away.deposit_dates(date(2026, 10, 20), date(2026, 11, 10), self.plan),
                         ["2026-10-23", "2026-11-06"])
        self.on("2026-10-20", "2026-10-30")   # ends Friday
        sec = away.section(date(2026, 10, 26), self.state, self.plan, self.log)
        self.assertEqual(sec["deposits"], ["2026-10-23"])
        self.assertTrue(sec["depositsPending"])
        self.assertEqual(sec["returnDay"], "2026-11-02")  # next weekday
        self.log.write_text(json.dumps({"recordedAt": "2026-11-02T08:00:00-07:00"}) + "\n")
        back = away.section(date(2026, 11, 2), self.state, self.plan, self.log)
        self.assertIsNotNone(back["justBack"])
        self.assertFalse(back["depositsPending"])

    def test_missing_state_is_not_away(self):
        self.assertFalse(away.is_away(date(2026, 10, 1), self.tmp / "nope.json"))


class MailerAwayTests(unittest.TestCase):
    def test_delegate_paused_but_rest_runs(self):
        ran = []
        steps = mailer.run_pipeline(lambda cmd: (ran.append(cmd[0]) or (0, "")), 0, away=True)
        self.assertNotIn("inferno_paper_delegate.py", ran)
        self.assertIn("inferno_short_premium_shadow.py", ran)
        paused = [s for s in steps if s["step"] == "paper delegate"][0]
        self.assertTrue(paused["ok"])
        self.assertIn("away", paused["detail"])

    def test_subject_tag(self):
        now = datetime(2026, 10, 22, 6, 5)
        self.assertIn("(away)", mailer.subject_for({"away": {"active": {"end": "x"}}, "headline": "h"}, now))
        self.assertTrue(mailer.subject_for({"headline": "h"}, now).startswith("[Inferno Desk] "))


class EditorAwayTextTests(unittest.TestCase):
    def payload(self, away_block):
        import inferno_desk_editor as editor
        p = {
            "away": away_block, "alerts": [], "decisions": [{"ticker": "BMI"}],
            "money": {"fresh": True, "ageHours": 1, "nlv": 850.0, "cash": 250.0, "performance": None},
            "positions": {"live": [{"symbol": "TE", "lossRule": True}], "paperActions": []},
            "orderCards": {"actionable": []}, "delegated": [], "evidence": {}, "earnings": None, "depositCard": None,
        }
        p["headline"] = editor.headline(p)
        return editor, p

    def test_away_email_is_short_and_has_no_action_items(self):
        editor, p = self.payload({"active": {"start": "2026-10-20", "end": "2026-10-28", "note": ""},
                                  "deposits": ["2026-10-23"], "returnDay": "2026-10-29"})
        text = editor.desk_editor_text(p)
        self.assertIn("Nothing here needs you", text)
        self.assertIn("Deposit 2026-10-23", text)
        self.assertNotIn("APPROVE", text)
        self.assertLess(len(text.splitlines()), 25)
        self.assertTrue(p["headline"].startswith("away through 2026-10-28"))

    def test_welcome_back_block(self):
        editor, p = self.payload({"active": None, "justBack": {"start": "2026-10-20", "end": "2026-10-28"},
                                  "deposits": ["2026-10-23"], "depositsPending": True})
        self.assertTrue(p["headline"].startswith("welcome back"))


if __name__ == "__main__":
    unittest.main()
