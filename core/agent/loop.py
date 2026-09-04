import logging
import inspect
import time
from typing import Any, Callable, Mapping, Protocol, TypeGuard, TypeVar, runtime_checkable

from core.agent.capabilities import (
    CapabilityDescriptor,
    CapabilityError,
    CapabilityErrorCategory,
    invoke_capability,
    is_client_display_enabled,
    validate_capability_arguments,
)
from core.actions.runtime import get_action_service
from core.config import DEMO_MODE
from core.agent.pricing import estimate_inference_cost
from core.agent.prompting import FINAL_ANSWER_INSTRUCTION
from core.agent.tool_schemas import descriptor_to_openai_schema, estimate_json_tokens
from core.agent.providers.contract import (
    InferenceProvider,
    ProviderProfile,
    ProviderToolEvent,
    ProviderTurnResult,
    ProviderStreamObserver,
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
    GroundingPresentation,
    LocalContextUsage,
    QueryTiming,
    TokenUsage,
    ToolSelectionDiagnostics,
    ToolResult,
)

# Import native handlers so capability registration runs at process start.
import core.agent.tools as _native_agent_tools  # noqa: F401
from core.tracing import trace_provider_turn, trace_tool_execution

AgentModelProfile = GeminiModelProfile | OllamaModelProfile | ProviderProfile
P = TypeVar("P", bound=AgentModelProfile, contravariant=True)

ToolsDispatcher = Callable[[str, dict[str, Any]], Any]


class ExecutionStopped(RuntimeError):
    """A coordinator requested a safe, cooperative end to a run."""


class ExecutionCancelled(ExecutionStopped):
    """The operator cancelled the run."""


