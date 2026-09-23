"""Voice delivery routes."""

from __future__ import annotations

from fastapi import APIRouter

from core.api.models import VoiceCueRequest, VoiceCueResponse, VoiceSpeakRequest, VoiceSpeakResponse
from core.api.voice import speak_cue, speak_text

router = APIRouter(tags=["voice"])


@router.post(
    "/api/v1/voice/speak",
    response_model=VoiceSpeakResponse,
    summary="Speak Text",
)
def voice_speak(payload: VoiceSpeakRequest) -> VoiceSpeakResponse:
    """
    Speak sanitized text using the configured TTS engine.

    Uses the universal speech lock so audio never overlaps. Voice mode ``off``
    returns ``403``. Competing requests return ``409``.
    """
    return speak_text(payload)


@router.post(
    "/api/v1/voice/cue",
    response_model=VoiceCueResponse,
    summary="Speak Contextual Voice Cue",
)
def voice_cue(payload: VoiceCueRequest) -> VoiceCueResponse:
    """Format and speak one supported contextual cue in automatic mode."""
    return speak_cue(payload)
