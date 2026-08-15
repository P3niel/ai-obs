# Detection

This document describes the alert/anomaly detection rules actually
implemented in `backend/app/operational_observability.py` and
`run_anomaly_detection.py`. It's generated from reading `_detect_run_alerts()`
directly, not from a design spec.

## Alert Conditions

`detect_alerts()` evaluates every run against `AlertThresholds` and returns
zero or more `Alert` objects. There are five conditions:

| Condition | Severity | Trigger |
| --- | --- | --- |
| `SLOW_RUN` | WARNING | Run duration (`metadata.durationMs`) exceeds `max_run_duration_ms`, **or** any latency sample exceeds `max_latency_ms`. Both cases produce a `SLOW_RUN` alert with a different message. |
| `SLOW_STEP` | WARNING | A step's duration exceeds `max_step_duration_ms`. One alert per offending step. |
| `STUCK_RUN` | CRITICAL | Run status is `RUNNING` and `metadata.updatedAgeMs` exceeds `stuck_after_ms`. |
| `ERRORED_STEP` | CRITICAL | An observation's `observedState` has a key containing `status` or `result` whose value is `error`, `errored`, `failed`, or `failure`. One alert per distinct errored step. |
| `EVALUATION_FAILURE` | CRITICAL | The run's Kernel evaluation result is `MISMATCH` (see [Architecture](architecture.md) for what that means). |

## Default Thresholds

`AlertThresholds` defaults, overridable per call:

```text
max_latency_ms      = 1000.0
max_run_duration_ms = 30000.0
max_step_duration_ms = 10000.0
stuck_after_ms       = 60000.0
```

These are plain constants, not learned or adaptive — there's no baselining,
no per-run-type threshold, and no statistical anomaly model behind them.

## Run Anomaly Report

`detect_run_anomalies()` is a narrower facade over `detect_alerts()`. It
only surfaces three of the five conditions:

```text
SLOW_RUN
STUCK_RUN
ERRORED_STEP
```

`SLOW_STEP` and `EVALUATION_FAILURE` are alert conditions available from
`detect_alerts()` directly, but are not included in `RunAnomalyReport`. If
you need the full alert set, call `detect_alerts()`, not
`detect_run_anomalies()`.

## Notification Dispatch

`build_notification_message()` formats an `Alert` for Slack or Discord.
`dispatch_alert_notifications()` (in-process) and
`dispatch_alerts_to_webhooks()` (in `alert_dispatch.py`, actual HTTP calls
to configured webhooks) send them. Provider failures are captured as
`NotificationDispatchResult` entries rather than raised — a bad webhook
doesn't crash the caller.

## Not Implemented

- No machine-learning or statistical anomaly detection — every condition
  above is a fixed threshold or a fixed string match.
- No cross-run trend detection (e.g. "latency is drifting upward over the
  last week"). Detection runs per-batch, over whatever runs are passed in.
- No alert deduplication, suppression window, or escalation policy.
- No live feed from detection into the static dashboard (see Roadmap in
  the [README](../README.md)).
