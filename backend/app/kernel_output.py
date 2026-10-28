"""Deterministic, read-only Kernel output assembler.

This module implements the Kernel Output contract v0.1. It is a stateless
pure function of one explicit input: the passive drift result, the M3 result,
and the projection of the evaluated run. It assembles the non-authoritative
``{drift, bias, stability, status}`` output of the Kernel contract. It never
recomputes M1, M2, drift or M3, reads the clock, persists, transmits or acts.

Shapes are validated by hand against a closed schema. Non-finite numbers are
rejected here although JSON cannot carry them.
"""

from __future__ import annotations

from datetime import datetime
import math
import re
from typing import Any
from typing import Mapping


INPUT_CONTRACT_VERSION = "kernel-output-input/v0.1"
OUTPUT_CONTRACT_VERSION = "kernel-output/v0.1"
ERROR_CONTRACT_VERSION = "kernel-output-error/v0.1"

DRIFT_OUTPUT_VERSION = "passive-drift-evaluation-output/v0.2"
M3_OUTPUT_VERSION = "m3-behavioral-stability-output/v0.1"

WARNING_FLOOR = 0.10
CRITICAL_FLOOR = 0.30
HEALTHY_STABILITY_FLOOR = 0.50

_INPUT_FIELDS = frozenset(
    {
        "contract_version",
        "evaluation_id",
        "drift_result",
        "m3_result",
        "evaluated_run",
    }
)
_ERROR_CODE_ORDER = (
    "INVALID_INPUT",
    "INVALID_CONTRACT_VERSION",
    "UNKNOWN_FIELD",
    "INVALID_EVALUATION_ID",
    "INVALID_DRIFT_RESULT",
    "INVALID_M3_RESULT",
    "INVALID_EVALUATED_RUN",
)
_TIMESTAMP_SHAPE = re.compile(
    r"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
    r"T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{3}Z$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BARE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_QUALIFICATIONS = frozenset({"independent", "cross_verified"})
_EXCLUSION_KEYS = frozenset(
    {
        "NOT_COMPARABLE",
        "RUN_NOT_ENDED",
        "RUN_AFTER_AS_OF",
        "NO_EVENTS",
        "UNSUPPORTED_EVENT_TYPE",
    }
)


class KernelOutputContractInputError(ValueError):
    """Raised when the input violates the Kernel Output input contract.

    Carries every detected error as ordered ``(code, field_path)`` pairs; no
    output exists for an invalid input.
    """

    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__(
            "invalid Kernel output input: "
            + ", ".join(f"{e['code']}@{e['field_path']}" for e in errors)
        )
        self.errors = errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": ERROR_CONTRACT_VERSION,
            "errors": [dict(error) for error in self.errors],
        }


def assemble_kernel_output(payload: Any) -> dict[str, Any]:
    """Assemble one Kernel output; raise ``KernelOutputContractInputError``.

    The input is never mutated and no field is repaired, dropped, or coerced.
    """
    errors = _contract_errors(payload)
    if errors:
        raise KernelOutputContractInputError(errors)
    return _assemble(payload)


def _assemble(payload: Mapping[str, Any]) -> dict[str, Any]:
    drift = payload["drift_result"]
    m3 = payload["m3_result"]
    run = payload["evaluated_run"]
    out: dict[str, Any] = {
        "contract_version": OUTPUT_CONTRACT_VERSION,
        "evaluation_id": payload["evaluation_id"],
        "authoritative": False,
        "as_of": m3["as_of"],
    }
    if not drift["evaluable"]:
        reason = {"code": "DRIFT_NOT_EVALUABLE", "field": "drift"}
        out["drift"] = {
            "evaluable": False,
            "reasons": [dict(r) for r in drift["non_evaluable_reasons"]],
        }
        out["bias"] = {"evaluable": False, "reasons": [dict(reason)]}
        out["stability"] = {"evaluable": False, "reasons": [dict(reason)]}
        out["status"] = "unclassified"
        out["status_reasons"] = [dict(reason)]
        return out

    d = drift["drift"]
    out["drift"] = {
        "evaluable": True,
        "value": d,
        "source_run_id": drift["source_run_id"],
        "target_id": drift["target_id"],
        "system_version": drift["system_version"],
        "observation_window_id": drift["observation_window_id"],
    }
    out["bias"] = {"evaluable": True, "value": d, "derived_from": "drift"}

    unavailable = _stability_unavailable_reasons(drift, m3, run)
    stability: float | None = None
    if unavailable:
        out["stability"] = {"evaluable": False, "reasons": unavailable}
    else:
        stability = m3["m3"] - d
        out["stability"] = {
            "evaluable": True,
            "value": stability,
            "m3": m3["m3"],
        }

    status_reasons: list[dict[str, str]] = []
    if d >= CRITICAL_FLOOR:
        status = "critical"
    elif d >= WARNING_FLOOR:
        status = "warning"
    elif stability is None:
        status = "unclassified"
        status_reasons = [
            {"code": "STABILITY_UNAVAILABLE", "field": "stability"}
        ]
    elif stability > HEALTHY_STABILITY_FLOOR:
        status = "healthy"
    else:
        status = "unclassified"
        status_reasons = [
            {"code": "HEALTH_REGION_UNDEFINED", "field": "stability"}
        ]
    out["status"] = status
    out["status_reasons"] = status_reasons
    return out


