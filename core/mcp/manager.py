"""Lifecycle manager for external MCP client connections."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport

from core.agent.capabilities import (
    CapabilityDescriptor,
    CapabilityError,
    CapabilityErrorCategory,
    namespaced_capability_name,
    register_capability,
    unregister_capability,
)
from core.mcp.models import (
    McpRuntimeConfig,
    McpServerConfig,
    McpServerStatus,
    McpServerStatusValue,
    McpStatusResponse,
    empty_mcp_status,
)

_LOGGER = logging.getLogger(__name__)

_LOCAL_NAME_SANITIZE = re.compile(r"[^a-z0-9_]+")
_STATUS_PRIORITY: tuple[McpServerStatusValue, ...] = (
    "authentication-required",
    "degraded",
    "configured",
    "connected",
    "disabled",
)


@dataclass
class _ServerRuntime:
    config: McpServerConfig
    status: McpServerStatusValue = "disabled"
    reason: str = "MCP server is disabled."
    client: Client[Any] | None = None
    registered_names: list[str] = field(default_factory=list)
    remote_tool_names: dict[str, str] = field(default_factory=dict)


class MCPClientManager:
    """Own FastMCP client sessions, discovery, and sync invoke bridging."""

    def __init__(self, config: McpRuntimeConfig) -> None:
        self._config = config
        self._loop: asyncio.AbstractEventLoop | None = None
        self._servers: dict[str, _ServerRuntime] = {}
        self._discovery_tasks: list[asyncio.Task[None]] = []
        self._lock = threading.RLock()
        self._started = False
        self._shutting_down = False

        for server_id, server_config in config.servers.items():
            initial_status: McpServerStatusValue = (
                "disabled" if not server_config.enabled else "configured"
            )
            reason = (
                "MCP server is disabled."
                if not server_config.enabled
                else "MCP server is configured and awaiting connection."
            )
            self._servers[server_id] = _ServerRuntime(
                config=server_config,
                status=initial_status,
                reason=reason,
            )

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    async def start(self) -> None:
        """Schedule non-blocking discovery tasks on the application event loop."""
        if self._started:
            return
        self._started = True
        self._loop = asyncio.get_running_loop()

        if not self._config.enabled:
            return

        for server_id, runtime in self._servers.items():
            if not runtime.config.enabled:
                continue
            task = asyncio.create_task(
                self._connect_and_discover(server_id),
                name=f"mcp-discover-{server_id}",
            )
            self._discovery_tasks.append(task)

    async def shutdown(self) -> None:
        """Cancel discovery, close transports, and unregister MCP capabilities."""
        self._shutting_down = True
        for task in self._discovery_tasks:
            task.cancel()
        if self._discovery_tasks:
            await asyncio.gather(*self._discovery_tasks, return_exceptions=True)
        self._discovery_tasks.clear()

        with self._lock:
            server_ids = list(self._servers.keys())

        for server_id in server_ids:
            await self._teardown_server(server_id)

        self._started = False
        self._loop = None

    def status_snapshot(self) -> McpStatusResponse:
        """Return a sanitized status payload with no secrets or exception text."""
        if not self._config.enabled:
            return empty_mcp_status()

        with self._lock:
            servers = [
                McpServerStatus(
                    id=server_id,
                    enabled=runtime.config.enabled,
                    transport=runtime.config.transport,
                    status=runtime.status,
                    reason=runtime.reason,
                    registered_tools=list(runtime.registered_names),
                )
                for server_id, runtime in self._servers.items()
            ]

        if not servers:
            return McpStatusResponse(
                enabled=True,
                status="configured",
                reason="MCP client runtime is enabled with no configured servers.",
                servers=[],
            )

        enabled_servers = [server for server in servers if server.enabled]
        if not enabled_servers:
            return McpStatusResponse(
                enabled=True,
                status="disabled",
                reason="All configured MCP servers are disabled.",
                servers=servers,
            )

        aggregate = _aggregate_status([server.status for server in enabled_servers])
        reason = _aggregate_reason(aggregate, enabled_servers)
        return McpStatusResponse(
            enabled=True,
            status=aggregate,
            reason=reason,
            servers=servers,
        )

    def invoke_tool_sync(
        self,
        server_id: str,
        capability_name: str,
        arguments: dict[str, Any],
        timeout_seconds: float,
    ) -> Any:
        """Bridge a synchronous capability call onto the application event loop."""
        loop = self._loop
        if loop is None or not self._started or self._shutting_down:
            raise CapabilityError(
                CapabilityErrorCategory.UNAVAILABLE,
                f"MCP capability '{capability_name}' is unavailable.",
            )

        with self._lock:
            runtime = self._servers.get(server_id)
            if runtime is None or runtime.client is None or runtime.status != "connected":
                raise CapabilityError(
                    CapabilityErrorCategory.UNAVAILABLE,
                    f"MCP capability '{capability_name}' is unavailable.",
                )
            remote_name = runtime.remote_tool_names.get(capability_name)
            if remote_name is None:
                raise CapabilityError(
                    CapabilityErrorCategory.UNAVAILABLE,
                    f"MCP capability '{capability_name}' is unavailable.",
                )
            client = runtime.client

        coro = self._call_tool(client, remote_name, arguments, timeout_seconds)
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout=timeout_seconds + 1.0)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise CapabilityError(
                CapabilityErrorCategory.TIMEOUT,
                "Capability invocation timed out.",
            ) from exc
        except CapabilityError:
            raise
        except Exception as exc:
            mapped = _map_exception(exc)
            raise mapped from exc

    async def _connect_and_discover(self, server_id: str) -> None:
        if self._shutting_down:
            return

        with self._lock:
            runtime = self._servers[server_id]
            config = runtime.config

        auth_token, headers, auth_error = _resolve_auth(config)
        if auth_error is not None:
            self._set_status(
                server_id,
                "authentication-required",
                auth_error,
            )
            return

        try:
            client = _build_client(config, auth_token=auth_token, headers=headers)
        except Exception:
            _LOGGER.warning(
                "Failed to configure MCP server %s; marking degraded.",
                server_id,
                exc_info=True,
            )
            self._set_status(
                server_id,
                "degraded",
                "MCP server configuration is invalid.",
            )
            return

        try:
            await asyncio.wait_for(
                client.__aenter__(),
                timeout=config.timeout_seconds,
            )
        except asyncio.TimeoutError:
            _LOGGER.warning("Timed out connecting to MCP server %s.", server_id)
            self._set_status(
                server_id,
                "degraded",
                "MCP server connection timed out.",
            )
            await _safe_close(client)
            return
        except asyncio.CancelledError:
            await _safe_close(client)
            raise
        except Exception as exc:
            category = _classify_connect_error(exc)
            if category == CapabilityErrorCategory.AUTHENTICATION:
                self._set_status(
                    server_id,
                    "authentication-required",
                    "MCP server authentication failed.",
                )
            else:
                _LOGGER.warning(
                    "MCP server %s is offline or unreachable.",
                    server_id,
                    exc_info=True,
                )
                self._set_status(
                    server_id,
                    "degraded",
                    "MCP server is offline or unreachable.",
                )
            await _safe_close(client)
            return

        if self._shutting_down:
            await _safe_close(client)
            return

        try:
            tools = await asyncio.wait_for(
                client.list_tools(),
                timeout=config.timeout_seconds,
            )
        except asyncio.TimeoutError:
            self._set_status(
                server_id,
                "degraded",
                "MCP tool discovery timed out.",
            )
            await _safe_close(client)
            return
        except asyncio.CancelledError:
            await _safe_close(client)
            raise
        except Exception:
            _LOGGER.warning(
                "MCP tool discovery failed for server %s.",
                server_id,
                exc_info=True,
            )
            self._set_status(
                server_id,
                "degraded",
                "MCP tool discovery failed.",
            )
            await _safe_close(client)
            return

        allowlist = set(config.tool_allowlist)
        registered: list[str] = []
        remote_map: dict[str, str] = {}

        for tool in tools:
            remote_name = getattr(tool, "name", None)
            if not isinstance(remote_name, str) or not remote_name:
                continue
            if remote_name not in allowlist:
                continue

            local_name = _normalize_local_tool_name(remote_name)
            try:
                capability_name = namespaced_capability_name(server_id, local_name)
            except ValueError:
                _LOGGER.warning(
                    "Skipping MCP tool %r on server %s; invalid capability name.",
                    remote_name,
                    server_id,
                )
                continue

            input_schema = getattr(tool, "inputSchema", None)
            if not isinstance(input_schema, dict):
                input_schema = {"type": "object", "properties": {}}
            elif input_schema.get("type") != "object":
                input_schema = {
                    "type": "object",
                    "properties": input_schema.get("properties") or {},
                }

            description = getattr(tool, "description", None)
            if not isinstance(description, str) or not description.strip():
                description = f"MCP tool {remote_name} from server {server_id}."

            title = remote_name.replace("_", " ").strip().title() or capability_name

            handler = _make_sync_handler(self, server_id, capability_name)
            descriptor = CapabilityDescriptor(
                name=capability_name,
                title=title,
                description=description.strip(),
                input_schema=input_schema,
                origin="mcp",
                risk="read",
                expose_to_assistant=True,
                expose_to_mcp_server=False,
                expose_to_client_display=False,
                timeout_seconds=config.timeout_seconds,
                max_output_chars=config.max_output_chars,
            )
            try:
                register_capability(descriptor, handler)
            except ValueError:
                _LOGGER.warning(
                    "Skipping duplicate or invalid MCP capability %s.",
                    capability_name,
                    exc_info=True,
                )
                continue

            registered.append(capability_name)
            remote_map[capability_name] = remote_name

        with self._lock:
            runtime = self._servers[server_id]
            runtime.client = client
            runtime.registered_names = registered
            runtime.remote_tool_names = remote_map
            runtime.status = "connected"
            if not allowlist:
                runtime.reason = (
                    "MCP server connected; tool allowlist is empty so no tools "
                    "were registered."
                )
            elif not registered:
                runtime.reason = (
                    "MCP server connected; no allowlisted tools were advertised."
                )
            else:
                runtime.reason = (
                    f"MCP server connected with {len(registered)} registered tool(s)."
                )

    async def _teardown_server(self, server_id: str) -> None:
        with self._lock:
            runtime = self._servers.get(server_id)
            if runtime is None:
                return
            client = runtime.client
            registered = list(runtime.registered_names)
            runtime.client = None
            runtime.registered_names = []
            runtime.remote_tool_names = {}
            if runtime.config.enabled:
                runtime.status = "configured"
                runtime.reason = "MCP server connection is closed."
            else:
                runtime.status = "disabled"
                runtime.reason = "MCP server is disabled."

        for name in registered:
            unregister_capability(name)

        if client is not None:
            await _safe_close(client)

    async def _call_tool(
        self,
        client: Client[Any],
        remote_name: str,
        arguments: dict[str, Any],
        timeout_seconds: float,
    ) -> Any:
        try:
            result = await asyncio.wait_for(
                client.call_tool(remote_name, arguments or {}, raise_on_error=False),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise CapabilityError(
                CapabilityErrorCategory.TIMEOUT,
                "Capability invocation timed out.",
            ) from exc
        except Exception as exc:
            raise _map_exception(exc) from exc

        if getattr(result, "is_error", False):
            raise CapabilityError(
                CapabilityErrorCategory.UPSTREAM_FAILURE,
                "Tool execution failed.",
            )

        return _serialize_tool_result(result)

    def _set_status(
        self,
        server_id: str,
        status: McpServerStatusValue,
        reason: str,
    ) -> None:
        with self._lock:
            runtime = self._servers[server_id]
            runtime.status = status
            runtime.reason = reason


def _make_sync_handler(
    manager: MCPClientManager,
    server_id: str,
    capability_name: str,
):
    def _handler(**kwargs: Any) -> Any:
        with manager._lock:
            runtime = manager._servers.get(server_id)
            timeout = (
                runtime.config.timeout_seconds
                if runtime is not None
                else 30.0
            )
        return manager.invoke_tool_sync(
            server_id,
            capability_name,
            dict(kwargs),
            timeout,
        )

    return _handler


def _build_client(
    config: McpServerConfig,
    *,
    auth_token: str | None,
    headers: dict[str, str],
) -> Client[Any]:
    if config.transport == "http":
        if not config.url:
            raise ValueError("HTTP MCP servers require a url.")
        transport = StreamableHttpTransport(
            url=config.url,
            headers=headers or None,
            auth=auth_token,
        )
        return Client(transport, timeout=config.timeout_seconds)

    if not config.command:
        raise ValueError("stdio MCP servers require a command.")
    env: dict[str, str] | None = None
    if config.auth_env and auth_token is not None:
        env = {config.auth_env: auth_token}
    transport = StdioTransport(
        command=config.command,
        args=list(config.args),
        env=env,
        cwd=config.cwd,
    )
    return Client(transport, timeout=config.timeout_seconds)


def _resolve_auth(
    config: McpServerConfig,
) -> tuple[str | None, dict[str, str], str | None]:
    auth_token: str | None = None
    if config.auth_env:
        value = os.environ.get(config.auth_env, "").strip()
        if not value:
            return (
                None,
                {},
                f"Environment variable '{config.auth_env}' is required for authentication.",
            )
        auth_token = value

    headers: dict[str, str] = {}
    for header_name, env_name in config.header_env.items():
        value = os.environ.get(env_name, "").strip()
        if not value:
            return (
                None,
                {},
                f"Environment variable '{env_name}' is required for authentication.",
            )
        headers[header_name] = value

    return auth_token, headers, None


def _normalize_local_tool_name(remote_name: str) -> str:
    lowered = remote_name.strip().lower().replace("-", "_").replace(".", "_")
    cleaned = _LOCAL_NAME_SANITIZE.sub("_", lowered)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        return "tool"
    if not cleaned[0].isalpha():
        cleaned = f"tool_{cleaned}"
    return cleaned


def _serialize_tool_result(result: Any) -> Any:
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    data = getattr(result, "data", None)
    if data is not None:
        return data
    content = getattr(result, "content", None)
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                texts.append(text)
        if texts:
            return {"text": "\n".join(texts)} if len(texts) > 1 else {"text": texts[0]}
    return {"result": str(result)}


def _map_exception(exc: Exception) -> CapabilityError:
    message = str(exc).lower()
    if isinstance(exc, CapabilityError):
        return exc
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return CapabilityError(
            CapabilityErrorCategory.TIMEOUT,
            "Capability invocation timed out.",
        )
    if any(token in message for token in ("401", "403", "unauthorized", "auth")):
        return CapabilityError(
            CapabilityErrorCategory.AUTHENTICATION,
            "MCP authentication failed.",
        )
    if any(token in message for token in ("connect", "unreachable", "refused", "offline")):
        return CapabilityError(
            CapabilityErrorCategory.UNAVAILABLE,
            "MCP capability is unavailable.",
        )
    return CapabilityError(
        CapabilityErrorCategory.UPSTREAM_FAILURE,
        "Tool execution failed.",
    )


def _classify_connect_error(exc: Exception) -> CapabilityErrorCategory:
    return _map_exception(exc).category


def _aggregate_status(
    statuses: list[McpServerStatusValue],
) -> McpServerStatusValue:
    for candidate in _STATUS_PRIORITY:
        if candidate in statuses:
            return candidate
    return "disabled"


def _aggregate_reason(
    status: McpServerStatusValue,
    servers: list[McpServerStatus],
) -> str:
    matching = [server for server in servers if server.status == status]
    if matching:
        return matching[0].reason
    return "MCP client runtime status is unknown."


async def _safe_close(client: Client[Any]) -> None:
    try:
        await client.__aexit__(None, None, None)
    except Exception:
        _LOGGER.debug("Error while closing MCP client.", exc_info=True)
    try:
        await client.close()
    except Exception:
        _LOGGER.debug("Error while disposing MCP client.", exc_info=True)