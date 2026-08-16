"""Advisory operational preflight evaluation."""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Iterable

from dotenv import load_dotenv

from core import config, database, scanner
from core.agent.local_runtime.coordinator import (
    check_resource_gate,
    get_provider_snapshot,
    get_system_vitals,
    is_local_execution_active,
)
from core.agent.local_runtime.registry import get_local_runtime_backend
from core.agent.catalog import (
    AGENT_SPECS,
    agent_has_credentials,
    build_concrete_agent,
    cloud_agent_keys,
    is_cloud_agent_key,
    is_local_agent_key,
    local_context_window_for_agent,
    local_reasoning_mode_for_agent,
    local_agent_keys,
    resolve_agent_selection,
)
from core.config import ENV_PATH, is_dev_mode
from core.settings import get_settings_store
from core.connectors.models import CONNECTOR_NAMES, EXTERNAL_CONNECTOR_NAMES
from core.settings import RuntimeSettingsSnapshot, get_settings_store
from core.telemetry.collector import enabled_connector_names
from core.telemetry.models import (
    PreflightBlocker,
    PreflightBlockerCode,
    PreflightRequest,
    PreflightResponse,
    PreflightWarning,
    PreflightWarningCode,
)
from core.synthesis.models import (
    FELIS_BRIEFING_CONTEXT_WINDOW,
    VALID_BRIEFING_MODES,
)
from core.telemetry.service import get_telemetry_service

load_dotenv(dotenv_path=ENV_PATH)

_LOGGER = logging.getLogger(__name__)

_WARNING_MESSAGES: dict[PreflightWarningCode, str] = {
    "outside_configured_network": (
        "Current Wi-Fi SSID does not match the configured network policy "
        "(HOME_SSID). This is a configured-network check, not proof of network security."
    ),
    "network_trust_unknown": (
        "Configured-network policy cannot be evaluated because the current SSID "
        "is missing or unreadable."
    ),
    "running_on_battery": (
        "Device is running on battery. Cold local-model loads may drain power."
    ),
    "rapid_connector_refresh": (
        "A forced external connector refresh already ran within the last five minutes."
    ),
    "high_resource_local_agent": (
        "The selected local Agent is resource-intensive on this host."
    ),
}

_BLOCKER_MESSAGES: dict[PreflightBlockerCode, str] = {
    "missing_credentials": "Required credentials are missing for the planned operation.",
    "model_unreachable": "The local model host is unreachable.",
    "model_not_installed": "The selected local model is not installed.",
    "concurrent_local_execution": "Another local execution is already in progress.",
    "insufficient_ram": "Host memory pressure exceeds the agent resource gate.",
    "cpu_overloaded": "Host CPU utilization exceeds the agent resource gate.",
    "database_failure": "Local database is unavailable.",
    "configuration_failure": "Runtime configuration is unavailable.",
    "invalid_input": "The preflight request contains invalid input.",
    "model_load_failure": "The selected local model failed to load.",
}

_BRIEFING_MODES = VALID_BRIEFING_MODES
_CONNECTOR_OPERATIONS = frozenset(
    {"activate", "activate_with_briefing", "refresh_telemetry"}
)


def _warning(code: PreflightWarningCode) -> PreflightWarning:
    return PreflightWarning(code=code, message=_WARNING_MESSAGES[code])


def _blocker(code: PreflightBlockerCode, message: str | None = None) -> PreflightBlocker:
    return PreflightBlocker(
        code=code,
        message=message or _BLOCKER_MESSAGES[code],
    )


def _normalize_acks(acknowledged: Iterable[str]) -> set[str]:
    return {str(item).strip() for item in acknowledged if str(item).strip()}


def _network_warnings() -> list[PreflightWarning]:
    current_ssid = scanner.get_current_ssid()
    target_ssid = os.getenv("HOME_SSID")
    if not target_ssid or not str(target_ssid).strip():
        return [_warning("network_trust_unknown")]
    if current_ssid is None or not str(current_ssid).strip():
        return [_warning("network_trust_unknown")]
    if current_ssid.strip() != str(target_ssid).strip():
        return [_warning("outside_configured_network")]
    return []


def _power_warnings(*, cold_local_load: bool) -> list[PreflightWarning]:
    if not cold_local_load:
        return []
    if scanner.get_power_state() == "battery":
        return [_warning("running_on_battery")]
    return []


def _loaded_model_matches(loaded_model: object, model_name: str) -> bool:
    if not isinstance(loaded_model, dict):
        return False
    return (
        loaded_model.get("name") == model_name
        or loaded_model.get("model") == model_name
    )


