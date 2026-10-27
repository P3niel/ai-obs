# Concepts: what AI-Obs measures, and why

Non-normative onboarding page. The status thresholds stated here are the ones
implemented in `backend/app/kernel_output.py`; the code is the authority.

Every output quoted below was produced by running the demos from a clean
checkout (commands in [Reproduce it](#reproduce-it)). Nothing is written by
hand.

## 1. What AI-Obs measures, and why

An AI system can believe it is doing well while reality says otherwise. A
support agent closes a ticket and reports success; the customer writes back the
next day. The system's own signals say "done"; the world says "not resolved".

AI-Obs makes that gap measurable. It compares two things:

| Measure | Question it answers | Where the value comes from |
| -- | -- | -- |
| **M1, reality** | Did it actually work, according to evidence from the world? | A qualified external evidence decision (user feedback, business outcome, external validation) |
| **M2, belief** | Did the system think it worked? | The system's own estimate (logs, confidence, scoring) |
| **D, the gap** | How far apart are the two? | `D = abs(M1 - M2)`, a passive magnitude |
| **M3, stability** | Is the behavior structurally consistent from run to run? | The shape of event sequences across comparable runs, not the correctness of answers |

Three rules keep these numbers honest:

- **A gap is only computed between comparable values.** If M1 and M2 refer to
  different system versions or targets, there is no `D`. The result is
  *non-evaluable* and says why. A missing number is better than a misleading one.
- **Missing or invalid evidence means abstention.** If the evidence behind M1 is
  absent or fails its integrity check, M1 is not produced and no `D` is computed.
- **Outputs are informational.** Nothing in the measured output triggers an
  action, changes trust, or corrects the system.

## 2. Why classic tools are not always enough

This is a statement about *categories of signal*, not about any product.

| Kind of tool | What it observes | What it does not compare |
| -- | -- | -- |
| Metrics and APM | Latency, throughput, error rates | Whether a fast, error-free answer was right |
| Logs and traces | What the system did and in what order | What the world later said about the outcome |
| LLM tracing and evaluation | Prompts, outputs, scores, often produced by the system or a judge model | The system's own estimate against *qualified external* evidence, as a separate, versioned quantity |

All of these describe the system *from the inside*: did it run, how fast, did it
fail, what did it say. A run can be fast, error-free and completed, and still be
wrong. Operational signals cannot see that, because they never look at reality.

AI-Obs keeps the operational layer; it is part of the repository. The second
question is simply added next to it: *does what the system believes match what
happened?*

The repository's own operational demo shows the operational layer at work. It
detects an errored step and a slow run:

```text
Current Alerts
- ERRORED_STEP (run-005)
- EVALUATION_FAILURE (run-005)
- SLOW_RUN (run-008)
```

That is useful, and it is a different question. It tells you a run failed or was
slow. It does not tell you that a run which looked healthy was believed to have
succeeded when evidence said it had not. That is what section 3 shows.

The two demos are separate and are not wired together: the operational demo does
not compute `D`, and the belief-versus-reality demo does not read operational
alerts. This page does not claim an integrated pipeline.

## 3. How the gap becomes observable

The chain, end to end, in the order the data moves:

1. **Qualified evidence** says what happened in the world.
2. **The M1 producer** turns a qualified evidence decision into M1, or abstains
   if the evidence is missing or invalid.
3. **The passive drift evaluator** compares M1 with M2 and returns `D` and a
   signed delta, or a structured non-evaluable result.
4. **The Kernel output** assembles `{drift, bias, stability, status}` from `D`
   and M3 and gives a health status.

The thresholds of step 4 belong to the Kernel output assembler
(`backend/app/kernel_output.py`), not to the passive evaluator, which attaches
no threshold, class or alert to `D`:

| Condition | Status |
| -- | -- |
| `D >= 0.30` | `critical` |
| `0.10 <= D < 0.30` | `warning` |
| `D < 0.10`, stability available and `> 0.50` | `healthy` |
| `D < 0.10`, stability `<= 0.50` | `unclassified` (`HEALTH_REGION_UNDEFINED`) |
| `D < 0.10`, stability unavailable | `unclassified` (`STABILITY_UNAVAILABLE`) |

`unclassified` is deliberate: when the contract defines no state, the output does
not invent one, and it never defaults to `healthy`.

### Worked example: belief far from reality

Scenario 3 of `backend/kernel_output_demo.py`. The system believes it fully
succeeded; reality says it did not.

```text
[3] Belief far from reality
    Gap of 0.30 or more: critical, from the gap alone.
    reality (M1) = 0   belief (M2) = 1
    gap (drift) = 1   bias = 1 (derived from drift)
    stability = 0 (M3 1 - drift)
    status = critical
```

### Same behavior, different verdicts

A small gap does not mean healthy. Scenario 1 is stable; scenario 4 has the same
small gap but unstable behavior:

```text
[1] Belief matches reality, stable behavior
    reality (M1) = 1   belief (M2) = 0.95
    gap (drift) = 0.05
    stability = 0.95 (M3 1 - drift)
    status = healthy

[4] Small gap but unstable behavior
    reality (M1) = 1   belief (M2) = 0.95
    gap (drift) = 0.05
    stability = 0.2833 (M3 0.3333 - drift)
    status = unclassified (HEALTH_REGION_UNDEFINED)
```

### Worked example: abstention

When the evidence is not there, AI-Obs says so instead of producing a number.
Scenario 3 of `backend/m2_demo.py`:

```text
[3] Referenced evidence is absent
    M1 abstains, so no D is computed.
    {"drift": null, "m1_produced": false, "reason_code": "EVIDENCE_MISSING"}
```

And when belief and reality are not comparable (scenario 7 of
`kernel_output_demo.py`):

```text
[7] Belief and reality not comparable
    M1 and M2 refer to different system versions: no gap, so the status is unclassified.
    gap (drift) = not evaluable: system_version
    status = unclassified (DRIFT_NOT_EVALUABLE)
```

## What this showcase does not claim

Read this before relying on any output.

- **The inputs are simulated.** M1, M2 and the run records are supplied by the
  demo scripts. Nothing collects evidence, qualifies it, stores it, or produces
  M2. The evidence qualification is a simulated, labelled external source; AI-Obs
  validates and compares M2, it does not produce it.
- **There is no real pipeline** collect, qualify, produce, present. That
  end-to-end path is not validated.
- **`D` is a magnitude, not a verdict.** The passive evaluator attaches no
  threshold. The status thresholds above live in the Kernel output assembler
  and are informational.
- **M3 is structural stability.** It is not the correctness of answers and not
  Confidence.
- **No action is taken.** Nothing in this repository gates, corrects or
  actuates anything. The Kernel output is informational (`authoritative:
  false`). The demo's note about a "Safety Gate" refers to a later component
  that is not part of this repository.
- **The dashboard does not show this output.** It is a static Run Explorer over
  embedded example Kernel payloads.

## Reproduce it

From the repository root, with the backend dependencies installed
(`python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt`):

```bash
.venv/bin/python3 backend/kernel_output_demo.py   # main scenario: belief versus reality
.venv/bin/python3 backend/m2_demo.py              # passive drift and stability, abstentions
.venv/bin/python3 backend/run_demo.py             # operational layer (classic signals)
```

All three are deterministic and run on synthetic data. Longer walk-throughs and
expected results per scenario are in [`demo.md`](demo.md).
