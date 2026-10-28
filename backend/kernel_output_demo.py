#!/usr/bin/env python3
"""Synthetic demonstration of the Kernel output: belief versus reality.

Usage (from the repository root):

    python3 backend/kernel_output_demo.py
    python3 backend/kernel_output_demo.py --json

What this is: seven deterministic scenarios that call the real passive drift
evaluator, the real M3 evaluator and the real Kernel output assembler on
hand-written, SIMULATED inputs, and print the gap between what a system
believes (M2) and what reality shows (M1) with its health status.

What this is not: a pipeline. Nothing here collects evidence, qualifies it,
produces an M2 belief or derives run records from a Kernel store. M1, M2 and
the run records are supplied by the scenarios and labelled ``simulated``. The
output is informational (``authoritative: false``) and is not an input of the
Safety Gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from typing import Callable

_BACKEND_ROOT = Path(__file__).resolve().parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.kernel_output import assemble_kernel_output  # noqa: E402
from app.m3_behavioral_stability import (  # noqa: E402
    evaluate_m3_behavioral_stability,
)
from app.passive_drift_evaluation import (  # noqa: E402
    evaluate_passive_drift,
)

_TARGET = "target-alpha"
_VERSION = "2026.09.1"
_AS_OF = "2026-10-01T00:00:00.000Z"
_SUCCESS = ["MODEL_CALL", "TOOL_CALL", "TOOL_RESULT", "FINAL_OUTPUT"]
_RETRY = ["MODEL_CALL", "TOOL_CALL", "TOOL_CALL", "TOOL_RESULT"]
_ERRORED = ["MODEL_CALL", "ERROR", "MODEL_CALL", "FINAL_OUTPUT"]
_STABLE = [_SUCCESS] * 12
_UNSTABLE = [_SUCCESS] * 4 + [_RETRY] * 4 + [_ERRORED] * 4
_TOO_FEW = [_SUCCESS] * 9

_LABEL = (
    "SIMULATED: M1, M2 and the run records are supplied by this script; "
    "nothing here collects evidence, qualifies it or produces M2."
)


def _m3_input(structures: list[list[str]]) -> dict[str, Any]:
    runs = []
    for index, events in enumerate(structures, start=1):
        day = f"2026-09-{index:02d}"
        runs.append(
            {
                "run_id": f"run-{index:02d}",
                "target_id": _TARGET,
                "system_version": _VERSION,
                "run_start_timestamp": f"{day}T10:00:00.000Z",
                "events": [
                    {
                        "timestamp": f"{day}T10:00:{n:02d}.000Z",
                        "event_type": event_type,
                    }
                    for n, event_type in enumerate(events)
                ],
                "run_end_timestamp": f"{day}T10:00:09.000Z",
            }
        )
    return {
        "contract_version": "m3-behavioral-stability-input/v0.1",
        "evaluation_id": "eval-m3-demo",
        "target_id": _TARGET,
        "system_version": _VERSION,
        "as_of": _AS_OF,
        "runs": runs,
    }


def _drift_input(
    run_id: str, m1: float, m2: float, m2_version: str = _VERSION
) -> dict[str, Any]:
    common = {
        "source_run_id": run_id,
        "target_id": _TARGET,
        "observation_window_id": "window-2026-09",
    }
    return {
        "contract_version": "passive-drift-evaluation-input/v0.2",
        "evaluation_id": "eval-drift-demo",
        "m1": dict(
            common,
            value=m1,
            system_version=_VERSION,
            evidence_ref="simulated/evidence/outcome",
            qualification="independent",
        ),
        "m2": dict(
            common,
            value=m2,
            system_version=m2_version,
            evaluator_id="simulated-belief-evaluator",
            evaluator_version="1.0.0",
        ),
    }


def _kernel_output(
    structures: list[list[str]],
    m1: float,
    m2: float,
    number: int,
    m2_version: str = _VERSION,
) -> dict[str, Any]:
    m3_input = _m3_input(structures)
    last = m3_input["runs"][-1]
    drift = evaluate_passive_drift(
        _drift_input(last["run_id"], m1, m2, m2_version)
    ).to_dict()
    m3 = evaluate_m3_behavioral_stability(m3_input)
    return assemble_kernel_output(
        {
            "contract_version": "kernel-output-input/v0.1",
            "evaluation_id": f"eval-kernel-demo-{number}",
            "drift_result": drift,
            "m3_result": m3,
            "evaluated_run": {
                "run_id": last["run_id"],
                "target_id": last["target_id"],
                "system_version": last["system_version"],
                "run_end_timestamp": last["run_end_timestamp"],
            },
        }
    )


def _scenarios() -> list[
    tuple[str, str, float, float, Callable[[int], dict[str, Any]]]
]:
    return [
        (
            "Belief matches reality, stable behavior",
            "Small gap and a stable window: healthy.",
            1.0,
            0.95,
            lambda n: _kernel_output(_STABLE, 1.0, 0.95, n),
        ),
        (
            "Belief overshoots reality",
            "Gap between 0.10 and 0.30: warning, from the gap alone.",
            0.8,
            1.0,
            lambda n: _kernel_output(_STABLE, 0.8, 1.0, n),
        ),
        (
            "Belief far from reality",
            "Gap of 0.30 or more: critical, from the gap alone.",
            0.0,
            1.0,
            lambda n: _kernel_output(_STABLE, 0.0, 1.0, n),
        ),
        (
            "Small gap but unstable behavior",
            "Stability is 0.5 or less and the gap is small: no state of the "
            "Kernel contract applies, so the status is unclassified.",
            1.0,
            0.95,
            lambda n: _kernel_output(_UNSTABLE, 1.0, 0.95, n),
        ),
        (
            "Not enough comparable runs, small gap",
            "M3 is non-evaluable, so healthy cannot be proven: unclassified.",
            1.0,
            0.95,
            lambda n: _kernel_output(_TOO_FEW, 1.0, 0.95, n),
        ),
        (
            "Not enough comparable runs, large gap",
            "The gap alone decides critical, even without stability.",
            0.0,
            1.0,
            lambda n: _kernel_output(_TOO_FEW, 0.0, 1.0, n),
        ),
        (
            "Belief and reality not comparable",
            "M1 and M2 refer to different system versions: no gap, so the "
            "status is unclassified.",
            1.0,
            0.95,
            lambda n: _kernel_output(_STABLE, 1.0, 0.95, n, "other-version"),
        ),
    ]


def run_scenarios() -> list[dict[str, Any]]:
    """Run every scenario and return its name, note, inputs and output."""
    return [
        {
            "scenario": index,
            "name": name,
            "note": note,
            "simulated": True,
            "m1": m1,
            "m2": m2,
            "output": call(index),
        }
        for index, (name, note, m1, m2, call) in enumerate(
            _scenarios(), start=1
        )
    ]


def _describe(output: dict[str, Any]) -> list[str]:
    drift = output["drift"]
    stability = output["stability"]
    lines = []
    if drift["evaluable"]:
        lines.append(
            f"gap (drift) = {drift['value']:.4g}   "
            f"bias = {output['bias']['value']:.4g} (derived from drift)"
        )
    else:
        lines.append("gap (drift) = not evaluable: " + _fields(drift))
    if stability["evaluable"]:
        lines.append(
            f"stability = {stability['value']:.4g} "
            f"(M3 {stability['m3']:.4g} - drift)"
        )
    else:
        lines.append("stability = unavailable: " + _fields(stability))
    status = output["status"]
    reasons = ", ".join(r["code"] for r in output["status_reasons"])
    lines.append(f"status = {status}" + (f" ({reasons})" if reasons else ""))
    return lines


def _fields(block: dict[str, Any]) -> str:
    return ", ".join(
        r.get("code", r.get("field", "?")) for r in block["reasons"]
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the simulated belief-versus-reality scenarios."
    )
    parser.add_argument(
        "--json", action="store_true", help="print results as JSON"
    )
    args = parser.parse_args()
    results = run_scenarios()
    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
        return 0
    print(__doc__.split("\n\n", 1)[0])
    print(_LABEL)
    print(
        "The output is informational and is not an input of the Safety "
        "Gate.\n"
    )
    for item in results:
        print(f"[{item['scenario']}] {item['name']}")
        print(f"    {item['note']}")
        print(
            f"    reality (M1) = {item['m1']:g}   belief (M2) = {item['m2']:g}"
        )
        for line in _describe(item["output"]):
            print(f"    {line}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
