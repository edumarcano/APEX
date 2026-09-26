"""Admission and durable lifecycle for model-independent briefing sessions."""

from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from typing import Callable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from core.briefings.models import (
    BUILTIN_BRIEFING_PROFILES,
    BriefingComparison,
    BriefingCoverage,
    BriefingDraft,
    BriefingEvidence,
    BriefingHistorySelection,
    BriefingGenerationConfiguration,
    BriefingGenerationRequest,
    BriefingInvestigationMetadata,
    BriefingStageProgress,
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


class BriefingHistoryContext(BaseModel):
    """The immutable history selection and its still-readable session snapshots."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    selection: BriefingHistorySelection
    sessions: tuple[BriefingSessionRecord, ...] = ()


class BriefingGenerationOutput(BaseModel):
    """Untrusted synthesis draft and its host-collected source snapshots."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    draft: BriefingDraft
    evidence: list[BriefingEvidence]
    coverage: list[BriefingCoverage]
    comparison: BriefingComparison | None = None
    investigation: BriefingInvestigationMetadata | None = None


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
    [UUID, BriefingGenerationRequest, BriefingGenerationConfiguration, RunExecutionControl, BriefingHistoryContext],
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
        if request.profile_id == "deep":
            from core.briefings.investigation import validate_deep_preflight

            validate_deep_preflight(configuration, partition=partition)  # type: ignore[arg-type]
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
        history_selection: BriefingHistorySelection | None = None
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
                    history_selection = self.store.capture_history_selection(
                        connection, partition
                    )
                    self.store.insert_pending(
                        connection,
                        session_id=session_id,
                        partition=partition,
                        request=request,
                        configuration=configuration,
                        history_selection=history_selection,
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

        active_control: list[RunExecutionControl | None] = [None]

        def execute(control: RunExecutionControl) -> BriefingExecutionResult:
            active_control[0] = control
            if history_selection is None:
                raise BriefingSessionConflictError(
                    "Admitted briefing has no frozen history selection."
                )
            selected_history, history_records = self.store.history_candidates(
                session_id, partition
            )
            if selected_history != history_selection:
                raise BriefingSessionConflictError(
                    "Admitted briefing history selection changed during execution."
                )
            generated = self._execute_generation(
                session_id,
                request,
                configuration,
                control,
                BriefingHistoryContext(
                    selection=selected_history,
                    sessions=tuple(history_records),
                ),
            )
            control.publish_activity(
                "briefing.stage", {"stage": "persisting", "state": "started"}
            )
            artifact = build_canonical_artifact(
                session_id=session_id,
                draft=generated.draft,
                evidence=generated.evidence,
                coverage=generated.coverage,
                comparison=generated.comparison,
                investigation=generated.investigation,
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
                finalized = handle.finalize(
                    status=status,
                    stop_reason=stop_reason,
                    evidence=RunCompletionEvidence(
                        final_message_status=conversation_status,
                        answer_persisted=success,
                    ),
                    error=error,
                    connection=connection,
                )
            control = active_control[0]
            if control is not None:
                control.publish_activity(
                    "briefing.stage",
                    {
                        "stage": "persisting",
                        "state": "completed" if success else (
                            "cancelled" if status == "cancelled" else "failed"
                        ),
                    },
                )
            return finalized

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
        if configuration.execution_kind == "model" and configuration.model.model_id != request.model_id:
            raise ValueError("Resolved briefing model does not match the explicit request.")
        if configuration.execution_kind == "demo" and (
            request.profile_id not in {"daily", "catch_up"}
            or configuration.model.provider != "demo"
            or configuration.model.runtime != "demo"
        ):
            raise ValueError("Demo briefing configuration is invalid.")
        if configuration.origin != request.origin:
            raise ValueError("Resolved briefing origin does not match the request.")


__all__ = [
    "BriefingExecutionResult",
    "BriefingGenerationOutput",
    "BriefingHistoryContext",
    "BriefingSessionQueries",
    "BriefingService",
    "BriefingStartResult",
    "get_briefing_service",
    "get_briefing_session_queries",
    "set_briefing_service",
    "set_briefing_session_queries",
]


_service: BriefingService | None = None
_queries: BriefingSessionQueries | None = None


def set_briefing_service(service: BriefingService | None) -> None:
    global _service
    _service = service


def get_briefing_service() -> BriefingService:
    if _service is None:
        raise RuntimeError("Briefing generation is unavailable.")
    return _service


def set_briefing_session_queries(
    service: BriefingSessionQueries | None,
) -> None:
    global _queries
    _queries = service


def get_briefing_session_queries() -> BriefingSessionQueries:
    if _queries is None:
        raise RuntimeError("Briefing session service is unavailable.")
    return _queries


def get_briefing_session_queries_optional() -> BriefingSessionQueries | None:
    """Allow Cortex turns without a briefing store in isolated runtimes."""
    return _queries


class BriefingSessionQueries:
    """Partition-aware read service with one explicit presentation mutation."""

    def __init__(
        self,
        store: BriefingSessionStore,
        partition_getter: Callable[[], str],
        coordinator: CortexRunCoordinator | None = None,
    ) -> None:
        self.store = store
        self._partition_getter = partition_getter
        self._coordinator = coordinator

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
        partition = self._partition_getter()
        record = self.store.get(session_id, partition)
        speech_status = (
            self.store.get_speech_status(session_id, partition)["status"]
            if record.run_status == "completed" and record.artifact is not None
            else "not_requested"
        )
        return self._detail(
            record,
            self._active_stage(record.run_id),
            speech_status=speech_status,
        )

    def evidence(self, session_id: UUID, evidence_id: UUID) -> BriefingEvidence:
        return self.store.evidence(session_id, self._partition_getter(), evidence_id)

    def mark_presented(self, session_id: UUID) -> BriefingSessionDetail:
        partition = self._partition_getter()
        record = self.store.mark_presented(session_id, partition)
        speech_status = self.store.get_speech_status(session_id, partition)["status"]
        return self._detail(
            record,
            self._active_stage(record.run_id),
            speech_status=speech_status,
        )

    def _active_stage(self, run_id: UUID) -> BriefingStageProgress | None:
        if self._coordinator is None:
            return None
        buffer = self._coordinator.events.get(run_id)
        if buffer is None:
            return None
        value = buffer.snapshot().payload.get("briefing_stage")
        if not isinstance(value, dict):
            return None
        try:
            return BriefingStageProgress.model_validate(value)
        except ValueError:
            return None

    @staticmethod
    def _detail(
        record: BriefingSessionRecord,
        active_stage: BriefingStageProgress | None = None,
        *,
        speech_status: str = "not_requested",
    ) -> BriefingSessionDetail:
        completed = record.run_status == "completed" and record.artifact is not None
        return BriefingSessionDetail(
            id=record.id,
            conversation_id=record.conversation_id,
            opening_message_id=record.opening_message_id,
            run_id=record.run_id,
            run_status=record.run_status,
            run_error_code=record.run_error_code,
            configuration=record.configuration,
            artifact=record.artifact if completed else None,
            evidence_count=len(record.evidence) if completed else 0,
            evidence_ids=[item.id for item in record.evidence] if completed else [],
            created_at=record.created_at,
            presented_at=record.presented_at,
            speech_status=speech_status,  # type: ignore[arg-type]
            active_stage=active_stage,
        )
