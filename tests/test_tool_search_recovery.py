"""Focused coverage for policy-safe tool search recovery."""

from __future__ import annotations

import unittest
from unittest import mock

from core.agent.capabilities import (
    CapabilityDescriptor,
    CapabilityError,
    CapabilityErrorCategory,
    list_agent_capabilities,
)
from core.agent.local_commands import estimate_schema_tokens
from core.agent.loop import run_agent_loop
from core.agent.routing.tool_search import (
    SEARCH_AVAILABLE_TOOLS_NAME,
    ToolSearchRecoveryConfig,
    build_searchable_catalog,
    can_offer_search_recovery,
    execute_tool_search,
    expand_pending_descriptors,
    get_search_available_tools_descriptor,
    search_available_tools,
)
from core.agent.types import AgentMessage, AgentQueryRequest, ToolCall


def _descriptor(
    name: str,
    family: str,
    *,
    risk: str = "read",
    expose: bool = True,
    schema: dict | None = None,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        name=name,
        title=name,
        description=f"{name} for {family}",
        input_schema=schema or {"type": "object", "properties": {}},
        origin="native",
        risk=risk,  # type: ignore[arg-type]
        expose_to_agent=expose,
        expose_to_mcp_server=False,
        expose_to_client_display=True,
        routing_family=family,
    )


class ToolSearchCatalogTests(unittest.TestCase):
    def test_build_searchable_catalog_excludes_write_and_unauthorized_tools(self) -> None:
        catalog = build_searchable_catalog(
            [
                _descriptor("get_weather_forecast", "weather"),
                _descriptor("search_gmail", "mail"),
                _descriptor("delete_repo", "github", risk="write"),
                _descriptor("hidden_tool", "search", expose=False),
            ],
            runtime="cloud",
            agent_key="acinonyx",
        )
        names = {descriptor.name for descriptor in catalog}
        self.assertIn("get_weather_forecast", names)
        self.assertNotIn("search_gmail", names)
        self.assertNotIn("delete_repo", names)
        self.assertNotIn("hidden_tool", names)

    def test_build_searchable_catalog_excludes_already_offered_tools(self) -> None:
        catalog = build_searchable_catalog(
            [
                _descriptor("get_weather_forecast", "weather"),
                _descriptor("search_gmail", "mail"),
            ],
            runtime="cloud",
            agent_key="neofelis",
            offered_names=["get_weather_forecast"],
        )
        names = {descriptor.name for descriptor in catalog}
        self.assertNotIn("get_weather_forecast", names)
        self.assertIn("search_gmail", names)

    def test_search_excludes_already_offered_families_from_results(self) -> None:
        catalog = build_searchable_catalog(
            [
                _descriptor("get_weather_forecast", "weather"),
                _descriptor("search_gmail", "mail"),
            ],
            runtime="cloud",
            agent_key="neofelis",
            offered_names=["get_weather_forecast"],
        )
        result = execute_tool_search(
            catalog,
            "gmail inbox",
            max_results=3,
            max_capabilities_per_family=3,
            excluded_families=["weather"],
        )
        families = {match["family"] for match in result["matches"]}
        self.assertNotIn("weather", families)

    def test_search_clamps_max_results_to_configuration(self) -> None:
        catalog = build_searchable_catalog(
            [
                _descriptor("get_weather_forecast", "weather"),
                _descriptor("search_gmail", "mail"),
                _descriptor("get_stock_quote", "market"),
                _descriptor("brave_brave_web_search", "search"),
            ],
            runtime="cloud",
            agent_key="neofelis",
        )
        result = execute_tool_search(
            catalog,
            "weather mail market search",
            max_results=3,
            max_capabilities_per_family=1,
        )
        self.assertLessEqual(result["match_count"], 3)

    def test_search_available_tools_requires_active_recovery(self) -> None:
        with self.assertRaises(CapabilityError) as ctx:
            search_available_tools("weather forecast")
        self.assertEqual(ctx.exception.category, CapabilityErrorCategory.UNAVAILABLE)

    def test_search_descriptor_is_not_agent_discoverable(self) -> None:
        descriptor = get_search_available_tools_descriptor()
        exposed = {item.name for item in list_agent_capabilities()}
        self.assertFalse(descriptor.expose_to_agent)
        self.assertNotIn(SEARCH_AVAILABLE_TOOLS_NAME, exposed)


