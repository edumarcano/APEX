from __future__ import annotations

import base64
import binascii
import ctypes
import io
import os
import threading
from typing import Any

# Headless SDL so pygame.mixer can init without a display
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pyttsx3
import requests
from dotenv import load_dotenv

from core import config

load_dotenv(dotenv_path=config.ENV_PATH)

_SPEAK_LOCK = threading.Lock()
_HTTP_SESSION: requests.Session = requests.Session()
_GOOGLE_TTS_CLIENT: Any | None = None


def _infer_language_code(voice_id: str) -> str:
    """Derive BCP-47 language code from a Google voice name."""
    parts = voice_id.split("-")
    if len(parts) >= 2 and len(parts[0]) == 2 and len(parts[1]) == 2:
        return f"{parts[0]}-{parts[1]}"
    return "en-US"


def _warm_system_subsystems() -> None:
    """Initialize and hold the pygame hardware mixer channel at import time."""
    try:
        pygame.mixer.init()
        print("[SPEAKER] Pygame hardware mixer channel pre-warmed successfully.")
    except Exception as exc:
        print(f"[SPEAKER] Pygame mixer pre-warm failed ({type(exc).__name__}).")


def _warm_cloud_clients() -> None:
    """Initialize Google Cloud TTS client at import when credentials are present."""
    global _GOOGLE_TTS_CLIENT

    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        print(
            "[SPEAKER] Skipping Google TTS client pre-warm: "
            "GOOGLE_APPLICATION_CREDENTIALS not present in environment variables."
        )
        return

    try:
        from google.cloud import texttospeech
        _GOOGLE_TTS_CLIENT = texttospeech.TextToSpeechClient()
        print("[SPEAKER] Cloud Text-to-Speech Client eagerly pre-warmed successfully.")
    except Exception as exc:  # noqa: BLE001
        print(f"[SPEAKER] Eager Google TTS pre-warm bypassed or failed ({type(exc).__name__}).")
        _GOOGLE_TTS_CLIENT = None


def fetch_google_audio(text: str, voice_id: str) -> bytes:
    """Synthesize text to MP3 bytes via the pre-warmed Google Cloud TTS client."""
    if _GOOGLE_TTS_CLIENT is None:
        if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            raise ValueError(
                "GOOGLE_APPLICATION_CREDENTIALS env variable is missing or unconfigured."
            )
        raise RuntimeError("Google TTS client context is completely uninitialized.")

    from google.cloud import texttospeech

    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code=_infer_language_code(voice_id),
        name=voice_id,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
    )
    response = _GOOGLE_TTS_CLIENT.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )
    return response.audio_content


