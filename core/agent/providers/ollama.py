import inspect
import json
import logging
import re
from typing import Any, Callable, get_args, get_origin, get_type_hints

import requests
from requests.exceptions import RequestException

from core.agent.providers.gemini_models import GeminiModelProfile
from core.agent.providers.ollama_lifecycle import (
    get_http_session,
    get_keep_alive_duration,
    register_activity,
)
from core.agent.providers.ollama_models import OllamaModelProfile
from core.agent.types import AgentMessage, ToolCall
from core.config import OLLAMA_HOST

AgentModelProfile = GeminiModelProfile | OllamaModelProfile

_LOGGER = logging.getLogger(__name__)

# Tool schemas are derived from static registry callables; build each once.
_SCHEMA_CACHE: dict[Any, dict[str, Any]] = {}


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
    cached = _SCHEMA_CACHE.get(func)
    if cached is not None:
        return cached

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

    schema = {
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
    _SCHEMA_CACHE[func] = schema
    return schema


def _serialize_tool_output(output: Any) -> str:
    """Serialize tool output as stable JSON when possible."""
    try:
        return json.dumps(output, default=str)
    except (TypeError, ValueError):
        return str(output)


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
                        "tool_name": result.name,
                        "content": _serialize_tool_output(result.output),
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


def _post_chat(payload: dict[str, Any], profile: AgentModelProfile) -> dict[str, Any]:
    """POST a chat payload to Ollama, log telemetry, and return the parsed body."""
    url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"

    try:
        response = get_http_session().post(
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

    load_duration_ns = data.get("load_duration")
    prompt_eval_duration_ns = data.get("prompt_eval_duration")
    eval_count = data.get("eval_count")
    eval_duration_ns = data.get("eval_duration")

    if any(
        v is not None
        for v in (
            data.get("total_duration"),
            load_duration_ns,
            data.get("prompt_eval_count"),
            prompt_eval_duration_ns,
            eval_count,
            eval_duration_ns,
        )
    ):
        load_s = (
            load_duration_ns / 1e9
            if isinstance(load_duration_ns, (int, float))
            else 0.0
        )
        prompt_eval_s = (
            prompt_eval_duration_ns / 1e9
            if isinstance(prompt_eval_duration_ns, (int, float))
            else 0.0
        )
        token_count = eval_count if isinstance(eval_count, int) else 0
        tps = 0.0
        if (
            isinstance(eval_duration_ns, (int, float))
            and eval_duration_ns > 0
            and isinstance(eval_count, int)
        ):
            tps = (eval_count / eval_duration_ns) * 1e9
        _LOGGER.info(
            "[AGENT][OLLAMA] Telemetry: load=%.3fs, prompt_eval=%.3fs, "
            "generation=%d tokens at %.2f t/s",
            load_s,
            prompt_eval_s,
            token_count,
            tps,
        )

    return data


def _extract_message(data: dict[str, Any]) -> dict[str, Any]:
    """Validate and return the 'message' object from an Ollama chat response."""
    message = data.get("message")
    if not isinstance(message, dict):
        raise RuntimeError(
            f"Ollama response missing 'message' object: {data!r}"
        )
    return message


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

        options: dict[str, Any] = {
            "temperature": profile.default_temperature,
        }

        is_local_profile = isinstance(profile, OllamaModelProfile)

        if is_local_profile:
            resolved_num_predict = (
                profile.tool_select_max_tokens
                if tools
                else profile.final_answer_max_tokens
            )
            options["num_predict"] = resolved_num_predict
            options["num_thread"] = profile.num_thread
            options["num_ctx"] = profile.context_window

        payload: dict[str, Any] = {
            "model": profile.api_model,
            "messages": ollama_messages,
            "stream": False,
            "options": options,
            "keep_alive": get_keep_alive_duration(),
        }

        if is_local_profile:
            payload["think"] = profile.think

        if tools:
            payload["tools"] = [_function_to_openai_schema(tool) for tool in tools]

        _LOGGER.info(
            "[AGENT][OLLAMA] generate_turn — model=%s messages=%d tools=%d",
            profile.api_model,
            len(ollama_messages),
            len(tools),
        )

        data = _post_chat(payload, profile)

        if is_local_profile:
            register_activity(profile.api_model)

        message = _extract_message(data)

        # A tool-select turn that hit the num_predict ceiling without emitting
        # a tool call produced a truncated prose answer. Regenerate once
        # without tools under the final-answer token budget.
        if (
            is_local_profile
            and tools
            and data.get("done_reason") == "length"
            and not message.get("tool_calls")
        ):
            _LOGGER.info(
                "[AGENT][OLLAMA] Tool-select turn truncated at %s tokens without "
                "a tool call; regenerating as final answer",
                options.get("num_predict"),
            )
            retry_options = dict(options)
            retry_options["num_predict"] = profile.final_answer_max_tokens
            retry_payload = dict(payload)
            retry_payload.pop("tools", None)
            retry_payload["options"] = retry_options

            data = _post_chat(retry_payload, profile)
            register_activity(profile.api_model)
            message = _extract_message(data)

        raw_content = message.get("content")
        if isinstance(raw_content, str) and raw_content:
            message["content"] = _strip_thinking_tags(raw_content)

        return _ollama_message_to_agent_message(message)
