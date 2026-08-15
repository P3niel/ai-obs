"""Operational observability helpers for Kernel-derived run artifacts.

The observability layer reads Kernel run payloads and reports metrics,
threshold alerts, and notification dispatch results. It does not mutate
Kernel state, influence CTX, block request flow, or perform network I/O
directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any
from typing import Mapping
from typing import Protocol
from typing import Sequence

from app.kernel import KernelRun
from app.payload_coercion import as_mapping as _mapping
from app.payload_coercion import optional_number as _optional_number
from app.payload_coercion import optional_text as _optional_text
from app.payload_coercion import sequence_of_mappings as _sequence_of_mappings


class ObservabilityError(ValueError):
    """Raised when observability input cannot be interpreted safely."""


class AlertCondition(str, Enum):
    SLOW_RUN = "SLOW_RUN"
    SLOW_STEP = "SLOW_STEP"
    STUCK_RUN = "STUCK_RUN"
    ERRORED_STEP = "ERRORED_STEP"
    EVALUATION_FAILURE = "EVALUATION_FAILURE"


class AlertSeverity(str, Enum):
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class NotificationProvider(str, Enum):
    SLACK = "SLACK"
    DISCORD = "DISCORD"


class NotificationClient(Protocol):
    def send(self, message: "NotificationMessage") -> None:
        """Deliver a provider-specific message."""


@dataclass(frozen=True)
class StepDurationMetric:
    step_id: str
    sample_count: int
    average_duration_ms: float
    max_duration_ms: float

    def to_dict(self) -> dict[str, int | float | str]:
        return {
            "stepId": self.step_id,
            "sampleCount": self.sample_count,
            "averageDurationMs": self.average_duration_ms,
            "maxDurationMs": self.max_duration_ms,
        }


@dataclass(frozen=True)
class EvaluationAggregate:
    match_count: int
    mismatch_count: int

    @property
    def total(self) -> int:
        return self.match_count + self.mismatch_count

    def to_dict(self) -> dict[str, float | int]:
        mismatch_rate = (
            self.mismatch_count / self.total
            if self.total
            else 0.0
        )
        return {
            "matchCount": self.match_count,
            "mismatchCount": self.mismatch_count,
            "totalEvaluated": self.total,
            "mismatchRate": mismatch_rate,
        }


@dataclass(frozen=True)
class OperationalMetrics:
    run_count: int
    completed_count: int
    running_count: int
    observation_count: int
    average_latency_ms: float | None
    max_latency_ms: float | None
    average_duration_ms: float | None
    max_duration_ms: float | None
    step_durations: tuple[StepDurationMetric, ...]
    evaluations: EvaluationAggregate

    def to_dict(self) -> dict[str, Any]:
        return {
            "runCount": self.run_count,
            "completedCount": self.completed_count,
            "runningCount": self.running_count,
            "observationCount": self.observation_count,
            "averageLatencyMs": self.average_latency_ms,
            "maxLatencyMs": self.max_latency_ms,
            "averageDurationMs": self.average_duration_ms,
            "maxDurationMs": self.max_duration_ms,
            "stepDurations": [
                step_duration.to_dict()
                for step_duration in self.step_durations
            ],
            "evaluations": self.evaluations.to_dict(),
        }


@dataclass(frozen=True)
class AlertThresholds:
    max_latency_ms: float = 1000.0
    max_run_duration_ms: float = 30000.0
    max_step_duration_ms: float = 10000.0
    stuck_after_ms: float = 60000.0


@dataclass(frozen=True)
class Alert:
    condition: AlertCondition
    severity: AlertSeverity
    run_id: str
    message: str
    details: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition.value,
            "severity": self.severity.value,
            "runId": self.run_id,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class NotificationMessage:
    provider: NotificationProvider
    title: str
    body: str
    alert: Alert

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider.value,
            "title": self.title,
            "body": self.body,
            "alert": self.alert.to_dict(),
        }


@dataclass(frozen=True)
class NotificationDispatchResult:
    provider: NotificationProvider
    alert_condition: AlertCondition
    run_id: str
    delivered: bool
    error: str | None = None

    def to_dict(self) -> dict[str, bool | str | None]:
        return {
            "provider": self.provider.value,
            "alertCondition": self.alert_condition.value,
            "runId": self.run_id,
            "delivered": self.delivered,
            "error": self.error,
        }


KernelRunInput = KernelRun | Mapping[str, Any]


def summarize_kernel_runs(
    runs: Sequence[KernelRunInput],
) -> OperationalMetrics:
    normalized_runs = tuple(_normalize_run(run) for run in runs)
    durations = [
        run.duration_ms
        for run in normalized_runs
        if run.duration_ms is not None
    ]
    latencies = [
        latency
        for run in normalized_runs
        for latency in run.latency_samples_ms
    ]
    step_duration_samples: dict[str, list[float]] = {}
    for run in normalized_runs:
        for step_id, duration_ms in run.step_durations_ms.items():
            step_duration_samples.setdefault(step_id, []).append(duration_ms)

    return OperationalMetrics(
        run_count=len(normalized_runs),
        completed_count=sum(
            1 for run in normalized_runs if run.status == "COMPLETED"
        ),
        running_count=sum(
            1 for run in normalized_runs if run.status == "RUNNING"
        ),
        observation_count=sum(
            run.observation_count for run in normalized_runs
        ),
        average_latency_ms=_average(latencies),
        max_latency_ms=max(latencies) if latencies else None,
        average_duration_ms=_average(durations),
        max_duration_ms=max(durations) if durations else None,
        step_durations=_build_step_duration_metrics(
            step_duration_samples
        ),
        evaluations=EvaluationAggregate(
            match_count=sum(
                1
                for run in normalized_runs
                if run.evaluation_result == "MATCH"
            ),
            mismatch_count=sum(
                1
                for run in normalized_runs
                if run.evaluation_result == "MISMATCH"
            ),
        ),
    )


def detect_alerts(
    runs: Sequence[KernelRunInput],
    thresholds: AlertThresholds | None = None,
) -> tuple[Alert, ...]:
    active_thresholds = thresholds or AlertThresholds()
    alerts: list[Alert] = []
    for run in (_normalize_run(run) for run in runs):
        alerts.extend(_detect_run_alerts(run, active_thresholds))
    return tuple(
        sorted(
            alerts,
            key=lambda alert: (
                alert.run_id,
                alert.condition.value,
                alert.message,
            ),
        )
    )


def dispatch_alert_notifications(
    alerts: Sequence[Alert],
    clients: Mapping[NotificationProvider, NotificationClient],
) -> tuple[NotificationDispatchResult, ...]:
    results: list[NotificationDispatchResult] = []
    for alert in alerts:
        for provider, client in sorted(
            clients.items(),
            key=lambda item: item[0].value,
        ):
            message = build_notification_message(provider, alert)
            try:
                client.send(message)
            except Exception as exc:  # pragma: no cover - type is external.
                results.append(
                    NotificationDispatchResult(
                        provider=provider,
                        alert_condition=alert.condition,
                        run_id=alert.run_id,
                        delivered=False,
                        error=str(exc),
                    )
                )
            else:
                results.append(
                    NotificationDispatchResult(
                        provider=provider,
                        alert_condition=alert.condition,
                        run_id=alert.run_id,
                        delivered=True,
                    )
                )
    return tuple(results)


def build_notification_message(
    provider: NotificationProvider,
    alert: Alert,
) -> NotificationMessage:
    prefix = "AI-Obs alert"
    title = f"{prefix}: {alert.condition.value}"
    if provider == NotificationProvider.SLACK:
        body = f"[{alert.severity.value}] {alert.run_id}: {alert.message}"
    elif provider == NotificationProvider.DISCORD:
        body = f"{alert.severity.value} - {alert.run_id} - {alert.message}"
    else:
        raise ObservabilityError(
            f"Unsupported notification provider: {provider!r}."
        )
    return NotificationMessage(
        provider=provider,
        title=title,
        body=body,
        alert=alert,
    )


@dataclass(frozen=True)
class _RunSnapshot:
    run_id: str
    status: str
    observation_count: int
    duration_ms: float | None
    updated_age_ms: float | None
    latency_samples_ms: tuple[float, ...]
    step_durations_ms: Mapping[str, float]
    evaluation_result: str | None
    errored_steps: tuple[str, ...]


def _detect_run_alerts(
    run: _RunSnapshot,
    thresholds: AlertThresholds,
) -> tuple[Alert, ...]:
    alerts: list[Alert] = []
    if (
        run.duration_ms is not None
        and run.duration_ms > thresholds.max_run_duration_ms
    ):
        alerts.append(
            Alert(
                condition=AlertCondition.SLOW_RUN,
                severity=AlertSeverity.WARNING,
                run_id=run.run_id,
                message="Run duration exceeded threshold.",
                details={
                    "durationMs": run.duration_ms,
                    "thresholdMs": thresholds.max_run_duration_ms,
                },
            )
        )

    slow_latencies = [
        latency
        for latency in run.latency_samples_ms
        if latency > thresholds.max_latency_ms
    ]
    if slow_latencies:
        alerts.append(
            Alert(
                condition=AlertCondition.SLOW_RUN,
                severity=AlertSeverity.WARNING,
                run_id=run.run_id,
                message="Run latency exceeded threshold.",
                details={
                    "maxLatencyMs": max(slow_latencies),
                    "thresholdMs": thresholds.max_latency_ms,
                },
            )
        )

    for step_id, duration_ms in sorted(run.step_durations_ms.items()):
        if duration_ms > thresholds.max_step_duration_ms:
            alerts.append(
                Alert(
                    condition=AlertCondition.SLOW_STEP,
                    severity=AlertSeverity.WARNING,
                    run_id=run.run_id,
                    message=f"Step {step_id} duration exceeded threshold.",
                    details={
                        "stepId": step_id,
                        "durationMs": duration_ms,
                        "thresholdMs": thresholds.max_step_duration_ms,
                    },
                )
            )

    if (
        run.status == "RUNNING"
        and run.updated_age_ms is not None
        and run.updated_age_ms > thresholds.stuck_after_ms
    ):
        alerts.append(
            Alert(
                condition=AlertCondition.STUCK_RUN,
                severity=AlertSeverity.CRITICAL,
                run_id=run.run_id,
                message="Running run has not reported fresh activity.",
                details={
                    "updatedAgeMs": run.updated_age_ms,
                    "thresholdMs": thresholds.stuck_after_ms,
                },
            )
        )

    for step_id in run.errored_steps:
        alerts.append(
            Alert(
                condition=AlertCondition.ERRORED_STEP,
                severity=AlertSeverity.CRITICAL,
                run_id=run.run_id,
                message=f"Step {step_id} reported an error state.",
                details={"stepId": step_id},
            )
        )

    if run.evaluation_result == "MISMATCH":
        alerts.append(
            Alert(
                condition=AlertCondition.EVALUATION_FAILURE,
                severity=AlertSeverity.CRITICAL,
                run_id=run.run_id,
                message="Kernel evaluation reported a mismatch.",
                details={"evaluationResult": run.evaluation_result},
            )
        )
    return tuple(alerts)


def _normalize_run(run: KernelRunInput) -> _RunSnapshot:
    payload = run.to_dict() if isinstance(run, KernelRun) else dict(run)
    run_id = _required_text(payload, "id")
    status = _required_text(payload, "status").upper()
    observations = _sequence_of_mappings(payload.get("observations", ()))
    metadata = _mapping(payload.get("metadata", {}))
    evaluation = _optional_mapping(payload.get("evaluation"))

    return _RunSnapshot(
        run_id=run_id,
        status=status,
        observation_count=_int_value(
            payload.get("observationCount"),
            default=len(observations),
        ),
        duration_ms=_optional_number(
            metadata.get("durationMs", payload.get("durationMs"))
        ),
        updated_age_ms=_optional_number(
            metadata.get("updatedAgeMs", payload.get("updatedAgeMs"))
        ),
        latency_samples_ms=_latency_samples(metadata, observations),
        step_durations_ms=_step_durations(metadata, payload),
        evaluation_result=_evaluation_result(evaluation),
        errored_steps=_errored_steps(observations),
    )


def _latency_samples(
    metadata: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
) -> tuple[float, ...]:
    samples: list[float] = []
    for key in ("latencyMs", "maxLatencyMs", "averageLatencyMs"):
        value = _optional_number(metadata.get(key))
        if value is not None:
            samples.append(value)

    for observation in observations:
        observed_state = _mapping(observation.get("observedState", {}))
        for key, value in observed_state.items():
            key_token = str(key).replace("_", "").replace(".", "").lower()
            if "latency" in key_token:
                sample = _optional_number(value)
                if sample is not None:
                    samples.append(sample)
    return tuple(samples)


def _evaluation_result(
    evaluation: Mapping[str, Any] | None,
) -> str | None:
    if evaluation is None:
        return None
    result = _optional_text(evaluation.get("result"))
    return result.upper() if result is not None else None


def _step_durations(
    metadata: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> Mapping[str, float]:
    durations: dict[str, float] = {}
    for key, value in _mapping(metadata.get("stepDurationsMs", {})).items():
        duration = _optional_number(value)
        if duration is not None:
            durations[str(key).strip()] = duration

    for step in _sequence_of_mappings(payload.get("steps", ())):
        step_id = _optional_text(step.get("id"))
        duration = _optional_number(step.get("durationMs"))
        if step_id and duration is not None:
            durations[step_id] = duration
    return durations


def _errored_steps(
    observations: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    errored: set[str] = set()
    for observation in observations:
        step_id = _optional_text(observation.get("stepId"))
        observed_state = _mapping(observation.get("observedState", {}))
        for key, value in observed_state.items():
            key_token = str(key).lower()
            value_token = str(value).strip().lower()
            if (
                step_id
                and ("status" in key_token or "result" in key_token)
                and value_token in {"error", "errored", "failed", "failure"}
            ):
                errored.add(step_id)
    return tuple(sorted(errored))


def _build_step_duration_metrics(
    samples_by_step: Mapping[str, Sequence[float]],
) -> tuple[StepDurationMetric, ...]:
    return tuple(
        StepDurationMetric(
            step_id=step_id,
            sample_count=len(samples),
            average_duration_ms=_average(samples) or 0.0,
            max_duration_ms=max(samples),
        )
        for step_id, samples in sorted(samples_by_step.items())
        if samples
    )


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = _optional_text(payload.get(key))
    if value is None:
        raise ObservabilityError(f"Run payload field {key!r} is required.")
    return value


def _int_value(value: Any, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _average(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None
