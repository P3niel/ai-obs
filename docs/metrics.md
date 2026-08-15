# Metrics

This document describes only the metrics that are actually computed by
`backend/app/operational_observability.py` and `latency_analytics.py`
today. It is generated from reading that code, not from a design spec —
if a metric isn't listed here, it isn't implemented yet (see Roadmap).

## Run Metrics

All produced by `summarize_kernel_runs()` → `OperationalMetrics`:

| Metric | Field | Description |
| --- | --- | --- |
| Run count | `runCount` | Total runs in the input batch. |
| Completed count | `completedCount` | Runs with Kernel status `COMPLETED`. |
| Running count | `runningCount` | Runs with Kernel status `RUNNING`. |
| Observation count | `observationCount` | Total observations across all runs. |
| Average latency | `averageLatencyMs` | Mean of all latency samples found in run metadata and observation `observedState` fields whose key contains `latency`. |
| Max latency | `maxLatencyMs` | Max of the same latency samples. |
| Average run duration | `averageDurationMs` | Mean of `metadata.durationMs` across runs that have it. |
| Max run duration | `maxDurationMs` | Max of the same. |

## Step Metrics

Per-step, from the same call, keyed by `stepId`:

| Metric | Field | Description |
| --- | --- | --- |
| Sample count | `sampleCount` | Number of duration samples for this step across runs. |
| Average step duration | `averageDurationMs` | Mean step duration. |
| Max step duration | `maxDurationMs` | Max step duration. |

Step durations are read from `metadata.stepDurationsMs` or from each step's
own `durationMs` field in the Kernel payload.

## Evaluation Metrics

From the Kernel's expected-vs-observed diff (`KernelEvaluation`, see
[Architecture](architecture.md)), aggregated across the run batch:

| Metric | Field | Description |
| --- | --- | --- |
| Match count | `matchCount` | Runs where the evaluation result is `MATCH`. |
| Mismatch count | `mismatchCount` | Runs where the evaluation result is `MISMATCH`. |
| Total evaluated | `totalEvaluated` | `matchCount + mismatchCount`. |
| Mismatch rate | `mismatchRate` | `mismatchCount / totalEvaluated`, or `0.0` if none evaluated. |

`mismatchRate` is the closest thing in the current implementation to a
"how often does representation diverge from reality" number — it is a
simple ratio over a fixed batch of runs, not a rolling trend, and it says
nothing about *why* a run mismatched, only whether the declared expected
state was observed.

## Latency Analytics Facade

`latency_analytics.py`'s `summarize_latency_analytics()` exposes a subset
of the fields above (`runCount`, `completedCount`, `runningCount`,
`averageLatencyMs`, `maxLatencyMs`, `averageDurationMs`, `maxDurationMs`,
`stepDurations`) without duplicating the calculation — it's a read-only
facade over `summarize_kernel_runs()`, not a separate computation.

## Metrics-Detection Handoff

`metrics_detection_handoff.py` is the only metric currently exchanged
through a versioned, validated artifact rather than read directly: the
`run.count` metric. This exists as a working example of the handoff
pattern, not as coverage for all metrics above — everything else in this
document is read directly by detection and analytics code, with no
intermediate artifact.

## Not Implemented

The following commonly-expected observability metrics do **not** exist in
this codebase yet. They are documented here explicitly so this list can't
be mistaken for a roadmap of hidden features:

- Success/failure rate as a named metric (only the raw match/mismatch
  counts and `mismatchRate` above exist).
- `p95` / percentile step or run durations (only average and max).
- Cost estimation from token counts and pricing. The dashboard *displays*
  a `metadata.estimatedCostUsd` field when present in a payload, but
  nothing in the backend computes it from tokens or a price table.
- Token counting.
- A rolling or baseline-comparison duration metric (e.g. "current run vs.
  median of the last N comparable runs").
- A composite "health score."
