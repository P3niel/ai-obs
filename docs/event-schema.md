# Event & Run Data Shapes

Two real, implemented shapes exist in this codebase — the Kernel run
payload and the demo's synthetic event. There is no general-purpose
"Event" ingestion schema yet; that's future work, described at the bottom.

## Kernel Run Payload

The shape everything in this repo actually reads and writes:
`KernelRun.to_dict()`, produced by `backend/app/kernel.py`.

```text
KernelRun {
  id: string
  status: "RUNNING" | "COMPLETED"
  stepCount: number
  observationCount: number
  steps: KernelStep[]
  observations: KernelObservation[]
  evaluation: KernelEvaluation | null
  run_start_timestamp: string        // ISO-8601 UTC, e.g. 2026-08-03T10:00:00.000Z
  run_end_timestamp: string | null
}

KernelStep {
  id: string
  name: string
  expectedState: { [key: string]: string }
  events: string[]
  step_start_timestamp: string
  step_end_timestamp: string | null
}

KernelObservation {
  id: string
  runId: string
  stepId: string
  fact: string
  observedState: { [key: string]: string }
}

KernelEvaluation {
  id: string
  runId: string
  result: "MATCH" | "MISMATCH"
  expectedState: { [key: string]: string }
  observedState: { [key: string]: string }
  matches: string[]        // keys present and equal in both states
  missing: string[]        // keys in expectedState absent from observedState
  unexpected: string[]     // keys in observedState absent from expectedState
  mismatched: { key: string, expected: string, observed: string }[]
}
```

`result` is computed, not stored: `MISMATCH` if `missing`, `unexpected`, or
`mismatched` is non-empty; `MATCH` otherwise. This is the literal
implementation of the expected-vs-observed comparison described in the
[README](../README.md) and [Architecture](architecture.md) — it's a plain
key/value diff between two string-keyed maps, not a semantic or statistical
comparison.

Optional metadata fields, read by observability/comparison when present but
not part of the Kernel's own output:

```text
metadata.durationMs
metadata.latencyMs / maxLatencyMs / averageLatencyMs
metadata.updatedAgeMs
metadata.stepDurationsMs
metadata.estimatedCostUsd   // display-only, read by the dashboard, never computed
```

## Demo Event

The runtime demo (`backend/app/demo_runtime.py`) generates a much smaller,
synthetic shape — one event per Kernel run, all of type `MODEL_CALL`:

```text
DemoEvent {
  run_id: string
  event: "MODEL_CALL"
  latency_ms: number
  status: "SUCCESS" | "FAILED"
}
```

This is the entire ingestion surface that exists today. There is no event
router, no support for other event types, and no persistence of events
themselves — the demo generates a fixed, deterministic sequence in memory
and immediately turns each one into a Kernel run.

## Planned: General Event / Trace Model (Not Implemented)

The original design sketches a broader `Event` concept — an immutable,
timestamped record of any observable action (model call, tool call, memory
access, error, output) that would be persisted and later reconstructed into
an ordered `Trace` per run, with derived Timeline/Diagnostics/Signal views
on top. None of that exists in code: there is no `Event` type wider than
`DemoEvent`, no event persistence, and no trace reconstruction. If you're
looking for it in the source, you won't find it — it's listed here, not in
the README's implemented-features list, because it's the clearest example
of a documented future direction that must not be read as a current
capability.
