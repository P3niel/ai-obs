"""Shared payload-coercion helpers for Kernel-derived run payloads.

These are pure, exception-free value-coercion primitives used by modules
that read ``KernelRun.to_dict()``-shaped payloads (or equivalent mappings)
and need to safely extract optional text, optional numbers, mappings, and
sequences of mappings, or deep-copy a JSON-like structure.

Domain-specific required-field validation (which raises each module's own
error type with its own message) intentionally stays local to each module;
this module only centralizes the coercion logic that was previously
copy-pasted verbatim, character-for-character, across
``operational_observability.py``, ``run_comparison.py``, ``replay.py``, and
``canonical_mapping.py`` (P3N-111).
"""

from __future__ import annotations

from typing import Any
from typing import Mapping
from typing import Sequence


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def optional_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def sequence_of_mappings(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def copy_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): copy_value(item)
        for key, item in value.items()
    }


def copy_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return copy_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [copy_value(item) for item in value]
    return value
