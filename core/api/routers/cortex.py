"""Cortex Engine routes for Agent catalog, queries, and local runtime control."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, status

from core.agent.catalog import AGENT_SPECS
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
from core.api.cortex import (
    build_agent_statuses,
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
from core.api.models import (
    AgentStatus,
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
)

router = APIRouter(tags=["cortex"])
_PROFILE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


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
def tool_catalog(agent: AgentKey = "panthera") -> ToolCatalogResponse:
    """Return the resolved selector catalog for one Apex Agent."""
    _ensure_agent_api_access(agent)
    return build_tool_catalog(agent)


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
    try:
        response = query_agent(execution_payload)
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
        default_profile_by_agent=dict(
            snapshot.tool_profiles.default_profile_by_agent
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
                default_profile_by_agent=(
                    defaults
                    if defaults is not None
                    else dict(snapshot.tool_profiles.default_profile_by_agent)
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
        for agent, selected in snapshot.tool_profiles.default_profile_by_agent.items()
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
    defaults = dict(snapshot.tool_profiles.default_profile_by_agent)
    defaults[payload.agent] = profile_id
    return _persist_custom_profiles(
        list(snapshot.tool_profiles.custom_profiles),
        defaults,
        affected_profile_id=profile_id,
    )


@router.get("/api/v1/agents", response_model=list[AgentStatus])
def list_agents() -> list[AgentStatus]:
    """
    Return visible Apex Agent status for cloud and local runtimes.

    Local provider reachability, installed models, and host vitals come from
    cached backend snapshots and the global coordinator, so frequent HUD
    polling never floods a local daemon while a model is generating.
    """
    return build_agent_statuses()


@router.post(
    "/api/v1/agents/{agent_key}/verify",
    response_model=CloudAgentVerificationResponse,
)
def verify_agent(agent_key: str) -> CloudAgentVerificationResponse:
    """Verify configured cloud credentials and model access without inference."""
    _ensure_agent_api_access(agent_key)
    return verify_cloud_agent_endpoint(agent_key)


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
    """Pre-warm a selected local Agent and confirm it is resident."""
    return load_local_model_endpoint(payload.agent)
