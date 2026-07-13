"""Assistant profile, query, and local model control routes."""

from __future__ import annotations

from fastapi import APIRouter

from core.agent.types import AgentQueryRequest, AgentQueryResponse
from core.api.assistant import (
    build_agent_profile_statuses,
    query_agent,
    unload_active_local_model_endpoint,
)
from core.api.models import AgentProfileStatus, LocalUnloadResponse

router = APIRouter(tags=["assistant"])


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
    "/api/v1/agent/local/unload",
    response_model=LocalUnloadResponse,
)
@router.post(
    "/api/v1/local-model/unload",
    response_model=LocalUnloadResponse,
)
def unload_local_model() -> LocalUnloadResponse:
    """
    Manually unload the currently active local Ollama model from memory.

    Returns success when no model is active or the unload completes cleanly.
    """
    return unload_active_local_model_endpoint()


@router.post("/api/v1/agent/query", response_model=AgentQueryResponse)
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
