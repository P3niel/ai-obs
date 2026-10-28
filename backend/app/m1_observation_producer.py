"""Deterministic qualified M1 observation producer.

This module implements the feedback/evaluation contract (v0.1). It is a pure
function over caller-supplied,
already-resolved facts: it reads one terminal ``EvidenceQualification``, its
revocations, and the permitted provenance of the referenced assertions. It
emits at most one immutable binary ``M1Observation``.

It does not read raw evidence, verify digests or signatures, qualify or weight
sources, resolve contradictions, persist state, or perform any I/O. Anything
missing, ambiguous, revoked, or unusable produces no M1 and a machine-readable
reason; no value is ever substituted or inferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import re
from typing import Any
from typing import Mapping
from typing import Sequence


M1_CONTRACT_VERSION = "m1-observation/v0.1"
M1_ID_PREFIX = "m1-"

_QUALIFICATION_VERSION = "feedback-evidence-qualification/v0.1"
_QUALIFICATION_REVOCATION_VERSION = (
    "feedback-evidence-qualification-revocation/v0.1"
)
_EVIDENCE_REVOCATION_VERSION = "feedback-evidence-revocation/v0.1"
_ASSERTION_VERSION = "feedback-evidence-assertion/v0.1"

_COMPARABILITY_FIELDS = (
    "source_run_id",
    "target_id",
    "system_version",
    "observation_window_id",
)

_QUALIFICATION_KEYS = frozenset(
    {
        "contract_version",
        "qualification_id",
        "profile_id",
        "profile_version",
        "evidence_ids",
        "qualification_state",
        "qualification",
        "qualifier_id",
        "qualifier_version",
        "qualifier_signature_ref",
        "reason_refs",
        "decided_at",
    }
)
_ASSERTION_KEYS = frozenset(
    {
        "contract_version",
        "evidence_id",
        "evidence_version",
        "profile_id",
        "profile_version",
        "source_type",
        "source_id",
        "source_version",
        "source_run_id",
        "target_id",
        "system_version",
        "observation_window_id",
        "outcome_value",
        "evidence_store_id",
        "evidence_store_version",
        "evidence_ref",
        "digest_algorithm",
        "content_digest",
        "source_signature_ref",
        "adapter_attestation_ref",
        "observed_at",
        "received_at",
    }
)
_ASSERTION_OPTIONAL_KEYS = frozenset(
    {"source_signature_ref", "adapter_attestation_ref"}
)
_QUALIFICATION_REVOCATION_KEYS = frozenset(
    {
        "contract_version",
        "revocation_id",
        "qualification_id",
        "authority_id",
        "reason_ref",
        "authority_signature_ref",
        "revoked_at",
    }
)
_EVIDENCE_REVOCATION_KEYS = frozenset(
    {
        "contract_version",
        "revocation_id",
        "evidence_id",
        "evidence_version",
        "authority_id",
        "reason_ref",
        "authority_signature_ref",
        "revoked_at",
    }
)
_PROFILE_REQUIRED_KEYS = (
    "profile_id",
    "profile_version",
    "authorized_source_types",
    "authorized_evidence_stores",
    "authorized_qualifier_refs",
)
_MODES = frozenset({"independent", "cross_verified"})
_SOURCE_TYPES = frozenset(
    {
        "user_feedback",
        "business_outcome",
        "external_validation",
        "human_adjudication",
        "automated_test",
        "llm_evaluator",
    }
)
# Never sufficient alone (owner decision 2026-08-21), so they cannot back an
# ``independent`` qualification.
_NOT_SUFFICIENT_ALONE = frozenset({"user_feedback", "llm_evaluator"})
_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)

USABILITY_USABLE = "USABLE"
# Resolved by the derived current view; the producer cannot verify these
# because it has no raw-evidence or key-registry access.
_UNUSABLE_USABILITY = frozenset(
    {
        "EVIDENCE_UNAVAILABLE",
        "INTEGRITY_VALIDATION_FAILED",
        "KEY_COMPROMISED",
    }
)

# Reason codes. The first group reuses stable contract error codes; the rest
# are module-local abstention reasons and are not contract error codes.
REASON_INVALID_INPUT = "INVALID_INPUT"
REASON_DUPLICATE_ID_CONFLICT = "DUPLICATE_ID_CONFLICT"
REASON_TARGET_MISMATCH = "TARGET_MISMATCH"
REASON_UNAUTHORIZED_SOURCE = "UNAUTHORIZED_SOURCE"
REASON_EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
REASON_INTEGRITY_FAILED = "INTEGRITY_VALIDATION_FAILED"
REASON_PROFILE_NOT_DECLARED = "PROFILE_NOT_DECLARED"
REASON_PROFILE_MISMATCH = "PROFILE_MISMATCH"
REASON_NOT_QUALIFIED = "NOT_QUALIFIED"
REASON_QUALIFICATION_REVOKED = "QUALIFICATION_REVOKED"
REASON_UNAUTHORIZED_QUALIFIER = "UNAUTHORIZED_QUALIFIER"
REASON_EVIDENCE_SET_INVALID = "EVIDENCE_SET_INVALID"
REASON_EVIDENCE_MISSING = "EVIDENCE_MISSING"
REASON_EVIDENCE_REVOKED = "EVIDENCE_REVOKED"
REASON_KEY_COMPROMISED = "KEY_COMPROMISED"
REASON_AUTHENTICITY_MISSING = "AUTHENTICITY_MISSING"
REASON_INDEPENDENCE_VIOLATION = "INDEPENDENCE_VIOLATION"
REASON_OUTCOME_CONFLICT = "OUTCOME_CONFLICT"


@dataclass(frozen=True)
class EvidenceView:
    """Permitted provenance for one referenced assertion.

    ``usability`` is the already-resolved current-view status of availability,
    integrity, and signing-key trust. ``independence_domain_id`` is the
    registered domain of the assertion's source.
    """

    assertion: Mapping[str, Any]
    independence_domain_id: str
    usability: str


@dataclass(frozen=True)
class M1ObservationPayload:
    m1_observation_id: str
    profile_id: str
    profile_version: str
    value: int
    source_run_id: str
    target_id: str
    system_version: str
    observation_window_id: str
    evidence_ref: str
    qualification: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": M1_CONTRACT_VERSION,
            "m1_observation_id": self.m1_observation_id,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "value": self.value,
            "source_run_id": self.source_run_id,
            "target_id": self.target_id,
            "system_version": self.system_version,
            "observation_window_id": self.observation_window_id,
            "evidence_ref": self.evidence_ref,
            "qualification": self.qualification,
        }

    def to_passive_drift_m1(self) -> dict[str, Any]:
        """Return the ``m1`` mapping accepted by passive drift evaluation."""
        return {
            "value": self.value,
            "source_run_id": self.source_run_id,
            "target_id": self.target_id,
            "system_version": self.system_version,
            "observation_window_id": self.observation_window_id,
            "evidence_ref": self.evidence_ref,
            "qualification": self.qualification,
        }


@dataclass(frozen=True)
class M1ProductionResult:
    observation: M1ObservationPayload | None
    reason_code: str | None = None
    field_path: str | None = None
    idempotent_replay: bool = False

    @property
    def produced(self) -> bool:
        return self.observation is not None


class _Abstain(Exception):
    def __init__(self, reason_code: str, field_path: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.field_path = field_path


def derive_m1_observation_id(qualification_id: str) -> str:
    """Return the replay-stable M1 identity for one qualification identity."""
    digest = hashlib.sha256(qualification_id.encode("utf-8")).hexdigest()
    return M1_ID_PREFIX + digest


def produce_m1_observation(
    *,
    qualification: Mapping[str, Any],
    qualification_revocations: Sequence[Mapping[str, Any]],
    evidence_revocations: Sequence[Mapping[str, Any]],
    evidence: Sequence[EvidenceView],
    profile: Mapping[str, Any],
    run: Mapping[str, Any],
    existing_m1: Mapping[str, Any] | None = None,
) -> M1ProductionResult:
    """Emit one binary ``M1Observation`` or abstain with a reason.

    ``run`` carries the four comparability identifiers plus the frozen
    ``evaluation_profile_id`` / ``evaluation_profile_version`` pair.
    ``existing_m1`` is the already-persisted M1 for the same qualification, if
    any, used only for idempotency and identity-conflict decisions.
    Inputs are never mutated.
    """
    try:
        return _produce(
            qualification,
            qualification_revocations,
            evidence_revocations,
            evidence,
            profile,
            run,
            existing_m1,
        )
    except _Abstain as abstention:
        return M1ProductionResult(
            observation=None,
            reason_code=abstention.reason_code,
            field_path=abstention.field_path,
        )


def _produce(
    qualification: Mapping[str, Any],
    qualification_revocations: Sequence[Mapping[str, Any]],
    evidence_revocations: Sequence[Mapping[str, Any]],
    evidence: Sequence[EvidenceView],
    profile: Mapping[str, Any],
    run: Mapping[str, Any],
    existing_m1: Mapping[str, Any] | None,
) -> M1ProductionResult:
    decision = _validate_qualification(qualification)
    _validate_profile(profile)
    run_ids = _validate_run(run)

    # Profile binding: run pair, profile, and decision must agree exactly.
    if (
        decision["profile_id"] != profile["profile_id"]
        or decision["profile_version"] != profile["profile_version"]
        or decision["profile_id"] != run["evaluation_profile_id"]
        or decision["profile_version"] != run["evaluation_profile_version"]
    ):
        raise _Abstain(REASON_PROFILE_MISMATCH, "/profile_id")

    if decision["qualification_state"] != "QUALIFIED":
        raise _Abstain(REASON_NOT_QUALIFIED, "/qualification_state")

    if _qualification_revoked(
        qualification_revocations, decision["qualification_id"]
    ):
        raise _Abstain(REASON_QUALIFICATION_REVOKED, "/qualification_id")

    if decision["qualifier_id"] not in profile["authorized_qualifier_refs"]:
        raise _Abstain(REASON_UNAUTHORIZED_QUALIFIER, "/qualifier_id")

    views = _select_evidence(decision, evidence)
    revoked = _revoked_evidence(evidence_revocations)
    value = _check_evidence(
        decision, views, revoked, profile, run, run_ids
    )

    observation = M1ObservationPayload(
        m1_observation_id=derive_m1_observation_id(
            decision["qualification_id"]
        ),
        profile_id=decision["profile_id"],
        profile_version=decision["profile_version"],
        value=value,
        source_run_id=run_ids["source_run_id"],
        target_id=run_ids["target_id"],
        system_version=run_ids["system_version"],
        observation_window_id=run_ids["observation_window_id"],
        evidence_ref=decision["qualification_id"],
        qualification=decision["qualification"],
    )
    return _apply_idempotency(observation, existing_m1)


def _apply_idempotency(
    observation: M1ObservationPayload,
    existing_m1: Mapping[str, Any] | None,
) -> M1ProductionResult:
    if existing_m1 is None:
        return M1ProductionResult(observation=observation)
    if not isinstance(existing_m1, Mapping):
        raise _Abstain(REASON_INVALID_INPUT, "/existing_m1")
    same_identity = (
        existing_m1.get("m1_observation_id") == observation.m1_observation_id
    )
    same_qualification = (
        existing_m1.get("evidence_ref") == observation.evidence_ref
    )
    if not same_identity and not same_qualification:
        return M1ProductionResult(observation=observation)
    if dict(existing_m1) == observation.to_dict():
        return M1ProductionResult(
            observation=observation, idempotent_replay=True
        )
    raise _Abstain(REASON_DUPLICATE_ID_CONFLICT, "/existing_m1")


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _Abstain(REASON_INVALID_INPUT, path)
    return value


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _Abstain(REASON_INVALID_INPUT, path)
    return value


def _text_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value:
        raise _Abstain(REASON_INVALID_INPUT, path)
    items = [
        _text(item, f"{path}/{index}") for index, item in enumerate(value)
    ]
    if len(set(items)) != len(items):
        raise _Abstain(REASON_INVALID_INPUT, path)
    return items


def _timestamp(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _TIMESTAMP.match(value):
        raise _Abstain(REASON_INVALID_INPUT, path)
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        raise _Abstain(REASON_INVALID_INPUT, path) from None
    return value


def _validate_qualification(
    qualification: Mapping[str, Any],
) -> dict[str, Any]:
    body = _mapping(qualification, "/qualification")
    if set(body) - _QUALIFICATION_KEYS:
        raise _Abstain(REASON_INVALID_INPUT, "/qualification")
    if body.get("contract_version") != _QUALIFICATION_VERSION:
        raise _Abstain(REASON_INVALID_INPUT, "/contract_version")
    decision: dict[str, Any] = {}
    for key in (
        "qualification_id",
        "profile_id",
        "profile_version",
        "qualifier_id",
        "qualifier_version",
        "qualifier_signature_ref",
    ):
        decision[key] = _text(body.get(key), f"/{key}")
    decision["evidence_ids"] = _text_list(
        body.get("evidence_ids"), "/evidence_ids"
    )
    _text_list(body.get("reason_refs"), "/reason_refs")
    _timestamp(body.get("decided_at"), "/decided_at")

    state = body.get("qualification_state")
    if not isinstance(state, str) or state not in (
        "QUALIFIED",
        "REJECTED",
        "CONFLICTED",
    ):
        raise _Abstain(REASON_INVALID_INPUT, "/qualification_state")
    decision["qualification_state"] = state
    mode = body.get("qualification")
    if state == "QUALIFIED":
        if not isinstance(mode, str) or mode not in _MODES:
            raise _Abstain(REASON_INVALID_INPUT, "/qualification")
        decision["qualification"] = mode
    elif "qualification" in body:
        raise _Abstain(REASON_INVALID_INPUT, "/qualification")
    return decision


def _validate_profile(profile: Mapping[str, Any]) -> None:
    body = _mapping(profile, "/profile")
    for key in _PROFILE_REQUIRED_KEYS:
        if key not in body:
            raise _Abstain(REASON_INVALID_INPUT, f"/profile/{key}")
    _text(body["profile_id"], "/profile/profile_id")
    _text(body["profile_version"], "/profile/profile_version")
    types = _text_list(
        body["authorized_source_types"], "/profile/authorized_source_types"
    )
    if not set(types) <= _SOURCE_TYPES:
        raise _Abstain(
            REASON_INVALID_INPUT, "/profile/authorized_source_types"
        )
    _text_list(
        body["authorized_qualifier_refs"],
        "/profile/authorized_qualifier_refs",
    )
    stores = body["authorized_evidence_stores"]
    if not isinstance(stores, (list, tuple)) or not stores:
        raise _Abstain(
            REASON_INVALID_INPUT, "/profile/authorized_evidence_stores"
        )
    for index, store in enumerate(stores):
        path = f"/profile/authorized_evidence_stores/{index}"
        item = _mapping(store, path)
        _text(item.get("evidence_store_id"), path)
        _text(item.get("evidence_store_version"), path)


def _validate_run(run: Mapping[str, Any]) -> dict[str, str]:
    body = _mapping(run, "/run")
    profile_id = body.get("evaluation_profile_id")
    profile_version = body.get("evaluation_profile_version")
    if profile_id is None and profile_version is None:
        raise _Abstain(REASON_PROFILE_NOT_DECLARED, "/run")
    _text(profile_id, "/run/evaluation_profile_id")
    _text(profile_version, "/run/evaluation_profile_version")
    return {
        field: _text(body.get(field), f"/run/{field}")
        for field in _COMPARABILITY_FIELDS
    }


def _qualification_revoked(
    revocations: Sequence[Mapping[str, Any]], qualification_id: str
) -> bool:
    if not isinstance(revocations, (list, tuple)):
        raise _Abstain(REASON_INVALID_INPUT, "/qualification_revocations")
    revoked = False
    for index, item in enumerate(revocations):
        path = f"/qualification_revocations/{index}"
        body = _mapping(item, path)
        if (
            set(body) != _QUALIFICATION_REVOCATION_KEYS
            or body["contract_version"] != _QUALIFICATION_REVOCATION_VERSION
        ):
            raise _Abstain(REASON_INVALID_INPUT, path)
        for key in sorted(_QUALIFICATION_REVOCATION_KEYS - {"revoked_at"}):
            _text(body[key], f"{path}/{key}")
        _timestamp(body["revoked_at"], f"{path}/revoked_at")
        if body["qualification_id"] == qualification_id:
            revoked = True
    return revoked


def _revoked_evidence(
    revocations: Sequence[Mapping[str, Any]],
) -> frozenset[tuple[str, str]]:
    if not isinstance(revocations, (list, tuple)):
        raise _Abstain(REASON_INVALID_INPUT, "/evidence_revocations")
    revoked: set[tuple[str, str]] = set()
    for index, item in enumerate(revocations):
        path = f"/evidence_revocations/{index}"
        body = _mapping(item, path)
        if (
            set(body) != _EVIDENCE_REVOCATION_KEYS
            or body["contract_version"] != _EVIDENCE_REVOCATION_VERSION
        ):
            raise _Abstain(REASON_INVALID_INPUT, path)
        for key in sorted(_EVIDENCE_REVOCATION_KEYS - {"revoked_at"}):
            _text(body[key], f"{path}/{key}")
        _timestamp(body["revoked_at"], f"{path}/revoked_at")
        revoked.add((body["evidence_id"], body["evidence_version"]))
    return frozenset(revoked)


def _select_evidence(
    decision: Mapping[str, Any], evidence: Sequence[EvidenceView]
) -> list[EvidenceView]:
    if not isinstance(evidence, (list, tuple)):
        raise _Abstain(REASON_INVALID_INPUT, "/evidence")
    by_id: dict[str, EvidenceView] = {}
    for index, view in enumerate(evidence):
        path = f"/evidence/{index}"
        if not isinstance(view, EvidenceView):
            raise _Abstain(REASON_INVALID_INPUT, path)
        assertion = _mapping(view.assertion, f"{path}/assertion")
        evidence_id = _text(
            assertion.get("evidence_id"), f"{path}/assertion/evidence_id"
        )
        if evidence_id in by_id:
            raise _Abstain(REASON_EVIDENCE_SET_INVALID, path)
        by_id[evidence_id] = view

    expected = decision["evidence_ids"]
    mode = decision["qualification"]
    if mode == "independent" and len(expected) != 1:
        raise _Abstain(REASON_EVIDENCE_SET_INVALID, "/evidence_ids")
    if mode == "cross_verified" and len(expected) < 2:
        raise _Abstain(REASON_EVIDENCE_SET_INVALID, "/evidence_ids")

    selected: list[EvidenceView] = []
    for evidence_id in expected:
        view = by_id.get(evidence_id)
        if view is None:
            raise _Abstain(REASON_EVIDENCE_MISSING, "/evidence_ids")
        selected.append(view)
    return selected


def _check_evidence(
    decision: Mapping[str, Any],
    views: Sequence[EvidenceView],
    revoked: frozenset[tuple[str, str]],
    profile: Mapping[str, Any],
    run: Mapping[str, Any],
    run_ids: Mapping[str, str],
) -> int:
    authorized_stores = {
        (item["evidence_store_id"], item["evidence_store_version"])
        for item in profile["authorized_evidence_stores"]
    }
    values: set[int] = set()
    source_ids: set[str] = set()
    domains: set[str] = set()

    for index, view in enumerate(views):
        path = f"/evidence/{index}"
        assertion = view.assertion
        _validate_assertion(assertion, path)

        if (
            assertion["profile_id"] != run["evaluation_profile_id"]
            or assertion["profile_version"]
            != run["evaluation_profile_version"]
        ):
            raise _Abstain(REASON_PROFILE_MISMATCH, f"{path}/profile_id")
        for field in _COMPARABILITY_FIELDS:
            if assertion[field] != run_ids[field]:
                raise _Abstain(REASON_TARGET_MISMATCH, f"{path}/{field}")

        key = (assertion["evidence_id"], assertion["evidence_version"])
        if key in revoked:
            raise _Abstain(REASON_EVIDENCE_REVOKED, f"{path}/evidence_id")

        if view.usability == "EVIDENCE_UNAVAILABLE":
            raise _Abstain(REASON_EVIDENCE_UNAVAILABLE, path)
        if view.usability == "INTEGRITY_VALIDATION_FAILED":
            raise _Abstain(REASON_INTEGRITY_FAILED, path)
        if view.usability == "KEY_COMPROMISED":
            raise _Abstain(REASON_KEY_COMPROMISED, path)
        if view.usability != USABILITY_USABLE:
            raise _Abstain(REASON_INVALID_INPUT, f"{path}/usability")

        if (
            assertion["source_type"]
            not in profile["authorized_source_types"]
            or (
                assertion["evidence_store_id"],
                assertion["evidence_store_version"],
            )
            not in authorized_stores
        ):
            raise _Abstain(REASON_UNAUTHORIZED_SOURCE, path)
        if (
            decision["qualification"] == "independent"
            and assertion["source_type"] in _NOT_SUFFICIENT_ALONE
        ):
            raise _Abstain(
                REASON_UNAUTHORIZED_SOURCE, f"{path}/source_type"
            )

        if not (
            assertion.get("source_signature_ref")
            or assertion.get("adapter_attestation_ref")
        ):
            raise _Abstain(REASON_AUTHENTICITY_MISSING, path)

        values.add(assertion["outcome_value"])
        source_ids.add(assertion["source_id"])
        domains.add(_text(view.independence_domain_id, f"{path}/domain"))

    if decision["qualification"] == "cross_verified" and (
        len(source_ids) != len(views) or len(domains) != len(views)
    ):
        raise _Abstain(REASON_INDEPENDENCE_VIOLATION, "/evidence_ids")
    if len(values) != 1:
        raise _Abstain(REASON_OUTCOME_CONFLICT, "/evidence_ids")
    return values.pop()


def _validate_assertion(assertion: Mapping[str, Any], path: str) -> None:
    keys = set(assertion)
    if keys - _ASSERTION_KEYS or (
        _ASSERTION_KEYS - _ASSERTION_OPTIONAL_KEYS - keys
    ):
        raise _Abstain(REASON_INVALID_INPUT, f"{path}/assertion")
    if assertion["contract_version"] != _ASSERTION_VERSION:
        raise _Abstain(REASON_INVALID_INPUT, f"{path}/contract_version")
    value = assertion["outcome_value"]
    if isinstance(value, bool) or value not in (0, 1):
        raise _Abstain(REASON_INVALID_INPUT, f"{path}/outcome_value")
    if not isinstance(value, int):
        raise _Abstain(REASON_INVALID_INPUT, f"{path}/outcome_value")
    for key in sorted(
        _ASSERTION_KEYS
        - _ASSERTION_OPTIONAL_KEYS
        - {
            "contract_version",
            "outcome_value",
            "observed_at",
            "received_at",
        }
    ):
        _text(assertion[key], f"{path}/{key}")
    for key in sorted(_ASSERTION_OPTIONAL_KEYS & keys):
        _text(assertion[key], f"{path}/{key}")
    _timestamp(assertion["observed_at"], f"{path}/observed_at")
    _timestamp(assertion["received_at"], f"{path}/received_at")
    if assertion["source_type"] not in _SOURCE_TYPES:
        raise _Abstain(REASON_INVALID_INPUT, f"{path}/source_type")
