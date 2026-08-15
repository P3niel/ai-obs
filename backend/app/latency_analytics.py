"""Latency analytics facade for Kernel-derived run artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Sequence

from app.operational_observability import KernelRunInput
from app.operational_observability import StepDurationMetric
from app.operational_observability import summarize_kernel_runs


@dataclass(frozen=True)
class LatencyAnalyticsSummary:
    run_count: int
    completed_count: int
    running_count: int
    average_latency_ms: float | None
    max_latency_ms: float | None
    average_duration_ms: float | None
    max_duration_ms: float | None
    step_durations: tuple[StepDurationMetric, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "runCount": self.run_count,
            "completedCount": self.completed_count,
            "runningCount": self.running_count,
            "averageLatencyMs": self.average_latency_ms,
            "maxLatencyMs": self.max_latency_ms,
            "averageDurationMs": self.average_duration_ms,
            "maxDurationMs": self.max_duration_ms,
            "stepDurations": [
                step_duration.to_dict()
                for step_duration in self.step_durations
            ],
        }


def summarize_latency_analytics(
    runs: Sequence[KernelRunInput],
) -> LatencyAnalyticsSummary:
    metrics = summarize_kernel_runs(runs)
    return LatencyAnalyticsSummary(
        run_count=metrics.run_count,
        completed_count=metrics.completed_count,
        running_count=metrics.running_count,
        average_latency_ms=metrics.average_latency_ms,
        max_latency_ms=metrics.max_latency_ms,
        average_duration_ms=metrics.average_duration_ms,
        max_duration_ms=metrics.max_duration_ms,
        step_durations=metrics.step_durations,
    )
