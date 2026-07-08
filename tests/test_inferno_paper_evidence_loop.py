from __future__ import annotations

"""Regression tests for the paper evidence-loop audit."""

import unittest
from unittest.mock import patch

from inferno_paper_evidence_loop import build_audit


class InfernoPaperEvidenceLoopTests(unittest.TestCase):
    """Verify the audit points at the real bottleneck."""

    @patch("inferno_paper_evidence_loop.load_paper_director")
    @patch("inferno_paper_evidence_loop.load_fill_rows")
    @patch("inferno_paper_evidence_loop.load_json_file")
    def test_build_audit_marks_approval_bottleneck(
        self,
        mock_load_json_file,
        mock_load_fill_rows,
        mock_load_paper_director,
    ) -> None:
        mock_load_fill_rows.return_value = []
        mock_load_paper_director.return_value = {
            "counts": {"approvalOnly": 1},
            "approvalSlate": [{"ticker": "WSC"}],
        }
        mock_load_json_file.side_effect = [
            {"stageableCount": 0, "stageableTickets": []},
            {"unmatchedRows": [], "openedRows": 0, "closedRows": 0},
            {"items": []},
            {"items": []},
            {"closedMetrics": {"scoredCount": 0}},
            {"deskVerdict": {"level": "insufficient-data"}},
        ]
        payload = build_audit()
        self.assertEqual(payload["verdict"], "approval-bottleneck")
        self.assertEqual(payload["counts"]["approvalOnly"], 1)
        self.assertEqual(payload["approvalTickers"], ["WSC"])

    @patch("inferno_paper_evidence_loop.load_paper_director")
    @patch("inferno_paper_evidence_loop.load_fill_rows")
    @patch("inferno_paper_evidence_loop.load_json_file")
    def test_build_audit_marks_operator_candidates_without_staging_instruction(
        self,
        mock_load_json_file,
        mock_load_fill_rows,
        mock_load_paper_director,
    ) -> None:
        mock_load_fill_rows.return_value = []
        mock_load_paper_director.return_value = {
            "counts": {"autoPaperSelected": 1, "approvalOnly": 0},
            "approvalSlate": [{"ticker": "MOD"}],
        }
        mock_load_json_file.side_effect = [
            {"stageableCount": 0, "stageableTickets": []},
            {"unmatchedRows": [], "openedRows": 0, "closedRows": 0},
            {"items": []},
            {"items": []},
            {"closedMetrics": {"scoredCount": 1}},
            {"deskVerdict": {"level": "insufficient-data"}},
        ]
        payload = build_audit()
        action_text = " ".join(payload["actions"])
        self.assertEqual(payload["verdict"], "operator-paper-candidates")
        self.assertIn("operator-owned paper workflow", action_text)
        self.assertNotIn("Paper-stage", action_text)
        self.assertNotIn("ready-to-stage", payload["verdict"])

    @patch("inferno_paper_evidence_loop.load_paper_director")
    @patch("inferno_paper_evidence_loop.load_fill_rows")
    @patch("inferno_paper_evidence_loop.load_json_file")
    def test_build_audit_preserves_stageable_count_as_operator_routable(
        self,
        mock_load_json_file,
        mock_load_fill_rows,
        mock_load_paper_director,
    ) -> None:
        mock_load_fill_rows.return_value = []
        mock_load_paper_director.return_value = {"counts": {"autoPaperSelected": 0}, "approvalSlate": []}
        mock_load_json_file.side_effect = [
            {"stageableCount": 1, "stageableTickets": [{"ticker": "FCX"}]},
            {"unmatchedRows": [], "openedRows": 0, "closedRows": 0},
            {"items": []},
            {"items": []},
            {"closedMetrics": {"scoredCount": 1}},
            {"deskVerdict": {"level": "insufficient-data"}},
        ]
        payload = build_audit()
        self.assertEqual(payload["verdict"], "operator-paper-candidates")
        self.assertEqual(payload["counts"]["stageableNow"], 1)
        self.assertEqual(payload["stageableTickers"], ["FCX"])

    @patch("inferno_paper_evidence_loop.load_paper_director")
    @patch("inferno_paper_evidence_loop.load_fill_rows")
    @patch("inferno_paper_evidence_loop.load_json_file")
    def test_build_audit_marks_collect_outcomes_when_open_rows_exist(
        self,
        mock_load_json_file,
        mock_load_fill_rows,
        mock_load_paper_director,
    ) -> None:
        mock_load_fill_rows.return_value = [
            {"ticketId": "abc", "status": "open", "ticker": "OTEX"},
            {"ticketId": "def", "status": "planned", "ticker": "AMD"},
        ]
        mock_load_paper_director.return_value = {"counts": {"approvalOnly": 0}, "approvalSlate": []}
        mock_load_json_file.side_effect = [
            {"stageableCount": 0, "stageableTickets": []},
            {"unmatchedRows": [], "openedRows": 1, "closedRows": 0},
            {"items": [{"ticketId": "abc", "ticker": "OTEX", "status": "paper-staged", "paperExecution": {"status": "open"}}]},
            {"items": []},
            {"closedMetrics": {"scoredCount": 2}},
            {"deskVerdict": {"level": "evidence-building"}},
        ]
        payload = build_audit()
        self.assertEqual(payload["verdict"], "collect-paper-outcomes")
        self.assertEqual(payload["counts"]["openFillRows"], 1)
        self.assertEqual(payload["counts"]["paperOpenTickets"], 1)
        self.assertIn("OTEX", payload["openPaperTickers"])
        self.assertIn("unattended agents must not close tickets", " ".join(payload["actions"]))
        self.assertNotIn("Close or update", " ".join(payload["actions"]))


if __name__ == "__main__":
    unittest.main()
