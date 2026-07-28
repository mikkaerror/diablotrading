from __future__ import annotations

import unittest
from datetime import datetime

from inferno_artifact_lifecycle import failed_lifecycle, successful_lifecycle


class InfernoArtifactLifecycleTests(unittest.TestCase):
    """Protect timestamp semantics for mutable evidence artifacts."""

    def test_success_preserves_legacy_generation_as_creation_time(self) -> None:
        payload = {"generatedAt": "2026-04-22T09:53:49-06:00", "items": []}
        updated = successful_lifecycle(
            payload,
            producer="inferno-paper-execution",
            source_data_as_of="2026-07-26T09:00:00-06:00",
            freshness_ttl_hours=36,
            schedule="post-open strike cycle",
            now=datetime.fromisoformat("2026-07-26T09:10:00-06:00"),
        )

        self.assertEqual(updated["generatedAt"], "2026-04-22T09:53:49-06:00")
        self.assertEqual(updated["createdAt"], "2026-04-22T09:53:49-06:00")
        self.assertEqual(updated["updatedAt"], "2026-07-26T09:10:00-06:00")
        self.assertEqual(updated["lastSuccessfulAt"], "2026-07-26T09:10:00-06:00")
        self.assertEqual(updated["lastAttemptAt"], "2026-07-26T09:10:00-06:00")
        self.assertEqual(updated["sourceDataAsOf"], "2026-07-26T09:00:00-06:00")
        self.assertEqual(updated["lifecycleStatus"], "success")

    def test_failure_preserves_last_successful_evidence_timestamp(self) -> None:
        prior = successful_lifecycle(
            {"items": []},
            producer="inferno-shadow-evidence",
            source_data_as_of="2026-07-26T09:00:00-06:00",
            now=datetime.fromisoformat("2026-07-26T09:10:00-06:00"),
        )
        failed = failed_lifecycle(
            prior,
            producer="inferno-shadow-evidence",
            error="source plan unavailable",
            now=datetime.fromisoformat("2026-07-26T09:20:00-06:00"),
        )

        self.assertEqual(failed["updatedAt"], "2026-07-26T09:10:00-06:00")
        self.assertEqual(failed["lastSuccessfulAt"], "2026-07-26T09:10:00-06:00")
        self.assertEqual(failed["lastAttemptAt"], "2026-07-26T09:20:00-06:00")
        self.assertEqual(failed["sourceDataAsOf"], "2026-07-26T09:00:00-06:00")
        self.assertEqual(failed["lifecycleStatus"], "failed")
        self.assertEqual(failed["lastFailure"]["message"], "source plan unavailable")


if __name__ == "__main__":
    unittest.main()
