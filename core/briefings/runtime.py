"""Shared-catalog configuration resolution for one briefing model call."""

from __future__ import annotations

from core.agent.catalog import local_reasoning_modes_for_model
from core.agent.local_runtime.registry import get_local_runtime_backend
from core.agent.model_catalog import (
    ModelProfile,
    model_has_credentials,
    visible_cloud_models,
    visible_local_models,
)
from core.agent.providers.llama_cpp_models import LLAMA_CPP_RUNTIME_CONFIGS
from core.agent.providers.ollama_models import OLLAMA_RUNTIME_CONFIGS
from core.briefings.models import (
    BUILTIN_BRIEFING_PROFILES,
    BriefingGenerationConfiguration,
    BriefingGenerationRequest,
    BriefingModelConfiguration,
    MAX_OUTPUT_TOKENS,
)
from core.config import (
    CORTEX_RUNS_MAX_ELAPSED_SECONDS,
    CORTEX_RUNS_MAX_MODEL_TURNS,
    CORTEX_RUNS_MAX_RETRIES,
    CORTEX_RUNS_MAX_TOOL_CALLS,
    DEMO_MODE,
    is_dev_mode,
)
from core.settings import get_settings_store


class BriefingModelConfigurationError(ValueError):
    """The explicit model or one of its requested controls cannot be used."""


def resolve_briefing_configuration(
    request: BriefingGenerationRequest,
) -> BriefingGenerationConfiguration:
    """Resolve exact catalog identity and validate model-specific controls."""
    if DEMO_MODE:
        raise BriefingModelConfigurationError(
            "Model-backed briefings are unavailable in demo mode."
        )

    dev_mode = is_dev_mode()
    visible_profiles = {
        profile.model_id: profile
        for profile in (
            *visible_cloud_models(dev_mode=dev_mode),
            *visible_local_models(dev_mode=dev_mode),
        )
    }
    profile = visible_profiles.get(request.model_id)
    if profile is None:
        raise BriefingModelConfigurationError(
            "The selected model is not available in the current environment."
        )
    if not model_has_credentials(profile):
        raise BriefingModelConfigurationError(
            f"Configure {profile.credential_env} before using the selected model."
        )

    settings = get_settings_store().get_snapshot()
    if not settings.ask_apex.enabled:
        raise BriefingModelConfigurationError(
            "Model-backed briefings are disabled in Agent settings."
        )

    reasoning: str | None = None
    context_window: int | None = None
    local_reasoning_mode: str | None = None
    if profile.runtime == "cloud":
        if request.local_reasoning_mode is not None:
            raise BriefingModelConfigurationError(
                "Local reasoning mode cannot be set for a cloud model."
            )
        if request.reasoning is not None and request.reasoning not in profile.reasoning_options:
            raise BriefingModelConfigurationError(
                "The requested reasoning option is not supported by the selected model."
            )
        reasoning = request.reasoning or profile.default_reasoning
        maximum_context = profile.maximum_context_window
        if request.context_window is not None:
            if maximum_context is None or request.context_window > maximum_context:
                raise BriefingModelConfigurationError(
                    "The requested context window exceeds the selected model's catalog limit."
                )
            context_window = request.context_window
    else:
        if request.reasoning is not None:
            raise BriefingModelConfigurationError(
                "Cloud reasoning effort cannot be set for a local model."
            )
        backend = get_local_runtime_backend(profile.provider)  # type: ignore[arg-type]
        if not backend.enabled:
            raise BriefingModelConfigurationError(
                f"Local {profile.provider} inference is disabled in system settings."
            )
        supported_modes = local_reasoning_modes_for_model(profile.model_id)
        if request.local_reasoning_mode is not None:
            if request.local_reasoning_mode not in supported_modes:
                raise BriefingModelConfigurationError(
                    "The requested local reasoning mode is not supported by the selected model."
                )
            local_reasoning_mode = request.local_reasoning_mode

        if profile.provider == "llama_cpp":
            runtime = LLAMA_CPP_RUNTIME_CONFIGS.get(profile.model_id)
            if runtime is None:
                raise BriefingModelConfigurationError(
                    "The selected llama.cpp model has no runtime configuration."
                )
            allowed_contexts = runtime.allowed_context_windows
            local_settings = settings.ask_apex.local
            if request.context_window is not None:
                if request.context_window not in allowed_contexts:
                    raise BriefingModelConfigurationError(
                        "The requested context window is not a supported preset for the selected model."
                    )
                context_window = request.context_window
            elif local_settings.last_model == profile.model_id and local_settings.context_window in allowed_contexts:
                context_window = local_settings.context_window
            else:
                context_window = runtime.default_context_window
            if local_reasoning_mode is None:
                local_reasoning_mode = (
                    local_settings.reasoning_mode
                    if local_settings.last_model == profile.model_id
                    and local_settings.reasoning_mode in supported_modes
                    else runtime.default_reasoning_mode
                )
        elif profile.provider == "ollama":
            runtime = OLLAMA_RUNTIME_CONFIGS.get(profile.model_id)
            if runtime is None:
                raise BriefingModelConfigurationError(
                    "The selected Ollama model has no runtime configuration."
                )
            if request.context_window is not None and request.context_window != runtime.context_window:
                raise BriefingModelConfigurationError(
                    "The selected Ollama model uses a fixed context window."
                )
            context_window = runtime.context_window
            if local_reasoning_mode is None:
                local_settings = settings.ask_apex.local
                local_reasoning_mode = (
                    local_settings.reasoning_mode
                    if local_settings.last_model == profile.model_id
                    and local_settings.reasoning_mode in supported_modes
                    else runtime.default_reasoning_mode
                )
        else:
            raise BriefingModelConfigurationError(
                "The selected local model has no supported runtime."
            )

    return BriefingGenerationConfiguration(
        profile=BUILTIN_BRIEFING_PROFILES[request.profile_id],
        model=BriefingModelConfiguration(
            model_id=profile.model_id,
            provider=profile.provider,
            runtime=profile.runtime,
            reasoning=reasoning,
            context_window=context_window,
            local_reasoning_mode=local_reasoning_mode,  # type: ignore[arg-type]
            max_elapsed_seconds=CORTEX_RUNS_MAX_ELAPSED_SECONDS,
            max_retries=CORTEX_RUNS_MAX_RETRIES,
            max_model_turns=CORTEX_RUNS_MAX_MODEL_TURNS,
            max_tool_calls=CORTEX_RUNS_MAX_TOOL_CALLS,
            output_token_limit=min(4096, MAX_OUTPUT_TOKENS),
        ),
        origin=request.origin,
    )


def get_visible_model_profile(model_id: str) -> ModelProfile:
    """Resolve a model only when it belongs to the visible shared catalog."""
    dev_mode = is_dev_mode()
    for profile in (
        *visible_cloud_models(dev_mode=dev_mode),
        *visible_local_models(dev_mode=dev_mode),
    ):
        if profile.model_id == model_id:
            return profile
    raise BriefingModelConfigurationError(
        "The selected model is not available in the current environment."
    )
