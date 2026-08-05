"""Checkpoint 4 coverage for LiteRT catalog visibility and API routing."""

from __future__ import annotations

import unittest
from unittest import mock

from fastapi import HTTPException

from core.agent.catalog import AGENT_SPECS, build_concrete_agent
from core.agent.providers.litert_models import LiteRTModelProfile
from core.agent.types import AgentQueryRequest
from core.api.cortex import (
    build_agent_statuses,
    load_local_model_endpoint,
    query_agent,
    unload_active_local_model_endpoint,
)


class LiteRTCatalogAndApiTests(unittest.TestCase):
    def test_preview_agents_remain_visible_when_litert_is_disabled(self) -> None:
        with mock.patch("core.agent.providers.litert_lifecycle.LITERT_ENABLED", False):
            statuses = {entry.key: entry for entry in build_agent_statuses()}

        for key, name in (("microtus", "Apex Microtus"), ("mustela", "Apex Mustela")):
            self.assertIn(key, AGENT_SPECS)
            self.assertEqual(statuses[key].display_name, name)
            self.assertEqual(statuses[key].provider, "litert")
            self.assertEqual(statuses[key].status, "disabled")
            self.assertIn("LiteRT local inference is disabled", statuses[key].reason or "")

    def test_explicit_litert_query_never_falls_back_to_ollama(self) -> None:
        with (
            mock.patch("core.api.cortex.LITERT_ENABLED", False),
            mock.patch("core.agent.providers.litert_lifecycle.LITERT_ENABLED", False),
            mock.patch("core.api.cortex._execute_agent_turn") as execute,
            mock.patch("core.api.cortex.OllamaProvider") as ollama,
        ):
            with self.assertRaises(HTTPException) as raised:
                query_agent(
                    AgentQueryRequest(agent="microtus", prompt="What time is it?")
                )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("LiteRT", str(raised.exception.detail))
        execute.assert_not_called()
        ollama.assert_not_called()

    def test_demo_mode_explicit_unavailable_litert_is_truthful(self) -> None:
        with (
            mock.patch("core.api.cortex.DEMO_MODE", True),
            mock.patch("core.api.cortex.LITERT_ENABLED", False),
            mock.patch("core.agent.providers.litert_lifecycle.LITERT_ENABLED", False),
            mock.patch("core.api.cortex.run_demo_agent_query") as demo,
        ):
            with self.assertRaises(HTTPException) as raised:
                query_agent(
                    AgentQueryRequest(agent="mustela", prompt="Summarize my day")
                )

        self.assertEqual(raised.exception.status_code, 503)
        demo.assert_not_called()

    def test_catalog_uses_provider_specific_profile_for_artifact_metadata(self) -> None:
        microtus = AGENT_SPECS["microtus"]
        mustela = AGENT_SPECS["mustela"]
        self.assertEqual(microtus.api_model, "litert-community/gemma-4-E2B-it-litert-lm")
        self.assertEqual(mustela.api_model, "litert-community/gemma-4-E4B-it-litert-lm")
        self.assertEqual(microtus.capability_tags, ("Lightweight", "Fast local", "LiteRT", "Constrained workflows"))
        self.assertEqual(mustela.capability_tags, ("Balanced local", "Deeper reasoning", "LiteRT", "Tool workflows"))

        profile = build_concrete_agent("microtus", native_effort=None)
        self.assertIsInstance(profile, LiteRTModelProfile)
        self.assertTrue((profile.artifact_path or "").endswith("gemma-4-E2B-it.litertlm"))
        self.assertNotIn("artifact_path", profile.model_dump())

    def test_litert_load_uses_shared_provider_slot_and_backend(self) -> None:
        with (
            mock.patch("core.api.cortex.DEMO_MODE", False),
            mock.patch("core.api.cortex.LITERT_ENABLED", True),
            mock.patch("core.agent.providers.litert_lifecycle.LITERT_ENABLED", True),
            mock.patch(
                "core.api.cortex.resolve_litert_agent_status",
                return_value=("available", None, False, False, None),
            ),
            mock.patch("core.api.cortex.try_begin_local_execution", return_value=True) as begin,
            mock.patch("core.api.cortex.end_local_execution") as end,
            mock.patch(
                "core.api.cortex.is_local_model_resident", side_effect=[False, True]
            ),
            mock.patch("core.api.cortex.check_litert_resource_gate", return_value=(True, None)),
            mock.patch("core.api.cortex.switch_local_model", return_value=True) as switch,
        ):
            response = load_local_model_endpoint("microtus")

        self.assertEqual(response.agent, "microtus")
        begin.assert_called_once_with("litert")
        switch.assert_called_once_with(mock.ANY, provider="litert")
        end.assert_called_once()

    def test_litert_unload_does_not_route_through_ollama(self) -> None:
        with (
            mock.patch("core.api.cortex.LOCAL_RUNTIME_MANUAL_UNLOAD_ENABLED", True),
            mock.patch("core.api.cortex.get_active_loaded_model", return_value="gemma-4-E2B-it.litertlm"),
            mock.patch("core.api.cortex.try_begin_local_execution", return_value=True) as begin,
            mock.patch("core.api.cortex.end_local_execution") as end,
            mock.patch("core.api.cortex.unload_active_local_model", return_value=True) as unload,
        ):
            response = unload_active_local_model_endpoint()

        self.assertEqual(response.status, "success")
        begin.assert_called_once_with("litert")
        unload.assert_called_once_with(provider="litert")
        end.assert_called_once()


if __name__ == "__main__":
    unittest.main()
