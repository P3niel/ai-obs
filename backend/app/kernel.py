"""Minimal runtime Kernel for run truth capture.

The Kernel records what a run expected, what it observed, and the
deterministic delta between those two states. It is intentionally
in-process and runtime-only.

Run and step timestamps are ISO-8601 UTC with millisecond precision,
exposed verbatim as ``run_start_timestamp``, ``run_end_timestamp``,
``step_start_timestamp``, and ``step_end_timestamp``. See docs/event-schema.md
for the full payload shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from enum import Enum
from typing import Any
from typing import Callable
from typing import Iterable
from typing import Mapping
from typing import Sequence

StateSnapshot = tuple[tuple[str, str], ...]

Clock = Callable[[], datetime]


class KernelError(ValueError):
    """Raised when Kernel runtime input or state transition is invalid."""


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


class EvaluationResult(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"


@dataclass(frozen=True)
class StateMismatch:
    key: str
    expected: str
    observed: str

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "expected": self.expected,
            "observed": self.observed,
        }


@dataclass(frozen=True)
class KernelStep:
    step_id: str
    name: str
    step_start_timestamp: str
    expected_state: StateSnapshot = ()
    events: tuple[str, ...] = ()
    step_end_timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.step_id,
            "name": self.name,
            "expectedState": _state_to_dict(self.expected_state),
            "events": list(self.events),
            "step_start_timestamp": self.step_start_timestamp,
            "step_end_timestamp": self.step_end_timestamp,
        }


@dataclass(frozen=True)
class KernelObservation:
    observation_id: str
    run_id: str
    step_id: str
    fact: str
    observed_state: StateSnapshot

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.observation_id,
            "runId": self.run_id,
            "stepId": self.step_id,
            "fact": self.fact,
            "observedState": _state_to_dict(self.observed_state),
        }


@dataclass(frozen=True)
class KernelEvaluation:
    evaluation_id: str
    run_id: str
    expected_state: StateSnapshot
    observed_state: StateSnapshot
    matches: tuple[str, ...]
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]
    mismatched: tuple[StateMismatch, ...]

    @property
    def result(self) -> EvaluationResult:
        if self.missing or self.unexpected or self.mismatched:
            return EvaluationResult.MISMATCH
        return EvaluationResult.MATCH

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.evaluation_id,
            "runId": self.run_id,
            "result": self.result.value,
            "expectedState": _state_to_dict(self.expected_state),
            "observedState": _state_to_dict(self.observed_state),
            "matches": list(self.matches),
            "missing": list(self.missing),
            "unexpected": list(self.unexpected),
            "mismatched": [
                mismatch.to_dict() for mismatch in self.mismatched
            ],
        }


@dataclass(frozen=True)
class KernelRun:
    run_id: str
    run_start_timestamp: str
    status: RunStatus = RunStatus.RUNNING
    steps: tuple[KernelStep, ...] = ()
    observations: tuple[KernelObservation, ...] = ()
    evaluation: KernelEvaluation | None = None
    run_end_timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.run_id,
            "status": self.status.value,
            "stepCount": len(self.steps),
            "observationCount": len(self.observations),
            "steps": [step.to_dict() for step in self.steps],
            "observations": [
                observation.to_dict()
                for observation in self.observations
            ],
            "evaluation": (
                self.evaluation.to_dict()
                if self.evaluation is not None
                else None
            ),
            "run_start_timestamp": self.run_start_timestamp,
            "run_end_timestamp": self.run_end_timestamp,
        }


class InMemoryKernelStore:
    """Deterministic in-process persistence for Kernel runs."""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._runs: dict[str, KernelRun] = {}
        self._clock: Clock = clock or (
            lambda: datetime.now(timezone.utc)
        )

    def create_run(self, run_id: str) -> KernelRun:
        normalized_run_id = _normalize_identifier(run_id, "run id")
        if normalized_run_id in self._runs:
            raise KernelError(f"Kernel run {normalized_run_id!r} exists.")

        run = KernelRun(
            run_id=normalized_run_id,
            run_start_timestamp=_format_timestamp(self._clock()),
        )
        self._runs[normalized_run_id] = run
        return run

    def append_step(
        self,
        run_id: str,
        *,
        step_id: str,
        name: str,
        expected_state: Mapping[str, str] | None = None,
        events: Sequence[str] = (),
    ) -> KernelStep:
        run = self._require_running_run(run_id)
        normalized_step_id = _normalize_identifier(step_id, "step id")
        if any(step.step_id == normalized_step_id for step in run.steps):
            raise KernelError(
                f"Kernel step {normalized_step_id!r} already exists."
            )

        step = KernelStep(
            step_id=normalized_step_id,
            name=_normalize_identifier(name, "step name"),
            step_start_timestamp=_format_timestamp(self._clock()),
            expected_state=_normalize_state(expected_state),
            events=_normalize_events(events),
        )
        self._runs[run.run_id] = KernelRun(
            run_id=run.run_id,
            run_start_timestamp=run.run_start_timestamp,
            status=run.status,
            steps=run.steps + (step,),
            observations=run.observations,
            evaluation=run.evaluation,
            run_end_timestamp=run.run_end_timestamp,
        )
        return step

    def record_observation(
        self,
        run_id: str,
        *,
        step_id: str,
        observation_id: str,
        fact: str,
        observed_state: Mapping[str, str],
    ) -> KernelObservation:
        run = self._require_running_run(run_id)
        normalized_step_id = _normalize_identifier(step_id, "step id")
        if not any(step.step_id == normalized_step_id for step in run.steps):
            raise KernelError(
                f"Kernel step {normalized_step_id!r} is not registered."
            )

        normalized_observation_id = _normalize_identifier(
            observation_id,
            "observation id",
        )
        if any(
            observation.observation_id == normalized_observation_id
            for observation in run.observations
        ):
            raise KernelError(
                "Kernel observation "
                f"{normalized_observation_id!r} already exists."
            )

        observation = KernelObservation(
            observation_id=normalized_observation_id,
            run_id=run.run_id,
            step_id=normalized_step_id,
            fact=_normalize_identifier(fact, "observation fact"),
            observed_state=_normalize_state(observed_state),
        )
        updated_steps = _mark_step_observed(
            run.steps,
            step_id=normalized_step_id,
            step_end_timestamp=_format_timestamp(self._clock()),
        )
        self._runs[run.run_id] = KernelRun(
            run_id=run.run_id,
            run_start_timestamp=run.run_start_timestamp,
            status=run.status,
            steps=updated_steps,
            observations=run.observations + (observation,),
            evaluation=run.evaluation,
            run_end_timestamp=run.run_end_timestamp,
        )
        return observation

    def complete_run(
        self,
        run_id: str,
        *,
        evaluation_id: str = "evaluation",
    ) -> KernelEvaluation:
        run = self._require_running_run(run_id)
        if not run.observations:
            raise KernelError(
                "Kernel run must include at least one observation before "
                "completion."
            )

        expected_state = _merge_state_snapshots(
            step.expected_state for step in run.steps
        )
        observed_state = _merge_state_snapshots(
            observation.observed_state for observation in run.observations
        )
        evaluation = _evaluate_state(
            evaluation_id=_normalize_identifier(
                evaluation_id,
                "evaluation id",
            ),
            run_id=run.run_id,
            expected_state=expected_state,
            observed_state=observed_state,
        )
        self._runs[run.run_id] = KernelRun(
            run_id=run.run_id,
            run_start_timestamp=run.run_start_timestamp,
            status=RunStatus.COMPLETED,
            steps=run.steps,
            observations=run.observations,
            evaluation=evaluation,
            run_end_timestamp=_format_timestamp(self._clock()),
        )
        return evaluation

    def get_run(self, run_id: str) -> KernelRun:
        normalized_run_id = _normalize_identifier(run_id, "run id")
        try:
            return self._runs[normalized_run_id]
        except KeyError as exc:
            raise KernelError(
                f"Kernel run {normalized_run_id!r} was not found."
            ) from exc

    def list_runs(self) -> tuple[KernelRun, ...]:
        return tuple(
            self._runs[run_id]
            for run_id in sorted(self._runs)
        )

    def list_steps(self, run_id: str) -> tuple[KernelStep, ...]:
        return self.get_run(run_id).steps

    def list_observations(
        self,
        run_id: str,
    ) -> tuple[KernelObservation, ...]:
        return self.get_run(run_id).observations

    def get_evaluation(self, run_id: str) -> KernelEvaluation:
        evaluation = self.get_run(run_id).evaluation
        if evaluation is None:
            raise KernelError("Kernel run does not have an evaluation yet.")
        return evaluation

    def _require_running_run(self, run_id: str) -> KernelRun:
        run = self.get_run(run_id)
        if run.status != RunStatus.RUNNING:
            raise KernelError(
                f"Kernel run {run.run_id!r} is already completed."
            )
        return run


def _evaluate_state(
    *,
    evaluation_id: str,
    run_id: str,
    expected_state: StateSnapshot,
    observed_state: StateSnapshot,
) -> KernelEvaluation:
    expected = _state_to_dict(expected_state)
    observed = _state_to_dict(observed_state)

    matches = tuple(
        sorted(
            key
            for key, expected_value in expected.items()
            if observed.get(key) == expected_value
        )
    )
    missing = tuple(
        sorted(key for key in expected if key not in observed)
    )
    unexpected = tuple(
        sorted(key for key in observed if key not in expected)
    )
    mismatched = tuple(
        StateMismatch(
            key=key,
            expected=expected[key],
            observed=observed[key],
        )
        for key in sorted(expected)
        if key in observed and observed[key] != expected[key]
    )
    return KernelEvaluation(
        evaluation_id=evaluation_id,
        run_id=run_id,
        expected_state=expected_state,
        observed_state=observed_state,
        matches=matches,
        missing=missing,
        unexpected=unexpected,
        mismatched=mismatched,
    )


def _normalize_identifier(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise KernelError(f"Kernel {label} must not be empty.")
    return normalized


def _normalize_state(
    state: Mapping[str, str] | None,
) -> StateSnapshot:
    if not state:
        return ()

    normalized: dict[str, str] = {}
    for raw_key, raw_value in state.items():
        key = _normalize_identifier(str(raw_key), "state key")
        value = str(raw_value).strip()
        if key in normalized:
            raise KernelError(
                f"Kernel state key {key!r} appears more than once."
            )
        normalized[key] = value
    return tuple(sorted(normalized.items()))


def _normalize_events(events: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        event.strip()
        for event in events
        if event.strip()
    )


def _merge_state_snapshots(
    snapshots: Iterable[StateSnapshot],
) -> StateSnapshot:
    merged: dict[str, str] = {}
    for snapshot in snapshots:
        for key, value in snapshot:
            merged[key] = value
    return tuple(sorted(merged.items()))


def _state_to_dict(snapshot: StateSnapshot) -> dict[str, str]:
    return {key: value for key, value in snapshot}


def _format_timestamp(moment: datetime) -> str:
    """Format a timestamp per run-temporal-contract-v0.2: ISO-8601 UTC,
    millisecond precision, ``Z`` suffix."""

    as_utc = moment.astimezone(timezone.utc)
    return as_utc.strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{as_utc.microsecond // 1000:03d}Z"
    )


def _mark_step_observed(
    steps: tuple[KernelStep, ...],
    *,
    step_id: str,
    step_end_timestamp: str,
) -> tuple[KernelStep, ...]:
    """Set step_end_timestamp on first observation for a step; later
    observations for the same step do not move it, consistent with
    immutable Event semantics."""

    updated: list[KernelStep] = []
    for step in steps:
        if step.step_id == step_id and step.step_end_timestamp is None:
            updated.append(
                KernelStep(
                    step_id=step.step_id,
                    name=step.name,
                    step_start_timestamp=step.step_start_timestamp,
                    expected_state=step.expected_state,
                    events=step.events,
                    step_end_timestamp=step_end_timestamp,
                )
            )
        else:
            updated.append(step)
    return tuple(updated)
