# Engineering Decisions

Design rationale, trade-offs, and the history behind key implementation choices.

This document records the major engineering trade-offs behind APEX so the reasoning stays close to the code. It is meant as a durable reference for why certain paths were chosen, what constraints shaped them, and which alternatives remain open for later work.

---

## Configuration

### `.env` vs `config.json` separation

`config.json` holds committed application defaults: which connectors are enabled, the persona prompt, TTS voice settings, and sports sub-module flags. It is committed to version control so the expected configuration shape is visible at a glance and can be modified without touching environment-specific secrets.

`.env` holds secrets: API keys, OAuth tokens, machine-specific paths, and environment-only switches such as `DEV_MODE` / `DEMO_MODE`. It is gitignored.

Keeping them separate means: the defaults are visible in version control, `.env.example` stays focused on secrets without getting cluttered with toggles, and you can change the persona or a feature flag without touching anything near your credentials.

### `config.local.json` as the mutable overlay

Editable operator preferences (briefing connectors, the independent Market poller, sports modules, assistant enablement/default profile, TTS engine/gender) are managed at runtime through `GET` / `PATCH /api/v1/settings`. Patches persist only to gitignored `config.local.json`, which overlays tracked `config.json` defaults. This keeps local machine preference changes out of version control while preserving a readable committed baseline.

`DEV_MODE`, `DEMO_MODE`, and other `.env` switches remain read-only through the settings API and are never written by PATCH.

---

## Backend and API

### SQLite over a flat file

The reminder feature needs read/write with persistent state (marking items as read, returning only unread records). SQLite handles that cleanly with no external dependencies, no process server, and no serialization format to maintain.

### Why the trigger endpoint is synchronous (blocking)

Making the trigger a long-polling synchronous call simplifies the client significantly. There is no need to manage a job ID, poll a separate results endpoint, or handle partial streaming. The trade-off is that the HTTP connection stays open for the full duration of the pipeline (typically 3-10 seconds). This is acceptable for a single-user local tool with no concurrency requirements. The `/api/v1/status` polling loop provides real-time progress feedback without requiring the trigger to stream or chunked-transfer its response.

### Independent runtime paths without removing the full pipeline

APEX activation, telemetry collection, briefing synthesis, assistant access, and voice delivery are separate runtime paths. This lets the HUD come online and remain useful without requiring a briefing, while still allowing each part of the system to be used when it makes sense.

`POST /api/v1/trigger` remains a supported full-pipeline operation, not just a compatibility route. It is still the simplest way to refresh telemetry, synthesize and persist a briefing, and optionally speak it in one request. Keeping it also preserves earlier integrations, but there is no reason to remove a useful direct workflow simply because the same capabilities can now run independently.

The trade-off is that APEX supports both composed and independent paths, so shared behavior must stay in reusable services rather than drifting into separate implementations.

### Telemetry snapshots stay process-local

The current telemetry snapshot lives in memory and represents the HUD's present operational state. It can be refreshed as a whole or updated connector by connector, and a failed refresh keeps the previous healthy result as stale instead of erasing useful information. Briefings, rather than raw snapshots, remain the durable historical record.

This keeps transient connector data out of the database and avoids treating an old machine state as if it were current after APEX restarts. The cost is that snapshot IDs expire with the backend process and cannot provide cross-session context.

That may change as APEX grows into a broader personal AI orchestrator, but persisting the current snapshot object directly would blur live state, history, and memory. Cross-session context should come with explicit rules for retention, privacy, freshness, provenance, and cleanup. A future design may keep the live snapshot temporary while separately storing activity history or selected facts that are genuinely useful as memory.

### Operational preflight warns before it blocks

Environment gating has been part of APEX since its first version. The original scanner required three checks before the briefing pipeline could run: the machine had to be connected to the configured home Wi-Fi, plugged into AC power, and outside the briefing cooldown.

These checks were intended to approximate the context in which APEX was meant to operate:

- The configured Wi-Fi suggested that the device was on the expected home network.
- AC power acted as a rough location signal. It usually meant the device was at its primary workstation rather than being used remotely elsewhere, even within the same house.
- The cooldown prevented repeated briefings and unnecessary API calls.

