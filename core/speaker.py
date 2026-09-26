from __future__ import annotations

import ctypes
import io
import logging
import math
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import wave
import json
from pathlib import Path
from typing import Any, Literal

import psutil
import pygame
import pyttsx3

from core import config
from core.settings import get_settings_store

# Headless SDL so pygame.mixer can initialize without a display.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

_LOGGER = logging.getLogger(__name__)
_SPEAK_LOCK = threading.Lock()
_LIFECYCLE_LOCK = threading.Lock()
_KOKORO_LOCK = threading.Lock()
_KOKORO_SYNTH_LOCK = threading.Lock()
_ACTIVE_ENGINE_LOCK = threading.Lock()
_CANCEL_EVENT = threading.Event()
_CACHED_PLAYBACK_LOCK = threading.Lock()
_CACHED_PLAYBACK_ID: str | None = None
_CACHED_PLAYBACK_EVENT: threading.Event | None = None

_GOOGLE_TTS_CLIENT: Any | None = None
_KOKORO_CLIENT: Any | None = None
_ACTIVE_PYTTSX3_ENGINE: Any | None = None
_INITIALIZED = False
_READINESS: dict[str, dict[str, Any]] = {
    "audio": {"ready": False, "reason": "not_initialized"},
    "google": {"ready": False, "reason": "not_initialized"},
    "kokoro": {"ready": False, "reason": "not_initialized"},
    "pyttsx3": {"ready": True, "reason": None},
}

ResolvedTtsEngine = Literal["google", "kokoro", "pyttsx3"]

KOKORO_RAM_LIMIT = 95.0
KOKORO_CPU_LIMIT = 80.0
KOKORO_CPU_RECOVERY_SECONDS = 3.0
KOKORO_CPU_SAMPLE_SECONDS = 0.1
KOKORO_CPU_STABLE_SAMPLES = 2
TTS_CHUNK_MAX_CHARS = 320
TTS_SYNTHESIS_TIMEOUT_SECONDS = 20.0
MAX_CACHED_AUDIO_CHUNKS = 16
MAX_CACHED_AUDIO_CHUNK_BYTES = 4 * 1024 * 1024
MAX_CACHED_AUDIO_BYTES = 12 * 1024 * 1024
MAX_CACHED_AUDIO_SECONDS = 180.0
_PLAYBACK_POLL_MS = 50

_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_MARKDOWN_HEADER_PATTERN = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MARKDOWN_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_MARKDOWN_ITALIC_PATTERN = re.compile(
    r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)"
)
_MARKDOWN_STRIKE_PATTERN = re.compile(r"~~(.+?)~~")
_MARKDOWN_CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```")
_MARKDOWN_INLINE_CODE_PATTERN = re.compile(r"`([^`]+)`")
_MARKDOWN_BLOCKQUOTE_PATTERN = re.compile(r"^>\s?", re.MULTILINE)
_MARKDOWN_HRULE_PATTERN = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)
_MARKDOWN_LIST_MARKER_PATTERN = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_MARKDOWN_ORDERED_LIST_PATTERN = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?。！？])\s+|\n+")


def _set_readiness(component: str, *, ready: bool, reason: str | None = None) -> None:
    _READINESS[component] = {"ready": ready, "reason": reason}


def readiness_snapshot() -> dict[str, dict[str, Any]]:
    """Return a copy of current speech subsystem readiness state."""
    return {name: dict(status) for name, status in _READINESS.items()}


def _infer_language_code(voice_id: str) -> str:
    parts = voice_id.split("-")
    if len(parts) >= 2 and len(parts[0]) == 2 and len(parts[1]) == 2:
        return f"{parts[0]}-{parts[1]}"
    return "en-US"


def _normalize_voice_gender(gender: str | None) -> str:
    if gender is None:
        return "female"
    return "male" if gender.strip().lower() == "male" else "female"


def _normalize_engine(engine: str | None) -> ResolvedTtsEngine:
    normalized = str(engine or "pyttsx3").strip().lower()
    if normalized == "piper":
        _LOGGER.warning("Piper is deprecated; routing to pyttsx3.")
        return "pyttsx3"
    if normalized in {"google", "kokoro", "pyttsx3"}:
        return normalized  # type: ignore[return-value]
    _LOGGER.warning("Unrecognized TTS engine %r; defaulting to pyttsx3.", engine)
    return "pyttsx3"


def _get_active_kokoro_voice(gender: str) -> str:
    return "am_michael" if gender == "male" else "af_sky"


def _get_active_google_voice(gender: str) -> str:
    return (
        "en-US-Chirp3-HD-Sadachbia"
        if gender == "male"
        else "en-US-Chirp3-HD-Laomedeia"
    )


