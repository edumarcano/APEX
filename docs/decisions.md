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

`DEV_AI_SYNTHESIS=slm` is registered as a valid value and appears in `.env.example` and README documentation. When selected, `brain.py` returns a placeholder string and logs a notice. This placeholder is scoped specifically to briefing synthesis (`brain.py`); it does not describe the state of Ollama integration in APEX as a whole.

Ollama is fully integrated and in production use for the APEX assistant (Cortex agent) via the local Lynx, Acinonyx, and Neofelis profiles — see `core/agent/providers/ollama.py`, `ollama_lifecycle.py`, and `ollama_models.py`. Using a local model to synthesize the periodic briefing itself (the `brain.py` code path controlled by `DEV_AI_SYNTHESIS=slm`) is a separate, still-unimplemented piece of work. Despite Ollama already being integrated for the assistant, routing briefing synthesis through a local model remains planned for a future release.

The `slm` value exists in the config surface now so that the routing contract is established and the `metadata.synthesis_strategy` field in API responses accurately reflects the intended enum (`raw | slm | llm`) without requiring a contract change later.

---

## SQLite over a flat file

The reminder feature needs read/write with persistent state (marking items as read, returning only unread records). SQLite handles that cleanly with no external dependencies, no process server, and no serialization format to maintain.

---

## Multi-tier synthesis fallback strategy

APEX is designed around progressive degradation rather than dependence on a single synthesis path. The primary briefing pipeline uses Gemini for synthesis. A single Gemini API key is sufficient to call multiple Gemini models; model-tier failover is a direction for a future release, not a current implementation.

