"""Deterministic passive M1/M2 drift evaluation.

This module implements the passive drift evaluation contract (v0.2). It
validates caller-supplied signal
metadata and computes informational drift only. It does not interpret raw
evidence, persist state, classify health, or trigger actions.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any
from typing import Mapping


INPUT_CONTRACT_VERSION = "passive-drift-evaluation-input/v0.2"
OUTPUT_CONTRACT_VERSION = "passive-drift-evaluation-output/v0.2"

_INPUT_KEYS = frozenset({"contract_version", "evaluation_id", "m1", "m2"})
_M1_KEYS = frozenset(
    {
        "value",
        "source_run_id",
        "target_id",
        "system_version",
        "observation_window_id",
        "evidence_ref",
        "qualification",
    }
)
_M2_KEYS = frozenset(
    {
        "value",
        "source_run_id",
        "target_id",
        "system_version",
        "observation_window_id",
        "evaluator_id",
        "evaluator_version",
    }
)
_QUALIFICATIONS = frozenset({"independent", "cross_verified"})
_COMPARABILITY_FIELDS = (
    "source_run_id",
    "target_id",
    "system_version",
    "observation_window_id",
)


class PassiveDriftContractInputError(ValueError):
    """Raised when a v0.2 envelope precondition is not satisfied."""


@dataclass(frozen=True)
class NonEvaluableReason:
    field: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "field": self.field,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class M1Observation:
    value: int | float
    source_run_id: str
    target_id: str
    system_version: str
    observation_window_id: str
    evidence_ref: str
    qualification: str

    def output_dict(self) -> dict[str, int | float | str]:
        return {
            "value": self.value,
            "evidence_ref": self.evidence_ref,
            "qualification": self.qualification,
        }


@dataclass(frozen=True)
class M2Observation:
    value: int | float
    source_run_id: str
    target_id: str
    system_version: str
    observation_window_id: str
    evaluator_id: str
    evaluator_version: str

    def output_dict(self) -> dict[str, int | float | str]:
        return {
            "value": self.value,
            "evaluator_id": self.evaluator_id,
            "evaluator_version": self.evaluator_version,
        }


@dataclass(frozen=True)
class PassiveDriftEvaluationResult:
    evaluation_id: str
    evaluable: bool
    reasons: tuple[NonEvaluableReason, ...] = ()
    m1: M1Observation | None = None
    m2: M2Observation | None = None
    drift: int | float | None = None
    signed_delta: int | float | None = None

    def to_dict(self) -> dict[str, Any]:
        if not self.evaluable:
            return {
                "contract_version": OUTPUT_CONTRACT_VERSION,
                "evaluation_id": self.evaluation_id,
                "evaluable": False,
                "non_evaluable_reasons": [
                    reason.to_dict() for reason in self.reasons
                ],
            }

        if self.m1 is None or self.m2 is None:
            raise AssertionError("Evaluable result requires M1 and M2.")
        if self.drift is None or self.signed_delta is None:
            raise AssertionError("Evaluable result requires drift values.")

        return {
            "contract_version": OUTPUT_CONTRACT_VERSION,
            "evaluation_id": self.evaluation_id,
            "evaluable": True,
            "source_run_id": self.m1.source_run_id,
            "target_id": self.m1.target_id,
            "system_version": self.m1.system_version,
            "observation_window_id": self.m1.observation_window_id,
            "m1": self.m1.output_dict(),
            "m2": self.m2.output_dict(),
            "drift": self.drift,
            "signed_delta": self.signed_delta,
        }


def evaluate_passive_drift(
    payload: Mapping[str, Any],
) -> PassiveDriftEvaluationResult:
    """Validate a v0.2 input and return its passive evaluation result."""

    evaluation_id = _validate_envelope(payload)
    reasons: list[NonEvaluableReason] = []
    _validate_no_unexpected_keys(payload, _INPUT_KEYS, "input", reasons)

    m1 = _parse_m1(payload.get("m1"), reasons)
    m2 = _parse_m2(payload.get("m2"), reasons)

    if m1 is not None and m2 is not None:
        _validate_comparability(m1, m2, reasons)

    if reasons:
        return PassiveDriftEvaluationResult(
            evaluation_id=evaluation_id,
            evaluable=False,
            reasons=tuple(reasons),
        )

    if m1 is None or m2 is None:
        raise AssertionError("Validated evaluation requires M1 and M2.")

    signed_delta = m1.value - m2.value
    return PassiveDriftEvaluationResult(
        evaluation_id=evaluation_id,
        evaluable=True,
        m1=m1,
        m2=m2,
        drift=abs(signed_delta),
        signed_delta=signed_delta,
    )


def _validate_envelope(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise PassiveDriftContractInputError(
            "Passive drift input must be a mapping."
        )

    contract_version = payload.get("contract_version")
    if contract_version != INPUT_CONTRACT_VERSION:
        raise PassiveDriftContractInputError(
            "contract_version must equal "
            f"{INPUT_CONTRACT_VERSION!r}."
        )

    evaluation_id = payload.get("evaluation_id")
    if not isinstance(evaluation_id, str) or not evaluation_id.strip():
        raise PassiveDriftContractInputError(
            "evaluation_id must be a non-empty string."
        )
    return evaluation_id


def _parse_m1(
    value: Any,
    reasons: list[NonEvaluableReason],
) -> M1Observation | None:
    if not isinstance(value, Mapping):
        reasons.append(
            NonEvaluableReason("m1", "must be a mapping")
        )
        return None

    before = len(reasons)
    _validate_no_unexpected_keys(value, _M1_KEYS, "m1", reasons)
    score = _number(value.get("value"), "m1.value", reasons)
    source_run_id = _text(
        value.get("source_run_id"), "m1.source_run_id", reasons
    )
    target_id = _text(value.get("target_id"), "m1.target_id", reasons)
    system_version = _text(
        value.get("system_version"), "m1.system_version", reasons
    )
    observation_window_id = _text(
        value.get("observation_window_id"),
        "m1.observation_window_id",
        reasons,
    )
    evidence_ref = _text(
        value.get("evidence_ref"), "m1.evidence_ref", reasons
    )
    qualification = _text(
        value.get("qualification"), "m1.qualification", reasons
    )
    if (
        qualification is not None
        and qualification not in _QUALIFICATIONS
    ):
        reasons.append(
            NonEvaluableReason(
                "m1.qualification",
                "must be independent or cross_verified",
            )
        )

    if len(reasons) != before:
        return None
    if (
        score is None
        or source_run_id is None
        or target_id is None
        or system_version is None
        or observation_window_id is None
        or evidence_ref is None
        or qualification is None
    ):
        raise AssertionError("Validated M1 fields must be present.")

    return M1Observation(
        value=score,
        source_run_id=source_run_id,
        target_id=target_id,
        system_version=system_version,
        observation_window_id=observation_window_id,
        evidence_ref=evidence_ref,
        qualification=qualification,
    )


def _parse_m2(
    value: Any,
    reasons: list[NonEvaluableReason],
) -> M2Observation | None:
    if not isinstance(value, Mapping):
        reasons.append(
            NonEvaluableReason("m2", "must be a mapping")
        )
        return None

    before = len(reasons)
    _validate_no_unexpected_keys(value, _M2_KEYS, "m2", reasons)
    score = _number(value.get("value"), "m2.value", reasons)
    source_run_id = _text(
        value.get("source_run_id"), "m2.source_run_id", reasons
    )
    target_id = _text(value.get("target_id"), "m2.target_id", reasons)
    system_version = _text(
        value.get("system_version"), "m2.system_version", reasons
    )
    observation_window_id = _text(
        value.get("observation_window_id"),
        "m2.observation_window_id",
        reasons,
    )
    evaluator_id = _text(
        value.get("evaluator_id"), "m2.evaluator_id", reasons
    )
    evaluator_version = _text(
        value.get("evaluator_version"),
        "m2.evaluator_version",
        reasons,
    )

    if len(reasons) != before:
        return None
    if (
        score is None
        or source_run_id is None
        or target_id is None
        or system_version is None
        or observation_window_id is None
        or evaluator_id is None
        or evaluator_version is None
    ):
        raise AssertionError("Validated M2 fields must be present.")

    return M2Observation(
        value=score,
        source_run_id=source_run_id,
        target_id=target_id,
        system_version=system_version,
        observation_window_id=observation_window_id,
        evaluator_id=evaluator_id,
        evaluator_version=evaluator_version,
    )


def _validate_no_unexpected_keys(
    payload: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
    reasons: list[NonEvaluableReason],
) -> None:
    keys = set(payload.keys())
    for key in sorted(keys - expected):
        reasons.append(
            NonEvaluableReason(f"{label}.{key}", "field is unexpected")
        )


def _number(
    value: Any,
    field: str,
    reasons: list[NonEvaluableReason],
) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        reasons.append(NonEvaluableReason(field, "must be a finite number"))
        return None
    # An int is always finite; isfinite would convert an out-of-range int to
    # float and raise OverflowError before the range check below.
    if isinstance(value, float) and not math.isfinite(value):
        reasons.append(NonEvaluableReason(field, "must be a finite number"))
        return None
    if value < 0 or value > 1:
        reasons.append(NonEvaluableReason(field, "must be in [0,1]"))
        return None
    return value


def _text(
    value: Any,
    field: str,
    reasons: list[NonEvaluableReason],
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        reasons.append(
            NonEvaluableReason(field, "must be a non-empty string")
        )
        return None
    return value


def _validate_comparability(
    m1: M1Observation,
    m2: M2Observation,
    reasons: list[NonEvaluableReason],
) -> None:
    for field in _COMPARABILITY_FIELDS:
        if getattr(m1, field) != getattr(m2, field):
            reasons.append(
                NonEvaluableReason(
                    field,
                    "M1 and M2 values must match exactly",
                )
            )
