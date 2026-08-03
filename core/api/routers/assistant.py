"""Assistant profile, query, and local model control routes."""

from __future__ import annotations

from fastapi import APIRouter

from core.agent.types import AgentQueryRequest, AgentQueryResponse, LocalCommandStatus
from core.api.assistant import (
    build_agent_profile_statuses,
    build_local_command_statuses,
    load_local_model_endpoint,
    query_agent,
    unload_active_local_model_endpoint,
    verify_cloud_profile_endpoint,
)
from core.api.models import (
    AgentProfileStatus,
    CloudProfileVerificationResponse,
    LocalLoadRequest,
    LocalLoadResponse,
    LocalUnloadResponse,
)

router = APIRouter(tags=["assistant"])


@router.get(
    "/api/v1/agent/commands",
    response_model=list[LocalCommandStatus],
)
def list_local_commands() -> list[LocalCommandStatus]:
    """Return local-only command bundles and current provider availability."""
    return build_local_command_statuses()


@router.get("/api/v1/agent/profiles", response_model=list[AgentProfileStatus])
def list_agent_profiles() -> list[AgentProfileStatus]:
    """
    Return profile availability for local and cloud assistant modes.

    Ollama reachability, installed tags, and host vitals come from a shared
    TTL snapshot (single /api/tags probe at most once per 10 seconds), so
    frequent HUD polling never floods the daemon while a model is generating.
    """
    return build_agent_profile_statuses()


@router.post(
    "/api/v1/agent/profiles/{profile_key}/verify",
    response_model=CloudProfileVerificationResponse,
)
def verify_agent_profile(profile_key: str) -> CloudProfileVerificationResponse:
    """Verify configured cloud credentials and model access without inference."""
    return verify_cloud_profile_endpoint(profile_key)


@router.post(
    "/api/v1/agent/local/unload",
    response_model=LocalUnloadResponse,
    operation_id="unload_active_local_model_endpoint_api_v1_agent_local_unload_post",
    summary="Unload Active Local Model Endpoint",
)
@router.post(
    "/api/v1/local-model/unload",
    response_model=LocalUnloadResponse,
    operation_id="unload_active_local_model_endpoint_api_v1_local_model_unload_post",
    summary="Unload Active Local Model Endpoint",
)
def unload_local_model() -> LocalUnloadResponse:
    """
    Manually unload the currently active local Ollama model from memory.

    Returns success when no model is active or the unload completes cleanly.
    """
    return unload_active_local_model_endpoint()


@router.post(
    "/api/v1/local-model/load",
    response_model=LocalLoadResponse,
    operation_id="load_local_model_endpoint_api_v1_local_model_load_post",
    summary="Load Local Model Endpoint",
)
def load_local_model(payload: LocalLoadRequest) -> LocalLoadResponse:
    """Pre-warm a selected local profile and confirm it is resident."""
    return load_local_model_endpoint(payload.profile)


@router.post(
    "/api/v1/agent/query",
    response_model=AgentQueryResponse,
    operation_id="query_agent_api_v1_agent_query_post",
    summary="Query Agent",
)
def agent_query(payload: AgentQueryRequest) -> AgentQueryResponse:
    """
    Execute an APEX assistant turn with optional tool calling.

    Runs synchronously so uvicorn can offload blocking provider I/O to a
    worker thread. Local (Ollama) queries pass an admission gate first:
    a non-blocking execution slot (429 when busy), a host resource gate for
    cold loads/switches (503 with the gate reason), and a coordinated model
    switch (503 on load failure). Already-loaded target models bypass the
    resource gate because their memory footprint is already present.
    """
    return query_agent(payload)