def prepare_text(text: str) -> str:
    """Convert markdown-like input to normalized Unicode plain text for speech."""
    cleaned = unicodedata.normalize("NFC", str(text or ""))
    replacements = (
        (_MARKDOWN_CODE_BLOCK_PATTERN, " "),
        (_MARKDOWN_IMAGE_PATTERN, r"\1"),
        (_MARKDOWN_LINK_PATTERN, r"\1"),
        (_MARKDOWN_INLINE_CODE_PATTERN, r"\1"),
        (_MARKDOWN_HEADER_PATTERN, ""),
        (_MARKDOWN_BLOCKQUOTE_PATTERN, ""),
        (_MARKDOWN_HRULE_PATTERN, " "),
        (_MARKDOWN_LIST_MARKER_PATTERN, ""),
        (_MARKDOWN_ORDERED_LIST_PATTERN, ""),
        (_MARKDOWN_BOLD_PATTERN, lambda match: match.group(1) or match.group(2) or ""),
        (_MARKDOWN_ITALIC_PATTERN, lambda match: match.group(1) or match.group(2) or ""),
        (_MARKDOWN_STRIKE_PATTERN, r"\1"),
    )
    for pattern, replacement in replacements:
        cleaned = pattern.sub(replacement, cleaned)

    # Preserve valid Unicode (including accents and non-Latin scripts) while
    # removing control/format characters that can confuse speech engines.
    cleaned = "".join(
        char
        for char in cleaned
        if char in "\n\t" or not unicodedata.category(char).startswith("C")
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def _split_hard(text: str, max_chars: int) -> list[str]:
    parts: list[str] = []
    remaining = text.strip()
    while len(remaining) > max_chars:
        split_at = remaining.rfind(" ", 0, max_chars + 1)
        if split_at <= 0:
            split_at = max_chars
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def chunk_text(text: str, *, max_chars: int = TTS_CHUNK_MAX_CHARS) -> list[str]:
    """Split prepared text on sentence boundaries with a hard character cap."""
    prepared = prepare_text(text)
    if not prepared:
        return []

    sentences = [part.strip() for part in _SENTENCE_BOUNDARY_PATTERN.split(prepared) if part.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_hard(sentence, max_chars))
            continue
        candidate = sentence if not current else f"{current} {sentence}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def _kokoro_paths() -> tuple[Path, Path]:
    weights_dir = (config.PROJECT_ROOT / "core" / "weights" / "kokoro").resolve()
    return (
        (weights_dir / "kokoro-v1.0.onnx").resolve(),
        (weights_dir / "voices-v1.0.bin").resolve(),
    )


def _run_with_timeout(function: Any, timeout: float) -> Any:
    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def _runner() -> None:
        try:
            result_queue.put((True, function()))
        except Exception as exc:  # noqa: BLE001
            result_queue.put((False, exc))

    threading.Thread(target=_runner, daemon=True).start()
    try:
        ok, result = result_queue.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError("tts_synthesis_timeout") from exc
    if ok:
        return result
    raise result


def _get_kokoro_client() -> Any:
    global _KOKORO_CLIENT
    if _KOKORO_CLIENT is not None:
        return _KOKORO_CLIENT

    with _KOKORO_LOCK:
        if _KOKORO_CLIENT is not None:
            return _KOKORO_CLIENT
        model_path, voices_path = _kokoro_paths()
        for path in (model_path, voices_path):
            if not path.is_file() or path.stat().st_size <= 0:
                raise FileNotFoundError(f"Kokoro model asset unavailable: {path.name}")
        try:
            from kokoro_onnx import Kokoro
        except ImportError as exc:
            raise ImportError("kokoro-onnx is not installed; install the tts-kokoro extra.") from exc
        _KOKORO_CLIENT = Kokoro(str(model_path), str(voices_path))
        return _KOKORO_CLIENT


def _ensure_kokoro_ready(*, probe: bool) -> bool:
    try:
        client = _get_kokoro_client()
        if probe:
            def _probe() -> Any:
                with _KOKORO_SYNTH_LOCK:
                    return client.create(
                        "ready",
                        voice=_get_active_kokoro_voice("female"),
                        speed=1.0,
                        lang="en-us",
                    )
            samples, sample_rate = _run_with_timeout(_probe, TTS_SYNTHESIS_TIMEOUT_SECONDS)
            if samples is None or len(samples) == 0 or int(sample_rate) <= 0:
                raise ValueError("kokoro_readiness_invalid_audio")
        _set_readiness("kokoro", ready=True, reason=None)
        return True
    except Exception as exc:  # noqa: BLE001
        reason = type(exc).__name__
        _set_readiness("kokoro", ready=False, reason=reason)
        _LOGGER.warning("Kokoro readiness check failed (%s).", reason)
        return False


def _ensure_google_ready() -> bool:
    global _GOOGLE_TTS_CLIENT
    if _GOOGLE_TTS_CLIENT is not None:
        _set_readiness("google", ready=True, reason=None)
        return True
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        _set_readiness("google", ready=False, reason="credentials_missing")
        return False
    try:
        from google.cloud import texttospeech
        _GOOGLE_TTS_CLIENT = texttospeech.TextToSpeechClient()
        _set_readiness("google", ready=True, reason=None)
        return True
    except Exception as exc:  # noqa: BLE001
        _GOOGLE_TTS_CLIENT = None
        reason = type(exc).__name__
        _set_readiness("google", ready=False, reason=reason)
        _LOGGER.warning("Google TTS readiness check failed (%s).", reason)
        return False


def initialize() -> dict[str, dict[str, Any]]:
    """Initialize audio and the configured optional speech engine during app startup."""
    global _INITIALIZED
    with _LIFECYCLE_LOCK:
        if _INITIALIZED:
            return readiness_snapshot()
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init()
            _set_readiness("audio", ready=True, reason=None)
        except Exception as exc:  # noqa: BLE001
            _set_readiness("audio", ready=False, reason=type(exc).__name__)
            _LOGGER.warning("Audio mixer initialization failed (%s).", type(exc).__name__)

        try:
            snapshot = get_settings_store().get_snapshot()
            configured = snapshot.voice.engine
        except Exception:  # noqa: BLE001
            configured = "pyttsx3"
        dev_engine = getattr(config, "DEV_TTS_PLAYBACK", "pyttsx3")
        selected = {_normalize_engine(configured)}
        if config.is_dev_mode():
            selected.add(_normalize_engine(dev_engine))

        if "google" in selected:
            _ensure_google_ready()
        if "kokoro" in selected:
            _ensure_kokoro_ready(probe=True)

        _INITIALIZED = True
        _LOGGER.info("Speech subsystem initialized: %s", readiness_snapshot())
        return readiness_snapshot()


def cancel() -> None:
    """Cancel active playback and suppress queued chunks."""
    _CANCEL_EVENT.set()
    with _CACHED_PLAYBACK_LOCK:
        cached_event = _CACHED_PLAYBACK_EVENT
        if cached_event is not None:
            cached_event.set()
    try:
        if pygame.mixer.get_init() is not None:
            pygame.mixer.music.stop()
    except Exception:  # noqa: BLE001
        pass
    with _ACTIVE_ENGINE_LOCK:
        engine = _ACTIVE_PYTTSX3_ENGINE
    if engine is not None:
        try:
            engine.stop()
        except Exception:  # noqa: BLE001
            pass


def shutdown() -> None:
    """Stop playback and release speech runtime resources."""
    global _INITIALIZED, _GOOGLE_TTS_CLIENT, _KOKORO_CLIENT, _ACTIVE_PYTTSX3_ENGINE
    with _LIFECYCLE_LOCK:
        cancel()
        with _ACTIVE_ENGINE_LOCK:
            _ACTIVE_PYTTSX3_ENGINE = None
        _GOOGLE_TTS_CLIENT = None
        _KOKORO_CLIENT = None
        try:
            if pygame.mixer.get_init() is not None:
                pygame.mixer.quit()
        except Exception:  # noqa: BLE001
            pass
        _INITIALIZED = False
        _set_readiness("audio", ready=False, reason="shutdown")
        _set_readiness("google", ready=False, reason="shutdown")
        _set_readiness("kokoro", ready=False, reason="shutdown")


def _kokoro_pressure_snapshot() -> tuple[float, float]:
    try:
        ram = float(psutil.virtual_memory().percent)
    except (OSError, AttributeError, TypeError, ValueError):
        ram = 0.0
    try:
        cpu = float(psutil.cpu_percent(interval=None))
    except (OSError, AttributeError, TypeError, ValueError):
        cpu = 0.0
    return ram, cpu


def _admit_kokoro() -> tuple[bool, str | None, bool]:
    """Apply Kokoro-specific RAM gate and bounded CPU recovery policy."""
    try:
        ram = float(psutil.virtual_memory().percent)
    except (OSError, AttributeError, TypeError, ValueError):
        ram = 0.0
    if ram >= KOKORO_RAM_LIMIT:
        _LOGGER.info("Kokoro blocked by RAM pressure (%.1f%% >= %.1f%%).", ram, KOKORO_RAM_LIMIT)
        return False, "kokoro_ram_pressure", True

    deadline = time.monotonic() + KOKORO_CPU_RECOVERY_SECONDS
    stable = 0
    saw_pressure = False
    while True:
        if _CANCEL_EVENT.is_set():
            return False, "speech_cancelled", saw_pressure
        try:
            cpu = float(psutil.cpu_percent(interval=KOKORO_CPU_SAMPLE_SECONDS))
        except (OSError, AttributeError, TypeError, ValueError):
            return True, None, saw_pressure
        if cpu <= KOKORO_CPU_LIMIT:
            stable += 1
            if stable >= KOKORO_CPU_STABLE_SAMPLES:
                return True, None, saw_pressure
        else:
            stable = 0
            saw_pressure = True
        if time.monotonic() >= deadline:
            _LOGGER.info("Kokoro CPU recovery timed out above %.1f%%.", KOKORO_CPU_LIMIT)
            return False, "kokoro_cpu_timeout", True


def resolve_tts_diagnostics(*, dev_mode: bool, configured_tts: str) -> tuple[str, bool]:
    """Resolve requested engine and report current speech-specific load pressure."""
    engine = _normalize_engine(configured_tts)
    if engine != "kokoro":
        return engine, False
    ram, cpu = _kokoro_pressure_snapshot()
    return engine, ram >= KOKORO_RAM_LIMIT or cpu > KOKORO_CPU_LIMIT


def _pack_pcm_to_wav_bytes(pcm_data: bytes, sample_rate: int) -> bytes:
    if not pcm_data or int(sample_rate) <= 0:
        raise ValueError("invalid_kokoro_audio")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(int(sample_rate))
        wav_file.writeframes(pcm_data)
    return buffer.getvalue()


def fetch_google_audio(text: str, voice_id: str) -> bytes:
    """Synthesize one text chunk to MP3 bytes with an explicit timeout."""
    if not _ensure_google_ready() or _GOOGLE_TTS_CLIENT is None:
        raise RuntimeError("google_tts_not_ready")
    from google.cloud import texttospeech

    response = _GOOGLE_TTS_CLIENT.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(
            language_code=_infer_language_code(voice_id),
            name=voice_id,
        ),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
        ),
        timeout=TTS_SYNTHESIS_TIMEOUT_SECONDS,
    )
    audio = bytes(response.audio_content or b"")
    if not audio:
        raise ValueError("empty_google_audio")
    return audio


