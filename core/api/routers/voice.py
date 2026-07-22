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

    Uses the universal speech lock so audio never overlaps. Voice mode ``off``
    returns ``403``. Competing requests return ``409``.
    """
    return speak_text(payload)
