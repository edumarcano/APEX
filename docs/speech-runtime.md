# Speech Runtime

APEX uses speech for short progress cues, explicit text requests, and highlights from saved briefings. Audio plays on the machine running the backend, through one shared speaker lock. The browser controls delivery but does not receive audio files.

For engine and voice settings, see [Configuration](configuration.md#voice-settings). This guide explains preparation, playback, fallback, and cancellation; the [API reference](api.md#voice) documents the HTTP requests.

## Voice modes and briefing controls

Voice mode determines which speech requests are allowed:

| Mode | Progress cues | Explicit speech and briefing highlights |
|---|---|---|
| Automatic | Best-effort cues for work started in the current page session | Available |
| Manual | Silent | Available |
| Off | Silent | Preparation and playback blocked |

Saved briefings have separate **Prepare**, **Play**, and **Stop** controls. Prepare creates a script and caches its audio. Play uses that cache, and Stop cancels that session's preparation or playback. Highlights never play automatically.

The interface also offers an option to prepare highlights automatically after a newly generated briefing completes. This preference is saved in the browser and works in automatic or manual voice mode. It does not prepare highlights just because a saved session is opened.

## Installation

The base install includes `pygame-ce` for audio playback and `pyttsx3` as the local speech fallback. Working delivery still depends on the host's audio setup and system speech engine.

Google Cloud TTS and Kokoro require optional packages. Choose one extra, or install both together:

```powershell
uv sync --extra tts-google
uv sync --extra tts-kokoro
uv sync --extra tts-google --extra tts-kokoro
```

Google also needs `GOOGLE_APPLICATION_CREDENTIALS`, as described in [Configuration](configuration.md#connector-credentials). Kokoro expects two local assets:

```text
core/weights/kokoro/kokoro-v1.0.onnx
core/weights/kokoro/voices-v1.0.bin
```

Installing the Kokoro extra does not supply those files. Keep model weights out of version control.

A missing optional package, credential, or model file does not prevent APEX from starting. The selected engine reports unavailable, and a speech request attempts the local fallback. If that fallback also fails, delivery reports a failure.

## Engine behavior

| Requested engine | Primary synthesis | Failure fallback |
|---|---|---|
| Google | Google Cloud TTS | local pyttsx3 |
| Kokoro | local Kokoro ONNX | local pyttsx3 |
| pyttsx3 | local pyttsx3 | delivery failure |

A Kokoro request never falls back to Google Cloud TTS. Its text stays local during audio synthesis. Preparing a briefing's highlight script is a separate model call and may use a cloud model; see [Privacy](privacy.md#speech) for that sharing boundary.

## Contextual cues

In automatic voice mode, APEX may speak a short first-person cue when telemetry collection starts and when it finishes, fails, or returns no fresh data. If the refresh will reuse a fresh snapshot, the start cue is skipped because no collection is needed. The result cue can still be spoken.

Briefing cues announce the start, including the profile name, and completion or failure. Spoken highlights have their own preparation completion and failure cues. These announcements apply only to work started in the current page session and are deduplicated for that work. Opening saved sessions, reloading during a run, cancelling, and reading saved highlight status are silent.

Greetings use the local time of day and an optional saved user designation. Cues do not announce engine fallback. They share the speaker lock with other delivery and are best effort: a busy or failed cue does not fail the operation it describes. See the [voice cue API](api.md#post-apiv1voicecue) for the request and response contract.

## Saved briefing highlights

Highlights are derived from one completed, persisted briefing artifact. They do not change the original briefing. Preparation and playback run on one speech worker, separate from the Cortex run workers, whose default capacity is two. That worker accepts one session job at a time rather than queuing additional sessions.

### Script preparation and validation

APEX asks the model captured in the briefing session to write a script using only that artifact. The call has no tools, retrieval, conversation history, or run telemetry. A saved user designation may also be included so the highlights can address the user naturally. The model deadline is the smaller of the session's saved model budget and 240 seconds, shared across the initial call and any repair. Local inference uses the shared admission lock and fails fast if another operation already owns it.

The script is instructed to preserve the artifact's facts and status. The validator checks item references, matching numeric values and date words, required uncertainty and category qualifiers, unsupported completion language for suggestions, and the absence of URLs or citations. These checks do not verify every factual claim. APEX can keep individually valid highlights without another model call. After a numeric mismatch, it may instead read the exact title and body of a model-selected item if that text fits the speech limits and contains no URL or citation.

If those recovery steps do not produce a usable script, APEX allows at most one repair call. Recovered scripts pass the same validator. Detected reference, numeric, date-word, and qualifier mismatches are rejected; preparation remains unavailable if no valid script can be recovered. A model deadline is reported as `speech_model_timeout`, separately from audio failures.

Demo Daily and Catch Up use a deterministic script from the persisted fixture artifact and the `DEMO_TTS` engine, without a model-provider call.

### Audio caching

After validating the script, APEX synthesizes short chunks and stores each separately in SQLite with its audio type and duration. WAV chunks are never concatenated. pyttsx3 exports WAV through a child process with a time limit. Chunk counts, byte sizes, durations, retries, and elapsed time are bounded.

The cache is bound to the exact briefing artifact and records the requested engine, resolved fallback engine, and voice gender. Play retains that prepared voice even if Runtime Settings later change. Prepare reuses a matching cache, rebuilds it after an engine or gender change, and explicitly rebuilds it with the current settings when requested with `?force=true`.

### Playback and stopping

Play sends the ordered cached chunks through the shared `core.speaker` lock. It does not regenerate the script or audio, and it does not stream bytes to the browser. A busy speaker can prevent delivery. Playback has a deadline derived from the stored chunk durations, and cancellation remains responsive while the mixer is active.

Stop cancels only the selected session's job and leaves unrelated speech alone. See the [briefing speech API](api.md#get-apiv1briefing-sessionssessionidspeech) for status, Prepare, Play, and Stop requests.

## Long-text delivery

Direct text delivery through Google or Kokoro normalizes Markdown to Unicode plain text and splits it at sentence boundaries. Very long sentences are split again at a fixed size limit. Valid accented and non-Latin characters are preserved.

This delivery path synthesizes one chunk ahead: the first chunk plays while the next is generated, keeping the queue small. Saved briefing highlights use the separate preparation and caching workflow above; all of their audio is prepared before Play.

## Kokoro resource checks

Kokoro has its own CPU and memory checks:

- RAM at or above 95% causes an immediate fallback to pyttsx3.
- CPU above 80% may be temporary, so APEX waits briefly and requires stable samples at or below the threshold before starting Kokoro.
- If CPU pressure remains high through that window, APEX falls back to pyttsx3.

These checks are separate from the general system scanner and allow a short CPU spike after briefing generation to settle.

## Readiness and cancellation

FastAPI initializes audio and checks Google credentials during startup when Google is selected. Kokoro remains unloaded until a speech request needs it. Importing the module does not load Kokoro or initialize Google Cloud TTS.

Startup readiness tracks audio mixer initialization and Google client setup when selected. Kokoro file checks and model loading happen with the first Kokoro request, which also runs its synthesis path. Optional engine readiness does not guarantee successful delivery, and an unavailable engine does not make the whole API unavailable: `/api/v1/health/ready` represents the core application. A Kokoro session is released after five minutes without active work; a new request loads it again.

Shutdown requests speech cancellation before draining Cortex runs. The speaker stops active mixer playback, attempts to stop pyttsx3, suppresses queued chunks, and ignores late synthesis results. SQLite and the speaker stay open while the briefing speech worker drains within the shared shutdown deadline. APEX then closes embedding and Kokoro sessions within that same remaining deadline before closing the speaker or persistence stores. If any worker or native session does not close in time, shutdown reports an error and leaves those dependencies open.
