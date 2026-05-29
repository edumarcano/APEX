from __future__ import annotations

import ctypes
import io
import os
import threading
from typing import Any

# Headless SDL so pygame.mixer can init without a display
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pyttsx3
from dotenv import load_dotenv

from core import config

load_dotenv(dotenv_path=config.ENV_PATH)

_SPEAK_LOCK = threading.Lock()
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
        print("[SPEAKER] Cloud Text-to-Speech Client pre-warmed successfully.")
    except Exception as exc:  # noqa: BLE001
        print(f"[SPEAKER] Google TTS client pre-warm bypassed or failed ({type(exc).__name__}).")
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


def speak(text: str) -> None:
    """Speak text parameters using pre-warmed cloud structures, defaulting to dynamic local thread loops.

    Protects and linearizes all executing threads via a universal lock block to guarantee
    thread-safe audio routing across asynchronous invocation checkpoints.
    """
    with _SPEAK_LOCK:
        print(f"[SPEAKER] Speak request received (chars={len(text)}).")

        if config.is_dev_mode():
            dev_tts = config.DEV_TTS_PLAYBACK
            print(f"[SPEAKER] DEV_MODE active; DEV_TTS_PLAYBACK routing vector is {dev_tts!r}.")

            if dev_tts == "pyttsx3":
                print("[SPEAKER] DEV_TTS_PLAYBACK is pyttsx3; routing directly to local execution.")
                _speak_pyttsx3_local(text)
                return

            if dev_tts == "google":
                print(
                    "[SPEAKER] DEV_TTS_PLAYBACK is google; network leakage warning — "
                    "falling through to live cloud Google TTS client API."
                )
            elif dev_tts == "elevenlabs":
                # TODO: APEX-V1.7.0 — Deploy ElevenLabs engine streaming pipeline with free tier monthly limits.
                print(
                    "[SPEAKER] DEV_TTS_PLAYBACK is elevenlabs; "
                    "placeholder routing — ElevenLabs pipeline not yet deployed."
                )
                return

        primary_raw = getattr(config, "PRIMARY_TTS", "pyttsx3")
        primary = str(primary_raw).strip().lower()

        print(f"[SPEAKER] Configured PRIMARY_TTS routing vector is {primary_raw!r}.")

        if primary == "pyttsx3":
            print("[SPEAKER] PRIMARY_TTS is pyttsx3, bypassing network paths, routing directly to local execution.")
            _speak_pyttsx3_local(text)
            return

        if primary == "google":
            print("[SPEAKER] Cloud priority sequence active: Google -> pyttsx3 offline fallback.")
            if _try_google_tts(text):
                return
            print("[SPEAKER] Network paths fully exhausted. Deploying local thread-isolated fallback.")
            _speak_pyttsx3_local(text)
            return

        print(
            f"[SPEAKER] Unrecognized PRIMARY_TTS keyword context {primary_raw!r} "
            "(expected google or pyttsx3), defaulting directly to local loop fallback bounds."
        )
        _speak_pyttsx3_local(text)


_warm_system_subsystems()
_warm_cloud_clients()


if __name__ == "__main__":
    speak("System audio test. Speaker operational.")
