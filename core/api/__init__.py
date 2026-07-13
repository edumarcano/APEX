"""APEX FastAPI package: app construction, models, state, and routers."""

from __future__ import annotations

from core.api.app import app, get_allowed_origins, main
from core.api.assistant import query_agent
from core.api.briefing import (
    _DEMO_STAGE_DELAY_SECONDS,
    _compute_confidence_and_failures,
    _evaluate_sports_trust,
    trigger_briefing,
)
from core.api.models import (
    BriefingResponse,
    DigestPayload,
    RuntimeMetadata,
    TelemetryPayload,
    parse_digest_payload as _parse_digest_payload,
    parse_runtime_metadata as _parse_runtime_metadata,
)
from core.api.state import (
    PipelineState,
    _TRIGGER_LOCK,
    _speak_and_cleanup,
    global_pipeline_state,
)
from core.api.tts import clean_for_tts

__all__ = [
    "BriefingResponse",
    "DigestPayload",
    "PipelineState",
    "RuntimeMetadata",
    "TelemetryPayload",
    "_DEMO_STAGE_DELAY_SECONDS",
    "_TRIGGER_LOCK",
    "_compute_confidence_and_failures",
    "_evaluate_sports_trust",
    "_parse_digest_payload",
    "_parse_runtime_metadata",
    "_speak_and_cleanup",
    "app",
    "clean_for_tts",
    "get_allowed_origins",
    "global_pipeline_state",
    "main",
    "query_agent",
    "trigger_briefing",
]
