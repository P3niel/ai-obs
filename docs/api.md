# Python API

The current shipped API is a Python module API. There is no implemented HTTP
API layer or durable run store. Runtime helpers accept `KernelRun` objects or
caller-serialized `KernelRun.to_dict()` payloads where documented.

## Future HTTP API Contract (Planned, Not Implemented)

The status and error vocabulary below is a design decision for a future HTTP
layer. Documenting it here is intentional — it shows the shape the API is
meant to grow into — but no HTTP server exists yet, and nothing in this
section is callable today.

Planned API status values:

```text
RUNNING
SUCCEEDED
FAILED
CANCELLED
STUCK
```

Active runtime-to-API mapping:

| Kernel Runtime | API Contract |
| --- | --- |
| `RUNNING` | `RUNNING` |
| `COMPLETED` | `SUCCEEDED` |

Canonical HTTP error vocabulary:

```text
RUN_ALREADY_EXISTS
STEP_ALREADY_EXISTS
RUN_NOT_FOUND
INVALID_STATUS_TRANSITION
RUN_ALREADY_COMPLETED
INVALID_REQUEST
INTERNAL_ERROR
```

Canonical HTTP responses:

| Condition | HTTP |
| --- | --- |
| Duplicate Run | `409 Conflict` |
| Duplicate Step | `409 Conflict` |
| Missing Run | `404 Not Found` |
| Invalid Transition | `409 Conflict` |
| Invalid Request | `400 Bad Request` |
| Internal Error | `500 Internal Server Error` |

Repeated completion requests return `409 Conflict` with
`RUN_ALREADY_COMPLETED`.

Future HTTP serialization and persistence-facing payloads must use:

```text
run_start_timestamp
run_end_timestamp
step_start_timestamp
step_end_timestamp
```

The deprecated draft timestamp terms `created_at`, `updated_at`, `started_at`,
and `finished_at` must not be used for future run or step serialization.

## Health

```python
from app.health import health_status

payload = health_status()
# {"status": "ok"}
```

## Kernel

`InMemoryKernelStore` creates runs, appends steps, records observations, and
completes runs with a deterministic evaluation. Run and step timestamps
(`run_start_timestamp`/`run_end_timestamp`/`step_start_timestamp`/
`step_end_timestamp`) are captured automatically at each lifecycle
transition. Pass `clock=` (a zero-argument callable returning a
timezone-aware `datetime`) to get deterministic timestamps in tests; it
defaults to the real UTC clock.

```python
from app.kernel import InMemoryKernelStore

store = InMemoryKernelStore()
run = store.create_run("run-001")

store.append_step(
    run.run_id,
    step_id="collect",
    name="collect service health",
    expected_state={"status": "ok"},
    events=("probe started", "probe finished"),
)

store.record_observation(
    run.run_id,
    step_id="collect",
    observation_id="obs-collect",
    fact="Health endpoint returned ok.",
    observed_state={"status": "ok"},
)

store.complete_run(run.run_id, evaluation_id="eval-001")
payload = store.get_run(run.run_id).to_dict()
```

Important classes and values:

- `KernelRun`: immutable run payload with `run_id`, `status`, `steps`,
  `observations`, optional `evaluation`, `run_start_timestamp`, and optional
  `run_end_timestamp`.
- `KernelStep`: expected state and events for a run step, plus
  `step_start_timestamp` and optional `step_end_timestamp`.
- `KernelObservation`: observed state and fact for a step.
- `KernelEvaluation`: expected versus observed state delta.
- `RunStatus`: `RUNNING` or `COMPLETED`.
- `EvaluationResult`: `MATCH` or `MISMATCH`.
- `KernelError`: raised for invalid Kernel input or state transitions.

## Operational Observability

`summarize_kernel_runs` derives aggregate metrics from Kernel payloads.
`detect_alerts` reads the same caller-provided Kernel payloads directly. This
repo does not write a shared metrics artifact, metrics row, or event stream
that detection later consumes — metrics and detection both read Kernel
payloads directly, except for one narrow case below.

