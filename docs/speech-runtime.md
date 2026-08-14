# Speech Runtime

APEX manages speech through `core.speaker`. It prepares text, chooses the engine, handles fallback, splits long text, plays audio, supports cancellation, and reports whether speech is ready. FastAPI starts the speech runtime during application startup and releases it during shutdown; importing `core.speaker` does not load Kokoro or initialize cloud TTS.

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

If an optional engine is missing its package, credentials, or local model files, APEX still starts. Speech reports that engine as unavailable and uses the local fallback when speech is requested.

## Engine behavior

| Requested engine | Primary synthesis | Failure fallback |
|---|---|---|
| Google | Google Cloud TTS | local pyttsx3 |
| Kokoro | local Kokoro ONNX | local pyttsx3 |
| pyttsx3 | local pyttsx3 | delivery failure |

Kokoro stays local. If Kokoro is unavailable or fails during preparation, synthesis, or playback, APEX falls back to pyttsx3 and never sends the text to Google Cloud TTS.

## Long-text delivery

Google and Kokoro input is normalized to Unicode plain text and split at sentence boundaries. Very long sentences are split again at a fixed size limit. Valid accented and non-Latin characters are preserved.

APEX synthesizes one chunk ahead of playback. The first chunk starts playing while the next one is generated, and the queue stays small so a long briefing does not need all of its audio in memory before playback begins.

## Kokoro resource checks

Kokoro has its own CPU and memory checks:

- RAM at or above 95% causes an immediate fallback to pyttsx3.
- CPU above 80% may be temporary, so APEX waits briefly and requires stable samples at or below the threshold before starting Kokoro.
- If CPU pressure remains high through that window, APEX falls back to pyttsx3.

These checks are separate from the general system scanner and avoid rejecting Kokoro just because briefing generation ended with a short CPU spike.

## Readiness and cancellation

Startup readiness tracks audio mixer initialization and the selected optional engine. Kokoro checks its model and voice files, loads the model, and runs a small synthesis probe. Google checks its credentials, package availability, and client setup.

An unavailable optional speech engine does not make the whole API unavailable. `/api/v1/health/ready` continues to represent the core application rather than every optional speech provider.

The speaker also owns cancellation during shutdown. It stops active mixer playback, attempts to stop pyttsx3, prevents queued chunks from continuing, and ignores late synthesis results. A user-facing stop control is outside the current speech runtime.
