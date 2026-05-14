from __future__ import annotations

import base64
import binascii
import io
import os
from typing import Any

os.environ.setdefault(
    "SDL_VIDEODRIVER", "dummy"
)  # prevent pygame from crashing on a headless/no-display environment

import pygame
import pyttsx3
import requests
from dotenv import load_dotenv

from core import config

load_dotenv(dotenv_path=config.ENV_PATH)


def _infer_language_code(voice_id: str) -> str:
    """Infer a BCP-47 language code from a Google voice identifier."""
    parts = voice_id.split("-")
    if len(parts) >= 2 and len(parts[0]) == 2 and len(parts[1]) == 2:
        return f"{parts[0]}-{parts[1]}"
    return "en-US"


def fetch_google_audio(text: str, voice_id: str) -> bytes:
    """Synthesize ``text`` with Google Cloud TTS and return MP3 bytes."""
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code=_infer_language_code(voice_id),
        name=voice_id,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
    )
    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )
    return response.audio_content


def fetch_inworld_audio(text: str, voice_id: str) -> bytes:
    """Synthesize text using Inworld TTS and return decoded audio bytes."""
    api_key = os.getenv("INWORLD_API_KEY")
    if not api_key:
        raise RuntimeError("INWORLD_API_KEY is not set.")

    response = requests.post(
        "https://api.inworld.ai/tts/v1/voice",
        headers={"Authorization": f"Basic {api_key}"},
        json={
            "text": text,
            "voiceId": voice_id,
            "modelId": "inworld-tts-1.5-mini",
        },
        timeout=30,
    )
    response.raise_for_status()

    data: dict[str, Any] = response.json()
    audio_content = data.get("audioContent")
    if not isinstance(audio_content, str):
        raise ValueError("Inworld response did not include a valid audioContent field.")

    try:
        return base64.b64decode(audio_content, validate=True)
    except binascii.Error as exc:
        raise ValueError("Inworld audioContent is not valid base64.") from exc


def _play_audio_bytes(data: bytes) -> None:
    """Play MP3 ``data`` in memory using ``pygame.mixer`` (no disk writes)."""
    if not data:
        raise ValueError("Cannot play empty audio bytes.")

    stream = io.BytesIO(data)
    pygame.mixer.init()
    pygame.mixer.music.load(stream)
    pygame.mixer.music.play()
    try:
        while pygame.mixer.music.get_busy():
            pygame.time.wait(100)
    finally:
        pygame.mixer.music.stop()
        unload = getattr(pygame.mixer.music, "unload", None)
        if callable(unload):
            unload()
        pygame.mixer.quit()


def initialize_engine():
    """
    Initializes the text-to-speech engine and sets the speed and voice.
    Returns:
        pyttsx3.Engine: The initialized engine.
    """
    engine = pyttsx3.init()

    engine.setProperty("rate", 175)

    voices = engine.getProperty("voices")
    engine.setProperty("voice", voices[0].id)

    return engine


def _speak_pyttsx3_local(text: str) -> None:
    """Synthesize locally with pyttsx3 (offline fallback)."""
    print("[SPEAKER] Initializing local pyttsx3 engine.")
    engine = initialize_engine()
    print(f"[SPEAKER] Local pyttsx3 output: {text}")
    print("[SPEAKER] Queuing pyttsx3 speech and starting run loop.")
    engine.say(text)
    engine.runAndWait()
    print("[SPEAKER] pyttsx3 playback finished.")


def _try_google_tts(content: str) -> bool:
    """Return ``True`` if Google cloud TTS played successfully."""
    if not config.GOOGLE_VOICE_ID.strip():
        print("[SPEAKER] Skipping Google TTS: google_voice_id is not configured.")
        return False
    try:
        print("[SPEAKER] Attempting Google Cloud TTS (primary or fallback).")
        audio = fetch_google_audio(content, config.GOOGLE_VOICE_ID)
        print("[SPEAKER] Google TTS succeeded; playing MP3 from memory.")
        _play_audio_bytes(audio)
        print("[SPEAKER] Google TTS playback completed.")
        return True
    except Exception as exc:  # noqa: BLE001 - broad catch so any cloud error drops to the next fallback
        print(f"[SPEAKER] Google TTS failed: {exc}.")
        return False


def _try_inworld_tts(content: str) -> bool:
    """Return ``True`` if Inworld TTS played successfully."""
    if not config.INWORLD_VOICE_ID.strip():
        print("[SPEAKER] Skipping Inworld TTS: inworld_voice_id is not configured.")
        return False
    try:
        print("[SPEAKER] Attempting Inworld TTS (primary or fallback).")
        audio = fetch_inworld_audio(content, config.INWORLD_VOICE_ID)
        print("[SPEAKER] Inworld TTS succeeded; playing MP3 from memory.")
        _play_audio_bytes(audio)
        print("[SPEAKER] Inworld TTS playback completed.")
        return True
    except Exception as exc:  # noqa: BLE001 - broad catch so any cloud error drops to the next fallback
        print(f"[SPEAKER] Inworld TTS failed: {exc}.")
        return False


def speak(text: str) -> None:
    """
    Speak ``text`` using cloud TTS when configured, with pyttsx3 as fallback.

    Order follows ``config.PRIMARY_TTS``: ``inworld`` tries Inworld then Google;
    ``google`` tries Google then Inworld. ``pyttsx3`` or exhausted cloud attempts
    use local pyttsx3.
    """
    primary_raw = getattr(config, "PRIMARY_TTS", "pyttsx3")
    primary = str(primary_raw).strip().lower()

    print(f"[SPEAKER] Speak request received (chars={len(text)}).")
    print(f"[SPEAKER] Configured PRIMARY_TTS is {primary_raw!r}.")

    if primary == "pyttsx3":
        print(
            "[SPEAKER] PRIMARY_TTS is pyttsx3, skipping cloud, "
            "using local engine only."
        )
        _speak_pyttsx3_local(text)
        return

    if primary == "inworld":
        print("[SPEAKER] Cloud order: Inworld first, then Google, then pyttsx3.")
        if _try_inworld_tts(text):
            return
        print("[SPEAKER] Inworld path unavailable or failed. Trying Google.")
        if _try_google_tts(text):
            return
        print("[SPEAKER] All cloud paths failed. Falling back to pyttsx3.")
        _speak_pyttsx3_local(text)
        return

    if primary == "google":
        print("[SPEAKER] Cloud order: Google first, then Inworld, then pyttsx3.")
        if _try_google_tts(text):
            return
        print("[SPEAKER] Google path unavailable or failed. Trying Inworld.")
        if _try_inworld_tts(text):
            return
        print("[SPEAKER] All cloud paths failed. Falling back to pyttsx3.")
        _speak_pyttsx3_local(text)
        return

    print(
        f"[SPEAKER] Unrecognized PRIMARY_TTS {primary_raw!r} "
        "(expected inworld, google, or pyttsx3), using pyttsx3 only."
    )
    _speak_pyttsx3_local(text)


if __name__ == "__main__":
    speak("System audio test. Speaker operational.")
