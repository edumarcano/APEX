"""Regression coverage for routing decision service."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from core.agent.capabilities import CapabilityDescriptor
from core.agent.routing.models import CapabilityRoutingRequest, RankedCapabilityFamily
from core.agent.routing.ranker import RankerResult, RankerUnavailable
from core.agent.routing.service import resolve_capabilities


def _descriptor(name: str, family: str) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        name=name,
        title=name,
        description=name,
        input_schema={"type": "object", "properties": {}},
        origin="native",
        risk="read",
        expose_to_agent=True,
        expose_to_mcp_server=False,
        expose_to_client_display=True,
        routing_family=family,
    )


class CapabilityRoutingDecisionTests(unittest.TestCase):
    def _request(self, **overrides):
        base = {
            "prompt": "Forecast",
            "history": (),
            "capabilities": (
                _descriptor("get_weather_forecast", "weather"),
                _descriptor("search_gmail", "mail"),
            ),
            "agent_key": "neofelis",
            "runtime": "cloud",
            "mode": "disabled",
            "explicit_scope": None,
        }
        base.update(overrides)
        return CapabilityRoutingRequest(**base)

    def test_disabled_cloud_offers_all_capabilities(self) -> None:
        decision = resolve_capabilities(self._request(mode="disabled", runtime="cloud"))
        self.assertEqual(decision.kind, "disabled")
        self.assertEqual(len(decision.offered_capabilities), 2)

    def test_disabled_local_offers_none(self) -> None:
        decision = resolve_capabilities(
            self._request(mode="disabled", runtime="local", agent_key="sorex")
        )
        self.assertEqual(decision.offered_capabilities, ())

    def test_explicit_none_bypasses_encoder(self) -> None:
        decision = resolve_capabilities(
            self._request(
                mode="enabled",
                runtime="local",
                agent_key="sorex",
                explicit_scope="none",
            )
        )
        self.assertEqual(decision.kind, "explicit_none")
        self.assertEqual(decision.offered_capabilities, ())

    @patch("core.agent.routing.service.rank_capability_families")
    def test_shadow_cloud_keeps_all_tools(self, ranker) -> None:
        ranker.return_value = RankerResult(
            rankings=(
                RankedCapabilityFamily(key="weather", score=0.9),
                RankedCapabilityFamily(key="none", score=0.1),
            ),
            model_key="all-minilm-l6-v2",
            latency_ms=1.0,
        )
        decision = resolve_capabilities(self._request(mode="shadow", runtime="cloud"))
        self.assertEqual(decision.kind, "shadow")
        self.assertFalse(decision.enforced)
        self.assertEqual(len(decision.offered_capabilities), 2)

    @patch("core.agent.routing.service.rank_capability_families")
    def test_enabled_semantic_reduces_cloud_tools(self, ranker) -> None:
        ranker.return_value = RankerResult(
            rankings=(
                RankedCapabilityFamily(key="weather", score=0.9),
                RankedCapabilityFamily(key="none", score=0.1),
            ),
            model_key="all-minilm-l6-v2",
            latency_ms=1.0,
        )
        decision = resolve_capabilities(self._request(mode="enabled", runtime="cloud"))
        self.assertEqual(decision.kind, "semantic")
        self.assertTrue(decision.enforced)
        self.assertEqual([tool.name for tool in decision.offered_capabilities], ["get_weather_forecast"])

    @patch("core.agent.routing.service.rank_capability_families")
    def test_model_missing_falls_back_full_on_cloud(self, ranker) -> None:
        from core.agent.routing.ranker import RankerUnavailable

        ranker.return_value = RankerUnavailable(reason="model_unavailable")
        decision = resolve_capabilities(self._request(mode="enabled", runtime="cloud"))
        self.assertEqual(decision.kind, "fallback_full")
        self.assertEqual(len(decision.offered_capabilities), 2)


if __name__ == "__main__":
    unittest.main()