class ToolSearchBudgetTests(unittest.TestCase):
    def test_expansion_allowance_counts_only_added_tokens(self) -> None:
        small = _descriptor("small_tool", "weather", schema={"type": "object", "properties": {"a": {"type": "string"}}})
        large = _descriptor(
            "large_tool",
            "mail",
            schema={
                "type": "object",
                "properties": {f"p{i}": {"type": "string"} for i in range(40)},
            },
        )
        offered = [_descriptor("existing_tool", "weather")]
        initial_tokens = estimate_schema_tokens(offered)
        added, count, blocked = expand_pending_descriptors(
            pending=[large, small],
            offered=offered,
            expansion_allowance=estimate_schema_tokens([small]) + 5,
        )
        self.assertEqual(count, 1)
        self.assertEqual(added[0].name, "small_tool")
        self.assertEqual(len(blocked), 1)
        self.assertGreater(estimate_schema_tokens(offered), initial_tokens)

    def test_partially_consumed_allowance_still_fits_smaller_descriptor(self) -> None:
        tiny = _descriptor("tiny", "todo")
        medium = _descriptor(
            "medium",
            "schedule",
            schema={"type": "object", "properties": {f"k{i}": {"type": "string"} for i in range(10)}},
        )
        offered: list[CapabilityDescriptor] = []
        allowance = estimate_schema_tokens([tiny])
        added_first, _, blocked = expand_pending_descriptors(
            pending=[medium, tiny],
            offered=offered,
            expansion_allowance=allowance,
        )
        self.assertEqual([item.name for item in added_first], ["tiny"])
        self.assertEqual(blocked[0].name, "medium")


