from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from core.agent.model_catalog import DEFAULT_PANTHERA_MODEL, get_model_profile
from core.agent.catalog import resolve_effort
from core.agent.local_runtime.contract import LocalModelRef
from core.agent.providers.contract import ProviderTurnResult
from core.agent.types import AgentMessage
from core.synthesis.models import CalendarFact, F1Fact, SynthesisInput, SynthesisResult
from core.synthesis.router import SynthesisRouter, WarmupHandle
from tests.support.agent_fixtures import (
    GEMINI_FLASH_LITE_MODEL,
    GEMINI_FLASH_MODEL,
    GEMMA_E2B_ALIAS,
    GEMMA_E2B_MODEL,
    QWEN3_17B_MODEL,
    QWEN3_4B_MODEL,
    build_felis_profile,
    build_panthera_profile,
)


def sample_input(**overrides: object) -> SynthesisInput:
    values: dict[str, object] = {
        "weather_summary": "Current temperature is 72 degrees with clear skies.",
        "calendar_event_count": 1,
        "next_calendar_event": CalendarFact(title="Review", start="Friday at 2 PM"),
        "pending_reminder_count": 1,
        "first_pending_reminder": "Charge laptop",
        "f1_this_week": F1Fact(race_name="British Grand Prix", start="Sunday at 10 AM"),
        "failed_connectors": [],
        "generated_at": "2026-07-10T12:00:00+00:00",
    }
    values.update(overrides)
    return SynthesisInput.model_validate(values)


