from __future__ import annotations

"""Tests for inferno_math_verify.

Counter-arguments the module must survive:

1. Missing artifact reported, not crashed.
2. Clean synthetic artifact passes every invariant.
3. Wilson lower > upper is caught.
4. Bootstrap point outside CI is caught.
5. Composite > component (geometric mean violation) is caught.
6. Kelly f_capped > MAX_KELLY is caught.
7. Bayesian P>0.5 < P>edge with edge>=0.5 is caught.
8. NMI rows not sorted desc is caught.
9. researchOnly / promotable / diagnosticOnly contract frozen.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import inferno_math_verify as mv


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _setup_clean_artifacts(data_dir: Path) -> None:
    _write(data_dir / "inferno_theme_synthesizer.json", {
        "edges": [{"metrics": {
            "winRate": 0.7, "winRateLower": 0.5, "winRateUpper": 0.85,
            "expectancyMean": 0.4, "expectancyLower": 0.1, "expectancyUpper": 0.7,
        }}],
        "antiEdges": [],
    })
    _write(data_dir / "inferno_devils_advocate.json", {
        "edgesHolding": 1, "edgesWeak": 0, "edgesFalsified": 0, "insufficientCount": 0,
        "strategyCount": 1,
        "results": [{"strategy": "X", "pValue": 0.02, "sampleSize": 20}],
    })
    _write(data_dir / "inferno_evidence_strength.json", {
        "strength": 0.4,
        "components": {"a": 0.5, "b": 0.6, "c": 0.5},
    })
    _write(data_dir / "inferno_kelly_sizing.json", {
        "maxKellyFraction": 0.25,
        "maxDailyRiskUnits": 3.0,
        "totalRecommendedRiskUnits": 0.5,
        "rows": [{"strategy": "X", "kellyFractionCapped": 0.2, "kellyFractionConservative": 0.2}],
    })
    _write(data_dir / "inferno_vol_premium.json", {
        "discriminators": [{"direction": "short-vol", "discriminator": 0.3, "lower": 0.1, "upper": 0.5}],
    })
    _write(data_dir / "inferno_bayesian_winrate.json", {
        "rows": [{
            "strategy": "X",
            "credibleLower": 0.4, "credibleUpper": 0.7,
            "posteriorMean": 0.6,
            "probabilityAboveCoin": 0.8,
            "probabilityAboveEdge": 0.5,
            "edgeThreshold": 0.55,
        }],
    })
    _write(data_dir / "inferno_information_gain.json", {
        "rows": [
            {"feature": "a", "miBits": 0.3, "normalisedMI": 0.5, "permutationPValue": 0.01},
            {"feature": "b", "miBits": 0.1, "normalisedMI": 0.2, "permutationPValue": 0.05},
        ],
    })
    _write(data_dir / "inferno_walk_forward.json", {
        "rows": [{
            "strategy": "X",
            "sampleSize": 20, "trainSize": 10, "validateSize": 10,
            "trainWinRate": 0.7, "trainWilsonLower": 0.4,
            "validateWinRate": 0.6, "validateWilsonLower": 0.3,
        }],
    })
    _write(data_dir / "inferno_regime_drift.json", {
        "alarmH": 5.0,
        "rows": [{
            "strategy": "X",
            "sampleSize": 20, "halfSplitIndex": 10,
            "baselineStd": 1.0, "alarmThreshold": 5.0,
            "maxPositiveCusum": 0.5, "maxNegativeCusum": -0.3,
        }],
    })
    _write(data_dir / "inferno_factor_regression.json", {
        "sampleSize": 40,
        "featureCount": 1,
        "positiveEdgeCount": 1,
        "negativeEdgeCount": 0,
        "inconclusiveCount": 0,
        "insufficientCount": 0,
        "coefficients": [{
            "feature": "ivBucket=high",
            "coefficient": 0.2,
            "lower95": 0.1,
            "upper95": 0.3,
            "verdict": "positive-edge",
        }],
    })


class ContractTests(unittest.TestCase):
    def test_stage(self) -> None:
        self.assertTrue(mv.MATH_VERIFY_STAGE.endswith("research-only"))

    def test_clean_payload_contract(self) -> None:
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _setup_clean_artifacts(data_dir)
            payload = mv.build_math_verify(data_dir=data_dir)
            self.assertTrue(payload["researchOnly"])
            self.assertFalse(payload["promotable"])
            self.assertTrue(payload["diagnosticOnly"])


class CleanRunTests(unittest.TestCase):
    def test_clean_artifacts_pass(self) -> None:
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _setup_clean_artifacts(data_dir)
            payload = mv.build_math_verify(data_dir=data_dir)
            self.assertEqual(payload["verdict"], "clean")
            self.assertEqual(payload["totalViolations"], 0)

    def test_missing_artifacts_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            # Don't write anything; every artifact is missing.
            payload = mv.build_math_verify(data_dir=data_dir)
            self.assertEqual(payload["verdict"], "artifacts-missing")
            self.assertEqual(payload["totalViolations"], 0)
            self.assertEqual(payload["missingArtifacts"], len(mv.VERIFIERS))


class ViolationDetectionTests(unittest.TestCase):
    def test_wilson_inverted_caught(self) -> None:
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _setup_clean_artifacts(data_dir)
            _write(data_dir / "inferno_theme_synthesizer.json", {
                "edges": [{"metrics": {
                    "winRate": 0.7, "winRateLower": 0.9, "winRateUpper": 0.5,  # INVERTED
                    "expectancyMean": 0.4, "expectancyLower": 0.1, "expectancyUpper": 0.7,
                }}],
                "antiEdges": [],
            })
            payload = mv.build_math_verify(data_dir=data_dir)
            self.assertEqual(payload["verdict"], "violations-detected")
            self.assertGreater(payload["findings"]["theme"]["violationCount"], 0)

    def test_kelly_over_cap_caught(self) -> None:
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _setup_clean_artifacts(data_dir)
            _write(data_dir / "inferno_kelly_sizing.json", {
                "maxKellyFraction": 0.25,
                "maxDailyRiskUnits": 3.0,
                "totalRecommendedRiskUnits": 0.5,
                "rows": [{"strategy": "X", "kellyFractionCapped": 0.5, "kellyFractionConservative": 0.5}],  # over cap
            })
            payload = mv.build_math_verify(data_dir=data_dir)
            self.assertGreater(payload["findings"]["kelly"]["violationCount"], 0)

    def test_composite_greater_than_component_caught(self) -> None:
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _setup_clean_artifacts(data_dir)
            _write(data_dir / "inferno_evidence_strength.json", {
                "strength": 0.9,  # composite higher than weakest component → violation
                "components": {"a": 0.95, "b": 0.5, "c": 0.95},
            })
            payload = mv.build_math_verify(data_dir=data_dir)
            self.assertGreater(payload["findings"]["evidenceStrength"]["violationCount"], 0)

    def test_composite_strength_schema_is_verified(self) -> None:
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _setup_clean_artifacts(data_dir)
            _write(data_dir / "inferno_evidence_strength.json", {
                "compositeStrength": 0.9,  # newer schema spelling
                "components": {"a": 0.95, "b": 0.5, "c": 0.95},
            })
            payload = mv.build_math_verify(data_dir=data_dir)
            self.assertGreater(payload["findings"]["evidenceStrength"]["violationCount"], 0)

    def test_factor_regression_ci_inversion_caught(self) -> None:
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _setup_clean_artifacts(data_dir)
            _write(data_dir / "inferno_factor_regression.json", {
                "sampleSize": 40,
                "featureCount": 1,
                "positiveEdgeCount": 1,
                "negativeEdgeCount": 0,
                "inconclusiveCount": 0,
                "insufficientCount": 0,
                "coefficients": [{
                    "feature": "ivBucket=high",
                    "coefficient": 0.2,
                    "lower95": 0.3,  # inverted
                    "upper95": 0.1,
                    "verdict": "positive-edge",
                }],
            })
            payload = mv.build_math_verify(data_dir=data_dir)
            self.assertGreater(payload["findings"]["factorRegression"]["violationCount"], 0)

    def test_p_value_out_of_unit_caught(self) -> None:
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _setup_clean_artifacts(data_dir)
            _write(data_dir / "inferno_devils_advocate.json", {
                "edgesHolding": 0, "edgesWeak": 0, "edgesFalsified": 0, "insufficientCount": 1,
                "strategyCount": 1,
                "results": [{"strategy": "X", "pValue": 1.5, "sampleSize": 20}],  # p > 1
            })
            payload = mv.build_math_verify(data_dir=data_dir)
            self.assertGreater(payload["findings"]["devilsAdvocate"]["violationCount"], 0)

    def test_nmi_not_sorted_caught(self) -> None:
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _setup_clean_artifacts(data_dir)
            _write(data_dir / "inferno_information_gain.json", {
                "rows": [
                    {"feature": "a", "miBits": 0.1, "normalisedMI": 0.2, "permutationPValue": 0.05},
                    {"feature": "b", "miBits": 0.3, "normalisedMI": 0.5, "permutationPValue": 0.01},  # higher NMI after lower → not sorted
                ],
            })
            payload = mv.build_math_verify(data_dir=data_dir)
            self.assertGreater(payload["findings"]["informationGain"]["violationCount"], 0)

    def test_walk_forward_sum_mismatch_caught(self) -> None:
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _setup_clean_artifacts(data_dir)
            _write(data_dir / "inferno_walk_forward.json", {
                "rows": [{
                    "strategy": "X",
                    "sampleSize": 20, "trainSize": 5, "validateSize": 5,  # 5+5 != 20
                    "trainWinRate": 0.5, "trainWilsonLower": 0.3,
                    "validateWinRate": 0.5, "validateWilsonLower": 0.3,
                }],
            })
            payload = mv.build_math_verify(data_dir=data_dir)
            self.assertGreater(payload["findings"]["walkForward"]["violationCount"], 0)


class TextRenderTests(unittest.TestCase):
    def test_text_has_sections(self) -> None:
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _setup_clean_artifacts(data_dir)
            payload = mv.build_math_verify(data_dir=data_dir)
            text = mv.verify_text(payload)
            self.assertIn("Math Verify", text)
            self.assertIn("Verdict:", text)
            self.assertIn("Per-module findings:", text)


if __name__ == "__main__":
    unittest.main()