def _evaluate_local_agent_blockers(
    agent_key: str,
    *,
    context_window: int | None = None,
) -> tuple[list[PreflightBlocker], bool]:
    """Return local blockers and whether execution would require a cold load."""
    blockers: list[PreflightBlocker] = []
    spec = AGENT_SPECS.get(agent_key)
    if spec is None or spec.runtime != "local":
        blockers.append(_blocker("invalid_input", f"Unknown local Agent: {agent_key!r}"))
        return blockers, False
    agent = build_concrete_agent(
        agent_key,
        native_effort=None,
        local_context_window=(
            context_window
            if context_window is not None
            else local_context_window_for_agent(agent_key)
        ),
        local_reasoning_mode=local_reasoning_mode_for_agent(agent_key),
    )
    backend = get_local_runtime_backend(agent.provider)

    if not backend.enabled:
        provider_label = "llama.cpp" if agent.provider == "llama_cpp" else "Ollama"
        blockers.append(
            _blocker(
                "model_unreachable",
                f"Local {provider_label} runtime is disabled.",
            )
        )
        return blockers, False

    if is_local_execution_active():
        blockers.append(_blocker("concurrent_local_execution"))

    snapshot = get_provider_snapshot(agent.provider)
    if not snapshot["reachable"]:
        blockers.append(_blocker("model_unreachable"))
        return blockers, False
    if agent.runtime_model_id not in snapshot["installed_models"]:
        blockers.append(
            _blocker(
                "model_not_installed",
                f"Local model {agent.runtime_model_id!r} is not installed.",
            )
        )
        return blockers, False

    cold_load_required = not any(
        _loaded_model_matches(loaded_model, agent.runtime_model_id)
        and loaded_model.get("state", "loaded") == "loaded"
        for loaded_model in snapshot["loaded_models"]
    )

    if cold_load_required:
        allowed, gate_reason = check_resource_gate(
            agent.ram_limit,
            agent.cpu_limit,
            vitals=get_system_vitals(),
        )
        if not allowed and gate_reason == "insufficient_ram":
            blockers.append(_blocker("insufficient_ram"))
        elif not allowed and gate_reason == "cpu_overloaded":
            blockers.append(_blocker("cpu_overloaded"))

    return blockers, cold_load_required


def _cloud_credential_blockers(
    *,
    involves_cloud: bool,
    agent: str | None,
    operation: str,
) -> list[PreflightBlocker]:
    if not involves_cloud:
        return []

    briefing_ops = {"activate_with_briefing", "generate_briefing"}
    if agent == "panthera" and operation in briefing_ops:
        if os.getenv("OPENAI_API_KEY"):
            return []
        return [
            _blocker(
                "missing_credentials",
                "OpenAI API key is not configured for cloud briefing.",
            )
        ]

    if agent and agent in AGENT_SPECS:
        if agent_has_credentials(agent):
            return []
        env_name = AGENT_SPECS[agent].credential_env or "required credentials"
        return [
            _blocker(
                "missing_credentials",
                f"{env_name} is not configured for agent {agent}.",
            )
        ]

    if os.getenv("OPENAI_API_KEY"):
        return []
    return [
        _blocker(
            "missing_credentials",
            "OpenAI API key is not configured for this cloud operation.",
        )
    ]


def _effective_connector_names(
    request: PreflightRequest,
    settings: RuntimeSettingsSnapshot | None,
) -> set[str]:
    """Resolve enabled connectors that the planned operation would collect."""
    if settings is None or request.operation not in _CONNECTOR_OPERATIONS:
        return set()

    enabled = enabled_connector_names(
        features=settings.features,
        modules=settings.modules,
    )
    requested = set(request.connectors or CONNECTOR_NAMES)
    return requested & enabled


def _connector_credential_blockers(names: set[str]) -> list[PreflightBlocker]:
    """Return one blocker describing missing configuration for requested connectors."""
    missing: list[str] = []
    if "weather" in names and not os.getenv("TARGET_LOCATION"):
        missing.append("weather")
    if "news" in names and not os.getenv("GNEWS_API_KEY"):
        missing.append("news")
    if "football" in names and not os.getenv("FOOTBALL_API_KEY"):
        missing.append("football")
    if names & {"email", "calendar"}:
        oauth_files = (
            config.PROJECT_ROOT / "token.json",
            config.PROJECT_ROOT / "credentials.json",
        )
        if not any(path.is_file() for path in oauth_files):
            missing.extend(sorted(names & {"email", "calendar"}))

    if not missing:
        return []
    return [
        _blocker(
            "missing_credentials",
            f"Required connector configuration is missing for: {', '.join(missing)}.",
        )
    ]


def _football_configuration_blockers(
    names: set[str], settings: RuntimeSettingsSnapshot | None
) -> list[PreflightBlocker]:
    if "football" not in names or settings is None or settings.football.teams:
        return []
    return [_blocker("configuration_failure", "Football requires one to three configured teams.")]


