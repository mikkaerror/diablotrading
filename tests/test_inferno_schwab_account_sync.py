from __future__ import annotations

"""Regression tests for the read-only Schwab account sync lane."""

import json
import unittest
from unittest.mock import patch

import inferno_schwab_account_sync as schwab_account


ACCOUNT_NUMBERS = [{"accountNumber": "11111234", "hashValue": "hash-secret-123"}]
ACCOUNTS = [
    {
        "securitiesAccount": {
            "type": "MARGIN",
            "accountNumber": "11111234",
            "isDayTrader": False,
            "isClosingOnlyRestricted": False,
            "currentBalances": {
                "liquidationValue": 1000.0,
                "cashBalance": 200.0,
                "cashAvailableForTrading": 150.0,
                "buyingPower": 500.0,
            },
            "positions": [
                {
                    "longQuantity": 4,
                    "averagePrice": 10.0,
                    "marketValue": 220.0,
                    "longOpenProfitLoss": 20.0,
                    "currentDayProfitLoss": 5.0,
                    "currentDayProfitLossPercentage": 2.3,
                    "instrument": {
                        "symbol": "IREN",
                        "description": "IREN LTD",
                        "assetType": "EQUITY",
                    },
                }
            ],
        }
    }
]


class SchwabAccountSyncTests(unittest.TestCase):
    """Pin the privacy and normalization behavior for Schwab account reads."""

    @patch("inferno_schwab_account_sync.TOS_ALLOW_LIVE_READONLY", True)
    @patch("inferno_schwab_account_sync.TOS_ALLOWED_ACCOUNT_SUFFIXES", ("1234",))
    def test_build_report_redacts_account_numbers_and_normalizes_positions(self) -> None:
        report = schwab_account.build_schwab_account_sync(
            account_numbers_payload=ACCOUNT_NUMBERS,
            accounts_payload=ACCOUNTS,
        )

        rendered = json.dumps(report)

        self.assertTrue(report["ok"])
        self.assertEqual(report["verdict"], "healthy")
        self.assertEqual(report["matchedSuffix"], "1234")
        self.assertEqual(report["accountSuffixCandidates"], ["1234"])
        self.assertEqual(report["netLiquidatingValue"], 1000.0)
        self.assertEqual(report["totalCash"], 200.0)
        self.assertEqual(report["positions"][0]["symbol"], "IREN")
        self.assertEqual(report["positions"][0]["qty"], 4)
        self.assertEqual(report["positions"][0]["mark"], 55.0)
        self.assertEqual(report["positions"][0]["plOpen"], 20.0)
        self.assertEqual(report["positions"][0]["plPercent"], 50.0)
        self.assertNotIn("11111234", rendered)
        self.assertNotIn("hash-secret-123", rendered)
        self.assertIn("***1234", rendered)

    @patch("inferno_schwab_account_sync.TOS_ALLOW_LIVE_READONLY", True)
    @patch("inferno_schwab_account_sync.TOS_ALLOWED_ACCOUNT_SUFFIXES", ("9999",))
    def test_unapproved_suffix_blocks_account_sync(self) -> None:
        report = schwab_account.build_schwab_account_sync(
            account_numbers_payload=ACCOUNT_NUMBERS,
            accounts_payload=ACCOUNTS,
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["verdict"], "blocked")
        self.assertIn("approved account suffix", report["message"])

    @patch("inferno_schwab_account_sync.TOS_ALLOW_LIVE_READONLY", True)
    @patch("inferno_schwab_account_sync.TOS_ALLOWED_ACCOUNT_SUFFIXES", ("1234",))
    def test_unapproved_account_holdings_are_not_persisted(self) -> None:
        account_numbers = ACCOUNT_NUMBERS + [{"accountNumber": "22229999", "hashValue": "other-hash"}]
        accounts = ACCOUNTS + [
            {
                "securitiesAccount": {
                    "type": "MARGIN",
                    "accountNumber": "22229999",
                    "currentBalances": {"liquidationValue": 5000.0, "cashBalance": 4000.0},
                    "positions": [
                        {
                            "longQuantity": 99,
                            "averagePrice": 1.0,
                            "marketValue": 999.0,
                            "instrument": {"symbol": "PRIVATE", "assetType": "EQUITY"},
                        }
                    ],
                }
            }
        ]

        report = schwab_account.build_schwab_account_sync(
            account_numbers_payload=account_numbers,
            accounts_payload=accounts,
        )
        rendered = json.dumps(report)

        self.assertTrue(report["ok"])
        self.assertEqual(report["counts"]["accounts"], 2)
        self.assertEqual(report["counts"]["approvedAccounts"], 1)
        self.assertEqual(report["counts"]["positions"], 1)
        self.assertNotIn("PRIVATE", rendered)
        self.assertNotIn("999.0", rendered)
        unapproved = [account for account in report["accounts"] if account["accountSuffix"] == "9999"][0]
        self.assertEqual(unapproved["positions"], [])
        self.assertIsNone(unapproved["netLiquidatingValue"])

    def test_option_position_mark_uses_contract_multiplier(self) -> None:
        row = schwab_account.normalize_position(
            {
                "longQuantity": 2,
                "averagePrice": 1.5,
                "marketValue": 400.0,
                "instrument": {"symbol": "XYZ  260619C00010000", "assetType": "OPTION"},
            }
        )

        self.assertEqual(row["qty"], 2)
        self.assertEqual(row["mark"], 2.0)
        self.assertEqual(row["plOpen"], 100.0)
        self.assertEqual(row["plPercent"], 33.3333)

    def test_build_account_url_targets_read_only_account_endpoint(self) -> None:
        url = schwab_account.build_account_url(
            {"api_base_url": "https://api.schwabapi.com"},
            schwab_account.ACCOUNTS_ENDPOINT,
            {"fields": "positions"},
        )

        self.assertEqual(url, "https://api.schwabapi.com/trader/v1/accounts?fields=positions")

    @patch("inferno_schwab_account_sync.schwab_account_enabled", return_value=True)
    @patch(
        "inferno_schwab_account_sync.refresh_token_if_possible",
        return_value={
            "envFileExists": True,
            "clientIdConfigured": True,
            "clientSecretConfigured": True,
            "tokenFileExists": True,
            "accessTokenPresent": True,
            "refreshTokenPresent": True,
            "reauthorizationRequired": True,
        },
    )
    @patch("inferno_schwab_account_sync.load_config", return_value={})
    def test_reauthorization_required_fails_before_account_api_call(
        self,
        _load_config,
        _refresh,
        _enabled,
    ) -> None:
        with patch("inferno_schwab_account_sync.schwab_get") as schwab_get:
            report = schwab_account.build_schwab_account_sync()

        self.assertEqual(report["verdict"], "reauthorization-required")
        self.assertIn("oauth.py restart", report["nextActions"][0])
        schwab_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