If the Gemini call fails, APEX falls back to reading raw connector data directly, ensuring a briefing is always delivered. A code placeholder for Ollama-hosted local briefing synthesis exists (`DEV_AI_SYNTHESIS=slm`), but that specific integration has not been implemented. This is distinct from the APEX assistant, where Ollama is already fully integrated (see the local agent profiles in [docs/architecture.md](architecture.md#core-agent--cortex-reasoning-engine-for-the-apex-assistant)). Despite Ollama already being integrated for the assistant, using a local model for briefing synthesis remains planned for the future.

This layered approach prioritizes reliability, offline capability, and graceful degradation.

**Implemented:** Gemini synthesis (Gemini 3.1 Flash Lite), offline raw-data fallback.

**Planned:** Model-tier failover within Gemini, local model synthesis for briefings via Ollama, improved degradation behavior.

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

## APEX assistant sessions are stateless on the server

The APEX assistant (`POST /api/v1/agent/query`) does not persist conversation history server-side. The client sends the full message history with every request, and the server appends the new turn and returns the updated response without writing anything to a session store.

This mirrors the project's existing preference for the client owning UI-facing state (see the trigger/polling design) and avoids adding session lifecycle management, expiry, cleanup, multi-tab conflicts, to a single-user local tool where the browser tab already holds the canonical conversation. The trade-off is that history is lost on page reload and is bounded by `config.json` `ask_apex.max_session_messages` purely as a client-side truncation concern, not a server-enforced limit.

---

## Local Ollama provider: single loaded model, non-blocking admission, and resource gates

The local agent profiles (Lynx, Acinonyx, Neofelis) share one constraint the cloud profiles do not: they compete directly with the host machine's own CPU and RAM. The design choices in `core/agent/providers/ollama_lifecycle.py` follow from that constraint.

**Single loaded model.** Only one local model is kept resident in Ollama memory at a time. `switch_local_model()` unloads the previous model before loading the next. Running multiple local models concurrently on consumer hardware risks starving the API server and the OS itself; a single-user local tool has no need for concurrent local models, so this restriction costs nothing in practice.

**Non-blocking admission instead of a queue.** `try_begin_local_execution()` claims a single execution slot without blocking; a second concurrent request is rejected with `429` rather than parked in a queue. A queue would let requests silently pile up behind a slow generation with no feedback to the user. An immediate rejection is simpler to reason about and lets the frontend prompt the user to retry.

**Resource gates as RAM/CPU percentage thresholds.** Each local profile defines its own `ram_limit`/`cpu_limit` in `config.json` (heavier models get stricter limits). This is a coarse but dependency-free way to avoid loading a model the host cannot comfortably run, without needing per-model memory-footprint calibration.

**Already-loaded models bypass the resource gate.** If a profile's model is already resident in Ollama, switching to it does not re-check the resource gate, even if host utilization has since risen. The gate exists to prevent a *new* cold load from pushing the system over the edge; a model already occupying memory doesn't consume any additional headroom by being reselected.

**Idle auto-unload, not manual-only cleanup.** `check_idle_models_loop()` runs as an API lifespan background task and unloads a local model after a configurable idle window (`ollama.idle_unload_timeout_minutes`), independent of Ollama's own `keep_alive` eviction. This keeps the resource footprint bounded during long standby periods without requiring the user to remember to unload a model manually. Manual unload remains available for cases where the user wants memory back immediately.

**Thinking output stripped, not surfaced.** `_strip_thinking_tags()` removes `<think>...</think>` blocks from Qwen model output before it reaches the assistant response. Reasoning traces are useful for debugging but are not intended as user-facing conversational text; `think` defaults to `False` in every local profile for the same reason — it costs generation time without a corresponding benefit in the current UI.

---

## Untrusted tool output boundary in the Cortex engine

Every tool result returned to Gemini during an agent loop turn is wrapped in an `<untrusted_tool_output>` XML tag, and every system instruction sent to the model includes a directive to treat that tag's contents as data, never as instructions.

Live connector data (calendar event titles, news headlines, Gmail subjects) is written by third parties outside APEX's control. Without an explicit boundary, adversarial or malformed text inside that data could be interpreted by the model as a system-level instruction override, a standard prompt-injection risk for any tool-calling agent that ingests external content. Marking tool output as untrusted at the prompt level costs nothing at runtime and requires no additional infrastructure, consistent with the project's preference for simple, dependency-free safeguards.

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

---

## TTS engine priority restructure: mobile CPU oversubscription and hardware-conditional Kokoro standby

APEX v1.10.0 integrated Kokoro ONNX and Piper CLI as candidates for a fully local, zero-API-cost voice engine. Both were benchmarked on an Intel Core Ultra 7 (Lunar Lake) mobile hybrid processor. Kokoro produced unacceptable latency under that specific hardware profile; Piper was subsequently pruned from the codebase. Kokoro itself remains fully integrated and operational.

**Root cause of latency on mobile x86**

`onnxruntime`'s CPU execution provider has no native SIMD matrix acceleration on hybrid mobile architectures (no AVX-512 support). Its thread pool defaults to active spin-waiting, which caused it to compete directly with the FastAPI event loop for time on the same physical cores. This produced core oversubscription and context-switching thrash at the OS scheduler level. Measured impact on Lunar Lake: Kokoro required over 40 seconds of silence before producing audio for a 420-character briefing. Piper required approximately 16 seconds of pre-speech calculation. Neither met the sub-5-second threshold required for conversational HUD use on that hardware.

**Resolution**

The engine priority order was restructured to protect system resources on thin-and-light mobile x86 hardware while preserving Kokoro as a fully active engine on capable hardware:

- **Google Cloud TTS** was restored as the active primary engine. It operates at sub-3-second end-to-end latency, imposes zero local CPU load, and produces quality consistent with the original design intent.
- **pyttsx3** (Windows SAPI5) was retained as the immediate local fallback. It starts speaking instantly, requires no configuration, and consumes no measurable CPU at rest.
- **Kokoro ONNX** was placed on hardware-conditional cold standby. When `primary_tts` is set to any engine other than `"kokoro"`, its Python imports are lazy-loaded and its background warmup thread is bypassed at boot, consuming 0 MB of RAM and 0 threads. When `primary_tts: "kokoro"` is set, as intended on hardware with dedicated ONNX acceleration such as Apple Silicon (Metal/CoreML) or an NVIDIA-equipped desktop (CUDA/TensorRT), the warmup thread activates automatically and the engine is expected to run at full neural synthesis speed. Kokoro is a supported, production-ready engine; its standby classification is a hardware-scoped default, not a deprecation.
- **Piper CLI** was removed from disk entirely to eliminate binary bloat and reduce the local engine maintenance surface. With Kokoro retained as the capable neural alternative, Piper provided no remaining value. A SemVer-safe redirect was added inside `speaker.py`: any `"piper"` value in `primary_tts` silently resolves to `"pyttsx3"` with a logged warning, preserving forward compatibility with existing config files.

**Trade-offs accepted**

Google Cloud TTS requires a live API key and network access. The pyttsx3 fallback covers offline and credential-failure scenarios but produces lower voice quality than any neural engine. On mobile x86, Kokoro's cold standby eliminates its resource footprint at the cost of not using local neural synthesis by default. On hardware where ONNX acceleration is available, setting `primary_tts: "kokoro"` in `config.json` restores full local neural synthesis with no other changes required.
