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
from core.agent.loop import run_agent_loop
from core.agent.routing.tool_search import (
    SEARCH_AVAILABLE_TOOLS_NAME,
    ToolSearchRecoveryConfig,
    activate_search_catalog,
    build_searchable_catalog,
    deactivate_search_catalog,
    execute_tool_search,
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
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        name=name,
        title=name,
        description=f"{name} for {family}",
        input_schema={"type": "object", "properties": {}},
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

    def test_local_runtime_excludes_cloud_only_github_family(self) -> None:
        catalog = build_searchable_catalog(
            [
                _descriptor("github_list_issues", "github"),
                _descriptor("get_weather_forecast", "weather"),
            ],
            runtime="local",
            agent_key="neofelis",
        )
        names = {descriptor.name for descriptor in catalog}
        self.assertIn("get_weather_forecast", names)
        self.assertNotIn("github_list_issues", names)

    def test_search_does_not_reveal_unauthorized_capabilities(self) -> None:
        allowed = build_searchable_catalog(
            [_descriptor("get_weather_forecast", "weather")],
            runtime="cloud",
            agent_key="acinonyx",
        )
        result = execute_tool_search(
            allowed,
            "read my gmail inbox",
            max_results=3,
            max_capabilities_per_family=3,
        )
        families = {match["family"] for match in result["matches"]}
        capability_names = {
            capability["name"]
            for match in result["matches"]
            for capability in match["capabilities"]
        }
        self.assertNotIn("mail", families)
        self.assertNotIn("search_gmail", capability_names)

    def test_search_available_tools_requires_active_catalog(self) -> None:
        with self.assertRaises(CapabilityError) as ctx:
            search_available_tools("weather forecast")
        self.assertEqual(ctx.exception.category, CapabilityErrorCategory.UNAVAILABLE)

    def test_search_available_tools_uses_request_catalog_only(self) -> None:
        allowed = build_searchable_catalog(
            [_descriptor("get_weather_forecast", "weather")],
            runtime="cloud",
            agent_key="neofelis",
        )
        token = activate_search_catalog(allowed)
        try:
            result = search_available_tools("weather forecast")
        finally:
            deactivate_search_catalog(token)
        self.assertGreaterEqual(result["match_count"], 1)
        self.assertEqual(result["matches"][0]["family"], "weather")

    def test_search_descriptor_is_not_agent_discoverable(self) -> None:
        descriptor = get_search_available_tools_descriptor()
        exposed = {item.name for item in list_agent_capabilities()}
        self.assertFalse(descriptor.expose_to_agent)
        self.assertNotIn(SEARCH_AVAILABLE_TOOLS_NAME, exposed)

    def test_invoke_registered_search_capability(self) -> None:
        allowed = build_searchable_catalog(
            [_descriptor("get_weather_forecast", "weather")],
            runtime="cloud",
            agent_key="neofelis",
        )
        result = execute_tool_search(
            allowed,
            "weather forecast",
            max_results=3,
            max_capabilities_per_family=3,
        )
        self.assertIn("matches", result)


class ToolSearchLoopTests(unittest.TestCase):
    def test_loop_allows_only_one_search_recovery_call(self) -> None:
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
                                    arguments={"query": "weather"},
                                ),
                                ToolCall(
                                    id="2",
                                    name=SEARCH_AVAILABLE_TOOLS_NAME,
                                    arguments={"query": "weather again"},
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

        response = run_agent_loop(
            AgentQueryRequest(prompt="forecast", agent="mus"),
            Provider(),
            Provider(),
            offered_tools=[weather],
            tool_search_recovery=recovery,
            recovery_diagnostics_holder=holder,
        )
        self.assertEqual(response.answer, "done")
        self.assertEqual(holder.get("tool_search_calls"), 1)
        search_outputs = [
            item
            for item in response.tool_outputs
            if item["name"] == SEARCH_AVAILABLE_TOOLS_NAME
        ]
        self.assertEqual(len(search_outputs), 2)
        self.assertEqual(search_outputs[0]["status"], "ok")
        self.assertEqual(search_outputs[1]["status"], "error")

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

    def test_cloud_recovery_expands_real_schemas_on_next_turn(self) -> None:
        weather = _descriptor("get_weather_forecast", "weather")
        mail = _descriptor("search_gmail", "mail")
        recovery = ToolSearchRecoveryConfig(
            enabled=True,
            searchable_catalog=(weather, mail),
            max_search_calls=1,
        )
        offered_turns: list[list[str]] = []

        class Provider:
            api_model = "gpt-test"
            max_tool_turns = 3
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

        response = run_agent_loop(
            AgentQueryRequest(prompt="email", agent="neofelis"),
            Provider(),
            Provider(),
            offered_tools=[weather],
            tool_search_recovery=recovery,
        )
        self.assertEqual(response.answer, "done")
        self.assertIn(SEARCH_AVAILABLE_TOOLS_NAME, offered_turns[0])
        self.assertIn("search_gmail", offered_turns[1])


if __name__ == "__main__":
    unittest.main()
