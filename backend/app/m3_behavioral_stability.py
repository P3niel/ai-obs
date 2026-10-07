"""Deterministic M3 Behavioral Stability evaluator.

This module implements the M3 Behavioral Stability contract (v0.1). It is a
stateless, read-only pure
function of one explicit input. It never reads the clock, interprets payloads,
persists state, derives records from canonical runs, computes Stability,
classifies health, or produces Confidence.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import re
from typing import Any
from typing import Mapping

import rfc8785


INPUT_CONTRACT_VERSION = "m3-behavioral-stability-input/v0.1"
OUTPUT_CONTRACT_VERSION = "m3-behavioral-stability-output/v0.1"
ERROR_CONTRACT_VERSION = "m3-behavioral-stability-error/v0.1"

WINDOW_SIZE = 50
MINIMUM_RUNS = 10

SUPPORTED_EVENT_TYPES = frozenset(
    {
        "MODEL_CALL",
        "TOOL_CALL",
        "TOOL_RESULT",
        "MEMORY_READ",
        "MEMORY_WRITE",
        "ERROR",
        "FINAL_OUTPUT",
    }
)
EXCLUSION_REASONS = (
    "NOT_COMPARABLE",
    "RUN_NOT_ENDED",
    "RUN_AFTER_AS_OF",
    "NO_EVENTS",
    "UNSUPPORTED_EVENT_TYPE",
)
ERROR_CODE_ORDER = (
    "INVALID_INPUT",
    "INVALID_CONTRACT_VERSION",
    "UNKNOWN_FIELD",
    "INVALID_EVALUATION_ID",
    "INVALID_COHORT",
    "INVALID_AS_OF",
    "INVALID_RUNS",
    "INVALID_RUN_RECORD",
    "DUPLICATE_RUN_ID",
)

_INPUT_FIELDS = frozenset(
    {
        "contract_version",
        "evaluation_id",
        "target_id",
        "system_version",
        "as_of",
        "runs",
    }
)
_RUN_FIELDS = frozenset(
    {
        "run_id",
        "target_id",
        "system_version",
        "run_start_timestamp",
        "run_end_timestamp",
        "events",
    }
)
_EVENT_FIELDS = frozenset({"timestamp", "event_type"})
_TIMESTAMP_SHAPE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"
)
_BARE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class M3ContractInputError(ValueError):
    """Raised when the input violates the M3 input contract.

    Carries every detected error as ordered ``(code, field_path)`` pairs; no
    evaluation result exists for an invalid input.
    """

    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__(
            "invalid M3 input: "
            + ", ".join(f"{e['code']}@{e['field_path']}" for e in errors)
        )
        self.errors = errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": ERROR_CONTRACT_VERSION,
            "errors": [dict(error) for error in self.errors],
        }


def evaluate_m3_behavioral_stability(
    payload: Any,
) -> dict[str, Any]:
    """Evaluate one M3 input; raise ``M3ContractInputError`` if invalid.

    The input is never mutated and no field is repaired, dropped, or coerced.
    """
    errors = _contract_errors(payload)
    if errors:
        raise M3ContractInputError(errors)
    return _evaluate(payload)


def _property_path(parent: str, name: str) -> str:
    if _BARE_NAME.fullmatch(name):
        return name if parent == "" else f"{parent}.{name}"
    return f"{parent or '$'}[{_json_string(name)}]"


def _json_string(value: str) -> str:
    out = ['"']
    for char in value:
        code = ord(char)
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif char == "\b":
            out.append("\\b")
        elif char == "\f":
            out.append("\\f")
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        elif code < 0x20 or code > 0x7E:
            if code > 0xFFFF:
                code -= 0x10000
                out.append(f"\\u{0xD800 + (code >> 10):04x}")
                out.append(f"\\u{0xDC00 + (code & 0x3FF):04x}")
            else:
                out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _valid_run_id(value: Any) -> bool:
    # A run_id enters the canonical (RFC 8785) digest, which cannot encode an
    # unpaired surrogate; such a string is not valid Unicode, so reject it
    # during validation instead of failing at digest time.
    if not _valid_id(value):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not _TIMESTAMP_SHAPE.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return False
    return True


def _contract_errors(payload: Any) -> list[dict[str, str]]:
    if not isinstance(payload, Mapping):
        return [{"code": "INVALID_INPUT", "field_path": "$"}]
    found: set[tuple[str, str]] = set()
    for key in payload:
        if key not in _INPUT_FIELDS:
            found.add(("UNKNOWN_FIELD", _property_path("", str(key))))
    if payload.get("contract_version") != INPUT_CONTRACT_VERSION:
        found.add(("INVALID_CONTRACT_VERSION", "contract_version"))
    if not _valid_id(payload.get("evaluation_id")):
        found.add(("INVALID_EVALUATION_ID", "evaluation_id"))
    for name in ("target_id", "system_version"):
        if not _valid_id(payload.get(name)):
            found.add(("INVALID_COHORT", name))
    if not _valid_timestamp(payload.get("as_of")):
        found.add(("INVALID_AS_OF", "as_of"))
    runs = payload.get("runs")
    if not isinstance(runs, list):
        found.add(("INVALID_RUNS", "runs"))
        runs = []
    seen: set[str] = set()
    for index, run in enumerate(runs):
        _run_errors(index, run, seen, found)
    ordered = sorted(
        found,
        key=lambda item: (
            ERROR_CODE_ORDER.index(item[0]),
            item[1].encode("utf-8"),
        ),
    )
    return [{"code": code, "field_path": path} for code, path in ordered]


def _run_errors(
    index: int,
    run: Any,
    seen: set[str],
    found: set[tuple[str, str]],
) -> None:
    base = f"runs[{index}]"
    if not isinstance(run, Mapping):
        found.add(("INVALID_RUN_RECORD", base))
        return
    for key in run:
        if key not in _RUN_FIELDS:
            found.add(("UNKNOWN_FIELD", _property_path(base, str(key))))
    if not _valid_run_id(run.get("run_id")):
        found.add(("INVALID_RUN_RECORD", f"{base}.run_id"))
    for name in ("target_id", "system_version"):
        if not _valid_id(run.get(name)):
            found.add(("INVALID_RUN_RECORD", f"{base}.{name}"))
    start_ok = _valid_timestamp(run.get("run_start_timestamp"))
    if not start_ok:
        found.add(("INVALID_RUN_RECORD", f"{base}.run_start_timestamp"))
    if "run_end_timestamp" in run:
        end = run["run_end_timestamp"]
        if not _valid_timestamp(end):
            found.add(("INVALID_RUN_RECORD", f"{base}.run_end_timestamp"))
        elif start_ok and end < run["run_start_timestamp"]:
            found.add(("INVALID_RUN_RECORD", f"{base}.run_end_timestamp"))
    events = run.get("events")
    if not isinstance(events, list):
        found.add(("INVALID_RUN_RECORD", f"{base}.events"))
        events = []
    for position, event in enumerate(events):
        where = f"{base}.events[{position}]"
        if not isinstance(event, Mapping):
            found.add(("INVALID_RUN_RECORD", where))
            continue
        for key in event:
            if key not in _EVENT_FIELDS:
                found.add(("UNKNOWN_FIELD", _property_path(where, str(key))))
        if not _valid_timestamp(event.get("timestamp")):
            found.add(("INVALID_RUN_RECORD", f"{where}.timestamp"))
        if not _valid_id(event.get("event_type")):
            found.add(("INVALID_RUN_RECORD", f"{where}.event_type"))
    run_id = run.get("run_id")
    if isinstance(run_id, str) and _valid_run_id(run_id):
        if run_id in seen:
            found.add(("DUPLICATE_RUN_ID", f"{base}.run_id"))
        seen.add(run_id)


def _exclusion_reason(
    run: Mapping[str, Any], payload: Mapping[str, Any]
) -> str | None:
    if (
        run["target_id"] != payload["target_id"]
        or run["system_version"] != payload["system_version"]
    ):
        return "NOT_COMPARABLE"
    if "run_end_timestamp" not in run:
        return "RUN_NOT_ENDED"
    if run["run_end_timestamp"] > payload["as_of"]:
        return "RUN_AFTER_AS_OF"
    if not run["events"]:
        return "NO_EVENTS"
    if any(
        e["event_type"] not in SUPPORTED_EVENT_TYPES for e in run["events"]
    ):
        return "UNSUPPORTED_EVENT_TYPE"
    return None


def _evaluate(payload: Mapping[str, Any]) -> dict[str, Any]:
    counts = {reason: 0 for reason in EXCLUSION_REASONS}
    eligible: list[tuple[str, str, tuple[str, ...]]] = []
    for run in payload["runs"]:
        reason = _exclusion_reason(run, payload)
        if reason is not None:
            counts[reason] += 1
            continue
        events = sorted(
            run["events"], key=lambda e: (e["timestamp"], e["event_type"])
        )
        eligible.append(
            (
                run["run_end_timestamp"],
                run["run_id"],
                tuple(e["event_type"] for e in events),
            )
        )
    eligible.sort(key=lambda item: (item[0], item[1]))
    selected = eligible[-WINDOW_SIZE:]
    result: dict[str, Any] = {
        "contract_version": OUTPUT_CONTRACT_VERSION,
        "evaluation_id": payload["evaluation_id"],
        "evaluable": len(selected) >= MINIMUM_RUNS,
        "target_id": payload["target_id"],
        "system_version": payload["system_version"],
        "as_of": payload["as_of"],
        "window_size": WINDOW_SIZE,
        "minimum_runs": MINIMUM_RUNS,
        "eligible_run_count": len(eligible),
        "sample_count": len(selected),
        "exclusion_counts": counts,
    }
    if not result["evaluable"]:
        result["non_evaluable_reasons"] = [
            {"code": "INSUFFICIENT_COMPARABLE_RUNS", "field": "sample_count"}
        ]
        return result
    tally: dict[tuple[str, ...], int] = {}
    for _, _, signature in selected:
        tally[signature] = tally.get(signature, 0) + 1
    modal = max(tally.values())
    result["modal_signature_count"] = modal
    result["m3"] = modal / len(selected)
    result["window_start"] = selected[0][0]
    result["window_end"] = selected[-1][0]
    result["selected_run_digest"] = hashlib.sha256(
        rfc8785.dumps([item[1] for item in selected])
    ).hexdigest()
    return result
