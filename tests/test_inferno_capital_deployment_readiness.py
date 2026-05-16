import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import inferno_capital_deployment_readiness as readiness
from inferno_io import atomic_write_json


class CapitalDeploymentReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.reports = self.root / "reports"
        self.data.mkdir()
        self.reports.mkdir()

        self.files = {
            "AUTHORITY_MANIFEST_FILE": self.data / "inferno_authority_manifest.json",
            "CAPITAL_ALLOCATOR_FILE": self.data / "inferno_capital_allocator.json",
            "CAPITAL_DEPLOYMENT_READINESS_FILE": self.data / "inferno_capital_deployment_readiness.json",
            "CAPITAL_DEPLOYMENT_READINESS_TEXT_FILE": self.reports / "capital_deployment_readiness_latest.txt",
            "LIVE_ACCOUNT_SYNC_FILE": self.data / "inferno_live_account_sync.json",
            "LIVE_POSITION_REVIEW_FILE": self.data / "inferno_live_position_review.json",
            "PAPER_EVIDENCE_LOOP_FILE": self.data / "inferno_paper_evidence_loop.json",
            "PAPER_TEST_DIRECTOR_FILE": self.data / "inferno_paper_test_director.json",
            "STRATEGY_LAB_FILE": self.data / "inferno_strategy_lab.json",
            "DATA_READINESS_AUDIT_FILE": self.data / "inferno_data_readiness_audit.json",
            "TICKER_UNIVERSE_AUDIT_FILE": self.data / "inferno_ticker_universe_audit.json",
            "OPS_MAINTENANCE_FILE": self.data / "inferno_ops_maintenance.json",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def write_base_artifacts(self, authority_override=None):
        authority = {
            "decision": {
                "authorityLevel": "paper-evidence-only",
                "brokerSubmitAllowed": False,
                "liveTradingAllowed": False,
            }
        }
        if authority_override:
            authority["decision"].update(authority_override)
        atomic_write_json(self.files["AUTHORITY_MANIFEST_FILE"], authority)
        atomic_write_json(
            self.files["LIVE_ACCOUNT_SYNC_FILE"],
            {
                "verdict": "healthy",
                "matchedSuffix": "1234",
                "generatedAt": "2026-05-14T09:00:00-06:00",
                "stockBuyingPower": 525,
            },
        )
        atomic_write_json(
            self.files["LIVE_POSITION_REVIEW_FILE"],
            {"verdict": "healthy", "counts": {"supported": 1, "review": 1, "fragile": 0}},
        )
        atomic_write_json(
            self.files["PAPER_EVIDENCE_LOOP_FILE"],
            {"verdict": "approval-bottleneck", "counts": {"remainingForPromotion": 30}},
        )
        atomic_write_json(
            self.files["PAPER_TEST_DIRECTOR_FILE"],
            {"verdict": "approval-bottleneck", "counts": {"stageableNow": 0, "approvalOnly": 1}},
        )
        atomic_write_json(self.files["STRATEGY_LAB_FILE"], {"deskVerdict": {"level": "insufficient-data"}})
        atomic_write_json(
            self.files["DATA_READINESS_AUDIT_FILE"],
            {"verdict": "ready-for-next-week-prep", "generatedAt": "2026-05-14T09:00:00-06:00"},
        )
        atomic_write_json(
            self.files["TICKER_UNIVERSE_AUDIT_FILE"],
            {"verdict": "healthy", "generatedAt": "2026-05-14T09:00:00-06:00", "criticalCount": 0},
        )
        atomic_write_json(self.files["OPS_MAINTENANCE_FILE"], {"verdict": "healthy"})

    def patch_paths(self):
        patches = [
            patch.object(readiness, name, path)
            for name, path in self.files.items()
        ]
        patches.extend(
            [
                patch.object(readiness, "build_capital_allocator", return_value={
                    "deployableCash": 525,
                    "maxOptionsRisk": 52.5,
                    "maxLongTermBuy": 157.5,
                    "reserveCash": 315,
                }),
                patch.object(readiness, "save_capital_allocator", return_value=None),
                patch.object(readiness, "ensure_dirs", return_value=None),
                patch.object(readiness, "local_today", return_value="2026-05-14"),
                patch.object(readiness, "account_suffix_allowed", return_value=True),
                patch.object(readiness, "approved_account_scope", return_value="account ending 1234"),
            ]
        )
        return patches

    def test_builds_manual_ready_with_warnings(self):
        self.write_base_artifacts()
        with self._stack_patches():
            result = readiness.build_capital_deployment_readiness(
                deployable_cash=525,
                for_date="2026-05-15",
            )

        self.assertEqual(result["verdict"], "manual-ready-with-warnings")
        self.assertTrue(result["manualDeploymentAllowed"])
        self.assertFalse(result["autoLiveAllowed"])
        self.assertTrue(self.files["CAPITAL_DEPLOYMENT_READINESS_FILE"].exists())
        self.assertIn("Paper evidence loop", "\n".join(result["warnings"]))

    def test_blocks_if_authority_allows_live_submit(self):
        self.write_base_artifacts({"brokerSubmitAllowed": True})
        with self._stack_patches():
            result = readiness.build_capital_deployment_readiness(
                deployable_cash=525,
                for_date="2026-05-15",
            )

        self.assertEqual(result["verdict"], "not-ready")
        self.assertFalse(result["manualDeploymentAllowed"])
        self.assertIn("Authority manifest allows live", "\n".join(result["blockers"]))

    def _stack_patches(self):
        stack = ExitStack()
        for patcher in self.patch_paths():
            stack.enter_context(patcher)
        return stack


if __name__ == "__main__":
    unittest.main()
