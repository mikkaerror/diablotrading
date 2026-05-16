from __future__ import annotations

"""Regression tests for the optional Cloud Run state vault."""

import os
import unittest
from unittest.mock import patch

from inferno_cloud_state import cloud_state_enabled, object_name, restore_cloud_artifacts


class CloudStateTests(unittest.TestCase):
    """Verify cloud state is safe when disabled and deterministic when enabled."""

    @patch.dict(os.environ, {}, clear=True)
    def test_cloud_state_disabled_without_bucket(self) -> None:
        self.assertFalse(cloud_state_enabled())
        report = restore_cloud_artifacts(paths=["data/nonexistent.json"])
        self.assertTrue(report["ok"])
        self.assertFalse(report["enabled"])

    @patch.dict(
        os.environ,
        {
            "INFERNO_CLOUD_STATE_BUCKET": "example-bucket",
            "INFERNO_CLOUD_STATE_PREFIX": "desk-state",
        },
        clear=True,
    )
    def test_object_name_uses_prefix_and_repo_relative_path(self) -> None:
        self.assertEqual(object_name("data/inferno_shadow_evidence.json"), "desk-state/data/inferno_shadow_evidence.json")


if __name__ == "__main__":
    unittest.main()
