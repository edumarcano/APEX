"""MCP client status routes."""

from __future__ import annotations

from fastapi import APIRouter

from core.mcp import empty_mcp_status, get_mcp_manager
from core.mcp.models import McpStatusResponse

router = APIRouter(tags=["mcp"])


@router.get("/api/v1/mcp/status", response_model=McpStatusResponse)
def mcp_status() -> McpStatusResponse:
    """
    Return sanitized MCP client connection status for each configured server.

    Never includes credentials, authorization headers, environment values, or
    raw upstream exception text.
    """
    manager = get_mcp_manager()
    if manager is None:
        return empty_mcp_status()
    return manager.status_snapshot()
