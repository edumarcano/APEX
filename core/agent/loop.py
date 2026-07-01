import inspect
import time
import traceback
from typing import Any, Callable, Dict, get_type_hints

from core.agent.providers.gemini import GeminiProvider
from core.agent.providers.gemini_models import GeminiModelProfile
from core.agent.tools import AGENT_TOOLS_REGISTRY
from core.agent.types import (
    AgentMessage,
    AgentQueryRequest,
    AgentQueryResponse,
    ToolResult,
)

ToolsDispatcher = Callable[[str, Dict[str, Any]], Any]


def default_tools_dispatcher(name: str, arguments: dict[str, Any]) -> Any:
    if name not in AGENT_TOOLS_REGISTRY:
        return f"Error: Tool '{name}' is not registered."

    try:
        func = AGENT_TOOLS_REGISTRY[name]
        type_hints = get_type_hints(func)
        sig = inspect.signature(func)
        validated_args: dict[str, Any] = {}

        for param_name, param in sig.parameters.items():
            if param_name not in arguments:
                if param.default != inspect.Parameter.empty:
                    validated_args[param_name] = param.default
                else:
                    return (
                        f"Error: Missing required argument '{param_name}' "
                        f"for tool '{name}'."
                    )
                continue

            value = arguments[param_name]
            declared_type = type_hints.get(param_name)

            if declared_type is int:
                try:
                    cast_value = int(value)
                except (TypeError, ValueError):
                    return (
                        f"Error: Argument '{param_name}' for tool '{name}' "
                        f"must be an integer; received {value!r}."
                    )

                if name == "get_weather_forecast":
                    cast_value = max(1, min(5, cast_value))
                elif name == "get_upcoming_calendar_events":
                    cast_value = max(1, min(14, cast_value))

                validated_args[param_name] = cast_value
            elif declared_type is float:
                try:
                    validated_args[param_name] = float(value)
                except (TypeError, ValueError):
                    return (
                        f"Error: Argument '{param_name}' for tool '{name}' "
                        f"must be a float; received {value!r}."
                    )
            elif declared_type is str:
                validated_args[param_name] = str(value)
            else:
                validated_args[param_name] = value

        return func(**validated_args)
    except Exception as exc:
        return f"Error during tool execution: {exc}"


def run_agent_loop(
    request: AgentQueryRequest,
    provider: GeminiProvider,
    profile: GeminiModelProfile,
    tools_dispatcher: ToolsDispatcher = default_tools_dispatcher,
) -> AgentQueryResponse:
    history: list[AgentMessage] = list(request.history)
    history.append(AgentMessage(role="user", content=request.prompt))

    tool_trace: list[dict[str, Any]] = []
    total_tool_executions = 0
    last_model_content: str | None = None

    try:
        for _turn in range(profile.max_tool_turns):
            model_message = provider.generate_turn(
                history,
                list(AGENT_TOOLS_REGISTRY.values()),
                profile,
            )
            history.append(model_message)

            if model_message.content:
                last_model_content = model_message.content

            if not model_message.tool_calls:
                return AgentQueryResponse(
                    answer=model_message.content or "",
                    profile_used=profile.model_dump(),
                    tool_trace=tool_trace,
                    session_id=request.session_id,
                )

            tool_results: list[ToolResult] = []

            for call in model_message.tool_calls:
                if total_tool_executions >= profile.max_tool_calls:
                    return AgentQueryResponse(
                        answer=last_model_content or "",
                        profile_used=profile.model_dump(),
                        tool_trace=tool_trace,
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
                    output = str(exc)

                duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
                total_tool_executions += 1

                tool_trace.append(
                    {
                        "name": call.name,
                        "status": status,
                        "duration_ms": duration_ms,
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
            session_id=request.session_id,
            error=(
                f"Agent turn limit reached ({profile.max_tool_turns} turns) "
                "without a final answer."
            ),
        )
    except Exception as exc:
        print(f"[AGENT][LOOP] Bounded loop execution crashed: {exc}")
        return AgentQueryResponse(
            answer=(
                "The Ask APEX agent encountered an issue reaching the cloud "
                "provider or running the requested operations. Please check "
                "your credentials, network status, or quota allocations, "
                "and try again."
            ),
            profile_used=profile.model_dump(),
            tool_trace=tool_trace,
            session_id=request.session_id,
            error=traceback.format_exc(),
        )
