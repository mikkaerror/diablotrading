from __future__ import annotations

"""Adversarial tests for inferno_paper_bootstrap.

Counter-arguments the module must survive:

1. Empty slate → 'no-evidence', no queue entries.
2. Slate with no row scoring at or above threshold → 'insufficient-relaxation'.
3. Some rows admit but below minimum count → 'slate-too-thin'.
4. Enough rows admit → 'ready-to-seed', queue populated, all paperBootstrap=true.
5. Every row clears all 5 gates → 'live-quality-found'.
6. Threshold of 5 ≡ live filter (proposals only emitted when score==5).
7. Threshold of 1 admits anything with one gate cleared.
8. paperBootstrap flag is true on every proposal.
9. liveQualityYet is true only when score==5.
10. researchOnly / promotable / diagnosticOnly contract frozen.
11. max_tickets caps the queue size.
"""

import unittest

import inferno_paper_bootstrap as pb


def make_row(**overrides) -> dict:
    base = {
        "ticker": "TEST",
        "readyScore": 80,
        "confidence": 3,
        "daysUntilEarnings": 10,
        "setupRec": "Bull Vertical",
        "signalTrigger": "breakout",
    }
    base.update(overrides)
    return base


def fake_snapshot(rows: list[dict]) -> dict:
    return {"rows": rows}


class ContractTests(unittest.TestCase):
    def test_stage_is_research_only(self) -> None:
        self.assertTrue(pb.PAPER_BOOTSTRAP_STAGE.endswith("research-only"))

    def test_contract_frozen(self) -> None:
        payload = pb.build_bootstrap(snapshot_loader=lambda: {})
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["diagnosticOnly"])


class ScoreRowTests(unittest.TestCase):
    def test_all_gates_pass_score_five(self) -> None:
        result = pb.score_row(make_row())
        self.assertEqual(result["score"], 5)
        self.assertEqual(result["failedGates"], [])

    def test_computed_readiness_drives_ready_gate(self) -> None:
        result = pb.score_row(make_row(readiness=88, readyScore=2))
        self.assertEqual(result["score"], 5)
        self.assertNotIn("readyOk", result["failedGates"])
        self.assertEqual(result["readiness"], 88)
        self.assertEqual(result["readyScore"], 2)

    def test_low_computed_readiness_fails_even_when_raw_score_is_high(self) -> None:
        result = pb.score_row(make_row(readiness=60, readyScore=99))
        self.assertEqual(result["score"], 4)
        self.assertIn("readyOk", result["failedGates"])

    def test_avoid_setup_fails_setup_gate(self) -> None:
        result = pb.score_row(make_row(setupRec="Avoid"))
        self.assertEqual(result["score"], 4)
        self.assertIn("setupOk", result["failedGates"])

    def test_low_ready_fails_ready_gate(self) -> None:
        result = pb.score_row(make_row(readyScore=50))
        self.assertEqual(result["score"], 4)
        self.assertIn("readyOk", result["failedGates"])

    def test_missing_trigger_fails_trigger_gate(self) -> None:
        result = pb.score_row(make_row(signalTrigger=None))
        self.assertEqual(result["score"], 4)
        self.assertIn("triggerOk", result["failedGates"])

    def test_far_dte_fails_dte_gate(self) -> None:
        result = pb.score_row(make_row(daysUntilEarnings=60))
        self.assertEqual(result["score"], 4)
        self.assertIn("dteOk", result["failedGates"])

    def test_all_fail_score_zero(self) -> None:
        result = pb.score_row(make_row(
            readyScore=10, confidence=0, daysUntilEarnings=99,
            setupRec="Avoid", signalTrigger=None,
        ))
        self.assertEqual(result["score"], 0)
        self.assertEqual(len(result["failedGates"]), 5)


