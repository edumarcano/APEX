import inspect
import logging
import time
from typing import Any, Callable, Dict, Generic, Protocol, TypeVar, get_type_hints, runtime_checkable

from core.agent.providers.gemini_models import GeminiModelProfile
from core.agent.providers.ollama_models import OllamaModelProfile
from core.agent.tools import AGENT_TOOLS_REGISTRY
from core.agent.types import (
    AgentMessage,
    AgentQueryRequest,
    AgentQueryResponse,
    ToolResult,
)

AgentModelProfile = GeminiModelProfile | OllamaModelProfile
P = TypeVar("P", bound=AgentModelProfile, contravariant=True)

ToolsDispatcher = Callable[[str, Dict[str, Any]], Any]

ALLOWED_TOOL_OUTPUT_REGISTRY: set[str] = {
    "get_weather_forecast",
    "get_f1_driver_standings",
    "get_f1_season_calendar",
    "get_upcoming_calendar_events",
    "get_active_reminders",
    "get_briefing_history",
}

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class AgentProvider(Protocol[P]):
    def generate_turn(
        self,
        messages: list[AgentMessage],
        tools: list[Any],
        profile: P,
        system_instruction_override: str | None = None,
    ) -> AgentMessage:
        ...


def default_tools_dispatcher(name: str, arguments: dict[str, Any]) -> Any:
    if name not in AGENT_TOOLS_REGISTRY:
        raise ValueError(f"Tool '{name}' is not registered.")

    func = AGENT_TOOLS_REGISTRY[name]
    type_hints = get_type_hints(func)
    sig = inspect.signature(func)
    validated_args: dict[str, Any] = {}

    for param_name, param in sig.parameters.items():
        if param_name not in arguments:
            if param.default != inspect.Parameter.empty:
                validated_args[param_name] = param.default
            else:
                raise ValueError(
                    f"Missing required argument '{param_name}' for tool '{name}'."
                )
            continue

        value = arguments[param_name]
        declared_type = type_hints.get(param_name)

        if declared_type is int:
            try:
                cast_value = int(value)
            except (TypeError, ValueError) as exc:
                raise TypeError(
                    f"Argument '{param_name}' for tool '{name}' must be an integer; "
                    f"received {value!r}."
                ) from exc

            if name == "get_weather_forecast":
                cast_value = max(1, min(5, cast_value))
            elif name == "get_upcoming_calendar_events":
                cast_value = max(1, min(14, cast_value))

            validated_args[param_name] = cast_value
        elif declared_type is float:
            try:
                validated_args[param_name] = float(value)
            except (TypeError, ValueError) as exc:
                raise TypeError(
                    f"Argument '{param_name}' for tool '{name}' must be a float; "
                    f"received {value!r}."
                ) from exc
        elif declared_type is str:
            validated_args[param_name] = str(value)
        else:
            validated_args[param_name] = value

    return func(**validated_args)


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
            turn_tools: list[Any] = list(AGENT_TOOLS_REGISTRY.values())

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
                except Exception as exc:
                    status = "error"
                    _LOGGER.warning(
                        "Agent tool execution failed: tool=%s error_type=%s",
                        call.name,
                        type(exc).__name__,
                    )
                    output = {"error": "Tool execution failed."}

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
                    if call.name in ALLOWED_TOOL_OUTPUT_REGISTRY:
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
