import logging
import time
from typing import Any, Callable, Dict, Protocol, TypeVar, runtime_checkable

from core.agent.capabilities import (
    CapabilityDescriptor,
    CapabilityError,
    CapabilityErrorCategory,
    invoke_capability,
    is_client_display_enabled,
    list_assistant_capabilities,
)
from core.agent.providers.gemini_models import GeminiModelProfile
from core.agent.providers.ollama_models import OllamaModelProfile
from core.agent.types import (
    AgentMessage,
    AgentQueryRequest,
    AgentQueryResponse,
    ToolResult,
)

# Import native handlers so capability registration runs at process start.
import core.agent.tools as _native_agent_tools  # noqa: F401

AgentModelProfile = GeminiModelProfile | OllamaModelProfile
P = TypeVar("P", bound=AgentModelProfile, contravariant=True)

ToolsDispatcher = Callable[[str, Dict[str, Any]], Any]

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class AgentProvider(Protocol[P]):
    def generate_turn(
        self,
        messages: list[AgentMessage],
        tools: list[CapabilityDescriptor],
        profile: P,
        system_instruction_override: str | None = None,
    ) -> AgentMessage:
        ...


def default_tools_dispatcher(name: str, arguments: dict[str, Any]) -> Any:
    """Invoke a registered capability through the shared capability registry."""
    return invoke_capability(name, arguments)


def run_agent_loop(
    request: AgentQueryRequest,
    provider: AgentProvider[P],
    profile: P,
    tools_dispatcher: ToolsDispatcher = default_tools_dispatcher,
    system_instruction_override: str | None = None,
) -> AgentQueryResponse:
    history: list[AgentMessage] = list(request.history)
    history.append(AgentMessage(role="user", content=request.prompt))

    tool_trace: list[dict[str, Any]] = []
    tool_outputs: list[dict[str, Any]] = []
    total_tool_executions = 0
    last_model_content: str | None = None

    try:
        for _turn in range(profile.max_tool_turns):
            turn_tools: list[CapabilityDescriptor] = list_assistant_capabilities()

            # On the last permitted local turn, withhold tools so the model is
            # forced into a text answer under the final-answer token budget
            # instead of burning the turn on a tool call that can never run.
            if (
                isinstance(profile, OllamaModelProfile)
                and _turn == profile.max_tool_turns - 1
            ):
                turn_tools = []

            model_message = provider.generate_turn(
                history,
                turn_tools,
                profile,
                system_instruction_override=system_instruction_override,
            )
            history.append(model_message)

            if model_message.content:
                last_model_content = model_message.content

            if not model_message.tool_calls:
                return AgentQueryResponse(
                    answer=model_message.content or "",
                    profile_used=profile.model_dump(),
                    tool_trace=tool_trace,
                    tool_outputs=tool_outputs,
                    session_id=request.session_id,
                )

            tool_results: list[ToolResult] = []

            for call in model_message.tool_calls:
                if total_tool_executions >= profile.max_tool_calls:
                    return AgentQueryResponse(
                        answer=last_model_content or "",
                        profile_used=profile.model_dump(),
                        tool_trace=tool_trace,
                        tool_outputs=tool_outputs,
                        session_id=request.session_id,
                        error=(
                            f"Tool execution limit reached "
                            f"({profile.max_tool_calls} calls)."
                        ),
                    )

                started_at = time.perf_counter()
                status = "ok"
                output: Any

                try:
                    output = tools_dispatcher(call.name, call.arguments)
                except CapabilityError as exc:
                    status = "error"
                    _LOGGER.warning(
                        "Agent capability failed: tool=%s category=%s",
                        call.name,
                        exc.category.value,
                    )
                    output = exc.as_output()
                except Exception as exc:
                    status = "error"
                    _LOGGER.warning(
                        "Agent tool execution failed: tool=%s error_type=%s",
                        call.name,
                        type(exc).__name__,
                    )
                    output = {
                        "error": "Tool execution failed.",
                        "error_category": (
                            CapabilityErrorCategory.UPSTREAM_FAILURE.value
                        ),
                    }

                duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
                total_tool_executions += 1

                tool_trace.append(
                    {
                        "name": call.name,
                        "status": status,
                        "duration_ms": duration_ms,
                    }
                )

                if status == "ok":
                    if is_client_display_enabled(call.name):
                        whitelisted_output: Any = output
                    else:
                        whitelisted_output = {
                            "error": "Tool output is not whitelisted for client display."
                        }
                else:
                    whitelisted_output = output

                tool_outputs.append(
                    {
                        "name": call.name,
                        "status": status,
                        "duration_ms": duration_ms,
                        "output": whitelisted_output,
                    }
                )

                tool_results.append(
                    ToolResult(id=call.id, name=call.name, output=output)
                )

            history.append(AgentMessage(role="tool", tool_results=tool_results))

        return AgentQueryResponse(
            answer=last_model_content or "",
            profile_used=profile.model_dump(),
            tool_trace=tool_trace,
            tool_outputs=tool_outputs,
            session_id=request.session_id,
            error=(
                f"Agent turn limit reached ({profile.max_tool_turns} turns) "
                "without a final answer."
            ),
        )
    except Exception as exc:
        _LOGGER.exception(
            "Bounded agent loop failed for profile %s",
            profile.api_model,
        )
        if isinstance(profile, OllamaModelProfile):
            answer = (
                "The APEX assistant encountered an issue reaching the local Ollama "
                "provider or running the requested operations. Please verify that "
                "Ollama is running, the model is installed, and system resources "
                "are sufficient, then try again."
            )
            error_detail = f"Local provider error ({type(exc).__name__})."
        else:
            answer = (
                "The APEX assistant encountered an issue reaching the cloud provider "
                "or running the requested operations. Please check your "
                "credentials, network status, or quota allocations, and try again."
            )
            error_detail = f"Cloud provider error ({type(exc).__name__})."

        return AgentQueryResponse(
            answer=answer,
            profile_used=profile.model_dump(),
            tool_trace=tool_trace,
            tool_outputs=tool_outputs,
            session_id=request.session_id,
            error=error_detail,
        )
