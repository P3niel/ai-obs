"""Canonical output mapping for the P3N-105 contract resolution (P3N-106).

Implements, read-only, over existing Kernel payloads and
``OperationalMetrics``:

- ``docs/kernel/contracts/run-status-contract-v0.3.md`` (status vocabulary)
- ``docs/kernel/contracts/kernelrun-serialization-contract-v0.1.md``
  (canonical run/step shape)
- ``docs/kernel/contracts/api-compatibility-mapping-contract-v0.1.md``
  (identifier field mapping)
- ``docs/kernel/contracts/latency-compatibility-mapping-contract-v0.1.md``
  (latency metric mapping)

This module only renames/reshapes existing output. It does not compute new
metrics, does not mutate Kernel state, does not perform I/O, and does not
introduce any new Kernel runtime status.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Mapping
from typing import Sequence

from app.kernel import KernelRun
from app.operational_observability import OperationalMetrics
from app.payload_coercion import optional_text as _optional_text


class CanonicalMappingError(ValueError):
    """Raised when a payload cannot be mapped to a canonical shape."""


_CANONICAL_STATUS_BY_RUNTIME: dict[str, str] = {
    "RUNNING": "running",
    "COMPLETED": "completed",
    "FAILED": "failed",
    "ERROR": "failed",
    "CANCELLED": "cancelled",
    "STUCK": "stuck",
}


def to_canonical_status(runtime_status: str) -> str:
    """Map a Kernel runtime status to the v0.3 canonical vocabulary.

    Only ``RUNNING`` and ``COMPLETED`` are reachable from the current
    Kernel (see ``backend/app/kernel.py`` ``RunStatus``); the remaining
    entries exist so this mapping is ready for a future runtime extension
    without requiring consumers to change. Any value with no defined
    mapping resolves to ``"unknown"`` rather than being guessed as success
    or failure.
    """

    return _CANONICAL_STATUS_BY_RUNTIME.get(
        str(runtime_status).strip().upper(),
        "unknown",
    )


@dataclass(frozen=True)
class CanonicalStep:
    step_id: str
    step_start_timestamp: str | None
    step_end_timestamp: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_start_timestamp": self.step_start_timestamp,
            "step_end_timestamp": self.step_end_timestamp,
        }


@dataclass(frozen=True)
class CanonicalRun:
    run_id: str
    status: str
    run_start_timestamp: str | None
    run_end_timestamp: str | None
    steps: tuple[CanonicalStep, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "run_start_timestamp": self.run_start_timestamp,
            "run_end_timestamp": self.run_end_timestamp,
            "steps": [step.to_dict() for step in self.steps],
        }


KernelRunInput = KernelRun | Mapping[str, Any]


def to_canonical_run(run: KernelRunInput) -> CanonicalRun:
    """Map a Kernel payload to the canonical run shape.

    Implementation note: ``KernelRun.to_dict()``/``KernelStep.to_dict()``
    key the run and step identifiers as ``id`` (not ``runId``/``stepId`` as
    illustrated in ``api-compatibility-mapping-contract-v0.1.md``'s generic
    example). This function treats ``id`` as that same identifier concept
    and maps it to ``run_id``/``step_id`` accordingly.
    """

    payload = run.to_dict() if isinstance(run, KernelRun) else dict(run)
    run_id = _required_text(payload, "id")
    status = _required_text(payload, "status")
    steps_payload = payload.get("steps", ())
    if not isinstance(steps_payload, Sequence) or isinstance(
        steps_payload,
        (str, bytes),
    ):
        raise CanonicalMappingError("Kernel payload steps must be a list.")

    steps = tuple(
        CanonicalStep(
            step_id=_required_text(step, "id"),
            step_start_timestamp=_optional_text(
                step.get("step_start_timestamp")
            ),
            step_end_timestamp=_optional_text(
                step.get("step_end_timestamp")
            ),
        )
        for step in steps_payload
        if isinstance(step, Mapping)
    )

    return CanonicalRun(
        run_id=run_id,
        status=to_canonical_status(status),
        run_start_timestamp=_optional_text(
            payload.get("run_start_timestamp")
        ),
        run_end_timestamp=_optional_text(payload.get("run_end_timestamp")),
        steps=steps,
    )


def to_canonical_latency_metrics(
    metrics: OperationalMetrics,
) -> dict[str, float | None]:
    """Map ``OperationalMetrics`` latency fields to the canonical metric
    names defined by
    ``docs/kernel/contracts/latency-compatibility-mapping-contract-v0.1.md``.

    Maps only the two metrics that contract defines. It does not compute new
    metrics and does not redefine ``run.duration.ms``/``step.duration.ms``,
    which remain owned by ``docs/kernel/metric-dictionary.md``.
    """

    return {
        "step.mean.duration.ms": metrics.average_latency_ms,
        "step.max.duration.ms": metrics.max_latency_ms,
    }


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = _optional_text(payload.get(key))
    if value is None:
        raise CanonicalMappingError(f"Payload field {key!r} is required.")
    return value
