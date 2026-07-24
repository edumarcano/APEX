"""Provider-neutral capability registry for assistant and future MCP surfaces."""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import json
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

_LOGGER = logging.getLogger(__name__)

CapabilityRisk = Literal["read", "write", "destructive"]
CapabilityOrigin = Literal["native", "mcp"]

CapabilityHandler = Callable[..., Any] | Callable[..., Awaitable[Any]]

_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_OUTPUT_CHARS = 50_000
_PROVIDER_NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9]*$")
_LOCAL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class CapabilityErrorCategory(str, Enum):
    UNAVAILABLE = "unavailable"
    AUTHENTICATION = "authentication"
    TIMEOUT = "timeout"
    INVALID_INPUT = "invalid-input"
    UPSTREAM_FAILURE = "upstream-failure"


class CapabilityError(Exception):
    """Normalized capability invocation failure."""

    def __init__(self, category: CapabilityErrorCategory, message: str) -> None:
        self.category = category
        self.message = message
        super().__init__(message)

    def as_output(self) -> dict[str, str]:
        return {
            "error": self.message,
            "error_category": self.category.value,
        }


class CapabilityDescriptor(BaseModel):
    name: str = Field(description="Stable capability name used by models and callers.")
    title: str = Field(description="Human-readable capability title.")
    description: str = Field(description="Model-facing capability description.")
    input_schema: dict[str, Any] = Field(
        description="JSON Schema object describing accepted arguments."
    )
    origin: CapabilityOrigin = Field(description="Whether the capability is native or MCP.")
    risk: CapabilityRisk = Field(
        description="Read, write, or destructive risk classification."
    )
    expose_to_assistant: bool = Field(
        description="Whether the assistant may discover and invoke this capability."
    )
    expose_to_mcp_server: bool = Field(
        description="Whether the APEX MCP server may export this capability."
    )
    expose_to_client_display: bool = Field(
        description="Whether structured output may be returned in tool_outputs."
    )
    timeout_seconds: float = Field(
        default=_DEFAULT_TIMEOUT_SECONDS,
        gt=0,
        description="Wall-clock invocation timeout in seconds.",
    )
    max_output_chars: int = Field(
        default=_DEFAULT_MAX_OUTPUT_CHARS,
        gt=0,
        description="Maximum serialized output size returned to callers.",
    )


