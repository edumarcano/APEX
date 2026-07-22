"""Advisory operational preflight evaluation."""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Iterable

from dotenv import load_dotenv

from core import config, database, scanner
from core.agent.providers.ollama_lifecycle import (
    check_resource_gate,
    get_status_snapshot,
    is_local_execution_active,
)
from core.agent.providers.ollama_models import OLLAMA_MODEL_PROFILES
from core.config import ENV_PATH, OLLAMA_ENABLED, is_dev_mode
from core.connectors.models import CONNECTOR_NAMES
from core.settings import get_settings_store
from core.telemetry.models import (
    PreflightBlocker,
    PreflightBlockerCode,
    PreflightRequest,
    PreflightResponse,
    PreflightWarning,
    PreflightWarningCode,
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
    "cloud_data_disclosure": (
        "This operation may send sanitized operational context to a cloud provider."
    ),
    "high_resource_local_profile": (
        "The selected local profile is resource-intensive on this host."
    ),
}

_BLOCKER_MESSAGES: dict[PreflightBlockerCode, str] = {
    "missing_credentials": "Required credentials are missing for the planned operation.",
    "model_unreachable": "The local model host is unreachable.",
    "model_not_installed": "The selected local model is not installed.",
    "concurrent_local_execution": "Another local execution is already in progress.",
    "insufficient_ram": "Host memory pressure exceeds the profile resource gate.",
    "cpu_overloaded": "Host CPU utilization exceeds the profile resource gate.",
    "database_failure": "Local database is unavailable.",
    "configuration_failure": "Runtime configuration is unavailable.",
    "invalid_input": "The preflight request contains invalid input.",
    "model_load_failure": "The selected local model failed to load.",
}

_LOCAL_PROFILES = frozenset({"lynx", "acinonyx", "neofelis"})
_CLOUD_PROFILES = frozenset({"comet", "nova", "pulsar"})


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


def _power_warnings(*, local_profile: bool) -> list[PreflightWarning]:
    if not local_profile:
        return []
    if scanner.get_power_state() == "battery":
        return [_warning("running_on_battery")]
    return []


def _evaluate_local_profile_blockers(profile_key: str) -> list[PreflightBlocker]:
    blockers: list[PreflightBlocker] = []
    profile = OLLAMA_MODEL_PROFILES.get(profile_key)
    if profile is None:
        blockers.append(_blocker("invalid_input", f"Unknown local profile: {profile_key!r}"))
        return blockers

    if not OLLAMA_ENABLED:
        blockers.append(_blocker("model_unreachable", "Local Ollama runtime is disabled."))
        return blockers

    if is_local_execution_active():
        blockers.append(_blocker("concurrent_local_execution"))

    snapshot = get_status_snapshot()
    if not snapshot["reachable"]:
        blockers.append(_blocker("model_unreachable"))
        return blockers
    if profile.api_model not in snapshot["installed_tags"]:
        blockers.append(
            _blocker(
                "model_not_installed",
                f"Local model {profile.api_model!r} is not installed.",
            )
        )
        return blockers

    allowed, gate_reason = check_resource_gate(profile.ram_limit, profile.cpu_limit)
    if not allowed and gate_reason == "insufficient_ram":
        blockers.append(_blocker("insufficient_ram"))
    elif not allowed and gate_reason == "cpu_overloaded":
        blockers.append(_blocker("cpu_overloaded"))

    return blockers


def _cloud_credential_blockers(*, involves_cloud: bool) -> list[PreflightBlocker]:
    if not involves_cloud:
        return []
    if os.getenv("GEMINI_API_KEY"):
        return []
    return [
        _blocker(
            "missing_credentials",
            "Gemini API key is not configured for cloud operations.",
        )
    ]


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

    try:
        get_settings_store().get_snapshot()
    except Exception:
        _LOGGER.exception("Preflight configuration failure")
        blockers.append(_blocker("configuration_failure"))

    try:
        database.initialize_db()
        database.probe_db()
    except (sqlite3.Error, OSError):
        _LOGGER.exception("Preflight database failure")
        blockers.append(_blocker("database_failure"))

    profile = (request.synthesis_profile or "").strip() or None
    local_profile = profile in _LOCAL_PROFILES
    cloud_profile = profile in _CLOUD_PROFILES if profile else False
    involves_cloud = bool(request.involves_cloud or cloud_profile)
    if (
        request.operation in {"activate_with_briefing", "generate_briefing"}
        and profile is None
    ):
        involves_cloud = True

    if not is_dev_mode():
        warnings.extend(_network_warnings())

    warnings.extend(_power_warnings(local_profile=local_profile))

    if request.force and get_telemetry_service().had_forced_refresh_within_window():
        warnings.append(_warning("rapid_connector_refresh"))

    if involves_cloud and not request.cloud_disclosure_acknowledged:
        warnings.append(_warning("cloud_data_disclosure"))

    if profile == "neofelis":
        warnings.append(_warning("high_resource_local_profile"))

    blockers.extend(_cloud_credential_blockers(involves_cloud=involves_cloud))

    if local_profile and profile is not None:
        blockers.extend(_evaluate_local_profile_blockers(profile))

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