class RankCandidatesTests(unittest.TestCase):
    def test_admits_at_threshold(self) -> None:
        rows = [
            make_row(ticker="A", readyScore=50, confidence=0, daysUntilEarnings=99, setupRec="Avoid", signalTrigger=None),  # 0/5
            make_row(ticker="B", readyScore=80, confidence=3),  # 5/5
            make_row(ticker="C", readyScore=80, confidence=3, daysUntilEarnings=60),  # 4/5
        ]
        admitted = pb.rank_candidates(rows, admit_threshold=3)
        self.assertEqual([r["ticker"] for r in admitted], ["B", "C"])

    def test_score_5_sorts_above_score_4(self) -> None:
        rows = [
            make_row(ticker="LOWER", readyScore=80, daysUntilEarnings=60),  # 4/5
            make_row(ticker="HIGHER", readyScore=80),  # 5/5
        ]
        admitted = pb.rank_candidates(rows, admit_threshold=3)
        self.assertEqual(admitted[0]["ticker"], "HIGHER")
        self.assertEqual(admitted[1]["ticker"], "LOWER")

    def test_tie_break_sorts_by_computed_readiness_not_raw_score(self) -> None:
        rows = [
            make_row(ticker="RAW_HIGH", readiness=75, readyScore=99),
            make_row(ticker="READY_HIGH", readiness=95, readyScore=1),
        ]
        admitted = pb.rank_candidates(rows, admit_threshold=5)
        self.assertEqual([r["ticker"] for r in admitted], ["READY_HIGH", "RAW_HIGH"])


