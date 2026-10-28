#!/usr/bin/env python3
"""Synthetic demonstration of the passive M1/M2 drift and M3 evaluators.

Usage (from the repository root):

    python3 backend/m2_demo.py
    python3 backend/m2_demo.py --json

What this is: nine deterministic scenarios that call the real evaluators on
hand-written, synthetic inputs and print the results.

What this is not: a pipeline. Nothing here collects evidence, qualifies it,
stores it, or produces an M2 belief. The qualification, the resolved evidence
facts, and the M2 value are supplied by the scenarios below. M3 runs on its own
synthetic run records and does not depend on M1 or M2.

``D = |M1 - M2|`` is a passive magnitude: no threshold, class, or alert is
attached to it. M3 measures structural stability of event sequences, not the
correctness of answers and not Confidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

_BACKEND_ROOT = Path(__file__).resolve().parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.m1_observation_producer import (  # noqa: E402
    EvidenceView,
    produce_m1_observation,
)
from app.m3_behavioral_stability import (  # noqa: E402
    evaluate_m3_behavioral_stability,
)
from app.passive_drift_evaluation import (  # noqa: E402
    evaluate_passive_drift,
)

_USABLE = "USABLE"

_RUN: dict[str, Any] = {
    "evaluation_profile_id": "support-resolution",
    "evaluation_profile_version": "1.0.0",
    "source_run_id": "run-support-001",
    "target_id": "ticket-123",
    "system_version": "support-agent-2026.08",
    "observation_window_id": "ticket-123-resolution-window",
}

_PROFILE: dict[str, Any] = {
    "contract_version": "evaluation-profile/v0.1",
    "profile_id": "support-resolution",
    "profile_version": "1.0.0",
    "owner_id": "support-operations",
    "run_type": "support-resolution",
    "outcome_definition_ref": "rule/outcome-ticket-resolved/v1",
    "binary_success_rule_ref": "rule/ticket-resolved/v1",
    "binary_failure_rule_ref": "rule/ticket-not-resolved/v1",
    "authorized_source_types": ["business_outcome", "automated_test"],
    "authorized_evidence_stores": [
        {
            "evidence_store_id": "support-outcomes",
            "evidence_store_version": "1.0.0",
        }
    ],
    "authorized_qualifier_refs": ["support-outcome-qualifier"],
    "evidence_timing_rule_ref": "rule/outcome-within-24h/v1",
    "abstention_rule_refs": [
        "rule/abstain-missing-outcome/v1",
        "rule/abstain-conflict/v1",
    ],
    "integrity_policy_ref": "policy/support-integrity/v1",
    "privacy_policy_ref": "policy/support-privacy/v1",
    "m2_producer": {
        "producer_type": "dedicated_evaluator",
        "evaluator_id": "support-belief-evaluator",
        "evaluator_version": "1.0.0",
        "input_schema_version": "support-belief-input/v1",
        "timing_rule_ref": "rule/m2-before-outcome/v1",
    },
}

_ASSERTION: dict[str, Any] = {
    "contract_version": "feedback-evidence-assertion/v0.1",
    "evidence_id": "evidence-ticket-closed",
    "evidence_version": "1.0.0",
    "profile_id": "support-resolution",
    "profile_version": "1.0.0",
    "source_type": "business_outcome",
    "source_id": "support-ticket-store",
    "source_version": "1.0.0",
    "source_run_id": "run-support-001",
    "target_id": "ticket-123",
    "system_version": "support-agent-2026.08",
    "observation_window_id": "ticket-123-resolution-window",
    "outcome_value": 1,
    "evidence_store_id": "support-outcomes",
    "evidence_store_version": "1.0.0",
    "evidence_ref": "tickets/123/outcome/1",
    "digest_algorithm": "sha-256",
    "content_digest": "0123456789abcdef" * 4,
    "source_signature_ref": "attestation-ticket-closed",
    "observed_at": "2026-08-21T10:00:00.000Z",
    "received_at": "2026-08-21T12:00:00.000Z",
}

_SECOND_ASSERTION: dict[str, Any] = dict(
    _ASSERTION,
    evidence_id="evidence-resolution-test",
    source_type="automated_test",
    source_id="resolution-test-runner",
    evidence_ref="tests/ticket-123/resolution",
    source_signature_ref="attestation-resolution-test",
)

_QUALIFICATION: dict[str, Any] = {
    "contract_version": "feedback-evidence-qualification/v0.1",
    "qualification_id": "qualification-ticket-resolved",
    "profile_id": "support-resolution",
    "profile_version": "1.0.0",
    "evidence_ids": ["evidence-ticket-closed"],
    "qualification_state": "QUALIFIED",
    "qualification": "independent",
    "qualifier_id": "support-outcome-qualifier",
    "qualifier_version": "1.0.0",
    "qualifier_signature_ref": "attestation-qualification-ticket-resolved",
    "reason_refs": ["reason/single-authorized-source/v1"],
    "decided_at": "2026-08-21T12:05:00.000Z",
}

_M2: dict[str, Any] = {
    "value": 1,
    "source_run_id": "run-support-001",
    "target_id": "ticket-123",
    "system_version": "support-agent-2026.08",
    "observation_window_id": "ticket-123-resolution-window",
    "evaluator_id": "support-belief-evaluator",
    "evaluator_version": "1.0.0",
}

_SUCCESS = ["MODEL_CALL", "TOOL_CALL", "TOOL_RESULT", "FINAL_OUTPUT"]
_RETRY = ["MODEL_CALL", "TOOL_CALL", "TOOL_CALL", "TOOL_RESULT"]


def _m1_chain(
    *,
    outcome: int = 1,
    usability: str = _USABLE,
    m2_overrides: dict[str, Any] | None = None,
    drop_evidence: bool = False,
) -> dict[str, Any]:
    """Produce M1 from supplied facts, then evaluate passive drift."""
    assertion = dict(_ASSERTION, outcome_value=outcome)
    qualification = dict(_QUALIFICATION)
    if drop_evidence:
        qualification["evidence_ids"] = [
            "evidence-ticket-closed",
            "evidence-resolution-test",
        ]
        qualification["qualification"] = "cross_verified"
    views = [
        EvidenceView(
            assertion=assertion,
            independence_domain_id="domain-tickets",
            usability=usability,
        )
    ]
    produced = produce_m1_observation(
        qualification=qualification,
        qualification_revocations=[],
        evidence_revocations=[],
        evidence=views,
        profile=_PROFILE,
        run=_RUN,
    )
    if produced.observation is None:
        return {
            "m1_produced": False,
            "reason_code": produced.reason_code,
            "drift": None,
        }
    m2 = dict(_M2, **(m2_overrides or {}))
    evaluation = evaluate_passive_drift(
        {
            "contract_version": "passive-drift-evaluation-input/v0.2",
            "evaluation_id": "evaluation-demo",
            "m1": produced.observation.to_passive_drift_m1(),
            "m2": m2,
        }
    ).to_dict()
    return {"m1_produced": True, "drift": evaluation}


def _m3_input(structures: list[list[str]]) -> dict[str, Any]:
    runs = []
    for index, events in enumerate(structures, start=1):
        day = f"2026-09-{index:02d}"
        runs.append(
            {
                "run_id": f"run-{index:02d}",
                "target_id": "target-alpha",
                "system_version": "2026.09.1",
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
        "target_id": "target-alpha",
        "system_version": "2026.09.1",
        "as_of": "2026-10-01T00:00:00.000Z",
        "runs": runs,
    }


def _scenarios() -> list[tuple[str, str, Callable[[], dict[str, Any]]]]:
    return [
        (
            "M1 = 1, M2 = 1",
            "Observed success matches the represented success.",
            lambda: _m1_chain(outcome=1),
        ),
        (
            "Observed failure M1 = 0, represented success M2 = 1",
            "Signed delta is negative; D is the magnitude.",
            lambda: _m1_chain(outcome=0),
        ),
        (
            "Referenced evidence is absent",
            "M1 abstains, so no D is computed.",
            lambda: _m1_chain(drop_evidence=True),
        ),
        (
            "Declared evidence integrity is invalid",
            "M1 abstains, so no D is computed.",
            lambda: _m1_chain(usability="INTEGRITY_VALIDATION_FAILED"),
        ),
        (
            "M1 and M2 refer to different system versions",
            "Not comparable: non-evaluable, no drift value.",
            lambda: _m1_chain(m2_overrides={"system_version": "other"}),
        ),
        (
            "M3: 10 runs, one event structure",
            "Behavioral stability is 1.",
            lambda: evaluate_m3_behavioral_stability(
                _m3_input([_SUCCESS] * 10)
            ),
        ),
        (
            "M3: 10 runs, two equally frequent structures",
            "Behavioral stability is 0.5.",
            lambda: evaluate_m3_behavioral_stability(
                _m3_input([_SUCCESS] * 5 + [_RETRY] * 5)
            ),
        ),
        (
            "M3: 9 runs",
            "Below the minimum evidence: non-evaluable, no value.",
            lambda: evaluate_m3_behavioral_stability(
                _m3_input([_SUCCESS] * 9)
            ),
        ),
        (
            "Repeat scenario 2 on identical inputs",
            "Identical result; no state is kept between calls.",
            lambda: {
                "identical": _m1_chain(outcome=0) == _m1_chain(outcome=0)
            },
        ),
    ]


def run_scenarios() -> list[dict[str, Any]]:
    """Run every scenario and return its name, note, and result."""
    return [
        {"scenario": index, "name": name, "note": note, "result": call()}
        for index, (name, note, call) in enumerate(_scenarios(), start=1)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the synthetic M1/M2 drift and M3 scenarios."
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
    print("Synthetic inputs; not a pipeline. See the module docstring.\n")
    for item in results:
        print(f"[{item['scenario']}] {item['name']}")
        print(f"    {item['note']}")
        print(f"    {json.dumps(item['result'], sort_keys=True)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
