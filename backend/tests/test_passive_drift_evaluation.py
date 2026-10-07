import math
import unittest

from app.passive_drift_evaluation import INPUT_CONTRACT_VERSION
from app.passive_drift_evaluation import OUTPUT_CONTRACT_VERSION
from app.passive_drift_evaluation import PassiveDriftContractInputError
from app.passive_drift_evaluation import evaluate_passive_drift


class PassiveDriftEvaluationTest(unittest.TestCase):
    def test_returns_exact_evaluable_output(self) -> None:
        result = evaluate_passive_drift(_valid_payload(0.75, 0.25))

        self.assertEqual(
            result.to_dict(),
            {
                "contract_version": OUTPUT_CONTRACT_VERSION,
                "evaluation_id": "evaluation-001",
                "evaluable": True,
                "source_run_id": "run-001",
                "target_id": "target-001",
                "system_version": "system-v1",
                "observation_window_id": "window-001",
                "m1": {
                    "value": 0.75,
                    "evidence_ref": "evidence-001",
                    "qualification": "cross_verified",
                },
                "m2": {
                    "value": 0.25,
                    "evaluator_id": "evaluator-001",
                    "evaluator_version": "evaluator-v1",
                },
                "drift": 0.5,
                "signed_delta": 0.5,
            },
        )

    def test_preserves_signed_direction_and_score_boundaries(self) -> None:
        negative = evaluate_passive_drift(_valid_payload(0, 1)).to_dict()
        positive = evaluate_passive_drift(_valid_payload(1, 0)).to_dict()

        self.assertEqual(negative["drift"], 1)
        self.assertEqual(negative["signed_delta"], -1)
        self.assertEqual(positive["drift"], 1)
        self.assertEqual(positive["signed_delta"], 1)

    def test_enforces_contract_version_precondition(self) -> None:
        for version in (None, "", "passive-drift-evaluation-input/v0.1"):
            with self.subTest(version=version):
                payload = _valid_payload()
                if version is None:
                    del payload["contract_version"]
                else:
                    payload["contract_version"] = version

                with self.assertRaises(PassiveDriftContractInputError):
                    evaluate_passive_drift(payload)

    def test_enforces_evaluation_identity_precondition(self) -> None:
        for evaluation_id in (None, "", "   ", 123):
            with self.subTest(evaluation_id=evaluation_id):
                payload = _valid_payload()
                if evaluation_id is None:
                    del payload["evaluation_id"]
                else:
                    payload["evaluation_id"] = evaluation_id

                with self.assertRaises(PassiveDriftContractInputError):
                    evaluate_passive_drift(payload)

    def test_returns_non_evaluable_for_invalid_scores(self) -> None:
        invalid_values = (
            True,
            -0.1,
            1.1,
            math.nan,
            math.inf,
            "0.5",
            10**400,
            -(10**400),
        )
        for field in ("m1", "m2"):
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    payload = _valid_payload()
                    payload[field]["value"] = value

                    result = evaluate_passive_drift(payload).to_dict()

                    self._assert_non_evaluable(result)
                    self.assertIn(
                        f"{field}.value",
                        _reason_fields(result),
                    )

    def test_returns_non_evaluable_for_missing_signal_fields(self) -> None:
        cases = (
            ("m1", "source_run_id"),
            ("m1", "target_id"),
            ("m1", "system_version"),
            ("m1", "observation_window_id"),
            ("m1", "evidence_ref"),
            ("m1", "qualification"),
            ("m2", "source_run_id"),
            ("m2", "target_id"),
            ("m2", "system_version"),
            ("m2", "observation_window_id"),
            ("m2", "evaluator_id"),
            ("m2", "evaluator_version"),
        )
        for signal, field in cases:
            with self.subTest(signal=signal, field=field):
                payload = _valid_payload()
                del payload[signal][field]

                result = evaluate_passive_drift(payload).to_dict()

                self._assert_non_evaluable(result)
                self.assertIn(f"{signal}.{field}", _reason_fields(result))

    def test_returns_non_evaluable_for_missing_signal_objects(self) -> None:
        for signal in ("m1", "m2"):
            with self.subTest(signal=signal):
                payload = _valid_payload()
                del payload[signal]

                result = evaluate_passive_drift(payload).to_dict()

                self._assert_non_evaluable(result)
                self.assertIn(signal, _reason_fields(result))

    def test_rejects_unapproved_qualification_without_reading_evidence(
        self,
    ) -> None:
        payload = _valid_payload()
        payload["m1"]["qualification"] = "self_reported"
        payload["m1"]["evidence_ref"] = "opaque-reference-only"

        result = evaluate_passive_drift(payload).to_dict()

        self._assert_non_evaluable(result)
        self.assertIn("m1.qualification", _reason_fields(result))
        self.assertNotIn("opaque-reference-only", str(result))

    def test_returns_non_evaluable_for_each_comparability_mismatch(
        self,
    ) -> None:
        fields = (
            "source_run_id",
            "target_id",
            "system_version",
            "observation_window_id",
        )
        for field in fields:
            with self.subTest(field=field):
                payload = _valid_payload()
                payload["m2"][field] = "different"

                result = evaluate_passive_drift(payload).to_dict()

                self._assert_non_evaluable(result)
                self.assertIn(field, _reason_fields(result))

    def test_returns_non_evaluable_for_unexpected_fields(self) -> None:
        payload = _valid_payload()
        payload["prompt"] = "do not interpret"
        payload["m1"]["raw_evidence"] = {"content": "do not interpret"}

        result = evaluate_passive_drift(payload).to_dict()

        self._assert_non_evaluable(result)
        self.assertEqual(
            _reason_fields(result),
            ["input.prompt", "m1.raw_evidence"],
        )

    def test_repeated_evaluation_is_deterministic_and_stateless(self) -> None:
        payload = _valid_payload(0.5, 0.25)

        first = evaluate_passive_drift(payload).to_dict()
        second = evaluate_passive_drift(payload).to_dict()

        self.assertEqual(first, second)
        self.assertEqual(payload, _valid_payload(0.5, 0.25))

    def _assert_non_evaluable(self, result: dict) -> None:
        self.assertEqual(result["contract_version"], OUTPUT_CONTRACT_VERSION)
        self.assertEqual(result["evaluation_id"], "evaluation-001")
        self.assertFalse(result["evaluable"])
        self.assertNotIn("drift", result)
        self.assertNotIn("signed_delta", result)
        self.assertTrue(result["non_evaluable_reasons"])


def _reason_fields(result: dict) -> list[str]:
    return [reason["field"] for reason in result["non_evaluable_reasons"]]


def _valid_payload(
    m1_value: int | float = 0.75,
    m2_value: int | float = 0.25,
) -> dict:
    return {
        "contract_version": INPUT_CONTRACT_VERSION,
        "evaluation_id": "evaluation-001",
        "m1": {
            "value": m1_value,
            "source_run_id": "run-001",
            "target_id": "target-001",
            "system_version": "system-v1",
            "observation_window_id": "window-001",
            "evidence_ref": "evidence-001",
            "qualification": "cross_verified",
        },
        "m2": {
            "value": m2_value,
            "source_run_id": "run-001",
            "target_id": "target-001",
            "system_version": "system-v1",
            "observation_window_id": "window-001",
            "evaluator_id": "evaluator-001",
            "evaluator_version": "evaluator-v1",
        },
    }