def _synthesize_kokoro_chunk(text: str, *, gender: str) -> bytes:
    if not _ensure_kokoro_ready(probe=False):
        raise RuntimeError("kokoro_not_ready")
    client = _get_kokoro_client()

    def _create() -> Any:
        with _KOKORO_SYNTH_LOCK:
            return client.create(
                text,
                voice=_get_active_kokoro_voice(gender),
                speed=1.0,
                lang="en-us",
            )

    samples, sample_rate = _run_with_timeout(_create, TTS_SYNTHESIS_TIMEOUT_SECONDS)
    if samples is None or len(samples) == 0 or int(sample_rate) <= 0:
        raise ValueError("invalid_kokoro_audio")
    try:
        import numpy as np
    except ImportError as exc:
        raise ImportError("numpy is not installed; install the tts-kokoro extra.") from exc
    pcm_data = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
    return _pack_pcm_to_wav_bytes(pcm_data, int(sample_rate))


def _mp3_duration_seconds(data: bytes) -> float:
    """Read MPEG audio frame headers without trusting provider metadata."""
    offset = 0
    if data.startswith(b"ID3") and len(data) >= 10:
        size_bytes = data[6:10]
        if any(byte & 0x80 for byte in size_bytes):
            raise ValueError("invalid_mp3_header")
        tag_size = (
            (size_bytes[0] << 21)
            | (size_bytes[1] << 14)
            | (size_bytes[2] << 7)
            | size_bytes[3]
        )
        offset = min(len(data), 10 + tag_size)
    frame_count = 0
    duration = 0.0
    while offset + 4 <= len(data):
        header = int.from_bytes(data[offset:offset + 4], "big")
        if (header >> 21) != 0x7FF:
            offset += 1
            continue
        version = (header >> 19) & 0b11
        layer = (header >> 17) & 0b11
        bitrate_index = (header >> 12) & 0b1111
        sample_index = (header >> 10) & 0b11
        if version == 1 or layer != 1 or bitrate_index in {0, 15} or sample_index == 3:
            offset += 1
            continue
        mpeg1_bitrates = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
        mpeg2_bitrates = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
        rates = (44100, 48000, 32000)
        sample_rate = rates[sample_index]
        if version == 2:
            sample_rate //= 2
        elif version == 0:
            sample_rate //= 4
        bitrate = (mpeg1_bitrates if version == 3 else mpeg2_bitrates)[bitrate_index]
        padding = (header >> 9) & 1
        frame_bytes = (144000 if version == 3 else 72000) * bitrate // sample_rate + padding
        if frame_bytes < 4 or offset + frame_bytes > len(data):
            offset += 1
            continue
        frame_count += 1
        duration += (1152 if version == 3 else 576) / sample_rate
        offset += frame_bytes
    if frame_count == 0 or not duration:
        raise ValueError("invalid_mp3_audio")
    return duration


