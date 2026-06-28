from __future__ import annotations

"""Regression tests for the low-context usage optimizer."""

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import inferno_usage_optimizer as optimizer


class InfernoUsageOptimizerTests(unittest.TestCase):
    """Keep the handoff packet compact, deterministic, and safety-forward."""

    def test_estimate_tokens_uses_configured_ratio(self) -> None:
        self.assertEqual(optimizer.estimate_tokens("abcd"), 1)
        self.assertEqual(optimizer.estimate_tokens("abcde"), 2)

    def test_measure_file_handles_missing_paths(self) -> None:
        result = optimizer.measure_file(Path("/tmp/definitely-missing-inferno-file.txt"))

        self.assertFalse(result["exists"])
        self.assertEqual(result["estimatedTokens"], 0)

    def test_build_usage_optimizer_reads_small_handoff_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            reports_dir = root / "reports"
            docs_dir = root / "docs"
            coordination_dir = root / "coordination"
            for path in (data_dir, reports_dir, docs_dir, coordination_dir):
                path.mkdir(parents=True, exist_ok=True)

            (data_dir / "inferno_model_command_center.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-05-18T06:00:00-06:00",
                        "headlineMetrics": {
                            "autoLiveAllowed": False,
                            "paperRemainingForPromotion": 30,
                            "riskGateHardFails": 0,
                        },
                        "nextActions": ["Keep paper evidence moving."],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_central_command.json").write_text(
                json.dumps({"verdict": "attention"}),
                encoding="utf-8",
            )
            (data_dir / "inferno_daily_loop.json").write_text(
                json.dumps({"verdict": "healthy"}),
                encoding="utf-8",
            )
            for relative in (
                "reports/model_command_center_onboard_latest.txt",
                "reports/model_command_center_latest.txt",
                "reports/central_command_latest.txt",
                "docs/SYSTEM_MAP.md",
                "docs/PROJECT_STATUS.md",
                "docs/MODEL_COLLABORATION_BRIEF.md",
                "docs/REPOSITORY_HYGIENE.md",
                "coordination/README.md",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{relative}\nsmall handoff file\n", encoding="utf-8")

            patches = [
                patch.object(optimizer, "ROOT", root),
                patch.object(optimizer, "DATA_DIR", data_dir),
                patch.object(optimizer, "REPORTS_DIR", reports_dir),
                patch.object(optimizer, "USAGE_OPTIMIZER_FILE", data_dir / "inferno_usage_optimizer.json"),
                patch.object(optimizer, "USAGE_OPTIMIZER_TEXT_FILE", reports_dir / "usage_optimizer_latest.txt"),
                patch.object(optimizer, "MODEL_COMMAND_CENTER_FILE", data_dir / "inferno_model_command_center.json"),
                patch.object(optimizer, "CENTRAL_COMMAND_FILE", data_dir / "inferno_central_command.json"),
                patch.object(optimizer, "DAILY_LOOP_FILE", data_dir / "inferno_daily_loop.json"),
            ]
            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                payload = optimizer.build_usage_optimizer()
                optimizer.save_usage_optimizer(payload)

            self.assertEqual(payload["verdict"], "lean")
            self.assertFalse(payload["systemSnapshot"]["autoLiveAllowed"])
            self.assertEqual(payload["systemSnapshot"]["commandCenter"], "ready")
            self.assertEqual(payload["systemSnapshot"]["paperRemainingForPromotion"], 30)
            self.assertEqual(payload["nextActions"], ["Keep paper evidence moving."])
            self.assertEqual(payload["readFirst"][0]["path"], "reports/model_command_center_onboard_latest.txt")
            self.assertEqual(payload["readFirst"][2]["path"], "docs/SYSTEM_MAP.md")
            self.assertEqual(payload["readIfNeeded"][0]["path"], "reports/model_command_center_latest.txt")
            self.assertLessEqual(
                payload["budget"]["readFirstEstimatedTokens"],
                optimizer.LEAN_HANDOFF_TOKEN_BUDGET,
            )
            self.assertTrue(payload["readIfNeeded"])
            self.assertTrue((reports_dir / "usage_optimizer_latest.txt").exists())


if __name__ == "__main__":
    unittest.main()