`metrics_detection_handoff.py` implements a versioned handoff artifact for
exactly one metric, `run.count`, as the initial (and so far only) example of
metrics being exchanged through a validated artifact rather than read
directly. See [Metrics](metrics.md) for the full list of implemented
metrics and which ones this applies to.

```python
from app.operational_observability import summarize_kernel_runs

metrics = summarize_kernel_runs([payload])
metrics.to_dict()
```

```python
from app.metrics_detection_handoff import build_metrics_detection_handoff
from app.metrics_detection_handoff import consume_metrics_detection_handoff

handoff = build_metrics_detection_handoff(
    [payload],
    handoff_id="handoff-001",
    created_at="2026-07-05T18:55:00.000Z",
)
metric_observations = consume_metrics_detection_handoff(handoff)
```

The handoff artifact intentionally excludes threshold values, detector
decisions, dashboard fields, provider delivery state, hidden defaults, inferred
metric definitions, and inferred detection rules. Duration and latency handoff
metrics remain blocked until explicit source timestamp and metric contracts are
available to the runtime payloads.

`detect_alerts` returns deterministic alerts for slow, stuck, errored, or
mismatched runs.

```python
from app.operational_observability import AlertThresholds
from app.operational_observability import detect_alerts

alerts = detect_alerts(
    [payload],
    thresholds=AlertThresholds(max_run_duration_ms=30000),
)
```

`build_notification_message` formats provider-specific messages for Slack or
Discord. `dispatch_alert_notifications` accepts caller-provided clients and
does not perform direct network I/O on its own.

```python
from app.operational_observability import NotificationProvider
from app.operational_observability import build_notification_message

message = build_notification_message(NotificationProvider.SLACK, alerts[0])
```

Important classes and values:

- `OperationalMetrics`
- `AlertThresholds`
- `Alert`
- `AlertCondition`
- `AlertSeverity`
- `NotificationProvider`
- `NotificationMessage`
- `NotificationDispatchResult`
- `ObservabilityError`
- `MetricsDetectionHandoff`
- `MetricObservation`
- `SourceRun`
- `MetricsDetectionHandoffError`

## Latency Analytics

`summarize_latency_analytics` exposes the core latency analytics contract for
dashboarding and alert logic without duplicating observability calculations.

```python
from app.latency_analytics import summarize_latency_analytics

summary = summarize_latency_analytics([payload])
summary.to_dict()
```

The payload includes run counts, average and maximum latency, average and
maximum run duration, and duration aggregates by step.

Important classes and values:

- `LatencyAnalyticsSummary`

## Run Anomaly Detection

`detect_run_anomalies` reports runs above configured thresholds, stuck runs,
and errored steps as anomalies (a narrower facade over `detect_alerts` — see
[Detection](detection.md) for exactly which alert conditions it surfaces).
The static dashboard does not consume this anomaly report as a live feed.

```python
from app.operational_observability import AlertThresholds
from app.run_anomaly_detection import detect_run_anomalies

report = detect_run_anomalies(
    [payload],
    thresholds=AlertThresholds(max_latency_ms=800),
)
report.to_dict()
```

The report includes total anomaly count, affected run count, counts by
condition, and each anomaly payload.

Important classes and values:

- `RunAnomaly`
- `RunAnomalyReport`
- `SUPPORTED_ANOMALY_CONDITIONS`

## Dashboard Linkage

The dashboard remains a static review surface over embedded Kernel-compatible
payloads. It does not consume a live anomaly report, alert feed, backend
route, metrics-to-detection handoff artifact, or runtime transport. Wiring
the dashboard to live detection output is unimplemented — see Roadmap in the
[README](../README.md).

## Alert Dispatch

`dispatch_alerts_to_webhooks` sends existing alert payloads to configured Slack
or Discord webhooks. Provider failures are captured as
`NotificationDispatchResult` entries instead of raising through the main request
flow.

```python
from app.alert_dispatch import WebhookConfig
from app.alert_dispatch import dispatch_alerts_to_webhooks

config = WebhookConfig.from_env()
results = dispatch_alerts_to_webhooks(alerts, config=config)
```

`detect_and_dispatch_alerts` combines alert detection and dispatch for callers
that want a single runtime helper.