def _audio_duration_seconds(data: bytes, content_type: str) -> float:
    if content_type == "audio/wav":
        with wave.open(io.BytesIO(data), "rb") as wav_file:
            rate = wav_file.getframerate()
            if rate <= 0:
                raise ValueError("invalid_wav_audio")
            return wav_file.getnframes() / rate
    if content_type == "audio/mpeg":
        return _mp3_duration_seconds(data)
    raise ValueError("unsupported_audio_type")


def _synthesize_pyttsx3_wav(
    text: str,
    *,
    gender: str,
    cancellation_event: threading.Event,
) -> bytes:
    with tempfile.TemporaryDirectory(prefix="apex-speech-") as directory:
        output_path = os.path.join(directory, "speech.wav")
        process = subprocess.Popen(
            [sys.executable, "-m", "core.speaker_export", output_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        payload = json.dumps({"text": text, "gender": gender}).encode("utf-8")
        deadline = time.monotonic() + TTS_SYNTHESIS_TIMEOUT_SECONDS
        try:
            input_bytes: bytes | None = payload
            while process.poll() is None:
                if cancellation_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=1.0)
                    raise RuntimeError("speech_cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    process.wait(timeout=1.0)
                    raise TimeoutError("pyttsx3_synthesis_timeout")
                try:
                    process.communicate(input=input_bytes, timeout=min(0.1, remaining))
                    input_bytes = None
                except subprocess.TimeoutExpired:
                    input_bytes = None
            if process.returncode != 0:
                raise RuntimeError("pyttsx3_synthesis_failed")
            with open(output_path, "rb") as audio_file:
                audio = audio_file.read(MAX_CACHED_AUDIO_CHUNK_BYTES + 1)
            if not audio or len(audio) > MAX_CACHED_AUDIO_CHUNK_BYTES:
                raise ValueError("pyttsx3_audio_size_invalid")
            return audio
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=1.0)


def _admit_kokoro_for_event(cancellation_event: threading.Event) -> tuple[bool, str | None]:
    try:
        ram = float(psutil.virtual_memory().percent)
    except (OSError, AttributeError, TypeError, ValueError):
        ram = 0.0
    if ram >= KOKORO_RAM_LIMIT:
        return False, "kokoro_ram_pressure"
    deadline = time.monotonic() + KOKORO_CPU_RECOVERY_SECONDS
    stable = 0
    while True:
        if cancellation_event.is_set():
            return False, "speech_cancelled"
        try:
            cpu = float(psutil.cpu_percent(interval=KOKORO_CPU_SAMPLE_SECONDS))
        except (OSError, AttributeError, TypeError, ValueError):
            return True, None
        if cpu <= KOKORO_CPU_LIMIT:
            stable += 1
            if stable >= KOKORO_CPU_STABLE_SAMPLES:
                return True, None
        else:
            stable = 0
        if time.monotonic() >= deadline:
            return False, "kokoro_cpu_timeout"


def synthesize_audio(
    text: str,
    *,
    tts_override: str,
    voice_gender: str,
    cancellation_event: threading.Event,
) -> tuple[list[dict[str, Any]], ResolvedTtsEngine]:
    """Prepare ordered, independently playable audio chunks without starting playback."""
    prepared = prepare_text(text)
    if not prepared:
        raise ValueError("speech_text_empty")
    chunks = chunk_text(prepared)
    if not chunks or len(chunks) > MAX_CACHED_AUDIO_CHUNKS:
        raise ValueError("speech_audio_chunk_count_invalid")
    gender = _normalize_voice_gender(voice_gender)
    selected = _normalize_engine(tts_override)

    def synthesize_all(engine: ResolvedTtsEngine) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        total_bytes = 0
        total_duration = 0.0
        for chunk in chunks:
            if cancellation_event.is_set():
                raise RuntimeError("speech_cancelled")
            if engine == "google":
                data = fetch_google_audio(chunk, _get_active_google_voice(gender))
                content_type = "audio/mpeg"
            elif engine == "kokoro":
                data = _synthesize_kokoro_chunk(chunk, gender=gender)
                content_type = "audio/wav"
            else:
                data = _synthesize_pyttsx3_wav(
                    chunk,
                    gender=gender,
                    cancellation_event=cancellation_event,
                )
                content_type = "audio/wav"
            if cancellation_event.is_set():
                raise RuntimeError("speech_cancelled")
            if not data or len(data) > MAX_CACHED_AUDIO_CHUNK_BYTES:
                raise ValueError("speech_audio_chunk_size_invalid")
            duration = _audio_duration_seconds(data, content_type)
            if not 0 < duration <= 60:
                raise ValueError("speech_audio_chunk_duration_invalid")
            total_bytes += len(data)
            total_duration += duration
            if total_bytes > MAX_CACHED_AUDIO_BYTES or total_duration > MAX_CACHED_AUDIO_SECONDS:
                raise ValueError("speech_audio_bundle_limit_exceeded")
            result.append({
                "audio": data,
                "content_type": content_type,
                "engine": engine,
                "duration_seconds": duration,
            })
        return result

    if selected == "kokoro":
        admitted, reason = _admit_kokoro_for_event(cancellation_event)
        if not admitted:
            if cancellation_event.is_set():
                raise RuntimeError("speech_cancelled")
            _LOGGER.info("Kokoro unavailable for saved speech (%s); using local pyttsx3.", reason)
            selected = "pyttsx3"
    try:
        return synthesize_all(selected), selected
    except Exception:
        if cancellation_event.is_set() or selected == "pyttsx3":
            raise
        # Cached speech follows legacy fallback rules. Kokoro never escalates to cloud TTS.
        _LOGGER.info("Saved speech engine %s failed; falling back to local pyttsx3.", selected)
        return synthesize_all("pyttsx3"), "pyttsx3"


def _play_cached_audio_bytes(
    data: bytes,
    cancellation_event: threading.Event,
    *,
    deadline: float,
) -> None:
    if not data:
        raise ValueError("empty_audio")
    if cancellation_event.is_set():
        raise RuntimeError("speech_cancelled")
    if pygame.mixer.get_init() is None:
        raise RuntimeError("audio_not_ready")
    if time.monotonic() >= deadline:
        raise TimeoutError("cached_audio_playback_timeout")
    stream = io.BytesIO(data)
    pygame.mixer.music.load(stream)
    pygame.mixer.music.play()
    try:
        while pygame.mixer.music.get_busy():
            if cancellation_event.is_set():
                pygame.mixer.music.stop()
                raise RuntimeError("speech_cancelled")
            if time.monotonic() >= deadline:
                raise TimeoutError("cached_audio_playback_timeout")
            pygame.time.wait(_PLAYBACK_POLL_MS)
        if cancellation_event.is_set():
            raise RuntimeError("speech_cancelled")
    finally:
        pygame.mixer.music.stop()
        unload = getattr(pygame.mixer.music, "unload", None)
        if callable(unload):
            unload()


def try_play_cached_audio(
    chunks: list[dict[str, Any]],
    *,
    playback_id: str,
    cancellation_event: threading.Event,
) -> bool:
    """Play cached chunks serially under one shared speaker lock."""
    global _CACHED_PLAYBACK_ID, _CACHED_PLAYBACK_EVENT
    if not chunks:
        return False
    if len(chunks) > MAX_CACHED_AUDIO_CHUNKS:
        raise ValueError("cached_audio_chunk_count_invalid")
    if not _SPEAK_LOCK.acquire(blocking=False):
        return False
    try:
        playable: list[tuple[bytes, float]] = []
        total_bytes = 0
        total_duration = 0.0
        for chunk in chunks:
            content_type = chunk.get("content_type")
            audio = chunk.get("audio")
            duration = chunk.get("duration_seconds")
            if content_type not in {"audio/mpeg", "audio/wav"} or not isinstance(audio, bytes):
                raise ValueError("cached_audio_chunk_invalid")
            if (
                not isinstance(duration, (int, float))
                or not math.isfinite(float(duration))
                or not 0 < float(duration) <= 60
            ):
                raise ValueError("cached_audio_duration_invalid")
            total_duration += float(duration)
            total_bytes += len(audio)
            if len(audio) > MAX_CACHED_AUDIO_CHUNK_BYTES:
                raise ValueError("cached_audio_chunk_limit_exceeded")
            if (
                total_bytes > MAX_CACHED_AUDIO_BYTES
                or total_duration > MAX_CACHED_AUDIO_SECONDS
            ):
                raise ValueError("cached_audio_bundle_limit_exceeded")
            playable.append((audio, float(duration)))
        started_at = time.monotonic()
        playback_budget = min(
            (total_duration * 2) + (len(playable) * 5),
            (MAX_CACHED_AUDIO_SECONDS * 2) + (MAX_CACHED_AUDIO_CHUNKS * 5),
        )
        playback_deadline = started_at + playback_budget
        with _CACHED_PLAYBACK_LOCK:
            if cancellation_event.is_set():
                return False
            _CACHED_PLAYBACK_ID = playback_id
            _CACHED_PLAYBACK_EVENT = cancellation_event
        for audio, duration in playable:
            if cancellation_event.is_set():
                raise RuntimeError("speech_cancelled")
            chunk_deadline = min(
                playback_deadline,
                time.monotonic() + (duration * 2) + 5,
            )
            _play_cached_audio_bytes(
                audio,
                cancellation_event,
                deadline=chunk_deadline,
            )
        return True
    finally:
        with _CACHED_PLAYBACK_LOCK:
            if _CACHED_PLAYBACK_ID == playback_id:
                _CACHED_PLAYBACK_ID = None
                _CACHED_PLAYBACK_EVENT = None
        _SPEAK_LOCK.release()


def cancel_cached_audio(playback_id: str) -> bool:
    """Cancel only the cached playback owned by ``playback_id``."""
    with _CACHED_PLAYBACK_LOCK:
        if _CACHED_PLAYBACK_ID != playback_id or _CACHED_PLAYBACK_EVENT is None:
            return False
        _CACHED_PLAYBACK_EVENT.set()
        try:
            if pygame.mixer.get_init() is not None:
                pygame.mixer.music.stop()
        except Exception:  # noqa: BLE001
            pass
        return True


def _synthesize_chunk(engine: ResolvedTtsEngine, text: str, *, gender: str) -> bytes:
    if _CANCEL_EVENT.is_set():
        raise RuntimeError("speech_cancelled")
    if engine == "google":
        return fetch_google_audio(text, _get_active_google_voice(gender))
    if engine == "kokoro":
        return _synthesize_kokoro_chunk(text, gender=gender)
    raise ValueError("pyttsx3_does_not_return_audio_bytes")


def _play_audio_bytes(data: bytes) -> None:
    if not data:
        raise ValueError("empty_audio")
    if _CANCEL_EVENT.is_set():
        raise RuntimeError("speech_cancelled")
    if pygame.mixer.get_init() is None:
        raise RuntimeError("audio_not_ready")

    stream = io.BytesIO(data)
    pygame.mixer.music.load(stream)
    pygame.mixer.music.play()
    try:
        while pygame.mixer.music.get_busy():
            if _CANCEL_EVENT.is_set():
                pygame.mixer.music.stop()
                raise RuntimeError("speech_cancelled")
            pygame.time.wait(_PLAYBACK_POLL_MS)
        if _CANCEL_EVENT.is_set():
            raise RuntimeError("speech_cancelled")
    finally:
        pygame.mixer.music.stop()
        unload = getattr(pygame.mixer.music, "unload", None)
        if callable(unload):
            unload()


def _speak_pyttsx3_local(text: str, *, gender: str) -> bool:
    global _ACTIVE_PYTTSX3_ENGINE
    if _CANCEL_EVENT.is_set():
        return False
    if os.name == "nt":
        try:
            ctypes.windll.ole32.CoInitialize(None)
        except OSError:
            pass

    try:
        engine = pyttsx3.init()
        with _ACTIVE_ENGINE_LOCK:
            _ACTIVE_PYTTSX3_ENGINE = engine
        engine.setProperty("rate", 175)
        voices = engine.getProperty("voices")
        if voices:
            selected_id = None
            for voice in voices:
                name = (getattr(voice, "name", "") or "").lower()
                voice_id = (getattr(voice, "id", "") or "").lower()
                voice_gender = (getattr(voice, "gender", "") or "").lower()
                terms = (name, voice_id, voice_gender)
                if gender == "male" and any("david" in term or "male" in term for term in terms):
                    selected_id = voice.id
                    break
                if gender != "male" and any("zira" in term or "female" in term for term in terms):
                    selected_id = voice.id
                    break
            engine.setProperty("voice", selected_id or voices[0].id)
        engine.say(text)
        engine.runAndWait()
        return not _CANCEL_EVENT.is_set()
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Local pyttsx3 playback failed (%s).", type(exc).__name__)
        return False
    finally:
        with _ACTIVE_ENGINE_LOCK:
            _ACTIVE_PYTTSX3_ENGINE = None


def _speak_streamed(engine: ResolvedTtsEngine, chunks: list[str], *, gender: str) -> bool:
    """Synthesize one chunk ahead while the current chunk is playing."""
    if not chunks:
        return False
    first_audio = _synthesize_chunk(engine, chunks[0], gender=gender)
    if len(chunks) == 1:
        _play_audio_bytes(first_audio)
        return True

    audio_queue: queue.Queue[tuple[int, bytes | None, BaseException | None]] = queue.Queue(maxsize=1)

    def _producer() -> None:
        for index, chunk in enumerate(chunks[1:], start=1):
            if _CANCEL_EVENT.is_set():
                return
            try:
                audio = _synthesize_chunk(engine, chunk, gender=gender)
                audio_queue.put((index, audio, None))
            except BaseException as exc:  # noqa: BLE001
                audio_queue.put((index, None, exc))
                return

    producer = threading.Thread(target=_producer, daemon=True)
    producer.start()
    _play_audio_bytes(first_audio)

    for expected_index in range(1, len(chunks)):
        if _CANCEL_EVENT.is_set():
            raise RuntimeError("speech_cancelled")
        index, audio, error = audio_queue.get(timeout=TTS_SYNTHESIS_TIMEOUT_SECONDS + 1.0)
        if index != expected_index:
            raise RuntimeError("tts_chunk_order_error")
        if error is not None:
            raise error
        if not audio:
            raise ValueError("empty_audio")
        _play_audio_bytes(audio)
    return True


def is_speaking() -> bool:
    if _SPEAK_LOCK.locked():
        return True
    try:
        return pygame.mixer.get_init() is not None and pygame.mixer.music.get_busy()
    except Exception:  # noqa: BLE001
        return False


def _route_tts_playback(text: str, tts_strategy: str, *, gender: str) -> ResolvedTtsEngine | None:
    engine = _normalize_engine(tts_strategy)
    if engine == "pyttsx3":
        return "pyttsx3" if _speak_pyttsx3_local(text, gender=gender) else None

    if engine == "kokoro":
        admitted, reason, _throttled = _admit_kokoro()
        if not admitted:
            _LOGGER.info("Kokoro unavailable for this request (%s); using local pyttsx3.", reason)
            return "pyttsx3" if _speak_pyttsx3_local(text, gender=gender) else None

    chunks = chunk_text(text)
    try:
        if _speak_streamed(engine, chunks, gender=gender):
            return engine
    except Exception as exc:  # noqa: BLE001
        if _CANCEL_EVENT.is_set() or str(exc) == "speech_cancelled":
            _LOGGER.info("Speech playback cancelled.")
            return None
        _LOGGER.warning(
            "%s TTS failed (%s); falling back locally to pyttsx3.",
            engine,
            type(exc).__name__,
        )

    # Privacy boundary: a local Kokoro request never escalates to cloud TTS.
    return "pyttsx3" if _speak_pyttsx3_local(text, gender=gender) else None


def _deliver_speech(
    text: str,
    *,
    tts_override: str | None = None,
    voice_gender: str | None = None,
) -> ResolvedTtsEngine | None:
    prepared = prepare_text(text)
    if not prepared:
        raise ValueError("speech_text_empty")
    _CANCEL_EVENT.clear()

    snapshot = get_settings_store().get_snapshot()
    gender = _normalize_voice_gender(
        voice_gender if voice_gender is not None else snapshot.voice.gender
    )
    if tts_override is not None:
        strategy = tts_override
    elif config.is_dev_mode():
        strategy = config.DEV_TTS_PLAYBACK
    else:
        strategy = snapshot.voice.engine
    _LOGGER.info("Speak request received (chars=%s, engine=%s).", len(prepared), strategy)
    return _route_tts_playback(prepared, strategy, gender=gender)


def speak(
    text: str,
    *,
    tts_override: str | None = None,
    voice_gender: str | None = None,
) -> ResolvedTtsEngine:
    """Speak text using centralized preparation, admission, fallback, and playback."""
    with _SPEAK_LOCK:
        resolved = _deliver_speech(
            text,
            tts_override=tts_override,
            voice_gender=voice_gender,
        )
        if resolved is None:
            raise RuntimeError("speech_delivery_failed")
        return resolved


def try_speak(
    text: str,
    *,
    tts_override: str | None = None,
    voice_gender: str | None = None,
) -> ResolvedTtsEngine | None:
    """Attempt speech without blocking when another delivery owns the speech lock."""
    if not _SPEAK_LOCK.acquire(blocking=False):
        return None
    try:
        resolved = _deliver_speech(
            text,
            tts_override=tts_override,
            voice_gender=voice_gender,
        )
        if resolved is None:
            raise RuntimeError("speech_delivery_failed")
        return resolved
    finally:
        _SPEAK_LOCK.release()


if __name__ == "__main__":
    initialize()
    try:
        speak("System audio test. Speaker operational.")
    finally:
        shutdown()
