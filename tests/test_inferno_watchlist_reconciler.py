from __future__ import annotations

"""Regression tests for the watchlist reconciler.

Contract:
- three-way drift buckets correctly partition the inputs
- verdict ladder: clean / drift-minor / drift-major / blocked
- blocked when extract artifact or sheet read fail
- stage constant ends with research-only; payload freezes the contract
- text renderer surfaces every bucket
"""

import unittest

import inferno_watchlist_reconciler as reconciler


def make_loaders(tos, sheet, tracker, *, tos_error=None, sheet_error=None, tracker_error=None):
    def tos_loader():
        diag = {"source": "test"}
        if tos_error:
            diag["error"] = tos_error
        return list(tos), diag

    def sheet_loader():
        diag = {"source": "test"}
        if sheet_error:
            diag["error"] = sheet_error
        return list(sheet), diag

    def tracker_loader():
        diag = {"source": "test"}
        if tracker_error:
            diag["error"] = tracker_error
        return list(tracker), diag

    return tos_loader, sheet_loader, tracker_loader


class ContractTests(unittest.TestCase):
    def test_stage_constant(self) -> None:
        self.assertTrue(reconciler.WATCHLIST_RECONCILER_STAGE.endswith("research-only"))

    def test_payload_freezes_research_contract(self) -> None:
        loaders = make_loaders(["NVDA"], ["NVDA"], ["NVDA"])
        payload = reconciler.build_reconciliation(
            tos_loader=loaders[0],
            sheet_loader=loaders[1],
            tracker_loader=loaders[2],
        )
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["diagnosticOnly"])


class DriftBucketTests(unittest.TestCase):
    def test_clean_when_tos_and_sheet_match(self) -> None:
        loaders = make_loaders(["NVDA", "AMD"], ["NVDA", "AMD"], ["NVDA", "AMD"])
        payload = reconciler.build_reconciliation(
            tos_loader=loaders[0], sheet_loader=loaders[1], tracker_loader=loaders[2],
        )
        self.assertEqual(payload["verdict"], "clean")
        self.assertEqual(payload["inTosOnly"], [])
        self.assertEqual(payload["inSheetOnly"], [])

    def test_drift_minor_when_few_in_tos_only(self) -> None:
        loaders = make_loaders(
            ["NVDA", "AMD", "AVGO"],
            ["NVDA", "AMD"],
            ["NVDA", "AMD"],
        )
        payload = reconciler.build_reconciliation(
            tos_loader=loaders[0], sheet_loader=loaders[1], tracker_loader=loaders[2],
        )
        self.assertEqual(payload["verdict"], "drift-minor")
        self.assertEqual(payload["inTosOnly"], ["AVGO"])

    def test_drift_major_when_in_sheet_only_present(self) -> None:
        loaders = make_loaders(
            ["NVDA"],
            ["NVDA", "OLD_TICKER"],
            ["NVDA"],
        )
        payload = reconciler.build_reconciliation(
            tos_loader=loaders[0], sheet_loader=loaders[1], tracker_loader=loaders[2],
        )
        self.assertEqual(payload["verdict"], "drift-major")
        self.assertEqual(payload["inSheetOnly"], ["OLD_TICKER"])

    def test_drift_major_when_many_in_tos_only(self) -> None:
        many = [f"T{i}" for i in range(reconciler.MINOR_DRIFT_LIMIT + 5)]
        loaders = make_loaders(many, [], [])
        payload = reconciler.build_reconciliation(
            tos_loader=loaders[0], sheet_loader=loaders[1], tracker_loader=loaders[2],
        )
        self.assertEqual(payload["verdict"], "drift-major")
        self.assertEqual(len(payload["inTosOnly"]), len(many))

    def test_blocked_when_extract_error(self) -> None:
        loaders = make_loaders([], ["NVDA"], ["NVDA"], tos_error="extract artifact missing")
        payload = reconciler.build_reconciliation(
            tos_loader=loaders[0], sheet_loader=loaders[1], tracker_loader=loaders[2],
        )
        self.assertEqual(payload["verdict"], "blocked")
        self.assertTrue(any("tos-extract" in reason for reason in payload["blockedReasons"]))

    def test_blocked_when_sheet_error(self) -> None:
        loaders = make_loaders(["NVDA"], [], ["NVDA"], sheet_error="creds missing")
        payload = reconciler.build_reconciliation(
            tos_loader=loaders[0], sheet_loader=loaders[1], tracker_loader=loaders[2],
        )
        self.assertEqual(payload["verdict"], "blocked")

    def test_tracker_error_is_not_fatal(self) -> None:
        loaders = make_loaders(
            ["NVDA"], ["NVDA"], [], tracker_error="no tracker artifact found",
        )
        payload = reconciler.build_reconciliation(
            tos_loader=loaders[0], sheet_loader=loaders[1], tracker_loader=loaders[2],
        )
        self.assertEqual(payload["verdict"], "clean")
        self.assertEqual(payload["blockedReasons"], [])


class TextRenderTests(unittest.TestCase):
    def test_text_surfaces_in_tos_only(self) -> None:
        loaders = make_loaders(
            ["NVDA", "AMD"], ["NVDA"], ["NVDA"],
        )
        payload = reconciler.build_reconciliation(
            tos_loader=loaders[0], sheet_loader=loaders[1], tracker_loader=loaders[2],
        )
        text = reconciler.reconciliation_text(payload)
        self.assertIn("Verdict: drift-minor", text)
        self.assertIn("In TOS but not in sheet", text)
        self.assertIn("- AMD", text)


if __name__ == "__main__":
    unittest.main()
