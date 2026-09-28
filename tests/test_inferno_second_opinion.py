from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from inferno_desk_editor import build_desk_editor, desk_editor_text
from inferno_second_opinion import ask_model, build_second_opinion, candidate_facts, pick_model

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


class SecondOpinionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        (self.data / "inferno_approval_queue.json").write_text(json.dumps({"items": [
            {"ticker": "ACN", "approvalStatus": "pending", "daysUntilEarnings": 4}]}))
        (self.data / "inferno_strike_plan.json").write_text(json.dumps({"items": [
            {"ticker": "ACN", "ok": True, "strikePlan": {"strategy": "LONG_STRADDLE"},
             "riskVerdict": {"metrics": {"maxLossDollars": 1510}}}]}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_key_is_quiet(self):
        payload = build_second_opinion(self.data, env={}, now=NOW)
        self.assertEqual(payload["status"], "no-key")
        self.assertTrue(payload["advisoryOnly"])
        self.assertFalse(payload["authorityChanged"])

    def test_items_and_desk_editor_quote(self):
        payload = build_second_opinion(
            self.data, env={"OPENAI_API_KEY": "k"}, asker=lambda f, k, m: f"{f['ticker']} risk is $1510", now=NOW,
            model_lister=lambda k: ["gpt-6-sol", "gpt-6-luna", "gpt-4o-mini-transcribe"])
        self.assertEqual(payload["model"], "gpt-6-luna")
        self.assertEqual(payload["items"], [{"ticker": "ACN", "challenge": "ACN risk is $1510"}])
        (self.data / "inferno_second_opinion.json").write_text(json.dumps(payload))
        editor = build_desk_editor(self.data, self.data, now=NOW)
        self.assertEqual(editor["decisions"][0]["secondOpinion"], "ACN risk is $1510")
        self.assertIn("ChatGPT's case against: ACN risk is $1510", desk_editor_text(editor))

    def test_network_failure_is_contained(self):
        def boom(*_):
            raise urllib.error.URLError("down")
        payload = build_second_opinion(self.data, env={"OPENAI_API_KEY": "k", "INFERNO_SECOND_OPINION_MODEL": "m"},
                                       asker=boom, now=NOW)
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["items"], [])

    def test_pick_model(self):
        self.assertEqual(pick_model(["gpt-6-astra", "gpt-6-luna", "gpt-4o-mini-transcribe"]), "gpt-6-luna")
        self.assertEqual(pick_model(["x-large", "y-mini", "z-mini-tts"]), "y-mini")
        self.assertIsNone(pick_model(["whisper-1", "gpt-4o-mini-transcribe"]))

    def test_model_list_failure_contained(self):
        def boom(_):
            raise urllib.error.URLError("down")
        payload = build_second_opinion(self.data, env={"OPENAI_API_KEY": "k"}, now=NOW, model_lister=boom)
        self.assertEqual(payload["status"], "unavailable")

    def test_ask_model_parses_and_trims(self):
        class Resp(io.BytesIO):
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        seen = {}
        def opener(request, timeout):
            seen["auth"] = request.headers.get("Authorization")
            seen["body"] = json.loads(request.data)
            text = " ".join(["word"] * 80)
            return Resp(json.dumps({"choices": [{"message": {"content": text}}]}).encode())
        out = ask_model(candidate_facts({"ticker": "ACN"}), "sk-x", "m", opener=opener)
        self.assertEqual(seen["auth"], "Bearer sk-x")
        self.assertEqual(seen["body"]["model"], "m")
        self.assertLessEqual(len(out.split()), 40)


if __name__ == "__main__":
    unittest.main()
