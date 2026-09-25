"""Admission and durable lifecycle for model-independent briefing sessions."""

from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from typing import Callable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from core.briefings.models import (
    BUILTIN_BRIEFING_PROFILES,
    BriefingCoverage,
    BriefingDraft,
    BriefingEvidence,
    BriefingGenerationConfiguration,
    BriefingGenerationRequest,
    BriefingSessionDetail,
    BriefingSessionRecord,
    BriefingSessionSummary,
    CanonicalBriefingArtifact,
    build_canonical_artifact,
    render_artifact_text,
)
from core.briefings.store import (
    BriefingSessionConflictError,
    BriefingSessionStore,
)
from core.conversations.store import ConversationStore
from core.runs.coordinator import (
    CortexRunCoordinator,
    RunExecutionControl,
)
from core.runs.models import (
    RunCompletionEvidence,
    RunError,
    RunLimitSnapshot,
    RunRecord,
    RunStatus,
    RunStopReason,
)
from core.runs.service import RunService


class BriefingGenerationOutput(BaseModel):
    """Untrusted synthesis draft and its host-collected source snapshots."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    draft: BriefingDraft
    evidence: list[BriefingEvidence]
    coverage: list[BriefingCoverage]


@dataclass(frozen=True, slots=True)
class BriefingExecutionResult:
    artifact: CanonicalBriefingArtifact
    evidence: tuple[BriefingEvidence, ...]


@dataclass(frozen=True, slots=True)
class BriefingStartResult:
    session: BriefingSessionRecord
    future: Future[object] | None
    replayed: bool


ConfigurationResolver = Callable[
    [BriefingGenerationRequest], BriefingGenerationConfiguration
]
GenerationExecutor = Callable[
    [UUID, BriefingGenerationRequest, BriefingGenerationConfiguration, RunExecutionControl],
    BriefingGenerationOutput,
]


class BriefingService:
    """Create one session/run/conversation atomically, then execute it once."""

    def __init__(
        self,
        *,
        store: BriefingSessionStore,
        conversations: ConversationStore,
        runs: RunService,
        coordinator: CortexRunCoordinator,
        partition_getter: Callable[[], str],
        resolve_configuration: ConfigurationResolver,
        execute_generation: GenerationExecutor,
    ) -> None:
        self.store = store
        self.conversations = conversations
        self.runs = runs
        self.coordinator = coordinator
        self._partition_getter = partition_getter
        self._resolve_configuration = resolve_configuration
        self._execute_generation = execute_generation

    def start(self, request: BriefingGenerationRequest) -> BriefingStartResult:
        """Admit a new request or return its idempotent session replay."""
        partition = self._partition_getter()
        if partition not in {"production", "sandbox"}:
            raise ValueError("Briefing partition is invalid.")

        existing = self.store.lookup_idempotency(partition, request)
        if existing is not None:
            return BriefingStartResult(
                session=existing,
                future=self.coordinator.future_for(existing.run_id),
                replayed=True,
            )

        configuration = self._resolve_configuration(request)
        self._validate_configuration(request, configuration)
        session_id = uuid4()
        conversation_id = uuid4()
        user_message_id = uuid4()
        opening_message_id = uuid4()
        run_id = uuid4()
        profile = BUILTIN_BRIEFING_PROFILES[request.profile_id]
        prompt = f"Prepare a {profile.label} briefing."
        request_metadata = {
            "briefing_session_id": str(session_id),
            "profile_id": request.profile_id,
            "model_id": request.model_id,
        }

        self.coordinator.admit(
            conversation_id=conversation_id,
            agent_message_id=opening_message_id,
        )
        try:
            with self.store.transaction() as connection:
                # BEGIN IMMEDIATE serializes the idempotency recheck with insert.
                existing = self.store.lookup_idempotency(
                    partition, request, connection=connection
                )
                if existing is None:
                    self.conversations.create_briefing_opening(
                        connection=connection,
                        conversation_id=conversation_id,
                        partition=partition,
                        origin=request.origin,
                        title=f"{profile.label} briefing",
                        user_id=user_message_id,
                        agent_id=opening_message_id,
                        prompt=prompt,
                        request_metadata=request_metadata,
                    )
                    limits = RunLimitSnapshot(
                        max_elapsed_seconds=configuration.model.max_elapsed_seconds,
                        max_retries=configuration.model.max_retries,
                        max_model_turns=configuration.model.max_model_turns,
                        max_tool_calls=configuration.model.max_tool_calls,
                    )
                    _run, handle, replayed_run = self.runs.create_run(
                        run_id=run_id,
                        conversation_id=conversation_id,
                        user_message_id=user_message_id,
                        agent_message_id=opening_message_id,
                        requested_model=request.model_id,
                        limit_snapshot=limits,
                        partition=partition,  # type: ignore[arg-type]
                        connection=connection,
                    )
                    if replayed_run:
                        raise BriefingSessionConflictError(
                            "A run already exists for the briefing opening message."
                        )
                    self.store.insert_pending(
                        connection,
                        session_id=session_id,
                        partition=partition,
                        request=request,
                        configuration=configuration,
                        conversation_id=conversation_id,
                        opening_message_id=opening_message_id,
                        run_id=run_id,
                    )
        except BaseException:
            self.coordinator.abandon_admission(opening_message_id)
            raise
        if existing is not None:
            self.coordinator.abandon_admission(opening_message_id)
            return BriefingStartResult(
                session=existing,
                future=self.coordinator.future_for(existing.run_id),
                replayed=True,
            )

        def execute(control: RunExecutionControl) -> BriefingExecutionResult:
            generated = self._execute_generation(
                session_id, request, configuration, control
            )
            artifact = build_canonical_artifact(
                session_id=session_id,
                draft=generated.draft,
                evidence=generated.evidence,
                coverage=generated.coverage,
            )
            return BriefingExecutionResult(
                artifact=artifact,
                evidence=tuple(generated.evidence),
            )

        def finalize(
            handle,
            response: object | None,
            status: RunStatus,
            stop_reason: RunStopReason,
            error: RunError | None,
        ) -> RunRecord:
            success = status == "completed"
            if success and not isinstance(response, BriefingExecutionResult):
                raise BriefingSessionConflictError(
                    "Completed briefing did not return a canonical artifact."
                )
            if success:
                assert isinstance(response, BriefingExecutionResult)
                answer = render_artifact_text(response.artifact)
                conversation_status = "completed"
                response_metadata = {
                    "briefing_session_id": str(session_id),
                    "artifact_schema_version": response.artifact.schema_version,
                }
            else:
                answer = ""
                conversation_status = (
                    "interrupted" if status in {"cancelled", "interrupted"} else "failed"
                )
                response_metadata = {"error_code": error.code if error else "internal_error"}

            with self.store.transaction() as connection:
                if success:
                    assert isinstance(response, BriefingExecutionResult)
                    self.store.save_completed_snapshot(
                        connection,
                        session_id=session_id,
                        partition=partition,
                        artifact=response.artifact,
                        evidence=list(response.evidence),
                    )
                self.conversations.finalize(
                    conversation_id=conversation_id,
                    agent_id=opening_message_id,
                    answer=answer,
                    status=conversation_status,
                    response_metadata=response_metadata,
                    connection=connection,
                )
                return handle.finalize(
                    status=status,
                    stop_reason=stop_reason,
                    evidence=RunCompletionEvidence(
                        final_message_status=conversation_status,
                        answer_persisted=success,
                    ),
                    error=error,
                    connection=connection,
                )

        try:
            future = self.coordinator.submit(
                handle=handle,
                resolved_model=configuration.model.model_id,
                provider=configuration.model.provider,
                runtime=configuration.model.runtime,
                execute=execute,
                finalize_run=finalize,
            )
        except Exception:
            # Submission can fail after the durable pending turn was committed.
            # Close it as failed so neither conversation nor run remains queued.
            finalize(
                handle,
                None,
                "failed",
                "internal_error",
                RunError(code="internal_error"),
            )
            raise

        return BriefingStartResult(
            session=self.store.get(session_id, partition),
            future=future,
            replayed=False,
        )

    @staticmethod
    def _validate_configuration(
        request: BriefingGenerationRequest,
        configuration: BriefingGenerationConfiguration,
    ) -> None:
        if configuration.profile != BUILTIN_BRIEFING_PROFILES[request.profile_id]:
            raise ValueError("Resolved briefing profile does not match the request.")
        if configuration.model.model_id != request.model_id:
            raise ValueError("Resolved briefing model does not match the explicit request.")
        if configuration.origin != request.origin:
            raise ValueError("Resolved briefing origin does not match the request.")


__all__ = [
    "BriefingExecutionResult",
    "BriefingGenerationOutput",
    "BriefingSessionQueries",
    "BriefingService",
    "BriefingStartResult",
    "get_briefing_session_queries",
    "set_briefing_session_queries",
]


_queries: BriefingSessionQueries | None = None


def set_briefing_session_queries(
    service: BriefingSessionQueries | None,
) -> None:
    global _queries
    _queries = service


def get_briefing_session_queries() -> BriefingSessionQueries:
    if _queries is None:
        raise RuntimeError("Briefing session service is unavailable.")
    return _queries


class BriefingSessionQueries:
    """Partition-aware read service with one explicit presentation mutation."""

    def __init__(
        self,
        store: BriefingSessionStore,
        partition_getter: Callable[[], str],
    ) -> None:
        self.store = store
        self._partition_getter = partition_getter

    def list(
        self, *, limit: int = 25, offset: int = 0
    ) -> list[BriefingSessionSummary]:
        return [
            BriefingSessionSummary(
                id=record.id,
                profile_id=record.request.profile_id,
                model_id=record.configuration.model.model_id,
                conversation_id=record.conversation_id,
                run_id=record.run_id,
                run_status=record.run_status,
                created_at=record.created_at,
                presented_at=record.presented_at,
            )
            for record in self.store.list(
                self._partition_getter(), limit=limit, offset=offset
            )
        ]

    def get(self, session_id: UUID) -> BriefingSessionDetail:
        return self._detail(self.store.get(session_id, self._partition_getter()))

    def evidence(self, session_id: UUID, evidence_id: UUID) -> BriefingEvidence:
        return self.store.evidence(session_id, self._partition_getter(), evidence_id)

    def mark_presented(self, session_id: UUID) -> BriefingSessionDetail:
        return self._detail(
            self.store.mark_presented(session_id, self._partition_getter())
        )

    @staticmethod
    def _detail(record: BriefingSessionRecord) -> BriefingSessionDetail:
        completed = record.run_status == "completed" and record.artifact is not None
        return BriefingSessionDetail(
            id=record.id,
            conversation_id=record.conversation_id,
            opening_message_id=record.opening_message_id,
            run_id=record.run_id,
            run_status=record.run_status,
            configuration=record.configuration,
            artifact=record.artifact if completed else None,
            evidence_count=len(record.evidence) if completed else 0,
            created_at=record.created_at,
            presented_at=record.presented_at,
        )
