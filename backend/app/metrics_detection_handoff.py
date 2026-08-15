"""Metrics-to-detection handoff artifact helpers.

Produces and consumes a versioned handoff artifact for the ``run.count``
metric — the only metric currently exchanged this way rather than read
directly (see docs/metrics.md). Detector thresholds, decisions, dashboard
fields, storage, and transport are intentionally outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import re
from typing import Any
from typing import Mapping
from typing import Sequence

from app.kernel import KernelRun


CONTRACT_VERSION = "metrics-detection-handoff/v0.1"
PRODUCER = "metrics"
CONSUMER = "detection"
SOURCE_PAYLOAD_CONTRACT = "KernelRun.to_dict"
METRIC_SOURCE_CONTRACT = "docs/metrics.md"

SUPPORTED_HANDOFF_METRIC_UNITS: Mapping[str, str | None] = {
    "run.count": None,
}

_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)
_HANDOFF_KEYS = frozenset(
    {
        "contract_version",
        "handoff_id",
        "created_at",
        "producer",
        "consumer",
        "source_runs",
        "metrics",
    }
)
_SOURCE_RUN_KEYS = frozenset({"run_id", "payload_contract"})
_METRIC_KEYS = frozenset(
    {
        "metric",
        "value",
        "unit",
        "sample_count",
        "source_contract",
    }
)

MetricValue = int | float | str | None
KernelRunInput = KernelRun | Mapping[str, Any]


class MetricsDetectionHandoffError(ValueError):
    """Raised when a handoff artifact violates the active contract."""


@dataclass(frozen=True)
class SourceRun:
    run_id: str
    payload_contract: str

    def to_dict(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "payload_contract": self.payload_contract,
        }


@dataclass(frozen=True)
class MetricObservation:
    metric: str
    value: MetricValue
    unit: str | None
    sample_count: int | None
    source_contract: str

    def to_dict(self) -> dict[str, MetricValue]:
        return {
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "sample_count": self.sample_count,
            "source_contract": self.source_contract,
        }


@dataclass(frozen=True)
class MetricsDetectionHandoff:
    contract_version: str
    handoff_id: str
    created_at: str
    producer: str
    consumer: str
    source_runs: tuple[SourceRun, ...]
    metrics: tuple[MetricObservation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "handoff_id": self.handoff_id,
            "created_at": self.created_at,
            "producer": self.producer,
            "consumer": self.consumer,
            "source_runs": [
                source_run.to_dict() for source_run in self.source_runs
            ],
            "metrics": [metric.to_dict() for metric in self.metrics],
        }


def build_metrics_detection_handoff(
    runs: Sequence[KernelRunInput],
    *,
    handoff_id: str,
    created_at: str,
) -> MetricsDetectionHandoff:
    """Build a validated handoff artifact from Kernel run payloads."""

    source_runs = tuple(_source_run_from_payload(run) for run in runs)
    handoff = MetricsDetectionHandoff(
        contract_version=CONTRACT_VERSION,
        handoff_id=handoff_id,
        created_at=created_at,
        producer=PRODUCER,
        consumer=CONSUMER,
        source_runs=source_runs,
        metrics=(
            MetricObservation(
                metric="run.count",
                value=len(source_runs),
                unit=None,
                sample_count=len(source_runs),
                source_contract=METRIC_SOURCE_CONTRACT,
            ),
        ),
    )
    return validate_metrics_detection_handoff(handoff)


def consume_metrics_detection_handoff(
    handoff: MetricsDetectionHandoff | Mapping[str, Any],
) -> tuple[MetricObservation, ...]:
    """Validate and expose handoff metrics to detection consumers."""

    return validate_metrics_detection_handoff(handoff).metrics


def validate_metrics_detection_handoff(
    handoff: MetricsDetectionHandoff | Mapping[str, Any],
) -> MetricsDetectionHandoff:
    """Validate a handoff artifact against the implemented contract surface."""

    payload = _handoff_mapping(handoff)
    _require_exact_keys(payload, _HANDOFF_KEYS, "handoff")

    contract_version = _required_text(payload, "contract_version")
    if contract_version != CONTRACT_VERSION:
        raise MetricsDetectionHandoffError(
            "Handoff contract_version must be "
            f"{CONTRACT_VERSION!r}."
        )

    handoff_id = _required_text(payload, "handoff_id")
    created_at = _required_text(payload, "created_at")
    _validate_timestamp(created_at)
    producer = _required_text(payload, "producer")
    if producer != PRODUCER:
        raise MetricsDetectionHandoffError(
            f"Handoff producer must be {PRODUCER!r}."
        )
    consumer = _required_text(payload, "consumer")
    if consumer != CONSUMER:
        raise MetricsDetectionHandoffError(
            f"Handoff consumer must be {CONSUMER!r}."
        )

    source_runs = tuple(
        _parse_source_run(item)
        for item in _sequence(payload.get("source_runs"), "source_runs")
    )
    metrics = tuple(
        _parse_metric(item)
        for item in _sequence(payload.get("metrics"), "metrics")
    )

    return MetricsDetectionHandoff(
        contract_version=contract_version,
        handoff_id=handoff_id,
        created_at=created_at,
        producer=producer,
        consumer=consumer,
        source_runs=source_runs,
        metrics=metrics,
    )


def _source_run_from_payload(run: KernelRunInput) -> SourceRun:
    payload = run.to_dict() if isinstance(run, KernelRun) else dict(run)
    return SourceRun(
        run_id=_required_text(payload, "id"),
        payload_contract=SOURCE_PAYLOAD_CONTRACT,
    )


def _handoff_mapping(
    handoff: MetricsDetectionHandoff | Mapping[str, Any],
) -> Mapping[str, Any]:
    if isinstance(handoff, MetricsDetectionHandoff):
        return handoff.to_dict()
    if isinstance(handoff, Mapping):
        return handoff
    raise MetricsDetectionHandoffError("Handoff must be a mapping.")


def _parse_source_run(item: Any) -> SourceRun:
    if not isinstance(item, Mapping):
        raise MetricsDetectionHandoffError(
            "source_runs items must be mappings."
        )
    _require_exact_keys(item, _SOURCE_RUN_KEYS, "source_run")
    run_id = _required_text(item, "run_id")
    payload_contract = _required_text(item, "payload_contract")
    if payload_contract != SOURCE_PAYLOAD_CONTRACT:
        raise MetricsDetectionHandoffError(
            "source_runs payload_contract must be "
            f"{SOURCE_PAYLOAD_CONTRACT!r}."
        )
    return SourceRun(
        run_id=run_id,
        payload_contract=payload_contract,
    )


def _parse_metric(item: Any) -> MetricObservation:
    if not isinstance(item, Mapping):
        raise MetricsDetectionHandoffError("metrics items must be mappings.")
    _require_exact_keys(item, _METRIC_KEYS, "metric")
    metric = _required_text(item, "metric")
    if metric not in SUPPORTED_HANDOFF_METRIC_UNITS:
        raise MetricsDetectionHandoffError(
            f"Metric {metric!r} is not supported by this handoff."
        )

    unit = _optional_text(item.get("unit"), "unit")
    expected_unit = SUPPORTED_HANDOFF_METRIC_UNITS[metric]
    if unit != expected_unit:
        raise MetricsDetectionHandoffError(
            f"Metric {metric!r} unit must be {expected_unit!r}."
        )
    source_contract = _required_text(item, "source_contract")
    if source_contract != METRIC_SOURCE_CONTRACT:
        raise MetricsDetectionHandoffError(
            "metrics source_contract must be "
            f"{METRIC_SOURCE_CONTRACT!r}."
        )

    return MetricObservation(
        metric=metric,
        value=_metric_value(item.get("value")),
        unit=unit,
        sample_count=_sample_count(item.get("sample_count")),
        source_contract=source_contract,
    )


def _require_exact_keys(
    payload: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    keys = set(payload.keys())
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if extra:
            details.append(f"unexpected keys: {', '.join(extra)}")
        raise MetricsDetectionHandoffError(
            f"Invalid {label} payload ({'; '.join(details)})."
        )


def _sequence(value: Any, key: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise MetricsDetectionHandoffError(f"{key} must be a sequence.")
    return tuple(value)


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MetricsDetectionHandoffError(
            f"Handoff field {key!r} must be a non-empty string."
        )
    return value


def _optional_text(value: Any, key: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MetricsDetectionHandoffError(
            f"Handoff field {key!r} must be a non-empty string or null."
        )
    return value


def _metric_value(value: Any) -> MetricValue:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MetricsDetectionHandoffError(
            "Metric value must be a number, string, or null."
        )
    if not math.isfinite(float(value)):
        raise MetricsDetectionHandoffError("Metric value must be finite.")
    return value


def _sample_count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MetricsDetectionHandoffError(
            "Metric sample_count must be a non-negative integer or null."
        )
    return value


def _validate_timestamp(created_at: str) -> None:
    if not _TIMESTAMP_PATTERN.match(created_at):
        raise MetricsDetectionHandoffError(
            "Handoff created_at must use canonical UTC timestamp format "
            "YYYY-MM-DDTHH:MM:SS.mmmZ."
        )
    try:
        datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise MetricsDetectionHandoffError(
            "Handoff created_at must be a valid UTC timestamp."
        ) from exc
