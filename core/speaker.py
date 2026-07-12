from __future__ import annotations

import ctypes
import io
import os
import threading
import wave

from typing import Any

try:
    from kokoro_onnx import Kokoro
except ImportError:
    Kokoro = None  # type: ignore[misc, assignment]

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

# Headless SDL so pygame.mixer can init without a display
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pyttsx3
from dotenv import load_dotenv

from core import config
from core.settings import get_settings_store

load_dotenv(dotenv_path=config.ENV_PATH)

_SPEAK_LOCK = threading.Lock()
_KOKORO_LOCK = threading.Lock()
_GOOGLE_TTS_CLIENT: Any | None = None
_KOKORO_CLIENT: Kokoro | None = None


def _infer_language_code(voice_id: str) -> str:
    """Derive BCP-47 language code from a Google voice name."""
    parts = voice_id.split("-")
    if len(parts) >= 2 and len(parts[0]) == 2 and len(parts[1]) == 2:
        return f"{parts[0]}-{parts[1]}"
    return "en-US"


def _normalize_voice_gender(gender: str | None) -> str:
    """Return a normalized male/female gender string."""
    if gender is None:
        return "female"
    normalized = gender.strip().lower()
    return "male" if normalized == "male" else "female"


def _get_active_kokoro_voice(gender: str) -> str:
    return "am_michael" if gender == "male" else "af_sky"


def _get_active_google_voice(gender: str) -> str:
    return (
        "en-US-Chirp3-HD-Sadachbia"
        if gender == "male"
        else "en-US-Chirp3-HD-Laomedeia"
    )


def _warm_system_subsystems() -> None:
    """Initialize and hold the pygame hardware mixer channel at import time."""
    try:
        pygame.mixer.init()
        print("[SPEAKER] Pygame hardware mixer channel pre-warmed successfully.")
    except Exception as exc:
        print(f"[SPEAKER] Pygame mixer pre-warm failed ({type(exc).__name__}).")


def _get_kokoro_client() -> Kokoro:
    """Return the thread-safe singleton Kokoro ONNX session."""
    global _KOKORO_CLIENT

    if Kokoro is None:
        raise ImportError("kokoro-onnx is not installed.")

    if _KOKORO_CLIENT is None:
        with _KOKORO_LOCK:
            if _KOKORO_CLIENT is None:
                weights_dir = (config.PROJECT_ROOT / "core" / "weights" / "kokoro").resolve()
                model_path = (weights_dir / "kokoro-v1.0.onnx").resolve()
                voices_path = (weights_dir / "voices-v1.0.bin").resolve()
                _KOKORO_CLIENT = Kokoro(str(model_path), str(voices_path))

    return _KOKORO_CLIENT


def _warm_local_kokoro() -> None:
    """Pre-warm the local Kokoro ONNX client when kokoro is the configured active engine."""
    try:
        primary = get_settings_store().get_snapshot().voice.engine
    except Exception:  # noqa: BLE001
        primary = "pyttsx3"
    dev_tts = str(getattr(config, "DEV_TTS_PLAYBACK", "pyttsx3")).strip().lower()

    if primary != "kokoro" and dev_tts != "kokoro":
        print("[SPEAKER] Local Kokoro ONNX is not selected as active. Skipping background warmup.")
        return

    def _warm() -> None:
        try:
            client = _get_kokoro_client()
            client.create(
                "warm",
                voice=_get_active_kokoro_voice("female"),
                speed=1.0,
                lang="en-us",
            )
            print("[SPEAKER] Local Kokoro ONNX client pre-warmed successfully.")
        except Exception as exc:  # noqa: BLE001
            print(f"[SPEAKER] Kokoro client pre-warm bypassed or failed ({type(exc).__name__}).")

    threading.Thread(target=_warm, daemon=True).start()


