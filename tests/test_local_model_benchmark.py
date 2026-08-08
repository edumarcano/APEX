"""Focused tests for the small local model benchmark utility."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.agent.local_runtime.contract import LocalModelRef
from core.agent.types import AgentQueryResponse
from scripts import benchmark_local_models as benchmark


class _NullSampler:
    def __init__(self, *_args, **_kwargs) -> None:
        self.samples = ()

    def start(self) -> None:
        return None

    def stop(self) -> benchmark.MemorySnapshot:
        return benchmark.MemorySnapshot()


class BenchmarkUtilityTests(unittest.TestCase):
    def test_case_file_has_small_versioned_suite(self) -> None:
        cases = benchmark.load_benchmark_cases()

        self.assertEqual(len(cases["performance"]), 3)
        self.assertEqual(len(cases["tool_cases"]), 13)

    def test_context_change_requires_reload_but_reasoning_change_does_not(self) -> None:
        same_alias = LocalModelRef(provider="llama_cpp", model="neotoma-16k")
        changed_alias = LocalModelRef(provider="llama_cpp", model="neotoma-32k")

        self.assertFalse(benchmark.requires_model_reload(same_alias, same_alias))
        self.assertTrue(benchmark.requires_model_reload(same_alias, changed_alias))

    def test_candidate_profile_is_not_added_to_agent_catalog(self) -> None:
        configurations = benchmark.build_configurations(
            agents=None,
            context=16384,
            all_contexts=False,
            reasoning_modes=("none",),
            candidate_model="gemma-4-E4B-Q4_K_M.gguf",
            runtime_alias="benchmark-gemma-e4b-16k",
        )

        self.assertEqual(len(configurations), 1)
        candidate = configurations[0]
        self.assertEqual(candidate.agent, "candidate")
        self.assertIsNone(candidate.agent_key)
        self.assertEqual(candidate.runtime_alias, "benchmark-gemma-e4b-16k")
        self.assertNotIn("benchmark-gemma-e4b-16k", benchmark.AGENT_SPECS)

    def test_unknown_resident_aborts_before_any_unload(self) -> None:
        backend = mock.Mock()
        backend.provider = "llama_cpp"
        backend.enabled = True
        snapshot = {
            "provider": "llama_cpp",
            "reachable": True,
            "installed_models": ["external-alias"],
            "loaded_models": [
                {
                    "provider": "llama_cpp",
                    "name": "external-alias",
                    "model": "external-alias",
                    "state": "loaded",
                }
            ],
            "sampled_at": 0.0,
        }
        known = LocalModelRef(provider="llama_cpp", model="apodemus-16k")

        with (
            mock.patch.object(
                benchmark,
                "iter_local_runtime_backends",
                return_value=(backend,),
            ),
            mock.patch.object(
                benchmark,
                "get_provider_snapshot",
                return_value=snapshot,
            ),
        ):
            with self.assertRaises(benchmark.BenchmarkAbort):
                benchmark.inspect_runtime_residents({known}, required_provider="llama_cpp")

        backend.unload_model.assert_not_called()

    def test_unload_failure_aborts_before_next_configuration(self) -> None:
        reference = LocalModelRef(provider="llama_cpp", model="apodemus-16k")
        runner = benchmark.BenchmarkRunner.__new__(benchmark.BenchmarkRunner)
        runner._allowed_refs = frozenset({reference})
        runner._owned_model = True
        runner._owned_ref = reference

        with (
            mock.patch.object(
                benchmark,
                "inspect_runtime_residents",
                return_value=({}, frozenset({reference})),
            ),
            mock.patch.object(
                benchmark,
                "get_active_local_model",
                return_value=reference,
            ),
            mock.patch.object(
                benchmark,
                "unload_active_local_model",
                return_value=False,
            ) as unload,
        ):
            with self.assertRaises(benchmark.BenchmarkAbort):
                runner._unload_known_residents()

        unload.assert_called_once()

    def test_prepare_unloads_before_loading_a_different_alias(self) -> None:
        first = LocalModelRef(provider="llama_cpp", model="apodemus-16k")
        second = LocalModelRef(provider="llama_cpp", model="apodemus-32k")
        events: list[str] = []
        snapshots = {
            "llama_cpp": {
                "provider": "llama_cpp",
                "reachable": True,
                "installed_models": ["apodemus-32k"],
                "loaded_models": [],
                "sampled_at": 0.0,
            }
        }
        backend = mock.Mock()
        backend.provider = "llama_cpp"
        backend.enabled = True
        profile = SimpleNamespace(
            provider="llama_cpp",
            runtime_model_id="apodemus-32k",
            context_window=32768,
            reasoning_mode="none",
            ram_limit=90.0,
            cpu_limit=95.0,
        )
        configuration = benchmark.BenchmarkConfiguration(
            agent="apodemus",
            provider="llama_cpp",
            model="model.gguf",
            runtime_alias="apodemus-32k",
            context=32768,
            reasoning="none",
            profile=profile,
            agent_key="apodemus",
            tool_projection_agent="apodemus",
        )
        runner = benchmark.BenchmarkRunner.__new__(benchmark.BenchmarkRunner)
        runner._allowed_refs = frozenset({first, second})
        runner._capture = lambda _provider: benchmark.MemorySnapshot()
        runner._owned_model = False
        runner._owned_ref = None
        runner._unload_known_residents = lambda: events.append("unload")

        with (
            mock.patch.object(
                benchmark,
                "get_local_runtime_backend",
                return_value=backend,
            ),
            mock.patch.object(
                benchmark,
                "inspect_runtime_residents",
                side_effect=[
                    (snapshots, frozenset({first})),
                    (snapshots, frozenset()),
                ],
            ) as inspect,
            mock.patch.object(
                benchmark,
                "check_resource_gate",
                return_value=(True, None),
            ),
        ):
            events.append("before")
            reused, _ = runner._prepare_configuration(configuration)

        self.assertFalse(reused)
        self.assertEqual(events, ["before", "unload"])
        self.assertEqual(inspect.call_count, 2)

    def test_resource_record_preserves_unavailable_metrics(self) -> None:
        record = benchmark.build_resource_record(
            benchmark.MemorySnapshot(),
            benchmark.MemorySnapshot(),
            (),
        )

        self.assertIsNone(record["minimum_available_ram_bytes"])
        self.assertIsNone(record["peak_committed_memory_bytes"])
        self.assertIsNone(record["provider_process_private_peak_bytes"])
        self.assertEqual(record["sample_count"], 2)

    def test_expected_fixture_error_counts_as_completed_tool(self) -> None:
        case = {
            "id": "fixture_error_recovery",
            "category": "recovery",
            "expected_tools": ["get_weather_forecast"],
            "required_answer_facts": ["service unavailable"],
            "fixture_errors": {"get_weather_forecast": "upstream"},
        }
        dispatcher = SimpleNamespace(
            descriptors={"get_weather_forecast": object()},
            invocations=[
                benchmark.FixtureInvocation(
                    name="get_weather_forecast",
                    arguments={"location": "Synthetic City"},
                    schema_valid=True,
                    expected_error=True,
                )
            ],
        )
        response = AgentQueryResponse(
            answer="The weather service unavailable, so I cannot check the forecast.",
            agent_used={},
            tool_trace=[{"name": "get_weather_forecast", "status": "error"}],
        )

        result = benchmark.score_tool_case(case, response, dispatcher, 0.1)

        self.assertTrue(result["completed_required_tools"])
        self.assertTrue(result["task_success"])

    def test_context_mismatch_still_cleans_up_loaded_model(self) -> None:
        reference = LocalModelRef(provider="llama_cpp", model="apodemus-16k")
        configuration = benchmark.BenchmarkConfiguration(
            agent="apodemus",
            provider="llama_cpp",
            model="model.gguf",
            runtime_alias="apodemus-16k",
            context=16384,
            reasoning="none",
            profile=SimpleNamespace(),
            agent_key="apodemus",
            tool_projection_agent="apodemus",
        )
        runner = benchmark.BenchmarkRunner.__new__(benchmark.BenchmarkRunner)
        runner.configurations = (configuration,)
        runner.cases = {"performance": [], "tool_cases": []}
        runner.repetitions = 1
        runner._allowed_refs = frozenset({reference})
        runner._owned_model = False
        runner._owned_ref = None
        runner._resource_sampler_factory = _NullSampler
        runner._capture = lambda _provider: benchmark.MemorySnapshot()
        runner._prepare_configuration = lambda _configuration: (
            False,
            benchmark.MemorySnapshot(),
        )
        runner._verify_target_resident = mock.Mock(
            side_effect=benchmark.BenchmarkFailure("context mismatch")
        )
        cleaned_refs: list[LocalModelRef | None] = []

        def cleanup() -> None:
            cleaned_refs.append(runner._owned_ref)
            runner._owned_model = False
            runner._owned_ref = None

        runner._cleanup_owned_model = cleanup

        with (
            mock.patch.object(benchmark, "try_begin_local_execution", return_value=True),
            mock.patch.object(benchmark, "end_local_execution"),
            mock.patch.object(benchmark, "switch_local_model", return_value=True),
        ):
            result = runner.run()

        self.assertFalse(result["aborted"])
        self.assertEqual(result["failed_runs"], 1)
        self.assertEqual(cleaned_refs, [reference])

    def test_warmup_is_not_counted_as_a_measured_repetition(self) -> None:
        configurations = benchmark.build_configurations(
            agents=("apodemus",),
            context=16384,
            all_contexts=False,
            reasoning_modes=("none",),
        )
        calls: list[str] = []
        response = AgentQueryResponse(answer="ready", agent_used={})

        class RecordingRunner(benchmark.BenchmarkRunner):
            def _prepare_configuration(self, _configuration):
                return False, benchmark.MemorySnapshot()

            def _verify_target_resident(self, _configuration):
                return None

            def _execute_query(
                self,
                _configuration,
                _provider,
                prompt,
                _descriptors,
                *,
                dispatcher=None,
            ):
                del dispatcher
                calls.append(prompt)
                return response, 0.01

            def _run_tool_suite(self, _configuration, _provider):
                return {
                    "metrics": {},
                    "cases": [],
                    "measured_tasks": 0,
                }

        runner = RecordingRunner(
            configurations,
            {"performance": benchmark.load_benchmark_cases()["performance"], "tool_cases": []},
            repetitions=2,
            capture=lambda _provider: benchmark.MemorySnapshot(),
            resource_sampler_factory=_NullSampler,
        )
        with (
            mock.patch.object(benchmark, "try_begin_local_execution", return_value=True),
            mock.patch.object(benchmark, "end_local_execution"),
            mock.patch.object(benchmark, "switch_local_model", return_value=True),
            mock.patch.object(runner, "_cleanup_owned_model"),
            mock.patch.object(
                benchmark,
                "_provider_for_profile",
                return_value=object(),
            ),
        ):
            result = runner.run()

        self.assertFalse(result["aborted"])
        run = result["runs"][0]
        self.assertEqual(run["performance"]["measured_requests"], 6)
        self.assertEqual(len(calls), 7)
        self.assertEqual(calls[0], "Reply with the single word READY.")
        self.assertNotIn(
            "Reply with the single word READY.",
            [record["case_id"] for record in run["performance"]["requests"]],
        )

    def test_json_and_markdown_outputs_are_serializable(self) -> None:
        result = {
            "benchmark_version": 0,
            "timestamp": "2026-08-08T11:30:00-04:00",
            "system": {"os": "Windows", "ram_gb": 16},
            "runs": [],
            "aborted": False,
        }
        with tempfile.TemporaryDirectory() as temporary:
            json_path, markdown_path = benchmark.write_results(
                result,
                Path(temporary) / "result.json",
            )

            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), result)
            self.assertIn("APEX Local Model Benchmark", markdown_path.read_text())


if __name__ == "__main__":
    unittest.main()
