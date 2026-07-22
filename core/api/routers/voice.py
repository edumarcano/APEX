"""Voice delivery routes."""

from __future__ import annotations

from fastapi import APIRouter

from core.api.models import VoiceSpeakRequest, VoiceSpeakResponse
from core.api.voice import speak_text

router = APIRouter(tags=["voice"])


@router.post(
    "/api/v1/voice/speak",
    response_model=VoiceSpeakResponse,
    summary="Speak Text",
)
def voice_speak(payload: VoiceSpeakRequest) -> VoiceSpeakResponse:
    """
    Speak sanitized text using the configured TTS engine.

    Uses the universal speech lock so audio never overlaps. Competing requests
    return ``409``. Voice mode gating lands in a later milestone; this endpoint
    always attempts delivery when called.
    """
    return speak_text(payload)
