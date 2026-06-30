from typing import Any

from google import genai
from google.genai import types

from core.agent.providers.gemini_models import GeminiModelProfile
from core.agent.types import AgentMessage, ToolCall


def _serialize_tool_output(output: Any) -> dict[str, Any]:
    if isinstance(output, dict):
        return output
    return {"result": output}


def _messages_to_contents(messages: list[AgentMessage]) -> list[types.Content]:
    contents: list[types.Content] = []

    for message in messages:
        parts: list[types.Part] = []

        if message.role == "user":
            if message.content:
                parts.append(types.Part.from_text(text=message.content))
            if parts:
                contents.append(types.Content(role="user", parts=parts))

        elif message.role == "model":
            if message.content:
                parts.append(types.Part.from_text(text=message.content))
            if message.tool_calls:
                for call in message.tool_calls:
                    parts.append(
                        types.Part.from_function_call(
                            name=call.name, args=call.arguments
                        )
                    )
            if parts:
                contents.append(types.Content(role="model", parts=parts))

        elif message.role == "tool":
            if message.tool_results:
                for result in message.tool_results:
                    parts.append(
                        types.Part.from_function_response(
                            name=result.name,
                            response=_serialize_tool_output(result.output),
                        )
                    )
            if parts:
                contents.append(types.Content(role="user", parts=parts))

    return contents


def _content_to_agent_message(content: types.Content) -> AgentMessage:
    text_segments: list[str] = []
    tool_calls: list[ToolCall] = []

    for part in content.parts or []:
        if part.text:
            text_segments.append(part.text)
        if part.function_call is not None:
            function_call = part.function_call
            call_id = function_call.id or f"{function_call.name}-{len(tool_calls)}"
            tool_calls.append(
                ToolCall(
                    id=call_id,
                    name=function_call.name,
                    arguments=function_call.args or {},
                )
            )

    combined_content = "".join(text_segments) if text_segments else None
    return AgentMessage(
        role="model",
        content=combined_content,
        tool_calls=tool_calls or None,
    )


class GeminiProvider:
    def __init__(self, api_key: str) -> None:
        self.client = genai.Client(api_key=api_key)

    def generate_turn(
        self,
        messages: list[AgentMessage],
        tools: list[dict],
        profile: GeminiModelProfile,
    ) -> AgentMessage:
        contents = _messages_to_contents(messages)

        config_kwargs: dict[str, Any] = {
            "temperature": profile.default_temperature,
            "system_instruction": "Your system-level agent instructions here",
        }
        if tools:
            config_kwargs["tools"] = tools
            config_kwargs["automatic_function_calling"] = (
                types.AutomaticFunctionCallingConfig(disable=True)
            )

        config = types.GenerateContentConfig(**config_kwargs)

        response = self.client.models.generate_content(
            model=profile.api_model,
            contents=contents,
            config=config,
        )

        if not response.candidates:
            raise ValueError("Gemini returned no response candidates.")

        candidate_content = response.candidates[0].content
        if candidate_content is None:
            raise ValueError("Gemini returned empty candidate content.")

        return _content_to_agent_message(candidate_content)
