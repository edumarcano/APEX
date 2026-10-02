"""Load non-secret MCP configuration from config.json and config.local.json."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from core.config import CONFIG_PATH
from core.config_documents import deep_merge, load_config_documents, read_json_object
from core.mcp.models import McpRuntimeConfig, McpServerConfig, parse_server_config
from core.runtime_paths import get_runtime_paths

_LOGGER = logging.getLogger(__name__)

_LOCAL_CONFIG_PATH: Path = get_runtime_paths().local_config_path
_SERVER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*$")


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        return read_json_object(path)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _LOGGER.warning("Unable to load MCP config from %s: %s", path, exc)
        return {}


def load_mcp_config(
    config_path: Path | None = None,
    local_path: Path | None = None,
) -> McpRuntimeConfig:
    """
    Load MCP runtime config from tracked defaults overlaid by local overrides.

    Secrets are never read from these files; only env-var name references are kept.
    """
    if config_path is None and local_path is None:
        paths = get_runtime_paths()
        merged = load_config_documents(
            paths.defaults_config_path,
            paths.operator_config_path,
            paths.local_config_path,
        )
    else:
        base_path = config_path or CONFIG_PATH
        overlay_path = local_path if local_path is not None else _LOCAL_CONFIG_PATH
        base = _read_json_object(base_path)
        local = _read_json_object(overlay_path) if overlay_path.exists() else {}
        merged = deep_merge(base, local)
    raw_mcp = merged.get("mcp", {})
    if raw_mcp is None:
        return McpRuntimeConfig()
    if not isinstance(raw_mcp, dict):
        _LOGGER.warning('Config key "mcp" must be a JSON object; using defaults.')
        return McpRuntimeConfig()

    enabled_raw = raw_mcp.get("enabled", False)
    enabled = enabled_raw if isinstance(enabled_raw, bool) else False
    if not isinstance(enabled_raw, bool):
        _LOGGER.warning('Config key "mcp.enabled" must be a boolean; using false.')
    servers_raw = raw_mcp.get("servers", {})
    servers: dict[str, McpServerConfig] = {}
    if not isinstance(servers_raw, dict):
        _LOGGER.warning('Config key "mcp.servers" must be a JSON object; ignoring.')
    else:
        for server_id, server_value in servers_raw.items():
            if not isinstance(server_id, str) or not _SERVER_ID_PATTERN.fullmatch(
                server_id.strip().lower()
            ):
                _LOGGER.warning(
                    "Ignoring MCP server id %r; expected lowercase alphanumeric token.",
                    server_id,
                )
                continue
            if not isinstance(server_value, dict):
                _LOGGER.warning(
                    "Ignoring MCP server %r; configuration must be a JSON object.",
                    server_id,
                )
                continue
            normalized_id = server_id.strip().lower()
            servers[normalized_id] = parse_server_config(server_value)

    return McpRuntimeConfig(enabled=enabled, servers=servers)