def _pack_pcm_to_wav_bytes(pcm_data: bytes, sample_rate: int) -> bytes:
    """Wrap raw 16-bit mono PCM bytes in a standard in-memory WAV container."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)

    return buffer.getvalue()


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


def _speak_kokoro_local(text: str, *, gender: str) -> None:
    """Synthesize and play text via the in-process Kokoro ONNX engine."""
    if np is None:
        raise ImportError("numpy is not installed.")

    client = _get_kokoro_client()
    samples, sample_rate = client.create(
        text,
        voice=_get_active_kokoro_voice(gender),
        speed=1.0,
        lang="en-us",
    )
    pcm_data = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
    wav_bytes = _pack_pcm_to_wav_bytes(pcm_data, sample_rate)
    _play_audio_bytes(wav_bytes)
    print("[SPEAKER] Local Kokoro ONNX playback completed.")


def _speak_pyttsx3_local(text: str, *, gender: str) -> None:
    """Speak text with a thread-local pyttsx3 engine."""
    if os.name == "nt":
        try:
            ctypes.windll.ole32.CoInitialize(None)
        except OSError:
            pass

    print("[SPEAKER] Local pyttsx3 route selected.")
    try:
        engine = pyttsx3.init()
        engine.setProperty("rate", 175)

        voices = engine.getProperty("voices")
        if voices:
            selected_id = None
            for voice in voices:
                name_lower = (getattr(voice, "name", "") or "").lower()
                id_lower = (getattr(voice, "id", "") or "").lower()
                gender_attr = (getattr(voice, "gender", "") or "").lower()

                if gender == "male":
                    if "david" in name_lower or "male" in name_lower or "male" in gender_attr or "david" in id_lower or "male" in id_lower:
                        selected_id = voice.id
                        break
                else:  # female
                    if "zira" in name_lower or "female" in name_lower or "female" in gender_attr or "zira" in id_lower or "female" in id_lower:
                        selected_id = voice.id
                        break

            if selected_id is None:
                selected_id = voices[0].id
            engine.setProperty("voice", selected_id)

        engine.say(text)
        engine.runAndWait()
        print("[SPEAKER] Local pyttsx3 playback completed.")
    except Exception as exc:
        print(f"[SPEAKER] Local pyttsx3 playback failed ({type(exc).__name__}).")


def _try_google_tts(content: str, *, gender: str) -> bool:
    """Return True if Google cloud TTS played successfully."""
    active_voice = _get_active_google_voice(gender)
    if not active_voice.strip():
        print("[SPEAKER] Skipping Google TTS: active_voice is not configured.")
        return False
    print("[SPEAKER] Google Cloud TTS route selected.")
    try:
        audio = fetch_google_audio(content, active_voice)
        _play_audio_bytes(audio)
        print("[SPEAKER] Google Cloud TTS playback completed.")
        return True
    except Exception as exc:  # noqa: BLE001 - broad catch drops execution to the next fallback loop safely
        print(f"[SPEAKER] Google Cloud TTS playback failed ({type(exc).__name__}).")
        return False


def is_speaking() -> bool:
    """Return True when speech is in progress (lock held or mixer active)."""
    if _SPEAK_LOCK.locked():
        return True
    try:
        if pygame.mixer.get_init() is not None and pygame.mixer.music.get_busy():
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _route_tts_playback(text: str, tts_strategy: str, *, gender: str) -> None:
    """Route speech through a safe, low-latency fallback chain keyed by ``tts_strategy``."""
    normalized = tts_strategy.strip().lower()

    if normalized == "piper":
        print(
            "[SPEAKER] WARNING: Piper engine has been deprecated. "
            "Gracefully redirecting to pyttsx3."
        )
        normalized = "pyttsx3"

    if normalized == "google":
        print("[SPEAKER] Routing to Google Cloud TTS client API.")
        if _try_google_tts(text, gender=gender):
            return
        print("[SPEAKER] Google TTS failed; falling back to pyttsx3.")
        _speak_pyttsx3_local(text, gender=gender)
        return

    if normalized == "kokoro":
        print("[SPEAKER] Routing to local Kokoro ONNX engine.")
        try:
            _speak_kokoro_local(text, gender=gender)
        except Exception as exc:  # noqa: BLE001
            print(
                f"[SPEAKER] Local Kokoro ONNX playback failed ({type(exc).__name__}); "
                "falling back to Google Cloud TTS."
            )
            _route_tts_playback(text, "google", gender=gender)
        return

    if normalized == "pyttsx3":
        print("[SPEAKER] Routing directly to local pyttsx3 execution.")
        _speak_pyttsx3_local(text, gender=gender)
        return

    print(
        f"[SPEAKER] Unrecognized TTS strategy {tts_strategy!r}; "
        "defaulting to local pyttsx3."
    )
    _route_tts_playback(text, "pyttsx3", gender=gender)


def speak(
    text: str,
    *,
    tts_override: str | None = None,
    voice_gender: str | None = None,
) -> None:
    """Speak text using bound engine/gender for the duration of this call.

    Protects and linearizes all executing threads via a universal lock block to guarantee
    thread-safe audio routing across asynchronous invocation checkpoints.

    Args:
        text: Plain-text payload for playback.
        tts_override: When set, bypasses DEV_MODE and runtime engine routing for this call.
        voice_gender: When set, binds male/female for this call; otherwise uses the
            runtime settings snapshot captured at speak entry.
    """
    with _SPEAK_LOCK:
        print(f"[SPEAKER] Speak request received (chars={len(text)}).")

        snapshot = get_settings_store().get_snapshot()
        bound_gender = _normalize_voice_gender(
            voice_gender if voice_gender is not None else snapshot.voice.gender
        )

        if tts_override is not None:
            print(f"[SPEAKER] TTS override active; routing vector is {tts_override!r}.")
            _route_tts_playback(text, tts_override, gender=bound_gender)
            return

        if config.is_dev_mode():
            dev_tts = config.DEV_TTS_PLAYBACK
            print(f"[SPEAKER] DEV_MODE active; DEV_TTS_PLAYBACK routing vector is {dev_tts!r}.")
            _route_tts_playback(text, dev_tts, gender=bound_gender)
            return

        primary = snapshot.voice.engine
        print(f"[SPEAKER] Configured PRIMARY_TTS routing vector is {primary!r}.")
        _route_tts_playback(text, primary, gender=bound_gender)


_warm_system_subsystems()
_warm_cloud_clients()
_warm_local_kokoro()


if __name__ == "__main__":
    speak("System audio test. Speaker operational.")