def _stability_unavailable_reasons(
    drift: Mapping[str, Any],
    m3: Mapping[str, Any],
    run: Mapping[str, Any],
) -> list[dict[str, str]]:
    not_comparable = "INPUT_NOT_COMPARABLE"
    reasons: list[dict[str, str]] = []
    if drift["source_run_id"] != run["run_id"]:
        reasons.append({"code": not_comparable, "field": "source_run_id"})
    if not drift["target_id"] == m3["target_id"] == run["target_id"]:
        reasons.append({"code": not_comparable, "field": "target_id"})
    if not drift["system_version"] == m3["system_version"] == (
        run["system_version"]
    ):
        reasons.append({"code": not_comparable, "field": "system_version"})
    if not m3["evaluable"]:
        reasons.append({"code": "M3_NOT_EVALUABLE", "field": "m3_result"})
    if "run_end_timestamp" not in run:
        reasons.append({"code": not_comparable, "field": "run_end_timestamp"})
    elif run["run_end_timestamp"] > m3["as_of"]:
        reasons.append({"code": not_comparable, "field": "as_of"})
    return reasons


def _property_path(name: str) -> str:
    if _BARE_NAME.fullmatch(name):
        return name
    return f"$[{_json_string(name)}]"


def _json_string(value: str) -> str:
    escapes = {
        '"': '\\"',
        "\\": "\\\\",
        "\b": "\\b",
        "\f": "\\f",
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
    }
    out = ['"']
    for char in value:
        code = ord(char)
        if char in escapes:
            out.append(escapes[char])
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


def _contract_errors(payload: Any) -> list[dict[str, str]]:
    if not isinstance(payload, Mapping):
        return [{"code": "INVALID_INPUT", "field_path": "$"}]
    found: set[tuple[str, str]] = set()
    for key in payload:
        if key not in _INPUT_FIELDS:
            found.add(("UNKNOWN_FIELD", _property_path(str(key))))
    if payload.get("contract_version") != INPUT_CONTRACT_VERSION:
        found.add(("INVALID_CONTRACT_VERSION", "contract_version"))
    if not _non_empty(payload.get("evaluation_id")):
        found.add(("INVALID_EVALUATION_ID", "evaluation_id"))
    if not _drift_result_valid(payload.get("drift_result")):
        found.add(("INVALID_DRIFT_RESULT", "drift_result"))
    if not _m3_result_valid(payload.get("m3_result")):
        found.add(("INVALID_M3_RESULT", "m3_result"))
    if not _run_valid(payload.get("evaluated_run")):
        found.add(("INVALID_EVALUATED_RUN", "evaluated_run"))
    ordered = sorted(
        found,
        key=lambda item: (
            _ERROR_CODE_ORDER.index(item[0]),
            item[1].encode("utf-8"),
        ),
    )
    return [{"code": code, "field_path": path} for code, path in ordered]


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _number(value: Any, low: float, high: float) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    # Finiteness is checked for floats only: math.isfinite() converts an int
    # to a float and raises OverflowError for an arbitrarily large integer,
    # which the range check below rejects exactly.
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return low <= value <= high


def _integer(value: Any, low: int, high: int | None = None) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, float):
        if not value.is_integer():
            return False
    elif not isinstance(value, int):
        return False
    return value >= low and (high is None or value <= high)


def _timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not _TIMESTAMP_SHAPE.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return False
    return True