None of these checks proved that the environment was secure or that the device was physically in a particular location. They were practical signals for a personal tool, not an authentication or security boundary.

That design worked when APEX had one main purpose and every activation launched a complete briefing. It became too restrictive once telemetry collection, assistant access, briefing synthesis, voice delivery, and local-model operations could run independently. A network mismatch or battery state should not prevent the entire HUD from becoming useful.

The same signals now feed advisory preflight warnings. APEX can warn about a configured-network mismatch, unknown network state, battery use, rapid connector refreshes, cloud disclosure, or elevated local-model resource use before an operation begins. These warnings provide context and allow the user to continue when appropriate.

Hard blockers are reserved for conditions that prevent the requested operation from running correctly, such as missing credentials, an unavailable model, local-inference contention, failed CPU or RAM gates, invalid input, or broken configuration and database state. This keeps the original safety and operational intent visible without making a personal local tool unusable whenever its environment differs from the expected setup.

### Speaker state sourced from the backend, not inferred on the frontend

Prior to v1.6.0, `isSpeaking` on the frontend was derived as `isPipelinePolling && activeStep === 4`. This was replaced with a direct `is_speaking` field on the `/api/v1/status` response, backed by `speaker.is_speaking()` which checks `_SPEAK_LOCK` and `pygame.mixer.music.get_busy()`.

The inferred approach had a window where the speaking border and voice-state animations were skipped if the frontend resolved the trigger before polling step 4. Sourcing the value from the backend means the speaker subsystem is the authority on its own state, and the frontend reacts to what is actually happening rather than what it predicted should happen.

### `_speak_and_cleanup` defers pipeline reset until after audio ends

`global_pipeline_state.reset()` is called inside `_speak_and_cleanup` after `speaker.speak()` returns, not at trigger return time. This keeps `is_speaking: true` in `/api/v1/status` responses for the full duration of audio playback, so the frontend's speaking animations remain active until the audio actually finishes rather than ending the moment the HTTP response lands.

### Launcher environment isolation

`launcher.py` gives each child process a different environment. Uvicorn gets the full environment including all `.env` keys. The static file server and browser process each get a stripped copy with only `PATH`, `SYSTEMROOT`, `TEMP`, `TMP`, and `PYTHONPATH`. API keys never reach the browser process.

### Separate liveness and readiness probes

`GET /api/v1/health/live` proves only that the API process can answer a request. `GET /api/v1/health/ready` additionally loads the runtime settings snapshot and executes a lightweight SQLite query, but deliberately excludes optional external providers. The launcher uses readiness, not the compatibility `GET /` route, so a broken local configuration or database prevents the HUD from opening while a connector outage does not make the whole local service unavailable.

### UTC writes with legacy timestamp reads

New run and briefing timestamps are written as timezone-aware UTC ISO-8601 values. Existing timezone-naive run timestamps are interpreted as local wall-clock time when read, preserving cooldown behavior without a destructive migration. The trade-off is a permanent compatibility branch in timestamp parsing; it is preferable to rewriting user data solely to normalize a TEXT field.

### `launch_apex.bat` as a hardware trigger proxy

The long-term intention is a physical button that cold-starts the full system without touching a keyboard. The `.bat` file is the software stand-in: a single-action desktop trigger that maps to the same `launcher.py` execution path a hardware input would eventually call.

---

## AI and Speech

### Why model synthesis over a template

Templated output gets repetitive and requires manual prose changes whenever the briefing evolves. Model synthesis keeps the voice flexible, but raw connector strings are not an acceptable model contract: they mix presentation with health state, make prompt-injection boundaries unclear, and expose more source content than synthesis needs.

Collection therefore normalizes each enabled module into a typed `ConnectorResult`, and synthesis serializes a sanitized, size-bounded `SynthesisInput`. Gemini and Ollama receive the same payload inside `<untrusted_connector_data>` markers; neither receives concatenated display telemetry, assistant tools, or assistant history. The schema requires maintenance when a new fact becomes synthesis-relevant, but that explicit work is the accepted trade-off for predictable privacy and validation. Provider or output-validation failures use deterministic synthesis from the same typed input.

