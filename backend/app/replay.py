"""Replay helpers for persisted Kernel run payloads.

The replay layer reads Kernel run artifacts and builds an immutable cursor
over their recorded steps. It does not mutate Kernel state, create new
runtime facts, or redefine the Kernel payload contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from enum import Enum
from typing import Any
from typing import Mapping
from typing import Sequence

from app.kernel import KernelRun
from app.payload_coercion import copy_mapping as _copy_mapping
from app.payload_coercion import sequence_of_mappings as _sequence_of_mappings


class ReplayError(ValueError):
    """Raised when a Kernel run cannot be replayed safely."""


class ReplayPhase(str, Enum):
    RUN_STARTED = "RUN_STARTED"
    STEP = "STEP"
    EVALUATION = "EVALUATION"
    RUN_COMPLETED = "RUN_COMPLETED"


@dataclass(frozen=True)
class ReplayFrame:
    run_id: str
    position: int
    total_frames: int
    phase: ReplayPhase
    status: str
    step_id: str | None = None
    step_name: str | None = None
    expected_state: Mapping[str, Any] | None = None
    events: tuple[str, ...] = ()
    observations: tuple[Mapping[str, Any], ...] = ()
    evaluation: Mapping[str, Any] | None = None

    @property
    def is_terminal(self) -> bool:
        return self.position == self.total_frames - 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "position": self.position,
            "totalFrames": self.total_frames,
            "phase": self.phase.value,
            "status": self.status,
            "stepId": self.step_id,
            "stepName": self.step_name,
            "expectedState": _copy_mapping(self.expected_state or {}),
            "events": list(self.events),
            "observations": [
                _copy_mapping(observation)
                for observation in self.observations
            ],
            "evaluation": (
                _copy_mapping(self.evaluation)
                if self.evaluation is not None
                else None
            ),
            "isTerminal": self.is_terminal,
        }


@dataclass(frozen=True)
class ReplaySession:
    run_id: str
    frames: tuple[ReplayFrame, ...]
    current_position: int = 0

    @property
    def total_frames(self) -> int:
        return len(self.frames)

    @property
    def current(self) -> ReplayFrame:
        try:
            return self.frames[self.current_position]
        except IndexError as exc:
            raise ReplayError(
                f"Replay position {self.current_position} is invalid."
            ) from exc

    @property
    def can_advance(self) -> bool:
        return self.current_position < self.total_frames - 1

    @property
    def can_retreat(self) -> bool:
        return self.current_position > 0

    def advance(self) -> "ReplaySession":
        if not self.can_advance:
            raise ReplayError("Replay is already at the terminal frame.")
        return replace(self, current_position=self.current_position + 1)

    def retreat(self) -> "ReplaySession":
        if not self.can_retreat:
            raise ReplayError("Replay is already at the first frame.")
        return replace(self, current_position=self.current_position - 1)

    def seek(self, position: int) -> "ReplaySession":
        if position < 0 or position >= self.total_frames:
            raise ReplayError(
                f"Replay position {position} is outside the timeline."
            )
        return replace(self, current_position=position)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "currentPosition": self.current_position,
            "totalFrames": self.total_frames,
            "canAdvance": self.can_advance,
            "canRetreat": self.can_retreat,
            "current": self.current.to_dict(),
            "frames": [frame.to_dict() for frame in self.frames],
        }


KernelReplayInput = KernelRun | Mapping[str, Any]


def build_replay_session(run: KernelReplayInput) -> ReplaySession:
    payload = run.to_dict() if isinstance(run, KernelRun) else dict(run)
    run_id = _required_text(payload, "id")
    status = _required_text(payload, "status").upper()
    steps = _sequence_of_mappings(payload.get("steps", ()))
    if not steps:
        raise ReplayError("Run payload must include at least one step.")

    normalized_steps = tuple(_normalize_step(step) for step in steps)
    step_ids = tuple(str(step["id"]) for step in normalized_steps)
    if len(set(step_ids)) != len(step_ids):
        raise ReplayError("Run payload contains duplicate step ids.")

    observations_by_step = _observations_by_step(
        payload.get("observations", ()),
        step_ids,
    )
    evaluation = _optional_mapping(payload.get("evaluation"))

    frames: list[ReplayFrame] = [
        ReplayFrame(
            run_id=run_id,
            position=0,
            total_frames=0,
            phase=ReplayPhase.RUN_STARTED,
            status=status,
        )
    ]
    for step in normalized_steps:
        step_id = str(step["id"])
        frames.append(
            ReplayFrame(
                run_id=run_id,
                position=len(frames),
                total_frames=0,
                phase=ReplayPhase.STEP,
                status=status,
                step_id=step_id,
                step_name=str(step["name"]),
                expected_state=_mapping_or_empty(step.get("expectedState")),
                events=_events(step.get("events", ())),
                observations=observations_by_step[step_id],
            )
        )

    if evaluation is not None:
        frames.append(
            ReplayFrame(
                run_id=run_id,
                position=len(frames),
                total_frames=0,
                phase=ReplayPhase.EVALUATION,
                status=status,
                evaluation=evaluation,
            )
        )

    if status == "COMPLETED":
        frames.append(
            ReplayFrame(
                run_id=run_id,
                position=len(frames),
                total_frames=0,
                phase=ReplayPhase.RUN_COMPLETED,
                status=status,
            )
        )

    total_frames = len(frames)
    return ReplaySession(
        run_id=run_id,
        frames=tuple(
            replace(frame, total_frames=total_frames)
            for frame in frames
        ),
    )


def _normalize_step(step: Mapping[str, Any]) -> Mapping[str, Any]:
    step_id = _required_text(step, "id")
    return {
        "id": step_id,
        "name": _required_text(step, "name"),
        "expectedState": _mapping_or_empty(step.get("expectedState")),
        "events": _events(step.get("events", ())),
    }


def _observations_by_step(
    value: Any,
    step_ids: tuple[str, ...],
) -> dict[str, tuple[Mapping[str, Any], ...]]:
    known_steps = set(step_ids)
    grouped: dict[str, list[Mapping[str, Any]]] = {
        step_id: []
        for step_id in step_ids
    }

    for observation in _sequence_of_mappings(value):
        step_id = _required_text(observation, "stepId")
        if step_id not in known_steps:
            raise ReplayError(
                f"Observation references unknown step {step_id!r}."
            )
        grouped[step_id].append(_copy_mapping(observation))

    return {
        step_id: tuple(observations)
        for step_id, observations in grouped.items()
    }


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None:
        raise ReplayError(f"Run payload field {key!r} is required.")
    normalized = str(value).strip()
    if not normalized:
        raise ReplayError(f"Run payload field {key!r} must not be empty.")
    return normalized


def _optional_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return _copy_mapping(value)
    return None


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    mapping = _optional_mapping(value)
    if mapping is not None:
        return mapping
    return {}


def _events(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        event.strip()
        for event in (str(item) for item in value)
        if event.strip()
    )
