"""Load non-secret MCP configuration from config.json and config.local.json."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from core.config import CONFIG_PATH, PROJECT_ROOT
from core.mcp.models import McpRuntimeConfig, McpServerConfig, parse_server_config
from core.settings.normalize import recursive_overlay

_LOGGER = logging.getLogger(__name__)

_LOCAL_CONFIG_PATH: Path = PROJECT_ROOT / "config.local.json"
_SERVER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*$")


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        _LOGGER.warning("Unable to load MCP config from %s: %s", path, exc)
        return {}
    if not isinstance(payload, dict):
        _LOGGER.warning("Config root in %s must be a JSON object; ignoring.", path)
        return {}
    return payload


def load_mcp_config(
    config_path: Path | None = None,
    local_path: Path | None = None,
) -> McpRuntimeConfig:
    """
    Load MCP runtime config from tracked defaults overlaid by local overrides.

    Secrets are never read from these files; only env-var name references are kept.
    """
    base_path = config_path or CONFIG_PATH
    overlay_path = local_path if local_path is not None else _LOCAL_CONFIG_PATH
    base = _read_json_object(base_path)
    local = _read_json_object(overlay_path) if overlay_path.exists() else {}
    merged = recursive_overlay(base, local)
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