### TTS strategy and fallback design

APEX uses a layered, cascading text-to-speech architecture with Google Cloud TTS as the default primary engine and pyttsx3 as the universal terminal fallback. Kokoro ONNX is available as an optional local engine; when selected, it falls back to Google Cloud TTS on failure, which in turn falls back to pyttsx3.

Clients and models are initialized and pre-warmed at startup. Speech playback is serialized through a dedicated lock to prevent overlapping audio output.

The active engine is controlled by `primary_tts` in `config.json`. Regardless of selection, a briefing is always delivered through the fallback chain.

**Current implementation:**

- Google Cloud TTS (primary cloud engine)
- pyttsx3 (terminal local OS fallback)
- Kokoro ONNX (optional local neural, selected via `primary_tts`; falls back to Google on failure)

### Why local briefing synthesis shares the assistant lifecycle

Local briefing synthesis uses the same Ollama provider, execution lock, model profiles, resource gates, and idle lifecycle as the assistant. There is no benefit in maintaining a second model manager for briefing work when both features compete for the same CPU, RAM, and single loaded-model slot.

The selected local briefing mode is still honored. Lynx, Acinonyx, and Neofelis warm or reuse their corresponding profile instead of silently substituting another resident model. The legacy `local` strategy maps to Acinonyx, which is the balanced local default. Local work does not queue behind another inference request; when the selected model cannot run, briefing synthesis falls back to Structured Digest with a recorded reason.

Shared lifecycle does not mean shared context. Briefing synthesis receives no assistant tools or conversation history, disables thinking, uses a bounded output contract, and sees only sanitized connector facts marked as untrusted evidence. The trade-off is contention between assistant and briefing work, which APEX exposes immediately instead of hiding behind a queue.

### Explicit briefing modes with a deterministic final fallback

APEX exposes five briefing modes so the choice between cloud speed, local resource use, and model-free output is deliberate:

- **Comet** uses Gemini 3.5 Flash Lite for the default fast cloud briefing.
- **Lynx** uses the smallest local profile and keeps its shorter, limited-telemetry prompt.
- **Acinonyx** is the balanced local default and uses the full Comet briefing contract.
- **Neofelis** uses the same full contract with a higher-capacity, slower local model.
- **Structured Digest** produces a model-free briefing directly from typed facts.

An explicitly selected local profile is not silently replaced with a different resident model. Comet may reuse a recognized resident local profile or briefly try Lynx when Gemini fails, but every unsuccessful path ends at Structured Digest. That gives APEX a useful result even when credentials, providers, models, or generated output fail.

All modes start from the same privacy-bounded `SynthesisInput`. Concatenated display telemetry never reaches Gemini or Ollama, and Structured Digest uses the same typed facts without making a model call. The legacy `cloud`, `local`, and `raw` strategy values remain compatibility aliases for Comet, Acinonyx, and Structured Digest respectively.

The extra mode surface requires more profile and fallback coverage, but it keeps the operational and privacy trade-offs visible instead of hiding them behind a single automatic router.

### TTS engine priority restructure: mobile CPU oversubscription and hardware-conditional Kokoro standby

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

---

## Local Inference

### Assistant profile names and model selection

The APEX assistant exposes six named profiles: cloud profiles (`Comet`, `Nova`, `Pulsar`) and local profiles (`Lynx`, `Acinonyx`, `Neofelis`). The codenames follow the broader APEX theme and personal naming style, but their technical purpose is to communicate relative speed, reasoning depth, and resource cost without exposing raw provider model IDs in the UI.

Cloud profiles exist for two reasons. First, the Gemini free tier applies rate limits per underlying model, so keeping multiple cloud profiles available gives APEX a practical fallback path when one model is temporarily constrained. Second, the backing Gemini models have different latency and reasoning characteristics, so the profiles are divided into fast, balanced, and advanced categories instead of treating every cloud call as equivalent.

