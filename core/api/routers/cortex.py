"""Cortex Engine routes for Agent catalog, queries, and local runtime control."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query, status

from core.agent.catalog import AGENT_SPECS, resolve_effort
from core.agent.model_catalog import get_model_profile, visible_cloud_models, visible_local_models
from core.agent.types import (
    AgentKey,
    AgentQueryRequest,
    ToolCatalogResponse,
    ToolProfileMetadata,
    ToolPreflightResponse,
)
from core.agent.tool_profiles import get_tool_profile, list_tool_profiles
from core.settings import (
    SettingsPatch,
    ToolProfile,
    ToolProfilesPatch,
    get_settings_store,
)
from core.config import is_dev_mode
from core.api.cortex import (
    build_tool_catalog,
    build_tool_preflight,
    load_local_model_endpoint,
    query_agent,
    unload_active_local_model_endpoint,
    verify_cloud_agent_endpoint,
)
from core.conversations import get_conversation_service
from core.conversations.models import (
    ConversationCreateRequest,
    ConversationDetail,
    ConversationPatchRequest,
    ConversationSummary,
    ConversationTurnRequest,
    ConversationTurnResult,
)
from core.conversations.store import (
    ConversationBusyError,
    ConversationConflictError,
    ConversationNotFoundError,
)
from core.retrieval import RetrievalBusyError, get_retrieval_service
from core.actions.runtime import get_action_service
from core.knowledge.capture import CAPABILITY_NAME, ContextCaptureError, reject_secret_text
from core.knowledge.reconciliation import CAPABILITY_NAME as RECONCILIATION_CAPABILITY_NAME
from core.knowledge.store import KnowledgeConflictError, KnowledgeNotFoundError, KnowledgeStoreError
from core.context import ContextAssembler, ContextPolicy
from core.knowledge import get_knowledge_service
from core.api.models import (
    CortexAgentResponse,
    ModelVerificationRequest,
    ActionResponse,
    CloudAgentVerificationResponse,
    LocalLoadRequest,
    LocalLoadResponse,
    LocalUnloadResponse,
    ToolProfileCreateRequest,
    ToolProfileDefaultRequest,
    ToolProfileUpdateRequest,
    ToolPreflightRequest,
    ToolProfilesResponse,
    RetrievalPrepareResponse,
    RetrievalStatusResponse,
    ContextCaptureRequest,
    ContextActionRequest,
    ContextEntityResponse,
    ContextRecordDetailResponse,
    ContextRecordResponse,
    ContextSourceResponse,
)

router = APIRouter(tags=["cortex"])
_PROFILE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


def _resolved_turn_metadata(payload: ConversationTurnRequest) -> dict[str, object]:
    """Capture model routing inputs before persisting a replayable turn."""
    settings = get_settings_store().get_snapshot().ask_apex
    model_id = payload.model_id or settings.selected_model
    profile = get_model_profile(model_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown model: {model_id!r}")
    if profile.dev_only and not is_dev_mode():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Model {model_id!r} is only available in development mode.")
    if profile.runtime == "cloud":
        return {
            "resolved_model": profile.model_id,
            "runtime": profile.runtime,
            "provider": profile.provider,
            "effective_effort": resolve_effort(profile, payload.effort),
            "effective_context_window": None,
            "effective_local_reasoning_mode": None,
        }
    if payload.effort is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Effort cannot be set for local models.")
    return {
        "resolved_model": profile.model_id,
        "runtime": profile.runtime,
        "provider": profile.provider,
        "effective_effort": None,
        "effective_context_window": payload.context_window or settings.local.context_window,
        "effective_local_reasoning_mode": payload.local_reasoning_mode or settings.local.reasoning_mode,
    }


def _context_entity(entity_id, *, partition: str) -> ContextEntityResponse | None:
    if entity_id is None:
        return None
    service = get_knowledge_service()
    try:
        entity = service.get_entity(entity_id, include_merged=True)
    except KnowledgeNotFoundError:
        return None
    if not service.entity_in_partition(entity.id, partition=partition):
        return None
    return ContextEntityResponse(
        id=str(entity.id), name=entity.name,
        aliases=service.aliases_for_entity(entity.id) if partition == "production" else [entity.name],
        merged_into_entity_id=str(entity.merged_into_entity_id) if entity.merged_into_entity_id else None,
    )


def _context_record(record) -> ContextRecordResponse:
    return ContextRecordResponse(
        id=str(record.id), partition=record.partition, kind=record.kind, text=record.text,
        status=record.status, subject=_context_entity(record.subject_entity_id, partition=record.partition),
        predicate=record.predicate, object_entity=_context_entity(record.object_entity_id, partition=record.partition),
        object_value=record.object_value, effective_at=record.effective_at,
        supersedes_record_id=str(record.supersedes_record_id) if record.supersedes_record_id else None,
        created_at=record.created_at, updated_at=record.updated_at,
    )


def _context_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KnowledgeNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Context record was not found.")
    if isinstance(exc, KnowledgeConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Context changed or cannot be reconciled.")
    if isinstance(exc, (KnowledgeStoreError, ValueError)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Context request is invalid.")
    raise exc


@router.post("/api/v1/cortex/context/captures", response_model=ActionResponse)
def propose_context_capture(payload: ContextCaptureRequest) -> ActionResponse:
    """Create an approval-gated manual personal-context capture."""
    from core.api.routers.actions import _record_response
    from core.config import DEMO_MODE

    if DEMO_MODE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Actions are unavailable in demo mode.")
    try:
        reject_secret_text(payload.text)
    except ContextCaptureError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    service = get_action_service()
    if service is None or not service.supports(CAPABILITY_NAME):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Personal context capture is unavailable.")
    action = service.propose(
        agent_key="operator", capability_name=CAPABILITY_NAME,
        arguments={**payload.model_dump(), "_apex_provenance": {
            "source_kind": "manual", "partition": get_conversation_service().partition(),
            "original_text": payload.text,
        }}, target="Personal Context", risk="write", summary="Approve personal context capture", actor="operator",
    )
    return _record_response(action)


@router.get("/api/v1/cortex/context", response_model=list[ContextRecordResponse])
def list_context_records(
    status_filter: list[str] | None = Query(default=None, alias="status"),
    kind: str | None = Query(default=None),
    q: str = Query(default="", max_length=240),
    limit: int = Query(default=100, ge=1, le=100),
) -> list[ContextRecordResponse]:
    """List local context in the server-owned current partition."""
    try:
        records = get_knowledge_service().list_records(
            partition=get_conversation_service().partition(),
            statuses=tuple(status_filter or ("active", "conflicting")), kind=kind, query=q, limit=limit,
        )
        return [_context_record(record) for record in records]
    except Exception as exc:
        raise _context_error(exc) from exc


@router.get("/api/v1/cortex/context/entities", response_model=list[ContextEntityResponse])
def list_context_entities(
    q: str = Query(default="", max_length=240), limit: int = Query(default=50, ge=1, le=100),
) -> list[ContextEntityResponse]:
    try:
        service = get_knowledge_service()
        return [
            ContextEntityResponse(
                id=str(entity.id), name=entity.name,
                aliases=service.aliases_for_entity(entity.id) if get_conversation_service().partition() == "production" else [entity.name],
            )
            for entity in service.list_entities_in_partition(
                partition=get_conversation_service().partition(), query=q, limit=limit,
            )
        ]
    except Exception as exc:
        raise _context_error(exc) from exc


@router.get("/api/v1/cortex/context/{record_id}", response_model=ContextRecordDetailResponse)
def get_context_record(record_id: str) -> ContextRecordDetailResponse:
    from uuid import UUID

    try:
        service = get_knowledge_service()
        detail = service.get_record(UUID(record_id), partition=get_conversation_service().partition())
        related = []
        for entity_id in (detail.record.subject_entity_id, detail.record.object_entity_id):
            if entity_id is not None:
                related.extend(service.one_hop_relationships(entity_id, partition=detail.record.partition))
        related_by_id = {str(record.id): record for record in related if record.id != detail.record.id}
        base = _context_record(detail.record)
        return ContextRecordDetailResponse(
            **base.model_dump(),
            sources=[ContextSourceResponse(id=str(source.id), kind=source.kind, locator=source.locator, original_text=source.original_text, created_at=source.created_at) for source in detail.sources],
            superseded_by=[str(identifier) for identifier in detail.superseded_by],
            related_records=[_context_record(record) for record in list(related_by_id.values())[:20]],
        )
    except Exception as exc:
        raise _context_error(exc) from exc


@router.post("/api/v1/cortex/context/actions", response_model=ActionResponse)
def propose_context_action(payload: ContextActionRequest) -> ActionResponse:
    """Propose a frozen, approval-gated reconciliation operation."""
    from uuid import UUID
    from core.api.routers.actions import _record_response
    from core.config import DEMO_MODE

    if DEMO_MODE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Actions are unavailable in demo mode.")
    service = get_action_service()
    if service is None or not service.supports(RECONCILIATION_CAPABILITY_NAME):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Personal context reconciliation is unavailable.")
    try:
        knowledge = get_knowledge_service()
        partition = get_conversation_service().partition()
        arguments = payload.model_dump(mode="json")
        operation = str(arguments["operation"])
        target = "Personal Context"
        if operation in {"retract", "restore", "set_current", "correct"}:
            detail = knowledge.get_record(UUID(str(arguments["record_id"])), partition=partition)
            arguments["expected_updated_at"] = detail.record.updated_at
            if operation == "correct":
                reject_secret_text(str(arguments["capture"]["text"]))
            target = detail.record.text[:120]
        elif operation == "add_alias":
            entity = knowledge.get_entity(UUID(str(arguments["entity_id"])))
            if not knowledge.entity_in_partition(entity.id, partition=partition):
                raise KnowledgeNotFoundError("entity_not_found")
            target = entity.name
        elif operation == "merge_entities":
            source = knowledge.get_entity(UUID(str(arguments["source_entity_id"])))
            target_entity = knowledge.get_entity(UUID(str(arguments["target_entity_id"])))
            if not knowledge.entity_in_partition(source.id, partition=partition) or not knowledge.entity_in_partition(target_entity.id, partition=partition):
                raise KnowledgeNotFoundError("entity_not_found")
            if source.id == target_entity.id:
                raise KnowledgeConflictError("entity_merge_invalid")
            target = f"{source.name} → {target_entity.name}"
        arguments["partition"] = partition
        action = service.propose(
            agent_key="operator", capability_name=RECONCILIATION_CAPABILITY_NAME,
            arguments=arguments, target=target,
            risk="destructive" if operation == "retract" else "write",
            summary=f"Approve personal context {operation.replace('_', ' ')}", actor="operator",
        )
        return _record_response(action)
    except Exception as exc:
        raise _context_error(exc) from exc


def _ensure_agent_api_access(agent_key: str) -> None:
    """Reject unknown Agent keys at public API boundaries."""
    if agent_key not in AGENT_SPECS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Requested Agent is not available.",
        )


def _normalize_profile_id(value: str) -> str:
    candidate = value.strip().lower()
    if not _PROFILE_ID_PATTERN.fullmatch(candidate):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Profile IDs must start with a letter and contain only lowercase "
                "letters, numbers, and underscores."
            ),
        )
    return candidate


def _normalized_tool_names(names: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(name.strip() for name in names if name.strip()))


def _normalize_profile_name(value: str) -> str:
    candidate = " ".join(value.split())
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Profile names must contain at least one non-whitespace character.",
        )
    if len(candidate) > 80:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Profile names may contain at most 80 characters after normalization.",
        )
    return candidate


@router.get(
    "/api/v1/cortex/tool-catalog",
    response_model=ToolCatalogResponse,
)
def tool_catalog(model_id: str | None = None) -> ToolCatalogResponse:
    """Return the resolved tool catalog for the selected or requested model."""
    return build_tool_catalog("apex", model_id=model_id)


@router.post(
    "/api/v1/cortex/tool-preflight",
    response_model=ToolPreflightResponse,
)
def tool_preflight(payload: ToolPreflightRequest) -> ToolPreflightResponse:
    """Estimate the next request using model-facing selected tool schemas."""
    _ensure_agent_api_access(payload.agent)
    try:
        return build_tool_preflight(payload)
    except ConversationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation was not found.",
        ) from exc


def _conversation_error(error: Exception) -> HTTPException:
    if isinstance(error, ConversationNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, ConversationBusyError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="turn_in_progress")
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


@router.get(
    "/api/v1/cortex/retrieval/status",
    response_model=RetrievalStatusResponse,
)
def retrieval_status() -> RetrievalStatusResponse:
    return RetrievalStatusResponse(**get_retrieval_service().status().as_dict())


@router.post(
    "/api/v1/cortex/retrieval/prepare",
    response_model=RetrievalPrepareResponse,
)
def retrieval_prepare() -> RetrievalPrepareResponse:
    try:
        return RetrievalPrepareResponse(**get_retrieval_service().prepare().as_dict())
    except RetrievalBusyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="retrieval_prepare_in_progress") from exc


@router.get("/api/v1/cortex/conversations", response_model=list[ConversationSummary])
def list_conversations(archived: bool = False) -> list[ConversationSummary]:
    return get_conversation_service().list(archived)


@router.post(
    "/api/v1/cortex/conversations",
    response_model=ConversationSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(payload: ConversationCreateRequest) -> ConversationSummary:
    return get_conversation_service().create(payload)


@router.get(
    "/api/v1/cortex/conversations/{conversation_id}",
    response_model=ConversationDetail,
)
def get_conversation(conversation_id: str) -> ConversationDetail:
    from uuid import UUID

    try:
        return get_conversation_service().detail(UUID(conversation_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation was not found.") from exc
    except (ConversationNotFoundError, ConversationConflictError) as exc:
        raise _conversation_error(exc) from exc


@router.patch(
    "/api/v1/cortex/conversations/{conversation_id}",
    response_model=ConversationSummary,
)
def patch_conversation(conversation_id: str, payload: ConversationPatchRequest) -> ConversationSummary:
    from uuid import UUID

    try:
        return get_conversation_service().patch(UUID(conversation_id), payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation was not found.") from exc
    except (ConversationNotFoundError, ConversationConflictError) as exc:
        raise _conversation_error(exc) from exc


@router.delete(
    "/api/v1/cortex/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation(conversation_id: str) -> None:
    from uuid import UUID

    try:
        get_conversation_service().delete(UUID(conversation_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation was not found.") from exc
    except (ConversationNotFoundError, ConversationConflictError) as exc:
        raise _conversation_error(exc) from exc


def _turn_result(conversation_id, user, agent) -> ConversationTurnResult:
    metadata = agent.response_metadata or {}
    return ConversationTurnResult(
        conversation_id=conversation_id,
        user_message_id=user.id,
        agent_message_id=agent.id,
        active_leaf_message_id=agent.id,
        message_status=agent.status,
        answer=agent.content,
        **metadata,
    )


@router.post(
    "/api/v1/cortex/conversations/{conversation_id}/turns",
    response_model=ConversationTurnResult,
)
def conversation_turn(conversation_id: str, payload: ConversationTurnRequest) -> ConversationTurnResult:
    from uuid import UUID

    try:
        parsed_id = UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation was not found.") from exc
    service = get_conversation_service()
    try:
        detail = service.detail(parsed_id)
        agent_key = payload.agent or detail.agent
        selected_tools = (
            payload.selected_tool_names
            if "selected_tool_names" in payload.model_fields_set
            else detail.selected_tool_names
        )
        tool_profile_id = (
            payload.tool_profile_id
            if "tool_profile_id" in payload.model_fields_set
            else detail.tool_profile_id
        )
        request_metadata = {
            "effort": payload.effort,
            "selected_tool_names": selected_tools,
            "tool_profile_id": tool_profile_id,
            "snapshot_id": payload.snapshot_id,
            "briefing_id": payload.briefing_id,
            **_resolved_turn_metadata(payload),
        }
        user, agent_message, history, replayed = service.begin_turn(
            parsed_id,
            user_id=payload.user_message_id,
            agent_id=payload.agent_message_id,
            parent_id=payload.parent_message_id,
            prompt=payload.prompt,
            agent=agent_key,
            request_metadata=request_metadata,
            selected_tool_names=selected_tools,
            tool_profile_id=tool_profile_id,
        )
        if replayed:
            if agent_message.status == "completed":
                try:
                    get_retrieval_service().index_turn(user, agent_message, partition=service.partition())
                except Exception:
                    pass
            return _turn_result(parsed_id, user, agent_message)
    except (ConversationNotFoundError, ConversationConflictError) as exc:
        raise _conversation_error(exc) from exc

    execution_kwargs = {
        "prompt": payload.prompt,
        "agent": agent_key,
        "effort": payload.effort,
        "model_id": payload.model_id,
        "context_window": payload.context_window,
        "local_reasoning_mode": payload.local_reasoning_mode,
        "history": history,
        "history_partition": service.partition(),
        "tool_profile_id": tool_profile_id,
        "snapshot_id": payload.snapshot_id,
        "briefing_id": payload.briefing_id,
    }
    if selected_tools is not None:
        execution_kwargs["selected_tool_names"] = selected_tools
    execution_payload = AgentQueryRequest(
        **execution_kwargs,
    )
    context_policy = ContextPolicy.from_settings(
        agent=agent_key,
        partition=service.partition(),
        settings=get_settings_store().get_snapshot(),
        model_id=payload.model_id,
    )
    context_bundle = ContextAssembler(
        get_retrieval_service(), get_knowledge_service()
    ).assemble(
        prompt=payload.prompt,
        conversation_id=parsed_id,
        policy=context_policy,
    )
    try:
        response = query_agent(
            execution_payload,
            action_provenance={
                "source_kind": "conversation_message",
                "conversation_id": str(parsed_id),
                "message_id": str(user.id),
                "partition": service.partition(),
            },
            context_bundle=context_bundle,
        )
    except HTTPException as exc:
        failed = service.finalize(
            parsed_id,
            payload.agent_message_id,
            answer="",
            status="failed",
            response_metadata={"error": str(exc.detail)},
        )
        _ = failed
        raise
    response_data = response.model_dump(mode="json", exclude={"answer", "session_id"})
    completed = service.finalize(
        parsed_id,
        payload.agent_message_id,
        answer=response.answer,
        status="failed" if response.error else "completed",
        response_metadata=response_data,
    )
    if completed.status == "completed":
        try:
            get_retrieval_service().index_turn(user, completed, partition=service.partition())
        except Exception:
            # Retrieval is a repairable secondary index and must not change the
            # established successful-turn contract.
            pass
    return _turn_result(parsed_id, user, completed)


def _profile_response(
    *, affected_profile_id: str | None = None
) -> ToolProfilesResponse:
    snapshot = get_settings_store().get_snapshot()
    return ToolProfilesResponse(
        profiles=[
            ToolProfileMetadata(
                id=profile.id,
                name=profile.name,
                description=profile.description,
                tool_names=list(profile.tool_names),
                built_in=profile.built_in,
                dynamic=profile.dynamic,
            )
            for profile in list_tool_profiles()
        ],
        default_profile_by_runtime=dict(
            snapshot.tool_profiles.default_profile_by_runtime
        ),
        affected_profile_id=affected_profile_id,
    )


def _custom_profile_map() -> dict[str, ToolProfile]:
    snapshot = get_settings_store().get_snapshot()
    return {
        profile.id: profile for profile in snapshot.tool_profiles.custom_profiles
    }


def _persist_custom_profiles(
    profiles: list[ToolProfile],
    defaults: dict[str, str] | None = None,
    *,
    affected_profile_id: str | None = None,
) -> ToolProfilesResponse:
    snapshot = get_settings_store().get_snapshot()
    get_settings_store().apply_patch(
        SettingsPatch(
            tool_profiles=ToolProfilesPatch(
                custom_profiles=profiles,
                default_profile_by_runtime=(
                    defaults
                    if defaults is not None
                    else dict(snapshot.tool_profiles.default_profile_by_runtime)
                ),
            )
        )
    )
    return _profile_response(affected_profile_id=affected_profile_id)


@router.get(
    "/api/v1/cortex/tool-profiles",
    response_model=ToolProfilesResponse,
)
def tool_profiles() -> ToolProfilesResponse:
    """Return built-in and settings-backed tool profiles."""
    return _profile_response()


@router.post(
    "/api/v1/cortex/tool-profiles",
    response_model=ToolProfilesResponse,
)
def create_tool_profile(payload: ToolProfileCreateRequest) -> ToolProfilesResponse:
    """Persist a custom profile without changing MCP authorization settings."""
    normalized_name = _normalize_profile_name(payload.name)
    profile_id = payload.id
    if profile_id is None:
        profile_id = re.sub(r"[^a-z0-9]+", "_", normalized_name.lower()).strip("_")
    if not profile_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A profile ID could not be derived from the profile name.",
        )
    profile_id = _normalize_profile_id(profile_id)
    if get_tool_profile(profile_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A built-in or saved profile already uses that ID.",
        )
    profiles = _custom_profile_map()
    profiles[profile_id] = ToolProfile(
        id=profile_id,
        name=normalized_name,
        description=payload.description.strip(),
        tool_names=_normalized_tool_names(payload.tool_names),
    )
    return _persist_custom_profiles(
        list(profiles.values()),
        affected_profile_id=profile_id,
    )


@router.patch(
    "/api/v1/cortex/tool-profiles/{profile_id}",
    response_model=ToolProfilesResponse,
)
def update_tool_profile(
    profile_id: str,
    payload: ToolProfileUpdateRequest,
) -> ToolProfilesResponse:
    """Edit an existing custom profile while preserving stale tool references."""
    normalized_id = _normalize_profile_id(profile_id)
    profiles = _custom_profile_map()
    current = profiles.get(normalized_id)
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Only saved custom profiles can be edited.",
        )
    normalized_name = (
        _normalize_profile_name(payload.name) if payload.name is not None else current.name
    )
    profiles[normalized_id] = current.model_copy(
        update={
            "name": normalized_name,
            "description": (
                payload.description.strip()
                if payload.description is not None
                else current.description
            ),
            "tool_names": (
                _normalized_tool_names(payload.tool_names)
                if payload.tool_names is not None
                else current.tool_names
            ),
        }
    )
    return _persist_custom_profiles(
        list(profiles.values()),
        affected_profile_id=normalized_id,
    )


@router.delete(
    "/api/v1/cortex/tool-profiles/{profile_id}",
    response_model=ToolProfilesResponse,
)
def delete_tool_profile(profile_id: str) -> ToolProfilesResponse:
    """Delete a saved custom profile and clear defaults pointing to it."""
    normalized_id = _normalize_profile_id(profile_id)
    profiles = _custom_profile_map()
    if normalized_id not in profiles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Only saved custom profiles can be deleted.",
        )
    profiles.pop(normalized_id)
    snapshot = get_settings_store().get_snapshot()
    defaults = {
        agent: selected
        for agent, selected in snapshot.tool_profiles.default_profile_by_runtime.items()
        if selected != normalized_id
    }
    return _persist_custom_profiles(
        list(profiles.values()),
        defaults,
        affected_profile_id=normalized_id,
    )


@router.post(
    "/api/v1/cortex/tool-profiles/default",
    response_model=ToolProfilesResponse,
)
def set_tool_profile_default(
    payload: ToolProfileDefaultRequest,
) -> ToolProfilesResponse:
    """Assign a built-in or saved profile as one Agent's default."""
    profile_id = _normalize_profile_id(payload.profile_id)
    if get_tool_profile(profile_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested tool profile does not exist.",
        )
    snapshot = get_settings_store().get_snapshot()
    defaults = dict(snapshot.tool_profiles.default_profile_by_runtime)
    defaults[payload.runtime] = profile_id
    return _persist_custom_profiles(
        list(snapshot.tool_profiles.custom_profiles),
        defaults,
        affected_profile_id=profile_id,
    )