```python
from app.alert_dispatch import detect_and_dispatch_alerts

results = detect_and_dispatch_alerts(
    [payload],
    thresholds=AlertThresholds(max_run_duration_ms=30000),
    config=WebhookConfig.from_env(),
)
```

Provider configuration uses environment variables:

```text
AI_OBS_SLACK_WEBHOOK_URL=https://hooks.slack.example/...
AI_OBS_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
AI_OBS_ALERT_WEBHOOK_TIMEOUT_SECONDS=5
AI_OBS_ALERT_ALLOW_INSECURE_HTTP=false
```

Configuration notes:

- Set only the providers that should receive alerts.
- `AI_OBS_ALERT_WEBHOOK_TIMEOUT_SECONDS` defaults to `5`.
- `AI_OBS_ALERT_ALLOW_INSECURE_HTTP` defaults to `false`; set it only for local
  test servers such as `http://127.0.0.1:<port>`.
- Provider secrets must stay outside repository-managed files.

Important classes and values:

- `WebhookConfig`
- `WebhookNotificationClient`
- `AlertDispatchError`
- `dispatch_alerts_to_webhooks`
- `detect_and_dispatch_alerts`

## Replay

`build_replay_session` creates an immutable timeline from a `KernelRun` object
or persisted Kernel payload.

```python
from app.replay import build_replay_session

session = build_replay_session(payload)
first_step = session.advance().current
terminal = session.seek(session.total_frames - 1).current
```

Important classes and values:

- `ReplaySession`: immutable timeline cursor with `advance`, `retreat`, and
  `seek`.
- `ReplayFrame`: one replay frame with phase, status, optional step data,
  observations, and evaluation data.
- `ReplayPhase`: `RUN_STARTED`, `STEP`, `EVALUATION`, or `RUN_COMPLETED`.
- `ReplayError`: raised for invalid payloads or cursor movement.

## Run Comparison

`compare_kernel_runs` compares two Kernel payloads or `KernelRun` objects.

```python
from app.run_comparison import compare_kernel_runs

comparison = compare_kernel_runs(baseline_payload, candidate_payload)
comparison.has_material_differences
comparison.to_dict()
```

Small metric deltas are classified as `NOISE`; structural and behavioral
differences are classified as `MATERIAL`.

```python
from app.run_comparison import ComparisonThresholds
from app.run_comparison import compare_kernel_runs

comparison = compare_kernel_runs(
    baseline_payload,
    candidate_payload,
    thresholds=ComparisonThresholds(latency_noise_threshold_ms=25),
)
```

Important classes and values:

- `RunComparison`
- `RunDifference`
- `MetricDelta`
- `ComparisonThresholds`
- `DifferenceKind`
- `DifferenceSeverity`
- `RunComparisonError`

## Runtime Demo

`backend/app/demo_runtime.py` implements an end-to-end observable runtime
demonstration. It generates a deterministic sequence of synthetic
`MODEL_CALL` events, records each one through the existing
`InMemoryKernelStore`, computes metrics with `summarize_kernel_runs`, detects
alerts with `detect_alerts` and `detect_run_anomalies`, and renders every
stage to the console.

```python
from app.demo_runtime import run_console_demo

run_console_demo()
```

Run the whole demonstration with a single command from the repository root:

```bash
.venv/bin/python3 backend/run_demo.py
```

Pass `--verbose` (or `run_console_demo(verbose=True)`) to print the raw input
event JSON, via `render_event_input`, immediately before the output it
produces for every event:

```bash
.venv/bin/python3 backend/run_demo.py --verbose
```

The demo introduces no new metric, threshold, detection rule, event schema,
or status enum; it only calls the existing pure functions above and prints
their existing output shapes (`OperationalMetrics.to_dict()`, `Alert.to_dict()`,
`RunAnomalyReport.to_dict()`). It does not read or write
`frontend/dashboard.html` or `frontend/dashboard.js` — the console demo is a
separate, additive, terminal-only renderer with synchronous in-process
refresh (no polling, HTTP, or feed).

Important classes and values:

- `DemoEvent`
- `DemoStepResult`
- `generate_demo_events`
- `run_demo_pipeline`
- `run_console_demo`
- `render_event_input`

## Payload Shape

