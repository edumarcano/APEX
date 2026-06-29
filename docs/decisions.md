# Engineering Decisions

Design rationale, trade-offs, and the history behind key implementation choices.

---

## `.env` vs `config.json` separation

`config.json` holds application state: which connectors are enabled, the persona prompt, TTS voice settings, and sports sub-module flags. It is committed to version control so the expected configuration shape is visible at a glance and can be modified without touching environment-specific secrets.

`.env` holds secrets: API keys, OAuth tokens, machine-specific paths. It is gitignored.

Keeping them separate means: the defaults are visible in version control, `.env.example` stays focused on secrets without getting cluttered with toggles, and you can change the persona or a feature flag without touching anything near your credentials.

---

## Why Gemini over a template

Templated output gets repetitive fast and requires manual updates whenever a data source changes its format or a new connector is added. Passing raw connector strings to the model and letting it handle sentence construction is simpler and more resilient to upstream format changes. The `system_prompt` field in `config.json` fully controls the voice and style without touching any Python.

---

## TTS strategy and fallback design

APEX uses a layered, cascading text-to-speech architecture with Google Cloud TTS as the default primary engine and pyttsx3 as the universal terminal fallback. Kokoro ONNX is available as an optional local engine; when selected, it falls back to Google Cloud TTS on failure, which in turn falls back to pyttsx3.

Clients and models are initialized and pre-warmed at startup. Speech playback is serialized through a dedicated lock to prevent overlapping audio output.

The active engine is controlled by `primary_tts` in `config.json`. Regardless of selection, a briefing is always delivered through the fallback chain.

**Current implementation:**

- Google Cloud TTS (primary cloud engine)
- pyttsx3 (terminal local OS fallback)
- Kokoro ONNX (optional local neural — selected via `primary_tts`; falls back to Google on failure)

---

## Why `DEV_AI_SYNTHESIS=slm` is a placeholder

`DEV_AI_SYNTHESIS=slm` is registered as a valid value and appears in `.env.example` and README documentation. When selected, `brain.py` returns a placeholder string and logs a notice. Local SLM routing via Ollama (planned model: `llama3.2:3b`) has not been implemented.

The value exists in the config surface now so that the routing contract is established and the `metadata.synthesis_strategy` field in API responses accurately reflects the intended enum (`raw | slm | llm`) without requiring a contract change later.

---

## SQLite over a flat file

The reminder feature needs read/write with persistent state (marking items as read, returning only unread records). SQLite handles that cleanly with no external dependencies, no process server, and no serialization format to maintain.

---

## Multi-tier synthesis fallback strategy

APEX is designed around progressive degradation rather than dependence on a single synthesis path. The primary briefing pipeline uses Gemini for synthesis. A single Gemini API key is sufficient to call multiple Gemini models; model-tier failover is a direction for a future release, not a current implementation.

If the Gemini call fails, APEX falls back to reading raw connector data directly, ensuring a briefing is always delivered. A code placeholder for Ollama-hosted local synthesis exists (`DEV_AI_SYNTHESIS=slm`), but local SLM integration has not been implemented.

This layered approach prioritizes reliability, offline capability, and graceful degradation.

**Implemented:** Gemini synthesis (Gemini 3.1 Flash Lite), offline raw-data fallback.

**Planned:** Model-tier failover within Gemini, local SLM synthesis via Ollama, improved degradation behavior.

---

## Why the trigger endpoint is synchronous (blocking)

Making the trigger a long-polling synchronous call simplifies the client significantly. There is no need to manage a job ID, poll a separate results endpoint, or handle partial streaming. The trade-off is that the HTTP connection stays open for the full duration of the pipeline (typically 3–10 seconds). This is acceptable for a single-user local tool with no concurrency requirements. The `/api/v1/status` polling loop provides real-time progress feedback without requiring the trigger to stream or chunked-transfer its response.

---

## Speaker state sourced from the backend, not inferred on the frontend

Prior to v1.6.0, `isSpeaking` on the frontend was derived as `isPipelinePolling && activeStep === 4`. This was replaced with a direct `is_speaking` field on the `/api/v1/status` response, backed by `speaker.is_speaking()` which checks `_SPEAK_LOCK` and `pygame.mixer.music.get_busy()`.

The inferred approach had a window where the speaking border and `VocalOrb` animations were skipped if the frontend resolved the trigger before polling step 4. Sourcing the value from the backend means the speaker subsystem is the authority on its own state, and the frontend reacts to what is actually happening rather than what it predicted should happen.

---

## `_speak_and_cleanup` defers pipeline reset until after audio ends

`global_pipeline_state.reset()` is called inside `_speak_and_cleanup` after `speaker.speak()` returns, not at trigger return time. This keeps `is_speaking: true` in `/api/v1/status` responses for the full duration of audio playback, so the frontend's speaking animations remain active until the audio actually finishes rather than ending the moment the HTTP response lands.

---

## Launcher environment isolation

`launcher.py` gives each child process a different environment. Uvicorn gets the full environment including all `.env` keys. The static file server and browser process each get a stripped copy with only `PATH`, `SYSTEMROOT`, `TEMP`, `TMP`, and `PYTHONPATH`. API keys never reach the browser process.

---

## `launch_apex.bat` as a hardware trigger proxy

The long-term intention is a physical button that cold-starts the full system without touching a keyboard. The `.bat` file is the software stand-in: a single-action desktop trigger that maps to the same `launcher.py` execution path a hardware input would eventually call.

---

## AI-Augmented Development Workflow

The project maintains a set of specialized agent rules to provide task-focused guidance across backend development, frontend development, operations, implementation, analysis, auditing, and documentation work.

Multiple rule formats exist to support the AI-assisted development environments used by the project. Depending on the environment, rules may be activated automatically based on context, selected explicitly by the developer, or used as part of agent-specialization workflows.

The responsibilities of each rule are summarized below.

| Rule | Activation | Role |
|---|---|---|
| `global` | automatic | Port constants, full code articulation, pre-flight validation gate, post-implementation handoff section, documentation language standards |
| `analyst` | contextual | API parameter mapping, nested JSON payload tracing, package ecosystem evaluation, mathematical logic analysis. Read-only — never modifies code |
| `auditor` | manual | Security and stability audits: thread races, deadlocks, blocking async calls, resource leaks, secrets isolation, SQLite transaction safety, documentation accuracy |
| `backend` | contextual | FastAPI routes, async orchestration, SQLite persistence, N+1 elimination, bounded retries, explicit timeout handling |
| `builder` | manual | Complete production-ready implementations after explicit sign-off. No placeholder scaffolding |
| `communicator` | manual | PR descriptions, merge summaries, release notes, repository documentation |
| `devops` | contextual | Launchers, dependency lockfiles, configuration management, environment boundaries |
| `frontend` | contextual | HUD layout, Vite/React/TypeScript/Tailwind, unified `useApexData()` hook contract, no per-component loading spinners |
| `mechanic` | manual | Compile-time failures, runtime crashes, typing conflicts, test suite generation |
