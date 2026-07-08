from __future__ import annotations

"""Doctor guard tests for expected-move ledger integrity."""

import unittest
from unittest.mock import patch

from inferno_doctor import expected_move_ledger_status


class ExpectedMoveDoctorGuardTests(unittest.TestCase):
    """The doctor should reject corrupted realized-move evidence."""

    def test_expected_move_ledger_status_rejects_data_integrity_failures(self) -> None:
        with patch("inferno_doctor.recent_or_today", return_value=True):
            ok, detail = expected_move_ledger_status(
                {
                    "generatedAt": "2026-07-07T12:00:00-06:00",
                    "verdict": "move-edge-watch",
                    "promotable": False,
                    "counts": {"closedLongVolRecords": 100},
                    "dataIntegrity": {
                        "records": 100,
                        "distinctRealizedValues": 30,
                        "replicationRatio": 3.33,
                        "implausibleMagnitudeThresholdPct": 40.0,
                        "implausibleMagnitudeRecords": 17,
                        "frozenRealizedNames": ["KEYS", "MRVL", "VNET"],
                        "duplicateEventCount": 70,
                        "reliable": False,
                    },
                }
            )

        self.assertFalse(ok)
        self.assertIn("data-integrity-fail", detail)
        self.assertIn("replication=3.33", detail)
        self.assertIn("frozen=KEYS,MRVL,VNET", detail)

    def test_expected_move_ledger_status_accepts_reliable_data_integrity(self) -> None:
        with patch("inferno_doctor.recent_or_today", return_value=True):
            ok, detail = expected_move_ledger_status(
                {
                    "generatedAt": "2026-07-07T12:00:00-06:00",
                    "verdict": "move-edge-negative",
                    "promotable": False,
                    "counts": {"closedLongVolRecords": 13},
                    "dataIntegrity": {
                        "records": 13,
                        "effectiveObservations": 13,
                        "reliable": True,
                    },
                }
            )

        self.assertTrue(ok)
        self.assertIn("data-integrity=ok", detail)


if __name__ == "__main__":
    unittest.main()
