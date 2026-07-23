"""Independent voice delivery helpers for activation cues and manual speak."""

from __future__ import annotations

from fastapi import HTTPException, status

from core import speaker
from core.api.models import VoiceSpeakRequest, VoiceSpeakResponse
from core.api.tts import clean_for_tts
from core.settings import get_settings_store


def speak_text(payload: VoiceSpeakRequest) -> VoiceSpeakResponse:
    """
    Sanitize and speak bounded text under the universal speech lock.

    Runs synchronously so FastAPI offloads blocking TTS I/O to a worker thread.
    Voice mode ``off`` returns ``403``. Competing delivery returns ``409``.
    """
    voice_mode = get_settings_store().get_snapshot().voice.mode
    if voice_mode == "off":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Voice delivery is disabled (voice.mode=off).",
        )

    cleaned = clean_for_tts(payload.text)
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Speech text is empty after sanitization.",
        )

    try:
        if not speaker.try_speak(cleaned):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Speech delivery is already in progress.",
            )
    except HTTPException:
        raise
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Speech delivery failed.",
        ) from None
    return VoiceSpeakResponse()
