"""Run comparison helpers for Kernel-derived run payloads.

The comparison layer reads Kernel run artifacts and reports deterministic
differences between two executions. It does not mutate Kernel state, alter
replay behavior, influence CTX, or redefine the Kernel payload contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from typing import Mapping
from typing import Sequence

from app.kernel import KernelRun
from app.payload_coercion import as_mapping as _mapping
from app.payload_coercion import copy_mapping as _copy_mapping
from app.payload_coercion import optional_number as _optional_number
from app.payload_coercion import optional_text as _optional_text
from app.payload_coercion import sequence_of_mappings as _sequence_of_mappings


class RunComparisonError(ValueError):
    """Raised when a run payload cannot be compared safely."""


class DifferenceSeverity(str, Enum):
    NOISE = "NOISE"
    MATERIAL = "MATERIAL"


class DifferenceKind(str, Enum):
    LATENCY_DELTA = "LATENCY_DELTA"
    DURATION_DELTA = "DURATION_DELTA"
    STEP_ADDED = "STEP_ADDED"
    STEP_REMOVED = "STEP_REMOVED"
    STEP_ORDER = "STEP_ORDER"
    STEP_NAME = "STEP_NAME"
    STEP_DURATION_DELTA = "STEP_DURATION_DELTA"
    OBSERVATION_ADDED = "OBSERVATION_ADDED"
    OBSERVATION_REMOVED = "OBSERVATION_REMOVED"
    OBSERVATION_FACT = "OBSERVATION_FACT"
    OBSERVED_STATE = "OBSERVED_STATE"
    EVALUATION_RESULT = "EVALUATION_RESULT"
    EVALUATION_FIELD = "EVALUATION_FIELD"


@dataclass(frozen=True)
class ComparisonThresholds:
    latency_noise_threshold_ms: float = 50.0
    duration_noise_threshold_ms: float = 100.0
    step_duration_noise_threshold_ms: float = 50.0


@dataclass(frozen=True)
class MetricDelta:
    baseline: float
    candidate: float
    delta: float

    def to_dict(self) -> dict[str, float]:
        return {
            "baseline": self.baseline,
            "candidate": self.candidate,
            "delta": self.delta,
        }


@dataclass(frozen=True)
class RunDifference:
    kind: DifferenceKind
    severity: DifferenceSeverity
    message: str
    details: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "severity": self.severity.value,
            "message": self.message,
            "details": _copy_mapping(self.details),
        }


@dataclass(frozen=True)
class RunComparison:
    baseline_run_id: str
    candidate_run_id: str
    latency_delta: MetricDelta | None
    duration_delta: MetricDelta | None
    differences: tuple[RunDifference, ...]

    @property
    def material_difference_count(self) -> int:
        return sum(
            1
            for difference in self.differences
            if difference.severity == DifferenceSeverity.MATERIAL
        )

    @property
    def noise_difference_count(self) -> int:
        return sum(
            1
            for difference in self.differences
            if difference.severity == DifferenceSeverity.NOISE
        )

    @property
    def has_material_differences(self) -> bool:
        return self.material_difference_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "baselineRunId": self.baseline_run_id,
            "candidateRunId": self.candidate_run_id,
            "hasMaterialDifferences": self.has_material_differences,
            "materialDifferenceCount": self.material_difference_count,
            "noiseDifferenceCount": self.noise_difference_count,
            "latencyDelta": (
                self.latency_delta.to_dict()
                if self.latency_delta is not None
                else None
            ),
            "durationDelta": (
                self.duration_delta.to_dict()
                if self.duration_delta is not None
                else None
            ),
            "differences": [
                difference.to_dict()
                for difference in self.differences
            ],
        }


KernelComparisonInput = KernelRun | Mapping[str, Any]


@dataclass(frozen=True)
class _StepSnapshot:
    step_id: str
    name: str


@dataclass(frozen=True)
class _ObservationSnapshot:
    observation_id: str
    step_id: str
    fact: str
    observed_state: Mapping[str, Any]


@dataclass(frozen=True)
class _RunSnapshot:
    run_id: str
    status: str
    steps: tuple[_StepSnapshot, ...]
    observations: tuple[_ObservationSnapshot, ...]
    evaluation: Mapping[str, Any] | None
    duration_ms: float | None
    max_latency_ms: float | None
    step_durations_ms: Mapping[str, float]

    @property
    def step_ids(self) -> tuple[str, ...]:
        return tuple(step.step_id for step in self.steps)


def compare_kernel_runs(
    baseline: KernelComparisonInput,
    candidate: KernelComparisonInput,
    thresholds: ComparisonThresholds | None = None,
) -> RunComparison:
    active_thresholds = thresholds or ComparisonThresholds()
    baseline_snapshot = _normalize_run(baseline)
    candidate_snapshot = _normalize_run(candidate)

    latency_delta = _metric_delta(
        baseline_snapshot.max_latency_ms,
        candidate_snapshot.max_latency_ms,
    )
    duration_delta = _metric_delta(
        baseline_snapshot.duration_ms,
        candidate_snapshot.duration_ms,
    )
    differences: list[RunDifference] = []
    differences.extend(
        _metric_differences(
            latency_delta=latency_delta,
            duration_delta=duration_delta,
            thresholds=active_thresholds,
        )
    )
    differences.extend(
        _step_differences(
            baseline_snapshot,
            candidate_snapshot,
            active_thresholds,
        )
    )
    differences.extend(
        _observation_differences(baseline_snapshot, candidate_snapshot)
    )
    differences.extend(
        _evaluation_differences(baseline_snapshot, candidate_snapshot)
    )

    return RunComparison(
        baseline_run_id=baseline_snapshot.run_id,
        candidate_run_id=candidate_snapshot.run_id,
        latency_delta=latency_delta,
        duration_delta=duration_delta,
        differences=tuple(differences),
    )


def _metric_differences(
    *,
    latency_delta: MetricDelta | None,
    duration_delta: MetricDelta | None,
    thresholds: ComparisonThresholds,
) -> tuple[RunDifference, ...]:
    differences: list[RunDifference] = []
    if latency_delta is not None and latency_delta.delta != 0:
        severity = _severity(
            latency_delta.delta,
            thresholds.latency_noise_threshold_ms,
        )
        differences.append(
            RunDifference(
                kind=DifferenceKind.LATENCY_DELTA,
                severity=severity,
                message="Run max latency changed.",
                details=latency_delta.to_dict(),
            )
        )
    if duration_delta is not None and duration_delta.delta != 0:
        severity = _severity(
            duration_delta.delta,
            thresholds.duration_noise_threshold_ms,
        )
        differences.append(
            RunDifference(
                kind=DifferenceKind.DURATION_DELTA,
                severity=severity,
                message="Run duration changed.",
                details=duration_delta.to_dict(),
            )
        )
    return tuple(differences)


def _step_differences(
    baseline: _RunSnapshot,
    candidate: _RunSnapshot,
    thresholds: ComparisonThresholds,
) -> tuple[RunDifference, ...]:
    differences: list[RunDifference] = []
    baseline_step_ids = baseline.step_ids
    candidate_step_ids = candidate.step_ids
    baseline_step_set = set(baseline_step_ids)
    candidate_step_set = set(candidate_step_ids)

    for step_id in sorted(baseline_step_set - candidate_step_set):
        differences.append(
            RunDifference(
                kind=DifferenceKind.STEP_REMOVED,
                severity=DifferenceSeverity.MATERIAL,
                message="Step was removed from candidate run.",
                details={"stepId": step_id},
            )
        )

    for step_id in sorted(candidate_step_set - baseline_step_set):
        differences.append(
            RunDifference(
                kind=DifferenceKind.STEP_ADDED,
                severity=DifferenceSeverity.MATERIAL,
                message="Step was added to candidate run.",
                details={"stepId": step_id},
            )
        )

    common_steps = tuple(
        step_id
        for step_id in baseline_step_ids
        if step_id in candidate_step_set
    )
    candidate_common_steps = tuple(
        step_id
        for step_id in candidate_step_ids
        if step_id in baseline_step_set
    )
    if common_steps != candidate_common_steps:
        differences.append(
            RunDifference(
                kind=DifferenceKind.STEP_ORDER,
                severity=DifferenceSeverity.MATERIAL,
                message="Common step order changed.",
                details={
                    "baselineOrder": list(common_steps),
                    "candidateOrder": list(candidate_common_steps),
                },
            )
        )

    baseline_steps = {step.step_id: step for step in baseline.steps}
    candidate_steps = {step.step_id: step for step in candidate.steps}
    for step_id in sorted(baseline_step_set & candidate_step_set):
        baseline_step = baseline_steps[step_id]
        candidate_step = candidate_steps[step_id]
        if baseline_step.name != candidate_step.name:
            differences.append(
                RunDifference(
                    kind=DifferenceKind.STEP_NAME,
                    severity=DifferenceSeverity.MATERIAL,
                    message="Step name changed.",
                    details={
                        "stepId": step_id,
                        "baseline": baseline_step.name,
                        "candidate": candidate_step.name,
                    },
                )
            )

    for step_id in sorted(
        set(baseline.step_durations_ms) & set(candidate.step_durations_ms)
    ):
        delta = _metric_delta(
            baseline.step_durations_ms[step_id],
            candidate.step_durations_ms[step_id],
        )
        if delta is None or delta.delta == 0:
            continue
        differences.append(
            RunDifference(
                kind=DifferenceKind.STEP_DURATION_DELTA,
                severity=_severity(
                    delta.delta,
                    thresholds.step_duration_noise_threshold_ms,
                ),
                message="Step duration changed.",
                details={"stepId": step_id, **delta.to_dict()},
            )
        )

    return tuple(differences)


def _observation_differences(
    baseline: _RunSnapshot,
    candidate: _RunSnapshot,
) -> tuple[RunDifference, ...]:
    differences: list[RunDifference] = []
    baseline_observations = _observations_by_key(baseline.observations)
    candidate_observations = _observations_by_key(candidate.observations)
    baseline_keys = set(baseline_observations)
    candidate_keys = set(candidate_observations)

    for key in sorted(baseline_keys - candidate_keys):
        differences.append(
            RunDifference(
                kind=DifferenceKind.OBSERVATION_REMOVED,
                severity=DifferenceSeverity.MATERIAL,
                message="Observation was removed from candidate run.",
                details=_observation_key_details(key),
            )
        )

    for key in sorted(candidate_keys - baseline_keys):
        differences.append(
            RunDifference(
                kind=DifferenceKind.OBSERVATION_ADDED,
                severity=DifferenceSeverity.MATERIAL,
                message="Observation was added to candidate run.",
                details=_observation_key_details(key),
            )
        )

    for key in sorted(baseline_keys & candidate_keys):
        baseline_observation = baseline_observations[key]
        candidate_observation = candidate_observations[key]
        if baseline_observation.fact != candidate_observation.fact:
            differences.append(
                RunDifference(
                    kind=DifferenceKind.OBSERVATION_FACT,
                    severity=DifferenceSeverity.MATERIAL,
                    message="Observation fact changed.",
                    details={
                        **_observation_key_details(key),
                        "baseline": baseline_observation.fact,
                        "candidate": candidate_observation.fact,
                    },
                )
            )
        differences.extend(
            _observed_state_differences(
                key,
                baseline_observation.observed_state,
                candidate_observation.observed_state,
            )
        )

    return tuple(differences)


def _observed_state_differences(
    observation_key: tuple[str, str],
    baseline_state: Mapping[str, Any],
    candidate_state: Mapping[str, Any],
) -> tuple[RunDifference, ...]:
    differences: list[RunDifference] = []
    baseline_keys = set(baseline_state)
    candidate_keys = set(candidate_state)

    for state_key in sorted(baseline_keys | candidate_keys):
        baseline_value = baseline_state.get(state_key)
        candidate_value = candidate_state.get(state_key)
        if baseline_value == candidate_value:
            continue
        if _is_latency_key(state_key) and (
            _optional_number(baseline_value) is not None
            or _optional_number(candidate_value) is not None
        ):
            continue
        differences.append(
            RunDifference(
                kind=DifferenceKind.OBSERVED_STATE,
                severity=DifferenceSeverity.MATERIAL,
                message="Observed state changed.",
                details={
                    **_observation_key_details(observation_key),
                    "stateKey": state_key,
                    "baseline": baseline_value,
                    "candidate": candidate_value,
                },
            )
        )
    return tuple(differences)


def _evaluation_differences(
    baseline: _RunSnapshot,
    candidate: _RunSnapshot,
) -> tuple[RunDifference, ...]:
    differences: list[RunDifference] = []
    baseline_evaluation = baseline.evaluation or {}
    candidate_evaluation = candidate.evaluation or {}
    baseline_result = _optional_text(baseline_evaluation.get("result"))
    candidate_result = _optional_text(candidate_evaluation.get("result"))
    if baseline_result != candidate_result:
        differences.append(
            RunDifference(
                kind=DifferenceKind.EVALUATION_RESULT,
                severity=DifferenceSeverity.MATERIAL,
                message="Kernel evaluation result changed.",
                details={
                    "baseline": baseline_result,
                    "candidate": candidate_result,
                },
            )
        )

    for field in ("matches", "missing", "unexpected", "mismatched"):
        baseline_value = _normalized_json_value(
            baseline_evaluation.get(field, [])
        )
        candidate_value = _normalized_json_value(
            candidate_evaluation.get(field, [])
        )
        if baseline_value == candidate_value:
            continue
        differences.append(
            RunDifference(
                kind=DifferenceKind.EVALUATION_FIELD,
                severity=DifferenceSeverity.MATERIAL,
                message=f"Kernel evaluation field {field} changed.",
                details={
                    "field": field,
                    "baseline": baseline_value,
                    "candidate": candidate_value,
                },
            )
        )
    return tuple(differences)


def _normalize_run(run: KernelComparisonInput) -> _RunSnapshot:
    payload = run.to_dict() if isinstance(run, KernelRun) else dict(run)
    run_id = _required_text(payload, "id")
    status = _required_text(payload, "status").upper()
    steps = tuple(
        _normalize_step(step)
        for step in _sequence_of_mappings(payload.get("steps", ()))
    )
    if not steps:
        raise RunComparisonError(
            f"Run payload {run_id!r} must include at least one step."
        )
    step_ids = tuple(step.step_id for step in steps)
    if len(set(step_ids)) != len(step_ids):
        raise RunComparisonError(
            f"Run payload {run_id!r} contains duplicate step ids."
        )

    observations = tuple(
        _normalize_observation(observation)
        for observation in _sequence_of_mappings(
            payload.get("observations", ())
        )
    )
    unknown_observations = sorted(
        {
            observation.step_id
            for observation in observations
            if observation.step_id not in set(step_ids)
        }
    )
    if unknown_observations:
        raise RunComparisonError(
            "Run payload "
            f"{run_id!r} has observations for unknown steps: "
            f"{', '.join(unknown_observations)}."
        )

    metadata = _mapping(payload.get("metadata", {}))
    latency_samples = _latency_samples(metadata, observations)
    return _RunSnapshot(
        run_id=run_id,
        status=status,
        steps=steps,
        observations=observations,
        evaluation=_optional_mapping(payload.get("evaluation")),
        duration_ms=_optional_number(
            metadata.get("durationMs", payload.get("durationMs"))
        ),
        max_latency_ms=max(latency_samples) if latency_samples else None,
        step_durations_ms=_step_durations(metadata, payload),
    )


def _normalize_step(step: Mapping[str, Any]) -> _StepSnapshot:
    return _StepSnapshot(
        step_id=_required_text(step, "id"),
        name=_required_text(step, "name"),
    )


def _normalize_observation(
    observation: Mapping[str, Any],
) -> _ObservationSnapshot:
    return _ObservationSnapshot(
        observation_id=_required_text(observation, "id"),
        step_id=_required_text(observation, "stepId"),
        fact=_required_text(observation, "fact"),
        observed_state=_copy_mapping(
            _mapping(observation.get("observedState", {}))
        ),
    )


def _latency_samples(
    metadata: Mapping[str, Any],
    observations: Sequence[_ObservationSnapshot],
) -> tuple[float, ...]:
    samples: list[float] = []
    for key in ("latencyMs", "maxLatencyMs", "averageLatencyMs"):
        value = _optional_number(metadata.get(key))
        if value is not None:
            samples.append(value)

    for observation in observations:
        for key, value in observation.observed_state.items():
            key_token = str(key).replace("_", "").replace(".", "").lower()
            if "latency" not in key_token:
                continue
            sample = _optional_number(value)
            if sample is not None:
                samples.append(sample)
    return tuple(samples)


def _step_durations(
    metadata: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> Mapping[str, float]:
    durations: dict[str, float] = {}
    for key, value in _mapping(metadata.get("stepDurationsMs", {})).items():
        duration = _optional_number(value)
        step_id = str(key).strip()
        if step_id and duration is not None:
            durations[step_id] = duration

    for step in _sequence_of_mappings(payload.get("steps", ())):
        step_identifier = _optional_text(step.get("id"))
        duration = _optional_number(step.get("durationMs"))
        if step_identifier and duration is not None:
            durations[step_identifier] = duration
    return durations


def _metric_delta(
    baseline: float | None,
    candidate: float | None,
) -> MetricDelta | None:
    if baseline is None or candidate is None:
        return None
    return MetricDelta(
        baseline=baseline,
        candidate=candidate,
        delta=candidate - baseline,
    )


def _severity(delta: float, noise_threshold: float) -> DifferenceSeverity:
    if abs(delta) <= noise_threshold:
        return DifferenceSeverity.NOISE
    return DifferenceSeverity.MATERIAL


def _is_latency_key(value: Any) -> bool:
    key_token = str(value).replace("_", "").replace(".", "").lower()
    return "latency" in key_token


def _observations_by_key(
    observations: Sequence[_ObservationSnapshot],
) -> Mapping[tuple[str, str], _ObservationSnapshot]:
    grouped: dict[tuple[str, str], _ObservationSnapshot] = {}
    for observation in observations:
        key = (observation.step_id, observation.observation_id)
        if key in grouped:
            raise RunComparisonError(
                "Run payload contains duplicate observation "
                f"{observation.observation_id!r} for step "
                f"{observation.step_id!r}."
            )
        grouped[key] = observation
    return grouped


def _observation_key_details(
    key: tuple[str, str],
) -> dict[str, str]:
    return {
        "stepId": key[0],
        "observationId": key[1],
    }


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = _optional_text(payload.get(key))
    if value is None:
        raise RunComparisonError(f"Run payload field {key!r} is required.")
    return value


def _optional_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return _copy_mapping(value)
    return None


def _normalized_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalized_json_value(item)
            for key, item in sorted(value.items())
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_normalized_json_value(item) for item in value]
    return value
