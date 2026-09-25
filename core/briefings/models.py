"""Contracts for persistent, model-independent briefing sessions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from core.runs.models import RunErrorCode

BriefingProfileId = Literal["daily", "catch_up", "deep"]
BriefingOrigin = Literal["hud", "cli"]
BriefingCategory = Literal[
    "observation",
    "accepted_context",
    "pending_review",
    "external_report",
    "analysis",
    "suggestion",
]
EvidenceTrust = Literal["observed", "accepted", "pending", "untrusted", "unknown"]
EvidenceIdentityKind = Literal["provider", "content", "masked", "fixture", "unknown"]
EvidenceRevisionKind = Literal["provider", "content", "none"]
CoverageStatus = Literal["complete", "partial", "unavailable", "disabled", "failed"]
BriefingStage = Literal["preparing", "collecting", "selecting", "synthesizing", "persisting"]
SpeechDeliveryStatus = Literal["not_requested", "ready", "unavailable"]

MAX_ARTIFACT_BYTES = 64 * 1024
MAX_EVIDENCE_BYTES = 256 * 1024
MAX_PROMPT_BYTES = 128 * 1024
MAX_OUTPUT_TOKENS = 8192

OpaqueSourceId = Annotated[str, StringConstraints(min_length=1, max_length=512)]


class BuiltinBriefingProfile(BaseModel):
    """Stable product intent for a built-in profile; model choice is separate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: BriefingProfileId
    label: str
    purpose: str
    source_strategy: Literal["current", "changes", "current_and_changes"]
    history_strategy: Literal["none", "presented_baseline", "conversation"]
    investigation_required: bool = False
    definition_version: int = Field(default=1, ge=1)


BUILTIN_BRIEFING_PROFILES: dict[BriefingProfileId, BuiltinBriefingProfile] = {
    "daily": BuiltinBriefingProfile(
        id="daily",
        label="Daily",
        purpose="A concise view of current information and its supporting evidence.",
        source_strategy="current",
        history_strategy="none",
        definition_version=2,
    ),
    "catch_up": BuiltinBriefingProfile(
        id="catch_up",
        label="Catch Up",
        purpose="A view of meaningful changes since a briefing was presented.",
        source_strategy="changes",
        history_strategy="presented_baseline",
    ),
    "deep": BuiltinBriefingProfile(
        id="deep",
        label="Deep",
        purpose="An evidence-backed investigation across relevant current information and context.",
        source_strategy="current_and_changes",
        history_strategy="conversation",
        investigation_required=True,
    ),
}


class BriefingGenerationRequest(BaseModel):
    """Internal generation request; partition, limits, and identity stay server-owned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: UUID
    profile_id: BriefingProfileId
    model_id: str = Field(min_length=1, max_length=160)
    reasoning: str | None = Field(default=None, min_length=1, max_length=32)
    context_window: int | None = Field(default=None, ge=1)
    local_reasoning_mode: Literal["none", "focused"] | None = None
    origin: BriefingOrigin = "hud"


class BriefingModelConfiguration(BaseModel):
    """Frozen, safe model and run settings captured when a session is admitted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    provider: Literal["gemini", "ollama", "llama_cpp", "openai", "openrouter", "demo"]
    runtime: Literal["cloud", "local", "demo"]
    reasoning: str | None = None
    context_window: int | None = Field(default=None, ge=1)
    local_reasoning_mode: Literal["none", "focused"] | None = None
    max_elapsed_seconds: int = Field(ge=1)
    max_retries: int = Field(ge=0)
    max_model_turns: int = Field(ge=1)
    max_tool_calls: int = Field(ge=1)
    output_token_limit: int = Field(ge=1, le=MAX_OUTPUT_TOKENS)


class BriefingGenerationConfiguration(BaseModel):
    """Safe configuration serialized with each session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: BuiltinBriefingProfile
    model: BriefingModelConfiguration
    origin: BriefingOrigin
    execution_kind: Literal["model", "demo"] = "model"


class BriefingSessionGenerateRequest(BaseModel):
    """HUD-facing generation request; origin and execution limits stay server-owned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: UUID
    profile_id: BriefingProfileId
    model_id: str = Field(min_length=1, max_length=160)
    reasoning: str | None = Field(default=None, min_length=1, max_length=32)
    context_window: int | None = Field(default=None, ge=1)
    local_reasoning_mode: Literal["none", "focused"] | None = None


class ExistingRecordReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["knowledge", "context_review", "external_activity", "action"]
    id: OpaqueSourceId


class BriefingEvidence(BaseModel):
    """Run-local evidence snapshot or an explicit unavailable reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    source: Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
    source_id: OpaqueSourceId
    identity_kind: EvidenceIdentityKind = "provider"
    revision: str | None = Field(default=None, max_length=512)
    revision_kind: EvidenceRevisionKind = "none"
    observed_at: datetime | None = None
    effective_at: datetime | None = None
    trust: EvidenceTrust = "unknown"
    content: str | None = Field(default=None, max_length=16_000)
    record_reference: ExistingRecordReference | None = None
    included_in_synthesis: bool = True
    selection_priority: int = Field(default=0, ge=0, le=100, exclude=True)
    available: bool = True
    unavailable_reason: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def _validate_availability(self) -> BriefingEvidence:
        if self.available and self.content is None and self.record_reference is None:
            raise ValueError("Available evidence must retain content or a typed record reference.")
        if not self.available and not self.unavailable_reason:
            raise ValueError("Unavailable evidence must explain why it is unavailable.")
        return self


class BriefingCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
    scope: str = Field(min_length=1, max_length=256)
    status: CoverageStatus
    observed_at: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    freshness_seconds: int | None = Field(default=None, ge=0)
    truncated: bool = False
    reason: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def _validate_window(self) -> BriefingCoverage:
        if self.window_start and self.window_end and self.window_start > self.window_end:
            raise ValueError("Coverage window start must not be after its end.")
        if self.status in {"unavailable", "disabled", "failed"} and not self.reason:
            raise ValueError("Unavailable coverage must include a reason.")
        return self


class BriefingItemDraft(BaseModel):
    """Model-facing content. Canonical IDs and provenance are assigned by APEX."""

    model_config = ConfigDict(extra="forbid")

    category: BriefingCategory
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=3_000)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=24)
    record_references: list[ExistingRecordReference] = Field(default_factory=list, max_length=12)

    @field_validator("evidence_ids")
    @classmethod
    def _unique_evidence_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Evidence references must be unique within an item.")
        return value


class BriefingSectionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    items: list[BriefingItemDraft] = Field(max_length=32)


class BriefingDraft(BaseModel):
    """Untrusted synthesis output before host identity and timestamp are attached."""

    model_config = ConfigDict(extra="forbid")

    sections: list[BriefingSectionDraft] = Field(max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=24)

    @field_validator("limitations")
    @classmethod
    def _bound_limitations(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 400 for item in value):
            raise ValueError("Each limitation must contain 1 to 400 characters.")
        return value


class BriefingItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    category: BriefingCategory
    title: str
    body: str
    evidence_ids: list[UUID]
    record_references: list[ExistingRecordReference] = Field(default_factory=list)


class BriefingSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    title: str
    items: list[BriefingItem]


class CanonicalBriefingArtifact(BaseModel):
    """Immutable saved result whose identity and timing are assigned by the host."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    session_id: UUID
    created_at: datetime
    sections: list[BriefingSection]
    coverage: list[BriefingCoverage]
    limitations: list[str]