Local profiles solve a different problem: hardware cost. Running models through Ollama competes directly with the same CPU and RAM needed by the API server, browser, and operating system. Multiple local tiers make it possible to choose a smaller model for quick or resource-constrained queries and reserve heavier models for prompts that justify the extra memory, CPU, and latency.

The current assistant tool set is intentionally small and read-only, so the difference between speed and reasoning depth is not always dramatic. The profile system is still useful now because it establishes the routing contract before the tool surface grows. As APEX gains more complex tool-calling workflows, longer reasoning chains, and higher-impact operations, explicit model selection will matter more: some tasks should prioritize fast interaction, while others should spend more compute for stronger planning and synthesis.

Each profile's `stable`/`preview` label follows a different basis by provider. Cloud profiles take the label directly from the corresponding Gemini model's own release documentation. Local profiles have no equivalent upstream signal, so the label reflects informal confidence from hands-on use. A local profile may stay `preview` even after enough testing elsewhere would call it stable, simply pending more use.

### APEX assistant sessions are stateless on the server

The APEX assistant (`POST /api/v1/agent/query`) does not persist conversation history server-side. The client sends the full message history with every request, and the server appends the new turn and returns the updated response without writing anything to a session store.

This mirrors the project's existing preference for the client owning UI-facing state (see the trigger/polling design) and avoids adding session lifecycle management, expiry, cleanup, and multi-tab conflict handling to a single-user local tool where the browser tab already holds the canonical conversation. The trade-off is that history is lost on page reload and is bounded by `config.json` `ask_apex.max_session_messages` purely as a client-side truncation concern, not a server-enforced limit.

### Local Ollama provider: single loaded model, non-blocking admission, and resource gates

The local agent profiles (Lynx, Acinonyx, Neofelis) share one constraint the cloud profiles do not: they compete directly with the host machine's own CPU and RAM. The design choices in `core/agent/providers/ollama_lifecycle.py` follow from that constraint.

**Single loaded model.** Only one local model is kept resident in Ollama memory at a time. `switch_local_model()` unloads the previous model before loading the next. Running multiple local models concurrently on consumer hardware risks starving the API server and the OS itself; a single-user local tool has no need for concurrent local models, so this restriction costs nothing in practice.

**Non-blocking admission instead of a queue.** `try_begin_local_execution()` claims a single execution slot without blocking; a second concurrent request is rejected with `429` rather than parked in a queue. A queue would let requests silently pile up behind a slow generation with no feedback to the user. An immediate rejection is simpler to reason about and lets the frontend prompt the user to retry.

**Resource gates as RAM/CPU percentage thresholds.** Each local profile defines its own `ram_limit`/`cpu_limit` in `config.json` (heavier models get stricter limits). This is a coarse but dependency-free way to avoid loading a model the host cannot comfortably run, without needing per-model memory-footprint calibration.

**Already-loaded models bypass the resource gate.** If a profile's model is already resident in Ollama, switching to it does not re-check the resource gate, even if host utilization has since risen. The gate exists to prevent a *new* cold load from pushing the system over the edge; a model already occupying memory doesn't consume any additional headroom by being reselected.

**Idle auto-unload, not manual-only cleanup.** `check_idle_models_loop()` runs as an API lifespan background task and unloads a local model after a configurable idle window (`ollama.idle_unload_timeout_minutes`), independent of Ollama's own `keep_alive` eviction. This keeps the resource footprint bounded during long standby periods without requiring the user to remember to unload a model manually. Manual unload remains available for cases where the user wants memory back immediately.

**Thinking output stripped, not surfaced.** `_strip_thinking_tags()` removes `<think>...</think>` blocks from Qwen model output before it reaches the assistant response. Reasoning traces are useful for debugging but are not intended as user-facing conversational text; `think` defaults to `False` in every local profile for the same reason: it costs generation time without a corresponding benefit in the current UI.

---

## Security

### Untrusted tool output boundary in the Cortex engine

Every tool result returned to Gemini during an agent loop turn is wrapped in an `<untrusted_tool_output>` XML tag, and every system instruction sent to the model includes a directive to treat that tag's contents as data, never as instructions.

