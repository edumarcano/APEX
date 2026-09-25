"""Admission for one model-backed turn through APEX local-runtime controls."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from core.agent.local_runtime.contract import LocalModelProfile, LocalModelRef
from core.agent.local_runtime.coordinator import (
    check_resource_gate,
    end_local_execution,
    get_provider_snapshot,
    is_local_model_ready,
    switch_local_model,
    try_begin_local_execution,
)
from core.agent.local_runtime.registry import get_local_runtime_backend


class LocalModelAdmissionError(RuntimeError):
    """A selected local model cannot start a generation now."""


@contextmanager
def admit_local_model(profile: LocalModelProfile) -> Iterator[None]:
    """Hold the shared inference slot while verifying/loading and using a model."""
    backend = get_local_runtime_backend(profile.provider)
    if not backend.enabled:
        raise LocalModelAdmissionError("Local inference is disabled in system settings.")
    if not try_begin_local_execution():
        raise LocalModelAdmissionError("A local model generation is already in progress.")

    try:
        snapshot = get_provider_snapshot(profile.provider, force_refresh=True)
        if not snapshot["reachable"]:
            raise LocalModelAdmissionError("The selected local runtime is unreachable.")
        if profile.runtime_model_id not in snapshot["installed_models"]:
            raise LocalModelAdmissionError(
                "The selected local model is not installed or configured."
            )

        ref = LocalModelRef(
            provider=profile.provider,
            model=profile.runtime_model_id,
        )
        if not is_local_model_ready(ref):
            allowed, _reason = check_resource_gate(profile.ram_limit, profile.cpu_limit)
            if not allowed:
                raise LocalModelAdmissionError(
                    "Local inference is blocked by current system resource limits."
                )
        if not switch_local_model(profile):
            raise LocalModelAdmissionError("The selected local model could not be loaded.")
        yield
    finally:
        end_local_execution()
