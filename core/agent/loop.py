import logging
import time
from typing import Any, Callable, Protocol, TypeGuard, TypeVar, runtime_checkable

from core.agent.capabilities import (
    CapabilityDescriptor,
    CapabilityError,
    CapabilityErrorCategory,
    invoke_capability,
    is_client_display_enabled,
    list_agent_capabilities,
)
from core.agent.local_commands import ResolvedLocalCommand, resolve_local_command
from core.agent.pricing import estimate_inference_cost
from core.agent.prompting import FINAL_ANSWER_INSTRUCTION
from core.agent.routing.tool_search import (
    SEARCH_AVAILABLE_TOOLS_NAME,
    ToolSearchRecoveryConfig,
    ToolSearchRecoveryState,
    can_expand_recovery_schemas,
    can_offer_search_recovery,
    execute_tool_search,
    expand_pending_descriptors,
    get_search_available_tools_descriptor,
)
from core.agent.providers.contract import (
    InferenceProvider,
    ProviderProfile,
    ProviderToolEvent,
    ProviderTurnResult,
    merge_token_usage,
    resolve_inference_provider,
)
from core.agent.providers.gemini_models import GeminiModelProfile
from core.agent.providers.ollama_models import OllamaModelProfile
from core.agent.local_runtime.contract import LocalModelProfile
from core.agent.types import (
    AgentMessage,
    AgentQueryRequest,
    AgentQueryResponse,
    Citation,
    LocalContextUsage,
    QueryTiming,
    TokenUsage,
    ToolResult,
)

# Import native handlers so capability registration runs at process start.
import core.agent.tools as _native_agent_tools  # noqa: F401

AgentModelProfile = GeminiModelProfile | OllamaModelProfile | ProviderProfile
P = TypeVar("P", bound=AgentModelProfile, contravariant=True)

ToolsDispatcher = Callable[[str, dict[str, Any]], Any]

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class AgentProvider(Protocol[P]):
    def generate_turn(
        self,
        messages: list[AgentMessage],
        tools: list[CapabilityDescriptor],
        profile: P,
        system_instruction_override: str | None = None,
    ) -> ProviderTurnResult:
        ...


def is_local_profile(profile: object) -> TypeGuard[LocalModelProfile]:
    """Return whether a profile uses the local Agent runtime contract."""
    return getattr(profile, "runtime", None) == "local"


def default_tools_dispatcher(name: str, arguments: dict[str, Any]) -> Any:
    """Invoke a registered capability through the shared capability registry."""
    return invoke_capability(name, arguments)


def build_agent_failure_details(
    profile: AgentModelProfile,
    exc: Exception,
) -> tuple[str, str]:
    """Return the sanitized provider-specific failure response."""
    if is_local_profile(profile):
        answer = (
            "The Apex Agent encountered an issue reaching the local "
            "provider or running the requested operations. Please verify that "
            "the local runtime is available, the model is installed, and system "
            "resources are sufficient, then try again."
        )
        error_detail = f"Local provider error ({type(exc).__name__})."
    else:
        answer = (
            "The Apex Agent encountered an issue reaching the cloud provider "
            "or running the requested operations. Please check your credentials, "
            "network status, or quota allocations, and try again."
        )
        error_detail = f"Cloud provider error ({type(exc).__name__})."
    return answer, error_detail


