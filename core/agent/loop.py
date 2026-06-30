import time
from typing import Any, Callable, Dict

from core.agent.providers.gemini import GeminiProvider
from core.agent.providers.gemini_models import GeminiModelProfile
from core.agent.types import (
    AgentMessage,
    AgentQueryRequest,
    AgentQueryResponse,
    ToolResult,
)

ToolsDispatcher = Callable[[str, Dict[str, Any]], Any]


def run_agent_loop(
    request: AgentQueryRequest,
    provider: GeminiProvider,
    profile: GeminiModelProfile,
    tools_dispatcher: ToolsDispatcher,
) -> AgentQueryResponse:
    history: list[AgentMessage] = list(request.history)
    history.append(AgentMessage(role="user", content=request.prompt))

    tool_trace: list[dict[str, Any]] = []
    total_tool_executions = 0
    last_model_content: str | None = None
    list_of_tool_declarations: list[dict] = []

    for _turn in range(profile.max_tool_turns):
        model_message = provider.generate_turn(
            history, list_of_tool_declarations, profile
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
                        f"Tool execution limit reached ({profile.max_tool_calls} calls)."
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
