"""Regression coverage for the provider-neutral capability registry."""

from __future__ import annotations

import unittest
import time
from unittest import mock

from core.agent.capabilities import (
    CapabilityDescriptor,
    CapabilityError,
    CapabilityErrorCategory,
    clear_capability_registry_for_tests,
    get_capability_descriptor,
    invoke_capability,
    is_client_display_enabled,
    list_agent_capabilities,
    namespaced_capability_name,
    register_capability,
)
from core.agent.loop import run_agent_loop
from core.agent.providers.contract import ProviderTurnResult
from core.agent.providers.gemini import _descriptors_to_gemini_tools
from tests.support.agent_fixtures import GEMINI_FLASH_MODEL, build_panthera_profile
from core.agent.providers.ollama import _descriptor_to_openai_schema
from core.agent.tools import register_native_capabilities
from core.agent.types import AgentMessage, AgentQueryRequest, ToolCall


class CapabilityRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_capability_registry_for_tests()
        register_native_capabilities()

    def tearDown(self) -> None:
        clear_capability_registry_for_tests()
        register_native_capabilities()

    def test_native_capabilities_are_registered_with_expected_risks(self) -> None:
        capabilities = list_agent_capabilities()
        names = {capability.name for capability in capabilities}
        self.assertEqual(
            names,
            {
                "get_weather_forecast",
                "get_f1_driver_standings",
                "get_f1_season_calendar",
                "get_upcoming_calendar_events",
                "get_active_reminders",
                "get_briefing_history",
                "search_gmail",
                "list_microsoft_todo_lists",
                "list_microsoft_todo_tasks",
                "create_microsoft_todo_task",
                "update_microsoft_todo_task",
                "complete_microsoft_todo_task",
                "reopen_microsoft_todo_task",
                "delete_microsoft_todo_task",
                "get_gmail_message",
            },
        )
        for capability in capabilities:
            self.assertEqual(capability.origin, "native")
            expected_risk = (
                "destructive" if capability.name == "delete_microsoft_todo_task"
                else "write" if capability.name in {
                    "create_microsoft_todo_task", "update_microsoft_todo_task",
                    "complete_microsoft_todo_task", "reopen_microsoft_todo_task",
                } else "read"
            )
            self.assertEqual(capability.risk, expected_risk)
            self.assertTrue(capability.expose_to_agent)
            self.assertTrue(capability.expose_to_client_display)
            self.assertFalse(capability.expose_to_mcp_server)

    def test_calendar_capability_defaults_to_fourteen_days(self) -> None:
        calendar = next(
            capability
            for capability in list_agent_capabilities()
            if capability.name == "get_upcoming_calendar_events"
        )
        days_schema = calendar.input_schema["properties"]["days"]

        self.assertEqual(days_schema["minimum"], 1)
        self.assertEqual(days_schema["maximum"], 14)
        self.assertEqual(days_schema["default"], 14)

    def test_gmail_capabilities_are_bounded_and_read_only(self) -> None:
        capabilities = {
            capability.name: capability
            for capability in list_agent_capabilities()
        }
        search = capabilities["search_gmail"]
        message = capabilities["get_gmail_message"]

        self.assertEqual(search.risk, "read")
        self.assertEqual(message.risk, "read")
        self.assertFalse(search.expose_to_mcp_server)
        self.assertFalse(message.expose_to_mcp_server)
        self.assertEqual(
            search.input_schema["properties"]["max_results"]["maximum"],
            20,
        )
        self.assertEqual(
            search.input_schema["properties"]["max_results"]["default"],
            10,
        )

    def test_duplicate_registration_is_rejected(self) -> None:
        descriptor = CapabilityDescriptor(
            name="get_weather_forecast",
            title="Duplicate",
            description="Duplicate registration should fail.",
            input_schema={"type": "object", "properties": {}},
            origin="native",
            risk="read",
            expose_to_agent=True,
            expose_to_mcp_server=False,
            expose_to_client_display=True,
        )
        with self.assertRaisesRegex(ValueError, "already registered"):
            register_capability(descriptor, lambda: None)

    def test_namespace_helper_builds_collision_safe_names(self) -> None:
        self.assertEqual(
            namespaced_capability_name("github", "list_issues"),
            "github_list_issues",
        )
        self.assertEqual(
            namespaced_capability_name("brave", "web_search"),
            "brave_web_search",
        )
        self.assertEqual(
            namespaced_capability_name("alphavantage", "quote"),
            "alphavantage_quote",
        )
        with self.assertRaises(ValueError):
            namespaced_capability_name("Git Hub", "list_issues")
        with self.assertRaises(ValueError):
            namespaced_capability_name("github", "List-Issues")

    def test_gemini_and_ollama_schemas_are_equivalent(self) -> None:
        capabilities = list_agent_capabilities()
        weather = next(
            capability
            for capability in capabilities
            if capability.name == "get_weather_forecast"
        )

        gemini_tools = _descriptors_to_gemini_tools([weather])
        gemini_declaration = gemini_tools[0].function_declarations[0]
        ollama_schema = _descriptor_to_openai_schema(weather)

        self.assertEqual(gemini_declaration.name, ollama_schema["function"]["name"])
        self.assertEqual(
            gemini_declaration.description,
            ollama_schema["function"]["description"],
        )
        self.assertEqual(
            gemini_declaration.parameters_json_schema,
            ollama_schema["function"]["parameters"],
        )
        self.assertEqual(
            ollama_schema["function"]["parameters"]["properties"]["days"]["maximum"],
            14,
        )

    def test_invoke_clamps_integer_bounds_and_applies_defaults(self) -> None:
        with mock.patch(
            "core.agent.tools.fetch_weather_forecast",
            return_value={"location": "test", "forecast": []},
        ) as fetch_mock:
            result = invoke_capability("get_weather_forecast", {"days": 99})

        self.assertEqual(result, {"location": "test", "forecast": []})
        fetch_mock.assert_called_once_with(location=None, days=14)

        with mock.patch(
            "core.agent.tools.fetch_weather_forecast",
            return_value={"location": "test", "forecast": []},
        ) as fetch_mock:
            invoke_capability("get_weather_forecast", {})

        fetch_mock.assert_called_once_with(location=None, days=5)

    def test_invoke_invalid_input_and_unavailable_categories(self) -> None:
        with self.assertRaises(CapabilityError) as missing:
            invoke_capability("get_weather_forecast", {"unexpected": True})
        self.assertEqual(
            missing.exception.category,
            CapabilityErrorCategory.INVALID_INPUT,
        )

        with self.assertRaises(CapabilityError) as unavailable:
            invoke_capability("missing_capability", {})
        self.assertEqual(
            unavailable.exception.category,
            CapabilityErrorCategory.UNAVAILABLE,
        )

    def test_nested_json_schema_constraints_are_enforced(self) -> None:
        clear_capability_registry_for_tests()
        register_capability(
            CapabilityDescriptor(
                name="structured",
                title="Structured",
                description="Validates nested arguments.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["safe"]},
                        "items": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "minItems": 1,
                        },
                    },
                    "required": ["mode", "items"],
                    "additionalProperties": False,
                },
                origin="native",
                risk="read",
                expose_to_agent=True,
                expose_to_mcp_server=False,
                expose_to_client_display=False,
            ),
            lambda **kwargs: kwargs,
        )

        with self.assertRaises(CapabilityError) as raised:
            invoke_capability("structured", {"mode": "unsafe", "items": "nope"})
        self.assertEqual(
            raised.exception.category,
            CapabilityErrorCategory.INVALID_INPUT,
        )
        self.assertEqual(
            invoke_capability("structured", {"mode": "safe", "items": [1, 2]}),
            {"mode": "safe", "items": [1, 2]},
        )

    def test_invalid_schema_is_rejected_at_registration(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid input schema"):
            register_capability(
                CapabilityDescriptor(
                    name="invalid_schema",
                    title="Invalid",
                    description="Invalid schema.",
                    input_schema={"type": "string"},
                    origin="native",
                    risk="read",
                    expose_to_agent=True,
                    expose_to_mcp_server=False,
                    expose_to_client_display=False,
                ),
                lambda: None,
            )

    def test_sync_timeout_returns_without_waiting_for_handler(self) -> None:
        clear_capability_registry_for_tests()
        register_capability(
            CapabilityDescriptor(
                name="slow",
                title="Slow",
                description="Times out.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                origin="native",
                risk="read",
                expose_to_agent=True,
                expose_to_mcp_server=False,
                expose_to_client_display=False,
                timeout_seconds=0.05,
            ),
            lambda: time.sleep(0.25),
        )

        started = time.perf_counter()
        with self.assertRaises(CapabilityError) as raised:
            invoke_capability("slow", {})
        elapsed = time.perf_counter() - started

        self.assertEqual(raised.exception.category, CapabilityErrorCategory.TIMEOUT)
        self.assertLess(elapsed, 0.15)

    def test_invoke_handler_exception_is_upstream_failure(self) -> None:
        clear_capability_registry_for_tests()
        register_capability(
            CapabilityDescriptor(
                name="boom",
                title="Boom",
                description="Raises.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                origin="native",
                risk="read",
                expose_to_agent=True,
                expose_to_mcp_server=False,
                expose_to_client_display=False,
            ),
            lambda: (_ for _ in ()).throw(RuntimeError("private-detail")),
        )
        with self.assertRaises(CapabilityError) as raised:
            invoke_capability("boom", {})

        self.assertEqual(
            raised.exception.category,
            CapabilityErrorCategory.UPSTREAM_FAILURE,
        )
        self.assertEqual(raised.exception.message, "Tool execution failed.")
        self.assertNotIn("private-detail", raised.exception.message)

    def test_client_display_flag_filters_tool_outputs(self) -> None:
        clear_capability_registry_for_tests()
        register_capability(
            CapabilityDescriptor(
                name="hidden_tool",
                title="Hidden",
                description="Not shown to the client.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                origin="native",
                risk="read",
                expose_to_agent=True,
                expose_to_mcp_server=False,
                expose_to_client_display=False,
            ),
            lambda: {"secret": "value"},
        )
        self.assertFalse(is_client_display_enabled("hidden_tool"))

        class Provider:
            def __init__(self) -> None:
                self.calls = 0

            def generate_turn(
                self,
                messages: list[AgentMessage],
                _tools: list[CapabilityDescriptor],
                _profile: object,
                system_instruction_override: str | None = None,
            ) -> ProviderTurnResult:
                del system_instruction_override
                self.calls += 1
                if self.calls == 1:
                    return ProviderTurnResult(
                        message=AgentMessage(
                            role="agent",
                            tool_calls=[
                                ToolCall(
                                    id="call-1",
                                    name="hidden_tool",
                                    arguments={},
                                )
                            ],
                        )
                    )
                return ProviderTurnResult(
                    message=AgentMessage(role="agent", content="Done.")
                )

        response = run_agent_loop(
            AgentQueryRequest(prompt="Hide this", agent="panthera"),
            Provider(),
            build_panthera_profile(model=GEMINI_FLASH_MODEL),
            selected_tools=[get_capability_descriptor("hidden_tool")],  # type: ignore[list-item]
        )

        self.assertEqual(
            response.tool_outputs[0]["output"],
            {"error": "Tool output is not whitelisted for client display."},
        )

    def test_ollama_schema_reflects_current_descriptor_without_name_cache(self) -> None:
        first = CapabilityDescriptor(
            name="same_name",
            title="First",
            description="First schema.",
            input_schema={"type": "object", "properties": {"value": {"type": "string"}}},
            origin="mcp",
            risk="read",
            expose_to_agent=True,
            expose_to_mcp_server=False,
            expose_to_client_display=False,
        )
        second = first.model_copy(
            update={
                "description": "Second schema.",
                "input_schema": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                },
            }
        )

        first_schema = _descriptor_to_openai_schema(first)
        second_schema = _descriptor_to_openai_schema(second)

        self.assertEqual(
            first_schema["function"]["parameters"]["properties"]["value"]["type"],
            "string",
        )
        self.assertEqual(
            second_schema["function"]["parameters"]["properties"]["value"]["type"],
            "integer",
        )

    def test_failed_capability_call_does_not_terminate_loop(self) -> None:
        class Provider:
            def __init__(self) -> None:
                self.calls = 0
                self.tool_result: object | None = None

            def generate_turn(
                self,
                messages: list[AgentMessage],
                _tools: list[CapabilityDescriptor],
                _profile: object,
                system_instruction_override: str | None = None,
            ) -> ProviderTurnResult:
                del system_instruction_override
                self.calls += 1
                if self.calls == 1:
                    return ProviderTurnResult(
                        message=AgentMessage(
                            role="agent",
                            tool_calls=[
                                ToolCall(
                                    id="call-1",
                                    name="missing_capability",
                                    arguments={},
                                )
                            ],
                        )
                    )
                self.tool_result = messages[-1].tool_results[0].output
                return ProviderTurnResult(
                    message=AgentMessage(role="agent", content="Recovered.")
                )

        response = run_agent_loop(
            AgentQueryRequest(prompt="Call missing", agent="panthera"),
            Provider(),
            build_panthera_profile(model=GEMINI_FLASH_MODEL),
        )

        self.assertEqual(response.answer, "Recovered.")
        self.assertEqual(response.tool_trace[0]["status"], "error")
        self.assertEqual(
            response.tool_outputs[0]["output"]["error_category"],
            CapabilityErrorCategory.UNAVAILABLE.value,
        )


if __name__ == "__main__":
    unittest.main()
