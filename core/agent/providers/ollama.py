import inspect
import json
import logging
import re
from typing import Any, Callable, get_args, get_origin, get_type_hints

import requests
from requests.exceptions import RequestException

from core.agent.providers.gemini_models import GeminiModelProfile
from core.agent.providers.ollama_models import OllamaModelProfile
from core.agent.types import AgentMessage, ToolCall
from core.config import OLLAMA_HOST

AgentModelProfile = GeminiModelProfile | OllamaModelProfile

_LOGGER = logging.getLogger(__name__)


def _python_type_to_json_schema(type_hint: Any) -> dict[str, str]:
    """Map a Python type hint to a minimal JSON Schema type declaration."""
    origin = get_origin(type_hint)
    if origin is not None:
        if origin is dict:
            return {"type": "object"}
        if origin is list:
            return {"type": "array"}

    if type_hint is int:
        return {"type": "integer"}
    if type_hint is float:
        return {"type": "number"}
    if type_hint is str:
        return {"type": "string"}
    if type_hint is dict:
        return {"type": "object"}
    if type_hint is list:
        return {"type": "array"}

    # Union / Optional fallbacks — pick the first non-None arg when present.
    args = get_args(type_hint)
    if args:
        non_none = [arg for arg in args if arg is not type(None)]
        if non_none:
            return _python_type_to_json_schema(non_none[0])

    return {"type": "string"}


def _extract_function_description(docstring: str | None) -> str:
    """Return the first non-empty line of a function docstring."""
    if not docstring:
        return ""
    for line in docstring.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _extract_param_descriptions(docstring: str | None) -> dict[str, str]:
    """Parse Google-style ``Args:`` blocks from a function docstring."""
    if not docstring:
        return {}

    descriptions: dict[str, str] = {}
    in_args = False
    current_param: str | None = None

    for line in docstring.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "Args:":
            in_args = True
            current_param = None
            continue
        if not in_args:
            continue
        if stripped.startswith(
            ("Returns:", "Return:", "Raises:", "Yields:", "Note:", "Examples:")
        ):
            break

        match = re.match(r"^(\w+):\s*(.*)$", stripped)
        if match:
            current_param = match.group(1)
            descriptions[current_param] = match.group(2).strip()
        elif current_param is not None:
            descriptions[current_param] += " " + stripped

    return descriptions