class RoutingTests(unittest.TestCase):
    def test_explicit_raw_calls_no_provider(self) -> None:
        router = SynthesisRouter()
        with patch.object(router, "_panthera") as panthera, patch.object(router, "_local") as local:
            result = router.synthesize(sample_input(), "raw")
        self.assertEqual(result.provider, "raw")
        panthera.assert_not_called()
        local.assert_not_called()

    def test_panthera_success(self) -> None:
        router = SynthesisRouter()
        expected = SynthesisResult(briefing="Ready.", provider="openai", agent="panthera")
        with patch.object(router, "_panthera", return_value=expected), patch(
            "core.synthesis.router.resident_agent_key", return_value=None
        ):
            result = router.synthesize(sample_input(), "cloud")
        self.assertEqual(result, expected)

    def test_panthera_uses_openai_at_fixed_none_effort_without_tools(self) -> None:
        router = SynthesisRouter()
        turn = ProviderTurnResult(
            message=AgentMessage(
                role="agent",
                content="===SPEECH===\nReady.\n===INSIGHTS===\n- Clear",
            ),
            resolved_model="gpt-5.6-luna",
            provider_ms=123.4,
        )
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), patch(
            "core.synthesis.router.OpenAIProvider.generate_turn", return_value=turn
        ) as generate:
            result = router._panthera(sample_input())
        messages, tools, profile = generate.call_args.args
        self.assertEqual(messages[0].role, "user")
        self.assertEqual(tools, [])
        self.assertEqual(profile.reasoning_effort, "none")
        self.assertTrue(
            generate.call_args.kwargs["system_instruction_override"].startswith(
                "You are Apex Panthera"
            )
        )
        self.assertEqual(result.provider, "openai")
        self.assertEqual(result.resolved_model, "gpt-5.6-luna")
        self.assertEqual(result.provider_ms, 123.4)

    def test_panthera_briefing_ignores_non_openai_selected_model(self) -> None:
        router = SynthesisRouter()
        turn = ProviderTurnResult(
            message=AgentMessage(
                role="agent",
                content="===SPEECH===\nReady.\n===INSIGHTS===\n- Clear",
            ),
            resolved_model=DEFAULT_PANTHERA_MODEL,
        )
        for selected_model in (
            "gemini-3.6-flash",
            "grok-4.3",
            "deepseek/deepseek-v4-flash-0731",
        ):
            with self.subTest(selected_model=selected_model), patch.dict(
                "os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False
            ), patch(
                "core.agent.catalog.resolve_selected_model_profile",
                return_value=get_model_profile(selected_model),
            ), patch(
                "core.synthesis.router.OpenAIProvider.generate_turn",
                return_value=turn,
            ) as generate:
                result = router._panthera(sample_input())

            _messages, _tools, profile = generate.call_args.args
            self.assertEqual(profile.api_model, DEFAULT_PANTHERA_MODEL)
            self.assertEqual(profile.provider, "openai")
            self.assertEqual(result.provider, "openai")
            self.assertEqual(result.resolved_model, DEFAULT_PANTHERA_MODEL)

    def test_panthera_falls_back_to_felis(self) -> None:
        router = SynthesisRouter()
        expected = SynthesisResult(briefing="Local.", provider="llama_cpp", agent="felis")
        with patch.object(router, "_panthera", side_effect=RuntimeError("openai_error")), patch.object(
            router, "_try_panthera_local_fallback", return_value=(expected, "")
        ) as local_fallback:
            result = router.synthesize(sample_input(), "cloud")
        self.assertEqual(result.agent, "felis")
        self.assertEqual(result.fallback_reason, "openai_error")
        local_fallback.assert_called_once_with(unittest.mock.ANY, "felis")

    def test_panthera_falls_back_to_structured_digest_after_felis(self) -> None:
        router = SynthesisRouter()
        with patch.object(router, "_panthera", side_effect=RuntimeError("openai_unavailable")), patch.object(
            router,
            "_try_panthera_local_fallback",
            return_value=(None, "local_insufficient_ram"),
        ) as local_fallback:
            result = router.synthesize_mode(sample_input(), "panthera")
        self.assertEqual(result.provider, "raw")
        self.assertEqual(result.fallback_reason, "local_insufficient_ram")
        self.assertEqual(
            result.fallback_steps,
            [
                "panthera:openai_unavailable",
                "felis:local_insufficient_ram",
                "structured_digest:resolved",
            ],
        )
        local_fallback.assert_called_once_with(unittest.mock.ANY, "felis")

    def test_late_warmup_returns_raw_without_cancelling_worker(self) -> None:
        router = SynthesisRouter()
        handle = WarmupHandle()
        with patch("core.synthesis.router.LOCAL_PRIMARY_GRACE_SECONDS", 0), patch(
            "core.synthesis.router.resident_agent_key", return_value=None
        ):
            result = router.synthesize(sample_input(), "local", handle)
        self.assertEqual(result.provider, "raw")
        self.assertEqual(result.fallback_reason, "local_warmup_timeout")
        self.assertFalse(handle.event.is_set())

    def test_completed_failed_warmup_uses_reason(self) -> None:
        handle = WarmupHandle(reason="local_model_missing")
        handle.event.set()
        router = SynthesisRouter()
        with patch("core.synthesis.router.resident_agent_key", return_value=None):
            result = router.synthesize(sample_input(), "local", handle)
        self.assertEqual(result.fallback_reason, "local_model_missing")

    def test_local_generation_has_no_tools_history_or_thinking(self) -> None:
        router = SynthesisRouter()
        response = ProviderTurnResult(
            message=AgentMessage(
                role="agent",
                content="===SPEECH===\nReady.\n===INSIGHTS===\n- Clear",
            )
        )
        with patch("core.synthesis.router.try_begin_local_execution", return_value=True), patch(
            "core.synthesis.router.end_local_execution"
        ), patch(
            "core.synthesis.router.LlamaCppProvider.generate_turn", return_value=response
        ) as generate, patch(
            "core.synthesis.router.PRIMARY_SYNTHESIS_PROMPT", "PRIMARY_PROMPT"
        ):
            result = router._local(sample_input(), "felis", None)
        messages, tools, profile = generate.call_args.args
        self.assertEqual(len(messages), 1)
        self.assertEqual(tools, [])
        self.assertEqual(profile.reasoning_mode, "none")
        self.assertEqual(profile.final_answer_max_tokens, 512)
        self.assertTrue(profile.system_instruction.startswith("You are Apex Felis"))
        self.assertIn("PRIMARY_PROMPT", profile.system_instruction)
        self.assertEqual(result.agent, "felis")

    def test_explicit_felis_synthesis_uses_llama_cpp_at_16k(self) -> None:
        router = SynthesisRouter()
        response = ProviderTurnResult(
            message=AgentMessage(
                role="agent",
                content="===SPEECH===\nReady.\n===INSIGHTS===\n- Clear",
            ),
            resolved_model=GEMMA_E2B_ALIAS,
        )
        handle = WarmupHandle(
            agent_key="felis",
            model_ref=LocalModelRef(provider="llama_cpp", model=GEMMA_E2B_ALIAS),
            success=True,
        )
        handle.event.set()
        states: list[tuple[object, ...]] = []
        router = SynthesisRouter(lambda *args: states.append(args))
        with patch(
            "core.synthesis.router.resident_agent_key", return_value=None
        ), patch.object(
            router, "start_agent_warmup", return_value=handle
        ), patch(
            "core.synthesis.router.resolve_selected_model_profile",
            return_value=get_model_profile(QWEN3_4B_MODEL),
        ), patch(
            "core.synthesis.router.try_begin_local_execution", return_value=True
        ), patch("core.synthesis.router.end_local_execution"), patch(
            "core.synthesis.router.LlamaCppProvider.generate_turn",
            return_value=response,
        ) as generate:
            result = router.synthesize_mode(sample_input(), "felis")

        messages, tools, profile = generate.call_args.args
        self.assertEqual(result.provider, "llama_cpp")
        self.assertEqual(result.agent, "felis")
        self.assertEqual(result.resolved_model, GEMMA_E2B_ALIAS)
        self.assertEqual(len(messages), 1)
        self.assertEqual(tools, [])
        self.assertEqual(profile.api_model, GEMMA_E2B_MODEL)
        self.assertEqual(profile.runtime_model_id, GEMMA_E2B_ALIAS)
        self.assertEqual(profile.context_window, 16_384)
        self.assertEqual(profile.reasoning_mode, "none")
        self.assertEqual(profile.final_answer_max_tokens, 512)
        self.assertIn(("generating", "llama_cpp", "felis", None), states)

    def test_resident_felis_reuses_the_actual_context_alias(self) -> None:
        router = SynthesisRouter()
        resident = LocalModelRef(provider="llama_cpp", model="gemma-4-e2b-4k")
        response = ProviderTurnResult(
            message=AgentMessage(
                role="agent",
                content="===SPEECH===\nReady.\n===INSIGHTS===\n- Clear",
            ),
            resolved_model="gemma-4-e2b-4k",
        )
        with patch(
            "core.synthesis.router.resident_agent_key", return_value="felis"
        ), patch(
            "core.synthesis.router.resident_local_model_ref",
            return_value=resident,
        ), patch(
            "core.synthesis.router.try_begin_local_execution", return_value=True
        ), patch("core.synthesis.router.end_local_execution"), patch(
            "core.synthesis.router.LlamaCppProvider.generate_turn",
            return_value=response,
        ) as generate, patch.object(router, "start_agent_warmup") as warmup:
            result = router.synthesize_mode(sample_input(), "felis")

        profile = generate.call_args.args[2]
        self.assertEqual(result.provider, "llama_cpp")
        self.assertEqual(profile.runtime_model_id, "gemma-4-e2b-4k")
        self.assertEqual(profile.context_window, 4096)
        warmup.assert_not_called()

    def test_explicit_felis_failure_falls_to_structured_digest(self) -> None:
        router = SynthesisRouter()
        handle = WarmupHandle(
            agent_key="felis",
            model_ref=LocalModelRef(provider="llama_cpp", model=GEMMA_E2B_ALIAS),
            success=True,
        )
        handle.event.set()
        with patch(
            "core.synthesis.router.resident_agent_key", return_value=None
        ), patch.object(
            router, "start_agent_warmup", return_value=handle
        ), patch(
            "core.synthesis.router.try_begin_local_execution", return_value=True
        ), patch("core.synthesis.router.end_local_execution"), patch(
            "core.synthesis.router.LlamaCppProvider.generate_turn",
            side_effect=RuntimeError("router unavailable"),
        ):
            result = router.synthesize_mode(sample_input(), "felis")

        self.assertEqual(result.provider, "raw")
        self.assertEqual(result.fallback_reason, "local_generation_failed")
        self.assertEqual(result.fallback_steps, ["structured_digest:resolved"])

    def test_felis_cold_warmup_uses_llama_cpp_provider_and_16k(self) -> None:
        router = SynthesisRouter()
        backend = MagicMock()
        backend.enabled = True
        snapshot = {
            "provider": "llama_cpp",
            "reachable": True,
            "installed_models": [GEMMA_E2B_ALIAS],
            "loaded_models": [],
            "sampled_at": 0.0,
        }
        with patch(
            "core.synthesis.router.get_local_runtime_backend",
            return_value=backend,
        ), patch(
            "core.synthesis.router._has_unrecognized_resident_model",
            return_value=False,
        ), patch(
            "core.synthesis.router.try_begin_local_execution", return_value=True
        ), patch(
            "core.synthesis.router.get_provider_snapshot",
            return_value=snapshot,
        ), patch(
            "core.synthesis.router.resolve_selected_model_profile",
            return_value=get_model_profile(QWEN3_4B_MODEL),
        ), patch(
            "core.synthesis.router.is_local_model_ready", return_value=False
        ), patch(
            "core.synthesis.router.check_resource_gate",
            return_value=(True, None),
        ), patch(
            "core.synthesis.router.switch_local_model", return_value=True
        ) as switch_model, patch("core.synthesis.router.end_local_execution"):
            handle = router.start_agent_warmup("felis")
            self.assertTrue(handle.event.wait(1.0))

        self.assertTrue(handle.success)
        self.assertEqual(
            handle.model_ref,
            LocalModelRef(provider="llama_cpp", model=GEMMA_E2B_ALIAS),
        )
        loaded_profile = switch_model.call_args.args[0]
        self.assertEqual(loaded_profile.api_model, GEMMA_E2B_MODEL)
        self.assertEqual(loaded_profile.context_window, 16_384)
        self.assertEqual(loaded_profile.reasoning_mode, "none")

    def test_felis_warmup_reports_disabled_runtime(self) -> None:
        router = SynthesisRouter()
        backend = MagicMock()
        backend.enabled = False
        with patch(
            "core.synthesis.router.get_local_runtime_backend",
            return_value=backend,
        ):
            handle = router.start_agent_warmup("felis")
        self.assertEqual(handle.reason, "local_disabled")
        self.assertTrue(handle.event.is_set())

    def test_felis_warmup_reports_unreachable_or_missing_alias(self) -> None:
        router = SynthesisRouter()
        backend = MagicMock()
        backend.enabled = True
        for snapshot, reason in (
            (
                {
                    "provider": "llama_cpp",
                    "reachable": False,
                    "installed_models": [],
                    "loaded_models": [],
                    "sampled_at": 0.0,
                },
                "local_unreachable",
            ),
            (
                {
                    "provider": "llama_cpp",
                    "reachable": True,
                    "installed_models": [],
                    "loaded_models": [],
                    "sampled_at": 0.0,
                },
                "local_model_missing",
            ),
        ):
            with self.subTest(reason=reason), patch(
                "core.synthesis.router.get_local_runtime_backend",
                return_value=backend,
            ), patch(
                "core.synthesis.router._has_unrecognized_resident_model",
                return_value=False,
            ), patch(
                "core.synthesis.router.try_begin_local_execution",
                return_value=True,
            ), patch(
                "core.synthesis.router.get_provider_snapshot",
                return_value=snapshot,
            ), patch("core.synthesis.router.end_local_execution"):
                handle = router.start_agent_warmup("felis")
                self.assertTrue(handle.event.wait(1.0))
            self.assertEqual(handle.reason, reason)

    def test_felis_warmup_reports_resource_gate(self) -> None:
        router = SynthesisRouter()
        backend = MagicMock()
        backend.enabled = True
        snapshot = {
            "provider": "llama_cpp",
            "reachable": True,
            "installed_models": [GEMMA_E2B_ALIAS],
            "loaded_models": [],
            "sampled_at": 0.0,
        }
        with patch(
            "core.synthesis.router.get_local_runtime_backend",
            return_value=backend,
        ), patch(
            "core.synthesis.router._has_unrecognized_resident_model",
            return_value=False,
        ), patch(
            "core.synthesis.router.try_begin_local_execution", return_value=True
        ), patch(
            "core.synthesis.router.get_provider_snapshot",
            return_value=snapshot,
        ), patch(
            "core.synthesis.router.is_local_model_ready", return_value=False
        ), patch(
            "core.synthesis.router.check_resource_gate",
            return_value=(False, "insufficient_ram"),
        ), patch("core.synthesis.router.end_local_execution"):
            handle = router.start_agent_warmup("felis")
            self.assertTrue(handle.event.wait(1.0))
        self.assertEqual(handle.reason, "local_insufficient_ram")

    def test_local_synthesis_strategy_resolves_to_felis(self) -> None:
        from core.synthesis.models import strategy_to_briefing_mode

        self.assertEqual(strategy_to_briefing_mode("local"), "felis")
        self.assertEqual(strategy_to_briefing_mode("cloud"), "panthera")
        self.assertEqual(strategy_to_briefing_mode("raw"), "structured_digest")
        self.assertEqual(strategy_to_briefing_mode("apodemus"), "felis")
        self.assertEqual(strategy_to_briefing_mode("sorex"), "panthera")

    def test_structured_digest_mode(self) -> None:
        router = SynthesisRouter()
        with patch.object(router, "_panthera") as panthera, patch.object(router, "_local") as local:
            result = router.synthesize_mode(sample_input(), "structured_digest")
        self.assertEqual(result.provider, "raw")
        panthera.assert_not_called()
        local.assert_not_called()

    def test_local_provider_stability_map(self) -> None:
        self.assertEqual(
            {
                GEMMA_E2B_MODEL: ("stable", "llama_cpp"),
                QWEN3_17B_MODEL: ("stable", "ollama"),
                QWEN3_4B_MODEL: ("stable", "ollama"),
            },
            {
                GEMMA_E2B_MODEL: ("stable", "llama_cpp"),
                QWEN3_17B_MODEL: ("stable", "ollama"),
                QWEN3_4B_MODEL: ("stable", "ollama"),
            },
        )

    def test_cloud_provider_stability_map(self) -> None:
        self.assertEqual(
            {
                GEMINI_FLASH_LITE_MODEL: ("stable", "gemini"),
                GEMINI_FLASH_MODEL: ("stable", "gemini"),
            },
            {
                GEMINI_FLASH_LITE_MODEL: ("stable", "gemini"),
                GEMINI_FLASH_MODEL: ("stable", "gemini"),
            },
        )

    def test_felis_ollama_model_specs(self) -> None:
        profile = build_felis_profile(model=QWEN3_4B_MODEL)
        self.assertEqual(profile.stability, "stable")
        self.assertEqual((profile.api_model, profile.context_window), ("qwen3:4b-instruct", 4096))
        self.assertEqual((profile.final_answer_max_tokens, profile.generation_timeout), (768, 150))

    def test_prepare_local_warms_felis(self) -> None:
        router = SynthesisRouter()
        with patch("core.synthesis.router.resident_agent_key", return_value=None), patch(
            "core.synthesis.router.get_local_runtime_backend"
        ) as backend:
            backend.return_value.enabled = False
            handle = router.prepare("local")
        self.assertIsNotNone(handle)
        assert handle is not None
        self.assertEqual(handle.agent_key, "felis")
        self.assertEqual(handle.reason, "local_disabled")
        self.assertTrue(handle.event.is_set())