def fetch_inworld_audio(text: str, voice_id: str) -> bytes:
    """Synthesize speech via Inworld TTS; returns decoded audio bytes."""
    api_key = os.getenv("INWORLD_API_KEY")
    if not api_key:
        raise RuntimeError("INWORLD_API_KEY is not set.")

    response = _HTTP_SESSION.post(
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
        raise ValueError("Inworld audioContent payload is not valid standard base64 structure.") from exc


def _play_audio_bytes(data: bytes) -> None:
    """Play raw MP3 data out of internal memory barriers via pygame.mixer streams.

    Parameters:
        data (bytes): Raw audio stream block array data.
    """
    if not data:
        raise ValueError("Cannot play empty audio bytes sequence context.")

    if pygame.mixer.get_init() is None:
        raise RuntimeError("Pygame mixer is not initialized; system pre-warm did not complete.")

    stream = io.BytesIO(data)
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


def _speak_pyttsx3_local(text: str) -> None:
    """Speak text with a thread-local pyttsx3 engine."""
    if os.name == "nt":
        try:
            ctypes.windll.ole32.CoInitialize(None)
        except OSError:
            pass

    try:
        print("[SPEAKER] Initializing thread-isolated local pyttsx3 engine context dynamically.")
        engine = pyttsx3.init()
        engine.setProperty("rate", 175)

        voices = engine.getProperty("voices")
        if voices:
            engine.setProperty("voice", voices[0].id)

        print("[SPEAKER] Enqueuing local pyttsx3 speech payload and running event loop thread bounds.")
        engine.say(text)
        engine.runAndWait()
        print("[SPEAKER] Local pyttsx3 playback sequence finalized cleanly.")
    except Exception as exc:
        print(f"[SPEAKER] Error: Local pyttsx3 initialization or run sequence failed ({type(exc).__name__}).")


def _try_google_tts(content: str) -> bool:
    """Return True if Google cloud TTS played successfully."""
    if not config.GOOGLE_VOICE_ID.strip():
        print("[SPEAKER] Skipping Google TTS: google_voice_id is not configured.")
        return False
    try:
        print("[SPEAKER] Attempting Google Cloud TTS (utilizing pre-warmed client context).")
        audio = fetch_google_audio(content, config.GOOGLE_VOICE_ID)
        print("[SPEAKER] Google TTS succeeded; playing MP3 from memory.")
        _play_audio_bytes(audio)
        print("[SPEAKER] Google TTS playback completed.")
        return True
    except Exception as exc:  # noqa: BLE001 - broad catch drops execution to the next fallback loop safely
        print(f"[SPEAKER] Error: Google TTS failed ({type(exc).__name__}).")
        return False


def _try_inworld_tts(content: str) -> bool:
    """Return True if Inworld TTS played successfully."""
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
    except Exception as exc:  # noqa: BLE001 - broad catch drops execution to the next fallback loop safely
        print(f"[SPEAKER] Error: Inworld TTS failed ({type(exc).__name__}).")
        return False


def speak(text: str) -> None:
    """Speak text parameters using pre-warmed cloud structures, defaulting to dynamic local thread loops.

    Protects and linearizes all executing threads via a universal lock block to guarantee 
    thread-safe audio routing across asynchronous invocation checkpoints.
    """
    with _SPEAK_LOCK:
        primary_raw = getattr(config, "PRIMARY_TTS", "pyttsx3")
        primary = str(primary_raw).strip().lower()

        print(f"[SPEAKER] Speak request received (chars={len(text)}).")
        print(f"[SPEAKER] Configured PRIMARY_TTS routing vector is {primary_raw!r}.")

        if primary == "pyttsx3":
            print("[SPEAKER] PRIMARY_TTS is pyttsx3, bypassing network paths, routing directly to local execution.")
            _speak_pyttsx3_local(text)
            return

        if primary == "inworld":
            print("[SPEAKER] Cloud priority sequence active: Inworld -> Google -> pyttsx3 offline fallback.")
            if _try_inworld_tts(text):
                return
            print("[SPEAKER] Inworld transmission dropped or failed. Routing to Google Cloud TTS.")
            if _try_google_tts(text):
                return
            print("[SPEAKER] Network paths fully exhausted. Deploying local thread-isolated fallback.")
            _speak_pyttsx3_local(text)
            return

        if primary == "google":
            print("[SPEAKER] Cloud priority sequence active: Google -> Inworld -> pyttsx3 offline fallback.")
            if _try_google_tts(text):
                return
            print("[SPEAKER] Google Cloud transmission dropped or failed. Routing to Inworld TTS.")
            if _try_inworld_tts(text):
                return
            print("[SPEAKER] Network paths fully exhausted. Deploying local thread-isolated fallback.")
            _speak_pyttsx3_local(text)
            return

        print(
            f"[SPEAKER] Unrecognized PRIMARY_TTS keyword context {primary_raw!r} "
            "(expected inworld, google, or pyttsx3), defaulting directly to local loop fallback bounds."
        )
        _speak_pyttsx3_local(text)


_warm_system_subsystems()
_warm_cloud_clients()


if __name__ == "__main__":
    speak("System audio test. Speaker operational.")
