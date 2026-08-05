"""Provider-aware local-agent preflight coverage."""

from __future__ import annotations

import unittest
from unittest import mock

from core.telemetry.preflight import _evaluate_local_agent_blockers


class LiteRTPreflightTests(unittest.TestCase):
    def _evaluate(
        self,
        agent: str,
        status: tuple[str, str | None, bool, bool, int | None],
        *,
        execution_active: bool = False,
    ):
        with mock.patch(
            "core.telemetry.preflight.resolve_litert_agent_status",
            return_value=status,
        ), mock.patch(
            "core.telemetry.preflight.is_local_execution_active",
            return_value=execution_active,
        ):
            return _evaluate_local_agent_blockers(agent)

    def test_litert_agents_are_not_unknown(self) -> None:
        for agent in ("microtus", "mustela"):
            blockers, cold_load = self._evaluate(
                agent, ("available", None, False, False, None)
            )
            self.assertEqual(blockers, [])
            self.assertTrue(cold_load)

    def test_disabled_litert_is_truthful(self) -> None:
        blockers, _ = self._evaluate(
            "microtus",
            ("disabled", "LiteRT local inference is disabled.", False, False, None),
        )
        self.assertEqual([item.code for item in blockers], ["model_unreachable"])
        self.assertIn("disabled", blockers[0].message.lower())

    def test_missing_interpreter_is_truthful(self) -> None:
        blockers, _ = self._evaluate(
            "mustela",
            (
                "provider_unreachable",
                "Configure a compatible LiteRT worker interpreter.",
                False,
                False,
                None,
            ),
        )
        self.assertEqual([item.code for item in blockers], ["model_unreachable"])
        self.assertIn("interpreter", blockers[0].message.lower())

    def test_missing_artifact_uses_model_not_installed(self) -> None:
        blockers, _ = self._evaluate(
            "microtus",
            (
                "model_not_installed",
                "Install the expected LiteRT model artifact 'gemma-4-E2B-it.litertlm'.",
                False,
                False,
                None,
            ),
        )
        self.assertEqual([item.code for item in blockers], ["model_not_installed"])
        self.assertIn("gemma-4-E2B-it.litertlm", blockers[0].message)

    def test_available_litert_passes(self) -> None:
        blockers, cold_load = self._evaluate(
            "mustela", ("available", None, True, False, 120)
        )
        self.assertEqual(blockers, [])
        self.assertFalse(cold_load)

    def test_active_local_execution_blocks_litert(self) -> None:
        blockers, _ = self._evaluate(
            "microtus",
            ("available", None, False, False, None),
            execution_active=True,
        )
        self.assertEqual(
            [item.code for item in blockers], ["concurrent_local_execution"]
        )

    def test_ollama_preflight_path_remains_provider_specific(self) -> None:
        snapshot = {
            "reachable": True,
            "installed_tags": ["qwen3:1.7b"],
            "loaded_models": [],
            "vitals": {"ram": 20.0, "cpu": 20.0},
            "sampled_at": 0.0,
        }
        with mock.patch("core.telemetry.preflight.OLLAMA_ENABLED", True), mock.patch(
            "core.telemetry.preflight.is_local_execution_active", return_value=False
        ), mock.patch(
            "core.telemetry.preflight.get_status_snapshot", return_value=snapshot
        ), mock.patch(
            "core.telemetry.preflight.check_resource_gate", return_value=(True, None)
        ) as gate:
            blockers, cold_load = _evaluate_local_agent_blockers("sorex")
        self.assertEqual(blockers, [])
        self.assertTrue(cold_load)
        gate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
