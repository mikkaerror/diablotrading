from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import inferno_ticket_cap_policy as policy
from inferno_io import atomic_write_json


class TicketCapPolicyTests(unittest.TestCase):
    """Ticket-cap policy should centralize sizing posture without authority changes."""

    def test_build_policy_uses_saved_band_and_keeps_live_cap_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            reports_dir = root / "reports"
            data_dir.mkdir()
            reports_dir.mkdir()
            files = {
                "TICKET_CAP_POLICY_CONFIG_FILE": data_dir / "operator_ticket_cap_policy.json",
                "TICKET_CAP_POLICY_FILE": data_dir / "inferno_ticket_cap_policy.json",
                "TICKET_CAP_POLICY_TEXT_FILE": reports_dir / "ticket_cap_policy_latest.txt",
            }
            atomic_write_json(
                files["TICKET_CAP_POLICY_CONFIG_FILE"],
                {
                    "minTicketDollars": 250,
                    "maxTicketDollars": 500,
                    "targetTicketDollars": 300,
                    "callOptionsPosture": "aggressive-defined-risk",
                    "source": "operator-assumption",
                },
            )
            with ExitStack() as stack:
                for name, path in files.items():
                    stack.enter_context(patch.object(policy, name, path))
                stack.enter_context(patch.object(policy, "ensure_dirs", return_value=None))
                stack.enter_context(
                    patch.object(
                        policy,
                        "current_risk_cap",
                        return_value={
                            "effectiveCap": 400,
                            "source": "ack",
                            "verdict": "aligned",
                            "ackedCap": 500,
                            "recommendedCap": 400,
                        },
                    )
                )
                payload = policy.build_ticket_cap_policy()
                policy.save_ticket_cap_policy(payload)

            self.assertEqual(payload["verdict"], "active")
            self.assertEqual(payload["requestedBand"]["minTicketDollars"], 250)
            self.assertEqual(payload["constructionBand"]["hardCapDollars"], 500)
            self.assertEqual(payload["effectiveBand"]["hardCapDollars"], 500)
            self.assertEqual(payload["effectiveBand"]["sourceRiskCapSource"], "paper-budget")
            self.assertEqual(payload["liveCapitalBand"]["hardCapDollars"], 400)
            self.assertEqual(payload["liveCapitalBand"]["sourceRiskCapSource"], "ack")
            self.assertTrue(payload["callOptionsPosture"]["aggressiveCallResearchEnabled"])
            self.assertFalse(payload["brokerSubmitAllowed"])
            self.assertFalse(payload["liveTradingAllowed"])
            self.assertTrue(files["TICKET_CAP_POLICY_TEXT_FILE"].exists())

    def test_zero_live_cap_stays_visible_without_closing_paper_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            reports_dir = root / "reports"
            data_dir.mkdir()
            reports_dir.mkdir()
            files = {
                "TICKET_CAP_POLICY_CONFIG_FILE": data_dir / "operator_ticket_cap_policy.json",
                "TICKET_CAP_POLICY_FILE": data_dir / "inferno_ticket_cap_policy.json",
                "TICKET_CAP_POLICY_TEXT_FILE": reports_dir / "ticket_cap_policy_latest.txt",
            }
            atomic_write_json(
                files["TICKET_CAP_POLICY_CONFIG_FILE"],
                {
                    "minTicketDollars": 250,
                    "maxTicketDollars": 500,
                    "targetTicketDollars": 250,
                    "callOptionsPosture": "aggressive-defined-risk",
                    "source": "operator-assumption",
                },
            )
            with ExitStack() as stack:
                for name, path in files.items():
                    stack.enter_context(patch.object(policy, name, path))
                stack.enter_context(patch.object(policy, "ensure_dirs", return_value=None))
                stack.enter_context(
                    patch.object(
                        policy,
                        "current_risk_cap",
                        return_value={
                            "effectiveCap": 0.0,
                            "source": "ack",
                            "verdict": "aligned",
                            "ackedCap": 500,
                            "recommendedCap": 500,
                            "drawdownLevel": "pause",
                            "drawdownCapMultiplier": 0.0,
                            "newEntriesAllowed": False,
                        },
                    )
                )
                payload = policy.build_ticket_cap_policy()

            self.assertEqual(payload["verdict"], "active")
            self.assertEqual(payload["constructionBand"]["hardCapDollars"], 500.0)
            self.assertEqual(payload["effectiveBand"]["hardCapDollars"], 500.0)
            self.assertEqual(payload["effectiveBand"]["sourceRiskCapSource"], "paper-budget")
            self.assertTrue(payload["effectiveBand"]["newEntriesAllowed"])
            self.assertEqual(payload["liveCapitalBand"]["hardCapDollars"], 0.0)
            self.assertEqual(payload["liveCapitalBand"]["drawdownLevel"], "pause")
            self.assertFalse(payload["liveCapitalBand"]["newEntriesAllowed"])

    def test_save_policy_config_normalizes_reversed_band(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "operator_ticket_cap_policy.json"
            with patch.object(policy, "TICKET_CAP_POLICY_CONFIG_FILE", path), \
                 patch.object(policy, "ensure_dirs", return_value=None):
                payload = policy.save_policy_config(
                    min_ticket_dollars=500,
                    max_ticket_dollars=250,
                    target_ticket_dollars=300,
                    call_options_posture="call-debit-biased",
                )

            self.assertEqual(payload["minTicketDollars"], 250)
            self.assertEqual(payload["maxTicketDollars"], 500)
            self.assertEqual(payload["targetTicketDollars"], 300)
            self.assertEqual(payload["callOptionsPosture"], "call-debit-biased")
            self.assertTrue(path.exists())

    def test_configure_preserves_omitted_saved_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            reports_dir = root / "reports"
            data_dir.mkdir()
            reports_dir.mkdir()
            files = {
                "TICKET_CAP_POLICY_CONFIG_FILE": data_dir / "operator_ticket_cap_policy.json",
                "TICKET_CAP_POLICY_FILE": data_dir / "inferno_ticket_cap_policy.json",
                "TICKET_CAP_POLICY_TEXT_FILE": reports_dir / "ticket_cap_policy_latest.txt",
            }
            atomic_write_json(
                files["TICKET_CAP_POLICY_CONFIG_FILE"],
                {
                    "minTicketDollars": 250,
                    "maxTicketDollars": 500,
                    "targetTicketDollars": 250,
                    "callOptionsPosture": "call-debit-biased",
                    "source": "operator-assumption",
                },
            )
            with ExitStack() as stack:
                for name, path in files.items():
                    stack.enter_context(patch.object(policy, name, path))
                stack.enter_context(patch.object(policy, "ensure_dirs", return_value=None))
                stack.enter_context(patch("sys.argv", ["inferno_ticket_cap_policy.py", "configure", "--min-ticket", "300"]))
                stack.enter_context(
                    patch.object(
                        policy,
                        "current_risk_cap",
                        return_value={
                            "effectiveCap": 500,
                            "source": "ack",
                            "verdict": "aligned",
                            "ackedCap": 500,
                            "recommendedCap": 500,
                        },
                    )
                )
                with redirect_stdout(StringIO()):
                    self.assertEqual(policy.main(), 0)

            saved = policy.load_json_file(files["TICKET_CAP_POLICY_CONFIG_FILE"]) or {}
            self.assertEqual(saved["minTicketDollars"], 300)
            self.assertEqual(saved["maxTicketDollars"], 500)
            self.assertEqual(saved["targetTicketDollars"], 300)
            self.assertEqual(saved["callOptionsPosture"], "call-debit-biased")


if __name__ == "__main__":
    unittest.main()
