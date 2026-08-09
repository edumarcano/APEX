"""Regression coverage for benchmark resource recovery between models."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock
import unittest

from scripts import benchmark_local_models as benchmark


class BenchmarkResourceRecoveryTests(unittest.TestCase):
    def _configuration(self) -> benchmark.BenchmarkConfiguration:
        profile = SimpleNamespace(
            provider="llama_cpp",
            runtime_model_id="neotoma-16k",
            context_window=16384,
            reasoning_mode="none",
            ram_limit=90.0,
            cpu_limit=95.0,
        )
        return benchmark.BenchmarkConfiguration(
            agent="neotoma",
            provider="llama_cpp",
            model="model.gguf",
            runtime_alias="neotoma-16k",
            context=16384,
            reasoning="none",
            profile=profile,
            agent_key="neotoma",
            tool_projection_agent="neotoma",
        )

    def test_resource_recovery_requires_consecutive_open_samples(self) -> None:
        runner = benchmark.BenchmarkRunner.__new__(benchmark.BenchmarkRunner)
        runner.resource_recovery_timeout_seconds = 5.0
        runner.resource_recovery_poll_seconds = 0.5
        runner.resource_recovery_stable_samples = 2
        sleeps: list[float] = []
        runner._sleep = sleeps.append

        with mock.patch.object(
            benchmark,
            "check_resource_gate",
            side_effect=[
                (False, "memory pressure"),
                (True, None),
                (False, "memory pressure"),
                (True, None),
                (True, None),
            ],
        ) as gate:
            recovered, reason = runner._wait_for_resource_recovery(
                self._configuration()
            )

        self.assertTrue(recovered)
        self.assertIsNone(reason)
        self.assertEqual(gate.call_count, 5)
        self.assertEqual(sleeps, [0.5, 0.5, 0.5, 0.5])

    def test_resource_recovery_timeout_returns_last_gate_reason(self) -> None:
        runner = benchmark.BenchmarkRunner.__new__(benchmark.BenchmarkRunner)
        runner.resource_recovery_timeout_seconds = 1.0
        runner.resource_recovery_poll_seconds = 0.5
        runner.resource_recovery_stable_samples = 2
        runner._sleep = lambda _seconds: None

        with mock.patch.object(
            benchmark,
            "check_resource_gate",
            return_value=(False, "memory pressure"),
        ) as gate:
            recovered, reason = runner._wait_for_resource_recovery(
                self._configuration()
            )

        self.assertFalse(recovered)
        self.assertEqual(reason, "memory pressure")
        self.assertEqual(gate.call_count, 3)

    def test_resource_blocked_is_distinct_from_model_failure(self) -> None:
        runner = benchmark.BenchmarkRunner.__new__(benchmark.BenchmarkRunner)
        configuration = self._configuration()
        runner._prepare_configuration = mock.Mock(
            side_effect=benchmark.ResourceBlocked("host resources did not recover")
        )
        runner._resource_sampler_factory = mock.Mock()
        runner._capture = mock.Mock()

        result = runner._run_configuration(configuration)

        self.assertEqual(result["status"], "resource_blocked")
        self.assertIn("did not recover", result["error"])
        self.assertIsNone(result["load_seconds"])
        runner._resource_sampler_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