class ToolSearchLoopTests(unittest.TestCase):
    def _run_with_provider(self, provider, *, recovery, offered, holder=None):
        diagnostics_holder = {} if holder is None else holder
        return run_agent_loop(
            AgentQueryRequest(prompt="forecast", agent="mus"),
            provider,
            provider,
            offered_tools=offered,
            tool_search_recovery=recovery,
            recovery_diagnostics_holder=diagnostics_holder,
        )

    def test_invalid_first_search_consumes_only_attempt(self) -> None:
        weather = _descriptor("get_weather_forecast", "weather")
        recovery = ToolSearchRecoveryConfig(
            enabled=True,
            searchable_catalog=(weather,),
            max_search_calls=1,
        )
        holder: dict[str, object] = {}

        class Provider:
            api_model = "test-model"
            max_tool_turns = 3
            max_tool_calls = 5
            system_instruction = "test"
            runtime = "local"
            context_window = 8192

            def model_dump(self):
                return {}

            def generate_turn(self, messages, tools, profile, system_instruction_override=None):
                if not any(message.role == "tool" for message in messages):
                    return mock.Mock(
                        message=AgentMessage(
                            role="agent",
                            content="",
                            tool_calls=[
                                ToolCall(
                                    id="1",
                                    name=SEARCH_AVAILABLE_TOOLS_NAME,
                                    arguments={"query": ""},
                                ),
                                ToolCall(
                                    id="2",
                                    name=SEARCH_AVAILABLE_TOOLS_NAME,
                                    arguments={"query": "weather"},
                                ),
                            ],
                        ),
                        provider_ms=1.0,
                        usage=None,
                        resolved_model=None,
                        citations=[],
                        provider_tool_events=[],
                        estimated_prompt_tokens=0,
                        history_messages_dropped=0,
                    )
                return mock.Mock(
                    message=AgentMessage(role="agent", content="done"),
                    provider_ms=1.0,
                    usage=None,
                    resolved_model=None,
                    citations=[],
                    provider_tool_events=[],
                    estimated_prompt_tokens=0,
                    history_messages_dropped=0,
                )

        response = self._run_with_provider(Provider(), recovery=recovery, offered=[weather], holder=holder)
        self.assertEqual(response.answer, "done")
        self.assertTrue(holder.get("tool_search_attempted"))
        self.assertEqual(holder.get("tool_search_calls"), 1)
        search_outputs = [
            item for item in response.tool_outputs if item["name"] == SEARCH_AVAILABLE_TOOLS_NAME
        ]
        self.assertEqual(len(search_outputs), 2)
        self.assertEqual(search_outputs[0]["status"], "error")
        self.assertEqual(search_outputs[1]["status"], "error")

    def test_model_max_results_clamped_to_configuration(self) -> None:
        weather = _descriptor("get_weather_forecast", "weather")
        mail = _descriptor("search_gmail", "mail")
        market = _descriptor("get_stock_quote", "market")
        search_tool = _descriptor("brave_brave_web_search", "search")
        recovery = ToolSearchRecoveryConfig(
            enabled=True,
            searchable_catalog=(weather, mail, market, search_tool),
            max_result_families=3,
            max_search_calls=1,
        )
        capture: dict[str, object] = {}

        class Provider:
            api_model = "test-model"
            max_tool_turns = 3
            max_tool_calls = 5
            system_instruction = "test"
            runtime = "cloud"
            provider = "openai"
            context_window = 128000

            def model_dump(self):
                return {}

            def generate_turn(self, messages, tools, profile, system_instruction_override=None):
                if not any(message.role == "tool" for message in messages):
                    return mock.Mock(
                        message=AgentMessage(
                            role="agent",
                            content="",
                            tool_calls=[
                                ToolCall(
                                    id="1",
                                    name=SEARCH_AVAILABLE_TOOLS_NAME,
                                    arguments={"query": "weather mail market search", "max_results": 5},
                                )
                            ],
                        ),
                        provider_ms=1.0,
                        usage=None,
                        resolved_model=None,
                        citations=[],
                        provider_tool_events=[],
                        estimated_prompt_tokens=0,
                        history_messages_dropped=0,
                    )
                tool_output = messages[-1].tool_results[0].output
                capture["match_count"] = tool_output["match_count"]
                return mock.Mock(
                    message=AgentMessage(role="agent", content="done"),
                    provider_ms=1.0,
                    usage=None,
                    resolved_model=None,
                    citations=[],
                    provider_tool_events=[],
                    estimated_prompt_tokens=0,
                    history_messages_dropped=0,
                )

        self._run_with_provider(Provider(), recovery=recovery, offered=[weather])
        self.assertLessEqual(capture.get("match_count", 0), 3)

    def test_sorex_two_turn_profile_does_not_offer_search(self) -> None:
        captured: list[list[str]] = []

        class Provider:
            api_model = "qwen3:1.7b"
            max_tool_turns = 2
            max_tool_calls = 3
            system_instruction = "test"
            runtime = "local"
            context_window = 4096

            def model_dump(self):
                return {}

            def generate_turn(self, messages, tools, profile, system_instruction_override=None):
                captured.append([tool.name for tool in tools])
                return mock.Mock(
                    message=AgentMessage(role="agent", content="done"),
                    provider_ms=1.0,
                    usage=None,
                    resolved_model=None,
                    citations=[],
                    provider_tool_events=[],
                    estimated_prompt_tokens=0,
                    history_messages_dropped=0,
                )

        recovery = ToolSearchRecoveryConfig(
            enabled=True,
            searchable_catalog=(_descriptor("get_weather_forecast", "weather"),),
            max_search_calls=1,
        )
        self.assertFalse(can_offer_search_recovery(2, 0))
        self._run_with_provider(Provider(), recovery=recovery, offered=[])
        self.assertNotIn(SEARCH_AVAILABLE_TOOLS_NAME, captured[0])

    def test_search_on_penultimate_turn_is_not_offered(self) -> None:
        captured: list[list[str]] = []

        class Provider:
            api_model = "test-model"
            max_tool_turns = 3
            max_tool_calls = 5
            system_instruction = "test"
            runtime = "cloud"
            provider = "openai"
            context_window = 128000

            def model_dump(self):
                return {}

            def generate_turn(self, messages, tools, profile, system_instruction_override=None):
                captured.append([tool.name for tool in tools])
                if len(captured) == 1:
                    return mock.Mock(
                        message=AgentMessage(
                            role="agent",
                            content="",
                            tool_calls=[
                                ToolCall(
                                    id="1",
                                    name="get_weather_forecast",
                                    arguments={},
                                )
                            ],
                        ),
                        provider_ms=1.0,
                        usage=None,
                        resolved_model=None,
                        citations=[],
                        provider_tool_events=[],
                        estimated_prompt_tokens=0,
                        history_messages_dropped=0,
                    )
                if len(captured) == 2:
                    return mock.Mock(
                        message=AgentMessage(role="agent", content="done"),
                        provider_ms=1.0,
                        usage=None,
                        resolved_model=None,
                        citations=[],
                        provider_tool_events=[],
                        estimated_prompt_tokens=0,
                        history_messages_dropped=0,
                    )
                return mock.Mock(
                    message=AgentMessage(role="agent", content="final"),
                    provider_ms=1.0,
                    usage=None,
                    resolved_model=None,
                    citations=[],
                    provider_tool_events=[],
                    estimated_prompt_tokens=0,
                    history_messages_dropped=0,
                )

        weather = _descriptor("get_weather_forecast", "weather")

        def dispatcher(name: str, arguments: dict):
            if name == "get_weather_forecast":
                return {"forecast": "sunny"}
            raise AssertionError(name)

        recovery = ToolSearchRecoveryConfig(
            enabled=True,
            searchable_catalog=(_descriptor("search_gmail", "mail"),),
            max_search_calls=1,
        )
        run_agent_loop(
            AgentQueryRequest(prompt="check", agent="neofelis"),
            Provider(),
            Provider(),
            offered_tools=[weather],
            tools_dispatcher=dispatcher,
            tool_search_recovery=recovery,
        )
        self.assertIn(SEARCH_AVAILABLE_TOOLS_NAME, captured[0])
        self.assertNotIn(SEARCH_AVAILABLE_TOOLS_NAME, captured[1])

    def test_cloud_recovery_expands_and_invokes_recovered_tool(self) -> None:
        weather = _descriptor("get_weather_forecast", "weather")
        mail = _descriptor("search_gmail", "mail")
        recovery = ToolSearchRecoveryConfig(
            enabled=True,
            searchable_catalog=(weather, mail),
            max_search_calls=1,
        )
        offered_turns: list[list[str]] = []
        invoked_tools: list[str] = []

        class Provider:
            api_model = "gpt-test"
            max_tool_turns = 4
            max_tool_calls = 5
            system_instruction = "test"
            runtime = "cloud"
            provider = "openai"
            context_window = 128000

            def model_dump(self):
                return {}

            def generate_turn(self, messages, tools, profile, system_instruction_override=None):
                offered_turns.append([tool.name for tool in tools])
                if len(offered_turns) == 1:
                    return mock.Mock(
                        message=AgentMessage(
                            role="agent",
                            content="",
                            tool_calls=[
                                ToolCall(
                                    id="1",
                                    name=SEARCH_AVAILABLE_TOOLS_NAME,
                                    arguments={"query": "gmail inbox"},
                                )
                            ],
                        ),
                        provider_ms=1.0,
                        usage=None,
                        resolved_model=None,
                        citations=[],
                        provider_tool_events=[],
                        estimated_prompt_tokens=0,
                        history_messages_dropped=0,
                    )
                if "search_gmail" in (tool.name for tool in tools):
                    invoked_tools.append("search_gmail")
                    return mock.Mock(
                        message=AgentMessage(
                            role="agent",
                            content="",
                            tool_calls=[
                                ToolCall(
                                    id="2",
                                    name="search_gmail",
                                    arguments={"query": "inbox"},
                                )
                            ],
                        ),
                        provider_ms=1.0,
                        usage=None,
                        resolved_model=None,
                        citations=[],
                        provider_tool_events=[],
                        estimated_prompt_tokens=0,
                        history_messages_dropped=0,
                    )
                return mock.Mock(
                    message=AgentMessage(role="agent", content="done"),
                    provider_ms=1.0,
                    usage=None,
                    resolved_model=None,
                    citations=[],
                    provider_tool_events=[],
                    estimated_prompt_tokens=0,
                    history_messages_dropped=0,
                )

        def dispatcher(name: str, arguments: dict):
            if name == "search_gmail":
                return {"messages": []}
            raise AssertionError(name)

        holder: dict[str, object] = {}
        response = run_agent_loop(
            AgentQueryRequest(prompt="email", agent="neofelis"),
            Provider(),
            Provider(),
            offered_tools=[weather],
            tools_dispatcher=dispatcher,
            tool_search_recovery=recovery,
            recovery_diagnostics_holder=holder,
        )
        self.assertEqual(response.answer, "done")
        self.assertIn("search_gmail", offered_turns[1])
        self.assertIn("search_gmail", invoked_tools)
        self.assertEqual(holder.get("recovered_families"), ["mail"])

    def test_empty_search_result_cannot_search_again(self) -> None:
        weather = _descriptor("get_weather_forecast", "weather")
        recovery = ToolSearchRecoveryConfig(
            enabled=True,
            searchable_catalog=(weather,),
            offered_families=frozenset({"weather"}),
            max_search_calls=1,
        )
        holder: dict[str, object] = {}

        class Provider:
            api_model = "test-model"
            max_tool_turns = 3
            max_tool_calls = 5
            system_instruction = "test"
            runtime = "cloud"
            provider = "openai"
            context_window = 128000

            def model_dump(self):
                return {}

            def generate_turn(self, messages, tools, profile, system_instruction_override=None):
                if not any(message.role == "tool" for message in messages):
                    return mock.Mock(
                        message=AgentMessage(
                            role="agent",
                            content="",
                            tool_calls=[
                                ToolCall(
                                    id="1",
                                    name=SEARCH_AVAILABLE_TOOLS_NAME,
                                    arguments={"query": "weather again"},
                                ),
                                ToolCall(
                                    id="2",
                                    name=SEARCH_AVAILABLE_TOOLS_NAME,
                                    arguments={"query": "weather third"},
                                ),
                            ],
                        ),
                        provider_ms=1.0,
                        usage=None,
                        resolved_model=None,
                        citations=[],
                        provider_tool_events=[],
                        estimated_prompt_tokens=0,
                        history_messages_dropped=0,
                    )
                return mock.Mock(
                    message=AgentMessage(role="agent", content="done"),
                    provider_ms=1.0,
                    usage=None,
                    resolved_model=None,
                    citations=[],
                    provider_tool_events=[],
                    estimated_prompt_tokens=0,
                    history_messages_dropped=0,
                )

        self._run_with_provider(Provider(), recovery=recovery, offered=[weather], holder=holder)
        self.assertEqual(holder.get("tool_search_calls"), 1)
        self.assertEqual(holder.get("recovery_results_already_offered"), ["weather"])

    def test_explicit_scope_path_does_not_offer_search_tool(self) -> None:
        captured_tools: list[str] = []

        class Provider:
            api_model = "test-model"
            max_tool_turns = 2
            max_tool_calls = 1
            system_instruction = "test"
            runtime = "local"
            context_window = 8192

            def model_dump(self):
                return {}

            def generate_turn(self, messages, tools, profile, system_instruction_override=None):
                captured_tools.extend(tool.name for tool in tools)
                return mock.Mock(
                    message=AgentMessage(role="agent", content="done"),
                    provider_ms=1.0,
                    usage=None,
                    resolved_model=None,
                    citations=[],
                    provider_tool_events=[],
                    estimated_prompt_tokens=0,
                    history_messages_dropped=0,
                )

        weather = _descriptor("get_weather_forecast", "weather")
        run_agent_loop(
            AgentQueryRequest(prompt="forecast", agent="mus", tool_scope="weather"),
            Provider(),
            Provider(),
            resolved_local_command=mock.Mock(
                scope="weather",
                descriptors=[weather],
            ),
        )
        self.assertEqual(captured_tools, ["get_weather_forecast"])
        self.assertNotIn(SEARCH_AVAILABLE_TOOLS_NAME, captured_tools)


