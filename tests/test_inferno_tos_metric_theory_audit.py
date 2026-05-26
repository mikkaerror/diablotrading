from __future__ import annotations

"""Tests for anti-confirmation audit of TOS custom metrics."""

import unittest

from inferno_schwab_price_history import build_report
from inferno_tos_metric_theory_audit import (
    FORMULA_THEORY,
    build_theory_audit,
    theory_audit_text,
)


def sample_history_payload(symbol: str = "TEST", days: int = 252, *, falling: bool = False) -> dict[str, object]:
    """Build deterministic Schwab-style candles."""
    base_ms = 1_700_000_000_000
    candles = []
    for index in range(days):
        day = index + 1
        close = 300.0 - day if falling else 50.0 + day
        candles.append(
            {
                "datetime": base_ms + day * 86_400_000,
                "open": close - 0.4,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 2_000_000 if day == days else 1_000_000,
            }
        )
    return {"symbol": symbol, "candles": candles}


class InfernoTosMetricTheoryAuditTests(unittest.TestCase):
    def test_theory_audit_marks_raw_momentum_as_needing_review(self) -> None:
        price_history = build_report(
            ["TEST"],
            fixture_payloads={"TEST": sample_history_payload()},
        )

        audit = build_theory_audit(price_history)

        self.assertEqual(audit["verdict"], "formula-policy-needs-review")
        self.assertEqual(audit["checked"], 1)
        self.assertEqual(audit["rows"][0]["posture"], "supports-thesis")
        self.assertEqual(FORMULA_THEORY["tos_momentum"]["theoryVerdict"], "revise-before-ranking")
        self.assertTrue(audit["authority"]["readOnly"])
        self.assertFalse(audit["authority"]["touchesTos"])
        self.assertFalse(audit["authority"]["stagesTrades"])

    def test_challenge_evidence_is_not_suppressed(self) -> None:
        price_history = build_report(
            ["DOWN"],
            fixture_payloads={"DOWN": sample_history_payload("DOWN", falling=True)},
        )

        audit = build_theory_audit(price_history)

        row = audit["rows"][0]
        challenge_messages = [
            item["message"]
            for item in (row["evidence"]["challenges"] or [])
        ]
        self.assertEqual(row["posture"], "challenges-thesis")
        self.assertTrue(any("negative" in message for message in challenge_messages))
        self.assertIn("Raw MOM is dollar-denominated", row["evidence"]["antiYesManCaveats"][0])

    def test_text_report_calls_out_formula_policy_and_next_actions(self) -> None:
        price_history = build_report(
            ["TEST"],
            fixture_payloads={"TEST": sample_history_payload()},
        )
        audit = build_theory_audit(price_history)
        text = theory_audit_text(audit)

        self.assertIn("Formula policy", text)
        self.assertIn("revise-before-ranking", text)
        self.assertIn("Treat raw MOM as display only", text)


if __name__ == "__main__":
    unittest.main()
