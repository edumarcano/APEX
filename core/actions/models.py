"""Typed immutable records for the action approval lifecycle."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Literal

from core.agent.capabilities import CapabilityRisk

ActionStatus = Literal[
    "proposed",
    "approved",
    "executing",
    "verifying",
    "verified",
    "rejected",
    "expired",
    "execution_failed",
    "verification_failed",
    "outcome_unknown",
]
ActionRisk = Literal["write", "destructive"]

MAX_EVIDENCE_BYTES = 16_384
_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_STATUS_VALUES: frozenset[str] = frozenset(
    {
        "proposed",
        "approved",
        "executing",
        "verifying",
        "verified",
        "rejected",
        "expired",
        "execution_failed",
        "verification_failed",
        "outcome_unknown",
    }
)


class ActionValidationError(ValueError):
    """Raised when an action-domain input is not safe to persist."""


def normalize_timestamp(value: datetime) -> datetime:
    """Return a timezone-aware UTC timestamp suitable for persistence."""
    if value.tzinfo is None:
        raise ActionValidationError("Action timestamps must include a timezone.")
    return value.astimezone(UTC)


def timestamp_to_storage(value: datetime) -> str:
    """Serialize a normalized timestamp consistently."""
    return normalize_timestamp(value).isoformat()


def timestamp_from_storage(value: str) -> datetime:
    """Parse persisted UTC action timestamps strictly."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ActionValidationError("Stored action timestamp is invalid.") from exc
    return normalize_timestamp(parsed)


def _freeze_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise ActionValidationError("Action data must contain only JSON values.")


def thaw_json(value: Any) -> Any:
    """Return a mutable deep copy of a frozen JSON-compatible value."""
    if isinstance(value, Mapping):
        return {str(key): thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def canonical_json(value: Any, *, max_bytes: int | None = None) -> str:
    """Serialize JSON deterministically and apply an optional byte bound."""
    try:
        encoded = json.dumps(
            thaw_json(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ActionValidationError("Action data must be valid JSON.") from exc
    if max_bytes is not None and len(encoded.encode("utf-8")) > max_bytes:
        raise ActionValidationError("Action evidence exceeds the permitted size.")
    return encoded


def frozen_json_object(value: Mapping[str, Any], *, max_bytes: int | None = None) -> Mapping[str, Any]:
    """Validate, copy, and freeze a JSON object."""
    if not isinstance(value, Mapping):
        raise ActionValidationError("Action data must be a JSON object.")
    frozen = _freeze_json(value)
    canonical_json(frozen, max_bytes=max_bytes)
    return frozen


def validate_code(value: str) -> str:
    """Validate a stable machine-readable action result code."""
    if not isinstance(value, str) or not _CODE_PATTERN.fullmatch(value):
        raise ActionValidationError("Action result codes must be stable lowercase identifiers.")
    return value


def _required_text(value: str, field_name: str, *, limit: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ActionValidationError(f"Action {field_name} must be non-empty and bounded.")
    return value


@dataclass(frozen=True, slots=True)
class ActionProposal:
    """Frozen request details that an approved action must execute exactly."""

    agent_key: str
    capability_name: str
    arguments: Mapping[str, Any]
    target: str
    risk: ActionRisk
    summary: str
    proposed_at: datetime
    expires_at: datetime
    proposal_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _required_text(self.agent_key, "agent key", limit=128)
        _required_text(self.capability_name, "capability name", limit=128)
        _required_text(self.target, "target")
        _required_text(self.summary, "summary", limit=1_024)
        if self.risk not in {"write", "destructive"}:
            raise ActionValidationError("Only write or destructive actions can be proposed.")
        proposed_at = normalize_timestamp(self.proposed_at)
        expires_at = normalize_timestamp(self.expires_at)
        if expires_at <= proposed_at:
            raise ActionValidationError("Action proposals must expire after they are created.")
        arguments = frozen_json_object(self.arguments)
        object.__setattr__(self, "arguments", arguments)
        object.__setattr__(self, "proposed_at", proposed_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "proposal_hash", proposal_hash_for(self))


def proposal_hash_for(proposal: ActionProposal) -> str:
    """Return an audit checksum for the immutable proposal fields.

    The checksum catches accidental corruption; it is not a security boundary
    because a user who can alter the database can also replace the checksum.
    """
    payload = {
        "agent_key": proposal.agent_key,
        "arguments": thaw_json(proposal.arguments),
        "capability_name": proposal.capability_name,
        "expires_at": timestamp_to_storage(proposal.expires_at),
        "proposed_at": timestamp_to_storage(proposal.proposed_at),
        "risk": proposal.risk,
        "summary": proposal.summary,
        "target": proposal.target,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ActionRecord:
    """Current durable state for one proposal."""

    action_id: str
    proposal: ActionProposal
    status: ActionStatus
    version: int
    updated_at: datetime

    def __post_init__(self) -> None:
        _required_text(self.action_id, "identifier", limit=128)
        if self.status not in _STATUS_VALUES:
            raise ActionValidationError("Action status is invalid.")
        if not isinstance(self.version, int) or self.version < 0:
            raise ActionValidationError("Action version is invalid.")
        object.__setattr__(self, "updated_at", normalize_timestamp(self.updated_at))


@dataclass(frozen=True, slots=True)
class ActionEvent:
    """One immutable state transition in an action's audit ledger."""

    action_id: str
    sequence: int
    from_status: ActionStatus | None
    to_status: ActionStatus
    occurred_at: datetime
    actor: str
    result_code: str
    evidence: Mapping[str, Any]

    def __post_init__(self) -> None:
        _required_text(self.action_id, "identifier", limit=128)
        if not isinstance(self.sequence, int) or self.sequence < 0:
            raise ActionValidationError("Action event sequence is invalid.")
        if self.from_status is not None and self.from_status not in _STATUS_VALUES:
            raise ActionValidationError("Action event source status is invalid.")
        if self.to_status not in _STATUS_VALUES:
            raise ActionValidationError("Action event target status is invalid.")
        _required_text(self.actor, "event actor", limit=128)
        object.__setattr__(self, "result_code", validate_code(self.result_code))
        object.__setattr__(self, "occurred_at", normalize_timestamp(self.occurred_at))
        object.__setattr__(
            self,
            "evidence",
            frozen_json_object(self.evidence, max_bytes=MAX_EVIDENCE_BYTES),
        )


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """A connector-neutral executor result; ``None`` means ambiguous outcome."""

    succeeded: bool | None
    code: str
    evidence: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.succeeded not in {True, False, None}:
            raise ActionValidationError("Execution outcome must be true, false, or unknown.")
        object.__setattr__(self, "code", validate_code(self.code))
        object.__setattr__(
            self,
            "evidence",
            frozen_json_object(self.evidence, max_bytes=MAX_EVIDENCE_BYTES),
        )


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    """Independent verifier result; only true permits a verified action."""

    verified: bool
    code: str
    evidence: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.verified, bool):
            raise ActionValidationError("Verification outcome must be boolean.")
        object.__setattr__(self, "code", validate_code(self.code))
        object.__setattr__(
            self,
            "evidence",
            frozen_json_object(self.evidence, max_bytes=MAX_EVIDENCE_BYTES),
        )


def action_risk(value: CapabilityRisk) -> ActionRisk:
    """Narrow a capability risk to the action-producing risks."""
    if value not in {"write", "destructive"}:
        raise ActionValidationError("Read capabilities cannot produce actions.")
    return value