class BuildBootstrapTests(unittest.TestCase):
    def test_empty_slate(self) -> None:
        payload = pb.build_bootstrap(snapshot_loader=lambda: {})
        self.assertEqual(payload["verdict"], "no-evidence")
        self.assertEqual(payload["proposals"], [])

    def test_insufficient_relaxation(self) -> None:
        rows = [make_row(
            ticker=f"T{i}", readyScore=10, confidence=0,
            daysUntilEarnings=99, setupRec="Avoid", signalTrigger=None,
        ) for i in range(5)]
        payload = pb.build_bootstrap(
            snapshot_loader=lambda: fake_snapshot(rows),
            admit_threshold=3,
        )
        self.assertEqual(payload["verdict"], "insufficient-relaxation")
        self.assertEqual(payload["proposals"], [])

    def test_ready_to_seed(self) -> None:
        rows = [make_row(ticker=f"T{i}") for i in range(5)]
        payload = pb.build_bootstrap(
            snapshot_loader=lambda: fake_snapshot(rows),
            admit_threshold=3,
            max_tickets=3,
        )
        self.assertEqual(payload["verdict"], "live-quality-found")
        self.assertEqual(len(payload["proposals"]), 3)
        for proposal in payload["proposals"]:
            self.assertTrue(proposal["paperBootstrap"])

    def test_mixed_quality_paper_only_and_live(self) -> None:
        rows = [
            make_row(ticker="LIVE1"),
            make_row(ticker="LIVE2"),
            make_row(ticker="LIVE3"),
            make_row(ticker="PAPER1", readyScore=50),  # 4/5
            make_row(ticker="PAPER2", readyScore=50),  # 4/5
        ]
        payload = pb.build_bootstrap(
            snapshot_loader=lambda: fake_snapshot(rows),
            admit_threshold=3,
            max_tickets=5,
        )
        self.assertEqual(payload["verdict"], "ready-to-seed")
        self.assertEqual(payload["liveQualityCount"], 3)
        self.assertEqual(payload["paperOnlyCount"], 2)

    def test_slate_too_thin(self) -> None:
        rows = [
            make_row(ticker="ONLY", readyScore=80),  # 5/5
            make_row(ticker="LOW", readyScore=10, confidence=0, daysUntilEarnings=99, setupRec="Avoid", signalTrigger=None),  # 0/5
        ]
        payload = pb.build_bootstrap(
            snapshot_loader=lambda: fake_snapshot(rows),
            admit_threshold=3,
        )
        self.assertEqual(payload["verdict"], "slate-too-thin")

    def test_threshold_5_equals_live_filter(self) -> None:
        rows = [
            make_row(ticker="LIVE"),
            make_row(ticker="PAPER", readyScore=50),  # 4/5
        ]
        payload = pb.build_bootstrap(
            snapshot_loader=lambda: fake_snapshot(rows * 3),  # 6 rows
            admit_threshold=5,
            max_tickets=10,
        )
        # Only LIVE rows admit at threshold=5
        for proposal in payload["proposals"]:
            self.assertEqual(proposal["ticker"], "LIVE")
            self.assertEqual(proposal["score"], 5)

    def test_threshold_1_admits_almost_everything(self) -> None:
        rows = [make_row(
            ticker=f"T{i}", readyScore=80,
            confidence=0, daysUntilEarnings=99, setupRec="Avoid", signalTrigger=None,
        ) for i in range(5)]  # 1/5 each
        payload = pb.build_bootstrap(
            snapshot_loader=lambda: fake_snapshot(rows),
            admit_threshold=1,
            max_tickets=10,
        )
        self.assertEqual(payload["admittedCount"], 5)

    def test_max_tickets_caps_queue(self) -> None:
        rows = [make_row(ticker=f"T{i}") for i in range(20)]
        payload = pb.build_bootstrap(
            snapshot_loader=lambda: fake_snapshot(rows),
            admit_threshold=3,
            max_tickets=4,
        )
        self.assertEqual(len(payload["proposals"]), 4)

    def test_every_proposal_carries_paper_bootstrap_flag(self) -> None:
        rows = [make_row(ticker=f"T{i}") for i in range(3)]
        payload = pb.build_bootstrap(
            snapshot_loader=lambda: fake_snapshot(rows),
            admit_threshold=3,
        )
        for proposal in payload["proposals"]:
            self.assertTrue(proposal["paperBootstrap"])

    def test_live_quality_flag_only_at_score_5(self) -> None:
        rows = [
            make_row(ticker="FIVE"),
            make_row(ticker="FOUR", readyScore=50),  # 4/5
            make_row(ticker="THREE", readyScore=50, confidence=0),  # 3/5
        ]
        payload = pb.build_bootstrap(
            snapshot_loader=lambda: fake_snapshot(rows),
            admit_threshold=3,
            max_tickets=5,
        )
        by_ticker = {p["ticker"]: p for p in payload["proposals"]}
        self.assertTrue(by_ticker["FIVE"]["liveQualityYet"])
        self.assertFalse(by_ticker["FOUR"]["liveQualityYet"])
        self.assertFalse(by_ticker["THREE"]["liveQualityYet"])

    def test_proposals_carry_readiness_for_reporting(self) -> None:
        rows = [make_row(ticker="READY", readiness=91, readyScore=2)]
        payload = pb.build_bootstrap(
            snapshot_loader=lambda: fake_snapshot(rows),
            admit_threshold=5,
            max_tickets=1,
        )
        self.assertEqual(payload["proposals"][0]["readiness"], 91)
        self.assertEqual(payload["proposals"][0]["readyScore"], 2)


class HistogramTests(unittest.TestCase):
    def test_histogram_sums_to_slate_size(self) -> None:
        rows = [
            make_row(ticker="A"),  # 5
            make_row(ticker="B", readyScore=50),  # 4
            make_row(ticker="C", readyScore=50, confidence=0),  # 3
        ]
        payload = pb.build_bootstrap(snapshot_loader=lambda: fake_snapshot(rows))
        total = sum(payload["scoreHistogram"].values())
        self.assertEqual(total, len(rows))


class TextRenderTests(unittest.TestCase):
    def test_text_has_expected_sections(self) -> None:
        rows = [make_row(ticker=f"T{i}") for i in range(3)]
        payload = pb.build_bootstrap(snapshot_loader=lambda: fake_snapshot(rows))
        text = pb.bootstrap_text(payload)
        self.assertIn("Paper Bootstrap", text)
        self.assertIn("Verdict:", text)
        self.assertIn("Gate-score histogram", text)
        self.assertIn("Thresholds:", text)


if __name__ == "__main__":
    unittest.main()
