"""Versioned contracts for untrusted external activity reports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


ActivityPartition = Literal["production", "sandbox"]
ActivityDisposition = Literal["new", "reviewed", "dismissed"]
ACTIVITY_CLIENT_ID_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"
ActivityClientId = Annotated[str, Field(pattern=ACTIVITY_CLIENT_ID_PATTERN)]
_ShortText = Annotated[str, Field(min_length=1, max_length=512)]
_LongText = Annotated[str, Field(min_length=1, max_length=20_000)]


def is_valid_activity_client_id(value: object) -> bool:
    """Return whether a caller-declared source ID follows the shared contract."""
    return isinstance(value, str) and re.fullmatch(ACTIVITY_CLIENT_ID_PATTERN, value) is not None


def _bounded_text(value: str, *, limit: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > limit:
        raise ValueError("must contain bounded non-whitespace text")
    return normalized


class ActivityFinding(BaseModel):
    """One untrusted structured finding kept inside the immutable report JSON."""

    model_config = ConfigDict(extra="forbid")

    title: _ShortText | None = None
    text: _LongText
    derivation: Literal["model_interpretation", "unknown"] = "unknown"

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        return _bounded_text(value, limit=512) if value is not None else None

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return _bounded_text(value, limit=20_000)


class ActivityReportContent(BaseModel):
    """The version-one report body. It never carries partition or identity."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    submission_key: Annotated[str, Field(min_length=1, max_length=256)]
    title: _ShortText
    task_status: _ShortText
    outcome: _LongText
    findings: list[ActivityFinding] = Field(default_factory=list, max_length=100)
    evidence_links: list[Annotated[str, Field(min_length=1, max_length=2048)]] = Field(default_factory=list, max_length=100)
    artifact_references: list[Annotated[str, Field(min_length=1, max_length=2048)]] = Field(default_factory=list, max_length=100)
    unresolved_questions: list[Annotated[str, Field(min_length=1, max_length=4_000)]] = Field(default_factory=list, max_length=100)
    suggested_follow_up: Annotated[str, Field(min_length=1, max_length=4_000)] | None = None
    subjects: list[Annotated[str, Field(min_length=1, max_length=512)]] = Field(default_factory=list, max_length=100)
    projects: list[Annotated[str, Field(min_length=1, max_length=512)]] = Field(default_factory=list, max_length=100)
    occurred_at: datetime | None = None
    native_task_url: Annotated[str, Field(min_length=1, max_length=2048)] | None = None
    markdown_body: Annotated[str, Field(min_length=1, max_length=200_000)] | None = None

    @field_validator("submission_key")
    @classmethod
    def normalize_submission_key(cls, value: str) -> str:
        return _bounded_text(value, limit=256)

    @field_validator("title", "task_status")
    @classmethod
    def normalize_short_text(cls, value: str) -> str:
        return _bounded_text(value, limit=512)

    @field_validator("evidence_links", "artifact_references")
    @classmethod
    def normalize_references(cls, values: list[str]) -> list[str]:
        return [_bounded_text(value, limit=2048) for value in values]

    @field_validator("unresolved_questions")
    @classmethod
    def normalize_questions(cls, values: list[str]) -> list[str]:
        return [_bounded_text(value, limit=4_000) for value in values]

    @field_validator("subjects", "projects")
    @classmethod
    def normalize_labels(cls, values: list[str]) -> list[str]:
        return [_bounded_text(value, limit=512) for value in values]

    @field_validator("outcome")
    @classmethod
    def normalize_outcome(cls, value: str) -> str:
        return _bounded_text(value, limit=20_000)

    @field_validator("suggested_follow_up")
    @classmethod
    def normalize_suggested_follow_up(cls, value: str | None) -> str | None:
        return _bounded_text(value, limit=4_000) if value is not None else None

    @field_validator("native_task_url")
    @classmethod
    def normalize_native_task_url(cls, value: str | None) -> str | None:
        return _bounded_text(value, limit=2048) if value is not None else None

    @field_validator("markdown_body")
    @classmethod
    def validate_markdown_body(cls, value: str | None) -> str | None:
        """Bound imported Markdown without rewriting its report content."""
        if value is None:
            return None
        if not value.strip() or len(value) > 200_000:
            raise ValueError("must contain bounded non-whitespace text")
        return value

    def resolve_finding_reference(self, reference: str) -> str:
        """Resolve the small, stable evidence-pointer contract for later review.

        A report with structured findings permits only ``/findings/<index>``.
        Reports without structured findings may instead point at their outcome
        or Markdown body. Callers never supply the evidence text separately.
        """
        return self.resolve_finding_evidence(reference)[0]

    def resolve_finding_evidence(self, reference: str) -> tuple[str, Literal["model_interpretation", "unknown"]]:
        """Resolve original text and only the derivation declared by the report."""
        if self.findings:
            prefix = "/findings/"
            if not reference.startswith(prefix):
                raise ValueError("finding_reference_invalid")
            raw_index = reference.removeprefix(prefix)
            if not raw_index.isdecimal() or (len(raw_index) > 1 and raw_index.startswith("0")):
                raise ValueError("finding_reference_invalid")
            index = int(raw_index)
            if index >= len(self.findings):
                raise ValueError("finding_reference_invalid")
            finding = self.findings[index]
            return finding.text, finding.derivation
        if reference == "/outcome":
            return self.outcome, "unknown"
        if reference == "/markdown_body" and self.markdown_body is not None:
            return self.markdown_body, "unknown"
        raise ValueError("finding_reference_invalid")


class ActivitySubmissionRequest(BaseModel):
    """One client-attributed report accepted by local and gateway adapters."""

    model_config = ConfigDict(extra="forbid")

    client_id: ActivityClientId
    report: ActivityReportContent


@dataclass(frozen=True, slots=True)
class ActivityReport:
    id: UUID
    partition: ActivityPartition
    client_id: str
    client_display_name: str
    principal: str
    received_at: str
    disposition: ActivityDisposition
    content: ActivityReportContent


@dataclass(frozen=True, slots=True)
class ActivitySubmissionReceipt:
    report: ActivityReport
    duplicate: bool


@dataclass(frozen=True, slots=True)
class ActivityContextReviewLink:
    """A retry-safe connection from immutable activity evidence to one review."""

    report_id: UUID
    partition: ActivityPartition
    finding_reference: str
    proposal_hash: str
    review_id: UUID
    action_id: str
