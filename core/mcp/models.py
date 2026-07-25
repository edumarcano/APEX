"""MCP client configuration and status models."""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

McpTransport = Literal["http", "stdio"]
McpToolRisk = Literal["read", "write", "destructive"]
McpServerStatusValue = Literal[
    "configured",
    "connected",
    "degraded",
    "disabled",
    "authentication-required",
]

_LOGGER = logging.getLogger(__name__)


class McpServerConfig(BaseModel):
    """Non-secret configuration for one external MCP server."""

    enabled: bool = False
    transport: McpTransport = "http"
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    tool_allowlist: list[str] = Field(default_factory=list)
    tool_risks: dict[str, McpToolRisk] = Field(default_factory=dict)
    tool_argument_maximums: dict[str, dict[str, int]] = Field(default_factory=dict)
    expose_to_client_display: bool = False
    timeout_seconds: float = Field(default=30.0, gt=0)
    connect_timeout_seconds: float = Field(default=30.0, gt=0)
    max_output_chars: int = Field(default=50_000, gt=0)
    oauth: bool = False
    auth_env: str | None = None
    header_env: dict[str, str] = Field(default_factory=dict)


class McpRuntimeConfig(BaseModel):
    """Top-level MCP client runtime configuration."""

    enabled: bool = False
    servers: dict[str, McpServerConfig] = Field(default_factory=dict)


class McpServerStatus(BaseModel):
    """Sanitized per-server status for diagnostics."""

    id: str
    enabled: bool
    transport: McpTransport
    status: McpServerStatusValue
    reason: str
    registered_tools: list[str] = Field(default_factory=list)


class McpStatusResponse(BaseModel):
    """Public MCP client status payload."""

    enabled: bool
    status: McpServerStatusValue
    reason: str
    servers: list[McpServerStatus] = Field(default_factory=list)


def empty_mcp_status(*, reason: str = "MCP client runtime is disabled.") -> McpStatusResponse:
    """Return a disabled status snapshot with no servers."""
    return McpStatusResponse(
        enabled=False,
        status="disabled",
        reason=reason,
        servers=[],
    )


def parse_server_config(raw: dict[str, Any]) -> McpServerConfig:
    """Parse a single server object with tolerant defaults."""
    transport_raw = raw.get("transport", "http")
    transport: McpTransport = "http"
    if isinstance(transport_raw, str) and transport_raw.strip().lower() in ("http", "stdio"):
        transport = transport_raw.strip().lower()  # type: ignore[assignment]

    allowlist_raw = raw.get("tool_allowlist", [])
    allowlist: list[str] = []
    if isinstance(allowlist_raw, list):
        allowlist = [str(item).strip() for item in allowlist_raw if str(item).strip()]

    tool_risks_raw = raw.get("tool_risks", {})
    tool_risks: dict[str, McpToolRisk] = {}
    if isinstance(tool_risks_raw, dict):
        for key, value in tool_risks_raw.items():
            if (
                isinstance(key, str)
                and key.strip()
                and isinstance(value, str)
                and value.strip().lower() in ("read", "write", "destructive")
            ):
                tool_risks[key.strip()] = value.strip().lower()  # type: ignore[assignment]

    maximums_raw = raw.get("tool_argument_maximums", {})
    tool_argument_maximums: dict[str, dict[str, int]] = {}
    if isinstance(maximums_raw, dict):
        for tool_name, arguments_raw in maximums_raw.items():
            if not isinstance(tool_name, str) or not tool_name.strip():
                continue
            if not isinstance(arguments_raw, dict):
                continue
            argument_maximums: dict[str, int] = {}
            for argument_name, maximum_raw in arguments_raw.items():
                if not isinstance(argument_name, str) or not argument_name.strip():
                    continue
                if isinstance(maximum_raw, bool):
                    continue
                try:
                    maximum = int(maximum_raw)
                except (TypeError, ValueError):
                    continue
                if maximum > 0:
                    argument_maximums[argument_name.strip()] = maximum
            if argument_maximums:
                tool_argument_maximums[tool_name.strip()] = argument_maximums

    args_raw = raw.get("args", [])
    args: list[str] = []
    if isinstance(args_raw, list):
        args = [str(item) for item in args_raw]

    header_env_raw = raw.get("header_env", {})
    header_env: dict[str, str] = {}
    if isinstance(header_env_raw, dict):
        for key, value in header_env_raw.items():
            if isinstance(key, str) and isinstance(value, str) and key.strip() and value.strip():
                header_env[key.strip()] = value.strip()

    timeout = raw.get("timeout_seconds", 30.0)
    try:
        timeout_seconds = float(timeout)
        if timeout_seconds <= 0:
            timeout_seconds = 30.0
    except (TypeError, ValueError):
        timeout_seconds = 30.0

    connect_timeout = raw.get("connect_timeout_seconds", 30.0)
    try:
        connect_timeout_seconds = float(connect_timeout)
        if connect_timeout_seconds <= 0:
            connect_timeout_seconds = 30.0
    except (TypeError, ValueError):
        connect_timeout_seconds = 30.0

    max_chars = raw.get("max_output_chars", 50_000)
    try:
        max_output_chars = int(max_chars)
        if max_output_chars <= 0:
            max_output_chars = 50_000
    except (TypeError, ValueError):
        max_output_chars = 50_000

    auth_env = raw.get("auth_env")
    auth_env_name = (
        auth_env.strip()
        if isinstance(auth_env, str) and auth_env.strip()
        else None
    )

    url = raw.get("url")
    url_value = url.strip() if isinstance(url, str) and url.strip() else None

    command = raw.get("command")
    command_value = (
        command.strip() if isinstance(command, str) and command.strip() else None
    )

    cwd = raw.get("cwd")
    cwd_value = cwd.strip() if isinstance(cwd, str) and cwd.strip() else None

    enabled_raw = raw.get("enabled", False)
    enabled = enabled_raw if isinstance(enabled_raw, bool) else False
    if not isinstance(enabled_raw, bool):
        _LOGGER.warning(
            'MCP server key "enabled" must be a boolean; defaulting to false.'
        )

    expose_raw = raw.get("expose_to_client_display", False)
    expose_to_client_display = expose_raw if isinstance(expose_raw, bool) else False
    if not isinstance(expose_raw, bool):
        _LOGGER.warning(
            'MCP server key "expose_to_client_display" must be a boolean; '
            "defaulting to false."
        )

    oauth_raw = raw.get("oauth", False)
    oauth = oauth_raw if isinstance(oauth_raw, bool) else False
    if not isinstance(oauth_raw, bool):
        _LOGGER.warning(
            'MCP server key "oauth" must be a boolean; defaulting to false.'
        )

    return McpServerConfig(
        enabled=enabled,
        transport=transport,
        url=url_value,
        command=command_value,
        args=args,
        cwd=cwd_value,
        tool_allowlist=allowlist,
        tool_risks=tool_risks,
        tool_argument_maximums=tool_argument_maximums,
        expose_to_client_display=expose_to_client_display,
        timeout_seconds=timeout_seconds,
        connect_timeout_seconds=connect_timeout_seconds,
        max_output_chars=max_output_chars,
        oauth=oauth,
        auth_env=auth_env_name,
        header_env=header_env,
    )
