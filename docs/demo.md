# Demo Guide

There are two separate demos in this repo: a static dashboard you click
through, and a terminal script that runs the actual pipeline end to end.
They are independent — the terminal demo does not read or write the
dashboard's files.

## Static Dashboard

- Local dashboard: [frontend/dashboard.html](../frontend/dashboard.html)
- Screenshot: [run-dashboard.png](assets/screenshots/run-dashboard.png)

The dashboard is self-contained and uses embedded example Kernel payloads,
so it can be opened from a local HTTP server without a backend process.

### Setup

From the repository root:

```bash
python3 -m http.server 8000
```

Open:

```text
http://127.0.0.1:8000/frontend/dashboard.html
```

### Walkthrough

1. Start on the full run list and show the summary strip: total runs,
   completed runs, and mismatches.
2. Select `run-observe-001` to show a completed `MATCH` run with a clean
   timeline and no evaluation deltas.
3. Select `run-observe-002` to show a completed `MISMATCH` run with mismatched
   state and unexpected observed state.
4. Use the result filters to isolate `MATCH` and `MISMATCH` runs.
5. Use the status filter to show the active `RUNNING` run with pending
   evaluation.
6. Note that replay and comparison exist as backend Python helpers
   (see [api.md](api.md)); this dashboard is the packaged static review
   surface, not a live view onto them.

## Runtime Pipeline Demo

`backend/run_demo.py` is a separate, additive demonstration of the full
observable runtime pipeline, distinct from the static dashboard above:

```text
Event Generator -> Kernel -> Storage -> Metrics -> Detection -> Console
```

### Setup

From the repository root:

```bash
.venv/bin/python3 backend/run_demo.py
```

No manual orchestration, network access, or additional services are
required — the demo has zero external dependencies, so it also runs with a
plain `python3 backend/run_demo.py` if you'd rather skip the virtual
environment entirely.

Add `--verbose` to print the raw input event JSON immediately before the
output it produces, for every event:

```bash
.venv/bin/python3 backend/run_demo.py --verbose
```

### What it does

1. Twelve deterministic synthetic `MODEL_CALL` events are generated and
   recorded one at a time through `InMemoryKernelStore`.
2. Each event prints an `EVENT RECEIVED` card with run ID, type, latency,
   and outcome.
3. After each event, updated metrics print: run count, success count, error
   count (from the Kernel evaluation match/mismatch aggregate), average
   latency, and max latency.
4. `run-005` is a synthetic failure; it immediately prints `ANOMALY DETECTED`
   for the `ERRORED_STEP` and `EVALUATION_FAILURE` alert conditions.
5. `run-008` has a 5100ms latency, exceeding the default
   `AlertThresholds.max_latency_ms` of 1000ms; it immediately prints
   `ANOMALY DETECTED` for the `SLOW_RUN` alert condition.
6. After every event, a refreshed dashboard block lists cumulative metrics
   and every currently active alert.
7. After the last event, the demo prints every stored run from the Kernel
   store and a detection-engine summary from `detect_run_anomalies`.

### Notes

- The demo calls `InMemoryKernelStore`, `summarize_kernel_runs` /
  `detect_alerts`, and `detect_run_anomalies` unchanged; it introduces no
  new metric, threshold, detection rule, event schema, or status.
- It is a terminal-only renderer with synchronous, in-process refresh (no
  polling, HTTP, or feed). It does not read or write
  `frontend/dashboard.html` or `frontend/dashboard.js`.
- "Success" / "Errors" in the demo metrics map to the Kernel evaluation
  `matchCount` / `mismatchCount`, not a separate status.

## Drift and Stability Demo (synthetic)

`backend/m2_demo.py` runs the passive M1/M2 drift evaluator and the M3
behavioral stability evaluator on nine deterministic, hand-written scenarios.
It calls the real code in `backend/app/`; it is **not** a pipeline.

```bash
python3 backend/m2_demo.py          # readable output
python3 backend/m2_demo.py --json   # machine-readable output
```

The demo needs the `rfc8785` package (`pip install -r backend/requirements.txt`).

### What is supplied, not produced

- The evidence qualification, the resolved evidence facts, and the M2 value are
  written into the scenarios. Nothing collects or qualifies evidence, stores a
  qualification, or produces an M2 belief.
- M1 and M2 form one branch (`produce_m1_observation`, then
  `evaluate_passive_drift`). M3 is a separate branch on its own run records and
  does not depend on M1 or M2.

### Scenarios and expected results

| # | Scenario | Result |
| -- | -- | -- |
| 1 | M1 = 1, M2 = 1 | D = 0, signed delta = 0 |
| 2 | Observed failure M1 = 0, represented success M2 = 1 | D = 1, signed delta = -1 |
| 3 | Referenced evidence absent | M1 abstains (`EVIDENCE_MISSING`), no D |
| 4 | Declared evidence integrity invalid | M1 abstains (`INTEGRITY_VALIDATION_FAILED`), no D |
| 5 | M1 and M2 refer to different system versions | Non-evaluable, no D |
| 6 | M3 on 10 runs, one event structure | M3 = 1 |
| 7 | M3 on 10 runs, two equally frequent structures | M3 = 0.5 |
| 8 | M3 on 9 runs | Non-evaluable, no M3 value |
| 9 | Scenario 2 repeated | Identical result |

`backend/tests/test_m2_demo.py` asserts these results.

### Limits

- `D = |M1 - M2|` is a passive magnitude. No threshold, class, or alert is
  attached to it, and none is implied.
- M3 measures structural stability of event sequences. It does not measure the
  correctness of answers and it is not Confidence.
- The scenarios are synthetic. They show how the evaluators behave on valid,
  missing, and non-comparable inputs; they do not show behavior on real data.

## General Talking Points

- Kernel payloads capture expected state, observed state, and the
  evaluation delta between them — see [Architecture](architecture.md).
- Observability reads caller-provided Kernel payloads for metrics, alerts,
  and notification message construction.
- Replay provides a deterministic timeline over serialized Kernel payloads.
- Comparison classifies metric noise separately from material structural
  or behavioral differences.
- The dashboard is static and embedded; it does not consume a live
  detection or anomaly feed. See Roadmap in the [README](../README.md).
