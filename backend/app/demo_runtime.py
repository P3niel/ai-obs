"""Deterministic end-to-end observable runtime demonstration for P3N-102.

This module wires the existing Kernel store, operational observability
metrics, and detection engine together and renders every stage to the
console:

    Event Generator -> Kernel -> Storage -> Metrics -> Detection -> Console

It introduces no new metric, threshold, detection rule, event schema, or
status enum. It only calls the existing pure functions in ``app.kernel``,
``app.operational_observability``, and ``app.run_anomaly_detection`` and
renders their existing output shapes. It does not read, write, or otherwise
touch ``frontend/dashboard.html`` or ``frontend/dashboard.js``; the P3N-85
detection-to-dashboard linkage contract governs that surface only, and this
module is a separate, additive, terminal-only renderer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from typing import Mapping
from typing import Sequence

from app.kernel import InMemoryKernelStore
from app.operational_observability import Alert
from app.operational_observability import AlertThresholds
from app.operational_observability import OperationalMetrics
from app.operational_observability import detect_alerts
from app.operational_observability import summarize_kernel_runs
from app.run_anomaly_detection import RunAnomalyReport
from app.run_anomaly_detection import detect_run_anomalies

DEMO_EVENT_TYPE = "MODEL_CALL"
DEMO_STEP_ID = "model_call"

_DIVIDER = "-" * 40
_DOUBLE_DIVIDER = "=" * 40

# "SUCCESS" / "FAILED" here are demo-only synthetic outcome labels used to
# build observed_state for the existing Kernel evaluation mechanism. They are
# not Kernel runtime statuses (RUNNING / COMPLETED) and not API contract
# statuses (RUNNING / SUCCEEDED / FAILED / CANCELLED / STUCK); every demo run
# still completes through the existing RUNNING -> COMPLETED lifecycle.
_OUTCOME_TO_OBSERVED_STATUS = {
    "SUCCESS": "ok",
    "FAILED": "failed",
}


@dataclass(frozen=True)
class DemoEvent:
    """One synthetic MODEL_CALL event driving one Kernel run in the demo."""

    run_id: str
    latency_ms: int
    outcome: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "event": DEMO_EVENT_TYPE,
            "latency_ms": self.latency_ms,
            "status": self.outcome,
        }


@dataclass(frozen=True)
class DemoStepResult:
    """Pipeline state after one event has traversed every stage."""

    event: DemoEvent
    run_payload: Mapping[str, Any]
    metrics: OperationalMetrics
    alerts: tuple[Alert, ...]
    new_alerts: tuple[Alert, ...]
    anomaly_report: RunAnomalyReport


def generate_demo_events() -> tuple[DemoEvent, ...]:
    """Return the fixed, deterministic demo event sequence.

    The sequence is mostly successful calls, one failed call (triggers the
    existing ERRORED_STEP and EVALUATION_FAILURE alert conditions), and one
    high-latency call (exceeds the existing AlertThresholds.max_latency_ms
    default of 1000ms and triggers the existing SLOW_RUN alert condition).
    """

    return (
        DemoEvent("run-001", 420, "SUCCESS"),
        DemoEvent("run-002", 680, "SUCCESS"),
        DemoEvent("run-003", 390, "SUCCESS"),
        DemoEvent("run-004", 910, "SUCCESS"),
        DemoEvent("run-005", 300, "FAILED"),
        DemoEvent("run-006", 560, "SUCCESS"),
        DemoEvent("run-007", 730, "SUCCESS"),
        DemoEvent("run-008", 5100, "SUCCESS"),
        DemoEvent("run-009", 480, "SUCCESS"),
        DemoEvent("run-010", 650, "SUCCESS"),
        DemoEvent("run-011", 720, "SUCCESS"),
        DemoEvent("run-012", 890, "SUCCESS"),
    )


def record_event(
    store: InMemoryKernelStore,
    event: DemoEvent,
) -> dict[str, Any]:
    """Record one demo event through the existing Kernel store.

    Follows the same run-payload-plus-metadata shape already used by
    ``backend/tests/test_operational_observability.py`` fixtures: a
    ``KernelRun.to_dict()`` payload with a ``metadata`` block carrying
    ``durationMs`` and ``stepDurationsMs`` for the metrics and detection
    helpers to read.
    """

    observed_status = _OUTCOME_TO_OBSERVED_STATUS[event.outcome]
    store.create_run(event.run_id)
    store.append_step(
        event.run_id,
        step_id=DEMO_STEP_ID,
        name="model call",
        expected_state={
            "status": "ok",
            "latency_ms": str(event.latency_ms),
        },
    )
    store.record_observation(
        event.run_id,
        step_id=DEMO_STEP_ID,
        observation_id=f"{event.run_id}-obs",
        fact="Model call completed.",
        observed_state={
            "status": observed_status,
            "latency_ms": str(event.latency_ms),
        },
    )
    store.complete_run(event.run_id)
    payload = store.get_run(event.run_id).to_dict()
    payload["metadata"] = {
        "durationMs": event.latency_ms,
        "stepDurationsMs": {DEMO_STEP_ID: event.latency_ms},
    }
    return payload


def run_demo_pipeline(
    events: Sequence[DemoEvent] | None = None,
    thresholds: AlertThresholds | None = None,
) -> tuple[DemoStepResult, ...]:
    """Run every demo event through Kernel, metrics, and detection.

    Returns one ``DemoStepResult`` per event, each carrying the metrics and
    alerts computed over every run recorded so far (including that event).
    """

    demo_events = (
        tuple(events) if events is not None else generate_demo_events()
    )
    store = InMemoryKernelStore()
    payloads: list[dict[str, Any]] = []
    seen_alert_keys: set[tuple[str, str, str]] = set()
    results: list[DemoStepResult] = []

    for event in demo_events:
        payload = record_event(store, event)
        payloads.append(payload)

        metrics = summarize_kernel_runs(payloads)
        alerts = detect_alerts(payloads, thresholds=thresholds)
        anomaly_report = detect_run_anomalies(payloads, thresholds=thresholds)

        alert_keys = {_alert_key(alert) for alert in alerts}
        new_keys = alert_keys - seen_alert_keys
        new_alerts = tuple(
            alert for alert in alerts if _alert_key(alert) in new_keys
        )
        seen_alert_keys |= alert_keys

        results.append(
            DemoStepResult(
                event=event,
                run_payload=payload,
                metrics=metrics,
                alerts=alerts,
                new_alerts=new_alerts,
                anomaly_report=anomaly_report,
            )
        )

    return tuple(results)


def _alert_key(alert: Alert) -> tuple[str, str, str]:
    return (alert.run_id, alert.condition.value, alert.message)


def render_event_input(event: DemoEvent) -> str:
    """Render the raw input JSON that drives one pipeline iteration.

    This is the same shape the event generator produces (``run_id``,
    ``event``, ``latency_ms``, ``status``); it is not a new event schema.
    """

    return json.dumps(event.to_dict(), indent=2)


def render_event_card(event: DemoEvent) -> str:
    lines = [
        _DIVIDER,
        "",
        "EVENT RECEIVED",
        "",
        "Run ID",
        event.run_id,
        "",
        "Type",
        DEMO_EVENT_TYPE,
        "",
        "Latency",
        f"{event.latency_ms} ms",
        "",
        "Status",
        event.outcome,
        "",
        _DIVIDER,
    ]
    return "\n".join(lines)


def render_alert(alert: Alert) -> str:
    lines = [
        "ANOMALY DETECTED",
        "",
        "Rule",
        alert.condition.value,
        "",
        "Severity",
        alert.severity.value,
        "",
        "Run",
        alert.run_id,
        "",
        "Message",
        alert.message,
    ]
    details = dict(alert.details)
    if details:
        lines += ["", "Details"]
        for key in sorted(details):
            lines.append(f"{key}: {details[key]}")
    return "\n".join(lines)


def render_metrics(metrics: OperationalMetrics) -> str:
    payload = metrics.to_dict()
    evaluations = payload["evaluations"]
    return "\n".join(
        [
            _label_line("Runs", payload["runCount"]),
            _label_line("Success", evaluations["matchCount"]),
            _label_line("Errors", evaluations["mismatchCount"]),
            _label_line(
                "Average latency",
                _format_ms(payload["averageLatencyMs"]),
            ),
            _label_line("Max latency", _format_ms(payload["maxLatencyMs"])),
        ]
    )


def render_dashboard(
    metrics: OperationalMetrics,
    active_alerts: Sequence[Alert],
) -> str:
    lines = [
        _DOUBLE_DIVIDER,
        "",
        "AI OBSERVABILITY - RUNTIME DEMO",
        "",
        _DOUBLE_DIVIDER,
        "",
        render_metrics(metrics),
        "",
        "Current Alerts",
    ]
    if active_alerts:
        for alert in active_alerts:
            lines.append(f"- {alert.condition.value} ({alert.run_id})")
    else:
        lines.append("(none)")
    lines += ["", _DOUBLE_DIVIDER]
    return "\n".join(lines)


def render_storage_summary(payloads: Sequence[Mapping[str, Any]]) -> str:
    lines = ["STORED RUNS", ""]
    for payload in payloads:
        evaluation = payload.get("evaluation") or {}
        lines.append(
            f"{payload['id']:<10} status={payload['status']:<10} "
            f"evaluation={evaluation.get('result', 'N/A')}"
        )
    return "\n".join(lines)


def _label_line(label: str, value: Any, width: int = 24) -> str:
    return f"{label}{'.' * max(1, width - len(label))}{value}"


def _format_ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f} ms"


def run_console_demo(
    events: Sequence[DemoEvent] | None = None,
    thresholds: AlertThresholds | None = None,
    *,
    verbose: bool = False,
    print_fn: Any = print,
) -> tuple[DemoStepResult, ...]:
    """Run the full demo pipeline and print every stage to the console.

    When ``verbose`` is true, the raw input JSON for each event is printed
    immediately before the output produced from it, so the input-to-output
    transformation is visible for every event.
    """

    results = run_demo_pipeline(events, thresholds=thresholds)

    for result in results:
        if verbose:
            print_fn("INPUT")
            print_fn(render_event_input(result.event))
            print_fn("")
        print_fn(render_event_card(result.event))
        for alert in result.new_alerts:
            print_fn("")
            print_fn(render_alert(alert))
        print_fn("")
        print_fn(render_dashboard(result.metrics, result.alerts))
        print_fn("")

    if results:
        final = results[-1]
        print_fn(
            render_storage_summary(
                [step.run_payload for step in results]
            )
        )
        print_fn("")
        print_fn(
            "Detection engine summary: "
            f"{final.anomaly_report.anomaly_count} anomaly(ies) across "
            f"{final.anomaly_report.affected_run_count} run(s) "
            f"{final.anomaly_report.condition_counts()}"
        )

    return results
