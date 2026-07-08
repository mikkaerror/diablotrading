from __future__ import annotations

"""Tests for the constant-drift guard in inferno_score_threshold_audit.

The guard must catch the same risk/threshold constant being defined with a
literal value in more than one module, escalate when the values actually
diverge, and stay quiet for constants that are already single-sourced.
"""

import unittest
from pathlib import Path
import tempfile

import inferno_score_threshold_audit as audit


class ConstantDriftScanTests(unittest.TestCase):
    def _write(self, root: Path, name: str, body: str) -> None:
        (root / name).write_text(body, encoding="utf-8")

    def test_aligned_duplicate_is_p2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "inferno_a.py", "MAX_DAILY_RISK_UNITS = 3.0\n")
            self._write(root, "inferno_b.py", "MAX_DAILY_RISK_UNITS = 3.0\n")
            findings = audit.constant_drift_findings(
                root=root, names=("MAX_DAILY_RISK_UNITS",)
            )
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["severity"], "P2")

    def test_diverged_duplicate_is_p1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "inferno_a.py", "MAX_DAILY_RISK_UNITS = 3.0\n")
            self._write(root, "inferno_b.py", "MAX_DAILY_RISK_UNITS = 4.0\n")
            findings = audit.constant_drift_findings(
                root=root, names=("MAX_DAILY_RISK_UNITS",)
            )
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["severity"], "P1")

    def test_single_definition_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "inferno_a.py", "MAX_DAILY_RISK_UNITS = 3.0\n")
            findings = audit.constant_drift_findings(
                root=root, names=("MAX_DAILY_RISK_UNITS",)
            )
            self.assertEqual(findings, [])

    def test_alias_is_not_a_drift_risk(self) -> None:
        # An alias to a single source carries no literal default, so it must
        # not be treated as a competing definition.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "inferno_a.py", "MIN_READY_SCORE = 72\n")
            self._write(root, "inferno_b.py", "MIN_READY_SCORE = CANDIDATE_MIN_READINESS\n")
            findings = audit.constant_drift_findings(
                root=root, names=("MIN_READY_SCORE",)
            )
            self.assertEqual(findings, [])

    def test_env_override_default_is_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "inferno_a.py", "MAX_KELLY_FRACTION = 0.25\n")
            self._write(
                root,
                "inferno_b.py",
                'MAX_KELLY_FRACTION = float(os.environ.get("INFERNO_KELLY_MAX_FRACTION", "0.25"))\n',
            )
            findings = audit.constant_drift_findings(
                root=root, names=("MAX_KELLY_FRACTION",)
            )
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["severity"], "P2")

    def test_live_repo_single_sources_known_risk_constants(self) -> None:
        # Against the real repo, these high-impact risk constants must stay
        # imported from the central math config, not redefined with literals.
        findings = audit.constant_drift_findings()
        titles = {f["title"] for f in findings}
        self.assertNotIn(
            "Risk/threshold constant MAX_DAILY_RISK_UNITS is defined in multiple files",
            titles,
        )
        self.assertNotIn(
            "Risk/threshold constant MAX_KELLY_FRACTION is defined in multiple files",
            titles,
        )


if __name__ == "__main__":
    unittest.main()