The shared runtime payload shape is the output of `KernelRun.to_dict()`:

```text
{
  "id": string,
  "status": "RUNNING" | "COMPLETED",
  "stepCount": number,
  "observationCount": number,
  "steps": [...],
  "observations": [...],
  "evaluation": object | null,
  "run_start_timestamp": string,
  "run_end_timestamp": string | null
}
```

Each entry in `steps` includes `step_start_timestamp` and
`step_end_timestamp` (`string | null`). Timestamps are ISO-8601 UTC with
millisecond precision (for example `2026-08-03T10:00:00.000Z`).
`run_start_timestamp`/`step_start_timestamp` are always present once the run
or step exists; the `_end_timestamp` fields are `null` until the run
completes or the step's first observation is recorded.

Optional metadata fields are read by observability and comparison when present:

```text
metadata.durationMs
metadata.latencyMs
metadata.maxLatencyMs
metadata.averageLatencyMs
metadata.updatedAgeMs
metadata.stepDurationsMs
```

Unknown metadata is ignored by the current helpers.

## Canonical Mapping

`backend/app/canonical_mapping.py` is an additive, read-only layer over the
payload shape above and over `OperationalMetrics`, without changing either:

```python
from app.canonical_mapping import to_canonical_run
from app.canonical_mapping import to_canonical_latency_metrics
from app.canonical_mapping import to_canonical_status

canonical_run = to_canonical_run(payload)
canonical_run.to_dict()
# {"run_id": ..., "status": "running"|"completed"|..., "run_start_timestamp": ...,
#  "run_end_timestamp": ..., "steps": [{"step_id": ..., "step_start_timestamp": ...,
#  "step_end_timestamp": ...}]}

to_canonical_latency_metrics(metrics)
# {"step.mean.duration.ms": ..., "step.max.duration.ms": ...}

to_canonical_status("RUNNING")  # "running"
```

`to_canonical_run` accepts either a `KernelRun` object or a
`KernelRun.to_dict()`-shaped mapping. `to_canonical_status` maps onto a
lowercase status vocabulary (`running`/`completed`/`failed`/`cancelled`/
`stuck`/`unknown`); only `running` and `completed` are reachable from the
current Kernel runtime — the rest exist for forward compatibility with a
future HTTP API and are not produced by any code path today.

Important classes and values:

- `CanonicalRun`
- `CanonicalStep`
- `CanonicalMappingError`
- `to_canonical_run`
- `to_canonical_status`
- `to_canonical_latency_metrics`

## Static Run Explorer

`frontend/dashboard.html` renders a dependency-free Run Explorer over embedded
Kernel-compatible payloads. The list view exposes run status, duration, step
count, and an error signal derived from existing observation/evaluation fields.
The selected-run summary exposes status, duration, step count, observation
count, errors, and estimated cost. The list can be narrowed by dashboard state
categories: `SUCCESS`, `FAILED`, and `RUNNING`.

The detail view can be opened directly with a hash route:

```text
frontend/dashboard.html#run=run-observe-004
```

The static Run Explorer does not fetch live runtime data and does not call
`summarize_kernel_runs`, `detect_alerts`, or `detect_run_anomalies`. It derives
its dashboard categories and error signals from the embedded payloads in
`frontend/dashboard.html`.

The error signal uses the same existing observation convention as operational
observability: an observation with a `stepId`, an `observedState` key containing
`status` or `result`, and a value of `error`, `errored`, `failed`, or `failure`
is rendered as a step error. Mismatched evaluations are rendered as evaluation
mismatches when no errored step is present.

The dashboard state filter is a UI category derived from existing fields:
`RUNNING` maps to Kernel runs whose status is `RUNNING`, `FAILED` maps to
completed runs with a step error or evaluation mismatch, and `SUCCESS` maps to
completed runs without those error signals. These dashboard categories do not
extend the Kernel `RunStatus` contract.

The timeline is reconstructed from the ordered `steps` array, each step's
`events`, and the matching observation for that `stepId`.

Estimated cost is displayed from available run metadata:

```text
metadata.estimatedCostUsd
```

The dashboard does not calculate a fallback cost heuristic when token and price
telemetry are absent.