def evaluate_preflight(request: PreflightRequest) -> PreflightResponse:
    """
    Evaluate advisory warnings and hard blockers for a planned operation.

    DEMO_MODE returns an empty advisory result (no simulation noise).
    Acknowledgement lists suppress matching warning codes for this request only.
    """
    if config.DEMO_MODE:
        return PreflightResponse(warnings=[], blockers=[], can_proceed=True)

    acks = _normalize_acks(request.acknowledged_warnings)
    warnings: list[PreflightWarning] = []
    blockers: list[PreflightBlocker] = []

    settings: RuntimeSettingsSnapshot | None = None
    try:
        settings = get_settings_store().get_snapshot()
    except Exception:
        _LOGGER.exception("Preflight configuration failure")
        blockers.append(_blocker("configuration_failure"))

    try:
        database.initialize_db()
        database.probe_db()
    except (sqlite3.Error, OSError):
        _LOGGER.exception("Preflight database failure")
        blockers.append(_blocker("database_failure"))

    briefing_mode = (request.briefing_mode or "").strip() or None
    if briefing_mode is not None and briefing_mode not in _BRIEFING_MODES:
        blockers.append(
            _blocker("invalid_input", f"Unknown briefing mode: {briefing_mode!r}")
        )

    if briefing_mode is not None and request.operation in {
        "activate_with_briefing",
        "generate_briefing",
    }:
        agent = None if briefing_mode == "structured_digest" else briefing_mode
        involves_cloud = briefing_mode == "panthera"
    else:
        agent = (request.synthesis_agent or "").strip() or None
        if (
            agent is None
            and request.operation == "cortex_query"
            and settings is not None
        ):
            _mode, agent, _effort = resolve_agent_selection(settings.ask_apex)
        if agent is None and request.operation in {
            "activate_with_briefing",
            "generate_briefing",
        }:
            agent = (
                settings.briefing.default_mode
                if settings is not None
                and settings.briefing.default_mode != "structured_digest"
                else "panthera"
            )
        cloud_agent = is_cloud_agent_key(agent) if agent else False
        involves_cloud = bool(request.involves_cloud or cloud_agent)

    valid_agents = set(local_agent_keys()) | set(cloud_agent_keys())
    if agent is not None and agent not in valid_agents:
        blockers.append(
            _blocker("invalid_input", f"Unknown synthesis agent: {agent!r}")
        )

    local_agent = is_local_agent_key(agent) if agent else False
    if not is_dev_mode():
        warnings.extend(_network_warnings())

    cold_local_load = False
    if local_agent and agent is not None:
        local_context_window = (
            FELIS_BRIEFING_CONTEXT_WINDOW
            if (
                agent == "felis"
                and request.operation in {"activate_with_briefing", "generate_briefing"}
            )
            else None
        )
        local_blockers, cold_local_load = _evaluate_local_agent_blockers(
            agent,
            context_window=local_context_window,
        )
        blockers.extend(local_blockers)

    warnings.extend(_power_warnings(cold_local_load=cold_local_load))

    effective_connectors = _effective_connector_names(request, settings)
    forced_external_refresh = bool(
        request.force and effective_connectors & set(EXTERNAL_CONNECTOR_NAMES)
    )
    if (
        forced_external_refresh
        and get_telemetry_service().had_forced_refresh_within_window()
    ):
        warnings.append(_warning("rapid_connector_refresh"))

    if local_agent and agent is not None:
        profile = build_concrete_agent(
            agent,
            native_effort=None,
            local_context_window=(
                FELIS_BRIEFING_CONTEXT_WINDOW
                if (
                    agent == "felis"
                    and request.operation
                    in {"activate_with_briefing", "generate_briefing"}
                )
                else local_context_window_for_agent(agent)
            ),
            local_reasoning_mode=local_reasoning_mode_for_agent(agent),
        )
        if getattr(profile, "high_resource", False):
            warnings.append(_warning("high_resource_local_agent"))

    blockers.extend(
        _cloud_credential_blockers(
            involves_cloud=involves_cloud,
            agent=agent,
            operation=request.operation,
        )
    )
    blockers.extend(_football_configuration_blockers(effective_connectors, settings))
    blockers.extend(_connector_credential_blockers(effective_connectors))

    if request.connectors:
        unknown = sorted(set(request.connectors) - set(CONNECTOR_NAMES))
        if unknown:
            blockers.append(
                _blocker("invalid_input", f"Unknown connector names: {unknown}")
            )

    filtered_warnings = [item for item in warnings if item.code not in acks]
    seen: set[str] = set()
    unique_warnings: list[PreflightWarning] = []
    for item in filtered_warnings:
        if item.code in seen:
            continue
        seen.add(item.code)
        unique_warnings.append(item)

    seen_blockers: set[str] = set()
    unique_blockers: list[PreflightBlocker] = []
    for item in blockers:
        if item.code in seen_blockers:
            continue
        seen_blockers.add(item.code)
        unique_blockers.append(item)

    return PreflightResponse(
        warnings=unique_warnings,
        blockers=unique_blockers,
        can_proceed=len(unique_blockers) == 0,
    )