class BriefingSessionRecord(BaseModel):
    """Validated persistent representation joined to the authoritative run status."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    partition: Literal["production", "sandbox"]
    idempotency_key: UUID
    conversation_id: UUID
    opening_message_id: UUID
    run_id: UUID
    request: BriefingGenerationRequest
    configuration: BriefingGenerationConfiguration
    created_at: datetime
    presented_at: datetime | None = None
    artifact: CanonicalBriefingArtifact | None = None
    evidence: list[BriefingEvidence] = Field(default_factory=list)
    run_status: Literal[
        "queued", "running", "cancelling", "completed", "failed", "cancelled", "interrupted"
    ]
    run_error_code: RunErrorCode | None = None


class BriefingSessionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    profile_id: BriefingProfileId
    model_id: str
    conversation_id: UUID
    run_id: UUID
    run_status: str
    created_at: datetime
    presented_at: datetime | None = None


class BriefingSessionDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    conversation_id: UUID
    opening_message_id: UUID
    run_id: UUID
    run_status: str
    run_error_code: RunErrorCode | None = None
    configuration: BriefingGenerationConfiguration
    artifact: CanonicalBriefingArtifact | None = None
    evidence_count: int = Field(ge=0)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=32)
    created_at: datetime
    presented_at: datetime | None = None
    speech_status: SpeechDeliveryStatus = "not_requested"


def build_canonical_artifact(
    *,
    session_id: UUID,
    draft: BriefingDraft,
    evidence: list[BriefingEvidence],
    coverage: list[BriefingCoverage],
    created_at: datetime | None = None,
) -> CanonicalBriefingArtifact:
    """Validate model references, assign host-owned IDs, and enforce snapshot limits."""
    evidence_by_id = {item.id: item for item in evidence}
    if len(evidence_by_id) != len(evidence):
        raise ValueError("Evidence IDs must be unique.")
    sections: list[BriefingSection] = []
    for section in draft.sections:
        items: list[BriefingItem] = []
        for item in section.items:
            if any(reference not in evidence_by_id for reference in item.evidence_ids):
                raise ValueError("Briefing items may reference only supplied evidence.")
            _validate_category_evidence(item, evidence_by_id)
            items.append(
                BriefingItem(
                    id=uuid4(),
                    category=item.category,
                    title=item.title,
                    body=item.body,
                    evidence_ids=list(item.evidence_ids),
                    record_references=list(item.record_references),
                )
            )
        sections.append(BriefingSection(id=uuid4(), title=section.title, items=items))
    artifact = CanonicalBriefingArtifact(
        session_id=session_id,
        created_at=created_at or datetime.now(timezone.utc),
        sections=sections,
        coverage=coverage,
        limitations=list(draft.limitations),
    )
    validate_snapshot_size(artifact, evidence)
    return artifact


def _validate_category_evidence(
    item: BriefingItemDraft,
    evidence_by_id: dict[UUID, BriefingEvidence],
) -> None:
    expected_trust = {
        "observation": "observed",
        "accepted_context": "accepted",
        "pending_review": "pending",
        "external_report": "untrusted",
    }.get(item.category)
    if not item.evidence_ids:
        raise ValueError("Briefing items must reference supporting evidence.")
    if any(not evidence_by_id[reference].available for reference in item.evidence_ids):
        raise ValueError("Unavailable evidence cannot support a briefing item.")
    if expected_trust is not None and any(
        evidence_by_id[reference].trust != expected_trust
        for reference in item.evidence_ids
    ):
        raise ValueError(f"{item.category} items must preserve the evidence trust category.")
    permitted_references = {
        evidence_by_id[reference].record_reference
        for reference in item.evidence_ids
        if evidence_by_id[reference].record_reference is not None
    }
    if any(reference not in permitted_references for reference in item.record_references):
        raise ValueError("Record references must be carried by supporting evidence.")


def validate_snapshot_size(
    artifact: CanonicalBriefingArtifact,
    evidence: list[BriefingEvidence],
) -> None:
    artifact_size = len(artifact.model_dump_json().encode("utf-8"))
    evidence_size = len(json.dumps(
        [item.model_dump(mode="json") for item in evidence],
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8"))
    if artifact_size > MAX_ARTIFACT_BYTES:
        raise ValueError(f"Canonical artifact exceeds {MAX_ARTIFACT_BYTES} bytes.")
    if evidence_size > MAX_EVIDENCE_BYTES:
        raise ValueError(f"Evidence snapshot exceeds {MAX_EVIDENCE_BYTES} bytes.")


def render_artifact_text(artifact: CanonicalBriefingArtifact) -> str:
    """Render a compact durable conversation message from the canonical artifact."""
    blocks: list[str] = []
    for section in artifact.sections:
        items: list[str] = []
        for item in section.items:
            labels = [item.category.replace("_", " ")]
            reference_kinds = {reference.kind for reference in item.record_references}
            if "context_review" in reference_kinds and item.category != "pending_review":
                labels.append("pending review")
            if "external_activity" in reference_kinds and item.category != "external_report":
                labels.append("untrusted external report")
            items.append(f"- **[{'; '.join(labels)}] {item.title}** {item.body}")
        if items:
            blocks.append(f"## {section.title}\n" + "\n".join(items))
    if artifact.limitations:
        blocks.append("## Coverage limits\n" + "\n".join(f"- {value}" for value in artifact.limitations))
    return "\n\n".join(blocks) or "No briefing items were produced."