class ProfileAndPersistenceTests(unittest.TestCase):
    def test_gemini_models_map_effort_to_thinking_level(self) -> None:
        expected = {
            GEMINI_FLASH_LITE_MODEL: {
                "minimal": "minimal",
                "low": "low",
                "medium": "medium",
                "high": "high",
            },
            GEMINI_FLASH_MODEL: {
                "minimal": "minimal",
                "low": "low",
                "medium": "medium",
                "high": "high",
            },
        }
        for model_id, efforts in expected.items():
            with self.subTest(model=model_id):
                model_profile = get_model_profile(model_id)
                assert model_profile is not None
                for effort, thinking in efforts.items():
                    native = resolve_effort(model_profile, effort)  # type: ignore[arg-type]
                    profile = build_panthera_profile(model=model_id, effort=effort)
                    self.assertEqual(profile.thinking_level, thinking)

    def test_panthera_cloud_models_have_expected_stability(self) -> None:
        self.assertEqual(
            {
                model_id: (
                    get_model_profile(model_id).stability,
                    get_model_profile(model_id).provider,
                )
                for model_id in (GEMINI_FLASH_LITE_MODEL, GEMINI_FLASH_MODEL)
            },
            {
                GEMINI_FLASH_LITE_MODEL: ("stable", "gemini"),
                GEMINI_FLASH_MODEL: ("stable", "gemini"),
            },
        )

    def test_briefing_metadata_migration_and_legacy_compatibility(self) -> None:
        from core import database

        db_path = "file:apex_synthesis_test?mode=memory&cache=shared"
        original_connect = sqlite3.connect
        anchor = original_connect(db_path, uri=True)
        try:
            with anchor:
                anchor.execute("DROP TABLE IF EXISTS briefings")
                anchor.execute("DROP TABLE IF EXISTS runs")
                anchor.execute("DROP TABLE IF EXISTS reminders")
                anchor.execute(
                    "CREATE TABLE briefings (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "timestamp TEXT NOT NULL, briefing TEXT NOT NULL, digest_json TEXT NOT NULL)"
                )

            def connect_shared(_path: str, timeout: float = 30.0) -> sqlite3.Connection:
                return original_connect(db_path, timeout=timeout, uri=True)

            with patch.object(database.sqlite3, "connect", side_effect=connect_shared), patch.object(
                database, "DB_NAME", db_path
            ):
                database.initialize_db()
                database.save_briefing(
                    "Ready.",
                    {"confidence_score": 100},
                    {"synthesis_provider": "raw"},
                )
                rows = database.fetch_briefing_history()
            self.assertEqual(rows[0]["metadata"]["synthesis_provider"], "raw")
        finally:
            anchor.close()


if __name__ == "__main__":
    unittest.main()
