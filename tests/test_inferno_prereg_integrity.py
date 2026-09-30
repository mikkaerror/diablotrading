from __future__ import annotations

import unittest

import inferno_prereg_integrity as pi


class PreregIntegrityTests(unittest.TestCase):
    def test_intact_and_drift(self):
        current = {name: pi.fingerprint(name) for name in pi.EXPERIMENTS}
        registry = {"experiments": {k: dict(v) for k, v in current.items()}}
        self.assertEqual(pi.check(registry, current), [])
        registry["experiments"]["earnings-runner-v1"]["docSha256"] = "0" * 64
        registry["experiments"]["short-premium-v2"]["constants"] = {
            **current["short-premium-v2"]["constants"], "MAX_DTE": "30"}
        alerts = pi.check(registry, current)
        self.assertTrue(any("EARNINGS_RUNNER_PREREG" in a and "changed" in a for a in alerts))
        self.assertTrue(any("MAX_DTE" in a for a in alerts))

    def test_registered_pins_match_repo(self):
        import json
        registry = json.loads(pi.REGISTRY_FILE.read_text())
        current = {name: pi.fingerprint(name) for name in pi.EXPERIMENTS}
        self.assertEqual(pi.check(registry, current), [])


if __name__ == "__main__":
    unittest.main()
