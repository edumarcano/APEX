import logging
from typing import Any

from core.agent.providers.ollama_models import OllamaModelProfile
from core.agent.providers.gemini_models import GeminiModelProfile
from core.agent.types import AgentMessage

AgentModelProfile = GeminiModelProfile | OllamaModelProfile

_LOGGER = logging.getLogger(__name__)


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


class OllamaProvider:
    """Local Ollama agent provider (message translation scaffold; REST client TBD)."""

    def generate_turn(
        self,
        messages: list[AgentMessage],
        tools: list[Any],
        profile: AgentModelProfile,
        system_instruction_override: str | None = None,
    ) -> AgentMessage:
        translated = _messages_to_ollama(messages)
        system_instruction = system_instruction_override or profile.system_instruction

        _LOGGER.info(
            "[AGENT][OLLAMA] generate_turn stub — model=%s messages=%d tools=%d "
            "system_instruction_len=%d",
            profile.api_model,
            len(translated),
            len(tools),
            len(system_instruction),
        )
        _LOGGER.debug("[AGENT][OLLAMA] translated messages: %s", translated)

        return AgentMessage(
            role="model",
            content="[OllamaProvider stub] generate_turn not yet implemented.",
        )
