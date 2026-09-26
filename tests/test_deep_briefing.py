"""Focused bounds, tool selection, and runtime policy tests for Deep."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from core.agent.capabilities import CapabilityDescriptor, CapabilityError, CapabilityErrorCategory
from core.agent.loop import ExecutionStopped
from core.agent.providers.contract import ProviderTurnResult
from core.agent.types import AgentMessage, AgentQueryResponse, ToolCall, ToolSelectionDiagnostics
from core.briefings.investigation import (
    DeepInvestigationCapabilityError,
    _ToolPlan,
    _build_investigation_prompt,
    _eligible_read_catalog_tools,
    _recheck_read_permission,
    _select_deep_tools,
    investigate_deep,
    validate_deep_preflight,
)
from core.briefings.models import (
    BUILTIN_BRIEFING_PROFILES,
    BriefingCoverage,
    BriefingEvidence,
    BriefingGenerationConfiguration,
    BriefingModelConfiguration,
)
from tests.support.agent_fixtures import GEMINI_FLASH_MODEL, build_cloud_profile


def _configuration(
    *,
    max_model_turns: int = 6,
    max_tool_calls: int = 10,
    context_window: int = 16_384,
    output_token_limit: int = 1_024,
) -> BriefingGenerationConfiguration:
    return BriefingGenerationConfiguration(
        profile=BUILTIN_BRIEFING_PROFILES["deep"],
        model=BriefingModelConfiguration(
            model_id="openrouter/test-model",
            provider="openrouter",
            runtime="cloud",
            reasoning="high",
            context_window=context_window,
            max_elapsed_seconds=600,
            max_retries=2,
            max_model_turns=max_model_turns,
            max_tool_calls=max_tool_calls,
            output_token_limit=output_token_limit,
        ),
        origin="hud",
    )


def _capability(name: str, *, risk: str = "read") -> CapabilityDescriptor:
    return CapabilityDescriptor(
        name=name,
        title=name,
        description="A bounded test capability.",
        input_schema={"type": "object", "properties": {}},
        origin="mcp" if name.startswith("brave_") else "native",
        risk=risk,  # type: ignore[arg-type]
        expose_to_agent=True,
        expose_to_mcp_server=False,
        expose_to_client_display=True,
    )


class _FakeAgentProfile:
    def __init__(self, *, turns: int = 6, calls: int = 10) -> None:
        self.max_tool_turns = turns
        self.max_tool_calls = calls
        self.system_instruction = "Use APEX capabilities safely."

    def model_copy(self, *, update):
        return _FakeAgentProfile(
            turns=update.get("max_tool_turns", self.max_tool_turns),
            calls=update.get("max_tool_calls", self.max_tool_calls),
        )

    def model_dump(self):
        return {"max_tool_turns": self.max_tool_turns, "max_tool_calls": self.max_tool_calls}


class _FakeControl:
    def __init__(self, remaining: float = 300.0) -> None:
        self._remaining = remaining

    def remaining_seconds(self) -> float:
        return self._remaining

    def check_cancelled(self) -> None:
        return

    def before_model_turn(self) -> None:
        return

    def after_model_turn(self, _result) -> None:
        return

    def before_tool(self) -> None:
        return

    def after_tool(self) -> None:
        return

    def before_provider_attempt(self) -> None:
        return

    def before_retry(self, _retry_number: int = 0) -> None:
        return


class DeepBriefingTests(unittest.TestCase):
    def test_preflight_reserves_two_synthesis_turns_and_requires_a_read(self) -> None:
        configuration = _configuration(max_model_turns=3)
        with patch("core.briefings.investigation._build_agent_profile", return_value=_FakeAgentProfile()), patch(
            "core.briefings.investigation._select_deep_tools",
            return_value=_ToolPlan(("get_active_reminders",), (_capability("get_active_reminders"),), ToolSelectionDiagnostics()),
        ):
            with self.assertRaisesRegex(DeepInvestigationCapabilityError, "two investigation turns"):
                validate_deep_preflight(configuration, partition="production")

        configuration = _configuration()
        with patch("core.briefings.investigation._build_agent_profile", return_value=_FakeAgentProfile()), patch(
            "core.briefings.investigation._select_deep_tools",
            return_value=_ToolPlan((), (), ToolSelectionDiagnostics()),
        ):
            with self.assertRaisesRegex(DeepInvestigationCapabilityError, "no eligible read capability"):
                validate_deep_preflight(configuration, partition="production")

        configuration = _configuration()
        bounded_plan = _ToolPlan(
            ("get_active_reminders",), (_capability("get_active_reminders"),),
            ToolSelectionDiagnostics(selected_schema_tokens=80),
        )
        with patch("core.briefings.investigation._build_agent_profile", return_value=_FakeAgentProfile()), patch(
            "core.briefings.investigation._select_deep_tools", return_value=bounded_plan
        ), patch("core.briefings.investigation._context_window", return_value=2_171), patch(
            "core.briefings.investigation.estimate_json_tokens", return_value=300
        ):
            with self.assertRaisesRegex(DeepInvestigationCapabilityError, "context window"):
                validate_deep_preflight(configuration, partition="production")

    def test_curated_tools_follow_relevant_evidence_and_exclude_unavailable_candidates(self) -> None:
        catalog = SimpleNamespace(groups=[SimpleNamespace(tools=[
            SimpleNamespace(name="search_gmail", available=True, allowed_for_agent=True, risk="read", apex_family="mail"),
            SimpleNamespace(name="get_gmail_message", available=False, allowed_for_agent=True, risk="read", apex_family="mail"),
            SimpleNamespace(name="send_email", available=True, allowed_for_agent=True, risk="write", apex_family="mail"),
            SimpleNamespace(name="list_microsoft_todo_lists", available=True, allowed_for_agent=True, risk="read", apex_family="microsoft_todo"),
            SimpleNamespace(name="list_microsoft_todo_tasks", available=True, allowed_for_agent=True, risk="read", apex_family="microsoft_todo"),
            SimpleNamespace(name="get_active_reminders", available=True, allowed_for_agent=True, risk="read", apex_family="schedule"),
            SimpleNamespace(name="brave_brave_web_search", available=True, allowed_for_agent=True, risk="read", apex_family="web_search"),
            SimpleNamespace(name="brave_" + "x" * 64, available=True, allowed_for_agent=True, risk="read", apex_family="web_search"),
        ])])
        descriptors = tuple(_capability(name) for name in (
            "search_gmail", "brave_brave_web_search", "list_microsoft_todo_lists",
            "list_microsoft_todo_tasks", "get_active_reminders"
        ))
        resolved = SimpleNamespace(
            descriptors=descriptors,
            diagnostics=ToolSelectionDiagnostics(),
        )
        evidence = [
            BriefingEvidence(
                source="email", source_id="mail-1", trust="observed", content="A changed unread message.",
                comparison_role="current", change_kind="changed",
            ),
            BriefingEvidence(
                source="reminders", source_id="task-1", trust="observed", content="A due task.",
                comparison_role="current", change_kind="time_sensitive",
            ),
            BriefingEvidence(
                source="external_report", source_id="report-1", trust="untrusted", content="A relevant report.",
                comparison_role="current", change_kind="new",
            ),
        ]

        with patch("core.briefings.investigation.build_tool_catalog", return_value=catalog), patch(
            "core.briefings.investigation.resolve_selected_tools", return_value=resolved
        ) as resolve:
            selected = _select_deep_tools(
                configuration=_configuration(),
                partition="production",
                evidence=evidence,
                coverage=[BriefingCoverage(source="email", scope="mail", status="complete")],
            )
            eligible = _eligible_read_catalog_tools("openrouter/test-model", "production")

        self.assertEqual(selected.names, (
            "search_gmail", "brave_brave_web_search", "list_microsoft_todo_lists",
            "list_microsoft_todo_tasks", "get_active_reminders",
        ))
        self.assertNotIn("get_gmail_message", selected.names)
        self.assertNotIn("send_email", selected.names)
        self.assertEqual(resolve.call_args.args[1], list(selected.names))
        self.assertNotIn("tool_profile_id", resolve.call_args.kwargs)
        self.assertIn("search_gmail", eligible)
        self.assertNotIn("brave_" + "x" * 64, eligible)
        self.assertNotIn("get_gmail_message", eligible)
        self.assertNotIn("send_email", eligible)

    def test_changed_snapshot_prompt_includes_paired_historical_evidence(self) -> None:
        pair_id = uuid4()
        previous_at = datetime(2026, 9, 24, 8, 30, tzinfo=timezone.utc)
        current_at = datetime(2026, 9, 25, 8, 30, tzinfo=timezone.utc)
        evidence = [
            BriefingEvidence(
                source="reminders", source_id="task-1", trust="observed",
                content="Current task due date: tomorrow.", observed_at=current_at,
                comparison_role="current", change_kind="changed", comparison_pair_id=pair_id,
            ),
            BriefingEvidence(
                source="reminders", source_id="task-1", trust="observed",
                content="Prior task due date: next week.", observed_at=previous_at,
                comparison_role="historical", change_kind="changed", comparison_pair_id=pair_id,
            ),
        ]
        plan = _ToolPlan(
            names=("get_active_reminders",),
            descriptors=(_capability("get_active_reminders"),),
            diagnostics=ToolSelectionDiagnostics(offered_tool_names=["get_active_reminders"]),
        )
        captured: dict[str, str] = {}

        def fake_loop(request, *_args, **_kwargs):
            captured["prompt"] = request.prompt
            return AgentQueryResponse(answer="No further read is needed.", agent_used={})

        with patch("core.briefings.investigation._build_agent_profile", return_value=_FakeAgentProfile()), patch(
            "core.briefings.investigation._select_deep_tools", return_value=plan
        ), patch("core.briefings.investigation._context_window", return_value=16_384), patch(
            "core.briefings.investigation.get_visible_model_profile", return_value=SimpleNamespace(credential_env=None)
        ), patch("core.briefings.investigation.create_provider", return_value=object()), patch(
            "core.briefings.investigation.is_local_profile", return_value=False
        ), patch("core.briefings.investigation.run_agent_loop", side_effect=fake_loop):
            result = investigate_deep(
                evidence=evidence,
                coverage=[],
                configuration=_configuration(),
                control=_FakeControl(),  # type: ignore[arg-type]
                partition="production",
            )

        self.assertEqual(result.metadata.status, "no_read_needed")
        self.assertIn("Prior task due date: next week.", captured["prompt"])
        self.assertIn('"comparison_role":"historical"', captured["prompt"])
        self.assertIn('"comparison_role":"current"', captured["prompt"])
        self.assertIn(previous_at.isoformat(), captured["prompt"])
        self.assertIn(current_at.isoformat(), captured["prompt"])

    def test_prompt_byte_fitting_keeps_changed_evidence_pairs_together(self) -> None:
        pair_id = uuid4()
        captured_at = datetime(2026, 9, 25, 8, 30, tzinfo=timezone.utc)
        evidence = [
            BriefingEvidence(
                source="reminders", source_id="task-1", trust="observed",
                content="Current task state: " + "C" * 900,
                observed_at=captured_at, comparison_role="current",
                change_kind="changed", comparison_pair_id=pair_id,
            ),
            BriefingEvidence(
                source="reminders", source_id="task-1", trust="observed",
                content="Historical task state: " + "H" * 900,
                observed_at=captured_at, comparison_role="historical",
                change_kind="changed", comparison_pair_id=pair_id,
            ),
        ]

        prompt, limited = _build_investigation_prompt(evidence, [], max_bytes=1_700)
        evidence_json = prompt.split("\nCurrent and historical evidence:\n", 1)[1]
        rows = json.loads(evidence_json)

        self.assertLessEqual(len(prompt.encode("utf-8")), 1_700)
        self.assertTrue(limited)
        self.assertEqual(
            {row["comparison_role"] for row in rows},
            {"current", "historical"},
        )
        self.assertEqual({row["comparison_pair_id"] for row in rows}, {str(pair_id)})
        self.assertTrue(all(row["content_shortened"] for row in rows))

    def test_mcp_read_risk_is_rechecked_at_invocation_time(self) -> None:
        catalog = {"brave_brave_web_search": SimpleNamespace(
            risk="read", available=True, allowed_for_agent=True
        )}
        config = SimpleNamespace(servers={"brave": SimpleNamespace(
            tool_allowlist=["brave_web_search"],
            tool_risks={"brave_web_search": "write"},
        )})
        descriptor = _capability("brave_brave_web_search")
        with patch("core.briefings.investigation.get_capability_descriptor", return_value=descriptor), patch(
            "core.briefings.investigation._eligible_read_catalog_tools", return_value=catalog
        ), patch("core.briefings.investigation.server_id_for_tool", return_value="brave"), patch(
            "core.briefings.investigation.load_mcp_config", return_value=config
        ):
            with self.assertRaises(CapabilityError) as raised:
                _recheck_read_permission(
                    "brave_brave_web_search",
                    model_id="openrouter/test-model",
                    partition="production",
                )
        self.assertEqual(raised.exception.category, CapabilityErrorCategory.UNAVAILABLE)

    def test_investigation_bounds_tools_and_captures_only_untrusted_results(self) -> None:
        descriptor = _capability("get_active_reminders")
        plan = _ToolPlan(
            names=("get_active_reminders",),
            descriptors=(descriptor,),
            diagnostics=ToolSelectionDiagnostics(
                requested_tool_names=["get_active_reminders"],
                offered_tool_names=["get_active_reminders"],
                selected_schema_tokens=64,
            ),
        )
        captured: dict[str, object] = {}

        def fake_loop(_request, _provider, profile, **kwargs):
            captured["profile"] = profile
            kwargs["activity_observer"]("model.started", {"turn": 2})
            output = kwargs["tools_dispatcher"]("get_active_reminders", {})
            return AgentQueryResponse(
                answer="This answer must not be saved.",
                agent_used={},
                tool_trace=[{"name": "get_active_reminders", "status": "ok"}],
                tool_outputs=[{
                    "name": "get_active_reminders",
                    "status": "ok",
                    "output": output,
                }],
            )

        config = _configuration(max_tool_calls=9)
        evidence = [BriefingEvidence(
            source="reminders", source_id="task-1", trust="observed", content="A due reminder.",
            comparison_role="current", change_kind="time_sensitive",
        )]
        with patch("core.briefings.investigation._build_agent_profile", return_value=_FakeAgentProfile()), patch(
            "core.briefings.investigation._select_deep_tools", return_value=plan
        ), patch("core.briefings.investigation._context_window", return_value=16_384), patch(
            "core.briefings.investigation.get_visible_model_profile", return_value=SimpleNamespace(credential_env=None)
        ), patch("core.briefings.investigation.create_provider", return_value=object()), patch(
            "core.briefings.investigation.is_local_profile", return_value=False
        ), patch("core.briefings.investigation._recheck_read_permission"), patch(
            "core.briefings.investigation.invoke_read_only_capability", return_value={"records": ["R" * 4_000]}
        ) as invoke_read, patch("core.briefings.investigation.run_agent_loop", side_effect=fake_loop):
            result = investigate_deep(
                evidence=evidence,
                coverage=[],
                configuration=config,
                control=_FakeControl(remaining=300),  # type: ignore[arg-type]
                partition="production",
            )

        profile = captured["profile"]
        self.assertEqual(profile.max_tool_turns, 3)
        self.assertEqual(profile.max_tool_calls, 4)
        self.assertEqual(result.metadata.time_budget_seconds, 150)
        self.assertAlmostEqual(invoke_read.call_args.kwargs["timeout_seconds"], 150, places=2)
        self.assertEqual(result.metadata.turns_used, 2)
        self.assertEqual(result.metadata.tool_calls_used, 1)
        self.assertEqual(result.metadata.result_count, 1)
        self.assertEqual(result.metadata.status, "limited")
        self.assertEqual(result.evidence[0].source, "get_active_reminders")
        self.assertEqual(result.evidence[0].trust, "untrusted")
        self.assertIn("captured ", result.evidence[0].content or "")
        self.assertIn("read results were truncated", " ".join(result.metadata.limitations))
        self.assertNotIn("This answer must not be saved", result.evidence[0].content or "")

    def test_display_policy_drift_after_read_keeps_the_captured_read_result(self) -> None:
        descriptor = _capability("get_active_reminders")
        plan = _ToolPlan(
            names=("get_active_reminders",),
            descriptors=(descriptor,),
            diagnostics=ToolSelectionDiagnostics(offered_tool_names=["get_active_reminders"]),
        )

        class Provider:
            def __init__(self) -> None:
                self.calls = 0
                self.output_token_limits: list[int | None] = []

            def generate_turn(self, *_args, **_kwargs):
                self.calls += 1
                self.output_token_limits.append(_kwargs.get("output_token_limit"))
                if self.calls == 1:
                    message = AgentMessage(role="agent", tool_calls=[ToolCall(
                        id="read-1", name="get_active_reminders", arguments={},
                    )])
                else:
                    message = AgentMessage(role="agent", content="The reminder result is useful.")
                return ProviderTurnResult(message=message)

        profile = build_cloud_profile(model=GEMINI_FLASH_MODEL)
        provider = Provider()
        with patch("core.briefings.investigation._build_agent_profile", return_value=profile), patch(
            "core.briefings.investigation._select_deep_tools", return_value=plan
        ), patch("core.briefings.investigation._context_window", return_value=16_384), patch(
            "core.briefings.investigation.get_visible_model_profile", return_value=SimpleNamespace(credential_env=None)
        ), patch("core.briefings.investigation.create_provider", return_value=provider), patch(
            "core.briefings.investigation.is_local_profile", return_value=False
        ), patch("core.briefings.investigation._recheck_read_permission"), patch(
            "core.briefings.investigation.invoke_read_only_capability", return_value={"task": "actual captured read data"}
        ), patch("core.agent.loop.is_client_display_enabled", return_value=False):
            result = investigate_deep(
                evidence=[], coverage=[], configuration=_configuration(output_token_limit=2_048),
                control=_FakeControl(), partition="production",  # type: ignore[arg-type]
            )

        self.assertEqual(result.metadata.status, "completed")
        self.assertIn("actual captured read data", result.evidence[0].content or "")
        self.assertNotIn("Tool output is not whitelisted for client display.", result.evidence[0].content or "")
        self.assertEqual(provider.output_token_limits, [1_024, 1_024])

    def test_model_can_choose_no_read_and_global_stops_are_not_downgraded(self) -> None:
        plan = _ToolPlan(
            names=("get_active_reminders",),
            descriptors=(_capability("get_active_reminders"),),
            diagnostics=ToolSelectionDiagnostics(offered_tool_names=["get_active_reminders"]),
        )
        base_patches = (
            patch("core.briefings.investigation._build_agent_profile", return_value=_FakeAgentProfile()),
            patch("core.briefings.investigation._select_deep_tools", return_value=plan),
            patch("core.briefings.investigation._context_window", return_value=16_384),
            patch("core.briefings.investigation.get_visible_model_profile", return_value=SimpleNamespace(credential_env=None)),
            patch("core.briefings.investigation.create_provider", return_value=object()),
            patch("core.briefings.investigation.is_local_profile", return_value=False),
        )
        no_read = AgentQueryResponse(answer="No extra read needed.", agent_used={})
        with base_patches[0], base_patches[1], base_patches[2], base_patches[3], base_patches[4], base_patches[5], patch(
            "core.briefings.investigation.run_agent_loop", return_value=no_read
        ):
            result = investigate_deep(
                evidence=[], coverage=[], configuration=_configuration(),
                control=_FakeControl(), partition="production",  # type: ignore[arg-type]
            )
        self.assertEqual(result.metadata.status, "no_read_needed")
        self.assertEqual(result.evidence, [])

        with base_patches[0], base_patches[1], base_patches[2], base_patches[3], base_patches[4], base_patches[5], patch(
            "core.briefings.investigation.run_agent_loop", side_effect=ExecutionStopped("cancelled")
        ):
            with self.assertRaises(ExecutionStopped):
                investigate_deep(
                    evidence=[], coverage=[], configuration=_configuration(),
                    control=_FakeControl(), partition="production",  # type: ignore[arg-type]
                )


if __name__ == "__main__":
    unittest.main()