def _closed(
    value: Any,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> bool:
    if not isinstance(value, Mapping):
        return False
    keys = set(value)
    return required <= keys <= required | optional


def _drift_result_valid(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("contract_version") != DRIFT_OUTPUT_VERSION:
        return False
    if not _non_empty(value.get("evaluation_id")):
        return False
    evaluable = value.get("evaluable")
    if evaluable is False:
        return _drift_non_evaluable_valid(value)
    if evaluable is True:
        return _drift_evaluable_valid(value)
    return False


def _drift_non_evaluable_valid(value: Mapping[str, Any]) -> bool:
    required = frozenset(
        {
            "contract_version",
            "evaluation_id",
            "evaluable",
            "non_evaluable_reasons",
        }
    )
    if not _closed(value, required):
        return False
    reasons = value["non_evaluable_reasons"]
    return (
        isinstance(reasons, list)
        and len(reasons) >= 1
        and all(
            _closed(item, frozenset({"field", "detail"}))
            and _non_empty(item["field"])
            and _non_empty(item["detail"])
            for item in reasons
        )
    )


def _drift_evaluable_valid(value: Mapping[str, Any]) -> bool:
    required = frozenset(
        {
            "contract_version",
            "evaluation_id",
            "evaluable",
            "source_run_id",
            "target_id",
            "system_version",
            "observation_window_id",
            "m1",
            "m2",
            "drift",
            "signed_delta",
        }
    )
    if not _closed(value, required):
        return False
    if not all(
        _non_empty(value[name])
        for name in (
            "source_run_id",
            "target_id",
            "system_version",
            "observation_window_id",
        )
    ):
        return False
    m1 = value["m1"]
    m2 = value["m2"]
    if not _closed(
        m1, frozenset({"value", "evidence_ref", "qualification"})
    ) or not _closed(
        m2, frozenset({"value", "evaluator_id", "evaluator_version"})
    ):
        return False
    if not (
        _number(m1["value"], 0, 1)
        and _non_empty(m1["evidence_ref"])
        and isinstance(m1["qualification"], str)
        and m1["qualification"] in _QUALIFICATIONS
        and _number(m2["value"], 0, 1)
        and _non_empty(m2["evaluator_id"])
        and _non_empty(m2["evaluator_version"])
        and _number(value["drift"], 0, 1)
        and _number(value["signed_delta"], -1, 1)
    ):
        return False
    return bool(
        value["drift"] == abs(m1["value"] - m2["value"])
        and value["signed_delta"] == m1["value"] - m2["value"]
    )


def _m3_result_valid(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("contract_version") != M3_OUTPUT_VERSION:
        return False
    evaluable = value.get("evaluable")
    if evaluable is True:
        return _m3_evaluable_valid(value)
    if evaluable is False:
        return _m3_non_evaluable_valid(value)
    return False


_M3_COMMON = frozenset(
    {
        "contract_version",
        "evaluation_id",
        "evaluable",
        "target_id",
        "system_version",
        "as_of",
        "window_size",
        "minimum_runs",
        "eligible_run_count",
        "sample_count",
        "exclusion_counts",
    }
)


def _m3_common_valid(value: Mapping[str, Any]) -> bool:
    counts = value["exclusion_counts"]
    return bool(
        _non_empty(value["evaluation_id"])
        and _non_empty(value["target_id"])
        and _non_empty(value["system_version"])
        and _timestamp(value["as_of"])
        and _integer(value["window_size"], 50, 50)
        and _integer(value["minimum_runs"], 10, 10)
        and _closed(counts, _EXCLUSION_KEYS)
        and all(_integer(counts[key], 0) for key in _EXCLUSION_KEYS)
    )


def _m3_evaluable_valid(value: Mapping[str, Any]) -> bool:
    required = _M3_COMMON | {
        "modal_signature_count",
        "m3",
        "window_start",
        "window_end",
        "selected_run_digest",
    }
    if not _closed(value, frozenset(required)):
        return False
    if not _m3_common_valid(value):
        return False
    sample = value["sample_count"]
    modal = value["modal_signature_count"]
    if not (
        _integer(value["eligible_run_count"], 10)
        and _integer(sample, 10, 50)
        and _integer(modal, 1)
        and _number(value["m3"], 0, 1)
        and _timestamp(value["window_start"])
        and _timestamp(value["window_end"])
        and isinstance(value["selected_run_digest"], str)
        and _SHA256.fullmatch(value["selected_run_digest"]) is not None
    ):
        return False
    return bool(modal <= sample and value["m3"] == modal / sample)


def _m3_non_evaluable_valid(value: Mapping[str, Any]) -> bool:
    required = _M3_COMMON | {"non_evaluable_reasons"}
    if not _closed(value, frozenset(required)):
        return False
    if not _m3_common_valid(value):
        return False
    reasons = value["non_evaluable_reasons"]
    return bool(
        _integer(value["eligible_run_count"], 0, 9)
        and _integer(value["sample_count"], 0, 9)
        and isinstance(reasons, list)
        and len(reasons) == 1
        and _closed(reasons[0], frozenset({"code", "field"}))
        and reasons[0]["code"] == "INSUFFICIENT_COMPARABLE_RUNS"
        and reasons[0]["field"] == "sample_count"
    )


def _run_valid(value: Any) -> bool:
    if not _closed(
        value,
        frozenset({"run_id", "target_id", "system_version"}),
        frozenset({"run_end_timestamp"}),
    ):
        return False
    if not all(
        _non_empty(value[name])
        for name in ("run_id", "target_id", "system_version")
    ):
        return False
    try:
        value["run_id"].encode("utf-8")
    except UnicodeEncodeError:
        return False
    return (
        "run_end_timestamp" not in value
        or _timestamp(value["run_end_timestamp"])
    )
