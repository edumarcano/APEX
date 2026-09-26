"""One bounded provider call for future briefing synthesis stages."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections.abc import Callable
from typing import Any, Literal

from google.genai.errors import APIError

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
_LOGGER = logging.getLogger(__name__)
_SAFE_PROVIDER_FIELD_PATH = re.compile(r"[A-Za-z0-9_.\[\]-]{1,160}\Z")


class BriefingModelOutputError(ValueError):
    """The provider did not return one bounded, tool-free response."""


class InvalidBriefingModelOutputError(BriefingModelOutputError):
    """A completed provider turn returned content that cannot be repaired as-is."""

    _REPAIR_FEEDBACK = {
        "tool_call": "The response attempted to call a tool; return only the briefing JSON object.",
        "oversized": "The response exceeded its output bound; return a concise briefing JSON object.",
        "empty": "No response content was returned; provide the briefing JSON object.",
    }

    def __init__(self, reason: Literal["tool_call", "oversized", "empty"]) -> None:
        repair_feedback = self._REPAIR_FEEDBACK[reason]
        super().__init__(repair_feedback)
        self.reason = reason
        self.repair_feedback = repair_feedback


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
        try:
            result = provider.generate_turn(
                [AgentMessage(role="user", content=prompt)],
                [],
                concrete_profile,
                execution_control=control,
                output_schema=output_schema,
                output_token_limit=output_token_limit,
            )
        except APIError as exc:
            _log_google_api_error(
                exc,
                configuration=configuration,
                control=control,
                prompt=prompt,
                system_instruction=system_instruction,
                output_schema=output_schema,
                output_token_limit=output_token_limit,
            )
            raise
        control.after_model_turn(result)
        if result.message.tool_calls:
            raise InvalidBriefingModelOutputError("tool_call")
        response_content = result.message.content or ""
        response_limit = min(MAX_ARTIFACT_BYTES, output_token_limit * 16)
        if len(response_content.encode("utf-8")) > response_limit:
            raise InvalidBriefingModelOutputError("oversized")
        if not response_content.strip():
            raise InvalidBriefingModelOutputError("empty")
        return result

    if is_local_profile(concrete_profile):
        with admit_local_model(concrete_profile):
            return _generate()
    return _generate()


def _log_google_api_error(
    error: APIError,
    *,
    configuration: BriefingGenerationConfiguration,
    control: RunExecutionControl,
    prompt: str,
    system_instruction: str,
    output_schema: dict[str, Any],
    output_token_limit: int,
) -> None:
    schema_json = json.dumps(
        output_schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    schema_hash = hashlib.sha256(schema_json.encode("utf-8")).hexdigest()[:12]
    run_id = getattr(getattr(control, "handle", None), "run_id", None) or "unknown"
    fields = _safe_google_field_paths(getattr(error, "details", None))
    _LOGGER.warning(
        "Briefing provider request failed: run_id=%s profile=%s provider=%s model=%s "
        "http_status=%s api_status=%s reason=%s fields=%s input_bytes=%s "
        "system_instruction_bytes=%s schema_bytes=%s schema_sha256=%s output_token_limit=%s",
        run_id,
        configuration.profile.id,
        configuration.model.provider,
        configuration.model.model_id,
        error.code,
        _safe_log_value(getattr(error, "status", None), fallback="unknown"),
        _google_error_reason(error, fields),
        ",".join(fields) if fields else "none",
        len(prompt.encode("utf-8")),
        len(system_instruction.encode("utf-8")),
        len(schema_json.encode("utf-8")),
        schema_hash,
        output_token_limit,
    )


def _safe_google_field_paths(details: Any) -> list[str]:
    """Extract only bounded request field paths from Google's structured errors."""
    fields: set[str] = set()
    visited = 0

    def visit(value: Any, depth: int = 0) -> None:
        nonlocal visited
        if depth > 6 or visited >= 128:
            return
        visited += 1
        if isinstance(value, dict):
            violations = value.get("fieldViolations")
            if isinstance(violations, list):
                for violation in violations[:8]:
                    if not isinstance(violation, dict):
                        continue
                    field = violation.get("field")
                    if isinstance(field, str) and _SAFE_PROVIDER_FIELD_PATH.fullmatch(field):
                        fields.add(field)
            for child in value.values():
                visit(child, depth + 1)
        elif isinstance(value, list):
            for child in value[:32]:
                visit(child, depth + 1)

    visit(details)
    return sorted(fields)[:5]


def _google_error_reason(error: APIError, fields: list[str]) -> str:
    status = str(getattr(error, "status", "") or "").casefold()
    message = str(getattr(error, "message", "") or "").casefold()
    field_text = " ".join(fields).casefold()
    if any(
        field_name in message or field_name in field_text
        for field_name in ("response_schema", "response_json_schema")
    ):
        return "structured_output_schema_rejected"
    if "max_output_tokens" in message or "max_output_tokens" in field_text:
        return "output_limit_rejected"
    if error.code == 413 or any(
        marker in message for marker in ("too many tokens", "input too large", "request too large")
    ):
        return "request_size_rejected"
    if error.code == 429 or status == "resource_exhausted":
        return "rate_limited"
    if error.code in {401, 403}:
        return "credentials_or_permission_rejected"
    if error.code == 400 or status == "invalid_argument":
        return "invalid_argument"
    return "provider_request_rejected"


def _safe_log_value(value: Any, *, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = re.sub(r"[^A-Za-z0-9_.-]", "_", value)[:64]
    return normalized or fallback