def run_agent_loop(
    request: AgentQueryRequest,
    provider: AgentProvider[P],
    profile: P,
    tools_dispatcher: ToolsDispatcher = default_tools_dispatcher,
    system_instruction_override: str | None = None,
    resolved_local_command: ResolvedLocalCommand | None = None,
    disable_cloud_tools: bool = False,
    cloud_tools: list[CapabilityDescriptor] | None = None,
    offered_tools: list[CapabilityDescriptor] | None = None,
    agent_key: str | None = None,
    tool_search_recovery: ToolSearchRecoveryConfig | None = None,
    recovery_diagnostics_holder: dict[str, object] | None = None,
) -> AgentQueryResponse:
    history: list[AgentMessage] = list(request.history)
    history.append(AgentMessage(role="user", content=request.prompt))

    tool_trace: list[dict[str, Any]] = []
    tool_outputs: list[dict[str, Any]] = []
    citations: list[Citation] = []
    provider_tool_events: list[ProviderToolEvent] = []
    total_tool_executions = 0
    last_model_content: str | None = None
    is_local = is_local_profile(profile)
    if offered_tools is not None:
        resolved_offered = list(offered_tools)
        local_tools = resolved_offered if is_local else []
        allowed_local_tools = {tool.name for tool in local_tools}
        resolved_cloud_tools = [] if is_local else resolved_offered
        allowed_cloud_tools = (
            set() if disable_cloud_tools else {tool.name for tool in resolved_cloud_tools}
        )
    elif is_local and request.tool_scope is not None:
        local_command = resolved_local_command or resolve_local_command(
            request.tool_scope
        )
        if local_command.scope != request.tool_scope:
            raise ValueError("Resolved local command does not match the request scope.")
        local_tools = list(local_command.descriptors)
        allowed_local_tools = {tool.name for tool in local_tools}
        resolved_cloud_tools = []
        allowed_cloud_tools = set()
    else:
        local_tools = []
        allowed_local_tools = set()
        resolved_cloud_tools = [] if is_local else (
            list(cloud_tools)
            if cloud_tools is not None
            else list_agent_capabilities()
        )
        allowed_cloud_tools = (
            set()
            if disable_cloud_tools
            else {tool.name for tool in resolved_cloud_tools}
        )
    estimated_prompt_tokens = 0
    peak_prompt_tokens: int | None = None
    history_messages_dropped = 0
    aggregated_usage: TokenUsage | None = None
    resolved_model: str | None = profile.api_model
    inference_provider: InferenceProvider | None
    try:
        inference_provider = resolve_inference_provider(profile)
    except TypeError:
        inference_provider = None
    provider_ms_total = 0.0
    apex_tool_ms_total = 0.0
    started_at = time.perf_counter()
    search_state: ToolSearchRecoveryState | None = None
    if tool_search_recovery and tool_search_recovery.enabled:
        search_state = ToolSearchRecoveryState(config=tool_search_recovery)
        if is_local:
            search_state.register_offered(local_tools)
        elif not disable_cloud_tools:
            search_state.register_offered(resolved_cloud_tools)

    def _attach_recovery_diagnostics() -> None:
        if search_state is None or recovery_diagnostics_holder is None:
            return
        recovery_diagnostics_holder.update(
            {
                "tool_search_enabled": True,
                "tool_search_attempted": search_state.search_attempted,
                "tool_search_invoked": search_state.invoked,
                "tool_search_succeeded": search_state.search_succeeded,
                "tool_search_calls": search_state.search_calls,
                "recovery_matched_families": list(search_state.matched_families),
                "recovered_families": list(search_state.recovered_families),
                "recovery_results_already_offered": list(
                    search_state.results_already_offered
                ),
                "recovery_expansion_blocked_by_budget": list(
                    search_state.expansion_blocked_by_budget
                ),
                "recovery_expanded_tool_count": search_state.expanded_tool_count,
                "recovery_extra_turns": search_state.extra_turns,
                "recovery_usable_turn_available": search_state.usable_recovery_turn_available,
            }
        )

    def response(
        *,
        answer: str,
        error: str | None = None,
    ) -> AgentQueryResponse:
        context_usage = None
        if is_local:
            context_usage = LocalContextUsage(
                estimated_prompt_tokens=estimated_prompt_tokens,
                peak_prompt_tokens=peak_prompt_tokens,
                context_window=profile.context_window,
                history_messages_dropped=history_messages_dropped,
            )
        total_ms = round((time.perf_counter() - started_at) * 1000, 2)
        timing = QueryTiming(
            total_ms=total_ms,
            provider_ms=round(provider_ms_total, 2),
            apex_tool_ms=round(apex_tool_ms_total, 2),
        )
        cost_estimate = estimate_inference_cost(
            model=resolved_model or profile.api_model,
            configured_model=profile.api_model,
            usage=aggregated_usage,
            hosted_tool_events=provider_tool_events,
            provider=inference_provider,
            agent_key=agent_key,
        )
        _attach_recovery_diagnostics()
        return AgentQueryResponse(
            answer=answer,
            agent_used=profile.model_dump(),
            tool_trace=tool_trace,
            tool_outputs=tool_outputs,
            session_id=request.session_id,
            error=error,
            tool_scope_used=request.tool_scope if is_local else None,
            local_context_usage=context_usage,
            resolved_model=resolved_model,
            usage=aggregated_usage,
            timing=timing,
            cost_estimate=cost_estimate,
            citations=citations,
        )

    def dispatch_tool(name: str, arguments: dict[str, Any]) -> Any:
        if name == SEARCH_AVAILABLE_TOOLS_NAME and search_state is not None:
            requested_max = arguments.get("max_results", search_state.config.max_result_families)
            try:
                max_results = int(requested_max)
            except (TypeError, ValueError):
                max_results = search_state.config.max_result_families
            max_results = max(1, min(max_results, search_state.config.max_result_families))
            return execute_tool_search(
                search_state.config.searchable_catalog,
                str(arguments.get("query", "")),
                max_results=max_results,
                max_capabilities_per_family=search_state.config.max_capabilities_per_family,
                history=request.history,
                excluded_families=sorted(search_state.config.offered_families),
            )
        return tools_dispatcher(name, arguments)

    try:
        for turn_index in range(profile.max_tool_turns):
            is_final_turn = turn_index == profile.max_tool_turns - 1
            if search_state is not None:
                search_state.usable_recovery_turn_available = can_offer_search_recovery(
                    profile.max_tool_turns,
                    turn_index,
                )

            if (
                search_state
                and search_state.pending_descriptors
                and can_expand_recovery_schemas(profile.max_tool_turns, turn_index)
            ):
                target_tools = local_tools if is_local else resolved_cloud_tools
                added, count, blocked = expand_pending_descriptors(
                    pending=search_state.pending_descriptors,
                    offered=target_tools,
                    expansion_allowance=search_state.config.max_expansion_schema_tokens,
                    blocked=search_state.blocked_descriptors,
                )
                search_state.pending_descriptors = []
                search_state.blocked_descriptors = blocked
                if added:
                    search_state.expanded_tool_count += count
                    search_state.extra_turns += 1
                    search_state.register_offered(added)
                    expanded_families = sorted(
                        {
                            descriptor.routing_family
                            for descriptor in added
                            if descriptor.routing_family is not None
                        }
                    )
                    search_state.recovered_families = expanded_families
                    search_state.expansion_blocked_by_budget = sorted(
                        {
                            descriptor.routing_family
                            for descriptor in blocked
                            if descriptor.routing_family is not None
                        }
                    )
                    if is_local:
                        allowed_local_tools.update(descriptor.name for descriptor in added)
                    else:
                        allowed_cloud_tools.update(descriptor.name for descriptor in added)

            turn_tools: list[CapabilityDescriptor] = (
                list(local_tools)
                if is_local
                else (
                    []
                    if disable_cloud_tools
                    else list(resolved_cloud_tools)
                )
            )

            if (
                search_state is not None
                and not is_final_turn
                and can_offer_search_recovery(profile.max_tool_turns, turn_index)
                and search_state.search_calls < search_state.config.max_search_calls
            ):
                search_descriptor = get_search_available_tools_descriptor()
                if all(tool.name != SEARCH_AVAILABLE_TOOLS_NAME for tool in turn_tools):
                    turn_tools.append(search_descriptor)

            # Withhold tools on the last permitted turn so every provider must
            # use its final model request to answer from the results already
            # collected instead of requesting a call that cannot be followed up.
            turn_instruction = system_instruction_override
            if is_final_turn:
                turn_tools = []
                turn_instruction = (
                    system_instruction_override or profile.system_instruction
                ) + FINAL_ANSWER_INSTRUCTION

            turn_result = provider.generate_turn(
                history,
                turn_tools,
                profile,
                system_instruction_override=turn_instruction,
            )
            model_message = turn_result.message
            history.append(model_message)
            if turn_result.provider_ms is not None:
                provider_ms_total += turn_result.provider_ms
            aggregated_usage = merge_token_usage(aggregated_usage, turn_result.usage)
            if turn_result.resolved_model:
                resolved_model = turn_result.resolved_model
            if turn_result.citations:
                citations.extend(turn_result.citations)
            if turn_result.provider_tool_events:
                provider_tool_events.extend(turn_result.provider_tool_events)
                for event in turn_result.provider_tool_events:
                    tool_trace.append(
                        {
                            "name": event.name,
                            "status": event.status,
                            "duration_ms": event.duration_ms,
                            "origin": "provider",
                            "billable_units": event.billable_units,
                        }
                    )

            estimated_prompt_tokens = max(
                estimated_prompt_tokens,
                turn_result.estimated_prompt_tokens
                or model_message.estimated_prompt_tokens
                or 0,
            )
            history_messages_dropped = max(
                history_messages_dropped,
                turn_result.history_messages_dropped,
                model_message.history_messages_dropped,
            )
            if model_message.prompt_tokens is not None:
                peak_prompt_tokens = max(
                    peak_prompt_tokens or 0,
                    model_message.prompt_tokens,
                )
            elif turn_result.usage and turn_result.usage.input_tokens is not None:
                peak_prompt_tokens = max(
                    peak_prompt_tokens or 0,
                    turn_result.usage.input_tokens,
                )

            if model_message.content:
                last_model_content = model_message.content

            if not model_message.tool_calls:
                return response(answer=model_message.content or "")

            tool_results: list[ToolResult] = []

            for call in model_message.tool_calls:
                if total_tool_executions >= profile.max_tool_calls:
                    return response(
                        answer=last_model_content or "",
                        error=(
                            f"Tool execution limit reached "
                            f"({profile.max_tool_calls} calls)."
                        ),
                    )

                tool_started = time.perf_counter()
                status = "ok"
                output: Any

                try:
                    if call.name == SEARCH_AVAILABLE_TOOLS_NAME:
                        if search_state is None:
                            raise CapabilityError(
                                CapabilityErrorCategory.UNAVAILABLE,
                                "Tool search recovery is not enabled for this request.",
                            )
                        if not can_offer_search_recovery(
                            profile.max_tool_turns,
                            turn_index,
                        ):
                            raise CapabilityError(
                                CapabilityErrorCategory.UNAVAILABLE,
                                "No remaining tool-enabled turn is available for recovery.",
                            )
                        if search_state.search_attempted:
                            raise CapabilityError(
                                CapabilityErrorCategory.UNAVAILABLE,
                                "Tool search recovery limit reached for this request.",
                            )
                        search_state.search_attempted = True
                        search_state.search_calls += 1
                    if is_local and call.name not in allowed_local_tools:
                        if call.name != SEARCH_AVAILABLE_TOOLS_NAME:
                            raise CapabilityError(
                                CapabilityErrorCategory.UNAVAILABLE,
                                "Tool is outside the selected local command scope.",
                            )
                    if not is_local and call.name not in allowed_cloud_tools:
                        if call.name != SEARCH_AVAILABLE_TOOLS_NAME:
                            raise CapabilityError(
                                CapabilityErrorCategory.UNAVAILABLE,
                                "Tool is outside the selected Agent policy.",
                            )
                    output = dispatch_tool(call.name, call.arguments)
                    if (
                        call.name == SEARCH_AVAILABLE_TOOLS_NAME
                        and search_state is not None
                        and status == "ok"
                    ):
                        search_state.invoked = True
                        if isinstance(output, dict):
                            search_state.search_succeeded = output.get("match_count", 0) > 0
                            search_state.queue_recovery_descriptors(output)
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

                duration_ms = round((time.perf_counter() - tool_started) * 1000, 2)
                apex_tool_ms_total += duration_ms
                total_tool_executions += 1

                tool_trace.append(
                    {
                        "name": call.name,
                        "status": status,
                        "duration_ms": duration_ms,
                        "origin": "apex",
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

        return response(
            answer=last_model_content or "",
            error=(
                f"Agent turn limit reached ({profile.max_tool_turns} turns) "
                "without a final answer."
            ),
        )
    except Exception as exc:
        _LOGGER.exception(
            "Bounded Agent loop failed for model configuration %s",
            profile.api_model,
        )
        answer, error_detail = build_agent_failure_details(profile, exc)
        return response(
            answer=answer,
            error=error_detail,
        )
