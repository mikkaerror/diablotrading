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
