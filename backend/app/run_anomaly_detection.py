"""Run anomaly detection facade for Kernel-derived run artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Mapping
from typing import Sequence

from app.operational_observability import Alert
from app.operational_observability import AlertCondition
from app.operational_observability import AlertSeverity
from app.operational_observability import AlertThresholds
from app.operational_observability import KernelRunInput
from app.operational_observability import detect_alerts


SUPPORTED_ANOMALY_CONDITIONS = frozenset(
    {
        AlertCondition.SLOW_RUN,
        AlertCondition.STUCK_RUN,
        AlertCondition.ERRORED_STEP,
    }
)


@dataclass(frozen=True)
class RunAnomaly:
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
class RunAnomalyReport:
    anomalies: tuple[RunAnomaly, ...]

    @property
    def anomaly_count(self) -> int:
        return len(self.anomalies)

    @property
    def affected_run_count(self) -> int:
        return len({anomaly.run_id for anomaly in self.anomalies})

    def condition_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for anomaly in self.anomalies:
            counts[anomaly.condition.value] = (
                counts.get(anomaly.condition.value, 0) + 1
            )
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "anomalyCount": self.anomaly_count,
            "affectedRunCount": self.affected_run_count,
            "conditionCounts": self.condition_counts(),
            "anomalies": [
                anomaly.to_dict() for anomaly in self.anomalies
            ],
        }


def detect_run_anomalies(
    runs: Sequence[KernelRunInput],
    thresholds: AlertThresholds | None = None,
) -> RunAnomalyReport:
    anomalies = tuple(
        _to_anomaly(alert)
        for alert in detect_alerts(runs, thresholds=thresholds)
        if alert.condition in SUPPORTED_ANOMALY_CONDITIONS
    )
    return RunAnomalyReport(anomalies=anomalies)


def _to_anomaly(alert: Alert) -> RunAnomaly:
    return RunAnomaly(
        condition=alert.condition,
        severity=alert.severity,
        run_id=alert.run_id,
        message=alert.message,
        details=alert.details,
    )