class ExecutionLimitReached(ExecutionStopped):
    """A cumulative run limit was reached."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ExecutionControl(Protocol):
    """Optional per-run callbacks supplied by the run coordinator."""

    def before_model_turn(self) -> None: ...
    def after_model_turn(self, result: ProviderTurnResult) -> None: ...
    def before_tool(self) -> None: ...
    def after_tool(self) -> None: ...
    def before_provider_attempt(self) -> None: ...
    def before_retry(self, retry_number: int = 0) -> None: ...
    def remaining_seconds(self) -> float: ...

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
        overflow = any(
            marker in str(exc).lower()
            for marker in (
                "local prompt budget exceeded",
                "context length",
                "context window",
                "too many tokens",
                "prompt is too long",
                "prompt too long",
                "input length",
            )
        ) or bool(getattr(exc, "is_context_overflow", False))
        if overflow:
            return (
                "The current interaction is too large for the local Agent "
                "context window after older complete interactions were removed. "
                "Shorten the prompt, select fewer tools, or start a new session "
                "and try again.",
                "Local context overflow: the current interaction did not fit "
                "after provider-authoritative history trimming.",
            )
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


_PRIOR_TOOL_OUTPUT_MAX_CHARS = 400


def _compact_tool_result_output(
    output: Any, max_chars: int = _PRIOR_TOOL_OUTPUT_MAX_CHARS
) -> Any:
    """Compact an earlier tool result within a multi-turn query to bound prompt growth."""
    import json

    if isinstance(output, dict) and output.get("compacted") is True:
        return output
    if isinstance(output, str):
        if output.endswith("... [prior step output compacted]"):
            return output
        if len(output) <= max_chars:
            return output
        return f"{output[:max_chars]}... [prior step output compacted]"
    if isinstance(output, (dict, list, tuple)):
        try:
            serialized = json.dumps(output, default=str)
        except Exception:
            serialized = str(output)
        if len(serialized) <= max_chars:
            return output
        preview = serialized[:max_chars]
        return {
            "preview": f"{preview}... [prior step output compacted]",
            "compacted": True,
        }
    return output


def run_agent_loop(
    request: AgentQueryRequest,
    provider: AgentProvider[P],
    profile: P,
    tools_dispatcher: ToolsDispatcher = default_tools_dispatcher,
    system_instruction_override: str | None = None,
    selected_tools: list[CapabilityDescriptor] | None = None,
    tool_selection: ToolSelectionDiagnostics | None = None,
    agent_key: str | None = None,
    action_provenance: Mapping[str, object] | None = None,
    execution_control: ExecutionControl | None = None,
    stream_observer: ProviderStreamObserver | None = None,
    activity_observer: Callable[[str, dict[str, Any]], None] | None = None,
    output_schema: dict[str, Any] | None = None,
) -> AgentQueryResponse:
    history: list[AgentMessage] = list(request.history)
    history.append(AgentMessage(role="user", content=request.prompt))

    turn_tool_messages: list[AgentMessage] = []
    tool_trace: list[dict[str, Any]] = []
    tool_outputs: list[dict[str, Any]] = []
    citations: list[Citation] = []
    grounding: GroundingPresentation | None = None
    provider_tool_events: list[ProviderToolEvent] = []
    total_tool_executions = 0
    last_model_content: str | None = None
    is_local = is_local_profile(profile)
    resolved_tools = list(selected_tools or [])
    allowed_tools = {tool.name for tool in resolved_tools}
    descriptors_by_name = {tool.name: tool for tool in resolved_tools}
    if tool_selection is None:
        requested_names = (
            list(request.selected_tool_names)
            if "selected_tool_names" in request.model_fields_set
            else []
        )
        tool_selection = ToolSelectionDiagnostics(
            requested_tool_names=requested_names,
            offered_tool_names=[tool.name for tool in resolved_tools],
            selected_schema_tokens=(
                estimate_json_tokens(
                    [
                        descriptor_to_openai_schema(tool)
                        for tool in resolved_tools
                    ]
                )
                if resolved_tools
                else 0
            ),
            active_profile_id=request.tool_profile_id,
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
        return AgentQueryResponse(
            answer=answer,
            agent_used=profile.model_dump(),
            tool_trace=tool_trace,
            tool_outputs=tool_outputs,
            session_id=request.session_id,
            error=error,
            resolved_tool_selection=tool_selection or ToolSelectionDiagnostics(),
            requested_tool_names=(
                tool_selection.requested_tool_names
                if tool_selection is not None
                else []
            ),
            offered_tool_names=(
                tool_selection.offered_tool_names if tool_selection is not None else []
            ),
            rejected_tool_names=(
                tool_selection.rejected_tool_names
                if tool_selection is not None
                else []
            ),
            selected_schema_tokens=(
                tool_selection.selected_schema_tokens
                if tool_selection is not None
                else 0
            ),
            active_tool_profile_id=(
                tool_selection.active_profile_id
                if tool_selection is not None
                else None
            ),
            active_tool_profile_name=(
                tool_selection.active_profile_name
                if tool_selection is not None
                else None
            ),
            local_context_usage=context_usage,
            resolved_model=resolved_model,
            usage=aggregated_usage,
            timing=timing,
            cost_estimate=cost_estimate,
            citations=citations,
            grounding=grounding,
        )

    try:
        for _turn in range(profile.max_tool_turns):
            if execution_control is not None:
                execution_control.before_model_turn()
            turn_tools: list[CapabilityDescriptor] = list(resolved_tools)

            # Withhold tools on the last permitted turn so every provider must
            # use its final model request to answer from the results already
            # collected instead of requesting a call that cannot be followed up.
            is_final_turn = _turn == profile.max_tool_turns - 1
            turn_instruction = system_instruction_override
            if is_final_turn:
                turn_tools = []
                turn_instruction = (
                    system_instruction_override or profile.system_instruction
                ) + FINAL_ANSWER_INSTRUCTION

            generate_kwargs: dict[str, Any] = {
                "system_instruction_override": turn_instruction,
            }
            provisional_text = False

            def observe_stream(event) -> None:
                nonlocal provisional_text
                if event.kind == "text" and event.text:
                    provisional_text = True
                elif event.kind == "reset":
                    provisional_text = False
                if stream_observer is not None:
                    stream_observer(event)

            if activity_observer is not None:
                activity_observer("model.started", {"turn": _turn + 1})
            # Existing test and extension providers may implement the small
            # pre-beta.2 contract.  Pass the new seam only when supported.
            parameters = inspect.signature(provider.generate_turn).parameters
            if "execution_control" in parameters:
                generate_kwargs["execution_control"] = execution_control
            if "stream_observer" in parameters:
                generate_kwargs["stream_observer"] = observe_stream
            if "output_schema" in parameters:
                generate_kwargs["output_schema"] = output_schema if is_final_turn else None
            with trace_provider_turn(
                model=profile.api_model,
                provider=profile.provider,
                turn=_turn + 1,
            ) as provider_span_ctx:
                turn_result = provider.generate_turn(
                    history, turn_tools, profile, **generate_kwargs
                )
                provider_span_ctx.record_result(turn_result)
            if execution_control is not None:
                execution_control.after_model_turn(turn_result)
            if activity_observer is not None:
                activity_observer(
                    "model.completed",
                    {
                        "turn": _turn + 1,
                        "provider_ms": turn_result.provider_ms,
                    },
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
            if turn_result.grounding is not None:
                grounding = turn_result.grounding
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
                    if activity_observer is not None:
                        activity_observer(
                            "tool.completed",
                            {
                                "name": event.name,
                                "origin": "provider",
                                "status": event.status,
                                "duration_ms": event.duration_ms,
                            },
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
                if activity_observer is not None:
                    activity_observer(
                        "response.completed",
                        {"answer": model_message.content or ""},
                    )
                return response(answer=model_message.content or "")

            if provisional_text and activity_observer is not None:
                activity_observer("response.reset", {})

            tool_results: list[ToolResult] = []

            for call in model_message.tool_calls:
                if execution_control is not None:
                    execution_control.before_tool()
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
                error_cat: str | None = None
                action_id: str | None = None
                action_risk: str | None = None
                if activity_observer is not None:
                    activity_observer(
                        "tool.started",
                        {"name": call.name, "origin": "apex"},
                    )

                with trace_tool_execution(
                    tool_name=call.name,
                    origin="apex",
                ) as tool_span_ctx:
                    try:
                        if call.name not in allowed_tools:
                            raise CapabilityError(
                                CapabilityErrorCategory.UNAVAILABLE,
                                "Tool is outside the resolved Agent tool selection.",
                            )
                        descriptor = descriptors_by_name.get(call.name)
                        if descriptor is None:
                            raise CapabilityError(
                                CapabilityErrorCategory.UNAVAILABLE,
                                "Tool is outside the resolved Agent tool selection.",
                            )
                        if descriptor.risk == "read":
                            output = tools_dispatcher(call.name, call.arguments)
                        else:
                            if DEMO_MODE:
                                raise CapabilityError(
                                    CapabilityErrorCategory.UNAVAILABLE,
                                    "Action capabilities are unavailable in demo mode.",
                                )
                            action_service = get_action_service()
                            if (
                                descriptor.origin != "native"
                                or action_service is None
                                or not action_service.supports(call.name)
                            ):
                                raise CapabilityError(
                                    CapabilityErrorCategory.UNAVAILABLE,
                                    "Action capability is unavailable.",
                                )
                            arguments = validate_capability_arguments(
                                call.name, call.arguments
                            )
                            if call.name == "remember_personal_context":
                                from core.knowledge.capture import reject_secret_text, validate_effective_at

                                reject_secret_text(str(arguments.get("text", "")))
                                validate_effective_at(arguments.get("effective_at"))
                                if action_provenance is None:
                                    raise CapabilityError(
                                        CapabilityErrorCategory.UNAVAILABLE,
                                        "Personal context capture requires a persisted conversation source.",
                                    )
                                arguments["_apex_provenance"] = dict(action_provenance)
                            action = action_service.propose(
                                agent_key=agent_key or request.agent,
                                capability_name=call.name,
                                arguments=arguments,
                                target=descriptor.title,
                                risk=descriptor.risk,
                                summary=f"Approve {descriptor.title}",
                            )
                            action_id = action.action_id
                            action_risk = action.proposal.risk
                            output = {
                                "action_id": action.action_id,
                                "status": action.status,
                                "message": (
                                    "Action proposed. It has not been executed and "
                                    "requires operator approval."
                                ),
                                "version": action.version,
                                "risk": action.proposal.risk,
                                "summary": action.proposal.summary,
                                "target": action.proposal.target,
                            }
                            if activity_observer is not None:
                                activity_observer(
                                    "action.proposed",
                                    {
                                        "action_id": action.action_id,
                                        "status": action.status,
                                        "risk": action.proposal.risk,
                                    },
                                )
                    except CapabilityError as exc:
                        status = "error"
                        error_cat = exc.category.value
                        _LOGGER.warning(
                            "Agent capability failed: tool=%s category=%s",
                            call.name,
                            exc.category.value,
                        )
                        output = exc.as_output()
                    except Exception as exc:
                        status = "error"
                        error_cat = CapabilityErrorCategory.UPSTREAM_FAILURE.value
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
                    tool_span_ctx.record_completion(
                        duration_ms=duration_ms,
                        status=status,
                        error_category=error_cat,
                        action_id=action_id,
                        action_risk=action_risk,
                    )

                tool_trace.append(
                    {
                        "name": call.name,
                        "status": status,
                        "duration_ms": duration_ms,
                        "origin": "apex",
                    }
                )
                if activity_observer is not None:
                    activity_observer(
                        "tool.completed",
                        {
                            "name": call.name,
                            "origin": "apex",
                            "status": status,
                            "duration_ms": duration_ms,
                        },
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
                if execution_control is not None:
                    execution_control.after_tool()

            if turn_tool_messages:
                for prior_result in turn_tool_messages[-1].tool_results or []:
                    prior_result.output = _compact_tool_result_output(
                        prior_result.output
                    )

            tool_message = AgentMessage(role="tool", tool_results=tool_results)
            turn_tool_messages.append(tool_message)
            history.append(tool_message)

        return response(
            answer=last_model_content or "",
            error=(
                f"Agent turn limit reached ({profile.max_tool_turns} turns) "
                "without a final answer."
            ),
        )
    except ExecutionStopped:
        raise
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
