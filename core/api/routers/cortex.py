"""Cortex Engine routes for Agent catalog, queries, and local runtime control."""

from __future__ import annotations

from fastapi import APIRouter

from core.agent.types import AgentQueryRequest, AgentQueryResponse, LocalCommandStatus
from core.api.cortex import (
    build_agent_statuses,
    build_local_command_statuses,
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
)

router = APIRouter(tags=["cortex"])


@router.get(
    "/api/v1/cortex/tool-scopes",
    response_model=list[LocalCommandStatus],
)
def list_local_commands() -> list[LocalCommandStatus]:
    """Return local-only command bundles and current provider availability."""
    return build_local_command_statuses()


@router.get("/api/v1/agents", response_model=list[AgentStatus])
def list_agents() -> list[AgentStatus]:
    """
    Return visible Apex Agent status for cloud and local runtimes.

    Ollama reachability, installed tags, and host vitals come from a shared
    TTL snapshot (single /api/tags probe at most once per 10 seconds), so
    frequent HUD polling never floods the daemon while a model is generating.
    """
    return build_agent_statuses()


@router.post(
    "/api/v1/agents/{agent_key}/verify",
    response_model=CloudAgentVerificationResponse,
)
def verify_agent(agent_key: str) -> CloudAgentVerificationResponse:
    """Verify configured cloud credentials and model access without inference."""
    return verify_cloud_agent_endpoint(agent_key)


@router.post(
    "/api/v1/cortex/local-model/unload",
    response_model=LocalUnloadResponse,
    operation_id="unload_active_local_model_endpoint_api_v1_cortex_local_model_unload_post",
    summary="Unload Active Local Model Endpoint",
)
def unload_local_model() -> LocalUnloadResponse:
    """
    Manually unload the currently active local Ollama model from memory.

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
    worker thread. Local (Ollama) queries pass an admission gate first:
    a non-blocking execution slot (429 when busy), a host resource gate for
    cold loads/switches (503 with the gate reason), and a coordinated model
    switch (503 on load failure). Already-loaded target models bypass the
    resource gate because their memory footprint is already present.
    """
    return query_agent(payload)
