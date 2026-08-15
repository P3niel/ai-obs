# Architecture

AI-Obs is a runtime layer that captures and inspects Kernel-derived run
facts. This document describes the current implementation, not aspirational
design.

## Runtime Diagram

```text
Operator or test
      |
      v
+----------------------+      KernelRun.to_dict()
| InMemoryKernelStore  | -----------------------------+
| create run           |                              |
| append steps         |                              v
| record observations  |                  +-----------------------+
| complete evaluation  |                  | Serialized KernelRun |
+----------------------+                  | payload              |
                                          +-----------------------+
      |                                                |
      |                                                |
      v                                                v
+--------------------------+              +-----------------------+
| Operational observability|              | Replay engine         |
| metrics                  |              | immutable timeline    |
| alerts                   |              | cursor movement       |
| notification messages    |              +-----------------------+
+--------------------------+                          |
      |
      v
+--------------------------+
| Metrics-detection        |
| handoff artifact         |
| run.count                |
+--------------------------+
      |
      v
+--------------------------+
| Detection consumers      |
| validated metric input   |
+--------------------------+

+--------------------------+              +-----------------------+
| Run comparison           |              | Static dashboard      |
| metric deltas            |              | run list              |
| step diffs               |              | timeline              |
| observation diffs        |              | evaluation deltas     |
| evaluation diffs         |              +-----------------------+
+--------------------------+
```

## Runtime Responsibilities

- **Kernel** (`backend/app/kernel.py`): owns the executable run truth model.
  It records a step's declared *expected state*, the *observed state*
  reported back by an observation, and computes a deterministic evaluation
  delta (`MATCH` / `MISMATCH`) between the two. This expected-vs-observed
  diff is the concrete, implemented form of the project's "gap" thesis —
  see the [README](../README.md) for the framing and its scope.
- **Operational observability** (`operational_observability.py`): reads
  Kernel payloads and derives run/step metrics, threshold alerts, and
  provider-specific (Slack/Discord) notification message bodies. It performs
  no network I/O itself — callers supply the notification client.
- **Latency analytics** (`latency_analytics.py`): a focused read-only facade
  over the same metrics for run counts, latency, duration, and step-duration
  aggregates.
- **Run anomaly detection** (`run_anomaly_detection.py`): a facade over
  alert detection that reports slow, stuck, and errored runs as anomalies.
- **Alert dispatch** (`alert_dispatch.py`): sends detected alerts to
  configured Slack or Discord webhooks and converts provider failures into
  dispatch results instead of raising.
- **Metrics-detection handoff** (`metrics_detection_handoff.py`): serializes
  the `run.count` metric into a versioned artifact for detection consumers.
  This is the only metric currently covered by a handoff artifact; duration
  and latency are not yet included.
- **Replay** (`replay.py`): reads a Kernel payload and builds an immutable,
  cursor-navigable frame timeline. Read-only — it does not mutate Kernel
  state or re-execute anything.
- **Run comparison** (`run_comparison.py`): reads two Kernel payloads and
  classifies differences as noise (small metric deltas) or material
  (structural/behavioral differences).
- **Canonical mapping** (`canonical_mapping.py`): an additive, read-only
  layer that maps Kernel payloads and `OperationalMetrics` onto a canonical
  status vocabulary, run shape, and latency metric names, without changing
  the modules above.
- **Runtime demo** (`demo_runtime.py` / `backend/run_demo.py`): drives a
  deterministic sequence of synthetic `MODEL_CALL` events through the
  Kernel store, operational observability, and detection helpers above,
  printing every stage to the console. It is a separate, additive,
  terminal-only surface — it does not read or write
  `frontend/dashboard.html` or `frontend/dashboard.js`, and introduces no
  new metric, threshold, detection rule, or status.
- **Static dashboard** (`frontend/dashboard.html`): presents embedded
  example Kernel payloads as a static, dependency-free Run Explorer. It
  does not fetch live data and does not call any of the Python helpers
  above at runtime.

## Boundaries

- Operational observability performs no direct network I/O; callers provide
  notification clients.
- Replay and comparison read Kernel payloads; they do not mutate Kernel
  state or redefine the Kernel payload contract.
- The static dashboard is a presentation surface only. It is not a backend
  API server and does not persist data.
- The runtime demo's console output is a separate terminal surface. It
  consumes metrics and detection output synchronously and in-process and is
  not a live feed into the static dashboard.

## Current Limitations

These are explicit, not implied:

- The Kernel store is in-process and deterministic; there is no durable
  storage layer. Restarting the process discards all runs.
- There is no HTTP API. Everything is a Python module API called
  in-process (`backend/app`); no server, no network boundary, no auth layer.
- Metrics and detection are Python helpers over caller-provided Kernel
  payloads, not a running pipeline. There is no event stream, message
  transport, or database behind them.
- Only the `run.count` metric has a versioned handoff artifact between
  metrics and detection; other metrics are read directly, not exchanged
  through a validated artifact.
- The dashboard uses embedded example payloads, not a live API. No
  detection or anomaly-report feed currently drives it — wiring the
  dashboard to live detection output is unimplemented (see Roadmap in the
  README).
- Replay and comparison fidelity is limited to fields present in Kernel
  payloads and optional metadata; there is no execution replay (re-running
  a model or tool) — only deterministic reconstruction of what was already
  recorded.
- The Kernel does not modify models, adjust weights, execute corrective
  actions, or take autonomous action of any kind. It observes and computes;
  it does not act.