class _CapabilityEntry(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    descriptor: CapabilityDescriptor
    handler: CapabilityHandler


def namespaced_capability_name(provider: str, local_name: str) -> str:
    """Build a collision-safe imported capability name such as ``github_list_issues``."""
    provider_key = provider.strip().lower()
    local_key = local_name.strip().lower()
    if not _PROVIDER_NAMESPACE_PATTERN.fullmatch(provider_key):
        raise ValueError(
            f"Invalid capability provider namespace {provider!r}; "
            "expected a lowercase alphanumeric token."
        )
    if not _LOCAL_NAME_PATTERN.fullmatch(local_key):
        raise ValueError(
            f"Invalid capability local name {local_name!r}; "
            "expected a lowercase snake_case token."
        )
    return f"{provider_key}_{local_key}"


def _validate_and_coerce_arguments(
    name: str,
    input_schema: Mapping[str, Any],
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(arguments, Mapping):
        raise CapabilityError(
            CapabilityErrorCategory.INVALID_INPUT,
            f"Arguments for capability '{name}' must be an object.",
        )

    properties = input_schema.get("properties") or {}
    if not isinstance(properties, Mapping):
        raise CapabilityError(
            CapabilityErrorCategory.INVALID_INPUT,
            f"Capability '{name}' has an invalid input schema.",
        )

    required = input_schema.get("required") or []
    if not isinstance(required, list):
        raise CapabilityError(
            CapabilityErrorCategory.INVALID_INPUT,
            f"Capability '{name}' has an invalid input schema.",
        )

    additional = input_schema.get("additionalProperties", True)
    validated: dict[str, Any] = {}

    for key in arguments:
        if key not in properties and additional is False:
            raise CapabilityError(
                CapabilityErrorCategory.INVALID_INPUT,
                f"Unexpected argument '{key}' for capability '{name}'.",
            )

    for param_name, prop_schema in properties.items():
        if not isinstance(prop_schema, Mapping):
            raise CapabilityError(
                CapabilityErrorCategory.INVALID_INPUT,
                f"Capability '{name}' has an invalid input schema.",
            )

        if param_name not in arguments:
            if "default" in prop_schema:
                validated[param_name] = prop_schema["default"]
                continue
            if param_name in required:
                raise CapabilityError(
                    CapabilityErrorCategory.INVALID_INPUT,
                    f"Missing required argument '{param_name}' for capability '{name}'.",
                )
            continue

        validated[param_name] = _coerce_property_value(
            name, param_name, prop_schema, arguments[param_name]
        )

    for param_name in required:
        if param_name not in validated:
            raise CapabilityError(
                CapabilityErrorCategory.INVALID_INPUT,
                f"Missing required argument '{param_name}' for capability '{name}'.",
            )

    return validated


def _coerce_property_value(
    capability_name: str,
    param_name: str,
    prop_schema: Mapping[str, Any],
    value: Any,
) -> Any:
    declared_type = prop_schema.get("type")

    if declared_type == "integer":
        try:
            cast_value = int(value)
        except (TypeError, ValueError) as exc:
            raise CapabilityError(
                CapabilityErrorCategory.INVALID_INPUT,
                (
                    f"Argument '{param_name}' for capability '{capability_name}' "
                    f"must be an integer; received {value!r}."
                ),
            ) from exc
        minimum = prop_schema.get("minimum")
        maximum = prop_schema.get("maximum")
        if isinstance(minimum, (int, float)):
            cast_value = max(int(minimum), cast_value)
        if isinstance(maximum, (int, float)):
            cast_value = min(int(maximum), cast_value)
        return cast_value

    if declared_type == "number":
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise CapabilityError(
                CapabilityErrorCategory.INVALID_INPUT,
                (
                    f"Argument '{param_name}' for capability '{capability_name}' "
                    f"must be a number; received {value!r}."
                ),
            ) from exc

    if declared_type == "string":
        return str(value)

    if declared_type == "boolean":
        if isinstance(value, bool):
            return value
        raise CapabilityError(
            CapabilityErrorCategory.INVALID_INPUT,
            (
                f"Argument '{param_name}' for capability '{capability_name}' "
                f"must be a boolean; received {value!r}."
            ),
        )

    return value


def _bound_output(output: Any, max_output_chars: int) -> Any:
    try:
        serialized = json.dumps(output, default=str)
    except (TypeError, ValueError):
        serialized = str(output)

    if len(serialized) <= max_output_chars:
        return output

    preview_budget = max(0, max_output_chars - 120)
    return {
        "error": "Capability output exceeded size limit.",
        "error_category": CapabilityErrorCategory.UPSTREAM_FAILURE.value,
        "truncated": True,
        "preview": serialized[:preview_budget],
    }


def _run_handler(
    handler: CapabilityHandler,
    arguments: dict[str, Any],
    timeout_seconds: float,
) -> Any:
    if inspect.iscoroutinefunction(handler):

        async def _async_call() -> Any:
            return await asyncio.wait_for(handler(**arguments), timeout=timeout_seconds)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                return asyncio.run(_async_call())
            except TimeoutError as exc:
                raise CapabilityError(
                    CapabilityErrorCategory.TIMEOUT,
                    "Capability invocation timed out.",
                ) from exc
            except CapabilityError:
                raise
            except Exception as exc:
                raise CapabilityError(
                    CapabilityErrorCategory.UPSTREAM_FAILURE,
                    "Tool execution failed.",
                ) from exc

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _async_call())
            try:
                return future.result(timeout=timeout_seconds + 1.0)
            except concurrent.futures.TimeoutError as exc:
                raise CapabilityError(
                    CapabilityErrorCategory.TIMEOUT,
                    "Capability invocation timed out.",
                ) from exc
            except CapabilityError:
                raise
            except Exception as exc:
                cause = exc.__cause__ or exc
                if isinstance(cause, TimeoutError):
                    raise CapabilityError(
                        CapabilityErrorCategory.TIMEOUT,
                        "Capability invocation timed out.",
                    ) from exc
                if isinstance(cause, CapabilityError):
                    raise cause from exc
                raise CapabilityError(
                    CapabilityErrorCategory.UPSTREAM_FAILURE,
                    "Tool execution failed.",
                ) from exc

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(handler, **arguments)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError as exc:
            raise CapabilityError(
                CapabilityErrorCategory.TIMEOUT,
                "Capability invocation timed out.",
            ) from exc
        except CapabilityError:
            raise
        except Exception as exc:
            raise CapabilityError(
                CapabilityErrorCategory.UPSTREAM_FAILURE,
                "Tool execution failed.",
            ) from exc


class CapabilityRegistry:
    """In-process registry of native and imported capabilities."""

    def __init__(self) -> None:
        self._entries: dict[str, _CapabilityEntry] = {}

    def register(
        self,
        descriptor: CapabilityDescriptor,
        handler: CapabilityHandler,
    ) -> None:
        if descriptor.name in self._entries:
            raise ValueError(
                f"Capability '{descriptor.name}' is already registered."
            )
        self._entries[descriptor.name] = _CapabilityEntry(
            descriptor=descriptor,
            handler=handler,
        )

    def get(self, name: str) -> _CapabilityEntry | None:
        return self._entries.get(name)

    def get_descriptor(self, name: str) -> CapabilityDescriptor | None:
        entry = self._entries.get(name)
        return entry.descriptor if entry is not None else None

    def list_assistant_capabilities(self) -> list[CapabilityDescriptor]:
        return [
            entry.descriptor
            for entry in self._entries.values()
            if entry.descriptor.expose_to_assistant
        ]

    def is_client_display_enabled(self, name: str) -> bool:
        entry = self._entries.get(name)
        if entry is None:
            return False
        return entry.descriptor.expose_to_client_display

    def invoke(self, name: str, arguments: Mapping[str, Any] | None = None) -> Any:
        entry = self._entries.get(name)
        if entry is None:
            raise CapabilityError(
                CapabilityErrorCategory.UNAVAILABLE,
                f"Capability '{name}' is not registered.",
            )

        raw_arguments = arguments or {}
        validated = _validate_and_coerce_arguments(
            name,
            entry.descriptor.input_schema,
            raw_arguments,
        )
        result = _run_handler(
            entry.handler,
            validated,
            entry.descriptor.timeout_seconds,
        )
        return _bound_output(result, entry.descriptor.max_output_chars)


_REGISTRY = CapabilityRegistry()


def _ensure_native_capabilities_loaded() -> None:
    """Import and register native tools when the registry is empty."""
    if "get_weather_forecast" in _REGISTRY._entries:
        return
    # Local import avoids an import cycle with core.agent.tools.
    from core.agent.tools import register_native_capabilities

    register_native_capabilities()


def register_capability(
    descriptor: CapabilityDescriptor,
    handler: CapabilityHandler,
) -> None:
    _REGISTRY.register(descriptor, handler)


def get_capability_descriptor(name: str) -> CapabilityDescriptor | None:
    _ensure_native_capabilities_loaded()
    return _REGISTRY.get_descriptor(name)


def list_assistant_capabilities() -> list[CapabilityDescriptor]:
    _ensure_native_capabilities_loaded()
    return _REGISTRY.list_assistant_capabilities()


def is_client_display_enabled(name: str) -> bool:
    _ensure_native_capabilities_loaded()
    return _REGISTRY.is_client_display_enabled(name)


def invoke_capability(name: str, arguments: Mapping[str, Any] | None = None) -> Any:
    _ensure_native_capabilities_loaded()
    return _REGISTRY.invoke(name, arguments)


def clear_capability_registry_for_tests() -> None:
    """Remove all registered capabilities. Test helper only."""
    _REGISTRY._entries.clear()
