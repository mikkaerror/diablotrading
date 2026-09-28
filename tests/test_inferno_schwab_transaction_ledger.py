from __future__ import annotations

"""Regression tests for the read-only Schwab transaction-ledger boundary."""

import csv
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import inferno_schwab_transaction_ledger as ledger
from inferno_schwab_account_sync import SchwabAccountAPIError


ACCOUNT_NUMBER = "11111234"
ACCOUNT_HASH = "hash-secret-123"
ACCOUNT_NUMBERS = [{"accountNumber": ACCOUNT_NUMBER, "hashValue": ACCOUNT_HASH}]
TRANSACTIONS = [
    {
        "activityId": 55,
        "time": "2026-07-21T16:00:00+00:00",
        "tradeDate": "2026-07-21",
        "settlementDate": "2026-07-22",
        "type": "TRADE",
        "status": "VALID",
        "netAmount": "-125.50",
        "description": "Private account 11111234 trade description",
        "transferItems": [
            {
                "amount": 1,
                "price": 1.25,
                "fee": 0.65,
                "instrument": {"symbol": "XYZ  260821C00010000", "assetType": "OPTION"},
            }
        ],
    }
]


class SchwabTransactionLedgerTests(unittest.TestCase):
    """Pin safe transaction normalization and token fail-closed behavior."""

    def test_balanced_contract_cash_requires_source_costs_and_matching_quantities(self):
        def transaction(tid, quantity, effect, cost, net, time):
            return ledger.normalize_transaction({"activityId": tid, "type": "TRADE", "status": "VALID", "time": time, "netAmount": net,
                "transferItems": [{"amount": quantity, "positionEffect": effect, "cost": cost, "instrument": {"symbol": "XYZ_CALL", "assetType": "OPTION"}},
                                  {"amount": .65, "cost": -.65, "feeType": "COMMISSION", "instrument": {"assetType": "CURRENCY"}}]}, account_suffix_value="1234")
        a = transaction("a", 1, "OPENING", -100, -100.65, "2026-09-01T10:00:00Z")
        b = transaction("b", -1, "CLOSING", 120, 119.35, "2026-09-02T10:00:00Z")
        result = ledger.closed_contract_cash_reconciliation([b, a])
        self.assertEqual(result["matchedNetCash"], 18.7)
        self.assertEqual(result["matchedContractGroups"][0]["reportedCosts"], 1.3)
        self.assertFalse(result["accountProfitKnown"])
        for rows in ([b], [a], [a, dict(b, netAmount=500)], [a, dict(b, status="CANCELED")]):
            self.assertIsNone(ledger.closed_contract_cash_reconciliation(rows)["matchedNetCash"])
        b["transferItems"][0]["quantity"] = -2
        self.assertIsNone(ledger.closed_contract_cash_reconciliation([a, b])["matchedNetCash"])

    def test_currency_first_preserves_all_legs_and_zero_values(self):
        raw = dict(TRANSACTIONS[0], transferItems=[
            {"amount": -.65, "feeType": "COMMISSION", "instrument": {"symbol": "CURRENCY_USD", "assetType": "CURRENCY", "description": "private"}},
            {"amount": 0, "quantity": 99, "price": 0, "fee": 0, "fees": 9, "positionEffect": "OPENING", "instrument": {"symbol": "XYZ_CALL", "assetType": "OPTION", "accountNumber": ACCOUNT_NUMBER}},
        ])
        row = ledger.normalize_transaction(raw, account_suffix_value="1234")
        self.assertEqual(row["symbol"], "XYZ_CALL")
        self.assertEqual((row["quantity"], row["price"], row["fee"]), (0, 0, 0))
        self.assertEqual(len(row["transferItems"]), 2)
        self.assertNotIn("private", json.dumps(row))
        self.assertNotIn(ACCOUNT_NUMBER, json.dumps(row))
        summary = ledger.summarize_transactions([row])
        self.assertEqual(summary["netAmountAcrossWindow"], -125.5)
        self.assertEqual(summary["optionLegCount"], 1)
        self.assertEqual(summary["optionLegsMissingPositionEffect"], 0)

    def test_multi_leg_cash_not_repeated_and_nonfinite_not_zero(self):
        raw = dict(TRANSACTIONS[0], transferItems=TRANSACTIONS[0]["transferItems"] * 2)
        row = ledger.normalize_transaction(raw, account_suffix_value="1234")
        self.assertIsNone(row["symbol"])
        self.assertEqual(row["assetType"], "MULTI_ASSET")
        summary = ledger.summarize_transactions([row])
        self.assertEqual(summary["optionLegCount"], 2)
        self.assertEqual(summary["optionTransactionCount"], 1)
        self.assertEqual(summary["netAmountAcrossWindow"], -125.5)
        for value in (True, False, "NaN", float("inf"), "-inf", "garbage"):
            self.assertIsNone(ledger.number(value))

    def test_duplicate_transaction_id_suppressed_conflict_blocks(self):
        report = ledger.finish_report(ledger.base_report(), rows_by_suffix=[("1234", TRANSACTIONS * 2)], source_status="fixture")
        self.assertEqual(report["duplicateTransactionsSuppressed"], 1)
        self.assertEqual(report["transactionSummary"]["netAmountAcrossWindow"], -125.5)
        conflict = dict(TRANSACTIONS[0], netAmount=100)
        report = ledger.finish_report(ledger.base_report(), rows_by_suffix=[("1234", TRANSACTIONS + [conflict])], source_status="fixture")
        self.assertFalse(report["ok"])
        self.assertEqual(report["verdict"], "conflicting-transactions")

    def test_failure_retains_last_good_json_csv_and_original_evidence_time(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(ledger, "SCHWAB_TRANSACTION_LEDGER_FILE", root / "ledger.json"), patch.object(ledger, "SCHWAB_TRANSACTION_LEDGER_TEXT_FILE", root / "ledger.txt"), patch.object(ledger, "SCHWAB_TRANSACTION_CSV_FILE", root / "ledger.csv"):
                good = ledger.finish_report(ledger.base_report(), rows_by_suffix=[("1234", TRANSACTIONS)], source_status="fixture")
                ledger.save_schwab_transaction_ledger(good)
                csv_before = (root / "ledger.csv").read_bytes()
                for _ in range(2):
                    ledger.save_schwab_transaction_ledger(ledger.base_report())
                    saved = json.loads((root / "ledger.json").read_text())
                    self.assertFalse(saved["ok"])
                    self.assertTrue(saved["retainedPriorEvidence"])
                    self.assertEqual(saved["transactions"], good["transactions"])
                    self.assertEqual(saved["evidenceGeneratedAt"], good["generatedAt"])
                    self.assertEqual((root / "ledger.csv").read_bytes(), csv_before)

    @patch.object(ledger, "TOS_ALLOW_LIVE_READONLY", True)
    @patch.object(ledger, "TOS_ALLOWED_ACCOUNT_SUFFIXES", ("1234",))
    def test_fixture_normalizes_transactions_and_never_persists_account_secret(self) -> None:
        report = ledger.build_schwab_transaction_ledger(
            account_numbers_payload=ACCOUNT_NUMBERS,
            transactions_by_hash={ACCOUNT_HASH: TRANSACTIONS},
            now=datetime.fromisoformat("2026-07-22T12:00:00-06:00"),
        )

        rendered = json.dumps(report)
        row = report["transactions"][0]

        self.assertTrue(report["ok"])
        self.assertEqual(report["verdict"], "healthy")
        self.assertEqual(report["matchedSuffixes"], ["1234"])
        self.assertEqual(row["netAmount"], -125.5)
        self.assertEqual(row["assetType"], "OPTION")
        self.assertTrue(row["descriptionPresent"])
        self.assertFalse(report["transactionSummary"]["realizedOptionsProfitKnown"])
        self.assertTrue(report["transactionSummary"]["neverInferRealizedOptionsProfitFromNetCash"])
        self.assertNotIn(ACCOUNT_NUMBER, rendered)
        self.assertNotIn(ACCOUNT_HASH, rendered)
        self.assertNotIn("Private account", rendered)

    @patch.object(ledger, "TOS_ALLOW_LIVE_READONLY", True)
    @patch.object(ledger, "TOS_ALLOWED_ACCOUNT_SUFFIXES", ("1234",))
    def test_save_replaces_canonical_csv_only_from_complete_redacted_report(self) -> None:
        report = ledger.build_schwab_transaction_ledger(
            account_numbers_payload=ACCOUNT_NUMBERS,
            transactions_by_hash={ACCOUNT_HASH: TRANSACTIONS},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_path = root / "data" / "inferno_schwab_transaction_ledger.json"
            text_path = root / "reports" / "schwab_transaction_ledger_latest.txt"
            csv_path = root / "data" / "schwab_transactions.csv"
            report_path.parent.mkdir()
            text_path.parent.mkdir()
            with (
                patch.object(ledger, "SCHWAB_TRANSACTION_LEDGER_FILE", report_path),
                patch.object(ledger, "SCHWAB_TRANSACTION_LEDGER_TEXT_FILE", text_path),
                patch.object(ledger, "SCHWAB_TRANSACTION_CSV_FILE", csv_path),
            ):
                ledger.save_schwab_transaction_ledger(report)

            saved = report_path.read_text(encoding="utf-8")
            csv_text = csv_path.read_text(encoding="utf-8")
            rows = list(csv.DictReader(csv_text.splitlines()))
            self.assertEqual(rows[0]["account_suffix"], "1234")
            self.assertEqual(rows[0]["net_amount"], "-125.5")
            self.assertNotIn(ACCOUNT_NUMBER, saved + csv_text)
            self.assertNotIn(ACCOUNT_HASH, saved + csv_text)

    @patch.object(ledger, "TOS_ALLOW_LIVE_READONLY", True)
    @patch.object(ledger, "TOS_ALLOWED_ACCOUNT_SUFFIXES", ("9999",))
    def test_unapproved_fixture_is_blocked_without_retaining_its_transactions(self) -> None:
        report = ledger.build_schwab_transaction_ledger(
            account_numbers_payload=ACCOUNT_NUMBERS,
            transactions_by_hash={ACCOUNT_HASH: TRANSACTIONS},
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["verdict"], "blocked")
        self.assertEqual(report["transactions"], [])
        self.assertNotIn("XYZ", json.dumps(report))

    @patch.object(ledger, "TOS_ALLOW_LIVE_READONLY", True)
    @patch.object(ledger, "transaction_ledger_enabled", return_value=True)
    @patch.object(
        ledger,
        "token_status",
        return_value={
            "envFileExists": True,
            "clientIdConfigured": True,
            "clientSecretConfigured": True,
            "tokenFileExists": True,
            "accessTokenPresent": True,
            "accessTokenNeedsRefresh": True,
            "reauthorizationRequired": False,
        },
    )
    @patch.object(ledger, "load_config", return_value={})
    def test_expiring_token_blocks_before_account_request(self, _config, _status, _enabled) -> None:
        with patch.object(ledger, "schwab_get") as schwab_get:
            report = ledger.build_schwab_transaction_ledger()

        self.assertEqual(report["verdict"], "access-token-refresh-needed")
        self.assertIn("no account request", report["message"])
        schwab_get.assert_not_called()

    @patch.object(ledger, "TOS_ALLOW_LIVE_READONLY", True)
    @patch.object(ledger, "TOS_ALLOWED_ACCOUNT_SUFFIXES", ("1234",))
    @patch.object(ledger, "transaction_ledger_enabled", return_value=True)
    @patch.object(
        ledger,
        "token_status",
        return_value={
            "envFileExists": True,
            "clientIdConfigured": True,
            "clientSecretConfigured": True,
            "tokenFileExists": True,
            "accessTokenPresent": True,
            "accessTokenNeedsRefresh": False,
            "reauthorizationRequired": False,
        },
    )
    @patch.object(ledger, "load_access_token", return_value="access-token")
    @patch.object(ledger, "load_config", return_value={"api_base_url": "https://api.schwabapi.com"})
    def test_transaction_endpoint_failure_does_not_leak_account_hash(
        self,
        _config,
        _token,
        _status,
        _enabled,
    ) -> None:
        endpoint = ledger.TRANSACTIONS_ENDPOINT_TEMPLATE.format(account_hash=ACCOUNT_HASH)
        with patch.object(
            ledger,
            "schwab_get",
            side_effect=[ACCOUNT_NUMBERS, SchwabAccountAPIError(f"bad response from {endpoint}", endpoint=endpoint)],
        ):
            report = ledger.build_schwab_transaction_ledger()

        rendered = json.dumps(report)
        self.assertEqual(report["verdict"], "fetch-failed")
        self.assertIn("transaction API", report["message"])
        self.assertNotIn(ACCOUNT_HASH, rendered)
        self.assertNotIn(endpoint, rendered)


if __name__ == "__main__":
    unittest.main()