@router.get("/api/v1/cortex/agent", response_model=CortexAgentResponse)
def cortex_agent() -> CortexAgentResponse:
    """Return the native Agent and its unified model catalog."""
    from core.api.cortex import build_model_catalog

    settings = get_settings_store().get_snapshot().ask_apex
    catalog = build_model_catalog()
    return CortexAgentResponse(
        description=AGENT_SPECS["apex"].description,
        selected_model=settings.selected_model,
        model_catalog=catalog,
    )


@router.post(
    "/api/v1/cortex/models/verify",
    response_model=CloudAgentVerificationResponse,
)
def verify_model(payload: ModelVerificationRequest) -> CloudAgentVerificationResponse:
    """Verify a cloud model without generating a turn."""
    profile = get_model_profile(payload.model_id)
    if profile is None or profile.runtime != "cloud":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Only cloud models can be verified.")
    return verify_cloud_agent_endpoint(payload.model_id)


@router.post(
    "/api/v1/cortex/local-model/unload",
    response_model=LocalUnloadResponse,
    operation_id="unload_active_local_model_endpoint_api_v1_cortex_local_model_unload_post",
    summary="Unload Active Local Model Endpoint",
)
def unload_local_model() -> LocalUnloadResponse:
    """
    Manually unload the currently active local model from memory.

    Returns success when no model is active or the unload completes cleanly.
    """
    return unload_active_local_model_endpoint()


@router.post(
    "/api/v1/cortex/local-model/load",
    response_model=LocalLoadResponse,
    operation_id="load_local_model_endpoint_api_v1_cortex_local_model_load_post",
    summary="Load Local Model Endpoint",
)
def load_local_model(payload: LocalLoadRequest) -> LocalLoadResponse:
    """Pre-warm a selected local model and confirm it is resident."""
    return load_local_model_endpoint(payload.model_id)
