"""One bounded provider call for future briefing synthesis stages."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from core.agent.catalog import build_concrete_agent
from core.agent.local_runtime.execution import admit_local_model
from core.agent.loop import is_local_profile
from core.agent.model_catalog import model_has_credentials
from core.agent.providers.factory import create_provider
from core.agent.providers.contract import ProviderTurnResult
from core.agent.types import AgentMessage
from core.briefings.models import (
    MAX_ARTIFACT_BYTES,
    MAX_PROMPT_BYTES,
    BriefingGenerationConfiguration,
)
from core.briefings.runtime import get_visible_model_profile
from core.runs.coordinator import RunExecutionControl

ProviderFactory = Callable[[Any, str | None], Any]


class BriefingModelOutputError(ValueError):
    """The provider did not return one bounded, tool-free response."""


def execute_single_call(
    *,
    configuration: BriefingGenerationConfiguration,
    prompt: str,
    output_schema: dict[str, Any],
    control: RunExecutionControl,
    provider_factory: ProviderFactory = create_provider,
) -> ProviderTurnResult:
    """Run exactly one catalog-selected model call with no tools or fallback."""
    model_configuration = configuration.model
    output_token_limit = model_configuration.output_token_limit
    prompt_bytes = len(prompt.encode("utf-8"))
    if prompt_bytes > MAX_PROMPT_BYTES:
        raise BriefingModelOutputError(
            f"Briefing input exceeds the {MAX_PROMPT_BYTES}-byte limit."
        )

    catalog_profile = get_visible_model_profile(model_configuration.model_id)
    if (
        catalog_profile.provider != model_configuration.provider
        or catalog_profile.runtime != model_configuration.runtime
    ):
        raise BriefingModelOutputError(
            "The frozen model configuration no longer matches the shared catalog."
        )
    if not model_has_credentials(catalog_profile):
        raise BriefingModelOutputError("Credentials for the selected model are unavailable.")

    concrete_profile = build_concrete_agent(
        "apex",
        native_effort=model_configuration.reasoning,  # type: ignore[arg-type]
        local_context_window=model_configuration.context_window,
        local_reasoning_mode=model_configuration.local_reasoning_mode,
        google_search_enabled=False,
        google_maps_enabled=False,
        model_id=model_configuration.model_id,
    )
    system_instruction = getattr(concrete_profile, "system_instruction", "")
    context_window = model_configuration.context_window
    if context_window is not None:
        # UTF-8 bytes are a conservative upper bound for input token count; the
        # output budget is already in tokens and is reserved before admission.
        if len(system_instruction.encode("utf-8")) + prompt_bytes + output_token_limit > context_window:
            raise BriefingModelOutputError(
                "The bounded briefing prompt exceeds the selected context window."
            )

    api_key = (
        os.getenv(catalog_profile.credential_env)
        if catalog_profile.credential_env
        else None
    )
    provider = provider_factory(concrete_profile, api_key)

    def _generate() -> ProviderTurnResult:
        control.before_model_turn()
        result = provider.generate_turn(
            [AgentMessage(role="user", content=prompt)],
            [],
            concrete_profile,
            execution_control=control,
            output_schema=output_schema,
            output_token_limit=output_token_limit,
        )
        control.after_model_turn(result)
        if result.message.tool_calls:
            raise BriefingModelOutputError(
                "The single-call briefing response attempted to request a tool."
            )
        response_content = result.message.content or ""
        response_limit = min(MAX_ARTIFACT_BYTES, output_token_limit * 16)
        if len(response_content.encode("utf-8")) > response_limit:
            raise BriefingModelOutputError(
                "The briefing response exceeds its configured output bound."
            )
        if not response_content.strip():
            raise BriefingModelOutputError("The selected model returned no briefing content.")
        return result

    if is_local_profile(concrete_profile):
        with admit_local_model(concrete_profile):
            return _generate()
    return _generate()
