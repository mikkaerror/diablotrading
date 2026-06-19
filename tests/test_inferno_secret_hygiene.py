from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_secret_hygiene as hygiene


class InfernoSecretHygieneTests(unittest.TestCase):
    """Keep the repo-security gate honest and deterministic."""

    def test_build_secret_hygiene_flags_tracked_sensitive_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gitignore = root / ".gitignore"
            gitignore.write_text("\n".join(hygiene.REQUIRED_GITIGNORE_PATTERNS) + "\n", encoding="utf-8")

            with (
                patch.object(hygiene, "ROOT", root),
                patch.object(hygiene, "GITIGNORE_FILE", gitignore),
                patch.object(hygiene, "tracked_repo_files", return_value=["README.md", ".env.smtp", "data/latest_snapshot.json"]),
            ):
                report = hygiene.build_secret_hygiene()

            self.assertEqual(report["verdict"], "attention")
            self.assertIn(".env.smtp", report["trackedSensitive"])
            self.assertIn("data/latest_snapshot.json", report["trackedSensitive"])

    def test_build_secret_hygiene_is_healthy_when_no_sensitive_paths_are_tracked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gitignore = root / ".gitignore"
            gitignore.write_text("\n".join(hygiene.REQUIRED_GITIGNORE_PATTERNS) + "\n", encoding="utf-8")

            with (
                patch.object(hygiene, "ROOT", root),
                patch.object(hygiene, "GITIGNORE_FILE", gitignore),
                patch.object(hygiene, "tracked_repo_files", return_value=["README.md", "inferno_doctor.py"]),
            ):
                report = hygiene.build_secret_hygiene()

            self.assertTrue(report["ok"])
            self.assertEqual(report["trackedSensitiveCount"], 0)
            self.assertEqual(report["missingGitignorePatterns"], [])

    def test_public_operator_config_is_not_treated_as_secret(self) -> None:
        self.assertFalse(hygiene.path_looks_sensitive("data/operator_long_term_holds.json"))
        self.assertTrue(hygiene.path_looks_sensitive("data/latest_snapshot.json"))


if __name__ == "__main__":
    unittest.main()