class ToolSearchEndToEndScriptedTests(unittest.TestCase):
    def _provider(self, *, turns: int, script: list[AgentMessage], capture: dict):
        class Provider:
            api_model = "scripted"
            max_tool_turns = turns
            max_tool_calls = 10
            system_instruction = "test"
            runtime = "cloud"
            provider = "openai"
            context_window = 128000

            def model_dump(self):
                return {}

            def generate_turn(self, messages, tools, profile, system_instruction_override=None):
                capture["tools"] = [tool.name for tool in tools]
                return mock.Mock(
                    message=script.pop(0),
                    provider_ms=1.0,
                    usage=None,
                    resolved_model=None,
                    citations=[],
                    provider_tool_events=[],
                    estimated_prompt_tokens=0,
                    history_messages_dropped=0,
                )

        return Provider()

    def test_declines_to_search_completes_without_recovery(self) -> None:
        weather = _descriptor("get_weather_forecast", "weather")
        recovery = ToolSearchRecoveryConfig(
            enabled=True,
            searchable_catalog=(_descriptor("search_gmail", "mail"),),
            max_search_calls=1,
        )
        holder: dict[str, object] = {}
        capture: dict[str, object] = {}
        response = run_agent_loop(
            AgentQueryRequest(prompt="just answer", agent="neofelis"),
            self._provider(
                turns=3,
                script=[AgentMessage(role="agent", content="answered")],
                capture=capture,
            ),
            self._provider(turns=3, script=[], capture={}),
            offered_tools=[weather],
            tool_search_recovery=recovery,
            recovery_diagnostics_holder=holder,
        )
        self.assertEqual(response.answer, "answered")
        self.assertFalse(holder.get("tool_search_attempted"))

    def test_no_tool_request_should_not_over_search(self) -> None:
        recovery = ToolSearchRecoveryConfig(
            enabled=True,
            searchable_catalog=(_descriptor("get_weather_forecast", "weather"),),
            max_search_calls=1,
        )
        holder: dict[str, object] = {}
        response = run_agent_loop(
            AgentQueryRequest(prompt="define osmosis", agent="neofelis"),
            self._provider(
                turns=3,
                script=[
                    AgentMessage(
                        role="agent",
                        content="",
                        tool_calls=[
                            ToolCall(
                                id="1",
                                name=SEARCH_AVAILABLE_TOOLS_NAME,
                                arguments={"query": "osmosis"},
                            )
                        ],
                    ),
                    AgentMessage(role="agent", content="done"),
                ],
                capture={},
            ),
            self._provider(turns=3, script=[], capture={}),
            offered_tools=[],
            tool_search_recovery=recovery,
            recovery_diagnostics_holder=holder,
        )
        self.assertEqual(response.answer, "done")
        self.assertTrue(holder.get("tool_search_attempted"))


class ToolSearchValidationTests(unittest.TestCase):
    def test_rejects_empty_and_overlong_queries(self) -> None:
        catalog = (_descriptor("search_gmail", "mail"),)
        with self.assertRaises(CapabilityError):
            execute_tool_search(catalog, "   ", max_results=1, max_capabilities_per_family=1)
        with self.assertRaises(CapabilityError):
            execute_tool_search(
                catalog,
                "x" * 501,
                max_results=1,
                max_capabilities_per_family=1,
            )

    def test_expansion_blocked_diagnostics_populated_when_nothing_fits(self) -> None:
        huge = _descriptor(
            "huge",
            "mail",
            schema={
                "type": "object",
                "properties": {f"p{i}": {"type": "string"} for i in range(200)},
            },
        )
        tiny = _descriptor("tiny", "mail")
        offered: list[CapabilityDescriptor] = []
        added, count, blocked = expand_pending_descriptors(
            pending=[huge, tiny],
            offered=offered,
            expansion_allowance=estimate_schema_tokens([tiny]) - 1,
            blocked=[],
        )
        self.assertEqual(added, [])
        self.assertEqual(count, 0)
        self.assertEqual(len(blocked), 2)


if __name__ == "__main__":
    unittest.main()
