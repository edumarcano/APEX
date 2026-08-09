# Speech Runtime

APEX treats speech delivery as an application-owned runtime subsystem. `core.speaker` owns text preparation, engine selection, resource admission, fallback, chunking, synthesis, playback, cancellation, and readiness. FastAPI initializes the subsystem during application startup and releases it during shutdown; importing `core.speaker` does not load Kokoro or initialize cloud TTS.

## Installation

The base APEX install includes `pygame-ce` and `pyttsx3`, so an offline fallback remains available without optional speech packages.

Google Cloud TTS and Kokoro are optional extras:

```powershell
uv sync --extra tts-google
uv sync --extra tts-kokoro
```

Install both optional speech engines with:

```powershell
uv sync --all-extras
```

Selecting an engine whose optional dependency, credentials, or local model assets are unavailable does not prevent APEX from starting. The speech subsystem records a degraded readiness reason and falls back locally when delivery is requested.

## Engine behavior

| Requested engine | Primary synthesis | Failure fallback |
|---|---|---|
| Google | Google Cloud TTS | local pyttsx3 |
| Kokoro | local Kokoro ONNX | local pyttsx3 |
| pyttsx3 | local pyttsx3 | delivery failure |

Kokoro is a strict local privacy boundary. A Kokoro request never escalates to Google Cloud TTS if local readiness, resource admission, synthesis, or playback fails.

## Long-text delivery

Google and Kokoro input is normalized to Unicode plain text and split on sentence boundaries with a bounded hard fallback for unusually long sentences. Valid accented and non-Latin characters are preserved.

Speech is synthesized one chunk ahead of playback: the first chunk is synthesized and begins playing while the next chunk is generated. The queue remains bounded so a long briefing does not require the full audio result to exist in memory before playback begins.

## Kokoro resource admission

Kokoro uses speech-specific admission rather than the generic APEX system-throttle boolean:

- RAM at or above 90% causes an immediate local pyttsx3 fallback.
- CPU above 80% is treated as potentially transient. APEX waits for a short bounded recovery window and requires stable samples at or below the threshold before starting Kokoro.
- Sustained CPU pressure through the recovery window falls back to local pyttsx3.

This policy leaves the project-wide scanner thresholds unchanged and avoids rejecting Kokoro solely because briefing synthesis ended on a short CPU spike.

## Readiness and cancellation

Startup readiness tracks audio mixer initialization and the selected optional engine. Kokoro readiness checks model and voice assets, model loading, and a small synthesis probe. Google readiness checks credentials, package availability, and client construction.

Optional-engine readiness is degraded state, not global API unavailability. `/api/v1/health/ready` continues to represent the core application rather than requiring every optional speech provider.

The speaker subsystem also owns an internal cancellation event. Shutdown stops active mixer playback, attempts to stop active pyttsx3 playback, prevents queued chunks from continuing, and discards late synthesis results. A user-facing stop control is intentionally outside this runtime change.