Live connector data (calendar event titles, news headlines, Gmail subjects) is written by third parties outside APEX's control. Without an explicit boundary, adversarial or malformed text inside that data could be interpreted by the model as a system-level instruction override, a standard prompt-injection risk for any tool-calling agent that ingests external content. Marking tool output as untrusted at the prompt level costs nothing at runtime and requires no additional infrastructure, consistent with the project's preference for simple, dependency-free safeguards.

---

## Development Process

### Agent instructions, scoped guidance, and skills

APEX replaced the earlier nine-persona rule set (`analyst`, `auditor`, `builder`, `communicator`, `devops`, `mechanic`, plus inlined backend/frontend/global content) with a thinner instruction stack. The old model duplicated long personas across `.agents/rules/` and `.cursor/rules/`, required a pre-flight validation block and post-change handoff on every edit, and treated implementation as gated behind a separate sign-off step. That created drift between the two rule surfaces and mixed always-on ceremony with task-specific procedures.

The current stack separates three concerns:

1. **Repository-wide instructions** live in `AGENTS.md`. That file is the single source for project context, working agreement, secrets boundaries, and validation commands. An explicit request to implement or fix something is treated as authorization for in-scope edits; there is no separate always-on approval gate.
2. **Scoped engineering guidance** lives in `docs/agent-guidance/` (`writing.md`, `backend.md`, `frontend.md`, `infrastructure.md`), with visual defaults in `docs/design-system.md`. Thin glob rules in `.agents/rules/` and `.cursor/rules/` point at those documents when matching files are in play, instead of inlining the same prose twice.
3. **Reusable procedures** live in `.agents/skills/`. Skills are loaded only when the task matches; they are not always-on behavior.

Dual editor surfaces remain intentional. Cursor loads `AGENTS.md` as always-on repository instructions, so `.cursor/rules/` keeps only glob-scoped pointers for backend, frontend, and infrastructure work. The Antigravity-oriented `.agents/rules/` surface keeps an `always_on` `global` rule that points at `AGENTS.md`, plus the same three scoped pointers. Guidance content is shared; only the activation wiring differs.

| Surface | Activation | Purpose |
|---|---|---|
| `AGENTS.md` | Always on (Cursor native; `.agents/rules/global.md` for Antigravity) | Project context, working agreement, secrets, validation, pointers to scoped guidance and skills |
| `docs/agent-guidance/writing.md` | Via `AGENTS.md` for documentation and repository communication | Plain-language standards for docs, PRs, changelog, and release notes |
| `docs/agent-guidance/backend.md` | Glob: `core/`, `clients/`, `tests/` Python | FastAPI, async safety, SQLite, contracts, connector trust boundaries |
| `docs/agent-guidance/frontend.md` plus `docs/design-system.md` | Glob: frontend TS/CSS/HTML; design system when visuals change | State ownership (`useApexData()` vs independent flows such as `useMarketData()`), accessibility, responsive layout, HUD visual language |
| `docs/agent-guidance/infrastructure.md` | Glob: config, env, lockfiles, launcher, package manifests | Secrets vs `config.json`, dependencies, `DEV_MODE` / `DEMO_MODE`, launcher behavior |
| `research-feature` | On demand | Evidence-backed research handoff using `docs/agent-handoffs/template.md` |
| `implement-plan` | On demand | Reconcile an approved plan with the repo and implement complete behavior |
| `fix-regression` | On demand | Diagnose, repair, and verify defects with focused regression coverage |
| `review-change` | On demand | Read-only review of a diff or PR, including documentation impact of that change |
| `audit-documentation` | On demand | Evidence-backed documentation drift audit across a range or the full repo |
| `prepare-release` | On demand | Feature PR/merge, milestone changelog, or tag/release phases with explicit approval for external actions |

The trade-off is less persona flavor and less automatic ceremony in exchange for one canonical instruction file, shared guidance that can be updated once, and procedures that load only when needed. Historical changelog entries that mention the nine-rule layout remain accurate as history; they do not describe the current agent configuration.
