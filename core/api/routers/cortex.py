"""Cortex Engine routes for Agent catalog, queries, and local runtime control."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, status

from core.agent.catalog import AGENT_SPECS, resolve_agent_selection
from core.agent.types import (
    AgentKey,
    AgentQueryRequest,
    AgentQueryResponse,
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


def _resolve_omitted_agent(payload: AgentQueryRequest) -> AgentQueryRequest:
    """Apply the saved Agent selection when the caller omitted ``agent``."""
    if "agent" in payload.model_fields_set:
        return payload
    snapshot = get_settings_store().get_snapshot()
    _runtime, agent, _effort = resolve_agent_selection(snapshot.ask_apex)
    return payload.model_copy(update={"agent": agent})


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
    return build_tool_preflight(payload)


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


@router.post(
    "/api/v1/cortex/query",
    response_model=AgentQueryResponse,
    operation_id="cortex_query_api_v1_cortex_query_post",
    summary="Query Agent",
)
def cortex_query(payload: AgentQueryRequest) -> AgentQueryResponse:
    """
    Execute one Cortex Engine turn for the selected Apex Agent.

    Runs synchronously so uvicorn can offload blocking provider I/O to a
    worker thread. Local Agent queries pass an admission gate first:
    a non-blocking execution slot (429 when busy), a host resource gate for
    cold loads/switches (503 with the gate reason), and a coordinated model
    switch (503 on load failure). Already-loaded target models bypass the
    resource gate because their memory footprint is already present.
    """
    effective_payload = _resolve_omitted_agent(payload)
    _ensure_agent_api_access(effective_payload.agent)
    return query_agent(effective_payload)
