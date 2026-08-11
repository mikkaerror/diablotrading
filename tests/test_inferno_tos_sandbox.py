from __future__ import annotations

"""Regression tests for fill-log seeding in the paperMoney sandbox."""

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_tos_sandbox


class InfernoTosSandboxFillLogTests(unittest.TestCase):
    """Verify stageable tickets seed the fill log without clobbering operator data."""

    def test_intent_stage_status_includes_strike_plan_blocks(self) -> None:
        status, reasons = inferno_tos_sandbox.intent_stage_status(
            {
                "ticker": "GDS",
                "approvalStatus": "pending",
                "intentStatus": "blocked",
                "intentBlocks": ["human approval still required"],
            },
            {
                "ok": True,
                "riskVerdict": {
                    "blocks": ["max loss $900.00 exceeds single-ticket cap $500.00"],
                },
                "strikePlan": {"liquidityNotes": []},
            },
            True,
        )

        self.assertEqual(status, "blocked")
        self.assertIn("human approval is missing", reasons)
        self.assertIn("human approval still required", reasons)
        self.assertIn("max loss $900.00 exceeds single-ticket cap $500.00", reasons)

    def test_intent_stage_status_uses_passed_rehearsal_variant(self) -> None:
        status, reasons = inferno_tos_sandbox.intent_stage_status(
            {
                "ticker": "GDS",
                "approvalStatus": "approved",
                "intentStatus": "approval-ready",
                "intentBlocks": [],
            },
            {
                "ok": True,
                "riskVerdict": {
                    "blocks": ["max loss $900.00 exceeds single-ticket cap $500.00"],
                },
                "strikePlan": {"strategy": "LONG_STRADDLE", "liquidityNotes": []},
                "paperRehearsalVariant": {
                    "strategy": "LONG_STRANGLE",
                    "paperVariantOnly": True,
                    "variantFamily": "cap-aware-long-strangle",
                    "variantForStrategy": "LONG_STRADDLE",
                    "riskVerdict": {"passed": True, "blocks": [], "warnings": []},
                    "liquidityNotes": [],
                },
            },
            True,
        )

        self.assertEqual(status, "stage-in-papermoney")
        self.assertEqual(reasons, [])

    def test_intent_stage_status_auto_stages_approval_only_paper_ticket(self) -> None:
        status, reasons = inferno_tos_sandbox.intent_stage_status(
            {
                "ticker": "WSC",
                "approvalStatus": "pending",
                "intentStatus": "blocked",
                "intentBlocks": ["human approval still required"],
            },
            {
                "ok": True,
                "riskVerdict": {"passed": True, "blocks": [], "warnings": []},
                "strikePlan": {"strategy": "LONG_STRADDLE", "liquidityNotes": []},
            },
            True,
        )

        self.assertEqual(status, "stage-in-papermoney")
        self.assertEqual(reasons, [])

    def test_staged_cap_fit_variant_is_the_fillable_sandbox_route(self) -> None:
        today = inferno_tos_sandbox.local_now().date().isoformat()
        cap_fit_ticket = {
            "ticketId": "capfit-iren",
            "tradeDate": today,
            "ticker": "IREN",
            "strategy": "CALL_DEBIT_SPREAD",
            "status": "paper-staged",
            "outcome": {"status": "open"},
            "paperVariantOnly": True,
            "paperVariantFamily": "cap-fit-debit-5w",
            "paperVariantOfStrategy": "LONG_STRADDLE",
            "capFitFallback": True,
            "routeFamily": "cap-fit-defined-risk",
            "setupRec": "CALL_DEBIT_SPREAD",
            "daysUntilEarnings": 16,
            "liveTradingAllowed": False,
            "brokerSubmitAllowed": False,
            "legs": [
                {"symbol": "IREN260828C00040000"},
                {"symbol": "IREN260828C00045000"},
            ],
        }
        unsafe_copy = {**cap_fit_ticket, "ticketId": "unsafe", "brokerSubmitAllowed": True}
        with patch.object(inferno_tos_sandbox, "load_json_file", return_value={"items": [cap_fit_ticket, unsafe_copy]}):
            staged = inferno_tos_sandbox.staged_cap_fit_variant_tickets()

        self.assertEqual(staged, [cap_fit_ticket])
        route = inferno_tos_sandbox.sandbox_ticket_from_staged_cap_fit_variant(staged[0])
        self.assertEqual(route["status"], "stage-in-papermoney")
        self.assertEqual(route["strategy"], "CALL_DEBIT_SPREAD")
        self.assertEqual(route["routeFamily"], "cap-fit-defined-risk")
        self.assertEqual(route["legSymbols"], ["IREN260828C00040000", "IREN260828C00045000"])

    def test_seed_fill_log_from_stageable_inserts_stub_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            work_file = Path(tmpdir) / "fill.csv"
            template_file = Path(tmpdir) / "template.csv"
            with (
                patch.object(inferno_tos_sandbox, "TOS_FILL_LOG_WORK_FILE", work_file),
                patch.object(inferno_tos_sandbox, "TOS_FILL_LOG_TEMPLATE_FILE", template_file),
            ):
                result = inferno_tos_sandbox.seed_fill_log_from_stageable(
                    [
                        {
                            "ticketId": "abc123",
                            "ticker": "WSC",
                            "strategy": "LONG_STRADDLE",
                            "expiration": "2026-05-15",
                            "routeFamily": "long-volatility event",
                            "previewOrder": {"orderType": "LIMIT"},
                        }
                    ],
                    "2026-05-05",
                )

                self.assertEqual(result["seededRowsInserted"], 1)
                self.assertEqual(result["pendingFillRows"], 1)

                with work_file.open("r", encoding="utf-8", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["ticketId"], "abc123")
                self.assertEqual(rows[0]["status"], "planned")
                self.assertEqual(rows[0]["ticker"], "WSC")

    def test_seed_fill_log_preserves_existing_operator_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            work_file = Path(tmpdir) / "fill.csv"
            template_file = Path(tmpdir) / "template.csv"
            with (
                patch.object(inferno_tos_sandbox, "TOS_FILL_LOG_WORK_FILE", work_file),
                patch.object(inferno_tos_sandbox, "TOS_FILL_LOG_TEMPLATE_FILE", template_file),
            ):
                inferno_tos_sandbox.seed_fill_log_from_stageable(
                    [
                        {
                            "ticketId": "abc123",
                            "ticker": "WSC",
                            "strategy": "LONG_STRADDLE",
                            "expiration": "2026-05-15",
                            "routeFamily": "long-volatility event",
                            "previewOrder": {"orderType": "LIMIT"},
                        }
                    ],
                    "2026-05-05",
                )
                with work_file.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=inferno_tos_sandbox.FILL_LOG_COLUMNS)
                    writer.writeheader()
                    writer.writerow(
                        {
                            "sessionDate": "2026-05-05",
                            "ticketId": "abc123",
                            "ticker": "WSC",
                            "strategy": "LONG_STRADDLE",
                            "expiration": "2026-05-15",
                            "environment": "thinkorswim-paperMoney",
                            "paperAccount": "paperMoney",
                            "routeFamily": "long-volatility event",
                            "orderType": "LIMIT",
                            "contracts": "1",
                            "entryPrice": "2.95",
                            "exitPrice": "",
                            "realizedPnl": "",
                            "status": "open",
                            "openedAt": "2026-05-05T10:00:00-10:00",
                            "closedAt": "",
                            "notes": "manually updated",
                        }
                    )

                result = inferno_tos_sandbox.seed_fill_log_from_stageable(
                    [
                        {
                            "ticketId": "abc123",
                            "ticker": "WSC",
                            "strategy": "LONG_STRADDLE",
                            "expiration": "2026-05-15",
                            "routeFamily": "long-volatility event",
                            "previewOrder": {"orderType": "LIMIT"},
                        }
                    ],
                    "2026-05-05",
                )

                self.assertEqual(result["seededRowsInserted"], 0)
                with work_file.open("r", encoding="utf-8", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(rows[0]["status"], "open")
                self.assertEqual(rows[0]["entryPrice"], "2.95")
                self.assertEqual(rows[0]["notes"], "manually updated")


if __name__ == "__main__":
    unittest.main()