def _function_to_openai_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Convert a Python callable into an OpenAI-compatible function tool schema."""
    sig = inspect.signature(func)
    type_hints = get_type_hints(func)
    docstring = func.__doc__
    param_descriptions = _extract_param_descriptions(docstring)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        type_hint = type_hints.get(param_name, str)
        prop_schema: dict[str, Any] = _python_type_to_json_schema(type_hint)
        prop_schema["description"] = param_descriptions.get(
            param_name,
            f"The parameter maps to argument: {param_name}",
        )
        properties[param_name] = prop_schema

        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": _extract_function_description(docstring),
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _messages_to_ollama(messages: list[AgentMessage]) -> list[dict[str, Any]]:
    """Translate APEX AgentMessage history into Ollama /api/chat payload entries."""
    ollama_messages: list[dict[str, Any]] = []

    for message in messages:
        if message.role == "user":
            ollama_messages.append(
                {
                    "role": "user",
                    "content": message.content if message.content is not None else "",
                }
            )

        elif message.role == "model":
            payload: dict[str, Any] = {
                "role": "assistant",
                "content": message.content if message.content is not None else "",
            }
            if message.tool_calls:
                payload["tool_calls"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": call.arguments,
                        },
                    }
                    for call in message.tool_calls
                ]
            ollama_messages.append(payload)

        elif message.role == "tool":
            if not message.tool_results:
                continue
            for result in message.tool_results:
                ollama_messages.append(
                    {
                        "role": "tool",
                        "content": str(result.output),
                    }
                )

    return ollama_messages


def _strip_thinking_tags(content: str | None) -> str:
    """Remove Qwen-style reasoning blocks from assistant content."""
    if not content:
        return ""

    think_open = "<" + "think" + ">"
    think_close = "</" + "think" + ">"
    content = re.sub(rf"{re.escape(think_open)}[\s\S]*?{re.escape(think_close)}", "", content)
    content = re.sub(rf"{re.escape(think_open)}[\s\S]*$", "", content)
    content = re.sub(rf"^[\s\S]*?{re.escape(think_close)}", "", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    content = re.sub(r"[ \t]{2,}", " ", content)
    return content.strip()


def _parse_tool_call_arguments(raw_arguments: Any) -> dict[str, Any]:
    """Normalize Ollama tool-call arguments to a dictionary."""
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            _LOGGER.warning(
                "[AGENT][OLLAMA] Failed to parse tool-call arguments JSON: %s",
                raw_arguments,
            )
    return {}


def _ollama_message_to_agent_message(message: dict[str, Any]) -> AgentMessage:
    """Map an Ollama /api/chat message object to a validated AgentMessage."""
    content = message.get("content")
    raw_tool_calls = message.get("tool_calls") or []
    tool_calls: list[ToolCall] = []

    for idx, raw_call in enumerate(raw_tool_calls):
        function_block = raw_call.get("function") or {}
        call_name = function_block.get("name") or ""
        arguments = _parse_tool_call_arguments(function_block.get("arguments"))
        call_id = raw_call.get("id") or f"call_{call_name}_{idx}"
        tool_calls.append(
            ToolCall(id=call_id, name=call_name, arguments=arguments)
        )

    return AgentMessage(
        role="model",
        content=content if content else None,
        tool_calls=tool_calls or None,
    )


class OllamaProvider:
    """Local Ollama agent provider backed by the /api/chat REST endpoint."""

    def generate_turn(
        self,
        messages: list[AgentMessage],
        tools: list[Any],
        profile: AgentModelProfile,
        system_instruction_override: str | None = None,
    ) -> AgentMessage:
        ollama_messages = _messages_to_ollama(messages)
        system_instruction = system_instruction_override or profile.system_instruction

        if system_instruction:
            ollama_messages.insert(
                0, {"role": "system", "content": system_instruction}
            )

        payload: dict[str, Any] = {
            "model": profile.api_model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": profile.default_temperature,
                "num_predict": profile.max_output_tokens,
            },
            "keep_alive": "5m",
        }

        if isinstance(profile, OllamaModelProfile):
            payload["think"] = profile.think

        if tools:
            payload["tools"] = [_function_to_openai_schema(tool) for tool in tools]

        url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"

        _LOGGER.info(
            "[AGENT][OLLAMA] generate_turn — model=%s messages=%d tools=%d",
            profile.api_model,
            len(ollama_messages),
            len(tools),
        )

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=profile.generation_timeout,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise RuntimeError(
                f"Ollama generation timed out after {profile.generation_timeout}s "
                f"for model {profile.api_model!r}."
            ) from exc
        except requests.ConnectionError as exc:
            raise RuntimeError(
                f"Failed to connect to Ollama at {OLLAMA_HOST}. "
                "Ensure the local Ollama daemon is running."
            ) from exc
        except RequestException as exc:
            status_detail = ""
            if exc.response is not None:
                status_detail = f" (HTTP {exc.response.status_code})"
            raise RuntimeError(
                f"Ollama request failed for model {profile.api_model!r}"
                f"{status_detail}: {exc}"
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Ollama returned non-JSON response (HTTP {response.status_code})."
            ) from exc

        message = data.get("message")
        if not isinstance(message, dict):
            raise RuntimeError(
                f"Ollama response missing 'message' object: {data!r}"
            )

        raw_content = message.get("content")
        if isinstance(raw_content, str) and raw_content:
            message["content"] = _strip_thinking_tags(raw_content)

        return _ollama_message_to_agent_message(message)
