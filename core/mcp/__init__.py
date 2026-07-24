"""APEX MCP client runtime: config loading, lifecycle manager, and status."""

from __future__ import annotations

from core.mcp.config import load_mcp_config
from core.mcp.manager import MCPClientManager
from core.mcp.models import (
    McpRuntimeConfig,
    McpServerConfig,
    McpServerStatus,
    McpStatusResponse,
    empty_mcp_status,
)

__all__ = [
    "MCPClientManager",
    "McpRuntimeConfig",
    "McpServerConfig",
    "McpServerStatus",
    "McpStatusResponse",
    "empty_mcp_status",
    "get_mcp_manager",
    "load_mcp_config",
    "set_mcp_manager",
]

_MANAGER: MCPClientManager | None = None


def get_mcp_manager() -> MCPClientManager | None:
    """Return the process-wide MCP client manager, if started."""
    return _MANAGER


def set_mcp_manager(manager: MCPClientManager | None) -> None:
    """Install or clear the process-wide MCP client manager."""
    global _MANAGER
    _MANAGER = manager
