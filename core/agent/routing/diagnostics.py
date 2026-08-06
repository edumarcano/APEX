"""Routing diagnostics helpers."""

from __future__ import annotations

from core.agent.routing.model_manifest import PRODUCTION_MODEL_KEY, PRODUCTION_MODEL_SPEC
from core.agent.routing.model_store import verify_installed_model
from core.agent.routing.models import CapabilityRoutingDecision
from core.agent.routing.onnx_encoder import _ENCODER_CACHE
from core.agent.types import CapabilityRoutingDiagnostics, ToolRoutingMode


def diagnostics_from_decision(
    mode: ToolRoutingMode,
    decision: CapabilityRoutingDecision,
) -> CapabilityRoutingDiagnostics:
    return CapabilityRoutingDiagnostics(
        mode=mode,
        decision=decision.kind,
        enforced=decision.enforced,
        selected_families=list(decision.selected_families),
        considered_tool_count=decision.considered_tool_count,
        offered_tool_count=decision.offered_tool_count,
        considered_schema_tokens=decision.considered_schema_tokens,
        offered_schema_tokens=decision.offered_schema_tokens,
        top_score=decision.top_score,
        score_margin=decision.score_margin,
        latency_ms=decision.latency_ms,
        model_key=decision.model_key,
        fallback_reason=decision.fallback_reason,
    )


def build_tool_routing_status(mode: ToolRoutingMode) -> dict[str, object]:
    if mode == "disabled":
        return {
            "mode": mode,
            "model_key": PRODUCTION_MODEL_KEY,
            "installed": False,
            "verified": False,
            "loaded": False,
            "state": "disabled",
            "reason": None,
        }
    verified, reason = verify_installed_model(PRODUCTION_MODEL_SPEC)
    loaded = False
    if verified:
        cached = _ENCODER_CACHE.get(PRODUCTION_MODEL_KEY)
        loaded = cached is not None and cached._session is not None  # noqa: SLF001
    state = "disabled"
    status_reason = reason
    if mode != "disabled":
        if not verified:
            state = reason or "not_installed"
        elif loaded:
            state = "loaded"
        else:
            state = "ready"
    return {
        "mode": mode,
        "model_key": PRODUCTION_MODEL_KEY,
        "installed": verified,
        "verified": verified,
        "loaded": loaded,
        "state": state,
        "reason": status_reason,
    }
